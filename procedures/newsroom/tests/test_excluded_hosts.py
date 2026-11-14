"""Excluded source hosts: matching is by host suffix, so a subdomain counts and a longer name does not."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.ideas.excluded_hosts import host_of, is_excluded, normalize_hosts  # noqa: E402


class ExcludedHostTests(unittest.TestCase):
    def test_a_host_matches_itself_and_its_subdomains_only(self) -> None:
        hosts = ["ipwatchdog.com"]
        self.assertTrue(is_excluded("https://ipwatchdog.com/2026/story", hosts))
        self.assertTrue(is_excluded("https://www.IPWatchdog.com:443/x", hosts))
        self.assertTrue(is_excluded("http://a.b.ipwatchdog.com", hosts))
        self.assertFalse(is_excluded("https://notipwatchdog.com/x", hosts))
        self.assertFalse(is_excluded("https://ipwatchdog.com.evil.example/x", hosts))
        self.assertFalse(is_excluded("https://example.org/ipwatchdog.com", hosts))

    def test_a_site_path_or_nothing_has_no_host_and_is_never_excluded(self) -> None:
        self.assertEqual(host_of("/posts/x/"), "")
        self.assertFalse(is_excluded("/posts/x/", ["ipwatchdog.com"]))
        self.assertFalse(is_excluded(None, ["ipwatchdog.com"]))
        self.assertFalse(is_excluded("https://ipwatchdog.com/x", []))

    def test_hosts_are_normalised_from_addresses_commas_and_case(self) -> None:
        self.assertEqual(normalize_hosts(["https://WWW.Example.com/a", "example.com.", "b.org, c.org", ""]), ("www.example.com", "example.com", "b.org", "c.org"))
        self.assertEqual(normalize_hosts("a.com, b.com,,"), ("a.com", "b.com"))
        self.assertEqual(normalize_hosts(None), ())


if __name__ == "__main__":
    unittest.main()
