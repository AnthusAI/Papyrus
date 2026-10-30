"""A person's accept can carry the newsroom Section on the Reference; nothing else teaches a section."""
import pytest

from papyrus_content.relevance_decisions import human_section_for_review
from papyrus_newsroom.reference_actions import review_reference_curation

SECTION_IDS = ["section-research", "section-policy"]
ACCEPTED_REFERENCE = {"id": "reference-1", "curationStatus": "accepted"}


def voted(status="accepted", **fields):
    """A Reference with its latest vote recorded on it, as a vote leaves it."""
    return {**ACCEPTED_REFERENCE, "curationStatus": status, "curationStatusUpdatedAt": "2026-10-29T10:00:00Z",
            "curationStatusUpdatedBy": "editor@example.org", **fields}


def test_an_explicit_human_accept_with_a_known_section_gives_that_section():
    reference = voted(curationActorKind="human", curationSectionId="section-policy")
    assert human_section_for_review(reference, SECTION_IDS) == "section-policy"


def test_a_delegated_accept_counts_as_human():
    reference = voted(curationActorKind="human", curationSectionId="section-research",
                      curationDelegation='{"delegationId": "d1", "relayedBy": "agent", "instruction": "yes"}')
    assert human_section_for_review(reference, SECTION_IDS) == "section-research"


@pytest.mark.parametrize("actor_kind", ["agent", "cyclotron", "rule", "catalog", None])
def test_agents_and_unknown_actors_never_produce_a_section(actor_kind):
    reference = voted(curationSectionId="section-research", **({"curationActorKind": actor_kind} if actor_kind else {}))
    assert human_section_for_review(reference, SECTION_IDS) is None


def test_an_unknown_or_missing_section_gives_none():
    assert human_section_for_review(voted(curationActorKind="human", curationSectionId="gone"), SECTION_IDS) is None
    assert human_section_for_review(voted(curationActorKind="human"), SECTION_IDS) is None
    assert human_section_for_review(ACCEPTED_REFERENCE, SECTION_IDS) is None


def test_only_the_latest_vote_counts():
    # A later reject replaces the vote: the Reference keeps only its latest vote.
    rejected = voted("rejected", curationActorKind="human")
    assert human_section_for_review(rejected, SECTION_IDS) is None


def test_a_reference_that_is_not_accepted_gives_none():
    reference = voted("pending", curationActorKind="human", curationSectionId="section-research")
    assert human_section_for_review(reference, SECTION_IDS) is None


def recording_graphql(section, created):
    reference = {"id": "reference-1", "lineageId": "reference-1", "corpusId": "corpus", "title": "T"}

    def graphql(query, variables):
        if "getReference(" in query:
            return {"getReference": reference}
        if "getNewsroomSection" in query:
            return {"getNewsroomSection": section}
        created.append((query, variables))
        return {"updateReference": {"id": "reference-1"}}
    return graphql


def test_review_curation_refuses_an_unknown_section_before_writing():
    created = []
    with pytest.raises(ValueError, match="not found"):
        review_reference_curation(recording_graphql(None, created), reference_id="reference-1", action="accept",
                                  section_id="section-missing")
    assert created == []


def test_review_curation_refuses_a_disabled_section_before_writing():
    created = []
    section = {"id": "section-research", "enabled": False, "enabledStatus": "disabled"}
    with pytest.raises(ValueError, match="disabled"):
        review_reference_curation(recording_graphql(section, created), reference_id="reference-1", action="accept",
                                  section_id="section-research")
    assert created == []


def test_a_section_is_refused_on_a_rejection():
    with pytest.raises(ValueError, match="only when accepting"):
        review_reference_curation(recording_graphql(None, []), reference_id="reference-1", action="reject",
                                  reason_code="out_of_scope", section_id="section-research")


def test_review_curation_records_an_enabled_section_on_the_reference_and_writes_no_message():
    created = []
    section = {"id": "section-research", "enabled": True, "enabledStatus": "enabled"}
    result = review_reference_curation(recording_graphql(section, created), reference_id="reference-1", action="accept",
                                       section_id="section-research")
    assert result["sectionId"] == "section-research"
    (query, variables), = created
    assert "updateReference" in query
    assert variables["input"]["curationSectionId"] == "section-research"
    assert variables["input"]["curationActorKind"] == "agent"
    assert not any("createMessage" in q or "createSemanticRelation" in q for q, _ in created)
