from __future__ import annotations

import copy
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
from procedures.newsroom.tests.reader_privacy import scan_files  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite  # noqa: E402

SITE_DIRECTORY = FIXTURES / "home-page"
SNAPSHOT_KEY = "_data/home-page/references.json"
STYLESHEET = REPO_ROOT / "src" / "papyrus_content" / "projection" / "standard" / "assets" / "papyrus-home-page.css"
GRID = re.compile(r'<section class="home-page-references" data-select="(?P<select>[a-z]+)" data-card="(?P<card>[a-z]+)">(?P<body>.*?)</section>', re.S)
CARD = re.compile(r'<li>(?P<card><(?:article class="home-page-tile"|div class="home-page-row").*?</(?:article|div)>)</li>', re.S)
TITLE = re.compile(r'class="home-page-title">(?:<a [^>]*>)?(?P<title>[^<]*)')
MAIN = re.compile(r"<main.*?</main>", re.S)


def quoted(text: str) -> list[str]:
    return re.findall(r'"([^"]*)"', text)


def project_site(context, *, settings=None, snapshot="fixture") -> None:
    settings = settings if settings is not None else json.loads((SITE_DIRECTORY / "projection.json").read_text(encoding="utf-8"))
    extra_files = {f"pages/{path.name}": path.read_bytes() for path in sorted((SITE_DIRECTORY / "pages").glob("*.md"))}
    fixture_bytes = (SITE_DIRECTORY / "_data" / "home-page" / "references.json").read_bytes()
    seed = {"fixture": {SNAPSHOT_KEY: fixture_bytes}, "empty": {SNAPSHOT_KEY: b'{"generatedAt":"2026-10-31T12:00:00.000Z","corpus":"c","fields":[],"references":[]}\n'}, "none": {}}[snapshot] if isinstance(snapshot, str) else {SNAPSHOT_KEY: snapshot}
    context.build_error = None
    try:
        context.site = ProjectedSite(settings=settings, content=SITE_DIRECTORY / "content", extra_files=extra_files, seed=seed)
    except (AssertionError, ValueError) as error:
        context.build_error = str(error)
        return
    context.add_cleanup(context.site.cleanup)


def fixture_settings_copy() -> dict:
    return copy.deepcopy(json.loads((SITE_DIRECTORY / "projection.json").read_text(encoding="utf-8")))


def grids(context, path: str, select: str) -> list[dict]:
    page = MAIN.search(context.site.text(path)).group(0)
    found = [{"card": match["card"], "cards": [card["card"] for card in CARD.finditer(match["body"])]} for match in GRID.finditer(page) if match["select"] == select]
    assert found, f"{path} has no {select!r} grid"
    return found


def titles_of(cards: list[str]) -> list[str]:
    return [html.unescape(TITLE.search(card)["title"]) for card in cards]


def one_grid(context, path: str, select: str) -> dict:
    return grids(context, path, select)[0]


@given("the home-page fixture site is projected")
def projected(context) -> None:
    project_site(context)
    assert context.build_error is None, context.build_error


@given("the home-page fixture site is projected with a default count of {count:d}")
def projected_with_default_count(context, count: int) -> None:
    settings = fixture_settings_copy()
    settings["homePage"]["references"]["defaultCount"] = count
    project_site(context, settings=settings)
    assert context.build_error is None, context.build_error


@given("the home-page fixture site is projected without a homePage setting")
def projected_without_home_page(context) -> None:
    settings = fixture_settings_copy()
    del settings["homePage"]
    project_site(context, settings=settings)


@given("the home-page fixture site is projected with an empty snapshot")
def projected_with_empty_snapshot(context) -> None:
    project_site(context, snapshot="empty")
    assert context.build_error is None, context.build_error


@given("the home-page fixture site is projected with no snapshot file")
def projected_with_no_snapshot(context) -> None:
    project_site(context, snapshot="none")
    assert context.build_error is None, context.build_error


@given('the home-page fixture site is projected with a Reference whose address is "{address}"')
def projected_with_unsafe_address(context, address: str) -> None:
    document = json.loads((SITE_DIRECTORY / "_data" / "home-page" / "references.json").read_text(encoding="utf-8"))
    for record in document["references"]:
        record["url"] = address
        record["image"] = address
    project_site(context, snapshot=json.dumps(document).encode("utf-8"))
    assert context.build_error is None, context.build_error


