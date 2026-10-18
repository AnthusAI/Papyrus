from __future__ import annotations

import pathlib
import tempfile
import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content import ontology_enrichment as ontology
from papyrus_knowledge_query import vector_index


def semantic_node(node_id: str, key: str, name: str) -> dict:
    return {
        "id": node_id,
        "lineageId": f"lineage-{node_id}",
        "versionNumber": 1,
        "versionState": "current",
        "nodeKey": key,
        "nodeKind": "entity",
        "displayName": name,
        "description": "",
        "aliases": [],
        "status": "active",
        "updatedAt": "2026-01-01T00:00:00Z",
    }


def relation(rel_id: str, subject_kind: str, subject_id: str, subject_lineage: str, predicate: str, object_id: str, object_lineage: str) -> dict:
    return {
        "id": rel_id,
        "relationState": "current",
        "predicate": predicate,
        "relationTypeKey": predicate,
        "relationDomain": "ontology",
        "subjectKind": subject_kind,
        "subjectId": subject_id,
        "subjectLineageId": subject_lineage,
        "subjectVersionNumber": 1,
        "objectKind": "semanticNode",
        "objectId": object_id,
        "objectLineageId": object_lineage,
        "objectVersionNumber": 1,
        "subjectStateKey": f"{subject_kind}#{subject_lineage}#current",
        "objectStateKey": f"semanticNode#{object_lineage}#current",
        "objectSubjectStateKey": f"semanticNode#{object_lineage}#current#{subject_kind}",
        "predicateObjectStateKey": f"{predicate}#semanticNode#{object_lineage}#current",
        "subjectVersionKey": f"{subject_kind}#{subject_id}",
        "objectVersionKey": f"semanticNode#{object_id}",
        "updatedAt": "2026-01-01T00:00:00Z",
    }


