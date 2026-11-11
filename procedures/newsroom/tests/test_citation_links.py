"""A body with citation markers and no bibliography directive never links to a missing anchor, and a site chooses how the bibliography links a source (PPY-21bb36)."""

from __future__ import annotations

import json
import re

import pytest

from papyrus_content.lens_evidence import run_checks, story_from_row
from papyrus_content.projection.projector import MarkusSiteProjector, read_static_files, settings_from_mapping

FRONT = (
    "title: Hello\ncitations:\n  smith:\n    type: webpage\n    title: A Page Cited\n    publisher: Acme Press\n"
    "    URL: https://example.org/outside\n    internalUrl: /references/smith/\n    issued: {date-parts: [[2020]]}\n"
    "  jones:\n    type: webpage\n    title: Another Page\n    publisher: Beta News\n    URL: https://example.net/other\n    issued: {date-parts: [[2021]]}\n"
)
WITHOUT_DIRECTIVE = "As shown [@smith] and again [@jones].\n"
WITH_DIRECTIVE = WITHOUT_DIRECTIVE + "\n::citations\n"
EXTERNAL = re.compile(r'href="https?://')


def render(body: str, raw: dict | None = None) -> str:
    site = MarkusSiteProjector(settings_from_mapping(raw or {}), read_static_files(None, None))
    return site._fragment(f"---\n{FRONT}---\n{body}", 1)


def fragment_targets(page: str) -> list[str]:
    return re.findall(r'href="#([^"]+)"', page)


def test_markers_without_a_directive_get_the_bibliography_so_no_link_dangles():
    page = render(WITHOUT_DIRECTIVE)
    ids = set(re.findall(r'id="([^"]+)"', page))
    assert fragment_targets(page) == ["citation-1", "citation-2"]
    assert set(fragment_targets(page)) <= ids
    assert page.index('<ol class="citationslist">') < page.index("</article>")


def test_the_appended_bibliography_is_the_one_the_directive_would_make():
    assert render(WITHOUT_DIRECTIVE).replace("\n", "") == render(WITH_DIRECTIVE).replace("\n", "")


def test_a_directive_in_the_body_is_not_duplicated():
    assert render(WITH_DIRECTIVE).count('<ol class="citationslist">') == 1


def test_a_body_without_markers_gets_no_bibliography():
    assert "citationslist" not in render("Plain words.\n")


def test_default_links_are_external_and_unchanged_for_a_source_with_no_page_of_ours():
    page = render(WITH_DIRECTIVE)
    assert page == render(WITH_DIRECTIVE, {"citations": True}) == render(WITH_DIRECTIVE, {"citations": {"links": "external"}})
    assert '<a href="https://example.net/other" target="_blank" rel="noopener noreferrer">https://example.net/other</a>' in page
    assert "citation-external" not in page and "<svg" not in page   # the icon is opt-in (citations.externalIcon)


def test_a_source_whose_entry_names_a_page_of_ours_links_to_it_in_the_default_mode():
    """Deliberate change (surfable site): the default mode honours ``internalUrl`` instead of linking out; ``internal`` and ``none`` are as before."""
    page = render(WITH_DIRECTIVE)
    assert '<a href="/references/smith/">A Page Cited' in page and "example.org/outside" not in page


@pytest.mark.parametrize("body", [WITH_DIRECTIVE, WITHOUT_DIRECTIVE])
@pytest.mark.parametrize("mode", ["internal", "none"])
def test_internal_and_none_emit_no_external_href_and_no_outside_address(body, mode):
    page = render(body, {"citations": {"links": mode}})
    assert not EXTERNAL.search(page)
    assert "example.org" not in page and "example.net" not in page
    assert "A Page Cited" in page and "Acme Press" in page and "2020" in page


def test_internal_links_a_source_only_to_the_sites_own_page_for_it_else_plain_text():
    page = render(WITH_DIRECTIVE, {"citations": {"links": "internal"}})
    assert '<a href="/references/smith/">A Page Cited' in page
    assert re.search(r'<li id="citation-2">Another Page[^<]*</li>', page)


def test_none_links_nothing_from_the_bibliography():
    page = render(WITH_DIRECTIVE, {"citations": {"links": "none"}})
    assert re.findall(r'<li id="citation-\d">[^<]*</li>', page) and "<li id=\"citation-1\"><a" not in page


@pytest.mark.parametrize("address", ["https://elsewhere.test/page", "//elsewhere.test/page", "javascript:alert(1)"])
def test_an_internal_page_that_is_an_address_is_never_linked(address):
    page = MarkusSiteProjector(settings_from_mapping({"citations": {"links": "internal"}}), read_static_files(None, None))._fragment(
        f"---\ntitle: T\ncitations:\n  a:\n    type: webpage\n    title: Only\n    internalUrl: '{address}'\n---\nSee [@a].\n", 1
    )
    assert not EXTERNAL.search(page) and "elsewhere.test" not in page and "javascript" not in page


@pytest.mark.parametrize("value", [{"links": "sideways"}, {"mode": "none"}, "none", 3])
def test_a_bad_citations_setting_is_refused(value):
    with pytest.raises(ValueError, match="citations"):
        settings_from_mapping({"citations": value})


def test_citations_false_still_turns_the_feature_off():
    assert settings_from_mapping({"citations": False}).citations is False
    assert settings_from_mapping({"citations": {"links": "none"}}).citations is True


def lens(body: str) -> dict:
    row = {"id": "l-v1", "lineageId": "l", "versionNumber": 1, "versionState": "current", "type": "article", "slug": "t", "section": None, "status": "draft",
           "stage": "copywriting", "headline": "T", "title": "T", "aliases": [], "metadata": json.dumps({"frontMatterYaml": FRONT}), "bodyMarkus": body,
           "createdAt": "2026-11-08T00:00:00Z", "updatedAt": "2026-11-08T00:00:00Z", "versionCreatedAt": "2026-11-08T00:00:00Z"}
    story = story_from_row(row)
    return next(row for row in run_checks(story, None) if row["check"] == "A5")


def test_the_checklist_check_names_markers_that_have_no_directive():
    finding = lens(WITHOUT_DIRECTIVE)
    assert finding["state"] != "pass"
    assert "[@jones]" in finding["message"] and "[@smith]" in finding["message"] and "::citations" in finding["message"]


def test_the_checklist_check_names_a_key_that_is_not_among_the_entries():
    finding = lens("As shown [@smith] and [@ghost].\n\n::citations\n")
    assert finding["state"] != "pass" and "[@ghost]" in finding["message"]
    assert "::citations" not in finding["message"]


def test_the_checklist_check_passes_when_every_marker_resolves_and_the_directive_is_present():
    assert lens(WITH_DIRECTIVE)["state"] == "pass"
