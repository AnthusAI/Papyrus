"""Paged Reference lists served from the public index: the same chunks as from the file, and what a change costs (the whole list is read; docs/plans/public-blocks-from-indexes.md). Offline."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from papyrus_content.home_page.export import collect_references
from papyrus_content.home_page.render import run_home_page_render
from papyrus_content.home_page.render_test import DAY, SITE, render_from_index, run_change
from papyrus_content.home_page.settings import home_page_settings_from_mapping
from papyrus_content.home_page.snapshot import build_snapshot, snapshot_bytes
from papyrus_content.home_page.state_store import DirtyBatch, MemoryBlockStore
from procedures.newsroom.tests.home_page_index_support import CORPUS, TODAY, IndexedClient, make_corpus, make_row
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite

WIRE = '::band{size="bare"}\n::include{kind="references" select="recommended" count="3" paged="true" id="wire" heading="Wire"}\n'
ARCHIVE = '::band{size="bare"}\n::include{kind="references" select="recent" count="2" paged="true" id="archive" heading="Archive"}\n'
PAGES = {"pages/wire.md": WIRE, "pages/archive.md": ARCHIVE}


def build(source: str, rows: list[dict], *, snapshot: bool) -> ProjectedSite:
    settings = json.loads((SITE / "projection.json").read_text(encoding="utf-8"))
    settings["homePage"]["references"] = {"corpus": CORPUS, "defaultCount": 6, "source": source, "paging": {"pageSize": 8}}
    settings["pages"] += [{"id": "wire", "path": "wire", "title": "Wire", "description": "Everything recommended.", "dependsOn": [], "source": "pages/wire.md"},
                          {"id": "archive", "path": "archive", "title": "Archive", "description": "Everything accepted.", "dependsOn": [], "source": "pages/archive.md"}]
    extra = {f"pages/{path.name}": path.read_bytes() for path in sorted((SITE / "pages").glob("*.md"))}
    extra.update({name: text.encode("utf-8") for name, text in PAGES.items()})
    seed = {}
    if snapshot:
        records = collect_references(IndexedClient(rows), CORPUS, home_page_settings_from_mapping({"references": {"corpus": CORPUS}}))
        seed = {"_data/home-page/references.json": snapshot_bytes(build_snapshot(records, datetime(2026, 11, 5, tzinfo=timezone.utc), corpus=CORPUS))}
    return ProjectedSite(settings=settings, content=SITE / "content", extra_files=extra, seed=seed, clock=lambda: DAY)


def lists_of(site: ProjectedSite) -> dict[str, str]:
    return {key: site.text(key) for key in site.tree if key.startswith(("reference-lists/", "wire/", "archive/")) and key.endswith((".html", ".json", ".md"))}


@pytest.fixture(scope="module")
def rows():
    return make_corpus(days=6, pending_per_day=25)


@pytest.fixture(scope="module")
def rendered(rows):
    from_file, from_index = build("snapshot", rows, snapshot=True), build("index", rows, snapshot=False)
    report, client = render_from_index(from_index, rows, block_store=MemoryBlockStore())
    yield from_file, from_index, report, client
    from_file.cleanup()
    from_index.cleanup()


def test_every_chunk_of_every_list_is_the_chunk_the_file_makes(rendered):
    from_file, from_index, report, _client = rendered
    assert not report.get("errors"), report
    wanted, found = lists_of(from_file), lists_of(from_index)
    assert len([key for key in wanted if key.startswith("reference-lists/")]) >= 6, "the lists are long enough to be cut into several chunks"
    assert set(found) == set(wanted)
    assert [key for key in wanted if wanted[key] != found[key]] == []


def test_a_whole_list_costs_one_request_for_every_hundred_rows_and_the_stars_once(rendered, rows):
    _from_file, _from_index, _report, client = rendered
    pending = len([row for row in rows if row["curationStatus"] == "pending" and (row.get("predictedAcceptProbability") or 0) >= 0.5])
    assert client.requests["referencesByFeedStateAndPrediction"] <= -(-pending // 100) + 2, dict(client.requests)
    assert client.requests["referencesByStarFeedAndArrival"] == 5


def test_a_row_that_can_be_in_a_list_asks_the_list_again_and_a_row_that_cannot_asks_nothing(rows):
    site = build("index", rows, snapshot=False)
    try:
        store = MemoryBlockStore()
        render_from_index(site, rows, block_store=store)
        from papyrus_content.home_page.routing import Coordinate

        none = DirtyBatch()
        report, client = render_from_index(site, rows, block_store=store, dirty=none)
        assert report["touchedBlocks"] == 0 and client.total() == 0 and report["pagesRewritten"] == 0
        newcomer = make_row("pen-wire", "pending", probability=0.8, arrived=TODAY)
        coordinate = Coordinate("pen-wire-v1", feed1=newcomer["publicFeedKey"], order1=newcomer["publicOrderKey"])
        report, client = run_change(site, store, [*rows, newcomer], coordinate)
        assert report["touchedBlocks"] >= 1 and client.requests["referencesByFeedStateAndPrediction"] >= 1
        assert "Title of pen-wire" in "".join(lists_of(site).values())
    finally:
        site.cleanup()


def test_a_chunk_file_the_new_cuts_no_longer_make_is_deleted(rows):
    site = build("index", rows, snapshot=False)
    try:
        store = MemoryBlockStore()
        render_from_index(site, rows, block_store=store)
        before = {key for key in site.tree if key.startswith("reference-lists/")}
        shrunk = [row for row in rows if not (row["curationStatus"] == "pending" and row["lineageId"].startswith(("pen-3", "pen-4", "pen-5")))]
        client = IndexedClient(shrunk)
        report = run_home_page_render(site.context, client, site.projector.standard.home_page, block_store=store, dirty=DirtyBatch(full_seq=1))
        after = {key for key in site.tree if key.startswith("reference-lists/")}
        assert before - after and report["deleted"], (len(before), len(after))
    finally:
        site.cleanup()
