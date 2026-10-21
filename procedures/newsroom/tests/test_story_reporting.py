from __future__ import annotations

import json
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.story_reporting import (
    append_story_message,
    latest_story_version,
    link_reference_to_story,
    save_story_version,
    story_references,
    story_thread_id,
    story_versions,
)

NOW = "2026-10-18T15:00:00Z"
LINEAGE = "item-sandbox-escape"


class FakeAuthoringClient:
    def __init__(self, tables):
        self.tables = tables

    def get_record(self, model, record_id):
        return self.tables.get(model, {}).get(record_id)

    def create_record(self, model, payload):
        self.tables.setdefault(model, {})[payload["id"]] = dict(payload)

    def update_record(self, model, payload):
        self.tables[model][payload["id"]].update(payload)

    def upsert(self, model, payload):
        outcome = "updated" if payload["id"] in self.tables.get(model, {}) else "created"
        self.tables.setdefault(model, {})[payload["id"]] = dict(payload)
        return outcome

    def list_by_index(self, index_name, key_value, *, limit=100):
        if index_name == "itemsByLineageAndVersion":
            return [row for row in self.tables.get("Item", {}).values() if row["lineageId"] == key_value]
        if index_name == "semanticRelationsBySubjectState":
            return [row for row in self.tables.get("SemanticRelation", {}).values() if row["subjectStateKey"] == key_value]
        raise AssertionError(index_name)


def client_with_one_story():
    first_version = {
        "id": LINEAGE, "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current", "type": "article", "slug": "sandbox-escape",
        "section": None, "status": "draft", "stage": "reporting", "headline": "Sandbox escape", "title": "Sandbox escape", "aliases": [],
        "metadata": json.dumps({"frontMatterYaml": 'title: "Sandbox escape"'}), "bodyMarkus": "First draft.", "createdAt": NOW, "updatedAt": NOW,
    }
    reference = {"id": "reference-pwn-ai-v1", "lineageId": "reference-pwn-ai", "versionNumber": 1}
    return FakeAuthoringClient({"Item": {LINEAGE: first_version}, "Reference": {"reference-pwn-ai-v1": reference, "reference-pwn-ai": reference}})


class StoryReportingTests(unittest.TestCase):
    def test_a_new_version_supersedes_the_previous_one_and_becomes_the_latest(self):
        client = client_with_one_story()
        saved = save_story_version(client, LINEAGE, front_matter_yaml='title: "Sandbox escape"', body_markus="Second draft.\n", actor="ChatGPT", change_reason="added the Vercel corroboration", now=NOW)
        self.assertEqual(saved["id"], f"{LINEAGE}-v2")
        self.assertEqual(saved["versionNumber"], 2)
        self.assertEqual(saved["previousVersionId"], LINEAGE)
        self.assertEqual(saved["versionCreatedBy"], "ChatGPT")
        self.assertEqual(client.tables["Item"][LINEAGE]["versionState"], "superseded")
        self.assertEqual([version["versionNumber"] for version in story_versions(client, LINEAGE)], [2, 1])
        self.assertEqual(latest_story_version(client, LINEAGE)["bodyMarkus"], "Second draft.\n")

    def test_a_new_version_gets_a_free_id_when_the_current_one_already_uses_the_next_suffix(self):
        client = client_with_one_story()
        renamed = dict(client.tables["Item"][LINEAGE], id=f"{LINEAGE}-v2", versionNumber=1, versionState="current", slug="sandbox-escape-renamed")
        client.tables["Item"][LINEAGE]["versionState"] = "superseded"
        client.tables["Item"][LINEAGE]["versionNumber"] = 0
        client.tables["Item"][renamed["id"]] = renamed
        saved = save_story_version(client, LINEAGE, front_matter_yaml='title: "Sandbox escape"', body_markus="Rewrite.\n", actor="ChatGPT", change_reason="rewrite", now=NOW)
        self.assertEqual(saved["id"], f"{LINEAGE}-v3")
        self.assertEqual(saved["versionNumber"], 2)
        self.assertEqual(saved["previousVersionId"], f"{LINEAGE}-v2")
        self.assertEqual(client.tables["Item"][f"{LINEAGE}-v2"]["versionState"], "superseded")

    def test_a_reference_is_consulted_first_and_later_marked_cited_without_a_second_link(self):
        client = client_with_one_story()
        link_reference_to_story(client, LINEAGE, "reference-pwn-ai-v1", role="consulted", actor="ChatGPT", note="primary source", now=NOW)
        link_reference_to_story(client, LINEAGE, "reference-pwn-ai-v1", role="cited", actor="ChatGPT", citation_key="pwn2026", now="2026-10-18T16:00:00Z")
        rows = story_references(client, LINEAGE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["role"], "cited")
        self.assertEqual(rows[0]["citationKey"], "pwn2026")
        self.assertEqual(rows[0]["note"], "primary source")
        self.assertEqual(rows[0]["addedAt"], NOW)

    def test_messages_are_ordered_attributed_and_kept_in_one_thread_per_story(self):
        client = client_with_one_story()
        first = append_story_message(client, LINEAGE, body="Found the primary source.", summary="Primary source", author_label="ChatGPT", now=NOW)
        second = append_story_message(client, LINEAGE, body="Vercel corroborates.", summary="Corroboration", author_label="ChatGPT", message_kind="research_packet", reference_lineage_id="reference-pwn-ai", now="2026-10-18T15:30:00Z")
        self.assertEqual((first["sequenceNumber"], second["sequenceNumber"]), (1, 2))
        self.assertEqual({first["threadId"], second["threadId"]}, {story_thread_id(LINEAGE)})
        thread = client.tables["MessageThread"][story_thread_id(LINEAGE)]
        self.assertEqual(thread["messageCount"], 2)
        self.assertEqual(thread["primaryAnchorLineageId"], LINEAGE)
        self.assertEqual(json.loads(second["metadata"])["referenceLineageId"], "reference-pwn-ai")

    def test_an_unknown_message_kind_is_refused(self):
        with self.assertRaises(ValueError):
            append_story_message(client_with_one_story(), LINEAGE, body="x", summary="x", author_label="a", message_kind="insight", now=NOW)


if __name__ == "__main__":
    unittest.main()
