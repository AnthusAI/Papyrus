"""Steps for features_backend/story-stars-cli.feature. Every client is an in-memory fake; nothing leaves the process."""

from __future__ import annotations

import contextlib
import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_story_stars_cli as support  # noqa: E402
from datetime import date  # noqa: E402

from papyrus_content import story_commands, story_signals  # noqa: E402

# Ranking buckets by rolling week from today, so the dates are days before the run, not calendar dates: "a" and "c" are in the last seven days, "b" the week
# before and "d" long before. Fixed dates would drift out of their buckets as the days pass.
AGES_IN_DAYS = {"a": 1, "b": 8, "c": 2, "d": 38}


def _date(name):
    return (datetime.now(timezone.utc) - timedelta(days=AGES_IN_DAYS[name])).strftime("%Y-%m-%dT10:00:00Z")


def _run(context, function, flags):
    context.failure, out = None, io.StringIO()
    # The Stories' dates are fixed, so the day the ranking counts from is fixed too; the real day would move them across week boundaries.
    with mock.patch.object(story_commands, "create_authoring_client", return_value=(context.client, {})), \
            mock.patch.object(story_signals, "utc_today", return_value=date(2026, 11, 8)), contextlib.redirect_stdout(out):
        try:
            function(flags)
        except ValueError as error:
            context.failure = error
    context.rows = [line.split("\t") for line in out.getvalue().splitlines()]


@given('the signed-in site has rated Stories "a" with 2 stars, "b" with 5 stars, "c" unrated and "d" with 4 stars')
def _stories(context):
    context.client = support.Client(*[support.story(name, stars, _date(name)) for name, stars in (("a", 2), ("b", 5), ("c", None), ("d", 4))])


@when("an editor lists the Stories")
def _list(context):
    _run(context, story_commands.stories_list, [])


@when('an editor lists the Stories with "{flags}"')
def _list_with(context, flags):
    _run(context, story_commands.stories_list, flags.split())


def _row(context, lineage):
    return next(row for row in context.rows if row[1] == "list" and row[2] == lineage)


@then('the Story "{lineage}" is listed with {stars:d} stars from the source "{source}" and {votes:d} vote')
@then('the Story "{lineage}" is listed with {stars:d} stars from the source "{source}" and {votes:d} votes')
def _listed_with(context, lineage, stars, source, votes):
    assert _row(context, lineage)[6:9] == [str(stars), source, str(votes)], context.rows


@then('only the Stories "{names}" are listed')
def _only(context, names):
    assert sorted(row[2] for row in context.rows[:-1]) == sorted(names.split(", ")), context.rows


@then('the Stories are listed in the order "{names}"')
def _order(context, names):
    assert [row[2] for row in context.rows[:-1]] == names.split(", "), context.rows


@when('an editor shows the Story "{lineage}"')
def _show(context, lineage):
    _run(context, story_commands.stories_show, ["--story", lineage])


@then('the shown signals say {stars:d} stars from the source "{source}" and the rating names "{who}"')
def _shown_rated(context, stars, source, who):
    signals = next(row for row in context.rows if row[2] == "signals")
    assert f"stars {stars}" in signals and f"source {source}" in signals
    assert f"ratedBy {who}" in next(row for row in context.rows if row[2] == "rating")


@then('the shown signals say {stars:d} stars from the source "{source}" and there is no rating line')
def _shown_unrated(context, stars, source):
    signals = next(row for row in context.rows if row[2] == "signals")
    assert f"stars {stars}" in signals and f"source {source}" in signals and not any(row[2] == "rating" for row in context.rows)


@when('an editor sets the stars of the Story "{lineage}" to "{stars}"')
def _set(context, lineage, stars):
    _run(context, story_commands.stories_set_stars, ["--story", lineage, "--stars", stars])


@when('an editor sets the stars of the Story "{lineage}" to "{stars}" as a dry run')
def _set_dry(context, lineage, stars):
    _run(context, story_commands.stories_set_stars, ["--story", lineage, "--stars", stars, "--dry-run"])


@then("the output says previous {previous:d} and stars {stars:d} and the newsroom was asked to set the stars to {asked:d}")
def _set_output(context, previous, stars, asked):
    assert f"previous {previous}" in context.rows[0] and f"stars {stars}" in context.rows[0]
    assert context.client.sent[0][1]["stars"] == asked


@then("the newsroom was asked to clear the stars")
def _cleared(context):
    assert context.client.sent[0][1]["stars"] is None


@then("the command fails saying the stars run from 0 to 5 and the newsroom was not asked")
def _refused(context):
    assert context.failure and "0 to 5" in str(context.failure) and context.client.sent == []


@then("the newsroom was not asked")
def _not_asked(context):
    assert context.client.sent == []
