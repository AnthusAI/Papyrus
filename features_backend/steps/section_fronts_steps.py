from __future__ import annotations

import copy
import hashlib
import html
import json
import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.standard.config import standard_settings_from_mapping  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, fixture_settings, written_keys  # noqa: E402

FRONTS_DIRECTORY = FIXTURES / "sectioned-fronts"
SNAPSHOT_KEY = "_data/home-page/references.json"
MAIN = re.compile(r"<main.*?</main>", re.S)
CARD_TITLE = re.compile(r'class="markus-card-title"><a [^>]*>(?P<title>[^<]*)</a>')
BLOCK = re.compile(r'<section class="markus-section-block" data-section="(?P<name>[^"]*)".*?</section>', re.S)
HEADING = re.compile(r'<h2 id="section-block-[^"]*"><a href="(?P<href>[^"]*)">(?P<label>[^<]*)</a></h2>')
MORE = re.compile(r'<p class="markus-section-more"><a href="(?P<href>[^"]*)">(?P<text>[^<]*?) <svg')
REFERENCE_TITLE = re.compile(r'class="home-page-title"><a [^>]*>(?P<title>[^<]*)</a>')
MAIN_HOOK = '''
def main(page):
    if page.kind == "home" or (page.kind == "listing" and page.section_index is not None):
        return '<div id="hook">hook front page</div>'
    return None
'''


def quoted(text: str) -> list[str]:
    return re.findall(r'"([^"]*)"', text)


def fronts_settings() -> dict:
    return copy.deepcopy(json.loads((FRONTS_DIRECTORY / "projection.json").read_text(encoding="utf-8")))


def project_fronts(context, settings: dict | None = None, extra: dict | None = None) -> None:
    extra_files = {"pages/notes-front.md": (FRONTS_DIRECTORY / "pages" / "notes-front.md").read_bytes(), **(extra or {})}
    seed = {SNAPSHOT_KEY: (FRONTS_DIRECTORY / "_data" / "home-page" / "references.json").read_bytes()}
    context.site = ProjectedSite(settings=settings or fronts_settings(), content=FIXTURES / "sectioned" / "content", extra_files=extra_files, seed=seed)
    context.add_cleanup(context.site.cleanup)


