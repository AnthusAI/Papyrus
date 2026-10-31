"""Generated story ideas are Items at the idea stage (src/papyrus_content/ideas/items.py, migrate.py)."""

from __future__ import annotations

import json

import pytest

from papyrus_content.ideas import monitor_stories
from papyrus_content.ideas.items import ItemStore, file_idea_item, generated_of, idea_rows
from papyrus_content.ideas.migrate import migrate, plan
from papyrus_content.story_from_reference import StoryCopiedFromReference
from papyrus_content.story_reporting import move_story_stage, stories_based_on_reference, story_references
from procedures.newsroom.tests.test_story_from_reference import ARTICLE_URL, NOW, SOURCE_TEXT, backend, reader

OWN = "A new family of routers decides, for each request, which model should answer it. [1]\n\n## Source\n\n1. Clef " + ARTICLE_URL + "\n\nSection: Articles. Drafted by AI.\n"


def draft(**changes):
    base = {"ideaId": "idea-1", "title": "Clef routes requests", "angle": "A router picks the model.", "body": OWN, "section": "Articles", "origin": "monitor", "runId": "run-1",
            "monitorId": "hn", "targets": [{"type": "entity", "id": "reference:reference-clef"}], "evidence": {"signals": 1, "source": "hn monitor: " + ARTICLE_URL},
            "citedItems": [{"title": "Clef", "url": ARTICLE_URL}]}
    return {**base, **changes}


def test_an_idea_is_an_item_at_the_idea_stage_that_records_its_machine_origin_and_links_its_reference():
    client = backend()
    result = file_idea_item(client, draft(), now=NOW, source_text_reader=reader)
    assert result["created"] and result["linked"] == ["reference-clef"]
    item = client.get_record("Item", result["itemId"])
    assert item["stage"] == "idea" and item["status"] == "draft" and item["section"] == "articles"
    assert "Section:" not in item["bodyMarkus"]
    generated = generated_of(item)
    assert (generated["origin"], generated["proposedBy"], generated["monitorId"], generated["runId"]) == ("monitor", "AI", "hn", "run-1")
    assert [link["role"] for link in story_references(client, result["lineageId"])] == ["based_on"]
    assert stories_based_on_reference(client, "reference-clef")[0]["storyLineageId"] == result["lineageId"]


def test_filing_the_same_idea_again_finds_the_item_and_changes_nothing():
    client = backend()
    first = file_idea_item(client, draft(), now=NOW, source_text_reader=reader)
    second = file_idea_item(client, draft(ideaId="idea-2", runId="run-2"), now=NOW, source_text_reader=reader)
    assert not second["created"] and second["itemId"] == first["itemId"]
    assert len(client.list_records("Item")) == 1 and len(client.tables["SemanticRelation"]) == 1


def test_a_body_that_copies_the_reference_is_refused_and_nothing_is_written():
    client = backend()
    with pytest.raises(StoryCopiedFromReference):
        file_idea_item(client, draft(body="Our view. " + SOURCE_TEXT + "\n"), now=NOW, source_text_reader=reader)
    assert client.list_records("Item") == [] and not client.tables.get("SemanticRelation")


def test_the_store_reads_ideas_as_drafts_and_a_spiked_one_counts_as_declined():
    client = backend()
    store = ItemStore(client, source_text_reader=reader)
    lineage = store.file_story_draft(draft())
    [row] = store.story_drafts()
    assert (row["id"], row["state"]) == (lineage, "draft") and monitor_stories.drafted_lineage_ids([row], []) == {"reference-clef"}
    move_story_stage(client, lineage, "spiked", actor="editor", reason="not our kind of story", now=NOW)
    [row] = idea_rows(client)
    assert row["state"] == "declined" and monitor_stories.drafted_lineage_ids([row], []) == {"reference-clef"}


def proposal(identifier, state="draft", lineage="reference-clef", created="2026-10-30T00:00:00Z", body=OWN):
    return {"id": identifier, "kind": "story_draft", "state": state, "title": f"Clef {identifier}", "summary": "A router.", "body": body, "createdAt": created, "proposer": "ai",
            "targets": json.dumps([{"type": "entity", "id": f"reference:{lineage}"}]), "evidence": json.dumps({"signals": 1, "source": "hn"})}


