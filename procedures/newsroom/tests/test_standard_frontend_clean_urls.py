"""``urls.style: clean``: a page is stored as ``x.html`` and addressed, linked and indexed as ``/x``."""

from __future__ import annotations

import re

import pytest

from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.urls import UrlPolicy
from procedures.newsroom.tests.test_standard_frontend_blocks import Site

ABOUT = "---\ntitle: About\ntype: page\ndescription: About us.\naliases: [/who/]\n---\nAbout text.\n"
GUIDE = "---\ntitle: A guide\ndescription: How.\n---\nGuide text.\n"
CONFIG = {
    "site": {"name": "Example", "productionUrl": "https://example.org"},
    "urls": {"style": "clean", "sections": {"learn": {"listing": False}}},
    "listings": {"tags": False},
}


@pytest.fixture()
def clean():
    site = Site(CONFIG, {"index.md": "---\ntitle: Home\n---\nHello.\n", "about.md": ABOUT, "learn/guide.md": GUIDE})
    assert site.project_all().ok
    yield site
    site.cleanup()


def test_objects_keep_the_html_key_and_urls_drop_it(clean):
    assert (clean.out / "about.html").is_file() and (clean.out / "learn" / "guide.html").is_file()
    assert 'href="https://example.org/learn/guide"' in clean.text("learn/guide.html")
    assert '<link rel="canonical" href="https://example.org/about">' in clean.text("about.html")
    assert 'property="og:url" content="https://example.org/about"' in clean.text("about.html")


def test_the_sitemap_feeds_and_twins_use_the_clean_address(clean):
    sitemap = clean.text("sitemap.xml")
    assert "<loc>https://example.org/about</loc>" in sitemap and "<loc>https://example.org/learn/guide</loc>" in sitemap
    assert ".html</loc>" not in sitemap
    assert '<link rel="alternate" type="text/markdown" href="/about.md">' in clean.text("about.html")
    assert (clean.out / "learn" / "guide.md").is_file()
    assert "https://example.org/learn/guide" in clean.text("llms.txt") or "/learn/guide.md" in clean.text("llms.txt")


def test_policy_maps_keys_to_paths_and_back():
    policy = UrlPolicy(standard_settings_from_mapping(CONFIG))
    assert policy.url_for_key("about.html") == "/about" and policy.url_for_key("learn/guide.html") == "/learn/guide"
    assert policy.url_for_key("index.html") == "/" and policy.url_for_key("articles/index.html") == "/articles/"
    assert policy.key_for_path("/about") == "about.html" and policy.key_for_path("/") == "index.html" and policy.key_for_path("/a/") == "a/index.html"
    plain = UrlPolicy(standard_settings_from_mapping({"site": {"name": "Example"}}))
    assert plain.url_for_key("about.html") == "/about.html" and plain.key_for_path("/about.html") == "about.html"
    assert re.fullmatch(r"x/y\.html", plain.item_key(None, "x/y"))
