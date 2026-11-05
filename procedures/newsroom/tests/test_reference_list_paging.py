"""Paged Reference lists: the first page in the HTML, the rest in chunk files, the shared order across them, and a change that rewrites only what it touches."""

from __future__ import annotations

import json
import re
from html import unescape

import pytest

from papyrus_content.home_page.task import _stale_list_files
from papyrus_content.projection.engine import project_stale_listings
from procedures.newsroom.tests.reader_privacy import scan_files
from procedures.newsroom.tests.reference_list_support import SNAPSHOT_KEY, list_files, project, record, snapshot, snapshot_bytes

KEY = re.compile(r'data-key="([0-9a-f]{12})"')


def keys_in(markup: str) -> list[str]:
    return KEY.findall(markup)


def section_of(page: str, select: str) -> str:
    return re.search(rf'<section class="home-page-references"[^>]*data-select="{select}".*?</section>', page, re.S).group(0)


def chain(site, select: str) -> list[dict]:
    """The data files of one list in the order the script would fetch them, from the control under the first page."""
    page = site.text("wire/index.html")
    source = re.search(r'data-src="([^"]+)"', section_of(page, select))
    files, found = [], source.group(1) if source else None
    while found:
        document = json.loads(site.tree[found.lstrip("/")])
        files.append(document)
        found = document["next"]
    return files


@pytest.fixture
def site():
    built = project(snapshot(130, 40), first=6, page_size=12)
    yield built
    built.cleanup()


def test_the_first_page_is_in_the_html_and_a_link_leads_to_the_next_static_page(site):
    page = site.text("wire/index.html")
    accepted = section_of(page, "recent")
    assert len(keys_in(accepted)) == 6
    link = re.search(r'<a class="home-page-load-more" rel="next" href="([^"]+)"', accepted)
    assert link and link.group(1).startswith("/reference-lists/wire/recent/") and link.group(1).endswith("/")
    assert 'role="status" aria-live="polite"' in accepted
    chunk_page = site.text(link.group(1).strip("/") + "/index.html")
    assert 'rel="next"' in chunk_page and "Back to The wire" in chunk_page


def test_every_reference_is_reachable_once_in_the_shared_order_and_nothing_is_capped(site):
    document = json.loads(site.text(SNAPSHOT_KEY))
    expected = [found["key"] for found in sorted((r for r in document["references"] if r["status"] == "accepted"), key=lambda r: r["acceptedAt"], reverse=True)]
    shown = keys_in(section_of(site.text("wire/index.html"), "recent"))
    for data in chain(site, "recent"):
        shown += keys_in(data["html"])
    assert len(shown) == 130 and len(set(shown)) == 130
    assert shown == expected
    recommended = keys_in(section_of(site.text("wire/index.html"), "recommended"))
    for data in chain(site, "recommended"):
        recommended += keys_in(data["html"])
    assert len(recommended) == 40 and not set(recommended) & set(shown)


def test_the_static_pages_chain_to_the_end_without_a_script(site):
    page = site.text("wire/index.html")
    found, pages = re.search(r'rel="next" href="([^"]+)"', section_of(page, "recent")).group(1), 0
    seen = keys_in(section_of(page, "recent"))
    while found:
        text = site.text(found.strip("/") + "/index.html")
        seen += keys_in(text)
        pages += 1
        onward = re.search(r'rel="next" href="([^"]+)"', text)
        found = onward.group(1) if onward else None
    assert pages == len(chain(site, "recent")) and len(seen) == 130


def test_the_data_file_carries_exactly_the_cards_of_the_page_and_the_markers_are_gone(site):
    name = next(key for key in list_files(site) if key.endswith(".json") and "/recent/" in key)
    data = json.loads(site.tree[name])
    page = site.text(name[: -len(".json")] + "/index.html")
    assert data["format"] == 1 and data["count"] == len(keys_in(data["html"]))
    assert data["html"] in page
    assert "papyrus:cards" not in page and "papyrus:cards" not in json.dumps(data)


def test_only_a_page_with_a_paged_list_loads_the_script():
    plain = project(snapshot(20, 5), paging=True, extra_files={"pages/wire.md": b'::band{size="bare"}\n::include{kind="references" select="recent" count="3"}\n'})
    try:
        assert "papyrus-reference-list.js" not in plain.text("wire/index.html")
        assert not list_files(plain)
        assert "js/papyrus-reference-list.js" in plain.tree  # the site opted in, so the file is published
    finally:
        plain.cleanup()


