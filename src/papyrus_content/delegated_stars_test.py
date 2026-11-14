"""An agent on the signed-in CLI relays a person's accept, reject and star rating under a delegation they approved (PPY-05f412)."""
import json

import pytest

TOKEN = "curation-delegation-1~secret"
RELAY = ["--reference", "reference-1", "--on-behalf-of", "editor@example.org", "--agent", "Claude", "--instruction", "Give it four stars."]


def stars_graphql(sent):
    def graphql(query, variables):
        sent.append((query, variables))
        return {"recordDelegatedStars": {"ok": True, "referenceId": variables["referenceId"], "stars": variables["stars"], "status": "accepted"}}
    return graphql


def test_the_approve_word_records_an_accept(monkeypatch, tmp_path):
    from papyrus_content import references_commands

    token_file = tmp_path / "token"
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    sent = []

    class FakeClient:
        @staticmethod
        def graphql(query, variables):
            sent.append((query, variables))
            return {"recordDelegatedCuration": {"ok": True, "referenceId": variables["referenceId"], "status": "accepted"}}

    monkeypatch.setattr(references_commands, "create_authoring_client", lambda: (FakeClient(), None))
    monkeypatch.delenv("PAPYRUS_DELEGATION_TOKEN", raising=False)
    references_commands.references_record_on_behalf_of([*RELAY, "--delegation-file", str(token_file)], action="approve")
    (_, variables), = sent
    assert variables["action"] == "accept"


def test_a_relayed_rating_sends_the_token_the_agent_and_the_person(tmp_path, capsys):
    from papyrus_content.references_commands import references_set_stars_on_behalf_of

    token_file = tmp_path / "token"
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    sent = []
    references_set_stars_on_behalf_of([*RELAY, "--stars", "4", "--delegation-file", str(token_file)], graphql=stars_graphql(sent))
    (query, variables), = sent
    assert "recordDelegatedStars" in query
    assert variables == {"referenceId": "reference-1", "stars": 4, "delegationId": "curation-delegation-1", "delegationToken": TOKEN,
                         "agentLabel": "Claude", "onBehalfOf": "editor@example.org", "instruction": "Give it four stars."}
    printed = capsys.readouterr().out
    assert printed.strip() == "references\tset-stars\treference-1\t4\taccepted\ton behalf of editor@example.org via Claude"
    assert "secret" not in printed


def test_a_relayed_rating_can_be_cleared(capsys):
    from papyrus_content.references_commands import references_set_stars_on_behalf_of

    sent = []
    references_set_stars_on_behalf_of([*RELAY, "--stars", "clear", "--delegation-token", TOKEN], graphql=stars_graphql(sent))
    assert sent[0][1]["stars"] is None
    assert "\tclear\t" in capsys.readouterr().out


@pytest.mark.parametrize("stars", ["0", "6", "2.5", "many", "-1"])
def test_a_rating_outside_one_to_five_is_refused_before_anything_is_sent(stars):
    from papyrus_content.references_commands import references_set_stars_on_behalf_of

    sent = []
    with pytest.raises(ValueError, match="1 to 5"):
        references_set_stars_on_behalf_of([*RELAY, "--stars", stars, "--delegation-token", TOKEN], graphql=stars_graphql(sent))
    assert sent == []


def test_a_rating_needs_stars_and_a_delegation(monkeypatch):
    from papyrus_content.references_commands import references_set_stars_on_behalf_of

    monkeypatch.delenv("PAPYRUS_DELEGATION_TOKEN", raising=False)
    with pytest.raises(ValueError, match="--stars"):
        references_set_stars_on_behalf_of([*RELAY, "--delegation-token", TOKEN], graphql=stars_graphql([]))
    with pytest.raises(ValueError, match="delegation-file"):
        references_set_stars_on_behalf_of([*RELAY, "--stars", "3"], graphql=stars_graphql([]))


