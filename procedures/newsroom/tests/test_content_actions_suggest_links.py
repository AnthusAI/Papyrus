from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

HANDLER_PATH = REPO_ROOT / "amplify" / "functions" / "content-actions" / "handler.py"
specification = importlib.util.spec_from_file_location("content_actions_handler_for_suggest_links", HANDLER_PATH)
content_actions = importlib.util.module_from_spec(specification)
specification.loader.exec_module(content_actions)


class SuggestReferenceLinksActionTests(unittest.TestCase):
    def test_without_the_knowledge_index_it_says_so_in_words(self):
        with mock.patch.dict(os.environ, {"PAPYRUS_S3_VECTOR_INDEX_ARN": ""}):
            result = content_actions.suggest_reference_links_action({"referenceId": "reference-a"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["message"], "Suggestions need the knowledge index.")

    def test_it_runs_suggest_for_with_the_site_index_and_no_embedding_key(self):
        captured = {}

        def fake_suggest_for(client, provider, reference_id, **options):
            captured.update(provider=provider, reference_id=reference_id, options=options)
            return {"referenceId": reference_id, "references": [], "concepts": [], "skipped": None}

        with mock.patch.dict(os.environ, {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:aws:s3vectors:us-east-1:1:bucket/b/index/i"}, clear=False), \
                mock.patch.object(content_actions, "create_authoring_client", return_value=(object(), {})), \
                mock.patch("papyrus_content.reference_suggestions.suggest_for", fake_suggest_for):
            os.environ.pop("OPENAI_API_KEY", None)
            result = content_actions.suggest_reference_links_action({"referenceId": "reference-a"})
        self.assertTrue(result["ok"])
        self.assertEqual(captured["reference_id"], "reference-a")
        self.assertEqual(captured["provider"].vector_index_arn, "arn:aws:s3vectors:us-east-1:1:bucket/b/index/i")

    def test_an_unknown_reference_is_refused_not_crashed(self):
        def missing(client, provider, reference_id, **options):
            raise ValueError(f"Reference not found: {reference_id}")

        with mock.patch.dict(os.environ, {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn"}), \
                mock.patch.object(content_actions, "create_authoring_client", return_value=(object(), {})), \
                mock.patch("papyrus_content.reference_suggestions.suggest_for", missing):
            result = content_actions.suggest_reference_links_action({"referenceId": "nope"})
        self.assertFalse(result["ok"])
        self.assertIn("Reference not found", result["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
