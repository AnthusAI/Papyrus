from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content import cli as papyrus_content_cli
from papyrus_content import messages_commands
from papyrus_content import relation_types
from papyrus_content import relations_commands


class RelationsCommandsTests(unittest.TestCase):
    def test_normalize_relation_type_key_matches_node_contract(self):
        self.assertEqual(relation_types.normalize_relation_type_key("Requests Work On"), "requests_work_on")
        self.assertEqual(relation_types.normalize_relation_type_key("  COMMENT  "), "comment")

    def test_load_semantic_relation_type_seeds_reads_default_config(self):
        seeds = relation_types.load_semantic_relation_type_seeds()
        self.assertGreater(len(seeds), 10)
        keys = {entry["key"] for entry in seeds}
        self.assertIn("comment", keys)
        self.assertIn("classified_as", keys)

    def test_member_of_is_a_seeded_ontology_relation_from_a_node_to_a_node(self):
        seeds = relation_types.load_semantic_relation_type_seeds()
        member_of = next(entry for entry in seeds if entry["key"] == "member_of")
        self.assertEqual((member_of["label"], member_of["inverseLabel"], member_of["domain"]), ("member of", "members", "ontology"))
        self.assertEqual((member_of["allowedSubjectKinds"], member_of["allowedObjectKinds"]), (["semanticNode"], ["semanticNode"]))
        self.assertTrue(member_of["isDirectional"] and not member_of["isSymmetric"] and not member_of["isTransitive"])
        fields = relation_types.semantic_relation_type_fields_for_predicate("member_of", seeds)
        self.assertEqual(fields["relationDomain"], "ontology")
        self.assertEqual(fields["relationTypeId"], relation_types.semantic_relation_type_id_for("member_of"))

    def test_build_semantic_relation_type_records_uses_stable_ids(self):
        seeds = relation_types.load_semantic_relation_type_seeds()
        comment = next(entry for entry in seeds if entry["key"] == "comment")
        records = relation_types.build_semantic_relation_type_records([comment], now="2026-01-01T00:00:00.000Z")
        self.assertEqual(len(records), 1)
        expected = records[0]["expected"]
        self.assertEqual(records[0]["modelName"], "SemanticRelationType")
        self.assertEqual(expected["id"], relation_types.semantic_relation_type_id_for("comment"))
        self.assertEqual(expected["key"], "comment")
        self.assertEqual(json.loads(expected["metadata"]), comment["metadata"])

    def test_build_semantic_relation_backfill_records_marks_noop_and_update(self):
        seeds = relation_types.load_semantic_relation_type_seeds()
        comment_type_id = relation_types.semantic_relation_type_id_for("comment")
        relations = [
            {
                "id": "semantic-relation-1",
                "predicate": "comment",
                "relationTypeId": comment_type_id,
                "relationTypeKey": "comment",
                "relationDomain": "commentary",
            },
            {
                "id": "semantic-relation-2",
                "predicate": "comment",
                "relationTypeKey": "comment",
                "relationDomain": "generic",
            },
            {
                "id": "semantic-relation-3",
                "predicate": "unknown_predicate",
            },
        ]
        changes = relation_types.build_semantic_relation_backfill_records(relations, seeds)
        self.assertEqual(changes[0]["action"], "noop")
        self.assertEqual(changes[1]["action"], "update")
        self.assertTrue(changes[1]["expected"]["relationTypeId"])
        self.assertEqual(changes[1]["expected"]["relationDomain"], "commentary")
        self.assertTrue(changes[2]["unknownType"])
        self.assertEqual(changes[2]["expected"]["relationDomain"], "generic")

    def test_legacy_knowledge_comment_records_without_subject_creates_message_only(self):
        records = messages_commands.legacy_knowledge_comment_records(
            {
                "id": "legacy-comment-1",
                "body": "Needs review.",
                "createdAt": "2026-01-01T00:00:00.000Z",
            }
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["modelName"], "Message")
        self.assertTrue(records[0]["expected"]["id"].startswith("message-legacy-"))
        self.assertEqual(records[0]["expected"]["content"], "Needs review.")

    def test_legacy_knowledge_comment_records_with_subject_creates_relation(self):
        records = messages_commands.legacy_knowledge_comment_records(
            {
                "id": "legacy-comment-2",
                "commentKind": "comment",
                "body": "Editor note.",
                "subjectKind": "reference",
                "subjectId": "reference-1",
                "subjectLineageId": "reference-lineage-1",
                "subjectVersionNumber": 2,
                "createdAt": "2026-01-01T00:00:00.000Z",
            }
        )
        self.assertEqual(len(records), 2)
        relation = records[1]["expected"]
        self.assertEqual(records[1]["modelName"], "SemanticRelation")
        self.assertEqual(relation["predicate"], "comment")
        self.assertEqual(relation["relationTypeKey"], "comment")
        self.assertEqual(relation["relationDomain"], "commentary")
        self.assertEqual(relation["objectKind"], "reference")
        self.assertEqual(relation["objectLineageId"], "reference-lineage-1")
        self.assertEqual(relation["objectVersionNumber"], 2)

    def test_is_ported_command_includes_relations_and_messages_routes(self):
        self.assertTrue(papyrus_content_cli.is_ported_command("relations", "import-types"))
        self.assertTrue(papyrus_content_cli.is_ported_command("relations", "backfill"))
        self.assertTrue(papyrus_content_cli.is_ported_command("messages", "export-legacy-comments"))
        self.assertTrue(papyrus_content_cli.is_ported_command("messages", "import-legacy-comments"))

    def test_relations_backfill_writes_report_without_apply(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = pathlib.Path(tmpdir)
            with mock.patch.object(relations_commands, "create_authoring_client") as create_client, mock.patch.object(
                relations_commands, "DEFAULT_RELATION_TYPES_PATH", REPO_ROOT / "corpora" / "papyrus-semantic-relation-types.yml"
            ):
                client = mock.Mock()
                client.list_records.return_value = [
                    {
                        "id": "semantic-relation-1",
                        "predicate": "comment",
                        "relationTypeKey": "comment",
                        "relationDomain": "generic",
                    }
                ]
                create_client.return_value = (client, {})
                original_cwd = pathlib.Path.cwd()
                try:
                    import os

                    os.chdir(cwd)
                    with mock.patch("sys.stdout") as stdout:
                        relations_commands.relations_backfill([])
                finally:
                    os.chdir(original_cwd)
                report_path = cwd / ".papyrus-runs"
                reports = list(report_path.glob("relation-type-backfill-*/backfill-report.json"))
                self.assertEqual(len(reports), 1)
                report = json.loads(reports[0].read_text(encoding="utf-8"))
                self.assertFalse(report["apply"])
                self.assertEqual(report["relationCount"], 1)
                self.assertEqual(report["changeCount"], 1)
                client.upsert.assert_not_called()
                stdout.write.assert_called()


if __name__ == "__main__":
    unittest.main()
