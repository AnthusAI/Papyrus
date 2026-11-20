"""The Reference adapters of the shared ranking: ``rank`` as a position in the public snapshot, and Reference windows (``home_page/ordering.py``). The algorithm is tested in ``quality_ranking_test.py``."""

import random
from datetime import date, timedelta

import pytest

from papyrus_content.home_page.ordering import (
    bucket_moment,
    has_ranks,
    order_in_buckets,
    order_public_records,
    rank_records,
)
from papyrus_content.quality_ranking import rank


def reference(key, stars=None, confidence=0.5, arrived="2026-10-10T00:00:00.000Z", accepted=None):
    return {"key": key, "stars": stars, "confidence": confidence, "arrivedAt": arrived, "acceptedAt": accepted}


def shared(items):
    return [item["key"] for item in rank(items, stars=lambda i: i["stars"], confidence=lambda i: i["confidence"], newest=lambda i: i["arrivedAt"], key=lambda i: i["key"])]


def public(key, rank, **fields):
    return {"key": key, "rank": rank, "confidence": 0.5, "arrivedAt": "2026-10-01T00:00:00.000Z", **fields}


def test_rank_is_a_position_over_every_reference_and_never_a_star_count():
    items = [(public("a", 0, confidence=0.9), None), (public("b", 0, confidence=0.1), 5), (public("c", 0, confidence=0.99), 1), (public("d", 0, confidence=0.5), None)]
    ranks = rank_records(items)
    assert ranks == {"b": 1, "a": 2, "d": 3, "c": 4}
    assert sorted(ranks.values()) == [1, 2, 3, 4]


def test_the_rank_order_restricted_to_any_subset_is_the_order_of_that_subset():
    rng = random.Random(7)
    items = [(public(f"k{n}", 0, confidence=rng.choice([0.1, 0.5, 0.9]), arrivedAt=f"2026-10-{n + 1:02d}T00:00:00.000Z"), rng.choice([None, None, 1, 2, 3, 4, 5])) for n in range(14)]
    ranks = rank_records(items)
    subset = [pair for pair in items if pair[0]["key"] not in ("k3", "k7", "k11")]
    from_ranks = [record["key"] for record in order_public_records([{**pair[0], "rank": ranks[pair[0]["key"]]} for pair in subset])]
    assert from_ranks == shared([{"key": pair[0]["key"], "stars": pair[1], "confidence": pair[0]["confidence"], "arrivedAt": pair[0]["arrivedAt"]} for pair in subset])


def test_records_with_ranks_are_ordered_by_rank_and_records_without_are_ordered_as_unrated():
    ranked = [public("a", 3), public("b", 1), public("c", 2)]
    assert has_ranks(ranked) and [record["key"] for record in order_public_records(ranked)] == ["b", "c", "a"]
    older = [{"key": "a", "confidence": 0.2, "arrivedAt": "2026-10-01T00:00:00.000Z"}, {"key": "b", "confidence": 0.9, "arrivedAt": "2026-10-01T00:00:00.000Z"}]
    assert not has_ranks(older) and [record["key"] for record in order_public_records(older)] == ["b", "a"]
    assert not has_ranks([public("a", 1), {"key": "b"}]), "one record without a rank means the snapshot predates ranks"
    assert not has_ranks([{"key": "a", "rank": True}])


@pytest.mark.parametrize(
    "accepted, arrived, expected",
    [
        ("2026-10-25T23:59:59.999Z", "2026-10-01T00:00:00.000Z", "2026-10-25T23:59:59.999Z"),
        (None, "2026-10-21T10:00:00.000Z", "2026-10-21T10:00:00.000Z"),   # no accepted time: the arrival
        ("", "2026-10-21T10:00:00.000Z", "2026-10-21T10:00:00.000Z"),
        ("not a date", "2026-10-21T10:00:00.000Z", "2026-10-21T10:00:00.000Z"),
        (None, None, None),
    ],
)
def test_a_reference_is_bucketed_by_the_date_the_selection_orders_by(accepted, arrived, expected):
    assert bucket_moment({"acceptedAt": accepted, "arrivedAt": arrived}) == expected


