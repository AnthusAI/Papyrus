"""Steps for features_backend/site/home-page-references-min-stars.feature. Local directories only: no network, no AWS."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from features_backend.steps.home_page_references_filters_steps import document_of, numbers_in, page_with  # noqa: E402
from procedures.newsroom.tests.reference_list_support import list_files, project, record  # noqa: E402
from procedures.newsroom.tests.test_reference_list_paging import chain, keys_in, section_of  # noqa: E402

LOW_RATED_NEWEST = 8
HIGH_RATINGS = (3, 4, 5, 4, 3, 5)


def video(number: int, stars: int | None) -> dict:
    found = record(number, "accepted")
    found["medium"] = "video"
    if stars is not None:
        found["stars"] = stars
    return found


def number_of(key: str) -> int:
    return int(key, 16)


@given("a snapshot of 30 accepted videos in which the newest 8 are rated 1 or 2, 6 are rated 3 to 5 and the rest are unrated")
def _(context):
    context.records = []
    for number in range(1, 31):
        rank_from_newest = 31 - number
        if rank_from_newest <= LOW_RATED_NEWEST:
            stars = 1 + number % 2
        elif rank_from_newest <= LOW_RATED_NEWEST + len(HIGH_RATINGS):
            stars = HIGH_RATINGS[rank_from_newest - LOW_RATED_NEWEST - 1]
        else:
            stars = None
        context.records.append(video(number, stars))


@given("a snapshot of 10 accepted videos in which 7 are rated 1 or 2 and 3 are rated 4")
def _(context):
    context.records = [video(number, 4 if number <= 3 else 1 + number % 2) for number in range(1, 11)]


@given('a page with a paged videos include with minStars "{minimum}"')
def _(context, minimum):
    page_with(context, f'::include{{kind="references" select="recent" medium="video" minStars="{minimum}" count="6" paged="true" id="all"}}')


@given('a page with a counted videos include with minStars "{minimum}" and a count of {count:d}')
def _(context, minimum, count):
    page_with(context, f'::include{{kind="references" select="recent" medium="video" minStars="{minimum}" count="{count}"}}')


@given("a page with a counted videos include with no minStars and a count of {count:d}")
def _(context, count):
    page_with(context, f'::include{{kind="references" select="recent" medium="video" count="{count}"}}')


def build(context):
    context.site = project(document_of(context.records), first=6, page_size=12, extra_files={"pages/wire.md": context.page_source})
    context.add_cleanup(context.site.cleanup)


@when("the minimum stars site is projected")
def _(context):
    build(context)


def low_rated_numbers(context) -> set[int]:
    return {number_of(found["key"]) for found in context.records if found.get("stars") in (1, 2)}


@then("no video rated 1 or 2 is on the page or in any data file of its lists")
def _(context):
    low = low_rated_numbers(context)
    assert low
    shown = numbers_in(context.site.text("wire/index.html"))
    for data in chain(context.site, "recent"):
        shown |= numbers_in(data["html"])
    assert shown and not shown & low, sorted(shown & low)


@then("the paged list holds the 22 videos not rated 1 or 2, each once, and no data file of it is empty")
def _(context):
    page = context.site.text("wire/index.html")
    shown = keys_in(section_of(page, "recent")) + [key for data in chain(context.site, "recent") for key in keys_in(data["html"])]
    wanted = {found["key"] for found in context.records if found.get("stars") not in (1, 2)}
    assert len(shown) == 22 == len(set(shown)) and set(shown) == wanted, (len(shown), len(set(shown)))
    files = chain(context.site, "recent")
    assert files and all(keys_in(data["html"]) for data in files)
    assert [key for key in list_files(context.site) if key.endswith(".json")]


@then("the page shows {count:d} videos and none of them is rated 1 or 2")
def _(context, count):
    shown = numbers_in(context.site.text("wire/index.html"))
    assert len(shown) == count and not shown & low_rated_numbers(context), sorted(shown)


@then("the page shows the 22 videos not rated 1 or 2 in the order a page without minStars gives them")
def _(context):
    html = context.site.text("wire/index.html")
    order = [int(number) for number in re.findall(r"Reference number (\d+)", html)]
    order = list(dict.fromkeys(order))
    unfiltered = [number_of(found["key"]) for found in sorted(context.records, key=lambda found: found["rank"])]
    expected = [number for number in unfiltered if number not in low_rated_numbers(context)]
    assert len(expected) == 22 and order == expected, (order, expected)


@then("the page shows all {count:d} videos")
def _(context, count):
    assert len(numbers_in(context.site.text("wire/index.html"))) == count


@then("projecting the minimum stars site stops and the error names the page and the allowed ratings")
def _(context):
    try:
        build(context)
    except (ValueError, AssertionError) as error:
        message = str(error)
    else:
        raise AssertionError("the build went on")
    assert "wire.md" in message and "minStars must be one of" in message and "3" in message, message