def test_the_migration_converts_open_proposals_and_skips_decided_covered_and_duplicate_ones():
    client = backend()
    proposals = [proposal("prop-a"), proposal("prop-b", created="2026-10-31T00:00:00Z"), proposal("prop-c", state="declined", lineage="reference-other"), proposal("prop-d", lineage="reference-other2")]
    dry = migrate(client, proposals, write=False)
    assert [(e["proposalId"], e["action"], e.get("reason")) for e in dry["entries"]] == [
        ("prop-a", "convert", None), ("prop-c", "skip", "decided"), ("prop-d", "convert", None), ("prop-b", "skip", "duplicate")]
    assert dry["written"] == 0 and client.list_records("Item") == []
    done = migrate(client, proposals, write=True, source_text_reader=reader, now=NOW)
    assert done["counts"]["convert"] == 1 and done["counts"].get("failed") == 1   # prop-d cites a Reference that does not exist
    [item] = client.list_records("Item")
    assert item["stage"] == "idea" and generated_of(item)["migratedFromProposal"] == "prop-a"
    again = plan(client, proposals)
    assert [e["reason"] for e in again if e["action"] == "skip" and e["proposalId"] in ("prop-a", "prop-b")] == ["already_covered", "already_covered"]


# --- the editorial gate ---------------------------------------------------------------------------------------------------------


from papyrus_content.ideas.items import IdeaRefused, review_order  # noqa: E402


class FakeGate:
    def __init__(self, findings=(), classifier=None, skipped=None):
        self.findings, self.classifier, self.skipped, self.recorded, self.seen = list(findings), classifier or {"status": "ran"}, skipped, [], []

    def check(self, body, section):
        self.seen.append((body, section))
        if self.skipped:
            return {"skipped": self.skipped}
        return {"findings": self.findings, "lanes": {"rules": {"status": "ran"}, "classifier": self.classifier}, "pack": {"version": "p1"}}

    def record(self, item, result):
        self.recorded.append((item["id"], result))


def finding(severity, status="violation", policy="production-claims"):
    return {"id": f"f-{severity}", "policyId": policy, "severity": severity, "status": status, "message": f"{policy} {severity}"}


def test_an_error_violation_refuses_the_filing_and_writes_nothing():
    client, gate = backend(), FakeGate([finding("error"), finding("warn")])
    with pytest.raises(IdeaRefused) as refusal:
        file_idea_item(client, draft(), now=NOW, source_text_reader=reader, gate=gate)
    assert [f["severity"] for f in refusal.value.findings] == ["error"] and "production-claims" in str(refusal.value)
    assert client.list_records("Item") == [] and gate.recorded == []


def test_warnings_are_kept_on_the_item_and_stored_as_its_check_run():
    client, gate = backend(), FakeGate([finding("warn"), finding("info", status="review", policy="hype")])
    result = file_idea_item(client, draft(supersedes=[]), now=NOW, source_text_reader=reader, gate=gate)
    check = generated_of(client.get_record("Item", result["itemId"]))["check"]
    assert check["counts"] == {"error": 0, "warn": 1, "info": 1} and check["judgment"]["ran"] is True
    assert [(item_id, r["pack"]["version"]) for item_id, r in gate.recorded] == [(result["itemId"], "p1")]
    assert gate.seen[0][1] == "articles" and "Section:" not in gate.seen[0][0]


def test_a_judgment_lane_that_did_not_run_is_recorded_not_passed_silently():
    client = backend()
    gate = FakeGate(classifier={"status": "unavailable", "reason": "no decision model is configured (set TYPESAFE_API_KEY)"})
    result = file_idea_item(client, draft(), now=NOW, source_text_reader=reader, gate=gate)
    judgment = generated_of(client.get_record("Item", result["itemId"]))["check"]["judgment"]
    assert judgment["ran"] is False and "TYPESAFE_API_KEY" in judgment["reason"]


def test_checks_turned_off_are_recorded_as_not_run():
    client = backend()
    result = file_idea_item(client, draft(), now=NOW, source_text_reader=reader, gate=FakeGate(skipped="disabled"))
    assert generated_of(client.get_record("Item", result["itemId"]))["check"] == {"ran": False, "skipped": "disabled"}


def test_supersedes_names_item_lineages_the_idea_replaces():
    client = backend()
    older = file_idea_item(client, draft(), now=NOW, source_text_reader=reader)["lineageId"]
    newer = file_idea_item(client, draft(ideaId="idea-2", targets=[{"type": "entity", "id": "topic-clef"}], title="Clef roundup", supersedes=[older]), now=NOW, source_text_reader=reader)
    assert newer["created"] and generated_of(client.get_record("Item", newer["itemId"]))["supersedes"] == [older]
    with pytest.raises(ValueError):
        file_idea_item(backend(), draft(supersedes=["item-nope"]), now=NOW, source_text_reader=reader)


def test_the_batch_review_lists_clean_ideas_first():
    ideas = [{"ideaId": "a", "editorialCheck": {"counts": {"error": 0, "warn": 2, "info": 0}}}, {"ideaId": "b"}, {"ideaId": "c", "editorialCheck": {"counts": {"error": 0, "warn": 0, "info": 1}}}]
    assert [idea["ideaId"] for idea in review_order(ideas)] == ["b", "c", "a"]