def set_path(settings: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    target = settings
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def main_of(context, path: str) -> str:
    return MAIN.search(context.site.text(path)).group(0)


def titles_in(markup: str) -> list[str]:
    return [html.unescape(match["title"]) for match in CARD_TITLE.finditer(markup)]


def block_markup(context, label: str) -> str:
    home = main_of(context, "index.html")
    for match in BLOCK.finditer(home):
        heading = HEADING.search(match.group(0))
        if heading and html.unescape(heading["label"]) == label:
            return match.group(0)
    raise AssertionError(f"the home page has no block {label!r}")


@given("the section-fronts fixture site is projected")
def projected(context) -> None:
    project_fronts(context)


@given('the section-fronts fixture site is projected with "{path}" removed')
def projected_with_removed(context, path: str) -> None:
    settings = fronts_settings()
    target = settings
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    del target[parts[-1]]
    project_fronts(context, settings)


@given('the section-fronts fixture site is projected with "{path}" set to {value}')
def projected_with_value(context, path: str, value: str) -> None:
    settings = fronts_settings()
    set_path(settings, path, json.loads(value))
    project_fronts(context, settings)


@given("the section-fronts fixture site is projected with a main hook")
def projected_with_hook(context) -> None:
    settings = fronts_settings()
    settings["hooks"] = "hooks.py"
    project_fronts(context, settings, {"hooks.py": MAIN_HOOK.encode("utf-8")})


@then('the section front page "{path}" is headed "{heading}" with the description "{description}"')
def front_heading(context, path: str, heading: str, description: str) -> None:
    page = main_of(context, path)
    assert "markus-section-index" in page, path
    assert f"<h1>{heading}</h1>" in page, page[:400]
    assert f'<p class="markus-section-description">{description}</p>' in page


@then('the section front page "{path}" has the lead Story "{title}"')
def front_lead(context, path: str, title: str) -> None:
    lead = re.search(r'<div class="markus-section-lead">(?P<body>.*?)</div>', main_of(context, path), re.S)
    assert lead is not None and titles_in(lead["body"]) == [title], path


@then('the section front page "{path}" lists the latest entries {titles}')
def front_latest(context, path: str, titles: str) -> None:
    grid = re.search(r'</div><div class="markus-card-grid">(?P<body>.*?)</div>(?=<section|<nav|</div>)', main_of(context, path), re.S)
    assert grid is not None, path
    assert titles_in(grid["body"]) == quoted(titles), titles_in(grid["body"])


@then('the section front page "{path}" has the section tabs {labels} with "{current}" current')
def front_tabs(context, path: str, labels: str, current: str) -> None:
    tabs = re.search(r'<nav class="markus-section-tabs".*?</nav>', main_of(context, path), re.S)[0]
    assert re.findall(r"<a [^>]*>([^<]*)</a>", tabs) == quoted(labels)
    assert re.findall(r'<a [^>]*aria-current="page"[^>]*>([^<]*)</a>', tabs) == [current]


@then('the section front page "{path}" links to older pages at "{href}"')
def front_older(context, path: str, href: str) -> None:
    assert f'<a rel="next" href="{href}">Older</a>' in main_of(context, path)


@then('"{path}" is the plain listing of "{title}" with no section front page')
def plain_listing(context, path: str, title: str) -> None:
    page = main_of(context, path)
    assert "markus-section-index" not in page and "markus-section-tabs" not in page
    assert titles_in(page) == [title]


@then("the home page has the section blocks {labels} in that order")
def home_blocks(context, labels: str) -> None:
    found = [html.unescape(HEADING.search(match.group(0))["label"]) for match in BLOCK.finditer(main_of(context, "index.html"))]
    assert found == quoted(labels), found


@then('the block "{label}" on the home page links to "{href}" with the text "{text}"')
def block_link(context, label: str, href: str, text: str) -> None:
    block = block_markup(context, label)
    assert HEADING.search(block)["href"] == href
    more = MORE.search(block)
    assert more is not None and more["href"] == href and html.unescape(more["text"]) == text, block[-400:]
    assert 'data-icon="arrow-right"' in block


@then('the block "{label}" on the home page shows the description "{description}"')
def block_description(context, label: str, description: str) -> None:
    assert f'<p class="markus-section-description">{description}</p>' in block_markup(context, label)


@then('the block "{label}" on the home page lists {titles}')
def block_lists(context, label: str, titles: str) -> None:
    assert titles_in(block_markup(context, label)) == quoted(titles)


@then('the block "{label}" on the home page says "{text}"')
def block_says(context, label: str, text: str) -> None:
    assert text in block_markup(context, label)


@then("the home page does not use the generated latest listing")
def home_not_latest(context) -> None:
    assert "markus-section-links" not in main_of(context, "index.html")


@then('the home page has no block "{label}"')
def home_lacks_block(context, label: str) -> None:
    labels = [html.unescape(HEADING.search(match.group(0))["label"]) for match in BLOCK.finditer(main_of(context, "index.html"))]
    assert label not in labels, labels


@then("the home page has no lead entries")
def home_without_lead(context) -> None:
    assert "markus-section-lead" not in main_of(context, "index.html")


@when('the sectioned fixture site is projected with homePage layout "latest"')
def sectioned_with_latest(context) -> None:
    settings = fixture_settings("sectioned")
    settings["homePage"] = {"layout": "latest"}
    context.layout_site = ProjectedSite(settings=settings, content=FIXTURES / "sectioned" / "content")
    context.add_cleanup(context.layout_site.cleanup)


@then('the standard page "index.html" is byte for byte the golden page of the sectioned fixture')
def byte_for_byte(context) -> None:
    assert context.site.tree["index.html"] == (FIXTURES / "sectioned" / "expected" / "index.html").read_bytes()


@then('the main element of "{path}" is the same as in the golden page of the sectioned fixture')
def main_equals_golden(context, path: str) -> None:
    golden = (FIXTURES / "sectioned" / "expected" / path).read_text(encoding="utf-8")
    assert MAIN.search(context.layout_site.text(path))[0] == MAIN.search(golden)[0]


@then("the fixtures flat, sectioned, authors, showcase and home-page project the recorded bytes")
def recorded_bytes(context) -> None:
    from procedures.newsroom.tests.test_section_fronts_off_by_default import FIXTURE_NAMES, MANIFEST, digests_of

    recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))
    different = [name for name in FIXTURE_NAMES if digests_of(name) != recorded[name]]
    assert not different, different


@then('the section front page "{path}" shows the References {titles} once, after the stories')
def front_references(context, path: str, titles: str) -> None:
    page = main_of(context, path)
    grid = page.index('<section class="home-page-references"')
    assert grid > page.rindex("markus-card-title"), "the References grid is not after the stories"
    shown = [html.unescape(match["title"]) for match in REFERENCE_TITLE.finditer(page)]
    assert shown == quoted(titles), shown
    assert len(set(shown)) == len(shown)


@then('the section front page "{path}" shows no References grid')
def front_no_references(context, path: str) -> None:
    assert "home-page-references" not in main_of(context, path)


@then('the section-fronts site did not write "{key}"')
def did_not_write(context, key: str) -> None:
    assert key not in written_keys(context.site), written_keys(context.site)


@when('the settings of a site without sections ask for homePage layout "sections"')
def refuse_sections_home(context) -> None:
    refuse(context, {"site": {"name": "Example"}, "homePage": {"layout": "sections"}})


@when("the settings of a section index ask for References on a site without homePage")
def refuse_references(context) -> None:
    refuse(context, {"site": {"name": "Example"}, "urls": {"sections": {"essays": {"index": {"references": "recent"}}}}})


@when('the settings ask for "{path}" of {value}')
def refuse_number(context, path: str, value: str) -> None:
    settings = fronts_settings()
    set_path(settings, path, json.loads(value))
    refuse(context, settings)


def refuse(context, settings: dict) -> None:
    try:
        standard_settings_from_mapping(settings)
    except ValueError as error:
        context.refusal = str(error)
    else:
        context.refusal = None


@then('the settings are refused with "{text}"')
def refused(context, text: str) -> None:
    assert context.refusal is not None and text in context.refusal, context.refusal
