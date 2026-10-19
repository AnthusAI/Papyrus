import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.categories_steering import (  # noqa: E402
    build_accepted_category_set_payload,
    build_steering_import_records,
    load_steering_bundle_from_biblicus,
)


FIXTURE_PATH = REPO_ROOT / "procedures" / "newsroom" / "tests" / "fixtures" / "steering-export-minimal.json"


def _steering_export_bundle() -> dict:
    return {
        "generated_at": "2026-01-01T00:00:00Z",
        "corpus": {
            "corpus_uri": "file:///corpora/AI-ML-research",
            "corpus_path": "/corpora/AI-ML-research",
            "name": "AI-ML-research",
            "generated_at": "2026-01-01T00:00:00Z",
            "item_count": 0,
        },
    }


class CategoriesSteeringTests(unittest.TestCase):
    def test_build_steering_import_records_matches_node_fixture_shape(self):
        bundle = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        plan = build_steering_import_records(
            bundle,
            {
                "classifierId": "ai-ml-v1",
                "corpusConfig": {"key": "AI-ML-research", "name": "AI-ML-research", "role": "canonical"},
                "importedAt": "2026-01-01T12:00:00.000Z",
            },
        )
        self.assertEqual(plan["corpusId"], "knowledge-corpus-ai-ml-research")
        self.assertEqual(plan["categorySetId"], "category-set-knowledge-corpus-ai-ml-research-ai-ml-v1")
        self.assertEqual(plan["importRunId"], "knowledge-import-knowledge-corpus-ai-ml-research-ai-ml-v1-4bc31e095f4fc34e")
        self.assertEqual(len(plan["records"]), 29)
        model_names = [record["modelName"] for record in plan["records"]]
        self.assertEqual(model_names.count("Category"), 4)
        self.assertEqual(model_names.count("SemanticNode"), 12)
        self.assertEqual(model_names.count("CategorySet"), 1)
        category_set = next(record for record in plan["records"] if record["modelName"] == "CategorySet")
        self.assertEqual(category_set["expected"]["classifierId"], "ai-ml-v1")
        self.assertEqual(category_set["expected"]["categoryCount"], 2)

    def test_build_steering_import_records_respects_category_set_override(self):
        bundle = {
            "generated_at": "2026-01-01T00:00:00Z",
            "corpus": {"name": "AI-ML-research", "role": "canonical"},
            "proposals": [
                {
                    "proposal_id": "proposal-1",
                    "proposal_kind": "create-taxonomy-node",
                    "status": "proposed",
                    "title": "Create taxonomy node",
                    "display_name": "Reasoning",
                    "category_key": "reasoning",
                    "payload": {"display_name": "Reasoning", "category_key": "reasoning"},
                }
            ],
            "artifacts": [],
            "warnings": [],
        }
        plan = build_steering_import_records(
            bundle,
            {
                "classifierId": "ai-ml-v1",
                "corpusConfig": {"key": "AI-ML-research", "name": "AI-ML-research", "role": "canonical"},
                "categorySetId": "category-set-override",
            },
        )
        proposal_record = next(record for record in plan["records"] if record["modelName"] == "SteeringProposal")
        self.assertEqual(plan["categorySetId"], "category-set-override")
        self.assertEqual(proposal_record["expected"]["categorySetId"], "category-set-override")

    def test_build_accepted_category_set_payload_sorts_topics(self):
        category_set = {
            "id": "category-set-test",
            "classifierId": "ai-ml-v1",
            "displayName": "AI/ML Research",
            "description": "desc",
        }
        topics = [
            {"categoryKey": "category.nlp", "displayName": "NLP", "rank": 2},
            {"categoryKey": "category.ml", "displayName": "Machine Learning", "rank": 1},
        ]
        payload = build_accepted_category_set_payload(category_set, topics)
        self.assertEqual([topic["topic_uid"] for topic in payload["topics"]], ["category.ml", "category.nlp"])

    def test_build_steering_import_records_derives_suggested_seed_samples_from_evidence(self):
        evidence_ids = [f"item-{index}" for index in range(1, 31)]
        bundle = {
            "generated_at": "2026-01-01T00:00:00Z",
            "corpus": {"name": "AI-ML-research", "role": "canonical"},
            "proposals": [
                {
                    "proposal_id": "proposal-evidence",
                    "proposal_kind": "create-taxonomy-node",
                    "status": "proposed",
                    "title": "Evidence proposal",
                    "display_name": "Reasoning",
                    "category_key": "reasoning",
                    "evidence": {"item_ids": evidence_ids},
                    "payload": {"display_name": "Reasoning", "category_key": "reasoning", "document_ids": evidence_ids},
                }
            ],
            "artifacts": [],
            "warnings": [],
        }
        plan = build_steering_import_records(
            bundle,
            {
                "classifierId": "ai-ml-v1",
                "corpusConfig": {"key": "AI-ML-research", "name": "AI-ML-research", "role": "canonical"},
                "categorySetId": "category-set-override",
            },
        )
        proposal_record = next(record for record in plan["records"] if record["modelName"] == "SteeringProposal")
        self.assertEqual(proposal_record["expected"]["evidenceItemIds"], evidence_ids)
        self.assertEqual(proposal_record["expected"]["suggestedSeedItemIds"], evidence_ids[:20])

    def test_load_steering_bundle_from_biblicus_runs_the_console_script_in_the_workdir(self):
        from papyrus_content import biblicus_runner

        bundle_json = json.dumps(_steering_export_bundle())
        with tempfile.TemporaryDirectory() as workdir, mock.patch.object(
            biblicus_runner, "resolve_biblicus_executable", return_value=pathlib.Path("/venv/bin/biblicus")
        ), mock.patch.object(biblicus_runner.subprocess, "run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout=bundle_json, stderr="")
            bundle = load_steering_bundle_from_biblicus(
                corpus="corpora/AI-ML-research",
                classifier="ai-ml-v1",
                biblicus_workdir=workdir,
            )
            expected_workdir = pathlib.Path(workdir).resolve()
        self.assertEqual(bundle["generated_at"], "2026-01-01T00:00:00Z")
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        self.assertEqual(
            args[0],
            ["/venv/bin/biblicus", "steering", "export", "--corpus", "corpora/AI-ML-research", "--classifier", "ai-ml-v1"],
        )
        self.assertEqual(kwargs["cwd"], expected_workdir)

    def test_load_steering_bundle_from_biblicus_raises_on_failure(self):
        from papyrus_content import biblicus_runner

        with tempfile.TemporaryDirectory() as workdir, mock.patch.object(
            biblicus_runner, "resolve_biblicus_executable", return_value=pathlib.Path("/venv/bin/biblicus")
        ), mock.patch.object(biblicus_runner.subprocess, "run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="export failed")
            with self.assertRaises(RuntimeError) as context:
                load_steering_bundle_from_biblicus(
                    corpus="corpora/AI-ML-research", classifier="ai-ml-v1", biblicus_workdir=workdir
                )
        self.assertIn("Biblicus steering export failed", str(context.exception))
        self.assertIn("export failed", str(context.exception))


if __name__ == "__main__":
    unittest.main()