def test_a_dry_run_rating_and_help_send_nothing_and_do_not_even_sign_in(monkeypatch, capsys):
    from papyrus_content import references_commands
    from papyrus_content.references_commands import references_set_stars_on_behalf_of

    def no_client():
        raise AssertionError("a dry run must not build a client")

    monkeypatch.setattr(references_commands, "create_authoring_client", no_client)
    references_set_stars_on_behalf_of([*RELAY, "--stars", "4", "--delegation-token", TOKEN, "--dry-run"])
    assert "dry-run: nothing sent" in capsys.readouterr().out
    references_set_stars_on_behalf_of(["--help"])
    assert "--stars <1-5|clear>" in capsys.readouterr().out
    with pytest.raises(ValueError, match="no longer accepts --apply"):
        references_set_stars_on_behalf_of([*RELAY, "--stars", "4", "--delegation-token", TOKEN, "--apply"])


class FakeResponse:
    status, reason = 200, "OK"

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body.encode()


class FakeConnection:
    """Stands in for the HTTPS connection of the real GraphQL client, so the headers it would send can be read."""

    def __init__(self, answer, seen):
        self.answer, self.seen = answer, seen

    def request(self, method, path, body=None, headers=None):
        self.seen.append({"method": method, "body": json.loads(body), "headers": dict(headers)})

    def getresponse(self):
        return FakeResponse(json.dumps({"data": self.answer(self.seen[-1]["body"])}))


def test_on_the_signed_in_lane_the_request_and_the_relay_go_with_the_session_token_and_never_aws_credentials(tmp_path, monkeypatch, capsys):
    from papyrus_content import references_commands
    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient

    seen = []

    def answer(body):
        query = body["query"]
        if "requestCurationDelegation" in query:
            return {"requestCurationDelegation": {"ok": True, "delegationId": body["variables"]["delegationId"], "userCode": "ABCD-2345",
                                                  "pendingExpiresAt": "2026-11-04T12:10:00.000Z", "requestedHours": 2}}
        if "recordDelegatedStars" in query:
            return {"recordDelegatedStars": {"ok": True, "referenceId": body["variables"]["referenceId"], "stars": 4, "status": "accepted"}}
        return {"recordDelegatedCuration": {"ok": True, "referenceId": body["variables"]["referenceId"], "status": "accepted"}}

    client = PapyrusGraphQLAuthoringClient(
        endpoint="https://api.example.test/graphql", tenant_id=None, site_tenant=False,
        header_factory=lambda body: {"content-type": "application/json", "Authorization": "id-token-of-the-session"})
    client._connection = FakeConnection(answer, seen)
    token_file = tmp_path / "token"
    references_commands.references_request_delegation(["--agent", "Claude", "--hours", "2", "--token-file", str(token_file)], graphql=client.graphql)
    # The delegation file holds the secret made by the request; the relays below read it back.
    monkeypatch.setattr(references_commands, "create_authoring_client", lambda: (client, None))
    arguments = [*RELAY, "--delegation-file", str(token_file)]
    references_commands.references_record_on_behalf_of(arguments, action="approve")
    references_commands.references_record_on_behalf_of([*arguments, "--reason-code", "duplicate"], action="reject")
    references_commands.references_set_stars_on_behalf_of([*arguments, "--stars", "4"])
    operations = [request["body"]["query"].split("(")[0].split()[-1] for request in seen]
    assert operations == ["RequestCurationDelegation", "RecordDelegatedCuration", "RecordDelegatedCuration", "RecordDelegatedStars"]
    assert seen[0]["body"]["variables"]["hours"] == 2
    assert all(request["headers"]["Authorization"] == "id-token-of-the-session" for request in seen)
    assert not any(key.lower().startswith("x-amz") for request in seen for key in request["headers"])
    assert all("approveCurationDelegation" not in request["body"]["query"] for request in seen), "the CLI has no way to approve a delegation"
    assert "Only a person in the Newsroom can approve it" in capsys.readouterr().out
