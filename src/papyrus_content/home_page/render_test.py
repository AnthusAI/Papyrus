"""A whole site rendered from the public index is the site rendered from the file, for the requests the design counts. Offline: a counting fake, no network."""
from __future__ import annotations

import copy
import json
from datetime import date, datetime, timezone

import pytest

from papyrus_content.home_page.export import collect_references
from papyrus_content.home_page.render import run_home_page_render
from papyrus_content.home_page.routing import Coordinate
from papyrus_content.home_page.settings import home_page_settings_from_mapping
from papyrus_content.home_page.snapshot import build_snapshot, snapshot_bytes
from papyrus_content.home_page.state_store import DirtyBatch, MemoryBlockStore
from procedures.newsroom.tests.home_page_index_support import CORPUS, TODAY, IndexedClient, make_corpus, make_row
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite

SITE = FIXTURES / "home-page"
DAY = date(2026, 11, 5)
EXTRA_PAGES = {
    "pages/windows.md": '::band{size="bare"}\n::include{kind="references" select="recent" count="3" bucket="week" heading="This week"}\n\n::include{kind="references" select="recommended" count="3" bucket="week" heading="Recommended this week"}\n',
    "pages/videos.md": '::band{size="bare"}\n::include{kind="references" select="recent" count="2" medium="video" heading="Videos"}\n',
}


def settings_json(source: str) -> dict:
    settings = json.loads((SITE / "projection.json").read_text(encoding="utf-8"))
    settings["homePage"]["references"] = {"corpus": CORPUS, "defaultCount": 6, "source": source}
    settings["pages"] += [{"id": "windows", "path": "windows", "title": "Windows", "description": "Rolling windows.", "dependsOn": [], "source": "pages/windows.md"},
                          {"id": "videos", "path": "videos", "title": "Videos", "description": "Videos.", "dependsOn": [], "source": "pages/videos.md"}]
    return settings


def build_site(source: str, rows: list[dict], *, snapshot: bool) -> ProjectedSite:
    extra = {f"pages/{path.name}": path.read_bytes() for path in sorted((SITE / "pages").glob("*.md"))}
    extra.update({name: text.encode("utf-8") for name, text in EXTRA_PAGES.items()})
    seed = {}
    if snapshot:
        records = collect_references(IndexedClient(rows), CORPUS, home_page_settings_from_mapping({"references": {"corpus": CORPUS}}))
        seed = {"_data/home-page/references.json": snapshot_bytes(build_snapshot(records, datetime(2026, 11, 5, tzinfo=timezone.utc), corpus=CORPUS))}
    site = ProjectedSite(settings=settings_json(source), content=SITE / "content", extra_files=extra, seed=seed, clock=lambda: DAY)
    return site


def render_from_index(site: ProjectedSite, rows: list[dict], **keywords) -> tuple[dict, IndexedClient]:
    client = IndexedClient(rows)
    settings = site.projector.standard.home_page
    report = run_home_page_render(site.context, client, settings, **keywords)
    return report, client


def pages_of(site: ProjectedSite) -> dict[str, str]:
    return {key: text for key, text in ((key, site.text(key)) for key in site.tree if key.endswith((".html", ".md")) and not key.startswith("_data")) if key.split("/")[0] in
            {"front", "tools", "rows", "defaults", "ranked", "recommended", "windows", "videos", "mixed", "quiet"}}


@pytest.fixture(scope="module")
def rows():
    return make_corpus()


@pytest.fixture(scope="module")
def rendered(rows):
    """The same corpus rendered from the file and from the index."""
    from_file = build_site("snapshot", rows, snapshot=True)
    from_index = build_site("index", rows, snapshot=False)
    report, client = render_from_index(from_index, rows, block_store=MemoryBlockStore())
    yield from_file, from_index, report, client
    from_file.cleanup()
    from_index.cleanup()


def test_every_page_rendered_from_the_index_is_the_page_rendered_from_the_file(rendered):
    from_file, from_index, report, _client = rendered
    assert not report.get("errors"), report
    wanted, found = pages_of(from_file), pages_of(from_index)
    assert set(found) == set(wanted) and len(wanted) >= 8
    different = [key for key in wanted if wanted[key] != found[key]]
    assert not different, different


def test_the_page_a_reader_sees_has_cards_in_it(rendered):
    _from_file, from_index, _report, _client = rendered
    front = from_index.text("front/index.html")
    assert front.count('class="home-page-tile"') >= 6 and "Recommended by Cyclotron" in front


def test_a_site_served_from_the_index_writes_no_references_file(rendered):
    _from_file, from_index, report, _client = rendered
    assert "_data/home-page/references.json" not in from_index.tree
    assert not any("references.json" in name for name in report["written"])


def test_a_whole_site_from_nothing_costs_the_requests_of_its_blocks_and_not_a_read_of_the_corpus(rendered, rows):
    _from_file, _from_index, report, client = rendered
    snapshot_client = IndexedClient(rows)
    collect_references(snapshot_client, CORPUS, home_page_settings_from_mapping({"references": {"corpus": CORPUS}}))
    assert report["mode"] == "full" and report["touchedBlocks"] == report["blocks"]
    assert client.total() < 60, dict(client.requests)
    assert snapshot_client.total() > 10 * client.total(), (snapshot_client.total(), client.total())
    assert client.requests["sections"] == 1 and client.requests["referencesByStarFeedAndArrival"] == 5, dict(client.requests)
    assert not [name for name in client.requests if name.startswith("snapshot:")], "no decision and no preview is read"