@then('the "{select}" grid on "{path}" lists {titles}')
def grid_lists(context, select: str, path: str, titles: str) -> None:
    found = titles_of(one_grid(context, path, select)["cards"])
    assert found == quoted(titles), found


@then('the "{select}" grid on "{path}" does not list {titles}')
def grid_does_not_list(context, select: str, path: str, titles: str) -> None:
    found = titles_of(one_grid(context, path, select)["cards"])
    assert not set(found) & set(quoted(titles)), found


@then('the "{select}" grid on "{path}" has {count:d} cards')
def grid_has_cards(context, select: str, path: str, count: int) -> None:
    assert len(one_grid(context, path, select)["cards"]) == count


@then('every card in the "{select}" grid on "{path}" is a {kind}')
def cards_are(context, select: str, path: str, kind: str) -> None:
    grid = one_grid(context, path, select)
    marker = {"tile": 'class="home-page-tile"', "row": 'class="home-page-row"'}[kind]
    assert grid["card"] == kind and grid["cards"] and all(marker in card for card in grid["cards"]), grid


@then('every card in the "{select}" grid on "{path}" says "{text}" next to a "{icon}" icon')
def cards_say(context, select: str, path: str, text: str, icon: str) -> None:
    cards = one_grid(context, path, select)["cards"]
    assert cards
    for card in cards:
        assert f"<span>{text}</span>" in card and f'data-icon="{icon}"' in card, card


@then('no card in the "{select}" grid on "{path}" says "{text}"')
def no_card_says(context, select: str, path: str, text: str) -> None:
    for card in one_grid(context, path, select)["cards"]:
        assert text not in card, card


@then('no Reference title appears twice on "{path}"')
def no_title_twice(context, path: str) -> None:
    placed = [title for select in ("recent", "confident", "recommended") for found in grids_if_any(context, path, select) for title in titles_of(found["cards"])]
    assert placed and len(placed) == len(set(placed)), placed


def grids_if_any(context, path: str, select: str) -> list[dict]:
    page = MAIN.search(context.site.text(path)).group(0)
    return [{"cards": [card["card"] for card in CARD.finditer(match["body"])]} for match in GRID.finditer(page) if match["select"] == select]


@then('"{path}" shows the text "{text}"')
def page_shows(context, path: str, text: str) -> None:
    assert html.escape(text, quote=True) in context.site.text(path) or text in context.site.text(path)


@then('"{path}" shows these in document order: {texts}')
def page_in_order(context, path: str, texts: str) -> None:
    page = context.site.text(path)
    position = 0
    for text in quoted(texts):
        found = page.find(text, position)
        assert found >= 0, f"{text!r} is not after position {position}"
        position = found + len(text)


@then('"{path}" contains the line \'{line}\'')
def twin_has_line(context, path: str, line: str) -> None:
    assert line in context.site.text(path).splitlines(), context.site.text(path)


@then('"{path}" does not contain "{text}"')
def page_lacks(context, path: str, text: str) -> None:
    assert text not in context.site.text(path)


@then('"{path}" has no Reference grid')
def page_without_grid(context, path: str) -> None:
    page = context.site.text(path)
    assert "home-page-references" not in page and "home-page-tile" not in page, page


@then('the build failed saying "{first}" and "{second}"')
def build_failed(context, first: str, second: str) -> None:
    assert context.build_error is not None, "the build succeeded"
    assert first in context.build_error and second in context.build_error, context.build_error


def card_titled(context, title: str, paths=("front/index.html", "ranked/index.html", "defaults/index.html", "recommended/index.html")) -> str:
    for path in paths:
        for select in ("recent", "confident", "recommended"):
            for found in grids_if_any(context, path, select):
                for card in found["cards"]:
                    if titles_of([card]) == [title]:
                        return card
    raise AssertionError(f"no card titled {title!r}")


@then('the card for "{title}" shows "{text}" next to a "{icon}" icon and a meter with {filled:d} filled segments')
def card_confidence(context, title: str, text: str, icon: str, filled: int) -> None:
    card = card_titled(context, title)
    assert f'<span class="home-page-confidence-value">{text}</span>' in card, card
    assert f'data-icon="{icon}"' in card, card
    assert card.count("home-page-meter-segment--filled") == filled, card