def test_a_site_that_has_not_opted_in_publishes_no_script_and_its_other_pages_are_the_same(site):
    plain_page = b'::band{size="bare"}\n::include{kind="references" select="recent" count="3"}\n'
    off = project(snapshot(20, 5), paging=False, extra_files={"pages/wire.md": plain_page})
    on = project(snapshot(20, 5), paging=True, extra_files={"pages/wire.md": plain_page})
    try:
        assert "js/papyrus-reference-list.js" not in off.tree and not list_files(off)
        assert {key: body for key, body in on.tree.items() if key != "js/papyrus-reference-list.js"} == off.tree
    finally:
        off.cleanup()
        on.cleanup()


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (b'::include{kind="references" select="recent" paged="true" more="/x/"}\n', "cannot be paged and have a more link"),
        (b'::include{kind="references" select="recent" paged="yes"}\n', 'paged must be "true" or "false"'),
        (b'::include{kind="references" select="recent" id="Bad Id" paged="true"}\n', "id names a paged list"),
        (b'::include{kind="references" select="recent" id="solo"}\n', "id names a paged list"),
        (b'::include{kind="references" select="recent" paged="true"}\n::include{kind="references" select="recent" paged="true" bucket="week"}\n::include{kind="references" select="recent" paged="true"}\n', "both named 'recent'"),
    ],
)
def test_a_wrong_paged_include_is_a_build_error(source, message):
    with pytest.raises((ValueError, AssertionError)) as error:
        project(snapshot(20, 5), extra_files={"pages/wire.md": source}).cleanup()
    assert message in str(error.value)


def test_a_site_that_has_not_opted_in_cannot_page_a_list():
    with pytest.raises((ValueError, AssertionError)) as error:
        project(snapshot(20, 5), paging=False).cleanup()
    assert "needs homePage.references.paging" in str(error.value)


def test_nothing_private_reaches_a_file_or_a_page(site):
    files = {key: body.decode("utf-8") for key, body in site.tree.items() if key.startswith("reference-lists/") or key == "wire/index.md"}
    assert files and scan_files(files, []) == {}
    for text in files.values():
        for private in ("curationStatusUpdatedBy", "starRating", "@", "predictedAcceptProbability"):
            assert private not in text


def test_the_twin_is_the_first_page_and_a_link_and_the_chunk_twins_chain_on(site):
    twin = site.text("wire/index.md")
    assert twin.count("- [Reference number") == 12   # six accepted and six recommended, not the corpus
    more = re.findall(r"\[More\]\((https://almanac\.example\.org/reference-lists/wire/(?:recent|recommended)/c[0-9a-f]+/index\.md)\)", twin)
    assert len(more) == 2
    chunk_twin = site.text(more[0].removeprefix("https://almanac.example.org/"))
    assert "Canonical: https://almanac.example.org/reference-lists/wire/recent/" in chunk_twin
    assert "[Back to The wire](https://almanac.example.org/wire/)" in chunk_twin and "[Next](https://almanac.example.org/reference-lists/wire/recent/" in chunk_twin
    assert chunk_twin.count("- [Reference number") >= 3
    full = site.text("llms-full.txt")
    assert full.count("- [Reference number") == 12, "llms-full.txt carries the first page of the twin, so it does not grow with the corpus"


# ------------------------------------------------------------------ the site's own card drawing

HOOKS = '''
import re

STOCK = re.compile(r'<article class="home-page-tile" data-status="([^"]*)">(.*?)</article>', re.S)


def page_finish(html, page):
    return STOCK.sub(lambda found: '<div class="site-card" data-status="%s">own</div>' % found.group(1), html)
'''


def test_the_sites_hook_draws_the_cards_of_a_later_page_as_it_draws_the_first():
    built = project(snapshot(60, 0), first=4, page_size=8, hooks="hooks.py", extra_files={"hooks.py": HOOKS.encode("utf-8")})
    try:
        page = built.text("wire/index.html")
        assert page.count('class="site-card"') == 4 and "home-page-tile" not in page
        data = chain(built, "recent")
        assert data and all("home-page-tile" not in item["html"] and item["html"].count('class="site-card"') == item["count"] for item in data)
        chunk_page = next(built.text(key) for key in list_files(built) if key.endswith("index.html"))
        assert "site-card" in chunk_page and "home-page-tile" not in chunk_page
    finally:
        built.cleanup()


