"""`papyrus stories list|show|set-stars` and the Story-signal MCP tools: stars, source, votes, bucket, filters, sorts, and the privacy guard."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import test_cli_reads as support  # noqa: E402
from papyrus_content import story_commands, story_signals  # noqa: E402
from papyrus_content.item_stars import ITEM_STAR_FIELDS, effective_rating  # noqa: E402
from papyrus_content.story_signals_mcp import call_story_signal_tool, story_signal_descriptions, story_signal_tools  # noqa: E402

TODAY = date(2026, 11, 8)


def story(lineage, stars=None, published="2026-11-07T10:00:00Z", **extra):
    row = support.story(lineage, "published", updated=published, **{"type": "article", "publishedAt": published, "bodyMarkus": "one two three", **extra})
    if stars:
        row.update(starRating=stars, starRatedAt="2026-11-08T09:00:00Z", starRatedBy="An Editor")
    return row


class Client(support.Client):
    def __init__(self, *rows):
        super().__init__({"Item": list(rows), "NewsroomSection": [{"id": "news", "title": "News Desk"}]})
        self.sent = []

    def graphql(self, query, variables=None):
        self.sent.append((query, variables))
        return {"setItemStars": {"ok": True, "itemId": variables["itemId"], "lineageId": "a", "stars": variables["stars"]}}


def lines(client, function, *flags):
    with mock.patch.object(story_commands, "create_authoring_client", return_value=(client, {})):
        return [line.split("\t") for line in support.run(function, list(flags)).splitlines()]


def fleet():
    return Client(story("a", 2, "2026-11-07T10:00:00Z"), story("b", 5, "2026-11-01T10:00:00Z"), story("c", None, "2026-11-06T10:00:00Z"),
                  story("d", 4, "2026-10-01T10:00:00Z"), story("p", 3, type="post"))


def test_list_appends_the_signal_columns_after_the_existing_six():
    rows = lines(fleet(), story_commands.stories_list)
    first = next(row for row in rows if row[2] == "b")
    assert first[:6] == ["stories", "list", "b", "published", "news", "Title b"]
    assert first[6:] == ["5", "editor", "1", first[9], "article", "3", "2026-11-01T10:00:00Z"] and first[9].startswith("week:")
    unrated = next(row for row in rows if row[2] == "c")
    assert unrated[6:9] == ["0", "none", "0"]


def test_stars_filters():
    assert {row[2] for row in lines(fleet(), story_commands.stories_list, "--stars", "5")[:-1]} == {"b"}
    assert {row[2] for row in lines(fleet(), story_commands.stories_list, "--min-stars", "4")[:-1]} == {"b", "d"}
    assert {row[2] for row in lines(fleet(), story_commands.stories_list, "--max-stars", "3")[:-1]} == {"a", "p"}
    assert {row[2] for row in lines(fleet(), story_commands.stories_list, "--stars", "0")[:-1]} == {"c"}
    assert {row[2] for row in lines(fleet(), story_commands.stories_list, "--type", "post")[:-1]} == {"p"}


def test_sort_stars_is_high_to_low_with_unrated_last_and_limit_keeps_its_meaning():
    rows = lines(fleet(), story_commands.stories_list, "--sort", "stars", "--limit", "3")
    assert [row[2] for row in rows[:-1]] == ["b", "d", "p"] and rows[-1][2] == "3 of 5"
    assert [row[2] for row in lines(fleet(), story_commands.stories_list, "--sort", "stars")[:-1]][-1] == "c"


def test_sort_rank_is_the_pages_ranking():
    from papyrus_content.projection.standard.story_order import rank_entries  # the code the page uses; list_stories calls it
    rows, _ = story_signals.list_stories(fleet(), sort="rank", as_of=TODAY, story_type="article")
    # week:0 is 11-02..11-08 (a:2 stars, c unrated -> c, a? unrated before 2 stars), then week:1 (b), then older (d)
    assert [row["lineageId"] for row in rows] == ["c", "a", "b", "d"]
    assert [row["bucket"] for row in rows] == ["week:0", "week:0", "week:1", "week:5"]
    assert rank_entries is not None


@pytest.mark.parametrize("flag,value", [("--stars", "6"), ("--min-stars", "-1"), ("--sort", "best")])
def test_list_rejects_bad_values(flag, value):
    with pytest.raises(ValueError):
        lines(fleet(), story_commands.stories_list, flag, value)


def test_show_prints_signals_and_the_editor_rating():
    rows = lines(fleet(), story_commands.stories_show, "--story", "b")
    signals = next(row for row in rows if row[2] == "signals")
    assert signals[3:9] == ["type article", "section news", signals[5], "stars 5", "source editor", "votes 1"]
    assert next(row for row in rows if row[2] == "rating")[3:] == ["ratedBy An Editor", "ratedAt 2026-11-08T09:00:00Z"]
    unrated = lines(fleet(), story_commands.stories_show, "--story", "c")
    assert "stars 0" in next(row for row in unrated if row[2] == "signals") and not any(row[2] == "rating" for row in unrated)


def test_set_stars_calls_setItemStars_and_prints_previous_and_new():
    client = fleet()
    rows = lines(client, story_commands.stories_set_stars, "--story", "a", "--stars", "4")
    assert rows == [["stories", "set-stars", "a", "previous 2", "stars 4", "editor value", "write"]]
    assert "setItemStars" in client.sent[0][0] and client.sent[0][1]["itemId"] == "a-v1" and client.sent[0][1]["stars"] == 4


def test_set_stars_zero_clears_and_dry_run_sends_nothing():
    client = fleet()
    lines(client, story_commands.stories_set_stars, "--story", "a", "--stars", "0")
    assert client.sent[0][1]["stars"] is None
    client.sent.clear()
    assert lines(client, story_commands.stories_set_stars, "--story", "a", "--stars", "3", "--dry-run")[0][-1].startswith("dry-run") and client.sent == []


@pytest.mark.parametrize("value", ["6", "-1", "x"])
def test_set_stars_rejects_out_of_range(value):
    client = fleet()
    with pytest.raises(ValueError, match="0 to 5"):
        lines(client, story_commands.stories_set_stars, "--story", "a", "--stars", value)
    assert client.sent == []


def test_effective_rating_is_the_editor_value_today():
    assert effective_rating({"starRating": 3}) == {"stars": 3, "source": "editor", "votes": 1}
    assert effective_rating({}) == {"stars": 0, "source": "none", "votes": 0}


def test_mcp_tools_mirror_the_cli():
    assert set(story_signal_tools()) == set(story_signal_descriptions()) == {"stories_list", "stories_show", "stories_set_stars", "papyrus_link_stories", "papyrus_link_concepts",
                                                                                                           "papyrus_suggest_links", "papyrus_related_concepts", "papyrus_search_concepts"}
    client = fleet()
    listed = call_story_signal_tool("stories_list", {"minStars": 4, "sort": "stars"}, client)
    assert [row["lineageId"] for row in listed["stories"]] == ["b", "d"] and listed["stories"][0]["source"] == "editor"
    assert call_story_signal_tool("stories_set_stars", {"storyLineageId": "a", "stars": 5}, client)["applied"] is True
    with pytest.raises(ValueError):
        call_story_signal_tool("stories_set_stars", {"storyLineageId": "a", "stars": 6}, client)


def test_ratings_never_reach_a_published_row():
    from papyrus_content.item_stars import assert_no_item_stars

    for name in ITEM_STAR_FIELDS:
        with pytest.raises(AssertionError):
            assert_no_item_stars({"id": "published-a", name: 3})
    published_fields = set(story_signals.signals(story("a", 3), "week", TODAY)) & set(ITEM_STAR_FIELDS)
    assert published_fields == set()   # the signals dict is staff output, but it never reuses a stored star field name