@then('the row card for "{title}" shows "{text}" with a visually hidden "confidence" label, a "{icon}" icon and a meter with {filled:d} filled segments')
def row_card_confidence(context, title: str, text: str, icon: str, filled: int) -> None:
    card = card_titled(context, title, ("rows/index.html",))
    assert card.startswith('<div class="home-page-row"'), card
    assert f'<span class="home-page-confidence-value">{text}<span class="home-page-visually-hidden"> confidence</span></span>' in card, card
    assert f'data-icon="{icon}"' in card, card
    assert card.count("home-page-meter-segment--filled") == filled, card


@then('the row card for "{title}" shows the label "{label}" and "{text}"')
def row_card_label_and_confidence(context, title: str, label: str, text: str) -> None:
    card = card_titled(context, title, ("rows/index.html",))
    assert card.startswith('<div class="home-page-row"'), card
    assert label in card and f">{text}<" in card, card


@then("the unfilled meter segments of a card are outlined shapes, not only a lighter colour")
def meter_outlines(context) -> None:
    stylesheet = STYLESHEET.read_text(encoding="utf-8")
    assert re.search(r"\.home-page-meter-segment \{[^}]*fill: none;[^}]*stroke: currentColor", stylesheet), stylesheet
    assert re.search(r"\.home-page-meter-segment--filled \{[^}]*fill: currentColor", stylesheet), stylesheet


@then("the home-page stylesheet draws no borders or lines")
def no_borders(context) -> None:
    stylesheet = STYLESHEET.read_text(encoding="utf-8")
    assert "home-page-references" in context.site.tree["css/papyrus-home-page.css"].decode("utf-8")
    declarations = re.findall(r"(?<![-\w])(border[\w-]*|outline[\w-]*|box-shadow)\s*:\s*([^;}]*)", stylesheet)
    allowed = [(name, value) for name, value in declarations if name == "border-radius" or (name == "border" and value.strip() == "0")]
    assert declarations == allowed, [declaration for declaration in declarations if declaration not in allowed]
    assert "<hr" not in context.site.text("front/index.html")


@then('the card for "{title}" says it was accepted by an editor')
def accepted_by_editor(context, title: str) -> None:
    assert "Accepted by an editor" in card_titled(context, title)


@then('the card for "{title}" says it was accepted automatically')
def accepted_automatically(context, title: str) -> None:
    assert "Accepted automatically" in card_titled(context, title)


@then("the identity scanner finds nothing in any rendered page")
def scanner_finds_nothing(context) -> None:
    pages = {key: body for key, body in context.site.tree.items() if key.endswith((".html", ".md", ".txt", ".json", ".xml"))}
    assert any(key.startswith("front/") for key in pages)
    assert scan_files(pages, []) == {}, scan_files(pages, [])


@then('no page links to "{scheme}"')
def no_unsafe_links(context, scheme: str) -> None:
    for key, body in context.site.tree.items():
        if key.endswith(".html"):
            assert f'href="{scheme}' not in body.decode("utf-8") and f'src="{scheme}' not in body.decode("utf-8"), key
    assert "home-page-tile" in context.site.text("defaults/index.html")


@given('a projection.json that sets {setting} to "{segment}"')
def settings_setting(context, setting: str, segment: str) -> None:
    raw: dict = {"site": {"name": "Example", "productionUrl": "https://example.org"}}
    if setting == "pages.path":
        raw["pages"] = [{"id": "p", "path": segment, "title": "P"}]
    elif setting.startswith("urls.sections."):
        raw["urls"] = {"sections": {setting.split(".")[2]: {"base": segment}}}
    elif setting.startswith("collections."):
        raw["collections"] = [{"id": setting.split(".")[1], "base": segment}]
    context.raw_settings = raw
    context.setting_name = setting


@when("the standard settings are read")
def read_settings(context) -> None:
    context.read_error = None
    try:
        context.read_settings = standard_settings_from_mapping(context.raw_settings)
    except ValueError as error:
        context.read_error = str(error)


@then('reading fails saying "{setting}" and "{reserved}" and "{newsroom}"')
def reading_fails(context, setting: str, reserved: str, newsroom: str) -> None:
    assert context.read_error is not None, "the settings were accepted"
    for text in (setting, reserved, newsroom):
        assert text in context.read_error, (text, context.read_error)


@then("the settings are accepted")
def settings_accepted(context) -> None:
    assert context.read_error is None, context.read_error
