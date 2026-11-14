"""Published Stories rank by recency bucket and then by the editors' private stars (PPY-5966d7): listings, the featured slot, includes and the rating task."""

from __future__ import annotations

from datetime import date

import pytest

from papyrus_content.projection.engine import project_all, project_stale_listings
from papyrus_content.projection.story_stars import MemoryStarStore
from papyrus_content.projection.story_stars_task import run_story_stars_task
from procedures.newsroom.tests.standard_frontend_content_support import cards, cms_site, featured, item, settings
from procedures.newsroom.tests.standard_frontend_support import written_keys

BAND = '::band{size="bare"}\n'
PAGES = [
    {"id": "latest", "path": "latest", "title": "Latest", "source": "latest.md"},
    {"id": "days", "path": "days", "title": "Days", "source": "days.md"},
    {"id": "plain", "path": "plain", "title": "Plain", "source": "plain.md"},
    {"id": "hero", "path": "hero", "title": "Hero", "source": "hero.md"},
]
FILES = {
    "latest.md": f'{BAND}::include{{kind="listing" types="article" count="20" layout="bare"}}\n',
    "days.md": f'{BAND}::include{{kind="listing" types="article" count="20" layout="bare" bucket="day"}}\n',
    "plain.md": f'{BAND}::include{{kind="listing" types="article" count="20" layout="bare" bucket="none"}}\n',
    "hero.md": f'{BAND}::include{{kind="listing" types="article" count="1" layout="bare"}}\n',
}
# Projected on 2026-02-08 the last seven days are 2026-02-02 to 2026-02-08: the five-star article (the 2nd) and the six newer ones are in that window, and
# the two Stories of the week before (the 29th and 30th) are in the window before it.
AS_OF = date(2026, 2, 8)
WEEK = [("eight", "2026-02-08"), ("seven", "2026-02-07"), ("six", "2026-02-06"), ("five", "2026-02-05"), ("four", "2026-02-04"), ("three", "2026-02-03")]
THIS_WEEK_STAR = ("star", "2026-02-02")
LAST_WEEK = [("old-a", "2026-01-30"), ("old-b", "2026-01-29")]
SETTINGS = settings(
    urls={"sections": {"posts": {}}},
    collections=[{"id": "everything", "base": "everything", "select": {"sections": ["posts"]}}],
    listings={"featuredCount": 1, "pageSize": 20},
    pages=PAGES,
)


HOOK_PAGE = {"id": "hooked", "path": "hooked", "title": "Hooked", "source": "hooked.md"}
HOOKS = (
    "def main(page):\n"
    "    if page.custom_id != 'hooked':\n"
    "        return None\n"
    "    ranked = page.ranked([entry for entry in page.entries if entry.type == 'article'])\n"
    "    return '<main><ol>' + ''.join('<li data-story=\"' + entry.slug + '\"></li>' for entry in ranked) + '</ol></main>'\n"
)


def hooked_site():
    settings_ = {**SETTINGS, "hooks": "hooks.py", "pages": [*PAGES, HOOK_PAGE]}
    projected = cms_site(settings_, stories(), {**FILES, "hooks.py": HOOKS, "hooked.md": BAND})
    projected.context.source.star_store = MemoryStarStore()
    projected.projector.clock = lambda: AS_OF
    return projected


def hooked(site) -> list[str]:
    import re

    return re.findall(r'data-story="([^"]+)"', site.text("hooked/index.html"))


def stories():
    return [item(slug, date=day) for slug, day in [*WEEK, THIS_WEEK_STAR, *LAST_WEEK]]


def rate(site, slug: str, count: int | None) -> None:
    row = site.client.tables["Item"][f"item-posts-{slug}"]
    row.update(starRating=count, starRatedAt="2026-11-03T09:00:00Z" if count else None, starRatedBy="an editor" if count else None)


