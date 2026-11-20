"""The time-bucketed quality ranking (``quality_ranking.py``, ``docs/quality-ranking.md``): the shared order, the rolling windows and their properties."""

import itertools
import random
from datetime import date, timedelta

import pytest

from papyrus_content.quality_ranking import in_windows, rank, rank_in_buckets, rolling_age, valid_stars


def reference(key, stars=None, confidence=0.5, arrived="2026-10-10T00:00:00.000Z", accepted=None):
    return {"key": key, "stars": stars, "confidence": confidence, "arrivedAt": arrived, "acceptedAt": accepted}


def shared(items):
    return [item["key"] for item in rank(items, stars=lambda i: i["stars"], confidence=lambda i: i["confidence"], newest=lambda i: i["arrivedAt"], key=lambda i: i["key"])]




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



def test_rank_in_buckets_ranks_stories_inside_a_bucket_and_keeps_every_story():
    stories = [("a", "2026-02-08", None), ("b", "2026-02-07", 5), ("c", "2026-02-06", 1), ("d", "2026-01-30", 5), ("e", "2026-02-05", 3), ("f", None, 4)]
    ranked = rank_in_buckets(stories, stars=lambda story: story[2], moment=lambda story: story[1], bucket="week", as_of=date(2026, 2, 8))
    assert [story[0] for story in ranked] == ["b", "e", "a", "c", "d", "f"]
    assert sorted(story[0] for story in ranked) == sorted(story[0] for story in stories)


def test_rank_in_buckets_without_any_stars_is_the_list_it_was_given():
    stories = [("a", "2026-02-08"), ("b", "2026-02-07"), ("c", "2026-01-30"), ("d", "2026-01-20")]
    assert rank_in_buckets(stories, stars=lambda story: None, moment=lambda story: story[1], bucket="week", as_of=date(2026, 2, 8)) == stories


def test_a_reference_with_no_confidence_ranks_below_every_scored_one_and_never_ties_with_a_real_half():
    """Ryan, 2026-11-05: no confidence is not 0.5. An accepted Reference the Cyclotron never scored is unrated and unscored: after the scored ones, before a low rating."""
    items = [reference("unscored", None, None, "2026-10-20T00:00:00.000Z"), reference("half", None, 0.5, "2026-10-01T00:00:00.000Z"), reference("zero", None, 0.0, "2026-10-01T00:00:00.000Z"),
             reference("low", 2, None), reference("high", 4, None)]
    assert shared(items) == ["high", "half", "zero", "unscored", "low"], "newer does not lift it over a scored one, not even a confident reject"


def test_unscored_references_go_newest_first_then_by_key():
    items = [reference("b", None, None, "2026-10-02T00:00:00.000Z"), reference("a", None, None, "2026-10-02T00:00:00.000Z"), reference("c", None, None, "2026-10-03T00:00:00.000Z")]
    assert shared(items) == ["c", "a", "b"]




def test_without_tie_accessors_equal_items_keep_the_order_they_came_in():
    items = [("c", None), ("a", None), ("b", None), ("d", 4)]
    assert [item[0] for item in rank(items, stars=lambda item: item[1])] == ["d", "c", "a", "b"]


@pytest.mark.parametrize(
    ("moment", "bucket", "expected"),
    [
        ("2026-02-08", "day", 0), ("2026-02-07", "day", 1), ("2026-02-08T23:30:00-05:00", "day", 0),   # read in UTC: 2026-02-09, after as_of, so window 0
        ("2026-02-02", "week", 0), ("2026-02-01", "week", 1), ("2026-01-26", "week", 1), ("2026-01-25", "week", 2),
        ("2026-02-20", "week", 0),   # after as_of: the newest window
        ("", "week", 2**31), (None, "day", 2**31), ("not a date", "week", 2**31),
    ],
)
def test_a_window_counts_whole_bucket_lengths_back_from_the_as_of_day_in_utc(moment, bucket, expected):
    assert rolling_age(moment, bucket, date(2026, 2, 8)) == expected


