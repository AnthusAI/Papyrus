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