@pytest.fixture()
def site():
    projected = cms_site(SETTINGS, stories(), FILES)
    projected.context.source.star_store = MemoryStarStore()
    projected.projector.clock = lambda: AS_OF
    yield projected
    projected.cleanup()


def listing(site, name: str = "latest") -> list[str]:
    return cards(site.text(f"{name}/index.html"))


def newest_first() -> list[str]:
    return [slug for slug, _day in [*WEEK, THIS_WEEK_STAR, *LAST_WEEK]]


def reproject(site):
    report = project_all(site.context)
    assert report.ok, report.errors
    return report


def test_a_site_with_no_stars_lists_newest_first_exactly_as_before(site):
    before = dict(site.tree)
    reproject(site)
    assert listing(site) == newest_first()
    assert site.tree == before, "no rated Story: no page changes by a single byte"


def test_a_five_star_story_stays_the_hero_above_six_newer_lower_rated_stories(site):
    rate(site, "star", 5)
    for slug in ("eight", "seven", "six", "five", "four", "three"):
        rate(site, slug, 2)
    reproject(site)
    assert cards(site.text("hero/index.html")) == ["star"]
    assert listing(site)[0] == "star"
    assert featured(site.text("posts/index.html")) == ["star"], "the featured slot of the Story-type listing page is the best of the newest bucket"


def test_inside_a_bucket_stories_rank_five_four_three_then_unrated_then_two_and_one(site):
    rate(site, "three", 1)
    rate(site, "four", 2)
    rate(site, "five", 3)
    rate(site, "six", 4)
    rate(site, "seven", 5)
    reproject(site)
    assert listing(site)[:7] == ["seven", "six", "five", "eight", "star", "four", "three"]


def test_older_stories_are_not_dropped_they_follow_in_earlier_buckets_each_ranked_inside_itself(site):
    rate(site, "old-b", 5)
    rate(site, "eight", 1)
    reproject(site)
    ranked = listing(site)
    assert sorted(ranked) == sorted(newest_first()), "every Story is still listed"
    assert ranked[-2:] == ["old-b", "old-a"], "last week's Stories follow this week's, the five-star one first inside its own bucket"
    assert ranked.index("eight") < ranked.index("old-b"), "a five-star Story of an earlier bucket never rises above a newer bucket"


def test_the_section_listing_pages_and_a_collection_rank_the_same_way(site):
    rate(site, "three", 5)
    reproject(site)
    assert cards(site.text("posts/index.html"))[0] == "three"
    assert cards(site.text("everything/index.html"))[0] == "three"
    # tag and flat listings follow the same ranking; the feed and the sitemap never do
    assert site.text("feed.xml").index("/eight") <site.text("feed.xml").index("/three")


def test_bucket_day_ranks_inside_a_day_and_bucket_none_keeps_newest_first(site):
    rate(site, "three", 5)
    reproject(site)
    assert listing(site, "days") == newest_first(), "each day holds one Story, so a day bucket changes nothing here"
    assert listing(site, "plain") == newest_first(), "bucket none is the plain newest-first list"
    assert listing(site)[0] == "three"


def test_unrated_stories_sort_sensibly_between_high_and_low_ratings(site):
    rate(site, "eight", 2)
    rate(site, "three", 4)
    reproject(site)
    this_week = listing(site)[:7]
    assert this_week[0] == "three" and this_week[-1] == "eight"
    assert this_week[1:-1] == ["seven", "six", "five", "four", "star"], "unrated Stories keep newest-first order between them"


def test_stars_never_appear_in_any_public_file(site):
    rate(site, "three", 5)
    rate(site, "six", 1)
    reproject(site)
    for key, body in site.tree.items():
        text = body.decode("utf-8", "ignore")
        for word in ("starRating", "starRatedAt", "starRatedBy", "data-stars", "story-stars", "an editor"):
            assert word not in text, f"{word} leaked into {key}"


