"""The quality ranking module (features_backend/quality-ranking.feature)."""

from __future__ import annotations

import ast
import sys
from datetime import date, timedelta
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import quality_ranking  # noqa: E402
from papyrus_content.home_page import ordering  # noqa: E402
from papyrus_content.projection.standard import home_page_blocks, story_order  # noqa: E402

AS_OF = date(2026, 10, 29)


def item(key, *, stars=None, confidence=None, moment="2026-10-28", arrived="2026-10-01T00:00:00.000Z"):
    return {"key": key, "stars": stars, "confidence": confidence, "moment": moment, "arrived": arrived}


def ranked(items, bucket="week", as_of=AS_OF):
    return quality_ranking.rank_in_buckets(
        items, stars=lambda i: i["stars"], confidence=lambda i: i["confidence"], newest=lambda i: i["arrived"], key=lambda i: i["key"], moment=lambda i: i["moment"], bucket=bucket, as_of=as_of
    )


def keys(items):
    return [i["key"] for i in items]


@given("Stories published in three different weeks")
def three_weeks(context):
    context.items = [item("old", moment="2026-10-10"), item("new-a", moment="2026-10-28"), item("mid", moment="2026-10-18"), item("new-b", moment="2026-10-24", stars=5)]


@when("they are ranked with week windows")
def rank_weeks(context):
    context.ranked = ranked(context.items)


@then("every Story of the newest week precedes every Story of the next")
def newest_first(context):
    assert keys(context.ranked) == ["new-b", "new-a", "mid", "old"], keys(context.ranked)


@given("a four-star Reference with low Cyclotron confidence and an unrated one with high confidence in the same window")
def four_vs_confident(context):
    context.items = [item("confident", confidence=0.99), item("four-star", stars=4, confidence=0.01)]


@when("they are ranked")
def rank_now(context):
    context.ranked = ranked(context.items)


@then("the four-star Reference comes first")
def four_first(context):
    assert keys(context.ranked)[0] == "four-star"


@given("an accepted Reference the Cyclotron never scored, and scored unrated ones with confidence 0.5 and 0.0")
def unscored(context):
    context.items = [item("unscored", arrived="2026-10-20T00:00:00.000Z"), item("half", confidence=0.5), item("zero", confidence=0.0)]


@then("the unscored Reference comes after both scored ones")
def unscored_last(context):
    assert keys(context.ranked) == ["half", "zero", "unscored"], keys(context.ranked)


@given("a one-star Reference the Cyclotron likes and an unrated one it does not")
def one_star(context):
    context.items = [item("one-star", stars=1, confidence=0.99), item("unrated", confidence=0.01)]


@then("the unrated Reference comes first")
def unrated_first(context):
    assert keys(context.ranked) == ["unrated", "one-star"]


@given("References dated across three weeks")
def across_weeks(context):
    context.items = [item(f"r{n}", moment=(AS_OF - timedelta(days=days)).isoformat()) for n, days in enumerate([1, 3, 8, 10, 16, 20, 40])]


@when("every Reference is rated and ranked")
def rate_all_and_rank(context):
    context.before = {i["key"]: quality_ranking.rolling_age(i["moment"], "week", AS_OF) for i in context.items}
    context.items = [{**i, "stars": 5 - n % 5} for n, i in enumerate(context.items)]
    context.ranked = ranked(context.items)


@then("each Reference is in the window its date gives and the windows come newest first")
def windows_hold(context):
    assert {i["key"]: quality_ranking.rolling_age(i["moment"], "week", AS_OF) for i in context.ranked} == context.before
    ages = [quality_ranking.rolling_age(i["moment"], "week", AS_OF) for i in context.ranked]
    assert ages == sorted(ages)


@given("a Reference that turns seven days old today")
def turns_seven(context):
    context.items = [item("turning", stars=5, moment=(AS_OF - timedelta(days=7)).isoformat()), item("newer", moment=(AS_OF - timedelta(days=2)).isoformat()), item("older", moment=(AS_OF - timedelta(days=12)).isoformat())]


@when("the ranking is made today and the day before")
def today_and_before(context):
    context.today = keys(ranked(context.items))
    context.yesterday = keys(ranked(context.items, as_of=AS_OF - timedelta(days=1)))


@then("it follows every newer Reference today and precedes the older window the day before")
def crossing(context):
    assert context.today == ["newer", "turning", "older"], context.today
    assert context.yesterday == ["turning", "newer", "older"], context.yesterday


@given("a ranked list of Stories")
def ranked_stories(context):
    context.items = [item(f"s{n}", stars=[None, 4, 2, 5, None, 3][n % 6], moment=(AS_OF - timedelta(days=3 * n)).isoformat(), confidence=[0.2, None, 0.9][n % 3]) for n in range(18)]
    context.whole = ranked(context.items)


@when("a section filter is applied to it")
def filter_section(context):
    context.subset = [i for i in context.items if int(i["key"][1:]) % 3 != 0]
    context.filtered = [i for i in context.whole if i in context.subset]


@then("the filtered list is in the same relative order as the whole list ranked")
def same_relative(context):
    assert keys(ranked(context.subset)) == keys(context.filtered)


@given("a ranked list of Stories and References, rated and unrated and some with no date")
def mixed(context):
    context.items = [item("a", stars=5), item("b"), item("c", stars=1, moment=None), item("d", confidence=0.4, moment="not a date"), item("e", stars=3, moment="2020-01-01")]


@then("every item is still in the ranked list")
def nothing_dropped(context):
    assert sorted(keys(ranked(context.items))) == sorted(keys(context.items))


def defined_functions(module) -> set[str]:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


@then("the Stories, the References, the Worth Watching row and the home page order with the functions of quality_ranking and define no ranking of their own")
def one_implementation(context):
    assert story_order.rank_in_buckets is quality_ranking.rank_in_buckets
    assert ordering.rank is quality_ranking.rank and ordering.in_windows is quality_ranking.in_windows
    assert home_page_blocks.valid_stars is quality_ranking.valid_stars and home_page_blocks.BUCKETS is quality_ranking.BUCKETS
    own = {"rank", "rank_in_buckets", "in_windows", "rolling_age", "valid_stars", "utc_today", "_tier"}
    for module in (story_order, ordering, home_page_blocks):
        assert not own & defined_functions(module), (module.__name__, own & defined_functions(module))
