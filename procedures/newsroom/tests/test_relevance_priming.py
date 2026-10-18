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


if __name__ == "__main__":
    unittest.main()
