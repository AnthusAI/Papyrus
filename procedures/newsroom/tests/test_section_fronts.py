"""Section fronts: the settings, the section index page, the home of sections, their twins and their digests."""

from __future__ import annotations

import json
import os

import pytest

from papyrus_content.home_page.settings import home_page_settings_from_mapping
from papyrus_content.projection.standard import components
from papyrus_content.projection.standard.config import SectionIndexConfig, standard_settings_from_mapping
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite

FRONTS = FIXTURES / "sectioned-fronts"
GOLDEN_KEYS = ("index.html", "essays/index.html", "notes/index.html", "index.md", "essays/index.md", "llms.txt")
BASE = {"site": {"name": "Example"}, "urls": {"sections": {"essays": {}, "notes": {}}}}


def fronts_site(settings: dict | None = None) -> ProjectedSite:
    return ProjectedSite(
        settings=settings or json.loads((FRONTS / "projection.json").read_text(encoding="utf-8")),
        content=FIXTURES / "sectioned" / "content",
        extra_files={"pages/notes-front.md": (FRONTS / "pages" / "notes-front.md").read_bytes()},
        seed={"_data/home-page/references.json": (FRONTS / "_data" / "home-page" / "references.json").read_bytes()},
    )


@pytest.fixture(scope="module")
def fronts():
    site = fronts_site()
    yield site
    site.cleanup()


def with_settings(**changes) -> dict:
    settings = json.loads(json.dumps(BASE))
    settings.update(changes)
    return settings


# ------------------------------------------------------------------ settings

def test_a_site_without_the_settings_has_no_section_fronts():
    settings = standard_settings_from_mapping(BASE)
    assert settings.section_fronts is False and settings.sections_home is False
    assert all(section.index is None for section in settings.sections)


def test_the_index_settings_default_to_a_lead_and_the_section_page_size():
    settings = standard_settings_from_mapping(with_settings(urls={"sections": {"essays": {"index": {}}}}))
    assert settings.sections[0].index == SectionIndexConfig(lead=True, latest=None, references=None, references_count=None, source=None)
    assert settings.section_fronts is True


def test_per_section_defaults_to_four_and_is_configurable():
    assert home_page_settings_from_mapping({}).per_section == 4
    assert home_page_settings_from_mapping({"perSection": 9}).per_section == 9
    assert home_page_settings_from_mapping({}).home_lead is True and home_page_settings_from_mapping({}).home_sections is None


@pytest.mark.parametrize(
    "settings, message",
    [
        (with_settings(urls={}, homePage={"layout": "sections"}), "needs urls.sections"),
        (with_settings(urls={"sections": {"essays": {"index": {"references": "recent"}}}}), "needs homePage"),
        (with_settings(urls={"sections": {"essays": {"index": {"references": "newest"}}}}, homePage={}), "must be one of"),
        (with_settings(urls={"sections": {"essays": {"index": {"latest": 0}}}}), "whole number"),
        (with_settings(urls={"sections": {"essays": {"index": {"latest": 2.5}}}}), "whole number"),
        (with_settings(urls={"sections": {"essays": {"index": {"lead": "yes"}}}}), "true or false"),
        (with_settings(urls={"sections": {"essays": {"index": {"colour": "red"}}}}), "Unknown urls.sections.essays.index settings: colour"),
        (with_settings(homePage={"layout": "sections", "homeSections": ["ghosts"]}), "no listing page: ghosts"),
        (with_settings(homePage={"layout": "sections", "homeSections": []}), "list of section names"),
        (with_settings(homePage={"layout": "sections", "perSection": 0}), "at least 1"),
        (with_settings(homePage={"layout": "sections", "perSection": 2.5}), "whole number"),
        (with_settings(homePage={"homeLead": "no"}), "true or false"),
    ],
)
def test_settings_that_cannot_work_are_refused(settings, message):
    with pytest.raises(ValueError, match=message):
        standard_settings_from_mapping(settings)


# ------------------------------------------------------------------ pages

def test_the_section_index_replaces_page_one_and_leaves_page_two_plain(fronts):
    assert "markus-section-index" in fronts.text("essays/index.html")
    assert "markus-section-index" not in fronts.text("essays/page/2/index.html")
    assert "markus-section-index" not in fronts.text("links/index.html")


def test_a_section_without_entries_has_neither_a_page_nor_a_block(fronts):
    assert "letters/index.html" not in fronts.tree
    assert 'data-section="letters"' not in fronts.text("index.html")


def test_the_stylesheet_is_published_only_for_sites_that_use_the_settings(fronts):
    assert "css/papyrus-section-fronts.css" in fronts.tree
    plain = ProjectedSite("sectioned")
    try:
        assert "css/papyrus-section-fronts.css" not in plain.tree and "papyrus-section-fronts" not in plain.text("index.html")
    finally:
        plain.cleanup()


def test_the_stylesheet_draws_no_borders():
    css = (FIXTURES.parents[2] / "src" / "papyrus_content" / "projection" / "standard" / "assets" / "papyrus-section-fronts.css").read_text(encoding="utf-8")
    assert "border:" not in css.replace("border-radius", "") and "outline" not in css and "box-shadow" not in css


def test_the_current_tab_is_marked_by_more_than_colour():
    from papyrus_content.projection.standard.page import SectionTab

    markup = components.section_tabs_html((SectionTab("A", "/a/", True), SectionTab("B", "/b/")))
    assert 'aria-current="page"' in markup and 'data-current="true"' in markup
    assert components.section_tabs_html((SectionTab("A", "/a/", True),)) == ""


def test_the_index_with_latest_pages_the_rest_after_it(fronts):
    assert "/essays/page/2/" in fronts.text("essays/index.html")
    assert "Slow Water" in fronts.text("essays/page/2/index.html") and "Slow Water" not in fronts.text("essays/index.html")


def test_a_larger_latest_shows_more_and_leaves_no_story_unreachable():
    settings = json.loads((FRONTS / "projection.json").read_text(encoding="utf-8"))
    settings["urls"]["sections"]["essays"]["index"]["latest"] = 4
    site = fronts_site(settings)
    try:
        assert "Slow Water" in site.text("essays/index.html") and "older" not in site.text("essays/index.html").lower()
        assert "essays/page/2/index.html" not in site.tree
    finally:
        site.cleanup()


def test_an_authored_index_that_is_not_a_file_in_the_static_directory_is_refused():
    settings = json.loads((FRONTS / "projection.json").read_text(encoding="utf-8"))
    settings["urls"]["sections"]["notes"]["index"]["source"] = "../outside.md"
    with pytest.raises((ValueError, AssertionError), match="not a file inside the static directory"):
        fronts_site(settings)


def test_a_digest_for_the_index_changes_with_its_settings():
    first = fronts_site()
    settings = json.loads((FRONTS / "projection.json").read_text(encoding="utf-8"))
    settings["urls"]["sections"]["essays"]["index"]["referencesCount"] = 1
    second = fronts_site(settings)
    try:
        assert first.text("essays/index.html").count("home-page-tile") == 2
        assert second.text("essays/index.html").count("home-page-tile") == 1
    finally:
        first.cleanup()
        second.cleanup()


# ------------------------------------------------------------------ goldens

@pytest.mark.parametrize("key", GOLDEN_KEYS)
def test_golden_pages(key, fronts):
    target = FRONTS / "expected" / key
    if os.environ.get("UPDATE_GOLDEN"):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fronts.tree[key])
    assert fronts.tree[key] == target.read_bytes(), f"sectioned-fronts/{key} differs from its golden (UPDATE_GOLDEN=1 regenerates)"
