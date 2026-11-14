"""The public home page puts rated References first and never prints the rating (features_backend/home-page-human-ratings.feature)."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from features_backend.steps.home_page_snapshot_steps import FixtureClient, document, run_snapshot, titled  # noqa: E402
from papyrus_content.home_page.export import EXCLUDED_REFERENCE_FIELDS  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, fixture_settings  # noqa: E402

PAGES = {
    "by-confidence": '::band{size="bare"}\n::include{kind="references" select="confident" count="12"}\n',
    "suggested": '::band{size="bare"}\n::include{kind="references" select="recommended" count="12"}\n',
    "newest": '::band{size="bare"}\n::include{kind="references" select="recent" count="12"}\n',
    "weekly": '::band{size="bare"}\n::include{kind="references" select="recent" bucket="week" count="12"}\n',
    "daily": '::band{size="bare"}\n::include{kind="references" select="recent" bucket="day" count="12"}\n',
    "confident-weekly": '::band{size="bare"}\n::include{kind="references" select="confident" bucket="week" count="12"}\n',
}
AS_OF = date(2026, 10, 31)   # the UTC day rolling buckets count back from, fixed so the scenarios do not depend on today
PRIVATE_SENTINELS = ("starRating", "starRatedAt", "starRatedBy", "editor-who-rated@example.test", "2026-10-31T09:00:00.000Z")


def build_site(context, pages: dict[str, str]) -> None:
    settings = fixture_settings("flat")
    settings["homePage"] = {"references": {"corpus": "knowledge-corpus-example", "defaultCount": 12}}
    settings["pages"] = [{"id": name, "path": name, "title": name.title(), "description": name, "dependsOn": [], "source": f"pages/{name}.md"} for name in pages]
    context.client = FixtureClient()
    context.build_error = None
    context.reports = []
    context.base_path = ""
    try:
        context.site = ProjectedSite(settings=settings, content=FIXTURES / "flat" / "content", clock=lambda: AS_OF, extra_files={f"pages/{name}.md": text for name, text in pages.items()})
    except (AssertionError, ValueError) as error:
        context.build_error = str(error)
        return
    context.add_cleanup(context.site.cleanup)


def rate(context, title: str, stars: int) -> None:
    rows = [row for row in context.client.rows() if row["title"].startswith(title)]
    assert len(rows) == 1, (title, [row["title"] for row in context.client.rows()])
    rows[0].update({"starRating": stars, "starRatedAt": "2026-10-31T09:00:00.000Z", "starRatedBy": "editor-who-rated@example.test"})


@given("a home-page site whose pages place confident, recommended, recent, weekly, daily and weekly confident grids")
def site_with_every_grid(context) -> None:
    build_site(context, PAGES)
    assert context.build_error is None, context.build_error


@given('a home-page site with a page whose references include has the bucket "{bucket}"')
def site_with_a_bad_bucket(context, bucket: str) -> None:
    build_site(context, {"bad": f'::band{{size="bare"}}\n::include{{kind="references" select="recent" bucket="{bucket}" count="3"}}\n'})


@given("the day of the render is {day}")
def day_of_the_render(context, day: str) -> None:
    context.site.projector.clock = lambda: date.fromisoformat(day)


@given("editors rated these References: {ratings}")
def editors_rated(context, ratings: str) -> None:
    for title, count in re.findall(r'"([^"]+)"\s+(\d)', ratings):
        rate(context, title, int(count))


@given("the home-page-snapshot task has run")
def snapshot_has_run(context) -> None:
    run_snapshot(context)
    context.before = document(context)


@when("editors rate these References: {ratings} and the home-page-snapshot task runs")
def rate_and_run(context, ratings: str) -> None:
    editors_rated(context, ratings)
    run_snapshot(context)


@when('an editor rates "{title}" {stars:d} stars and the home-page-snapshot task runs again')
def rate_and_run_again(context, title: str, stars: int) -> None:
    rate(context, title, stars)
    context.site.writer.operations.clear()
    run_snapshot(context)


@then('the record titled "{title}" has {stars:d} stars')
def record_has_stars(context, title: str, stars: int) -> None:
    assert titled(context, title)["stars"] == stars, titled(context, title)


@then('the record titled "{title}" has no stars')
def record_has_no_stars(context, title: str) -> None:
    assert titled(context, title)["stars"] is None, titled(context, title)


@when('an editor clears the rating of "{title}" and the home-page-snapshot task runs again')
def clear_and_run_again(context, title: str) -> None:
    rows = [row for row in context.client.rows() if row["title"].startswith(title)]
    assert len(rows) == 1
    rows[0].update({"starRating": None, "starRatedAt": None, "starRatedBy": None})
    context.site.writer.operations.clear()
    run_snapshot(context)


@then("no record in the file names who rated or when")
def no_rater_in_records(context) -> None:
    for record in document(context)["references"]:
        assert not [name for name in record if name != "stars" and ("star" in name.lower() or "rated" in name.lower())], record
        assert not set(record) & set(EXCLUDED_REFERENCE_FIELDS), record


@then("no file the site holds mentions who rated or when")
def no_rater_anywhere(context) -> None:
    for name, content in context.site.tree.items():
        for sentinel in PRIVATE_SENTINELS:
            assert sentinel.encode() not in content, f"{name} mentions {sentinel}"


@then("every record has a rank that is a position in the shared order, from 1 to the number of records")
def ranks_are_positions(context) -> None:
    records = document(context)["references"]
    assert sorted(record["rank"] for record in records) == list(range(1, len(records) + 1)), [record["rank"] for record in records]


@then('the only differences in the file are the ranks of the References that moved and the stars of "{title}"')
def only_rank_and_stars_differ(context, title: str) -> None:
    def comparable(snapshot: dict) -> list[dict]:
        return [{key: value for key, value in record.items() if key != "rank" and not (key == "stars" and record["title"] == title)} for record in snapshot["references"]]

    after = document(context)
    assert comparable(after) == comparable(context.before)
    before_stars = next(record["stars"] for record in context.before["references"] if record["title"] == title)
    assert titled(context, title)["stars"] != before_stars, "the rated record's count changed"


@then('the build failed saying "{first}" and "{second}" and "{third}"')
def build_failed_three(context, first: str, second: str, third: str) -> None:
    assert context.build_error is not None, "the build succeeded"
    for text in (first, second, third):
        assert text in context.build_error, context.build_error


@then('the file keeps "{title}" at rank {rank:d}')
def keeps_rank(context, title: str, rank: int) -> None:
    found = [record for record in document(context)["references"] if record["title"] == title]
    assert found and found[0]["rank"] == rank, found

