"""Published Stories rank by recency bucket and stars (features_backend/standard-story-star-ranking.feature)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.engine import project_all  # noqa: E402
from papyrus_content.projection.standard.config import standard_settings_from_mapping  # noqa: E402
from papyrus_content.projection.story_stars import MemoryStarStore  # noqa: E402
from papyrus_content.projection.story_stars_task import run_story_stars_task  # noqa: E402
from procedures.newsroom.tests import test_story_star_ranking as ranking  # noqa: E402
from procedures.newsroom.tests.standard_frontend_content_support import cards, cms_site, featured, item  # noqa: E402

PRIVATE_WORDS = ("starRating", "starRatedAt", "starRatedBy", "data-stars", "story-stars", "an editor")


def names(text: str) -> list[str]:
    return re.findall(r'"([^"]+)"', text)


def build(context, settings=None) -> None:
    context.site = cms_site(settings or ranking.SETTINGS, ranking.stories(), ranking.FILES)
    context.site.context.source.star_store = MemoryStarStore()
    context.site.projector.clock = lambda: ranking.AS_OF
    context.add_cleanup(context.site.cleanup)
    context.before = dict(context.site.tree)


def listing(context, name: str) -> list[str]:
    return cards(context.site.text("posts/index.html" if name == "posts" else f"{name}/index.html"))


def project_again(context) -> None:
    report = project_all(context.site.context)
    assert report.ok, report.errors


@given("a site of seven Stories this week, one five-star candidate on Monday of that week, and two Stories from the week before")
def the_site(context) -> None:
    build(context)


@given("the editors rated {ratings}")
def editors_rated(context, ratings: str) -> None:
    # "A 5 stars and B, C and D 2 stars" or "A 5, B 4, C 3": a count rates the quoted names that came since the previous count.
    waiting: list[str] = []
    for name, number in re.findall(r'"([^"]+)"|\b([1-5])\b', ratings):
        if name:
            waiting.append(name)
            continue
        assert waiting, ratings
        for slug in waiting:
            ranking.rate(context.site, slug, int(number))
        waiting = []
    assert not waiting, ratings


@given('a site whose listings.bucket is none and the editors rated "{slug}" {count:d} stars')
def none_site(context, slug: str, count: int) -> None:
    build(context, {**ranking.SETTINGS, "listings": {"featuredCount": 1, "pageSize": 20, "bucket": "none"}})
    ranking.rate(context.site, slug, count)


@given("the site has been projected")
def projected(context) -> None:
    project_again(context)
    context.site.writer.operations.clear()


@given("the site is projected again")
@when("the site is projected again")
def projected_again(context) -> None:
    project_again(context)


@when("the site is projected two days later")
def projected_two_days_later(context) -> None:
    context.site.projector.clock = lambda: ranking.date(2026, 2, 10)
    project_again(context)


@when("two days pass with no write")
def two_days_pass(context) -> None:
    context.site.projector.clock = lambda: ranking.date(2026, 2, 10)


@when("the stale-listings pass runs")
def stale_pass(context) -> None:
    from papyrus_content.projection.engine import project_stale_listings

    context.report = project_stale_listings(context.site.context)
    assert context.report.ok, context.report.errors


@then("a second stale-listings pass rewrites nothing")
def second_stale_pass(context) -> None:
    from papyrus_content.projection.engine import project_stale_listings

    assert not project_stale_listings(context.site.context).written


@then('the "{name}" listing still starts with {slug}')
def listing_still_starts(context, name: str, slug: str) -> None:
    assert listing(context, name)[0] == slug, listing(context, name)


@then("every page is byte for byte what it was")
def unchanged(context) -> None:
    assert context.site.tree == context.before


@then('the "{name}" listing is {slugs}')
def listing_is(context, name: str, slugs: str) -> None:
    expected = [part.strip() for part in re.split(r",| and ", slugs) if part.strip()]
    assert listing(context, name) == expected, listing(context, name)


@then('the "{name}" listing starts with {slug}')
def listing_starts(context, name: str, slug: str) -> None:
    assert listing(context, name)[0] == slug, listing(context, name)


@then('the featured slot of the "{name}" listing page is {slug}')
def featured_slot(context, name: str, slug: str) -> None:
    assert featured(context.site.text("posts/index.html")) == [slug]


@then('the first Story of the "{name}" listing page is {slug}')
def first_story(context, name: str, slug: str) -> None:
    assert listing(context, name)[0] == slug, listing(context, name)


@then("the first Story on the home page is {slug}")
def first_on_home(context, slug: str) -> None:
    assert cards(context.site.text("index.html"))[0] == slug


@then('the feed lists "{first}" before "{second}"')
def feed_order(context, first: str, second: str) -> None:
    feed = context.site.text("feed.xml")
    assert feed.index(f"/{first}") < feed.index(f"/{second}")


@then('every Story is still on the "{name}" listing page')
def everything_listed(context, name: str) -> None:
    assert sorted(listing(context, name)) == sorted(ranking.newest_first())


@then('a listings.bucket of "{bucket}" is refused saying "{message}"')
def bad_listing_bucket(context, bucket: str, message: str) -> None:
    try:
        standard_settings_from_mapping({"site": {"name": "Example"}, "listings": {"bucket": bucket}})
    except ValueError as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError("the bad bucket was accepted")


@then('an include with bucket "{bucket}" is refused saying "{message}"')
def bad_include_bucket(context, bucket: str, message: str) -> None:
    try:
        cms_site(
            ranking.settings(pages=[{"id": "p", "path": "p", "title": "P", "source": "p.md"}]),
            [item("x")],
            {"p.md": f'{ranking.BAND}::include{{kind="listing" bucket="{bucket}"}}\n'},
        )
    except ValueError as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError("the bad bucket was accepted")


@then("no file the site holds mentions a star rating, who gave one, or the private rating store")
def nothing_private_public(context) -> None:
    for key, body in context.site.tree.items():
        text = body.decode("utf-8", "ignore")
        for word in PRIVATE_WORDS:
            assert word not in text, f"{key} mentions {word}"


@when('an editor rates "{slug}" {count:d} stars and the story-stars task runs')
def rate_and_run(context, slug: str, count: int) -> None:
    ranking.rate(context.site, slug, count)
    context.site.writer.operations.clear()
    context.task_id = f"item-posts-{slug}"
    context.result = run_story_stars_task(context.site.context, context.site.client, {"task": "story-stars", "itemId": context.task_id})


@when('the story-stars task runs again for "{slug}"')
def run_again(context, slug: str) -> None:
    context.result = run_story_stars_task(context.site.context, context.site.client, {"task": "story-stars", "itemId": f"item-posts-{slug}"})


@when('an editor clears the rating of "{slug}" and the story-stars task runs')
def clear_and_run(context, slug: str) -> None:
    ranking.rate(context.site, slug, None)
    context.result = run_story_stars_task(context.site.context, context.site.client, {"task": "story-stars", "itemId": f"item-posts-{slug}"})


@when("an editor rates an unpublished Story {count:d} stars and the story-stars task runs")
def rate_unpublished(context, count: int) -> None:
    context.site.client.tables["Item"]["draft-v1"] = {"id": "draft-v1", "lineageId": "draft", "type": "article", "versionState": "current", "starRating": count}
    context.result = run_story_stars_task(context.site.context, context.site.client, {"task": "story-stars", "itemId": "draft-v1"})


@then("the task records the rating and rewrites the pages {pages}")
def rewrote_pages(context, pages: str) -> None:
    assert context.result["recorded"] is True and context.result["published"] is True, context.result
    assert set(context.result["rewritten"]) >= set(names(pages)), context.result
    assert {key for key in context.result["rewritten"] if key.endswith(".html")} == set(names(pages)), context.result


@then("the pages {pages} were not rewritten")
def not_rewritten(context, pages: str) -> None:
    assert not set(names(pages)) & set(context.result["rewritten"]), context.result


@then("no Story page was rendered again")
def no_story_pages(context) -> None:
    assert not [key for key in context.result["rewritten"] if key.startswith(("posts/three", "posts/eight", "posts/star"))], context.result


@then("the second run reports that nothing was recorded and no page was rewritten")
def second_run_nothing(context) -> None:
    assert context.result == {"ok": True, "recorded": False, "pagesRewritten": 0}, context.result


@then("the task records the rating and rewrites no page")
def records_only(context) -> None:
    assert context.result["recorded"] is True and context.result["pagesRewritten"] == 0, context.result
    assert context.site.context.source.star_store.stars["draft"] == 4


@then("the store holds the rating once and a second projection reads it without reading the Items again")
def store_reads_once(context) -> None:
    store = context.site.context.source.star_store
    assert store.stars["item-posts-three"] == 5
    writes, calls = store.writes, len(context.site.client.calls)
    project_again(context)
    reads_of_items = [call for call in context.site.client.calls[calls:] if call[:2] == ("list_by_index", "itemsByLineageAndVersion")]
    assert store.writes == writes and not reads_of_items, (store.writes, writes, reads_of_items)


class _LimitedTable:
    def __init__(self):
        self.stars, self.largest = {}, 0

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None):
        self.largest = max(self.largest, len(UpdateExpression.encode()))
        assert len(UpdateExpression.encode()) <= 4096
        if UpdateExpression.startswith("SET stars = if_not_exists"):
            return
        for assignment in UpdateExpression.removeprefix("SET ").split(", "):
            target, value = assignment.split(" = ")
            self.stars[ExpressionAttributeNames[target.removeprefix("stars.")]] = ExpressionAttributeValues[value]


@given("a rating store that refuses an update over DynamoDB's size limit")
def step_limited_store(context):
    from papyrus_content.projection.story_stars import DynamoStarStore

    context.limited_table = _LimitedTable()
    context.limited_store = DynamoStarStore(context.limited_table, "abcd1234")


@when("a thousand Stories nobody has seen before are remembered at once")
def step_remember_thousand(context):
    context.limited_store.record({f"lineage-{number}": number % 6 for number in range(1000)})


@then("every rating is remembered and no single write went over the limit")
def step_all_remembered(context):
    assert len(context.limited_table.stars) == 1000 and 0 < context.limited_table.largest <= 4096


@given("a rating store that refuses every write")
def step_refusing_store(context):
    class Refusing(MemoryStarStore):
        def record(self, entries):
            raise RuntimeError("the table refused")

    context.refusing_store = Refusing()


@when("a Story rated four stars is looked up for the first time")
def step_look_up(context):
    from papyrus_content.projection.story_stars import known_stars

    context.found_stars = known_stars(context.refusing_store, ["rated"], lambda lineage: 4)


@then("the listing still has its four stars, and the next render reads it again")
def step_still_stars(context):
    assert context.found_stars == {"rated": 4} and context.refusing_store.load() == {}



@given("a site whose hook page lists the Stories through page.ranked")
def hook_site(context) -> None:
    context.site = ranking.hooked_site()
    context.add_cleanup(context.site.cleanup)
    context.before = dict(context.site.tree)


@then("the hook page lists the Stories newest first")
def hook_page_newest_first(context) -> None:
    assert ranking.hooked(context.site) == ranking.newest_first(), ranking.hooked(context.site)


@then("the hook page starts with {slugs}")
def hook_page_starts(context, slugs: str) -> None:
    expected = [part.strip() for part in slugs.split(",")]
    assert ranking.hooked(context.site)[: len(expected)] == expected, ranking.hooked(context.site)


@then('the page "{page}" was rewritten')
def page_rewritten(context, page: str) -> None:
    assert page in context.result["rewritten"], context.result
