"""An agent on the signed-in CLI accepts, rejects and rates as the person signed in: no delegation, code or approval."""
import pytest


def recorder(sent, answer_field, answer):
    def graphql(query, variables):
        sent.append((query, variables))
        return {answer_field: {"ok": True, "referenceId": variables["referenceId"], **answer(variables)}}
    return graphql


def test_approve_without_a_delegation_sends_the_signed_in_persons_accept(capsys):
    from papyrus_content.references_commands import references_record_on_behalf_of

    sent = []
    graphql = recorder(sent, "reviewReferenceCuration", lambda v: {"action": v["action"], "status": "accepted", "reasonCode": None})
    references_record_on_behalf_of(["--reference", "reference-1", "--agent", "Claude"], action="approve", graphql=graphql)
    (query, variables), = sent
    assert "reviewReferenceCuration" in query and "delegation" not in query.lower()
    assert variables["action"] == "accept" and variables["agentLabel"] == "Claude"
    assert "accepted" in capsys.readouterr().out


def test_reject_needs_words_or_a_code_and_sends_them():
    from papyrus_content.references_commands import references_record_on_behalf_of

    with pytest.raises(ValueError):
        references_record_on_behalf_of(["--reference", "reference-1"], action="reject", graphql=lambda *_: {})
    sent = []
    graphql = recorder(sent, "reviewReferenceCuration", lambda v: {"action": v["action"], "status": "rejected", "reasonCode": None})
    references_record_on_behalf_of(["--reference", "reference-1", "--note", "Off topic for this desk."], action="reject", graphql=graphql)
    (_, variables), = sent
    assert variables["action"] == "reject" and variables["note"] == "Off topic for this desk." and variables["agentLabel"] is None


def test_set_stars_without_a_delegation_rates_as_the_person_and_can_clear(capsys):
    from papyrus_content.references_commands import references_set_stars_on_behalf_of

    sent = []
    graphql = recorder(sent, "setReferenceStars", lambda v: {"stars": v["stars"], "status": "pending"})
    references_set_stars_on_behalf_of(["--reference", "reference-1", "--stars", "4", "--agent", "Claude"], graphql=graphql)
    references_set_stars_on_behalf_of(["--reference", "reference-1", "--stars", "clear"], graphql=graphql)
    assert [(v["stars"], v["agentLabel"]) for _, v in sent] == [(4, "Claude"), (None, None)]
    assert all("setReferenceStars" in query for query, _ in sent)


def test_dry_run_and_bad_ratings_send_nothing(capsys):
    from papyrus_content.references_commands import references_record_on_behalf_of, references_set_stars_on_behalf_of

    def refuse(*_):
        raise AssertionError("nothing should be sent")

    references_set_stars_on_behalf_of(["--reference", "reference-1", "--stars", "5", "--dry-run"], graphql=refuse)
    references_record_on_behalf_of(["--reference", "reference-1", "--dry-run"], action="approve", graphql=refuse)
    assert capsys.readouterr().out.count("dry-run: nothing sent") == 2
    for stars in ("0", "6", "x"):
        with pytest.raises(ValueError):
            references_set_stars_on_behalf_of(["--reference", "reference-1", "--stars", stars], graphql=refuse)
