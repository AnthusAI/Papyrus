import unittest

from papyrus_content.relevance_priming import (normalize_priming_url, priming_item_id, priming_label,
                                               priming_request_payload_id)


class RelevancePrimingHelpersTest(unittest.TestCase):
    def test_only_https_urls_are_accepted_and_fragments_are_dropped(self):
        self.assertEqual(normalize_priming_url(" HTTPS://Example.org/A?b=1#section "), "https://example.org/A?b=1")
        for refused in ("http://example.org/a", "ftp://example.org", "example.org/a", "", None):
            with self.assertRaises(ValueError):
                normalize_priming_url(refused)

    def test_item_ids_are_stable_per_page_and_never_a_reference_id(self):
        first = priming_item_id("https://example.org/a#one")
        self.assertEqual(first, priming_item_id("https://EXAMPLE.org/a#two"))
        self.assertNotEqual(first, priming_item_id("https://example.org/b"))
        self.assertTrue(first.startswith("priming:") and len(first) == len("priming:") + 16)

    def test_the_label_must_be_one_the_cyclotron_has(self):
        self.assertEqual(priming_label({"label": "exclude"}, ["include", "exclude"]), "exclude")
        with self.assertRaisesRegex(ValueError, "include, exclude"):
            priming_label({"label": "maybe"}, ["include", "exclude"])

    def test_request_payload_ids_match_the_browser(self):
        self.assertEqual(priming_request_payload_id("Papyrus Relevance", "Req 1"),
                         "knowledge-raw-payload-cyclotron-priming-request-papyrus-relevance-req-1")


class TransientFailureTest(unittest.TestCase):
    def test_service_outage_codes_are_transient_and_source_problems_are_not(self):
        from papyrus_content.reference_url_text import is_transient_failure_reason
        for code in ("grobid_unreachable", "grobid_request_failed", "grobid_timeout", "biblicus_timeout"):
            self.assertTrue(is_transient_failure_reason({"code": code}), code)
        self.assertTrue(is_transient_failure_reason({"code": "x", "details": {"fetch_error": {"code": "grobid_unreachable"}}}))
        for code in ("empty_text", "grobid_structured_unavailable", "biblicus_cli_failed"):
            self.assertFalse(is_transient_failure_reason({"code": code}), code)

    def test_a_hung_biblicus_child_becomes_a_timeout_reason(self):
        from papyrus_content.biblicus_runner import BiblicusCommandTimeoutError
        reason = BiblicusCommandTimeoutError(command=["biblicus"], timeout_seconds=300).failure_reason()
        self.assertEqual(reason["code"], "biblicus_timeout")

    def test_url_text_extraction_is_killed_after_the_timeout(self):
        import subprocess
        from pathlib import Path
        from unittest import mock
        from papyrus_content.biblicus_runner import BiblicusCommandTimeoutError, BiblicusRunner
        from papyrus_content.reference_url_text import URL_TEXT_SUBPROCESS_TIMEOUT_SECONDS, _url_text_timeout_seconds
        self.assertGreater(URL_TEXT_SUBPROCESS_TIMEOUT_SECONDS, 120)
        self.assertEqual(_url_text_timeout_seconds(), URL_TEXT_SUBPROCESS_TIMEOUT_SECONDS)
        with mock.patch.dict("os.environ", {"PAPYRUS_URL_TEXT_TIMEOUT_SECONDS": "42"}):
            self.assertEqual(_url_text_timeout_seconds(), 42.0)
        from biblicus.api import UrlTextRequest
        runner = BiblicusRunner(workdir=Path("."), environment={}, executable=Path("biblicus"))
        with mock.patch("papyrus_content.biblicus_runner.subprocess.run",
                        side_effect=subprocess.TimeoutExpired(cmd="biblicus", timeout=7)) as run:
            with self.assertRaises(BiblicusCommandTimeoutError):
                runner.extract_url_text(UrlTextRequest(source_uri="https://example.org/a"), timeout_seconds=7)
        self.assertEqual(run.call_args.kwargs["timeout"], 7)

    def test_liveness_check_asks_grobid_and_treats_silence_as_down(self):
        import urllib.error
        from unittest import mock
        from papyrus_content.relevance_priming import grobid_is_alive
        self.assertTrue(grobid_is_alive(""))
        with mock.patch("papyrus_content.relevance_priming.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            self.assertTrue(grobid_is_alive("http://grobid.invalid:8070/"))
            self.assertEqual(urlopen.call_args.args[0], "http://grobid.invalid:8070/api/isalive")
            urlopen.side_effect = urllib.error.URLError("refused")
            self.assertFalse(grobid_is_alive("http://grobid.invalid:8070"))


if __name__ == "__main__":
    unittest.main()
