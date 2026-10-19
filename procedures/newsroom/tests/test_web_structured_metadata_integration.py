"""Integration tests for shared web structured metadata, run through the installed Biblicus console script."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from papyrus_content import web_structured_metadata
from papyrus_content.biblicus_runner import BiblicusRunner
from papyrus_content.catalog import normalize_catalog_reference_item
from papyrus_content.source_site_plugins import resolve_source_site_enrichment
from papyrus_newsroom import reference_curation_signals

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "web_metadata"
_BLOG_FIXTURE = _FIXTURES / "synthetic_blog_json_ld.html"
_NEWS_FIXTURE = _FIXTURES / "synthetic_news_open_graph.html"


class WebStructuredMetadataIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        workdir = tempfile.TemporaryDirectory()
        self.addCleanup(workdir.cleanup)
        environment = patch.dict(os.environ, {"BIBLICUS_WORKDIR": workdir.name})
        environment.start()
        self.addCleanup(environment.stop)

    def test_biblicus_cli_matches_python_api(self):
        html = _BLOG_FIXTURE.read_text(encoding="utf-8")
        from biblicus.api import WebMetadataRequest
        from biblicus.web_reference_metadata import extract_web_reference_metadata_from_html

        api_payload = extract_web_reference_metadata_from_html(
            html,
            source_uri="https://fixture.test/blog/post",
        )
        cli_response = BiblicusRunner.from_environment().extract_web_metadata(
            WebMetadataRequest(source_uri="https://fixture.test/blog/post", html_content=html)
        )
        self.assertEqual(cli_response.status, "ok")
        self.assertEqual(cli_response.title, api_payload.get("title"))
        self.assertEqual(cli_response.authors, api_payload.get("authors"))

    def test_papyrus_subprocess_resolves_blog_fixture(self):
        html = _BLOG_FIXTURE.read_text(encoding="utf-8")
        payload = web_structured_metadata.resolve_web_reference_metadata(
            "https://fixture.test/blog/post",
            html_content=html,
        )
        self.assertEqual(payload.get("title"), "Understanding Sequence Models")
        self.assertGreaterEqual(len(payload.get("authors") or []), 2)
        self.assertIn("json_ld", payload.get("layers") or [])

    def test_reference_curation_local_html_uses_shared_heuristics(self):
        html = _NEWS_FIXTURE.read_text(encoding="utf-8")
        resolved = reference_curation_signals._title_subtitle_from_local_html(html)
        self.assertEqual(resolved.get("title"), "Corpus Audit Checklist")
        self.assertEqual(resolved.get("source"), "local_html_metadata")

    def test_source_site_default_plugin_merges_web_metadata(self):
        html = _NEWS_FIXTURE.read_text(encoding="utf-8")

        def fetcher(_url: str, timeout: int = 20) -> str:
            return html

        enrichment = resolve_source_site_enrichment(
            reference={"id": "ref-1", "title": "", "sourceUri": "https://fixture.test/news/story"},
            source_uri="https://fixture.test/unknown-host.example/article",
            fetcher=fetcher,
        )
        metadata = enrichment.get("metadata") if isinstance(enrichment.get("metadata"), dict) else {}
        self.assertTrue(metadata.get("title") or metadata.get("webStructuredMetadata"))


class WebStructuredMetadataConfigurationTests(unittest.TestCase):
    def test_missing_workdir_raises_clear_error(self):
        with patch.dict(os.environ):
            os.environ.pop("BIBLICUS_WORKDIR", None)
            with self.assertRaises(web_structured_metadata.WebStructuredMetadataError) as ctx:
                web_structured_metadata.resolve_web_reference_metadata(
                    "https://example.test/article",
                    html_content="<html><title>Hi</title></html>",
                )
        self.assertEqual(ctx.exception.reason.get("code"), "biblicus_runner_failed")
        self.assertIn("BIBLICUS_WORKDIR is required", ctx.exception.reason.get("message"))


if __name__ == "__main__":
    unittest.main()
