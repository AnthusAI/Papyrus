from __future__ import annotations

import pathlib
import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.analysis_commands import (  # noqa: E402
    _assert_entity_graph_run_ready,
    _analysis_import_graph_artifact_internal,
    analysis_entity_graph_preflight,
    _extract_last_json_from_file,
    _analysis_publish_graph_snapshot_internal,
)
from papyrus_content.analysis_graph import (  # noqa: E402
    apply_graph_generated_purge_plan,
    build_graph_export_import_records,
    build_graph_export_publish_records,
    build_graph_generated_purge_plan,
    filter_graph_export_payload_by_entity_popularity,
)


def _sample_graph_payload() -> dict:
    return {
        "snapshot": {"extractor_id": "ner-entities", "snapshot_id": "snap-001"},
        "manifest": {
            "graph_id": "graph-001",
            "extraction_snapshot": "pipeline:demo",
            "configuration": {"extractor_id": "ner-entities"},
        },
        "nodes": [
            {"node_id": "item:doc-1", "node_type": "item", "label": "Doc 1", "properties": {"item_id": "doc-1"}},
            {"node_id": "ent:ai", "node_type": "entity", "label": "AI", "properties": {"canonical": "Artificial Intelligence"}},
            {"node_id": "ent:ml", "node_type": "entity", "label": "ML", "properties": {"canonical": "Machine Learning"}},
        ],
        "edges": [
            {"edge_id": "edge-1", "src": "item:doc-1", "dst": "ent:ai", "edge_type": "mentions", "item_id": "doc-1", "weight": 0.9},
            {"edge_id": "edge-2", "src": "ent:ai", "dst": "ent:ml", "edge_type": "broader_than", "weight": 0.4},
            {"edge_id": "edge-3", "src": "ent:ml", "dst": "ent:ai", "edge_type": "edge_not_seeded", "weight": 0.3},
        ],
        "stats": {"items_processed": 1, "mentions_found": 1},
    }


