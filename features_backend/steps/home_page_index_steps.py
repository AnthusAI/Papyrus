"""Steps for features_backend/home-page-index.feature. Everything is in memory: a counting fake of the indexes, no network, no AWS."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.home_page.parity import ROUNDING_TIER, parity_report  # noqa: E402
from papyrus_content.home_page.render_test import build_site, pages_of, render_from_index  # noqa: E402
from papyrus_content.home_page.routing import Coordinate  # noqa: E402
from papyrus_content.home_page.settings import home_page_settings_from_mapping  # noqa: E402
from papyrus_content.home_page.state_store import DirtyBatch, MemoryBlockStore  # noqa: E402
from procedures.newsroom.tests.home_page_index_support import CORPUS, TODAY, IndexedClient, make_corpus, make_row  # noqa: E402


@given("a corpus of References with accepted, recommended, starred and video rows")
def a_corpus(context) -> None:
    context.rows = make_corpus()


@given("a pending Reference nobody predicted")
def an_unpredicted_reference(context) -> None:
    context.rows = [*context.rows, make_row("never-predicted", "pending", probability=None, arrived=TODAY)]


@given("two accepted References whose confidences round to the same percentage")
def two_alike(context) -> None:
    context.rows = [make_row("later", "accepted", probability=0.904, arrived=TODAY, accepted=TODAY),
                    make_row("sooner", "accepted", probability=0.896, arrived=TODAY.replace(hour=13), accepted=TODAY)]


def remember(context, site):
    context.add_cleanup(site.cleanup)
    return site


@given("the fixture site rendered from the public index")
def rendered_once(context) -> None:
    context.index_site = remember(context, build_site("index", context.rows, snapshot=False))
    context.store = MemoryBlockStore()
    context.report, context.client = render_from_index(context.index_site, context.rows, block_store=context.store)
    context.first_requests = context.client.total()


@when("the fixture site is rendered from the public index")
def render_index(context) -> None:
    context.index_site = remember(context, build_site("index", context.rows, snapshot=False))
    context.report, context.client = render_from_index(context.index_site, context.rows, block_store=MemoryBlockStore())


@when("the fixture site is rendered from the file and from the public index")
def render_both(context) -> None:
    context.file_site = remember(context, build_site("snapshot", context.rows, snapshot=True))
    context.index_site = remember(context, build_site("index", context.rows, snapshot=False))
    context.report, context.client = render_from_index(context.index_site, context.rows, block_store=MemoryBlockStore())
    sites = {"snapshot": remember(context, build_site("snapshot", [], snapshot=False)), "index": remember(context, build_site("index", [], snapshot=False))}
    context.parity = parity_report(IndexedClient(context.rows), lambda variant: (sites[variant].context, sites[variant].out))


@then("every page that places a Reference is identical in both")
def identical(context) -> None:
    wanted, found = pages_of(context.file_site), pages_of(context.index_site)
    assert set(wanted) == set(found) and wanted, sorted(set(wanted) ^ set(found))
    assert [key for key in wanted if wanted[key] != found[key]] == []


@then("the pages include Markdown twins")
def twins(context) -> None:
    assert any(key.endswith(".md") for key in pages_of(context.index_site))


@then("fewer than {count:d} requests were made")
def fewer_than(context, count: int) -> None:
    assert context.client.total() < count, dict(context.client.requests)


@then("no decision and no preview was read")
def no_per_row_reads(context) -> None:
    assert not [name for name in context.client.requests if name.startswith("snapshot:")], dict(context.client.requests)


@then("the star partitions were read once for the whole run and the section labels once")
def once(context) -> None:
    assert context.client.requests["referencesByStarFeedAndArrival"] == 5 and context.client.requests["sections"] == 1, dict(context.client.requests)


@then("no file of References was written")
def no_file(context) -> None:
    assert "_data/home-page/references.json" not in context.index_site.tree


@then("no page shows the unpredicted Reference")
def not_shown(context) -> None:
    assert all("never-predicted" not in text for text in pages_of(context.index_site).values())


@when("a batch arrives that holds no change a block can show")
def an_empty_batch(context) -> None:
    context.report, context.client = render_from_index(context.index_site, context.rows, block_store=context.store, dirty=DirtyBatch())


@then("no block was asked and no request was made and no page was rewritten")
def nothing(context) -> None:
    assert context.report["mode"] == "incremental" and context.report["touchedBlocks"] == 0 and context.client.total() == 0 and context.report["pagesRewritten"] == 0, context.report


@when("a new accepted Reference with a high confidence is recorded as a change")
def accepted_arrives(context) -> None:
    newcomer = make_row("acc-new", "accepted", probability=0.97, arrived=TODAY, accepted=TODAY)
    coordinate = Coordinate("acc-new-v1", feed1=newcomer["publicFeedKey"], order1=newcomer["publicOrderKey"], accepted1=newcomer["curationStatusUpdatedAt"])
    batch = DirtyBatch(ids=frozenset({coordinate.identifier}), coords=frozenset({json.dumps(coordinate.to_json(), sort_keys=True)}))
    context.report, context.client = render_from_index(context.index_site, [*context.rows, newcomer], block_store=context.store, dirty=batch)


@then("the front page shows it")
def front_shows(context) -> None:
    assert "Title of acc-new" in context.index_site.text("front/index.html")


@then("the page that places only recommended References is not rewritten")
def recommended_untouched(context) -> None:
    assert "recommended/index.html" not in context.report["rewritten"], context.report["rewritten"]


@when("the trigger reports that a window held more changes than it can list")
def mass_import(context) -> None:
    context.report, context.client = render_from_index(context.index_site, context.rows, block_store=context.store, dirty=DirtyBatch(full_seq=1))


@then("every block was asked and the run says it was full")
def everything(context) -> None:
    assert context.report["mode"] == "full" and context.report["touchedBlocks"] == context.report["blocks"]


@when('the settings name source "index" and a recommended threshold of {threshold:g}')
def refused_settings(context, threshold: float) -> None:
    context.error = None
    try:
        home_page_settings_from_mapping({"references": {"corpus": CORPUS, "source": "index", "recommendedThreshold": threshold}})
    except ValueError as error:
        context.error = str(error)


@then("the settings are refused and the message names the threshold")
def named(context) -> None:
    assert context.error and "recommendedThreshold" in context.error, context.error


@then("the report says the pages differ only inside a rounding tier")
def rounding(context) -> None:
    assert context.parity["differing"] and {item["kind"] for item in context.parity["differing"]} == {ROUNDING_TIER}, context.parity


@then("the check does not fail")
def does_not_fail(context) -> None:
    assert context.parity["ok"] is True


# --- paged lists ---------------------------------------------------------------------------------------------------------------------------------


@when("the paged fixture site is rendered from the file and from the public index")
def render_paged_both(context) -> None:
    from papyrus_content.home_page.render_paged_test import build

    context.file_site = remember(context, build("snapshot", context.rows, snapshot=True))
    context.index_site = remember(context, build("index", context.rows, snapshot=False))
    context.report, context.client = render_from_index(context.index_site, context.rows, block_store=MemoryBlockStore())


@then("every page and every chunk file of every paged list is identical in both")
def chunks_identical(context) -> None:
    from papyrus_content.home_page.render_paged_test import lists_of

    wanted, found = lists_of(context.file_site), lists_of(context.index_site)
    assert any(key.startswith("reference-lists/") for key in wanted) and set(wanted) == set(found)
    assert [key for key in wanted if wanted[key] != found[key]] == []


@given("the paged fixture site rendered from the public index")
def paged_rendered(context) -> None:
    from papyrus_content.home_page.render_paged_test import build

    context.index_site = remember(context, build("index", context.rows, snapshot=False))
    context.store = MemoryBlockStore()
    context.report, context.client = render_from_index(context.index_site, context.rows, block_store=context.store)


@when("a new recommended Reference is recorded as a change")
def recommended_arrives(context) -> None:
    newcomer = make_row("pen-wire", "pending", probability=0.8, arrived=TODAY)
    coordinate = Coordinate("pen-wire-v1", feed1=newcomer["publicFeedKey"], order1=newcomer["publicOrderKey"])
    batch = DirtyBatch(ids=frozenset({coordinate.identifier}), coords=frozenset({json.dumps(coordinate.to_json(), sort_keys=True)}))
    context.report, context.client = render_from_index(context.index_site, [*context.rows, newcomer], block_store=context.store, dirty=batch)


@then("the paged list shows it")
def paged_shows(context) -> None:
    from papyrus_content.home_page.render_paged_test import lists_of

    assert "Title of pen-wire" in "".join(lists_of(context.index_site).values())
