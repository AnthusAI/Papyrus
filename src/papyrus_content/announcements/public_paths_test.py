"""A Story's link follows the address the site publishes (its sitemap), not one rebuilt from the section and slug (PPY-1905cc)."""
from __future__ import annotations

import pytest

from papyrus_content.announcements import public_paths

ORIGIN = "https://news.example"
SITEMAP = """<urlset><url><loc>https://news.example/</loc></url><url><loc>https://news.example/articles/the-eternal-october/</loc></url>
<url><loc>https://news.example/es/articulos/the-eternal-october/</loc></url><url><loc>https://news.example/articles/slow-water/</loc></url></urlset>"""


@pytest.fixture(autouse=True)
def empty_cache():
    public_paths._cache.clear()


def site(text=SITEMAP, calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        return text
    return fetch


def test_the_published_address_replaces_a_rebuilt_one_that_does_not_exist():
    assert public_paths.published_path(ORIGIN, "the-eternal-october", "/security/the-eternal-october.html", fetch=site()) == "/articles/the-eternal-october/"


def test_a_rebuilt_address_the_site_publishes_is_kept():
    assert public_paths.published_path(ORIGIN, "slow-water", "/articles/slow-water/", fetch=site()) == "/articles/slow-water/"


def test_an_unknown_slug_or_an_unreadable_sitemap_keeps_the_rebuilt_address():
    assert public_paths.published_path(ORIGIN, "missing", "/x/missing.html", fetch=site()) == "/x/missing.html"

    def broken(url):
        raise OSError("down")
    public_paths._cache.clear()
    assert public_paths.published_path(ORIGIN, "slow-water", "/security/slow-water.html", fetch=broken) == "/security/slow-water.html"


def test_two_pages_of_the_same_length_with_the_slug_are_ambiguous_and_keep_the_rebuilt_address():
    text = "<urlset><url><loc>https://news.example/a/same/</loc></url><url><loc>https://news.example/b/same/</loc></url></urlset>"
    assert public_paths.published_path(ORIGIN, "same", "/c/same.html", fetch=site(text)) == "/c/same.html"


def test_a_sitemap_index_is_followed_and_the_sitemap_is_read_once():
    calls = []
    def fetch(url):
        calls.append(url)
        return "<sitemapindex><sitemap><loc>https://news.example/sitemap-1.xml</loc></sitemap></sitemapindex>" if url.endswith("/sitemap.xml") else SITEMAP
    assert public_paths.published_path(ORIGIN, "slow-water", "/s/slow-water.html", fetch=fetch) == "/articles/slow-water/"
    assert public_paths.published_path(ORIGIN, "the-eternal-october", "/s/x.html", fetch=fetch) == "/articles/the-eternal-october/"
    assert calls == ["https://news.example/sitemap.xml", "https://news.example/sitemap-1.xml"]


def test_no_origin_means_no_lookup():
    assert public_paths.published_path("", "slow-water", "/s/slow-water.html", fetch=site()) == "/s/slow-water.html"
