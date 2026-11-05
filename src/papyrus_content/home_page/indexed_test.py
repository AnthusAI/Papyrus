"""The index reader chooses what the snapshot would choose, for the requests the design counts (docs/plans/public-blocks-from-indexes.md, PPY-7f1e54). Offline."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from papyrus_content.home_page.export import collect_references
from papyrus_content.home_page.indexed import IndexDocument, IndexReader
from papyrus_content.home_page.settings import home_page_settings_from_mapping
from papyrus_content.home_page.snapshot import build_snapshot
from papyrus_content.projection.standard import home_page_blocks as blocks
from papyrus_content.projection.standard.page_ledger import PageLedger
from procedures.newsroom.tests.home_page_index_support import CORPUS, TODAY, IndexedClient, make_corpus, make_row

AS_OF = date(2026, 11, 5)
LABELS = {"Tools": "Tools"}


def settings_for(source: str = "snapshot", **references):
    return home_page_settings_from_mapping({"references": {"corpus": CORPUS, "source": source, **references}})


def both(rows, **references):
    """``(snapshot document, index document, index client)`` over the same rows."""
    snapshot_client = IndexedClient(rows)
    records = collect_references(snapshot_client, CORPUS, settings_for(**references))
    snapshot = build_snapshot(records, datetime.now(timezone.utc), corpus=CORPUS)
    client = IndexedClient(rows)
    reader = IndexReader(client, CORPUS, settings_for("index", **references))
    return snapshot, IndexDocument(reader), client


def chosen(document, attributes, *, placed=(), default_count=6):
    ledger = PageLedger()
    for key in placed:
        ledger.claim(blocks.LEDGER_PREFIX + key)
    found = blocks.select_references(document, attributes, ledger, default_count, LABELS, AS_OF)
    return [record["key"] for record in found]


ATTRIBUTES = [
    {"select": "recent", "count": "3"},
    {"select": "recent", "count": "8"},
    {"select": "confident", "count": "3"},
    {"select": "confident", "count": "10"},
    {"select": "recommended", "count": "3"},
    {"select": "recommended", "count": "12"},
    {"select": "recent", "count": "4", "bucket": "week"},
    {"select": "confident", "count": "5", "bucket": "week"},
    {"select": "recommended", "count": "5", "bucket": "week"},
    {"select": "recommended", "count": "5", "bucket": "day"},
    {"select": "recent", "count": "3", "medium": "video"},
    {"select": "recent", "count": "5", "section": "Tools"},
    {"select": "confident", "count": "2", "section": "Tools"},
]


@pytest.mark.parametrize("attributes", ATTRIBUTES, ids=lambda attributes: " ".join(f"{k}={v}" for k, v in attributes.items()))
def test_a_block_chooses_from_the_index_what_it_chooses_from_the_file(attributes):
    snapshot, index, _client = both(make_corpus())
    found = chosen(snapshot, attributes)
    assert found, "the fixture must give every block something to choose"
    assert chosen(index, attributes) == found, attributes


@pytest.mark.parametrize("attributes", ATTRIBUTES[:10], ids=lambda attributes: " ".join(f"{k}={v}" for k, v in attributes.items()))
def test_a_block_skips_what_the_page_already_placed_and_still_fills_its_count(attributes):
    snapshot, index, _client = both(make_corpus())
    first = chosen(snapshot, {**attributes, "count": "4"})
    assert chosen(index, attributes, placed=first[:4]) == chosen(snapshot, attributes, placed=first[:4])


def test_the_threshold_decides_which_pending_rows_are_recommended():
    snapshot, index, _client = both(make_corpus(), recommendedThreshold=0.8)
    attributes = {"select": "recommended", "count": "10"}
    assert chosen(index, attributes) == chosen(snapshot, attributes)
    assert all(record["confidence"] >= 0.8 for record in index.for_block(attributes, 10, AS_OF)["references"])


def test_a_threshold_below_one_half_is_an_error_on_the_index_path_that_names_the_setting():
    with pytest.raises(ValueError, match="recommendedThreshold"):
        settings_for("index", recommendedThreshold=0.4)
    assert settings_for("snapshot", recommendedThreshold=0.4).references.recommended_threshold == 0.4


def test_an_unpredicted_pending_row_is_never_recommended():
    rows = make_corpus(pending_per_day=0, days=1) + [make_row("quiet", "pending", arrived=TODAY, probability=None), make_row("sure", "pending", arrived=TODAY, probability=0.9)]
    _snapshot, index, _client = both(rows)
    keys = [record["title"] for record in index.for_block({"select": "recommended"}, 10, AS_OF)["references"]]
    assert keys == ["Title of sure"]


def test_stars_order_the_blocks_and_stay_out_of_every_key_and_record():
    snapshot, index, _client = both(make_corpus(starred=3))
    for select in ("confident", "recommended"):
        attributes = {"select": select, "count": "6"}
        assert chosen(index, attributes) == chosen(snapshot, attributes)
    for record in index.for_block({"select": "confident"}, 10, AS_OF)["references"]:
        assert "starRating" not in record and "starFeedKey" not in record


def test_ties_at_the_cut_are_read_whole_so_the_order_is_the_files():
    rows = [make_row(f"tie-{n}", "accepted", probability=0.7, arrived=TODAY, accepted=TODAY) for n in range(7)]
    snapshot, index, _client = both(rows)
    attributes = {"select": "confident", "count": "3"}
    assert chosen(index, attributes) == chosen(snapshot, attributes)
    recent = {"select": "recent", "count": "3"}
    assert chosen(index, recent) == chosen(snapshot, recent)


def test_within_a_rounding_tier_the_index_orders_by_the_stored_prediction_at_full_precision():
    """The snapshot ranks on the prediction rounded to two places; the index sorts on the stored value. They differ only inside one tier."""
    rows = [make_row("later", "accepted", probability=0.904, arrived=TODAY, accepted=TODAY), make_row("sooner", "accepted", probability=0.896, arrived=TODAY.replace(hour=13), accepted=TODAY)]
    snapshot, index, _client = both(rows)
    attributes = {"select": "confident", "count": "2"}
    assert chosen(snapshot, attributes) != chosen(index, attributes)
    assert sorted(chosen(snapshot, attributes)) == sorted(chosen(index, attributes))


def test_the_records_are_the_files_records_except_where_the_stored_prediction_replaces_a_decision():
    snapshot, index, _client = both(make_corpus())
    wanted = {record["key"]: record for record in snapshot["references"]}
    for record in index.for_block({"select": "confident"}, 12, AS_OF)["references"]:
        original = {name: value for name, value in wanted[record["key"]].items() if name != "rank"}
        assert {name: value for name, value in record.items() if name != "rank"} == original, record["key"]


# --- the requests, counted (the numbers of docs/plans/public-blocks-from-indexes.md) ---------------------------------------------------------------


def requests_for(*blocks_asked: dict, rows=None) -> dict[str, int]:
    client = IndexedClient(rows if rows is not None else make_corpus())
    index = IndexDocument(IndexReader(client, CORPUS, settings_for("index")))
    ledger = PageLedger()
    for attributes in blocks_asked:
        blocks.select_references(index, attributes, ledger, 6, LABELS, AS_OF)
    return dict(client.requests)


def test_a_recent_block_is_one_page_of_the_accepted_list_and_reads_no_star_and_no_decision():
    assert requests_for({"select": "recent", "count": "3"}) == {"referencesByCurationStatusKey": 1, "sections": 1}


def test_a_confident_block_is_one_page_of_the_public_index_and_the_five_star_partitions_once():
    found = requests_for({"select": "confident", "count": "3"})
    assert found["referencesByPublicFeed"] == 1 and found["referencesByStarFeedAndArrival"] == 5 and found["sections"] == 1 and sum(found.values()) == 7


def test_a_recommended_block_reads_the_prediction_index_down_to_the_threshold_in_one_page():
    found = requests_for({"select": "recommended", "count": "3"})
    assert found["referencesByFeedStateAndPrediction"] == 1 and sum(found.values()) == 7


def test_the_stars_and_the_sections_are_read_once_for_every_block_of_a_run():
    found = requests_for({"select": "recent", "count": "3"}, {"select": "confident", "count": "3"}, {"select": "recommended", "count": "2"},
                         {"select": "confident", "count": "6"}, {"select": "recommended", "count": "6"})
    assert found["referencesByStarFeedAndArrival"] == 5 and found["sections"] == 1, found


def test_a_weekly_recommended_block_is_one_query_per_day_of_its_window_and_one_to_find_where_to_stop():
    found = requests_for({"select": "recommended", "count": "3", "bucket": "week"})
    assert found["referencesByPublicFeed"] == 7 and found["referencesByFeedStateAndArrival"] == 1, found


def test_a_window_that_the_first_week_fills_costs_no_second_week():
    found = requests_for({"select": "recommended", "count": "20", "bucket": "week"})
    assert found["referencesByPublicFeed"] == 7, "the first week holds far more than twenty"


def test_a_block_that_a_week_cannot_fill_goes_on_to_the_next_window_and_stops_at_the_oldest_row():
    rows = make_corpus(days=10, pending_per_day=1)
    found = requests_for({"select": "recommended", "count": "500", "bucket": "week"}, rows=rows)
    assert found["referencesByPublicFeed"] == 14, "two windows of seven days, then the oldest pending row ends it"


def test_a_page_never_reads_more_of_a_partition_than_the_rows_it_places_need():
    rows = make_corpus(days=30, accepted_per_day=40, pending_per_day=0)
    found = requests_for({"select": "recent", "count": "3"}, rows=rows)
    assert found["referencesByCurationStatusKey"] == 1, "twelve hundred accepted rows, one page of a hundred"