# ------------------------------------------------------------------ freshness

def rewrite(site, document):
    (site.out / SNAPSHOT_KEY).write_bytes(snapshot_bytes(document))
    site.projector._home_page.reset()
    site.projector._plan_cache = None
    readers = site.projector.home_page_reader_keys()
    site.writer.operations.clear()
    report = project_stale_listings(site.context, readers)
    assert report.ok, report.errors
    return report


def test_a_new_reference_at_the_top_rewrites_a_few_files_not_every_chunk():
    built = project(snapshot(400, 0), first=6, page_size=12)
    try:
        before = list_files(built)
        assert len(before) > 60   # many chunks, so "a few" means something
        document = json.loads(built.text(SNAPSHOT_KEY))
        newest = record(9_999, "accepted", rank=0)
        newest.update(acceptedAt="2099-01-01T00:00:00.000Z", title="Brand new")
        document["references"].insert(0, newest)
        for position, found in enumerate(document["references"], start=1):
            found["rank"] = position   # every later Reference moves down one place
        report = rewrite(built, document)
        written = [key for key in report.written if key.startswith("reference-lists/")]
        assert 0 < len(written) <= 8, written
        assert "wire/index.html" in report.written
        after = list_files(built)
        unchanged = [key for key in before if key in after and before[key] == after[key]]
        assert len(unchanged) >= len(before) - 12
        expected = built.projector.reference_list_keys()
        stored = {key for key in after if built.projector.owns_page_key(key)}
        assert set(_stale_list_files(built.context)) == {key for key in stored if key not in expected}
    finally:
        built.cleanup()


RANKED = b'::band{size="bare"}\n::include{kind="references" select="confident" count="6" paged="true"}\n'


def test_a_rating_that_moves_a_reference_up_touches_only_where_it_left_and_where_it_arrived():
    document = snapshot(400, 0)
    built = project(document, first=6, page_size=12, extra_files={"pages/wire.md": RANKED})
    try:
        before = list_files(built)
        moved = document["references"].pop(250)
        document["references"].insert(0, moved)
        for position, found in enumerate(document["references"], start=1):
            found["rank"] = position   # everything between the two places moves down one
        report = rewrite(built, document)
        written = [key for key in report.written if key.startswith("reference-lists/")]
        assert 0 < len(written) <= 14, written
        assert keys_in(section_of(built.text("wire/index.html"), "confident"))[0] == moved["key"], "the rated Reference leads the ranked list"
    finally:
        built.cleanup()


def test_a_snapshot_that_changes_nothing_a_list_shows_rewrites_no_list_file():
    document = snapshot(300, 0)
    built = project(document, first=6, page_size=12)
    try:
        document["generatedAt"] = "2026-11-05T09:00:00.000Z"
        report = rewrite(built, document)
        assert [key for key in report.written if key.startswith("reference-lists/")] == []
    finally:
        built.cleanup()


def test_a_removed_reference_leaves_the_other_chunks_alone():
    document = snapshot(300, 0)
    built = project(document, first=6, page_size=12)
    try:
        before = list_files(built)
        document["references"] = [found for position, found in enumerate(document["references"]) if position != 150]
        for position, found in enumerate(document["references"], start=1):
            found["rank"] = position
        report = rewrite(built, document)
        written = [key for key in report.written if key.startswith("reference-lists/")]
        assert 0 < len(written) <= 8, written
        assert sum(1 for key in before if built.tree.get(key) == before[key]) >= len(before) - 12
    finally:
        built.cleanup()


def test_a_chunk_that_no_longer_exists_is_found_stale_and_nothing_else_is():
    document = snapshot(200, 0)
    built = project(document, first=6, page_size=12)
    try:
        assert _stale_list_files(built.context) == []
        stray = "reference-lists/wire/recent/cdeadbeef00.json"
        built.writer.put(stray, b"{}")
        stray_page = "reference-lists/wire/recent/cdeadbeef00/index.html"
        built.writer.put(stray_page, b"<p>old</p>")
        assert _stale_list_files(built.context) == sorted([stray, stray_page])
        document["references"] = document["references"][:20]
        rewrite(built, document)
        stale = _stale_list_files(built.context)
        assert stray in stale and any(key.endswith(".json") for key in stale if key != stray)
    finally:
        built.cleanup()