def test_a_rating_that_moves_nothing_rewrites_no_page(site):
    rate(site, "eight", 3)
    reproject(site)
    store = site.context.source.star_store
    store.record({"item-posts-eight": 5})
    site.writer.operations.clear()
    report = project_stale_listings(site.context)
    assert report.ok and not report.written, "four stars or five, the order is the same, so nothing is written"
    assert written_keys(site) == set()


def test_a_rating_that_moves_a_story_rewrites_only_the_listings_that_show_the_move(site):
    reproject(site)
    site.writer.operations.clear()
    site.context.source.star_store.record({"item-posts-three": 5})
    report = project_stale_listings(site.context)
    assert report.ok
    changed = {key for key in report.written if key.endswith(".html")}
    assert changed == {"index.html", "latest/index.html", "hero/index.html", "posts/index.html", "everything/index.html"}, "the days and plain listings keep their order and are not touched"
    assert listing(site)[0] == "three"
    assert not any(key.startswith(("posts/three", "posts/eight")) for key in report.written), "no Story page is rendered again"


# ------------------------------------------------------------------ the rating task


def test_the_task_records_the_rating_and_rewrites_the_pages_whose_order_changed(site):
    reproject(site)
    site.writer.operations.clear()
    rate(site, "three", 5)
    result = run_story_stars_task(site.context, site.client, {"task": "story-stars", "itemId": "item-posts-three"})
    assert result["recorded"] and result["published"] and result["pagesRewritten"] > 0
    assert site.context.source.star_store.stars["item-posts-three"] == 5
    assert listing(site)[0] == "three"
    again = run_story_stars_task(site.context, site.client, {"task": "story-stars", "itemId": "item-posts-three"})
    assert again == {"ok": True, "recorded": False, "pagesRewritten": 0}, "the same rating twice does nothing"


def test_clearing_a_rating_puts_the_story_back_in_date_order(site):
    rate(site, "three", 5)
    reproject(site)
    rate(site, "three", None)
    run_story_stars_task(site.context, site.client, {"task": "story-stars", "itemId": "item-posts-three"})
    assert listing(site) == newest_first()


def test_rating_a_story_nobody_has_published_records_it_and_renders_nothing(site):
    site.client.tables["Item"]["draft-v1"] = {"id": "draft-v1", "lineageId": "draft", "type": "article", "versionState": "current", "starRating": 4}
    result = run_story_stars_task(site.context, site.client, {"task": "story-stars", "itemId": "draft-v1"})
    assert result["recorded"] is True and result["published"] is False and result["pagesRewritten"] == 0
    assert site.context.source.star_store.stars["draft"] == 4


def test_the_task_without_a_rating_store_or_an_item_does_nothing(site):
    assert "skipped" in run_story_stars_task(site.context, site.client, {"task": "story-stars", "itemId": "nothing"})
    site.context.source.star_store = None
    assert "skipped" in run_story_stars_task(site.context, site.client, {"task": "story-stars", "itemId": "item-posts-three"})


def test_a_story_published_after_it_was_rated_is_ranked_without_a_rating_event(site):
    """The store has never seen the Story: its rating is read once from the Item rows, so rating before publishing counts."""
    rate(site, "three", 5)
    store = site.context.source.star_store
    assert "item-posts-three" not in store.stars
    reproject(site)
    assert store.stars["item-posts-three"] == 5 and listing(site)[0] == "three"
    reads = store.reads
    reproject(site)
    assert store.stars == {**store.stars}, "a second projection finds every Story known"
    assert store.writes == 1 and store.reads == reads + 1


def test_the_markdown_twin_lists_stories_in_the_page_order_and_carries_no_star(site):
    rate(site, "three", 5)
    reproject(site)
    twin = site.text("latest/index.md")
    links = [line for line in twin.splitlines() if "/posts/" in line]
    assert "/three" in links[0], twin
    assert [name for name in ("starRating", "stars", "data-stars", "an editor") if name in twin] == []


# ------------------------------------------------------------------ rolling windows


