"""The three-star floor (features_backend/three-star-floor.feature): Stories through the projector, References through the home-page snapshot, the roundup draft."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from features_backend.steps.home_page_snapshot_steps import FixtureClient  # noqa: E402
from papyrus_content.home_page.export import collect_references  # noqa: E402
from papyrus_content.home_page.settings import HomePageSettings  # noqa: E402
from papyrus_content.newsletter.issues_test import DAY, START, rig_context  # noqa: E402
from papyrus_content.projection.story_stars import MemoryStarStore  # noqa: E402
from papyrus_content.projection.story_stars_task import run_story_stars_task  # noqa: E402
from procedures.newsroom.tests import test_story_star_ranking as ranking  # noqa: E402
from procedures.newsroom.tests.standard_frontend_content_support import cards, cms_site  # noqa: E402

SLUGS = ("eight", "seven", "six", "five", "four", "three")
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def build_site(context, quality: dict | None, ratings: dict[str, int]) -> None:
    settings = {**ranking.SETTINGS, "publicData": {"latestCount": 20}, **({"quality": quality} if quality is not None else {})}
    context.site = cms_site(settings, ranking.stories(), ranking.FILES)
    context.site.context.source.star_store = MemoryStarStore()
    context.site.projector.clock = lambda: ranking.AS_OF
    context.add_cleanup(context.site.cleanup)
    for slug, count in ratings.items():
        ranking.rate(context.site, slug, count)
    report = ranking.reproject(context.site)
    assert report.ok, report.errors


def rerate(context, slug: str, count: int) -> None:
    ranking.rate(context.site, slug, count)
    run_story_stars_task(context.site.context, context.site.client, {"task": "story-stars", "itemId": f"item-posts-{slug}"})


def feed(site) -> list[str]:
    return re.findall(r"<link>[^<]*/posts/([^/<.]+)", site.text("feed.xml"))


def sitemap(site) -> list[str]:
    return re.findall(r"<loc>[^<]*/posts/([^/<.]+)", site.text("sitemap.xml"))


def listing(site) -> list[str]:
    return cards(site.text("latest/index.html"))


def public_data(site) -> str:
    return "".join(body.decode("utf-8", "ignore") for key, body in site.tree.items() if key.endswith(".json"))


def assert_surfaces(context, expected: list[str]) -> None:
    site = context.site
    assert listing(site) == expected, listing(site)
    assert cards(site.text("index.html")) == expected
    assert feed(site) == expected, feed(site)
    assert sitemap(site) == expected, sitemap(site)
    text = public_data(site)
    for slug in SLUGS:
        assert (slug.upper() in text) == (slug in expected), f"public data and {slug}"


@given("a site with the quality floor on and a Story rated four stars and a Story rated three stars")
def two_rated(context) -> None:
    build_site(context, {}, {"eight": 4, "seven": 3})


@given("a site with the quality floor on and a Story nobody rated")
def one_unrated(context) -> None:
    build_site(context, {}, {})


@given("a site with the quality floor on and Stories rated one, two and three stars")
def low_ratings(context) -> None:
    build_site(context, {}, {"eight": 1, "seven": 2, "six": 3})


@given("a site with no quality setting and Stories rated and unrated")
def no_setting(context) -> None:
    build_site(context, None, {"eight": 4, "seven": 1})


@given("a site whose quality floor is four stars and Stories rated three and four stars")
def raised(context) -> None:
    build_site(context, {"floorStars": 4}, {"eight": 3, "seven": 4})


@given("a site with the quality floor on and no Story rated")
def none_rated(context) -> None:
    build_site(context, {}, {})


@given("a site with the quality floor on and a Story rated four stars")
def one_rated(context) -> None:
    build_site(context, {}, {"eight": 4})
    assert_surfaces(context, ["eight"])


@then("both Stories are on the home page, the listing page, the feed, the sitemap and the public data")
def both(context) -> None:
    assert_surfaces(context, ["eight", "seven"])


@then("the Story is not on the home page, the listing page, the feed, the sitemap or the public data")
def not_anywhere(context) -> None:
    assert_surfaces(context, [])


@then("the page of the Story is still served")
def page_served(context) -> None:
    assert any(key.startswith("posts/eight") for key in context.site.tree), sorted(context.site.tree)


@then("only the three-star Story is listed anywhere")
def only_three(context) -> None:
    assert_surfaces(context, ["six"])


@then("every Story is listed everywhere, rated or not")
def all_listed(context) -> None:
    assert sorted(listing(context.site)) == sorted(ranking.newest_first())
    assert len(feed(context.site)) == len(ranking.newest_first())


@then("only the four-star Story is listed anywhere")
def only_four(context) -> None:
    assert_surfaces(context, ["seven"])


@then("the listing page shows no Story and the feed and the sitemap list none")
def nothing(context) -> None:
    assert_surfaces(context, [])


@when("an editor rates it two stars")
def rated_down(context) -> None:
    rerate(context, "eight", 2)


@then("the listings, the feed and the sitemap no longer have it")
def gone(context) -> None:
    assert_surfaces(context, [])


@when("an editor rates it three stars")
def rated_up(context) -> None:
    rerate(context, "eight", 3)


@then("the listings, the feed and the sitemap have it again")
def back(context) -> None:
    assert_surfaces(context, ["eight"])


def reference_client(ratings: dict[str, int]) -> FixtureClient:
    client = FixtureClient()
    for title, stars in ratings.items():
        row = next(row for row in client.rows() if row["title"].startswith(title))
        row.update({"starRating": stars, "starRatedAt": "2026-11-12T09:00:00.000Z", "starRatedBy": "an editor"})
    return client


def snapshot_titles(context) -> list[str]:
    records = collect_references(context.client, context.client.corpus_id, HomePageSettings(floor_stars=context.floor))
    context.records = records
    return sorted(record["title"] for record in records)


@given("a site with the quality floor on and a pending Reference the Cyclotron is 95 percent sure about and an accepted Reference nobody rated")
def predicted_and_unrated(context) -> None:
    context.client, context.floor = FixtureClient(), 3
    pending = next(row for row in context.client.rows() if row["title"].startswith("Pending mid"))
    pending["predictedAcceptProbability"] = 0.95


@then("neither Reference is in the public snapshot and no recommended Reference is")
def no_prediction_public(context) -> None:
    titles = snapshot_titles(context)
    assert "Pending mid" not in titles and "Accepted two" not in titles, titles
    assert titles == [], titles
    assert all(record["status"] != "recommended" for record in context.records)


@given("a site with the quality floor on and accepted References rated one, two, three and five stars")
def rated_refs(context) -> None:
    context.client, context.floor = reference_client({"Accepted one": 5, "Accepted two": 3, "Accepted three": 2, "Accepted four": 1}), 3


@then("the public snapshot holds the three-star and the five-star Reference only")
def three_and_five(context) -> None:
    assert snapshot_titles(context) == ["Accepted one", "Accepted two"], snapshot_titles(context)


@given("a site whose quality floor is four stars and accepted References rated three and four stars")
def raised_refs(context) -> None:
    context.client, context.floor = reference_client({"Accepted one": 4, "Accepted two": 3}), 4


@then("the public snapshot holds the four-star Reference only")
def four_only(context) -> None:
    assert snapshot_titles(context) == ["Accepted one"], snapshot_titles(context)


def week(rig, ratings: list[int | None]) -> None:
    for number, stars in enumerate(ratings):
        rig.content.publish(slug=f"story-{number}", title=f"Story {number}", section="articles", at=START - DAY, stars=stars)


def draft_body(rig, assembled: dict) -> str:
    return rig.content.items[rig.service.issues.get(assembled["issueId"])["itemId"]]["bodyMarkus"]


@given("a site with the quality floor on and a week of five published Stories, two rated three stars or more")
def week_of_five(context) -> None:
    import dataclasses

    context.rig_manager = rig_context()
    context.rig = context.rig_manager.__enter__()
    context.add_cleanup(lambda: context.rig_manager.__exit__(None, None, None))
    context.rig.service.settings = dataclasses.replace(context.rig.settings, floor_stars=3)
    week(context.rig, [4, 3, 2, 1, None])


@given("a site with the quality floor on and a week of published Stories nobody rated")
def week_unrated(context) -> None:
    import dataclasses

    context.rig_manager = rig_context()
    context.rig = context.rig_manager.__enter__()
    context.add_cleanup(lambda: context.rig_manager.__exit__(None, None, None))
    context.rig.service.settings = dataclasses.replace(context.rig.settings, floor_stars=3)
    week(context.rig, [None, None, None])


@when("the roundup draft is assembled")
def assemble_draft(context) -> None:
    context.assembled = context.rig.task("assemble-roundup", listId="weekly")
    assert context.assembled["status"] == "created", context.assembled


@when("the roundup is assembled on its schedule")
def assemble_scheduled(context) -> None:
    context.assembled = context.rig.task("assemble-roundup", listId="weekly")


@then("the draft names the two rated Stories as the issue")
def draft_issue(context) -> None:
    kept = draft_body(context.rig, context.assembled).split("## Left out")[0]
    assert [f"[Story {number}]" in kept for number in range(5)] == [True, True, False, False, False]


@then("the draft shows the other three under a Left out heading as not reaching the floor")
def draft_left_out(context) -> None:
    body = draft_body(context.rig, context.assembled)
    left = body.split("## Left out")[1]
    assert [f"[Story {number}]" in left for number in range(5)] == [False, False, True, True, True]
    assert "floor of 3 stars" in left


@then("no draft is made")
def no_draft(context) -> None:
    assert context.assembled["status"] == "empty", context.assembled


@given("a quality floor of three stars")
def aggregate_floor(context) -> None:
    context.floor = 3


@then("the floor reads the rating only through the effective rating function the quality code already uses")
def aggregate_seam(context) -> None:
    from unittest import mock

    from papyrus_content.home_page.export import is_chosen

    row = {"id": "a", "lineageId": "a", "curationStatus": "accepted"}
    settings = HomePageSettings(floor_stars=context.floor)
    assert not is_chosen(row, None, settings)
    with mock.patch("papyrus_content.item_stars.aggregate_rating", return_value={"stars": 4, "source": "votes", "votes": 5}):
        assert is_chosen(row, None, settings), "an aggregate of votes reaches the floor with no other change"
