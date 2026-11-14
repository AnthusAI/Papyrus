"""Steps for features_backend/home-page-references-filters.feature. Local directories only: no network, no AWS."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from procedures.newsroom.tests.reference_list_support import list_files, project, record  # noqa: E402
from procedures.newsroom.tests.test_reference_list_paging import chain, keys_in, section_of  # noqa: E402


def numbers_in(markup: str) -> set[int]:
    return {int(number) for number in re.findall(r"Reference number (\d+)", markup)}


def numbers_of(records: list[dict], keep) -> set[int]:
    return {int(found["key"], 16) for found in records if keep(found)}


def document_of(records: list[dict]) -> dict:
    ordered = sorted(records, key=lambda found: -int(found["key"], 16))
    for position, found in enumerate(ordered, start=1):
        found["rank"] = position
    return {"generatedAt": "2026-11-04T12:00:00.000Z", "corpus": "knowledge-corpus-example", "fields": [], "references": ordered}


def accepted(number: int, section: str | None, medium: str | None = None) -> dict:
    found = record(number, "accepted")
    found.pop("section", None)
    if section:
        found["section"] = section
    if medium:
        found["medium"] = medium
    return found


def numbered(start: int, count: int, section: str | None, medium: str | None = None) -> list[dict]:
    return [accepted(number, section, medium) for number in range(start, start + count)]


@given('a snapshot of 200 accepted References, 150 filed under "Agents" or "Science", 50 with no section and 5 filed under "Papyrus"')
def _(context):
    context.records = numbered(1, 75, "Agents") + numbered(76, 75, "Science") + numbered(151, 50, None) + numbered(201, 5, "Papyrus")


@given("a snapshot of accepted videos and accepted articles")
def _(context):
    context.records = numbered(1, 12, "Tools", "video") + numbered(13, 12, "Tools")


@given('a snapshot of accepted References in "Agents", "Science" and "Art"')
def _(context):
    context.records = numbered(1, 10, "Agents") + numbered(11, 10, "Science") + numbered(21, 10, "Art")


def page_with(context, include: str) -> None:
    context.page_source = ('::band{size="bare"}\n\n' + include + "\n").encode("utf-8")


@given('a page with a paged references include with notSection "{values}", a first page of {first:d} and the id "{name}"')
def _(context, values, first, name):
    page_with(context, f'::include{{kind="references" select="recent" notSection="{values}" count="{first}" paged="true" id="{name}"}}')


@given('a page with a references include with notMedium "{value}" and a count of {count:d}')
def _(context, value, count):
    page_with(context, f'::include{{kind="references" select="recent" notMedium="{value}" count="{count}"}}')


@given('a page with a references include with section "{values}" and a count of {count:d}')
def _(context, values, count):
    page_with(context, f'::include{{kind="references" select="recent" section="{values}" count="{count}"}}')


@given('a page with a references include with medium "{medium}" and notMedium "{other}"')
def _(context, medium, other):
    page_with(context, f'::include{{kind="references" select="recent" medium="{medium}" notMedium="{other}" count="6"}}')


@given('a page with a references include with notMedium "{value}"')
def _(context, value):
    page_with(context, f'::include{{kind="references" select="recent" notMedium="{value}" count="6"}}')


@given('a page with a paged references include with section "{value}" and no id')
def _(context, value):
    page_with(context, f'::include{{kind="references" select="recent" section="{value}" count="4" paged="true"}}')


def build(context):
    context.site = project(document_of(context.records), first=6, page_size=12, extra_files={"pages/wire.md": context.page_source})
    context.add_cleanup(context.site.cleanup)


@when("the filtered references site is projected")
def _(context):
    build(context)


@then('the page and the data files of the "{name}" list together hold exactly the {total:d} References not filed under Agents or Science, each once')
def _(context, name, total):
    shown = keys_in(section_of(context.site.text("wire/index.html"), "recent"))
    shown += [key for data in chain(context.site, "recent") for key in keys_in(data["html"])]
    wanted = [found["key"] for found in context.records if found.get("section") not in ("Agents", "Science")]
    assert len(shown) == total and len(set(shown)) == total and set(shown) == set(wanted), (len(shown), len(set(shown)), len(wanted))
    assert f"/reference-lists/wire/{name}/" in context.site.text("wire/index.html")


@then('no data file of the "{name}" list is empty')
def _(context, name):
    files = chain(context.site, "recent")
    assert files and all(keys_in(data["html"]) for data in files)
    assert [key for key in list_files(context.site) if key.endswith(".json") and f"/{name}/" in key]


@then("no card on the page is a video and the page shows {count:d} cards")
def _(context, count):
    shown = numbers_in(context.site.text("wire/index.html"))
    videos = numbers_of(context.records, lambda found: found.get("medium") == "video")
    assert len(shown) == count and not shown & videos


@then("the page shows the Agents and Science References and no Art Reference")
def _(context):
    shown = numbers_in(context.site.text("wire/index.html"))
    wanted = numbers_of(context.records, lambda found: found.get("section") in ("Agents", "Science"))
    assert shown == wanted, shown


@then("the Markdown twin of the page lists the same References as the page")
def _(context):
    twin = context.site.text("wire/index.md")
    expected = numbers_in(context.site.text("wire/index.html"))
    found = numbers_in(twin)
    assert found and found == expected, (sorted(found), sorted(expected))


def refused(context) -> str:
    try:
        build(context)
    except (ValueError, AssertionError) as error:
        return str(error)
    raise AssertionError("the build went on")


@then("projecting the site stops and the error names the page and says medium and notMedium cannot be used together")
def _(context):
    message = refused(context)
    assert "wire.md" in message and "medium and notMedium together" in message, message


@then("projecting the site stops and the error names the page and the allowed media")
def _(context):
    message = refused(context)
    assert "wire.md" in message and "notMedium must be one of" in message and "video" in message, message


@then('the list is named "{name}" and shows only the Art References')
def _(context, name):
    page = context.site.text("wire/index.html")
    assert f"/reference-lists/wire/{name}/" in page, page[-800:]
    art = {found["key"] for found in context.records if found.get("section") == "Art"}
    shown = keys_in(section_of(page, "recent")) + [key for data in chain(context.site, "recent") for key in keys_in(data["html"])]
    assert set(shown) == art and len(shown) == len(art)
