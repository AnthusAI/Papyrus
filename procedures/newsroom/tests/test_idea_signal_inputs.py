"""Signal inputs: the one read pass that feeds the idea signals (src/papyrus_content/ideas/signal_inputs.py)."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from papyrus_content.ideas.signal_inputs import load_signal_inputs
from procedures.newsroom.tests.ideas_fixtures import CORPUS, NOW, entity, reference, relevance, story


def voted(number: int, status: str, actor: str | None = "human", **more: Any) -> dict[str, Any]:
    row = reference(number, status=status)
    row.update({"curationActorKind": actor, "curationStatusUpdatedAt": "2026-10-22T09:00:00Z", "curationStatusUpdatedBy": "editor-a",
                "curationStatusReason": f"reason {number}", "curationReasonCode": "off_topic", "sourcePublishedAt": "2026-10-01"})
    row.update(more)
    return row


def concept(row: dict[str, Any], name: str, predicate: str, **more: Any) -> dict[str, Any]:
    return {**entity(row, name), "predicate": predicate, **more}


def message(number: int, thread: str, role: str = "human", **more: Any) -> dict[str, Any]:
    return {"id": f"m-{number}", "threadId": thread, "status": "active", "role": role, "authorKind": "staff", "content": f"text {number}",
            "createdAt": f"2026-10-2{number}T00:00:00Z", **more}


class FakeSignalClient:
    tenant_id = None

    def __init__(self, references=(), relations=None, threads=(), messages=None, stories=(), items=(), page_size=2, incoming=None) -> None:
        self.references = list(references)
        self.relations = relations or {}
        self.incoming = incoming or {}
        self.incoming_queries: list[str] = []
        self.threads = list(threads)
        self.messages = messages or {}
        self.stories = list(stories)
        self.items = list(items)
        self.page_size = page_size
        self.message_pages = 0
        self.relation_queries: list[str] = []

    def list_records(self, model: str) -> list[dict[str, Any]]:
        return {"MessageThread": self.threads, "Item": self.items}.get(model, [])

    def list_by_index(self, index: str, key: str) -> list[dict[str, Any]]:
        corpus, _, status = key.rpartition("#")
        return [row for row in self.references if row["corpusId"] == corpus and row["curationStatus"] == status]

    def list_semantic_relations_by_subject_state(self, key: str) -> list[dict[str, Any]]:
        self.relation_queries.append(key)
        return self.relations.get(key.split("#")[1], [])

    def list_semantic_relations_by_object_state(self, key: str) -> list[dict[str, Any]]:
        self.incoming_queries.append(key)
        return self.incoming.get(key.split("#")[1], [])

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        variables = variables or {}
        if "listItems" in query:
            return {"listItems": {"items": self.stories, "nextToken": None}}
        assert "listMessagesByThreadAndCreatedAt" in query
        self.message_pages += 1
        rows = self.messages.get(variables["threadId"], [])
        start = int(variables.get("nextToken") or 0)
        end = start + self.page_size
        return {"listMessagesByThreadAndCreatedAt": {"items": rows[start:end], "nextToken": str(end) if end < len(rows) else None}}


def idea_item(number: int, stage: str = "idea") -> dict[str, Any]:
    front = "generated:\n  origin: monitor\n  targets: []\n"
    return {"id": f"item-idea-{number}-v1", "lineageId": f"item-idea-{number}", "versionState": "current", "stage": stage, "title": f"Idea {number}",
            "deck": "", "versionCreatedAt": "2026-10-20T00:00:00Z", "metadata": json.dumps({"frontMatterYaml": front})}


def test_messages_from_people_are_paged_and_machines_are_left_out():
    client = FakeSignalClient(
        threads=[{"id": "t1", "threadKind": "reference_conversation", "primaryAnchorKey": "reference#r1"}],
        messages={"t1": [message(1, "t1"), message(2, "t1", role="assistant"), message(3, "t1"), message(4, "t1", deletedAt="2026-10-25T00:00:00Z"), message(5, "t1", content="  "), message(6, "t1", authorKind="reader")]},
    )
    inputs = load_signal_inputs(client, site="example-site", now=NOW)
    assert [m.message_id for m in inputs.messages] == ["m-1", "m-3", "m-6"]
    assert inputs.messages[0].anchor_key == "reference#r1" and inputs.messages[0].thread_kind == "reference_conversation"
    assert inputs.messages[2].author_kind == "reader"
    assert client.message_pages == 3


def test_only_human_votes_are_votes_in_every_status_with_reason_and_both_dates():
    rows = [voted(1, "accepted"), voted(2, "rejected"), voted(3, "archived"), voted(4, "accepted", actor="cyclotron"), voted(5, "accepted", actor=None), voted(6, "pending")]
    inputs = load_signal_inputs(FakeSignalClient(references=rows), site="example-site", now=NOW)
    assert sorted(v.status for v in inputs.votes) == ["accepted", "archived", "pending", "rejected"]
    vote = next(v for v in inputs.votes if v.status == "rejected")
    assert (vote.reason, vote.reason_code, vote.voted_by, vote.voted_at) == ("reason 2", "off_topic", "editor-a", "2026-10-22T09:00:00Z")
    assert vote.source_published_at == "2026-10-01" and vote.created_at and vote.url


def test_a_reference_links_to_a_concept_by_mentions_or_related_to_and_by_nothing_else():
    row = voted(1, "accepted")
    lineage = row["lineageId"]
    relations = {lineage: [
        concept(row, "cn-a", "mentions"), concept(row, "cn-b", "related_to"), concept(row, "cn-c", "uses_evidence"),
        concept(row, "cn-d", "mentions", relationState="superseded"), concept(row, "cn-e", "mentions", objectKind="reference"), relevance(row),
    ]}
    inputs = load_signal_inputs(FakeSignalClient(references=[row], relations=relations), site="example-site", now=NOW)
    assert [(l.concept_id, l.predicate) for l in inputs.concept_links] == [("cn-a", "mentions"), ("cn-b", "related_to")]
    assert inputs.votes[0].concept_ids == ("cn-a", "cn-b")


def test_pending_references_with_a_positive_verdict_are_context_only():
    positive, negative, unjudged, voted_pending = reference(1, status="pending"), reference(2, status="pending"), reference(3, status="pending"), voted(4, "pending")
    relations = {positive["lineageId"]: [relevance(positive, "include", 0.8), concept(positive, "cn-a", "mentions")], negative["lineageId"]: [relevance(negative, "exclude", 0.1)]}
    inputs = load_signal_inputs(FakeSignalClient(references=[positive, negative, unjudged, voted_pending], relations=relations), site="example-site", now=NOW)
    assert [p.lineage_id for p in inputs.pending_context] == [positive["lineageId"]]
    assert inputs.pending_context[0].score == 0.8 and inputs.pending_context[0].concept_ids == ("cn-a",)
    assert [v.status for v in inputs.votes] == ["pending"]


def test_published_items_and_all_ideas_including_spiked_are_loaded_for_repeat_suppression():
    client = FakeSignalClient(
        stories=[story("Published one"), story("Still a draft", status="draft", stage="draft")],
        items=[idea_item(1), idea_item(2, stage="spiked"), {"id": "x-v1", "lineageId": "x", "versionState": "current", "stage": "draft", "title": "Human story"}],
    )
    inputs = load_signal_inputs(client, site="example-site", now=NOW)
    assert [s.title for s in inputs.published] == ["Published one"]
    assert sorted((i.title, i.state) for i in inputs.ideas) == [("Idea 1", "draft"), ("Idea 2", "declined")]


def test_the_snapshot_is_frozen_and_reads_only_the_sites_corpus():
    other = reference(9, corpus="knowledge-corpus-other")
    inputs = load_signal_inputs(FakeSignalClient(references=[voted(1, "accepted"), other]), site="example-site", now=NOW)
    assert len(inputs.votes) == 1 and inputs.site == "example-site" and CORPUS.endswith("example-site")
    with pytest.raises(dataclasses.FrozenInstanceError):
        inputs.site = "x"  # type: ignore[misc]


def test_relations_are_read_only_for_votes_pending_and_thread_anchors():
    plain, rejected_by_rule, anchored = voted(1, "accepted", actor=None), voted(2, "rejected", actor="cyclotron"), voted(3, "accepted", actor=None)
    human, pending = voted(4, "accepted"), reference(5, status="pending")
    client = FakeSignalClient(
        references=[plain, rejected_by_rule, anchored, human, pending],
        threads=[{"id": "t1", "threadKind": "reference_conversation", "primaryAnchorKey": f"reference#{anchored['lineageId']}"}],
    )
    load_signal_inputs(client, site="example-site", now=NOW)
    assert sorted(client.relation_queries) == sorted(f"reference#{row['lineageId']}#current" for row in (anchored, human, pending))


def edge(subject: dict[str, Any], other: dict[str, Any], predicate: str = "related_to", **more: Any) -> dict[str, Any]:
    return {"subjectKind": "reference", "subjectLineageId": subject["lineageId"], "objectKind": "reference", "objectLineageId": other["lineageId"],
            "predicate": predicate, "relationState": "current", "createdAt": "2026-10-30T00:00:00Z", **more}


def test_current_reference_edges_are_read_from_both_ends_with_their_dates_and_only_for_references_already_read():
    first, second, outside = voted(1, "accepted"), voted(2, "accepted"), voted(3, "accepted", actor=None)
    relations = {first["lineageId"]: [edge(first, second), edge(first, outside, "cites"), edge(first, second, "mentions"), edge(first, second, relationState="suggested")]}
    incoming = {second["lineageId"]: [edge(first, second), edge(outside, second, "supports")]}
    client = FakeSignalClient(references=[first, second, outside], relations=relations, incoming=incoming)
    inputs = load_signal_inputs(client, site="example-site", now=NOW)
    pairs = [(e.subject_lineage_id, e.object_lineage_id, e.predicate, e.created_at) for e in inputs.edges]
    assert pairs == sorted([
        (first["lineageId"], second["lineageId"], "related_to", "2026-10-30T00:00:00Z"),
        (first["lineageId"], outside["lineageId"], "cites", "2026-10-30T00:00:00Z"),
        (outside["lineageId"], second["lineageId"], "supports", "2026-10-30T00:00:00Z"),
    ])
    assert sorted(client.incoming_queries) == sorted(f"reference#{row['lineageId']}#current" for row in (first, second))


def test_every_accepted_reference_is_listed_whoever_accepted_it():
    human, machine, rejected = voted(1, "accepted"), voted(2, "accepted", actor="cyclotron"), voted(3, "rejected")
    inputs = load_signal_inputs(FakeSignalClient(references=[human, machine, rejected]), site="example-site", now=NOW)
    assert sorted((a.lineage_id, a.accepted_by) for a in inputs.accepted) == sorted([(human["lineageId"], "human"), (machine["lineageId"], "machine")])
    assert all(a.accepted_at == "2026-10-22T09:00:00Z" for a in inputs.accepted)


def test_a_pending_verdict_comes_from_the_rows_prediction_without_a_read():
    likely, unlikely = {**reference(1, status="pending"), "predictedAcceptProbability": 0.83}, {**reference(2, status="pending"), "predictedAcceptProbability": 0.2}
    client = FakeSignalClient(references=[likely, unlikely])
    inputs = load_signal_inputs(client, site="example-site", now=NOW, out_of_time=lambda: True)
    assert [(p.lineage_id, p.score) for p in inputs.pending_context] == [(likely["lineageId"], 0.83)]
    assert client.relation_queries == []


def test_pending_relations_are_read_most_likely_first_until_time_runs_out():
    rows = [{**reference(number, status="pending"), "predictedAcceptProbability": number / 100} for number in range(1, 80)]
    client = FakeSignalClient(references=rows)
    checks = iter([False, True])
    inputs = load_signal_inputs(client, site="example-site", now=NOW, workers=2, out_of_time=lambda: next(checks, True))
    read = [key.split("#")[1] for key in client.relation_queries]
    by_lineage = {row["lineageId"]: row["predictedAcceptProbability"] for row in rows}
    assert len(read) == 8 and min(by_lineage[lineage] for lineage in read) > max(p for lineage, p in by_lineage.items() if lineage not in read)
    assert len(inputs.pending_context) == len([row for row in rows if row["predictedAcceptProbability"] >= 0.5])
