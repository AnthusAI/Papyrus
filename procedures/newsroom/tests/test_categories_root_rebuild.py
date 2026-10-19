import pathlib
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.categories_commands import (  # noqa: E402
    build_root_description,
    categories_rebuild_roots,
    parse_root_range_option,
    select_root_topic_candidates,
)


class CategoriesRootRebuildTests(unittest.TestCase):
    def test_parse_root_range_option_defaults(self) -> None:
        self.assertEqual(parse_root_range_option(None), (12, 20))

    def test_parse_root_range_option_rejects_invalid(self) -> None:
        with self.assertRaises(ValueError):
            parse_root_range_option("abc")
        with self.assertRaises(ValueError):
            parse_root_range_option("20:12")
        with self.assertRaises(ValueError):
            parse_root_range_option("0:12")

    def test_select_root_topic_candidates_filters_ignored_terms(self) -> None:
        topics = [
            {
                "topic_id": 1,
                "label": "research",
                "document_count": 120,
                "document_ids": ["doc-1", "doc-2"],
                "keywords": [{"keyword": "research", "score": 0.9}],
            },
            {
                "topic_id": 2,
                "label": "Large language model methods",
                "document_count": 95,
                "document_ids": ["doc-3", "doc-4"],
                "keywords": [
                    {"keyword": "language models", "score": 0.91},
                    {"keyword": "reasoning", "score": 0.75},
                ],
            },
            {
                "topic_id": 3,
                "label": "document candidate",
                "document_count": 60,
                "document_ids": ["doc-5"],
                "keywords": [{"keyword": "document", "score": 0.8}, {"keyword": "candidate", "score": 0.7}],
            },
        ]
        result = select_root_topic_candidates(
            topics=topics,
            ignored_terms=["et", "al", "document", "candidate", "research"],
            root_min=1,
            root_max=20,
        )
        self.assertEqual(result["selectedCount"], 1)
        self.assertEqual(result["selected"][0]["categoryKey"], "language_models")
        skipped_labels = {entry["label"] for entry in result["skipped"]}
        self.assertIn("research", skipped_labels)
        self.assertIn("document candidate", skipped_labels)

    def test_select_root_topic_candidates_respects_max_selection(self) -> None:
        topics = []
        for index in range(30):
            topics.append(
                {
                    "topic_id": index + 1,
                    "label": f"topic {index + 1}",
                    "document_count": 100 - index,
                    "document_ids": [f"doc-{index + 1}"],
                    "keywords": [{"keyword": f"keyword {index + 1}", "score": 1 - (index * 0.01)}],
                }
            )
        result = select_root_topic_candidates(topics=topics, ignored_terms=[], root_min=12, root_max=20)
        self.assertEqual(result["candidateCount"], 30)
        self.assertEqual(result["selectedCount"], 20)

    def test_build_root_description_omits_old_bertopic_boilerplate(self) -> None:
        description = build_root_description("Reasoning", ["reasoning", "agents"])
        self.assertNotIn("Root topic candidate discovered from corpus-level BERTopic analysis", description)
        self.assertIn("Keywords:", description)

    @mock.patch("papyrus_content.categories_commands.select_root_topic_candidates")
    @mock.patch("papyrus_content.categories_commands.run_biblicus")
    @mock.patch("papyrus_content.categories_commands.latest_pipeline_snapshot")
    @mock.patch("papyrus_content.categories_commands.load_steering_bundle_from_biblicus")
    @mock.patch("papyrus_content.categories_commands.resolve_accepted_category_set")
    @mock.patch("papyrus_content.categories_commands.create_authoring_client")
    @mock.patch("papyrus_content.categories_commands.resolve_biblicus_corpus_path")
    @mock.patch("papyrus_content.categories_commands.timestamp_run_id")
    @mock.patch("papyrus_content.categories_commands.load_lexical_steering_config")
    @mock.patch("papyrus_content.categories_commands.resolve_classifier_for_corpus")
    @mock.patch("papyrus_content.categories_commands.require_corpus_config")
    @mock.patch("papyrus_content.categories_commands.require_steering_config")
    def test_categories_rebuild_roots_fails_when_selected_below_minimum(
        self,
        mock_require_steering_config,
        mock_require_corpus_config,
        mock_resolve_classifier,
        mock_load_lexical,
        mock_timestamp_run_id,
        mock_resolve_corpus_path,
        mock_create_authoring_client,
        mock_resolve_accepted_category_set,
        mock_load_bundle,
        mock_latest_snapshot,
        mock_run_biblicus,
        mock_select_candidates,
    ) -> None:
        mock_require_steering_config.return_value = {
            "canonicalTopicSet": {"corpusKey": "demo-corpus", "classifierId": "demo-classifier"},
            "corpora": [{"key": "demo-corpus", "path": "/tmp/corpus"}],
        }
        mock_require_corpus_config.return_value = {"key": "demo-corpus", "path": "/tmp/corpus"}
        mock_resolve_classifier.return_value = "demo-classifier"
        mock_load_lexical.return_value = {"ignoredTerms": []}
        mock_timestamp_run_id.return_value = "20260529T000000Z"
        mock_load_bundle.return_value = {"runs": []}
        mock_latest_snapshot.return_value = "snapshot-1"
        mock_run_biblicus.return_value = '{"report":{"topics":[]}}'
        mock_select_candidates.return_value = {"selected": []}

        class _FakeClient:
            def list_records(self, model_name: str):
                if model_name == "CategorySet":
                    return [{"id": "set-1", "lineageId": "set-lineage-1"}]
                if model_name == "Category":
                    return []
                if model_name in {"SteeringProposal", "SteeringDecision"}:
                    return []
                return []

        mock_create_authoring_client.return_value = (_FakeClient(), None)
        mock_resolve_accepted_category_set.return_value = {
            "id": "set-1",
            "lineageId": "set-lineage-1",
            "corpusId": "knowledge-corpus-demo",
            "classifierId": "demo-classifier",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            corpus_path = pathlib.Path(tmpdir) / "corpus"
            corpus_path.mkdir(parents=True, exist_ok=True)
            mock_resolve_corpus_path.return_value = corpus_path
            with mock.patch.dict("os.environ", {"BIBLICUS_WORKDIR": tmpdir}), self.assertRaises(ValueError):
                categories_rebuild_roots(["--yes", "--dry-run", "--output-dir", str(pathlib.Path(tmpdir) / "run")])


if __name__ == "__main__":
    unittest.main()
