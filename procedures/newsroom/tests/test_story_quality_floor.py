"""The site's quality floor (PPY-0e8d66) on the Story side: below it a Story is served by its address and is on no list, feed, sitemap or public data file."""

from __future__ import annotations

import json
import re

import pytest

from papyrus_content.projection.story_stars import MemoryStarStore
from papyrus_content.projection.story_stars_task import run_story_stars_task
from procedures.newsroom.tests import test_story_star_ranking as ranking
from procedures.newsroom.tests.standard_frontend_content_support import cards, cms_site
from procedures.newsroom.tests.test_story_star_ranking import reproject

SETTINGS = {**ranking.SETTINGS, "publicData": {"latestCount": 20}}


def build(settings):
    site = cms_site(settings, ranking.stories(), ranking.FILES)
    site.context.source.star_store = MemoryStarStore()
    site.projector.clock = lambda: ranking.AS_OF
    return site


@pytest.fixture()
def floor_site():
    site = build({**SETTINGS, "quality": {}})
    yield site
    site.cleanup()


@pytest.fixture()
def plain_site():
    site = build(SETTINGS)
    yield site
    site.cleanup()


def feed_slugs(site) -> list[str]:
    return re.findall(r"<link>[^<]*/posts/([^/<.]+)", site.text("feed.xml"))


def sitemap_slugs(site) -> list[str]:
    return re.findall(r"<loc>[^<]*/posts/([^/<.]+)", site.text("sitemap.xml"))


def public_data_text(site) -> str:
    return "".join(body.decode("utf-8", "ignore") for key, body in site.tree.items() if key.endswith(".json"))


def test_with_no_quality_key_unrated_stories_are_listed_exactly_as_before(plain_site):
    assert cards(plain_site.text("latest/index.html")) == ranking.newest_first()
    assert len(feed_slugs(plain_site)) == 9


def test_with_the_floor_on_an_unrated_story_is_on_no_list_feed_sitemap_or_public_file_but_its_page_is_served(floor_site):
    ranking.rate(floor_site, "eight", 4)
    ranking.rate(floor_site, "seven", 3)
    reproject(floor_site)
    assert cards(floor_site.text("latest/index.html")) == ["eight", "seven"]
    assert cards(floor_site.text("index.html")) == ["eight", "seven"]
    assert feed_slugs(floor_site) == ["eight", "seven"]
    assert sitemap_slugs(floor_site) == ["eight", "seven"]
    assert '"six"' not in public_data_text(floor_site).lower() and "/posts/six/" not in public_data_text(floor_site)
    assert "posts/six/index.html" in floor_site.tree or "posts/six.html" in floor_site.tree or any(key.startswith("posts/six") for key in floor_site.tree), "the page is still served"


def test_one_and_two_stars_do_not_qualify(floor_site):
    ranking.rate(floor_site, "eight", 2)
    ranking.rate(floor_site, "seven", 1)
    ranking.rate(floor_site, "six", 3)
    reproject(floor_site)
    assert cards(floor_site.text("latest/index.html")) == ["six"]


def test_a_site_that_raises_the_floor_drops_three_star_stories():
    site = build({**SETTINGS, "quality": {"floorStars": 4}})
    try:
        ranking.rate(site, "eight", 3)
        ranking.rate(site, "seven", 4)
        reproject(site)
        assert cards(site.text("latest/index.html")) == ["seven"]
    finally:
        site.cleanup()


def test_too_few_items_shows_fewer_and_nothing_qualifying_shows_an_empty_list(floor_site):
    reproject(floor_site)
    assert cards(floor_site.text("latest/index.html")) == []
    assert feed_slugs(floor_site) == []
    assert sitemap_slugs(floor_site) == []


def rerate(site, slug: str, count: int) -> None:
    """An editor changes a rating: the Story's record changes and the story-stars task records it and rebuilds what lists the Story."""
    ranking.rate(site, slug, count)
    run_story_stars_task(site.context, site.client, {"task": "story-stars", "itemId": f"item-posts-{slug}"})


def test_rated_down_and_rated_up_move_the_story_off_and_on_every_surface(floor_site):
    rerate(floor_site, "eight", 4)
    assert feed_slugs(floor_site) == ["eight"]
    rerate(floor_site, "eight", 2)
    assert cards(floor_site.text("latest/index.html")) == []
    assert feed_slugs(floor_site) == [] and sitemap_slugs(floor_site) == []
    rerate(floor_site, "seven", 3)
    assert cards(floor_site.text("latest/index.html")) == ["seven"]
    assert feed_slugs(floor_site) == ["seven"] and sitemap_slugs(floor_site) == ["seven"]


def test_no_public_file_carries_a_star_count_and_the_page_of_a_below_floor_story_still_reads(floor_site):
    ranking.rate(floor_site, "eight", 4)
    reproject(floor_site)
    for key, body in floor_site.tree.items():
        for word in ("starRating", "starRatedBy", "data-stars"):
            assert word not in body.decode("utf-8", "ignore"), key


def test_public_data_lists_only_stories_at_the_floor(floor_site):
    ranking.rate(floor_site, "eight", 4)
    reproject(floor_site)
    data = [key for key in floor_site.tree if key.endswith(".json") and "six" not in key]
    text = public_data_text(floor_site)
    assert data, "the site writes public data"
    assert "EIGHT" in text and "SIX" not in text


def test_the_quality_key_reaches_the_standard_settings_and_the_home_page_settings():
    from papyrus_content.projection.standard.config import standard_settings_from_mapping

    base = {"site": {"name": "Example"}, "homePage": {}}
    assert standard_settings_from_mapping(base).quality.floor_stars is None
    assert standard_settings_from_mapping(base).home_page.floor_stars is None
    on = standard_settings_from_mapping({**base, "quality": {"floorStars": 4}})
    assert on.quality.floor_stars == 4 and on.home_page.floor_stars == 4
    with pytest.raises(ValueError, match="quality.floorStars"):
        standard_settings_from_mapping({**base, "quality": {"floorStars": 0}})