def test_a_week_is_the_last_seven_days_counted_back_from_the_day_of_the_projection(site):
    rate(site, "star", 5)
    rate(site, "three", 1)
    site.projector.clock = lambda: date(2026, 2, 10)   # two days later: the 2nd and 3rd have fallen out of the last seven days
    reproject(site)
    assert listing(site) == ["eight", "seven", "six", "five", "four", "star", "old-a", "old-b", "three"]


def test_a_story_changes_bucket_with_time_alone_and_only_a_later_pass_corrects_the_pages(site):
    rate(site, "star", 5)
    reproject(site)
    assert listing(site)[0] == "star"
    site.projector.clock = lambda: date(2026, 2, 10)
    assert listing(site)[0] == "star", "nothing re-rendered, so the page still holds the old order"
    site.writer.operations.clear()
    report = project_stale_listings(site.context)
    assert report.ok and {"latest/index.html", "posts/index.html", "index.html"} <= set(report.written)
    assert listing(site)[0] == "eight"
    again = project_stale_listings(site.context)
    assert not again.written, "once corrected, nothing is rewritten until the day changes again"


def test_the_order_depends_on_the_day_and_never_on_the_time():
    from papyrus_content.home_page.ordering import rolling_age

    assert [rolling_age(day, "week", date(2026, 2, 8)) for day in ("2026-02-08", "2026-02-02", "2026-02-01", "2026-01-26", "2026-02-20", "", None)] == [0, 0, 1, 1, 0, 2**31, 2**31]
    assert rolling_age("2026-02-07T23:59:00Z", "day", date(2026, 2, 8)) == 1


# ------------------------------------------------------------------ settings


def test_a_bucket_other_than_day_week_or_none_is_a_build_error_that_names_where():
    from papyrus_content.projection.standard.config import standard_settings_from_mapping

    with pytest.raises(ValueError, match="listings.bucket must be one of day, week, none, got 'month'"):
        standard_settings_from_mapping(settings(listings={"bucket": "month"}))
    with pytest.raises(ValueError, match="bucket must be one of day, week, none, got 'month'"):
        cms_site(settings(pages=[{"id": "p", "path": "p", "title": "P", "source": "p.md"}]), [item("x")], {"p.md": f'{BAND}::include{{kind="listing" bucket="month"}}\n'})


def test_a_site_can_make_none_its_default_bucket_and_keep_every_listing_newest_first():
    plain = cms_site({**SETTINGS, "listings": {"featuredCount": 1, "pageSize": 20, "bucket": "none"}}, stories(), FILES)
    plain.context.source.star_store = MemoryStarStore()
    plain.projector.clock = lambda: AS_OF
    try:
        rate(plain, "three", 5)
        reproject(plain)
        assert listing(plain) == newest_first()
        assert cards(plain.text("posts/index.html")) == newest_first()
    finally:
        plain.cleanup()


# ------------------------------------------------------------------ hooks: page.ranked


def test_a_hook_that_calls_page_ranked_sees_a_five_star_story_ahead_of_a_newer_unrated_one():
    site = hooked_site()
    try:
        assert hooked(site) == newest_first(), "nothing rated: newest first"
        rate(site, "three", 5)
        reproject(site)
        assert hooked(site)[:2] == ["three", "eight"], "five stars lead the bucket, the newer unrated Story follows"
        assert hooked(site)[-2:] == ["old-a", "old-b"] or hooked(site)[-2:] == ["old-b", "old-a"]
    finally:
        site.cleanup()


def test_a_rating_re_renders_the_hook_page_that_ranks_and_a_rating_that_moves_nothing_does_not():
    site = hooked_site()
    try:
        reproject(site)
        site.writer.operations.clear()
        site.context.source.star_store.record({"item-posts-three": 5})
        report = project_stale_listings(site.context)
        assert report.ok and "hooked/index.html" in report.written
        assert hooked(site)[0] == "three"
    finally:
        site.cleanup()
