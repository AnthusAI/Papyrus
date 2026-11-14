"""The vote backfill copies each Reference's latest vote from its old curation Message onto the Reference."""
import json

from papyrus_content import reference_vote_backfill as backfill
from papyrus_content.reference_vote import latest_vote


class FakeClient:
    def __init__(self, references, messages=(), relations=()):
        self.references = {row["id"]: dict(row) for row in references}
        self.messages = {row["id"]: dict(row) for row in messages}
        self.relations = list(relations)
        self.updates = []

    def list_records(self, model):
        assert model == "Reference"
        return list(self.references.values())

    def list_by_index(self, index, key):
        if index == "semanticRelationsByObjectState":
            return [relation for relation in self.relations if relation["objectStateKey"] == key]
        return []   # no metadata attachments

    def get_record(self, model, record_id):
        assert model == "Message"
        return self.messages.get(record_id)

    def update_record(self, model, payload):
        assert model == "Reference"
        self.updates.append(payload)
        self.references[payload["id"]].update(payload)


def reference(lineage, **fields):
    return {"id": f"{lineage}-v1", "lineageId": lineage, "versionState": "current", "curationStatus": "accepted",
            "curationStatusUpdatedAt": "2026-10-10T00:00:00Z", "curationStatusUpdatedBy": "editor@example.org", **fields}


def message(message_id, lineage, created_at, author="editor@example.org", **metadata):
    return ({"id": message_id, "messageKind": "reference_curation", "authorLabel": author, "createdAt": created_at,
             "metadata": json.dumps(metadata)},
            {"id": f"relation-{message_id}", "relationState": "current", "predicate": "comment", "subjectKind": "message",
             "subjectId": message_id, "objectStateKey": f"reference#{lineage}#current"})


def world(*references_and_votes):
    references, messages, relations = [], [], []
    for ref, votes in references_and_votes:
        references.append(ref)
        for vote in votes:
            row, relation = message(*vote[:3], **vote[3])
            messages.append(row)
            relations.append(relation)
    return FakeClient(references, messages, relations)


def test_the_newest_curation_message_becomes_the_reference_s_latest_vote():
    client = world((reference("a"), [
        ("m1", "a", "2026-10-01T00:00:00Z", {"actorKind": "human", "action": "reject", "reasonCode": "duplicate"}),
        ("m2", "a", "2026-10-02T00:00:00Z", {"actorKind": "human", "action": "accept", "sectionId": "section-research",
                                              "decisionRelationId": "relation-1", "shareable": True}),
    ]))
    result = backfill.run_backfill(client, apply=True)
    assert (result["scanned"], result["planned"], result["written"]) == (1, 1, 1)
    vote = latest_vote(client.references["a-v1"])
    assert vote["actorKind"] == "human" and vote["sectionId"] == "section-research" and vote["reasonCode"] is None
    assert vote["decisionRelationId"] == "relation-1" and vote["shareable"] is True


def test_a_dry_run_counts_and_writes_nothing():
    client = world((reference("a"), [("m1", "a", "2026-10-01T00:00:00Z", {"actorKind": "human"})]))
    result = backfill.run_backfill(client, apply=False)
    assert result["dryRun"] is True and result["planned"] == 1 and result["written"] == 0 and result["actorKinds"] == {"human": 1}
    assert client.updates == []


def test_service_and_unknown_actors_become_agents_and_only_named_people_become_human():
    client = world(
        (reference("service"), [("m1", "service", "2026-10-01T00:00:00Z", {"actorKind": "service"})]),
        (reference("unknown"), [("m2", "unknown", "2026-10-01T00:00:00Z", {"action": "accept"})]),
        (reference("named", curationStatusUpdatedBy="editor@example.org"),
         [("m3", "named", "2026-10-01T00:00:00Z", {"action": "accept"})]),
        (reference("cyclotron"), [("m4", "cyclotron", "2026-10-01T00:00:00Z", {"actorKind": "cyclotron"})]),
    )
    client.messages["m2"]["authorLabel"] = "Papyrus newsroom"
    client.messages["m3"]["authorLabel"] = "editor@example.org"
    client.messages["m1"]["authorLabel"] = "editor@example.org"   # a named person, but the message says service: stays an agent
    backfill.run_backfill(client, apply=True, human_authors=["editor@example.org"])
    kinds = {lineage: client.references[f"{lineage}-v1"]["curationActorKind"] for lineage in ("service", "unknown", "named", "cyclotron")}
    assert kinds == {"service": "human", "unknown": "agent", "named": "human", "cyclotron": "cyclotron"}


def test_a_delegated_vote_keeps_its_delegation():
    client = world((reference("a"), [("m1", "a", "2026-10-01T00:00:00Z", {
        "actorKind": "human", "attestation": "delegated", "relayedBy": "newsroom-reporter", "delegationId": "d1", "instruction": "Reject it."})]))
    backfill.run_backfill(client, apply=True)
    assert latest_vote(client.references["a-v1"])["delegation"] == {"delegationId": "d1", "relayedBy": "newsroom-reporter", "instruction": "Reject it."}


def test_references_with_a_recorded_vote_or_no_curation_message_are_left_alone():
    client = world(
        (reference("done", curationActorKind="human"), [("m1", "done", "2026-10-01T00:00:00Z", {"actorKind": "agent"})]),
        (reference("never"), []),
    )
    result = backfill.run_backfill(client, apply=True)
    assert (result["alreadyRecorded"], result["noVote"], result["planned"]) == (1, 1, 0)
    assert client.updates == [] and client.references["done-v1"]["curationActorKind"] == "human"