class AnalysisEntityGraphBridgeTests(unittest.TestCase):
    def test_publish_plan_records_and_unresolved_diagnostics(self) -> None:
        payload = _sample_graph_payload()
        plan = build_graph_export_publish_records(
            payload,
            corpus_id="knowledge-corpus-demo",
            classifier_id=None,
            imported_at="2026-01-01T00:00:00Z",
            reference_by_external_item_id={},
        )
        model_names = [record["modelName"] for record in plan["records"]]
        self.assertEqual(model_names, ["KnowledgeImportRun", "KnowledgeArtifact", "KnowledgeRawPayload"])
        self.assertEqual(plan["mentionEdgeCount"], 1)
        self.assertEqual(plan["unresolvedReferences"], 1)
        self.assertIn("doc-1", plan["unresolvedReferenceItemIds"])

    def test_import_gate_blocks_apply_on_unresolved_reference_ids(self) -> None:
        fake_result = {
            "plan": {
                "snapshotRef": "ner-entities:snap-001",
                "importRunId": "knowledge-import-demo",
                "semanticNodeCount": 2,
                "semanticRelationCount": 1,
                "mentionEdgeCount": 3,
                "mentionRelationCount": 0,
                "unresolvedReferences": 3,
                "unresolvedReferenceItemIds": ["doc-1", "doc-2"],
                "records": [],
            },
            "attachment": {"storagePath": "knowledge/raw/payload.json.gz"},
            "changes": [],
        }
        with (
            patch("papyrus_content.analysis_commands.create_authoring_client", return_value=(object(), {})),
            patch("papyrus_content.analysis_commands.plan_graph_artifact_import", return_value=fake_result),
            patch("papyrus_content.analysis_commands.apply_record_changes") as apply_changes,
        ):
            with self.assertRaisesRegex(ValueError, "Graph import blocked"):
                _analysis_import_graph_artifact_internal("knowledge-import-demo", options={}, apply=True)
            apply_changes.assert_not_called()

    def test_graph_generated_purge_plan_collects_nodes_and_relations(self) -> None:
        class FakeClient:
            def list_knowledge_import_runs_by_corpus_kind_and_imported_at(self, _key: str):
                return [{"id": "knowledge-import-knowledge-corpus-demo-graph-ner-entities-abc"}]

            def list_semantic_nodes_by_corpus_and_node_key(self, _corpus_id: str, **_kwargs):
                return [
                    {
                        "id": "node-1",
                        "versionState": "current",
                        "importRunId": "knowledge-import-knowledge-corpus-demo-graph-ner-entities-abc",
                    }
                ]

            def list_semantic_relations_by_import_run_and_imported_at(self, _run_id: str, **_kwargs):
                return [{"id": "rel-1", "relationState": "current"}]

        with patch(
            "papyrus_content.analysis_graph.fetch_graph_artifact_rows_indexed",
            return_value=([{"importRunId": "knowledge-import-knowledge-corpus-demo-graph-ner-entities-abc"}], {}),
        ):
            plan = build_graph_generated_purge_plan(
                FakeClient(),
                corpus_id="knowledge-corpus-demo",
            )
        self.assertEqual(plan["semanticNodeIds"], ["node-1"])
        self.assertEqual(plan["semanticRelationIds"], ["rel-1"])
        deleted = apply_graph_generated_purge_plan(FakeClient(), plan, apply=False)
        self.assertEqual(deleted["deleted"]["SemanticNode"], 0)

    def test_popularity_filter_drops_low_mention_entities(self) -> None:
        payload = {
            "snapshot": {"extractor_id": "ner-entities", "snapshot_id": "snap-001"},
            "manifest": {
                "graph_id": "graph-001",
                "extraction_snapshot": "pipeline:demo",
                "configuration": {"extractor_id": "ner-entities"},
            },
            "nodes": [
                {"node_id": "item:doc-1", "node_type": "item", "label": "Doc 1", "properties": {"item_id": "doc-1"}},
                {"node_id": "item:doc-2", "node_type": "item", "label": "Doc 2", "properties": {"item_id": "doc-2"}},
                {"node_id": "ent:ai", "node_type": "entity", "label": "AI", "properties": {"entity_type": "ORG"}},
                {"node_id": "ent:ml", "node_type": "entity", "label": "ML", "properties": {"entity_type": "ORG"}},
            ],
            "edges": [
                {"edge_id": "m1", "src": "item:doc-1", "dst": "ent:ai", "edge_type": "mentions", "item_id": "doc-1", "weight": 5},
                {"edge_id": "m2", "src": "item:doc-2", "dst": "ent:ai", "edge_type": "mentions", "item_id": "doc-2", "weight": 4},
                {"edge_id": "m3", "src": "item:doc-1", "dst": "ent:ml", "edge_type": "mentions", "item_id": "doc-1", "weight": 1},
                {"edge_id": "r1", "src": "ent:ai", "dst": "ent:ml", "edge_type": "related_to", "weight": 1},
            ],
        }
        filtered, stats = filter_graph_export_payload_by_entity_popularity(payload, min_reference_count=2)
        kept_ids = {node["node_id"] for node in filtered["nodes"]}
        self.assertEqual(kept_ids, {"ent:ai"})
        self.assertEqual(stats["entitiesAfter"], 1)
        self.assertEqual(len(filtered["edges"]), 2)
        import_plan = build_graph_export_import_records(
            filtered,
            corpus_id="knowledge-corpus-demo",
            classifier_id="classifier-demo",
            imported_at="2026-01-01T00:00:00Z",
            reference_by_external_item_id={
                "doc-1": {"id": "reference-doc-1-v3", "lineageId": "reference-doc-1", "versionNumber": 3},
                "doc-2": {"id": "reference-doc-2-v1", "lineageId": "reference-doc-2", "versionNumber": 1},
            },
        )
        semantic_nodes = [record["expected"] for record in import_plan["records"] if record["modelName"] == "SemanticNode"]
        self.assertEqual(len(semantic_nodes), 1)
        self.assertEqual(semantic_nodes[0]["displayName"], "AI")
        self.assertEqual(semantic_nodes[0]["acceptedReferenceMentionCount"], 9)
        self.assertEqual(semantic_nodes[0]["distinctSourceKindCount"], 2)
        self.assertEqual(semantic_nodes[0]["description"], "entity: ORG")
        relation_rows = [record["expected"] for record in import_plan["records"] if record["modelName"] == "SemanticRelation"]
        mentions = [row for row in relation_rows if row.get("predicate") == "mentions"]
        self.assertEqual(len(mentions), 2)
        self.assertEqual(import_plan["mentionRelationCount"], 2)

    def test_import_mapping_preserves_mentions_and_typed_edges(self) -> None:
        payload = _sample_graph_payload()
        plan = build_graph_export_import_records(
            payload,
            corpus_id="knowledge-corpus-demo",
            classifier_id="classifier-demo",
            imported_at="2026-01-01T00:00:00Z",
            reference_by_external_item_id={
                "doc-1": {
                    "id": "reference-doc-1-v3",
                    "lineageId": "reference-doc-1",
                    "versionNumber": 3,
                }
            },
        )
        relation_rows = [record["expected"] for record in plan["records"] if record["modelName"] == "SemanticRelation"]
        self.assertGreaterEqual(len(relation_rows), 3)
        mentions = [row for row in relation_rows if row.get("predicate") == "mentions"]
        self.assertGreaterEqual(len(mentions), 1)
        typed = [row for row in relation_rows if row.get("subjectKind") == "semanticNode" and row.get("objectKind") == "semanticNode"]
        self.assertTrue(any(row.get("predicate") == "broader_than" for row in typed))
        self.assertTrue(any(row.get("predicate") == "related_to" for row in typed))

    def test_publish_command_creates_graph_export_attachment_metadata(self) -> None:
        payload = _sample_graph_payload()
        captured_records: dict[str, list[dict]] = {}

        def capture_changes(_client, records):
            captured_records["records"] = records
            return [{"action": "create", "modelName": record["modelName"], "expected": record["expected"]} for record in records]

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = pathlib.Path(temp_dir) / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            with (
                patch("papyrus_content.analysis_commands.require_steering_config", return_value={"configPath": "test"}),
                patch(
                    "papyrus_content.analysis_commands.require_corpus_config",
                    return_value={"key": "demo", "path": "corpora/demo"},
                ),
                patch("papyrus_content.analysis_commands._resolve_snapshot_manifest_path", return_value=manifest),
                patch("papyrus_content.analysis_commands._preflight_biblicus_catalog_compatibility"),
                patch("papyrus_content.analysis_commands._export_graph_snapshot_payload", return_value=payload),
                patch("papyrus_content.analysis_commands._validate_graph_export_payload"),
                patch("papyrus_content.analysis_commands.create_authoring_client", return_value=(object(), {})),
                patch("papyrus_content.analysis_commands.hydrate_graph_reference_map_sync", return_value={}),
                patch(
                    "papyrus_content.analysis_commands.build_record_changes_tolerating_optional_models",
                    side_effect=capture_changes,
                ),
            ):
                result = _analysis_publish_graph_snapshot_internal(
                    corpus_key="demo",
                    snapshot_ref="ner-entities:snap-001",
                    options={"biblicus-workdir": temp_dir},
                    apply=False,
                )
        self.assertEqual(result["command"], "analysis publish-graph-snapshot")
        records = captured_records["records"]
        attachments = [record for record in records if record["modelName"] == "ModelAttachment"]
        self.assertEqual(len(attachments), 1)
        attachment = attachments[0]["expected"]
        self.assertEqual(attachment["role"], "graph_export")
        self.assertEqual(attachment["ownerKind"], "knowledgeRawPayload")
        self.assertTrue(str(attachment.get("filename") or "").endswith(".json.gz"))

    def test_extract_last_json_parses_multiline_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = pathlib.Path(temp_dir) / "graph-extract.stdout.log"
            log_path.write_text(
                "\n".join(
                    [
                        "[graph] starting snapshot abc",
                        "[graph] completed snapshot abc",
                        "{",
                        '  "snapshot_id": "abc",',
                        '  "stats": {',
                        '    "items_processed": 20',
                        "  }",
                        "}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            parsed = _extract_last_json_from_file(log_path)
        self.assertEqual(parsed["snapshot_id"], "abc")
        self.assertEqual(parsed["stats"]["items_processed"], 20)

    def test_entity_graph_run_now_preflight_blocks_placeholder_snapshot(self) -> None:
        with self.assertRaisesRegex(ValueError, "resolved extraction snapshot"):
            _assert_entity_graph_run_ready(
                {
                    "effectiveParameters": {"extractionSnapshot": "pipeline:<canonical-topic-text-snapshot>"},
                }
            )

    def test_import_apply_chunked_and_resumable(self) -> None:
        fake_changes = [
            {
                "action": "create",
                "modelName": "SemanticNode",
                "expected": {"id": f"semantic-node-{index}"},
            }
            for index in range(5)
        ]
        fake_result = {
            "plan": {
                "snapshotRef": "ner-entities:snap-001",
                "importRunId": "knowledge-import-demo",
                "semanticNodeCount": 5,
                "semanticRelationCount": 0,
                "mentionEdgeCount": 0,
                "mentionRelationCount": 0,
                "unresolvedReferences": 0,
                "unresolvedReferenceItemIds": [],
                "records": [],
            },
            "attachment": {"storagePath": "knowledge/raw/payload.json.gz"},
            "changes": fake_changes,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint = pathlib.Path(temp_dir) / "checkpoint.json"
            first_pass_calls: list[list[str]] = []

            def first_pass_apply(_client, changes):
                first_pass_calls.append([change["expected"]["id"] for change in changes])
                if len(first_pass_calls) == 2:
                    raise RuntimeError("boom on second chunk")

            with (
                patch("papyrus_content.analysis_commands.create_authoring_client", return_value=(object(), {})),
                patch("papyrus_content.analysis_commands.plan_graph_artifact_import", return_value=fake_result),
                patch("papyrus_content.analysis_commands.update_newsroom_summary_after_analysis_import"),
                patch("papyrus_content.newsroom_commands.apply_newsroom_summary_recount"),
                patch("papyrus_content.analysis_commands.apply_record_changes", side_effect=first_pass_apply),
            ):
                with self.assertRaisesRegex(RuntimeError, "boom on second chunk"):
                    _analysis_import_graph_artifact_internal(
                        "knowledge-import-demo",
                        options={"chunk-size": "2", "checkpoint": str(checkpoint), "resume": "true"},
                        apply=True,
                    )
            self.assertTrue(checkpoint.exists())
            second_pass_calls: list[list[str]] = []
            with (
                patch("papyrus_content.analysis_commands.create_authoring_client", return_value=(object(), {})),
                patch("papyrus_content.analysis_commands.plan_graph_artifact_import", return_value=fake_result),
                patch("papyrus_content.analysis_commands.update_newsroom_summary_after_analysis_import"),
                patch("papyrus_content.newsroom_commands.apply_newsroom_summary_recount"),
                patch(
                    "papyrus_content.analysis_commands.apply_record_changes",
                    side_effect=lambda _client, changes: second_pass_calls.append([change["expected"]["id"] for change in changes]),
                ),
            ):
                _analysis_import_graph_artifact_internal(
                    "knowledge-import-demo",
                    options={"chunk-size": "2", "checkpoint": str(checkpoint), "resume": "true"},
                    apply=True,
                )
            self.assertEqual(second_pass_calls, [["semantic-node-2", "semantic-node-3"], ["semantic-node-4"]])
            self.assertFalse(checkpoint.exists())

    def test_entity_graph_preflight_reports_unresolved_snapshot_blocker(self) -> None:
        with patch("papyrus_content.analysis_commands._build_analysis_reindex_plan_from_options") as build_plan:
            build_plan.return_value = {
                "profile": {"scope": "entity-graph"},
                "corpus": {"id": "knowledge-corpus-demo", "key": "demo"},
                "biblicusWorkdir": "/tmp",
                "effectiveParameters": {"extractionSnapshot": "pipeline:<placeholder>"},
            }
            with (
                patch("papyrus_content.analysis_commands.require_steering_config", return_value={"configPath": "test"}),
                patch("papyrus_content.analysis_commands.require_corpus_config", return_value={"key": "demo", "path": "corpora/demo"}),
                patch("papyrus_content.analysis_commands._preflight_biblicus_catalog_compatibility"),
                patch("papyrus_content.analysis_commands.create_authoring_client", return_value=(object(), {})),
                patch("papyrus_content.analysis_commands.hydrate_graph_reference_map_sync", return_value={}),
            ):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    analysis_entity_graph_preflight(["--profile", "reference-entity-graph", "--json"])
                result = json.loads(buffer.getvalue())
        self.assertFalse(result["ok"])
        self.assertIn("unresolved_extraction_snapshot", result["blockers"])


if __name__ == "__main__":
    unittest.main()
