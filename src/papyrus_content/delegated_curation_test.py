"""The agent side of recording a person's decision with a delegation they granted."""
import pytest

from papyrus_newsroom.reference_actions import delegation_id_from_token, record_delegated_curation

TOKEN = "curation-delegation-1~secret"


def recording_graphql(sent):
    def graphql(query, variables):
        sent.append((query, variables))
        return {"recordDelegatedCuration": {"ok": True, "referenceId": variables["referenceId"], "status": "accepted"}}
    return graphql


def test_the_delegation_id_travels_inside_the_token():
    assert delegation_id_from_token(TOKEN) == "curation-delegation-1"
    with pytest.raises(ValueError, match="not a delegation token"):
        delegation_id_from_token("secret-only")


def test_a_relayed_approval_sends_the_token_the_agent_and_the_named_person():
    sent = []
    result = record_delegated_curation(recording_graphql(sent), reference_id="reference-1", action="accept",
                                       delegation_token=TOKEN, agent_label="ChatGPT",
                                       on_behalf_of="editor@example.org", instruction="Approve that one, it is core.",
                                       note="Core topic.")
    assert result["status"] == "accepted"
    (query, variables), = sent
    assert "recordDelegatedCuration" in query
    assert variables == {"referenceId": "reference-1", "action": "accept", "delegationId": "curation-delegation-1",
                         "delegationToken": TOKEN, "agentLabel": "ChatGPT", "onBehalfOf": "editor@example.org",
                         "instruction": "Approve that one, it is core.",
                         "note": "Core topic.", "reasonCode": None, "sectionId": None}


def test_a_delegation_never_records_anything_but_accept_or_reject():
    for action in ("reopen", "archive"):
        with pytest.raises(ValueError, match="only accept or reject"):
            record_delegated_curation(recording_graphql([]), reference_id="r", action=action, delegation_token=TOKEN,
                                      agent_label="ChatGPT", on_behalf_of="editor@example.org", instruction="x")


def test_a_relayed_approval_can_name_the_newsroom_section():
    sent = []
    record_delegated_curation(recording_graphql(sent), reference_id="reference-1", action="accept",
                              delegation_token=TOKEN, agent_label="ChatGPT", on_behalf_of="editor@example.org",
                              instruction="Approve it for Research.", section_id="newsroom-section-research")
    (_, variables), = sent
    assert variables["sectionId"] == "newsroom-section-research"


def device_authorization_graphql(sent, states):
    remaining = list(states)

    def graphql(query, variables):
        sent.append((query, variables))
        if "requestCurationDelegation" in query:
            return {"requestCurationDelegation": {"ok": True, "delegationId": variables["delegationId"],
                                                  "userCode": "ABCD-2345", "pendingExpiresAt": "2026-10-18T12:10:00.000Z",
                                                  "requestedHours": variables["hours"] or 8}}
        state = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return {"getCurationDelegationStatus": {"delegationId": variables["delegationId"], "state": state,
                                                "expiresAt": "2026-10-18T20:00:00.000Z", "grantorLabel": "editor@example.org"}}
    return graphql


def test_a_requested_delegation_keeps_its_secret_in_a_private_file_and_prints_only_the_code(tmp_path, capsys):
    import hashlib
    import os
    import stat
    from papyrus_content.references_commands import references_request_delegation

    sent = []
    token_file = tmp_path / "private" / "delegation.token"
    references_request_delegation(["--agent", "curator", "--hours", "4", "--token-file", str(token_file)],
                                  graphql=device_authorization_graphql(sent, ["pending"]))
    token = token_file.read_text(encoding="utf-8")
    assert stat.S_IMODE(os.stat(token_file).st_mode) == 0o600
    delegation_id, _, secret = token.partition("~")
    assert delegation_id.startswith("curation-delegation-") and len(secret) >= 24
    (query, variables), = sent
    assert variables == {"delegationId": delegation_id, "tokenHash": hashlib.sha256(token.encode()).hexdigest(),
                         "agentLabel": "curator", "hours": 4}
    assert secret not in str(variables)
    printed = capsys.readouterr()
    assert "ABCD-2345" in printed.out and "approve code" in printed.out
    assert secret not in printed.out + printed.err and token not in printed.out + printed.err


def test_the_default_token_file_lives_under_the_config_directory_with_private_mode(tmp_path, monkeypatch, capsys):
    import os
    import stat
    from papyrus_content.references_commands import references_request_delegation

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    references_request_delegation(["--agent", "curator"], graphql=device_authorization_graphql([], ["pending"]))
    (written,) = (tmp_path / "papyrus" / "delegations").glob("*.token")
    assert stat.S_IMODE(os.stat(written).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(written.parent).st_mode) == 0o700


def test_waiting_polls_until_a_person_approves(tmp_path, capsys):
    from papyrus_content.references_commands import references_request_delegation

    sent, naps = [], []
    references_request_delegation(["--agent", "curator", "--wait", "--token-file", str(tmp_path / "t")],
                                  graphql=device_authorization_graphql(sent, ["pending", "pending", "approved"]),
                                  sleep=naps.append, poll_interval_seconds=2.0)
    assert naps == [2.0, 2.0]
    assert len([query for query, _ in sent if "getCurationDelegationStatus" in query]) == 3
    assert "approved" in capsys.readouterr().out


@pytest.mark.parametrize("state", ["denied", "expired", "revoked"])
def test_waiting_ends_with_an_error_when_the_request_is_not_approved(tmp_path, state):
    from papyrus_content.references_commands import references_request_delegation

    with pytest.raises(ValueError, match=state):
        references_request_delegation(["--agent", "curator", "--wait", "--token-file", str(tmp_path / "t")],
                                      graphql=device_authorization_graphql([], ["pending", state]),
                                      sleep=lambda _: None)


def test_waiting_gives_up_after_the_timeout(tmp_path):
    from papyrus_content.references_commands import references_request_delegation

    with pytest.raises(ValueError, match="Timed out"):
        sent = []
        graphql = device_authorization_graphql(sent, ["pending"])
        references_request_delegation(["--agent", "curator", "--wait", "--token-file", str(tmp_path / "t")],
                                      graphql=graphql, sleep=lambda _: None, timeout_seconds=0.0)


def test_a_request_without_an_agent_is_refused():
    from papyrus_content.references_commands import references_request_delegation

    with pytest.raises(ValueError, match="--agent"):
        references_request_delegation([], graphql=device_authorization_graphql([], ["pending"]))


def test_a_decision_can_read_its_token_from_a_file_without_echoing_it(tmp_path, monkeypatch, capsys):
    from papyrus_content import references_commands

    token_file = tmp_path / "token"
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    sent = []

    class FakeClient:
        graphql = staticmethod(recording_graphql(sent))

    monkeypatch.setattr(references_commands, "create_authoring_client", lambda: (FakeClient(), None))
    monkeypatch.delenv("PAPYRUS_DELEGATION_TOKEN", raising=False)
    references_commands.references_record_on_behalf_of(
        ["--reference", "reference-1", "--on-behalf-of", "editor@example.org", "--agent", "ChatGPT",
         "--instruction", "Approve it.", "--delegation-file", str(token_file)], action="accept")
    (_, variables), = sent
    assert variables["delegationToken"] == TOKEN
    assert "secret" not in capsys.readouterr().out
