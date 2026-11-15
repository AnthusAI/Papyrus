"""A brand pack and a site notice, applied by the standard front end: one small brand stylesheet, the shared theme, and the notice everywhere."""

from __future__ import annotations

import copy
import json
import re

import pytest

from procedures.newsroom.tests.standard_frontend_support import ProjectedSite, fixture_settings

PACK = {
    "schemaVersion": 1,
    "name": "Example Ledger",
    "wordmark": {"text": "Example Ledger"},
    "colors": {
        "light": {"bg": "#F5EFE0", "ink": "#1C1A17", "bandBg": "#EAE1CB", "bandCardBg": "#FFFBF0", "bandMutedBg": "#DDD2B6", "buttonBg": "#8E1B16", "buttonInk": "#FFF8EC", "rule": "#6B6150", "focus": "#0B5C8A"},
        "dark": {"bg": "#17140F", "ink": "#F1E9D6", "bandBg": "#221E16", "bandCardBg": "#2B261C", "bandMutedBg": "#352F23", "buttonBg": "#F0A59C", "buttonInk": "#2A0907", "rule": "#9A8F78", "focus": "#8CC8EE"},
    },
    "fonts": {"heading": "Source Serif 4", "body": "Source Serif 4"},
    "shape": {"corners": "square"},
    "ornaments": "quiet",
}
NOTICE = {"label": "Satire", "text": "Everything on this site is invented."}


def settings(**changes):
    raw = copy.deepcopy(fixture_settings("sectioned"))
    raw["brandPack"] = "brand.json"
    raw["site"]["notice"] = NOTICE
    raw.update(changes)
    return raw


@pytest.fixture(scope="module")
def branded():
    site = ProjectedSite(settings=settings(), content=ProjectedSite.__init__.__globals__["FIXTURES"] / "sectioned" / "content", extra_files={"brand.json": json.dumps(PACK)})
    yield site
    site.cleanup()


def page(site, key):
    return (site.out / key).read_text(encoding="utf-8")


def test_a_page_links_the_shared_theme_then_the_brand_stylesheet_last(branded):
    html = page(branded, "index.html")
    links = re.findall(r'<link rel="stylesheet" href="([^"?]+)', html)
    brand = [link for link in links if "papyrus-brand-" in link]
    assert len(brand) == 1 and links[-1] == brand[0]
    assert "/css/markus-vendor.css" not in links and "/css/site-theme.css" not in links
    assert links.index("/css/papyrus-tokens.css") < links.index("/css/papyrus-publication.css") < links.index(brand[0])


def test_the_brand_stylesheet_is_small_and_carries_the_pack_in_both_themes(branded):
    name = re.search(r"/css/(papyrus-brand-[0-9a-f]{12}\.css)", page(branded, "index.html")).group(1)
    css = (branded.out / "css" / name).read_text(encoding="utf-8")
    assert len(css) < 4000
    assert "--papyrus-bg:#F5EFE0" in css and "--papyrus-bg:#17140F" in css and "--papyrus-corner-lg:0" in css
    assert (branded.out / "fonts" / "source-serif-4-latin-wght-normal.woff2").exists()


def test_the_notice_is_on_every_kind_of_page_and_in_the_twins_the_feeds_and_the_structured_data(branded):
    for key in ("index.html", "essays/index.html", "essays/slow-water/index.html"):
        assert 'class="papyrus-notice"' in page(branded, key) and "Everything on this site is invented." in page(branded, key), key
    assert "> **Satire.** Everything on this site is invented." in page(branded, "essays/slow-water/index.md")
    assert "> **Satire.** Everything on this site is invented." in page(branded, "llms.txt")
    assert "<description>Satire. " in page(branded, "feed.xml") and "<summary>Satire. " in page(branded, "atom.xml")
    assert '"genre":"Satire"' in page(branded, "essays/slow-water/index.html")


def test_a_pack_that_fails_the_policy_stops_the_build_naming_the_problem(tmp_path):
    bad = copy.deepcopy(PACK)
    bad["colors"]["dark"]["ink"] = "#5A6672"
    with pytest.raises(ValueError, match="ink on bg"):
        ProjectedSite(settings=settings(), content=ProjectedSite.__init__.__globals__["FIXTURES"] / "sectioned" / "content", extra_files={"brand.json": json.dumps(bad)})


def test_a_font_on_the_allow_list_without_hosted_files_is_refused_saying_so():
    bad = copy.deepcopy(PACK)
    bad["fonts"]["heading"] = "Lora"
    with pytest.raises(ValueError, match="does not host yet"):
        ProjectedSite(settings=settings(), content=ProjectedSite.__init__.__globals__["FIXTURES"] / "sectioned" / "content", extra_files={"brand.json": json.dumps(bad)})


def test_a_site_without_a_brand_pack_or_notice_is_unchanged():
    site = ProjectedSite("sectioned")
    try:
        html = page(site, "index.html")
        assert "papyrus-notice" not in html and "papyrus-brand-" not in html and "papyrus-tokens" not in html
    finally:
        site.cleanup()


def test_a_notice_needs_both_words():
    with pytest.raises(ValueError, match="needs both a label and a text"):
        ProjectedSite(settings=settings(site={**fixture_settings("sectioned")["site"], "notice": {"label": "Satire"}}), content=ProjectedSite.__init__.__globals__["FIXTURES"] / "sectioned" / "content", extra_files={"brand.json": json.dumps(PACK)})