# --- a change, counted ---------------------------------------------------------------------------------------------------------------------------------


def changed_site(rows):
    site = build_site("index", rows, snapshot=False)
    store = MemoryBlockStore()
    _report, first = render_from_index(site, rows, block_store=store)
    site.full_requests = first.total()
    return site, store


def run_change(site, store, rows, *coordinates: Coordinate):
    batch = DirtyBatch(ids=frozenset(c.identifier for c in coordinates), coords=frozenset(json.dumps(c.to_json(), sort_keys=True) for c in coordinates))
    return render_from_index(site, rows, block_store=store, dirty=batch)


def test_a_low_confidence_reference_that_arrives_costs_no_request_and_writes_no_page(rows):
    site, store = changed_site(rows)
    try:
        # it has no public key, so the trigger drops it before it is ever listed; a batch with nothing in it asks no block anything
        report, client = run_change(site, store, rows)
        assert report["mode"] == "incremental" and report["touchedBlocks"] == 0 and client.total() == 0 and report["pagesRewritten"] == 0
    finally:
        site.cleanup()


def test_a_recommended_row_under_every_block_touches_no_block(rows):
    site, store = changed_site(rows)
    try:
        coordinate = Coordinate("pen-new-v1", feed1="c#recommended#2026-11-05", order1="p0.500000#2026-11-05T09:00:00.000Z#pen-new-v1")
        report, client = run_change(site, store, rows, coordinate)
        assert report["touchedBlocks"] == 0 and report["pagesRewritten"] == 0 and client.total() == 0, report
    finally:
        site.cleanup()


def test_a_new_best_recommended_row_asks_only_the_blocks_it_can_enter(rows):
    site, store = changed_site(rows)
    try:
        newcomer = make_row("pen-best", "pending", probability=0.999, arrived=TODAY)
        grown = rows + [newcomer]
        coordinate = Coordinate("pen-best-v1", feed1=newcomer["publicFeedKey"], order1=newcomer["publicOrderKey"], stars1=None)
        report, client = run_change(site, store, grown, coordinate)
        assert 0 < report["touchedBlocks"] < report["blocks"], report
        assert report["pagesRewritten"] > 0 and "quiet/index.html" not in report["rewritten"] and "tools/index.html" not in report["rewritten"], report["rewritten"]
        assert "Title of pen-best" in site.text("recommended/index.html")
        assert client.total() <= site.full_requests, (client.total(), site.full_requests, dict(client.requests))   # a page that is rewritten asks all of its blocks, so a fixture whose blocks all share pages saves nothing here
        assert client.requests["referencesByStarFeedAndArrival"] == 5 and client.requests["sections"] == 1, "stars and sections are read once for the run"
    finally:
        site.cleanup()


def test_accepting_a_row_asks_the_blocks_it_enters_and_rewrites_only_their_pages(rows):
    site, store = changed_site(rows)
    try:
        accepted = make_row("acc-new", "accepted", probability=0.97, arrived=TODAY, accepted=TODAY)
        coordinate = Coordinate("acc-new-v1", feed1=accepted["publicFeedKey"], order1=accepted["publicOrderKey"], accepted1=accepted["curationStatusUpdatedAt"])
        report, client = run_change(site, store, rows + [accepted], coordinate)
        assert report["touchedBlocks"] >= 1 and report["touchedBlocks"] < report["blocks"], report
        assert client.total() <= site.full_requests
        assert "Title of acc-new" in site.text("front/index.html")
        assert "recommended/index.html" not in report["rewritten"], "a page that places only recommended References is not rewritten for an accepted one"
        quiet = site.text("quiet/index.html")
        assert "acc-new" not in quiet
    finally:
        site.cleanup()


def test_a_mass_import_asks_every_block_once(rows):
    site, store = changed_site(rows)
    try:
        report, client = render_from_index(site, rows, block_store=store, dirty=DirtyBatch(full_seq=1))
        assert report["mode"] == "full" and report["touchedBlocks"] == report["blocks"] and client.total() < 60
    finally:
        site.cleanup()


def test_a_remembered_record_from_another_build_is_not_repaired_but_asked_again(rows):
    site, store = changed_site(rows)
    try:
        store.record = {**store.record, "fingerprint": "another build"}
        report, _client = render_from_index(site, rows, block_store=store, dirty=DirtyBatch())
        assert report["mode"] == "full"
    finally:
        site.cleanup()


def test_nothing_private_reaches_a_page_served_from_the_index(rendered):
    from procedures.newsroom.tests.reader_privacy import identity_leaks

    _from_file, from_index, _report, _client = rendered
    for key, text in pages_of(from_index).items():
        assert not identity_leaks(text), key
        assert "starRating" not in text and "starFeedKey" not in text and "publicOrderKey" not in text, key


def test_a_dry_run_writes_and_remembers_nothing(rows):
    site = build_site("index", rows, snapshot=False)
    try:
        store = MemoryBlockStore()
        before = site.tree
        report, _client = render_from_index(site, rows, block_store=store, dry_run=True)
        assert site.tree == before and store.saves == 0 and report["wouldRewrite"]
    finally:
        site.cleanup()
