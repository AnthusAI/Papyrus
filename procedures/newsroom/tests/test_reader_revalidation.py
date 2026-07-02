from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from papyrus_content.reader_revalidation import trigger_reader_cache_revalidation


class ReaderRevalidationTests(unittest.TestCase):
    @patch("papyrus_content.reader_revalidation.urllib.request.urlopen")
    def test_trigger_reader_cache_revalidation_posts_edition_payload(self, urlopen_mock) -> None:
        response = urlopen_mock.return_value.__enter__.return_value
        response.read.return_value = json.dumps({"ok": True, "revalidatedPaths": ["/2026/june/28"]}).encode("utf-8")

        with patch.dict(
            "os.environ",
            {
                "PAPYRUS_BASE_URL": "http://localhost:3001",
                "PAPYRUS_REVALIDATE_SECRET": "test-secret",
            },
            clear=False,
        ):
            result = trigger_reader_cache_revalidation(
                edition_date="2026-06-28",
                article_slugs=["sample-story"],
            )

        self.assertEqual(result, {"ok": True, "revalidatedPaths": ["/2026/june/28"]})
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:3001/api/revalidate")
        self.assertEqual(request.get_header("X-papyrus-revalidate-secret"), "test-secret")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["editionDate"], "2026-06-28")
        self.assertEqual(payload["articleSlugs"], ["sample-story"])

    def test_trigger_reader_cache_revalidation_skips_without_config(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "papyrus_content.reader_revalidation.resolve_reader_cache_revalidate_secret",
                return_value=None,
            ),
            patch(
                "papyrus_content.reader_revalidation.resolve_reader_revalidation_base_url",
                return_value="",
            ),
        ):
            self.assertIsNone(
                trigger_reader_cache_revalidation(
                    edition_date="2026-06-28",
                    article_slugs=["sample-story"],
                ),
            )


if __name__ == "__main__":
    unittest.main()
