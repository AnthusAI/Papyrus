"""The shared order, its rank, and the time buckets (``home_page/ordering.py``)."""

import itertools
import random
from datetime import date, timedelta

import pytest

from papyrus_content.home_page.ordering import (
    bucket_of,
    bucket_moment,
    has_ranks,
    order_in_buckets,
    order_public_records,
    ordered,
    rank_in_buckets,
    rank_records,
    valid_stars,
)


def reference(key, stars=None, confidence=0.5, arrived="2026-10-10T00:00:00.000Z", accepted=None):
    return {"key": key, "stars": stars, "confidence": confidence, "arrivedAt": arrived, "acceptedAt": accepted}


def shared(items):
    return [item["key"] for item in ordered(items, stars=lambda i: i["stars"], confidence=lambda i: i["confidence"], newest=lambda i: i["arrivedAt"], key=lambda i: i["key"])]


def test_high_stars_then_unrated_by_confidence_then_low_stars():
    items = [
        reference("low1", 1, 0.99), reference("low2", 2, 0.99), reference("unrated-high", None, 0.9), reference("unrated-low", None, 0.2),
        reference("s3", 3, 0.1), reference("s4", 4, 0.1), reference("s5", 5, 0.1),
    ]
    assert shared(items) == ["s5", "s4", "s3", "unrated-high", "unrated-low", "low2", "low1"]


def test_a_low_rating_sinks_a_reference_the_cyclotron_is_sure_of_and_a_high_one_lifts_a_doubtful_one():
    assert shared([reference("sure", 2, 1.0), reference("meh", None, 0.5)]) == ["meh", "sure"]
    assert shared([reference("doubtful", 3, 0.0), reference("sure", None, 1.0)]) == ["doubtful", "sure"]


def test_equal_standing_goes_to_the_newest_arrival_then_the_key():
    items = [
        reference("b", 4, arrived="2026-10-02T00:00:00.000Z"), reference("a", 4, arrived="2026-10-02T00:00:00.000Z"),
        reference("c", 4, arrived="2026-10-03T00:00:00.000Z"), reference("d", None, 0.5, "2026-10-01T00:00:00.000Z"), reference("e", None, 0.5, "2026-10-04T00:00:00.000Z"),
    ]
    assert shared(items) == ["c", "a", "b", "e", "d"]


def test_the_order_does_not_depend_on_the_input_order():
    items = [reference(f"k{n}", stars, confidence, f"2026-10-{n + 1:02d}T00:00:00.000Z") for n, (stars, confidence) in enumerate(itertools.product([None, 1, 2, 3, 4, 5], [0.2, 0.8]))]
    expected = shared(items)
    for seed in range(5):
        shuffled = items[:]
        random.Random(seed).shuffle(shuffled)
        assert shared(shuffled) == expected


@pytest.mark.parametrize(("value", "expected"), [(1, 1), (5, 5), (3.0, 3), (0, None), (6, None), (None, None), (True, None), ("4", None), (2.5, None)])
def test_valid_stars_reads_only_a_whole_number_from_one_to_five(value, expected):
    assert valid_stars(value) == expected


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


# ------------------------------------------------------------------ Stories use the same buckets and the same order


@pytest.mark.parametrize(
    ("moment", "bucket", "expected"),
    [
        ("2026-02-08", "week", "2026-02-02"),          # a Sunday belongs to the week that began on the Monday before
        ("2026-02-09", "week", "2026-02-09"),
        ("2026-02-08", "day", "2026-02-08"),
        ("2026-02-08T23:30:00-05:00", "day", "2026-02-09"),   # UTC, whatever the offset says
        ("", "week", ""),
        (None, "day", ""),
        ("not a date", "week", ""),
    ],
)
def test_bucket_of_takes_a_date_or_a_timestamp_and_buckets_it_in_utc(moment, bucket, expected):
    assert bucket_of(moment, bucket) == expected


def test_rank_in_buckets_ranks_stories_inside_a_bucket_and_keeps_every_story():
    stories = [("a", "2026-02-08", None), ("b", "2026-02-07", 5), ("c", "2026-02-06", 1), ("d", "2026-01-30", 5), ("e", "2026-02-05", 3), ("f", None, 4)]
    ranked = rank_in_buckets(stories, stars=lambda story: story[2], moment=lambda story: story[1], bucket="week")
    assert [story[0] for story in ranked] == ["b", "e", "a", "c", "d", "f"]
    assert sorted(story[0] for story in ranked) == sorted(story[0] for story in stories)


def test_rank_in_buckets_without_any_stars_is_the_list_it_was_given():
    stories = [("a", "2026-02-08"), ("b", "2026-02-07"), ("c", "2026-01-30"), ("d", "2026-01-20")]
    assert rank_in_buckets(stories, stars=lambda story: None, moment=lambda story: story[1], bucket="week") == stories


def test_a_reference_with_no_confidence_ranks_below_every_scored_one_and_never_ties_with_a_real_half():
    """Ryan, 2026-11-05: no confidence is not 0.5. An accepted Reference the Cyclotron never scored is unrated and unscored: after the scored ones, before a low rating."""
    items = [reference("unscored", None, None, "2026-10-20T00:00:00.000Z"), reference("half", None, 0.5, "2026-10-01T00:00:00.000Z"), reference("zero", None, 0.0, "2026-10-01T00:00:00.000Z"),
             reference("low", 2, None), reference("high", 4, None)]
    assert shared(items) == ["high", "half", "zero", "unscored", "low"], "newer does not lift it over a scored one, not even a confident reject"


def test_unscored_references_go_newest_first_then_by_key():
    items = [reference("b", None, None, "2026-10-02T00:00:00.000Z"), reference("a", None, None, "2026-10-02T00:00:00.000Z"), reference("c", None, None, "2026-10-03T00:00:00.000Z")]
    assert shared(items) == ["c", "a", "b"]


def test_a_missing_or_bad_confidence_in_a_public_record_is_none_and_the_build_orders_it_as_unscored():
    from papyrus_content.home_page.ordering import confidence_of

    assert confidence_of({"confidence": None}) is None and confidence_of({}) is None and confidence_of({"confidence": True}) is None
    assert confidence_of({"confidence": 0.0}) == 0.0 and confidence_of({"confidence": 0.5}) == 0.5
    records = [{"key": "none", "arrivedAt": "2026-10-09T00:00:00.000Z"}, {"key": "half", "confidence": 0.5, "arrivedAt": "2026-10-01T00:00:00.000Z"}]
    assert [record["key"] for record in order_public_records(records)] == ["half", "none"]
