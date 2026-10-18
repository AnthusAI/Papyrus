from __future__ import annotations

import io
import json
import pathlib
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content import messages_commands


class InMemoryAuthoringClient:
    def __init__(self, messages: list[dict], relations: list[dict]):
        self.messages = {message["id"]: dict(message) for message in messages}
        self.relations = {relation["id"]: dict(relation) for relation in relations}

    def list_messages_safe(self, *, limit: int = 100, next_token: str | None = None):
        rows = [{"id": message["id"], "messageKind": message.get("messageKind")} for message in self.messages.values()]
        return rows, None

    def get_record(self, model_name: str, record_id: str):
        assert model_name == "Message"
        return dict(self.messages[record_id])

    def update_record(self, model_name: str, payload: dict):
        assert model_name == "Message"
        self.messages[payload["id"]].update(payload)

    def list_records(self, model_name: str):
        assert model_name == "SemanticRelation"
        return [dict(relation) for relation in self.relations.values()]

    def create_record(self, model_name: str, payload: dict):
        assert model_name == "SemanticRelation"
        self.relations[payload["id"]] = dict(payload)

    def delete_record(self, model_name: str, record_id: str):
        assert model_name == "SemanticRelation"
        del self.relations[record_id]


def build_client() -> InMemoryAuthoringClient:
    messages = [
        {
            "id": "message-reference-insight-a",
            "messageKind": "insight",
            "metadata": json.dumps({"kind": "reference.insight.created", "targetId": "reference-a"}),
        },
        {"id": "message-tavily", "messageKind": "insight", "metadata": json.dumps({"kind": "research.tavily.insight"})},
        {"id": "message-comment", "messageKind": "comment", "metadata": json.dumps({"kind": "reference.insight.created"})},
        {"id": "message-already-note", "messageKind": "note", "metadata": json.dumps({"kind": "reference.note.created"})},
    ]
    relations = [
        {
            "id": "semantic-relation-old",
            "predicate": "insight_about",
            "relationTypeKey": "insight_about",
            "relationTypeId": "semantic-relation-type-insight-about",
            "relationDomain": "knowledge",
            "subjectVersionKey": "message#message-reference-insight-a",
            "objectVersionKey": "reference#reference-a",
            "objectStateKey": "reference#reference-a#current",
            "predicateObjectStateKey": "insight_about#reference#reference-a#current",
            "metadata": json.dumps({"kind": "reference.insight"}),
        },
        {"id": "semantic-relation-unrelated", "predicate": "comment"},
    ]
    return InMemoryAuthoringClient(messages, relations)


def run_migration(client: InMemoryAuthoringClient, flags: list[str]) -> str:
    output = io.StringIO()
    with mock.patch.object(messages_commands, "create_authoring_client", return_value=(client, None)):
        with redirect_stdout(output):
            messages_commands.messages_migrate_insights_to_notes(flags)
    return output.getvalue()


class MigrateInsightsToNotesTests(unittest.TestCase):
    def test_dry_run_changes_nothing_and_prints_counts(self):
        client = build_client()
        output = run_migration(client, ["--dry-run"])
        self.assertEqual(client.messages["message-reference-insight-a"]["messageKind"], "insight")
        self.assertIn("semantic-relation-old", client.relations)
        self.assertIn("dry-run\tmessageKindsRewritten\t2", output)
        self.assertIn("dry-run\trelationsCreated\t1", output)

    def test_apply_rewrites_messages_metadata_and_relations(self):
        client = build_client()
        output = run_migration(client, [])
        self.assertIn("applied\tmessageKindsRewritten\t2", output)
        self.assertEqual(client.messages["message-reference-insight-a"]["messageKind"], "note")
        self.assertEqual(
            json.loads(client.messages["message-reference-insight-a"]["metadata"])["kind"],
            "reference.note.created",
        )
        self.assertEqual(json.loads(client.messages["message-tavily"]["metadata"])["kind"], "research.tavily.note")
        self.assertEqual(client.messages["message-comment"]["messageKind"], "comment")
        self.assertNotIn("semantic-relation-old", client.relations)
        migrated = [relation for relation in client.relations.values() if relation.get("predicate") == "note_about"]
        self.assertEqual(len(migrated), 1)
        self.assertEqual(migrated[0]["relationTypeKey"], "note_about")
        self.assertEqual(migrated[0]["relationTypeId"], "semantic-relation-type-note-about")
        self.assertEqual(migrated[0]["predicateObjectStateKey"], "note_about#reference#reference-a#current")
        self.assertEqual(json.loads(migrated[0]["metadata"])["kind"], "reference.note")
        self.assertIn("semantic-relation-unrelated", client.relations)

    def test_second_run_is_idempotent(self):
        client = build_client()
        run_migration(client, [])
        snapshot_messages = json.dumps(client.messages, sort_keys=True)
        snapshot_relations = json.dumps(client.relations, sort_keys=True)
        output = run_migration(client, [])
        self.assertEqual(json.dumps(client.messages, sort_keys=True), snapshot_messages)
        self.assertEqual(json.dumps(client.relations, sort_keys=True), snapshot_relations)
        self.assertIn("applied\tmessageKindsRewritten\t0", output)
        self.assertIn("applied\trelationsDeleted\t0", output)

    def test_existing_migrated_relation_is_not_recreated(self):
        client = build_client()
        run_migration(client, [])
        migrated_id = next(rid for rid, relation in client.relations.items() if relation.get("predicate") == "note_about")
        legacy = build_client().relations["semantic-relation-old"]
        client.relations["semantic-relation-old"] = legacy
        output = run_migration(client, [])
        self.assertIn("applied\trelationsCreated\t0", output)
        self.assertIn("applied\trelationsDeleted\t1", output)
        self.assertIn(migrated_id, client.relations)
        self.assertNotIn("semantic-relation-old", client.relations)


if __name__ == "__main__":
    unittest.main()
