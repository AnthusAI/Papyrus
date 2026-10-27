"""PDF source text: the shared extractor, the TTAB download address, and the monitor-stories reader (no network)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
for entry in (ROOT / "src", Path(__file__).parent):
    sys.path.insert(0, str(entry))

from papyrus_content import pdf_text  # noqa: E402
from papyrus_content.ideas import source_text  # noqa: E402
from pdf_fixtures import make_pdf  # noqa: E402

DECISION = make_pdf([["In re Example Co.", "Serial No. 99 held 2026-10-20.", "The refusal is affirmed."], ["Second page has 42 findings."]])
WRAPPER = "<html><body><h1>Decision</h1><a href='/files/decision.pdf'>Download</a><a href='https://other.example/x.pdf'>Elsewhere</a></body></html>"


class PdfTextTests(unittest.TestCase):
    def test_pages_are_numbered_and_limited_to_the_range(self) -> None:
        count, pages = pdf_text.extract_pages(DECISION, 2, 2)
        self.assertEqual((count, [p["page"] for p in pages]), (2, [2]))
        self.assertIn("42 findings", pages[0]["text"])

    def test_ttab_single_slash_document_address_becomes_the_downloadable_double_slash(self) -> None:
        single = "https://ttab-reading-room.uspto.gov/ttab-document/legal-proceeding/1/decision/FINAL_2.pdf"
        double = "https://ttab-reading-room.uspto.gov/ttab-document//legal-proceeding/1/decision/FINAL_2.pdf"
        self.assertEqual(pdf_text.downloadable_url(single), double)
        self.assertEqual(pdf_text.downloadable_url(double), double)
        self.assertEqual(pdf_text.downloadable_url("https://example.org/ttab-document/a.pdf"), "https://example.org/ttab-document/a.pdf")


class ReaderTests(unittest.TestCase):
    def test_pdf_bytes_become_a_whitespace_collapsed_excerpt_within_the_limit(self) -> None:
        text = source_text.read_source_text("https://example.org/a.pdf", lambda url: DECISION, 4000)
        self.assertEqual(text, "In re Example Co. Serial No. 99 held 2026-10-20. The refusal is affirmed. Second page has 42 findings.")
        self.assertLessEqual(len(source_text.read_source_text("https://example.org/a.pdf", lambda url: DECISION, 30)), 30)

    def test_a_thin_wrapper_page_leads_to_its_own_hosts_pdf(self) -> None:
        asked = []

        def fetch(url):
            asked.append(url)
            return WRAPPER if url.endswith("/decision") else DECISION

        text = source_text.read_source_text("https://example.org/decision", fetch, 4000)
        self.assertEqual(asked, ["https://example.org/decision", "https://example.org/files/decision.pdf"])
        self.assertIn("The refusal is affirmed", text)

    def test_a_full_html_page_is_not_replaced_by_its_pdf(self) -> None:
        page = "<html><body><p>" + "A substantial paragraph of the page itself. " * 10 + "</p><a href='/x.pdf'>pdf</a></body></html>"
        asked = []
        text = source_text.read_source_text("https://example.org/p", lambda url: asked.append(url) or page, 4000)
        self.assertTrue(text.startswith("A substantial") and asked == ["https://example.org/p"])

    def test_unreadable_sources_give_none(self) -> None:
        self.assertIsNone(source_text.read_source_text("https://example.org/a", lambda url: None, 4000))
        self.assertIsNone(source_text.read_source_text("https://example.org/a", lambda url: b"%PDF-1.4 not really", 4000))
        self.assertIsNone(source_text.read_source_text("https://example.org/a", lambda url: make_pdf([[]]), 4000))
        self.assertIsNone(source_text.read_source_text("https://example.org/a", mock.Mock(side_effect=RuntimeError("boom")), 4000))
        self.assertIsNone(source_text.read_source_text("https://example.org/a", lambda url: WRAPPER if url.endswith("/a") else None, 4000))

    def test_main_pdf_link_ignores_other_hosts(self) -> None:
        self.assertEqual(source_text.main_pdf_link(WRAPPER, "https://example.org/decision"), "https://example.org/files/decision.pdf")
        self.assertIsNone(source_text.main_pdf_link("<a href='https://other.example/x.pdf'>x</a>", "https://example.org/d"))


class FetchTests(unittest.TestCase):
    def response(self, kind, body):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.headers = {"Content-Type": kind}
        response.read.side_effect = lambda size=None: body if size is None else body[:size]
        return response

    def fetch(self, url, kind, body, public=True):
        opener = mock.Mock()
        opener.open.return_value = self.response(kind, body)
        with mock.patch.object(source_text, "public_http_url", return_value=public), mock.patch("urllib.request.build_opener", return_value=opener):
            return source_text.fetch_source(url), opener

    def test_pdf_content_is_returned_as_bytes_and_html_as_text(self) -> None:
        self.assertEqual(self.fetch("https://example.org/a", "application/pdf", DECISION)[0], DECISION)
        self.assertEqual(self.fetch("https://example.org/a.pdf?x=1", "application/octet-stream", DECISION)[0], DECISION)
        self.assertEqual(self.fetch("https://example.org/a", "text/html; charset=utf-8", b"<p>hi</p>")[0], "<p>hi</p>")

    def test_other_types_fake_pdfs_and_oversize_files_are_not_read(self) -> None:
        self.assertIsNone(self.fetch("https://example.org/a", "image/png", b"x")[0])
        self.assertIsNone(self.fetch("https://example.org/a", "application/pdf", b"<html>not a pdf</html>")[0])
        with mock.patch.object(source_text, "MAXIMUM_PDF_BYTES", 10):
            self.assertIsNone(self.fetch("https://example.org/a", "application/pdf", DECISION)[0])

    def test_a_non_public_address_is_never_requested(self) -> None:
        result, opener = self.fetch("http://127.0.0.1/a.pdf", "application/pdf", DECISION, public=False)
        self.assertIsNone(result)
        opener.open.assert_not_called()

    def test_a_ttab_address_is_requested_at_its_downloadable_form(self) -> None:
        _, opener = self.fetch("https://ttab-reading-room.uspto.gov/ttab-document/legal-proceeding/1/d.pdf", "application/pdf", DECISION)
        self.assertEqual(opener.open.call_args[0][0].full_url, "https://ttab-reading-room.uspto.gov/ttab-document//legal-proceeding/1/d.pdf")

    def test_a_redirect_to_a_private_address_is_refused(self) -> None:
        handler = source_text._PublicRedirects()
        request = mock.Mock(full_url="https://example.org/a")
        with mock.patch.object(source_text, "public_http_url", return_value=False), self.assertRaises(Exception):
            handler.redirect_request(request, None, 302, "Found", {}, "http://10.0.0.1/secret")


if __name__ == "__main__":
    unittest.main()