AS_OF = date(2026, 10, 29)


def test_newest_window_first_and_the_shared_order_inside_each_window():
    records = [
        public("old-5star", 1, acceptedAt="2026-10-20T00:00:00.000Z"),
        public("new-unrated", 2, acceptedAt="2026-10-27T00:00:00.000Z"),
        public("old-unrated", 3, acceptedAt="2026-10-21T00:00:00.000Z"),
        public("new-1star", 4, acceptedAt="2026-10-28T00:00:00.000Z"),
    ]
    assert [record["key"] for record in order_in_buckets(records, "week", AS_OF)] == ["new-unrated", "new-1star", "old-5star", "old-unrated"]
    assert [record["key"] for record in order_in_buckets(records, "day", AS_OF)] == ["new-1star", "new-unrated", "old-unrated", "old-5star"]


def test_a_week_is_the_last_seven_days_and_not_the_calendar_week():
    # 2026-10-26 is a Monday. As of Wednesday the 28th a calendar week would split the 25th (Sunday) from the 26th; rolling puts both in the last seven days.
    records = [public("sunday", 1, acceptedAt="2026-10-25T09:00:00.000Z"), public("monday", 2, acceptedAt="2026-10-26T09:00:00.000Z"), public("older", 3, acceptedAt="2026-10-21T09:00:00.000Z")]
    assert [record["key"] for record in order_in_buckets(records, "week", date(2026, 10, 28))] == ["sunday", "monday", "older"], "window 0 is Oct 22-28, ranked inside; older is window 1"
    assert [record["key"] for record in order_in_buckets(records, "week", date(2026, 10, 29))] == ["sunday", "monday", "older"]


def test_a_reference_crosses_into_the_older_window_with_time_alone_and_nothing_is_dropped():
    records = [public("a", 1, acceptedAt="2026-10-22T09:00:00.000Z"), public("b", 2, acceptedAt="2026-10-28T09:00:00.000Z"), public("c", 3, acceptedAt="2026-10-15T09:00:00.000Z")]
    assert [record["key"] for record in order_in_buckets(records, "week", date(2026, 10, 28))] == ["a", "b", "c"]
    after = order_in_buckets(records, "week", date(2026, 10, 29))   # a is now 7 days old
    assert [record["key"] for record in after] == ["b", "a", "c"]


def test_the_order_changes_only_on_the_day_a_reference_crosses_a_window():
    records = [public("a", 1, acceptedAt="2026-10-22T09:00:00.000Z"), public("b", 2, acceptedAt="2026-10-28T09:00:00.000Z")]
    orders = [[record["key"] for record in order_in_buckets(records, "week", date(2026, 10, 28) + timedelta(days=days))] for days in range(0, 6)]
    assert orders[0] == ["a", "b"] and all(order == ["b", "a"] for order in orders[1:]), "one change, on the day a turned seven days old"


def test_a_reference_with_no_date_is_in_the_oldest_window():
    records = [public("dated", 2, acceptedAt="2026-10-20T00:00:00.000Z"), {"key": "undated", "rank": 1}]
    assert [record["key"] for record in order_in_buckets(records, "week", AS_OF)] == ["dated", "undated"]


def test_a_missing_or_bad_confidence_in_a_public_record_is_none_and_the_build_orders_it_as_unscored():
    from papyrus_content.home_page.ordering import confidence_of

    assert confidence_of({"confidence": None}) is None and confidence_of({}) is None and confidence_of({"confidence": True}) is None
    assert confidence_of({"confidence": 0.0}) == 0.0 and confidence_of({"confidence": 0.5}) == 0.5
    records = [{"key": "none", "arrivedAt": "2026-10-09T00:00:00.000Z"}, {"key": "half", "confidence": 0.5, "arrivedAt": "2026-10-01T00:00:00.000Z"}]
    assert [record["key"] for record in order_public_records(records)] == ["half", "none"]
