"""The <papyrus-search> ranking, run in Node against a small index."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from papyrus_content.projection.public_data import SEARCH_COMPONENT_SOURCE

INDEX = [
    {"title": "Decision models are not calculators", "url": "/posts/decision-models.html", "summary": "Why a model is not a formula", "tags": ["decisions"], "date": "2026-03-01"},
    {"title": "Cafe notes", "url": "/posts/cafe.html", "summary": "A decision about coffee", "tags": ["coffee"], "date": "2026-04-01"},
    {"title": "Gardening", "url": "/posts/garden.html", "summary": "Tomatoes", "tags": ["decision"], "date": "2026-02-01"},
    {"title": "Unsafe", "url": "//evil.example/x", "summary": "", "tags": [], "date": "2026-01-01"},
]


def run_node(expression: str):
    script = f"const search = require({json.dumps(str(SEARCH_COMPONENT_SOURCE))}); const index = {json.dumps(INDEX)}; console.log(JSON.stringify({expression}));"
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class SearchComponentTests(unittest.TestCase):
    def test_title_matches_outrank_tag_and_summary_matches(self) -> None:
        urls = run_node('search.rank(index, "decision", 10).map(e => e.url)')
        self.assertEqual(urls, ["/posts/decision-models.html", "/posts/garden.html", "/posts/cafe.html"])

    def test_every_word_must_match_and_accents_are_ignored(self) -> None:
        self.assertEqual(run_node('search.rank(index, "decision coffee", 10).map(e => e.url)'), ["/posts/cafe.html"])
        self.assertEqual(run_node('search.rank(index, "caf\\u00e9", 10).map(e => e.url)'), ["/posts/cafe.html"])
        self.assertEqual(run_node('search.rank(index, "zebra", 10)'), [])
        self.assertEqual(run_node('search.rank(index, "   ", 10)'), [])

    def test_the_limit_applies_and_only_site_addresses_are_linkable(self) -> None:
        self.assertEqual(len(run_node('search.rank(index, "decision", 1)')), 1)
        self.assertEqual(run_node('[search.isSiteAddress("/a"), search.isSiteAddress("//x.y"), search.isSiteAddress("https://x.y"), search.isSiteAddress("javascript:1")]'), [True, False, False, False])

    def test_the_script_is_one_file_shipped_with_the_package(self) -> None:
        self.assertTrue(Path(SEARCH_COMPONENT_SOURCE).is_file())
        self.assertIn("papyrus-search", Path(SEARCH_COMPONENT_SOURCE).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