def test_a_week_is_the_last_seven_days_and_not_the_calendar_week():
    as_of = date(2026, 10, 28)   # a Wednesday: the 25th (Sunday) and the 26th (Monday) are both in the last seven days
    assert rolling_age("2026-10-25", "week", as_of) == rolling_age("2026-10-26", "week", as_of) == 0


# ------------------------------------------------------------------ properties, over many seeded random inputs

STARS = [None, None, 1, 2, 3, 4, 5]
CONFIDENCE = [None, 0.0, 0.2, 0.5, 0.9]


def random_items(seed, size=30):
    rng = random.Random(seed)
    return [
        {"key": f"k{n:02d}", "stars": rng.choice(STARS), "confidence": rng.choice(CONFIDENCE), "arrived": f"2026-10-{rng.randint(1, 28):02d}T00:00:00.000Z", "moment": f"2026-10-{rng.randint(1, 28):02d}" if rng.random() > 0.1 else None}
        for n in range(size)
    ]


def ranked(items, as_of=date(2026, 10, 29), bucket="week"):
    return rank_in_buckets(items, stars=lambda i: i["stars"], confidence=lambda i: i["confidence"], newest=lambda i: i["arrived"], key=lambda i: i["key"], moment=lambda i: i["moment"], bucket=bucket, as_of=as_of)


@pytest.mark.parametrize("bucket", ["day", "week"])
@pytest.mark.parametrize("seed", range(12))
def test_nothing_is_dropped_and_nothing_is_added(seed, bucket):
    items = random_items(seed)
    assert sorted(item["key"] for item in ranked(items, bucket=bucket)) == sorted(item["key"] for item in items)


@pytest.mark.parametrize("seed", range(12))
def test_the_order_is_deterministic_for_a_given_day_and_does_not_depend_on_the_input_order(seed):
    items = random_items(seed)
    expected = [item["key"] for item in ranked(items)]
    shuffled = items[:]
    random.Random(seed + 100).shuffle(shuffled)
    assert [item["key"] for item in ranked(shuffled)] == expected
    assert [item["key"] for item in ranked(items)] == expected


@pytest.mark.parametrize("seed", range(12))
def test_the_order_is_stable_under_subsetting(seed):
    items = random_items(seed)
    rng = random.Random(seed + 200)
    subset = [item for item in items if rng.random() > 0.4]
    whole = [item["key"] for item in ranked(items) if item in subset]
    assert [item["key"] for item in ranked(subset)] == whole


@pytest.mark.parametrize("seed", range(12))
def test_a_rating_never_changes_the_window_an_item_is_in(seed):
    items = random_items(seed)
    as_of = date(2026, 10, 29)
    windows = {item["key"]: rolling_age(item["moment"], "week", as_of) for item in items}
    rerated = [{**item, "stars": random.Random(seed).choice(STARS)} for item in items]
    assert windows == {item["key"]: rolling_age(item["moment"], "week", as_of) for item in rerated}
    ages = [rolling_age(item["moment"], "week", as_of) for item in ranked(rerated)]
    assert ages == sorted(ages), "the newest window first, whatever the ratings"


@pytest.mark.parametrize("seed", range(6))
def test_time_alone_moves_an_item_to_an_older_window_and_the_order_changes_only_on_such_a_day(seed):
    items = random_items(seed)
    orders = [[item["key"] for item in ranked(items, as_of=date(2026, 10, 29) + timedelta(days=days))] for days in range(0, 16)]
    changes = [days for days in range(1, 16) if orders[days] != orders[days - 1]]
    crossings = {days for days in range(1, 16) if any(rolling_age(item["moment"], "week", date(2026, 10, 29) + timedelta(days=days)) != rolling_age(item["moment"], "week", date(2026, 10, 29) + timedelta(days=days - 1)) for item in items)}
    assert set(changes) <= crossings


def test_in_windows_keeps_the_order_it_is_given_inside_a_window():
    items = [("late", "2026-02-08"), ("early", "2026-02-02"), ("older", "2026-01-30")]
    assert [item[0] for item in in_windows(items, moment=lambda item: item[1], bucket="week", as_of=date(2026, 2, 8))] == ["late", "early", "older"]