class OntologyEnrichmentTests(unittest.TestCase):
    def build_state(self) -> dict:
        node_a = semantic_node("node-a", "entity.alpha", "Alpha")
        node_b = semantic_node("node-b", "entity.beta", "Beta")
        rel_a1 = relation("rel-a1", "reference", "ref-1", "ref-lineage-1", "mentions", "node-a", node_a["lineageId"])
        rel_a2 = relation("rel-a2", "reference", "ref-2", "ref-lineage-2", "mentions", "node-a", node_a["lineageId"])
        rel_b1 = relation("rel-b1", "reference", "ref-3", "ref-lineage-3", "mentions", "node-b", node_b["lineageId"])
        return ontology.build_state_indexes(
            {
                "SemanticNode": [node_a, node_b],
                "SemanticRelation": [rel_a1, rel_a2, rel_b1],
                "Reference": [
                    {"id": "ref-1", "lineageId": "ref-lineage-1", "versionState": "current", "title": "Reference 1"},
                    {"id": "ref-2", "lineageId": "ref-lineage-2", "versionState": "current", "title": "Reference 2"},
                    {"id": "ref-3", "lineageId": "ref-lineage-3", "versionState": "current", "title": "Reference 3"},
                ],
                "Message": [],
                "Assignment": [],
                "AssignmentEvent": [],
                "Item": [],
                "Category": [],
                "CategorySet": [],
                "SteeringProposal": [],
                "NewsroomSection": [],
                "ModelAttachment": [],
                "SemanticRelationType": [
                    {"key": "mentions"},
                    {"key": "explains_relation"},
                    {"key": "note_about"},
                    {"key": "same_as"},
                    {"key": "alias_of"},
                    {"key": "related_to"},
                ],
            }
        )

    def test_rank_prioritizes_high_connectivity_concepts(self):
        ranked = ontology.rank_concepts(self.build_state())
        self.assertEqual(ranked[0]["id"], "node-a")
        self.assertGreater(ranked[0]["acceptedReferenceMentions"], ranked[1]["acceptedReferenceMentions"])

    def test_rank_concepts_tie_breaks_by_node_key(self):
        node_a = semantic_node("node-a", "entity.alpha", "Alpha")
        node_b = semantic_node("node-b", "entity.beta", "Beta")
        state = ontology.build_state_indexes(
            {
                "SemanticNode": [node_b, node_a],
                "SemanticRelation": [],
                "Reference": [],
                "Message": [],
                "Assignment": [],
                "AssignmentEvent": [],
                "Item": [],
                "Category": [],
                "CategorySet": [],
                "SteeringProposal": [],
                "NewsroomSection": [],
                "ModelAttachment": [],
                "SemanticRelationType": [],
            }
        )
        ranked = ontology.rank_concepts(state, include_profile_status=False)
        self.assertEqual([row["nodeKey"] for row in ranked], ["entity.alpha", "entity.beta"])

    def test_rank_concepts_excludes_operational_relations_by_default(self):
        state = self.build_state()
        node_b = state["models"]["SemanticNode"][1]
        state["models"]["SemanticRelation"].append(
            relation(
                "rel-operational",
                "assignment",
                "assign-1",
                "assign-lineage-1",
                "blocked_by",
                node_b["id"],
                node_b["lineageId"],
            )
        )
        excluded = ontology.rank_concepts(state, include_profile_status=False)
        included = ontology.rank_concepts(state, include_profile_status=False, include_operational=True)
        excluded_b = next(row for row in excluded if row["id"] == node_b["id"])
        included_b = next(row for row in included if row["id"] == node_b["id"])
        self.assertEqual(excluded_b["relationCount"], 1)
        self.assertEqual(included_b["relationCount"], 2)

    def test_build_concept_authority_records_materializes_counts_and_rank(self):
        state = self.build_state()
        ranked = ontology.rank_concepts(state, include_profile_status=False)
        scoped = ontology.scoped_ranked_concepts(state, ranked, options={})
        records = ontology.build_concept_authority_records(state, scoped)
        self.assertEqual(len(records), 2)
        first = records[0]["expected"]
        self.assertEqual(first["id"], "node-a")
        self.assertEqual(first["authorityRank"], 1)
        self.assertEqual(first["acceptedReferenceMentionCount"], 2)
        self.assertIn("authorityScore", first)
        self.assertIn("distinctSourceKindCount", first)
        self.assertIn("relationCount", first)

    def test_relation_status_freshness_uses_fingerprint(self):
        state = self.build_state()
        rel = state["models"]["SemanticRelation"][0]
        fingerprint = ontology.relation_explanation_fingerprint(state, rel)
        attachment = {
            "id": "attachment-1",
            "ownerKind": "semanticRelation",
            "ownerId": rel["id"],
            "role": ontology.RELATION_EXPLANATION_ROLE,
            "sortKey": "current",
            "status": "active",
            "sha256": "sha",
            "updatedAt": "2026-01-01T00:00:00Z",
        }
        state["attachments"].append(attachment)
        state["attachmentsByOwnerRole"][("semanticRelation", rel["id"], ontology.RELATION_EXPLANATION_ROLE)].append(attachment)
        state["attachmentPayloads"]["attachment-1"] = {"inputFingerprint": fingerprint, "output": {"meaning": "Alpha relation explanation."}}
        self.assertEqual(ontology.relation_explanation_status(state, [rel])[0]["status"], "fresh")
        rel["updatedAt"] = "2026-01-02T00:00:00Z"
        self.assertEqual(ontology.relation_explanation_status(state, [rel])[0]["status"], "stale")

    def test_build_relation_explanation_records_attach_to_semantic_relation(self):
        state = self.build_state()
        rel = state["models"]["SemanticRelation"][0]
        context = ontology.build_relation_context(
            state,
            rel,
            input_fingerprint=ontology.relation_explanation_fingerprint(state, rel),
        )
        records = ontology.build_relation_explanation_records(
            rel,
            context,
            {"meaning": "Reference 1 mentions Alpha as an entity.", "confidence": 0.91, "model": "test-model"},
            now="2026-01-01T00:00:00Z",
        )
        by_model = {record["modelName"]: record for record in records}
        self.assertEqual(by_model["ModelAttachment"]["expected"]["ownerKind"], "semanticRelation")
        self.assertEqual(by_model["ModelAttachment"]["expected"]["role"], ontology.RELATION_EXPLANATION_ROLE)
        self.assertEqual(by_model["SemanticRelation"]["expected"]["relationTypeKey"], "explains_relation")
        self.assertEqual(by_model["Message"]["expected"]["messageKind"], "ontology_relation_explanation")

    def test_concept_profile_status_depends_on_relation_explanations(self):
        state = self.build_state()
        concept = state["models"]["SemanticNode"][0]
        missing = ontology.concept_profile_status(state, [concept])[0]
        self.assertEqual(missing["status"], "missing")
        self.assertGreater(missing["missingRelationExplanations"], 0)

    def test_ontology_vector_from_payload_emits_metadata(self):
        attachment = {
            "ownerKind": "semanticNode",
            "ownerId": "node-a",
            "ownerLineageId": "lineage-node-a",
            "role": "ontology_concept_profile",
        }
        candidate = vector_index._ontology_vector_from_payload(
            attachment,
            {
                "artifactKind": "ontology_concept_profile",
                "inputFingerprint": "fingerprint-1",
                "conceptId": "node-a",
                "conceptLineageId": "lineage-node-a",
                "generatedAt": "2026-01-01T00:00:00Z",
                "output": {
                    "meaning": "Alpha is a concept profile with enough text to be vector indexed for retrieval and deduplication.",
                    "confidence": 0.88,
                },
            },
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["metadata"]["vectorKind"], "ontology_concept_profile")
        self.assertEqual(candidate["metadata"]["inputFingerprint"], "fingerprint-1")

    def test_rank_concepts_can_skip_profile_status_scan(self):
        state = self.build_state()
        with mock.patch.object(ontology, "concept_profile_status", side_effect=RuntimeError("should-not-run")):
            ranked = ontology.rank_concepts(state, include_profile_status=False)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["profileStatus"], "missing")

    def test_run_tactus_json_procedure_failure_reports_target_and_excerpt(self):
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            mock.patch("papyrus_content.ontology_enrichment.subprocess.run") as run,
        ):
            procedure_path = pathlib.Path(tmpdir) / "fake-procedure.tac"
            procedure_path.write_text("Procedure {}", encoding="utf-8")
            run.return_value = mock.Mock(
                returncode=1,
                stdout="stdout line one\nstdout line two",
                stderr="stderr line one\nstderr line two",
            )
            with self.assertRaises(RuntimeError) as raised:
                ontology.run_tactus_json_procedure(
                    procedure_path,
                    {"context_json": {"id": "x"}},
                    markers=("relation_explanation",),
                    target_kind="relation",
                    target_id="semantic-relation-1",
                )
        message = str(raised.exception)
        self.assertIn("target=relation:semantic-relation-1", message)
        self.assertIn(str(procedure_path), message)
        self.assertIn("stderr line two", message)

    def test_emit_ontology_llm_failure_prints_next_commands(self):
        stderr = StringIO()
        with redirect_stderr(stderr):
            ontology._emit_ontology_llm_failure(
                command="ontology-explain",
                target_kind="relation",
                target_id="semantic-relation-1",
                error=RuntimeError("boom"),
                next_commands=[
                    "poetry run papyrus knowledge ontology explain --relation-id semantic-relation-1 --no-llm --apply",
                    "poetry run papyrus knowledge ontology explain --relation-id semantic-relation-1 --apply",
                ],
            )
        output = stderr.getvalue()
        self.assertIn("ontology-explain\tontology-error\tfailed", output)
        self.assertIn("ontology-explain\tontology-next\t1", output)
        self.assertIn("ontology-explain\tontology-next\t2", output)


if __name__ == "__main__":
    unittest.main()
