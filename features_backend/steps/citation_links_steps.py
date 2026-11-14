from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.projector import MarkusSiteProjector, read_static_files, settings_from_mapping  # noqa: E402

FRONT = (
    "title: Hello\ncitations:\n  smith:\n    type: webpage\n    title: A Page Cited\n    publisher: Acme Press\n"
    "    URL: https://example.org/outside\n    internalUrl: /references/smith/\n    issued: {date-parts: [[2020]]}\n"
    "  jones:\n    type: webpage\n    title: Another Page\n    publisher: Beta News\n    URL: https://example.net/other\n    issued: {date-parts: [[2021]]}\n"
)
MARKERS = "As shown [@smith] and again [@jones].\n"
BODIES = {
    "citation markers and no bibliography line": MARKERS,
    "citation markers and a bibliography line": MARKERS + "\n::citations\n",
}
OUTSIDE = re.compile(r'href="(?:https?:)?//')


def render(body: str, raw: dict) -> str:
    site = MarkusSiteProjector(settings_from_mapping(raw), read_static_files(None, None))
    return site._fragment(f"---\n{FRONT}---\n{body}", 1)


@given("a Papyrus site whose citations setting is not declared")
def undeclared(context) -> None:
    context.citations_raw = {}


@given("a Papyrus site whose citations setting is externalIcon")
def icon_on(context) -> None:
    context.citations_raw = {"citations": {"externalIcon": True}}


@given('a Papyrus site whose citations links are "{mode}"')
def declared(context, mode: str) -> None:
    context.citations_raw = {"citations": {"links": mode}}


@when("the site renders a Story with {kind}")
def renders(context, kind: str) -> None:
    context.page = render(BODIES[kind], context.citations_raw)


PAPER = (
    "title: Hello\ncitations:\n  lemley:\n    type: article\n    title: Foundation Models and Fair Use\n    container-title: SSRN\n"
    "    author: [{family: Lemley, given: Mark}]\n    issued: {date-parts: [[2026]]}\n"
)
PAPER_DOI = "    DOI: 10.2139/ssrn.7682724\n"
PAPER_URL = "    URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7682724\n"
PAPER_IDENTIFIERS = {"both a DOI and a URL": PAPER_DOI + PAPER_URL, "only a DOI": PAPER_DOI, "only a URL": PAPER_URL}


@when("the site renders a Story citing a paper that has {identifiers}")
def renders_paper(context, identifiers: str) -> None:
    site = MarkusSiteProjector(settings_from_mapping(context.citations_raw), read_static_files(None, None))
    front = PAPER + PAPER_IDENTIFIERS[identifiers]
    context.page = site._fragment(f"---\n{front}---\n" + "As shown [@lemley].\n\n::citations\n", 1)


@then("the bibliography entry ends with the DOI, a space, and the link to the URL")
def doi_then_url(context) -> None:
    entry = item_of(context.page, "Foundation Models and Fair Use")
    assert "ssrn.7682724 <a " in entry and "ssrn.7682724<a" not in entry, entry


@then("the bibliography entry shows the DOI and no link")
def doi_only(context) -> None:
    entry = item_of(context.page, "Foundation Models and Fair Use")
    assert entry.endswith("ssrn.7682724</li>") and "<a " not in entry, entry


@then("the bibliography entry shows the link to the URL after a space and no DOI")
def url_only(context) -> None:
    entry = item_of(context.page, "Foundation Models and Fair Use")
    assert ". <a " in entry and "doi.org" not in entry, entry


@then("every citation number links to an entry on the same page")
def numbers_resolve(context) -> None:
    targets = re.findall(r'<span class="citation"><a href="#([^"]+)">', context.page)
    ids = set(re.findall(r'<li id="([^"]+)"', context.page))
    assert targets and set(targets) <= ids, (targets, ids)


@then('the page lists "{title}" once, inside the article')
def listed_once(context, title: str) -> None:
    assert context.page.count(title) == 1 and context.page.index(title) < context.page.index("</article>"), context.page


@then('the source "{title}" links to "{href}"')
def source_links(context, title: str, href: str) -> None:
    assert re.search(rf'<a (?:class="[^"]*" )?href="{re.escape(href)}"', context.page) and title in context.page, context.page


@then('the page is the same as for a site whose citations links are "{mode}"')
def same_page(context, mode: str) -> None:
    assert context.page == render(BODIES["citation markers and a bibliography line"], {"citations": {"links": mode}})


@then("the page has no link to an outside address")
def no_outside(context) -> None:
    assert not OUTSIDE.search(context.page) and "example.org" not in context.page and "example.net" not in context.page, context.page


@then('the page shows the title, publisher and date of "{title}" as text')
def text_shown(context, title: str) -> None:
    assert title in context.page and "Acme Press" in context.page and "2020" in context.page, context.page


@then('the source "{title}" is plain text')
def plain_text(context, title: str) -> None:
    assert re.search(rf'<li id="citation-\d+">{re.escape(title)}[^<]*</li>', context.page), context.page


@then('the setting {setting} is refused with a message naming "{name}"')
def refused(context, setting: str, name: str) -> None:
    try:
        settings_from_mapping({"citations": json.loads(setting)})
    except ValueError as exc:
        assert name in str(exc)
    else:
        raise AssertionError("the setting was accepted")


def item_of(page: str, title: str) -> str:
    return re.search(rf'<li id="citation-\d+">(?:(?!</li>).)*?{re.escape(title)}.*?</li>', page, re.S).group(0)


@then('the source "{title}" opens in a new tab and carries the external-link icon')
def outside_marked(context, title: str) -> None:
    entry = item_of(context.page, title)
    assert 'target="_blank"' in entry and 'rel="noopener noreferrer"' in entry and 'data-icon="external-link"' in entry, entry


@then('the source "{title}" has no icon and does not open a new tab')
def inside_unmarked(context, title: str) -> None:
    entry = item_of(context.page, title)
    assert "<svg" not in entry and "_blank" not in entry, entry


@then('the source "{title}" has no icon and opens in a new tab')
def outside_plain(context, title: str) -> None:
    entry = item_of(context.page, title)
    assert "<svg" not in entry and "citation-external" not in entry and 'target="_blank"' in entry, entry
