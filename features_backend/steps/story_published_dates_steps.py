"""A Story keeps its first publication time; the served version says when it went live (features_backend/story-published-dates*.feature)."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.publishing import ItemFields, publish_item, save_item, unpublish_item  # noqa: E402
from papyrus_content.story_published_dates import run_backfill_published_dates  # noqa: E402
from papyrus_content.story_reporting import save_story_version  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

LINEAGE = "item-articles-dated"
MONTHS = {"January": 1, "November": 11}


def iso(day: int, month: str, year: int, hour: int = 12, minute: int = 0) -> str:
    return f"{year:04d}-{MONTHS[month]:02d}-{day:02d}T{hour:02d}:{minute:02d}:00Z"


def fields(body: str = "Hello world.\n") -> ItemFields:
    return ItemFields(type="article", slug="dated", section="articles", front_matter_yaml="title: Dated\n", body_markus=body, aliases=[], id=LINEAGE)


def rows(client) -> list[dict]:
    return sorted((row for row in client.tables["Item"].values() if row.get("lineageId") == LINEAGE), key=lambda row: row["versionNumber"])


def newest(client) -> dict:
    return rows(client)[-1]


def published_row(client) -> dict:
    return client.tables["PublishedItem"]["published-" + LINEAGE]


def stamp_version(client, number: int, **changes) -> None:
    row = next(row for row in rows(client) if row["versionNumber"] == number)
    client.tables["Item"][row["id"]].update(changes)


@given("a Story first published on {day:d} {month} {year:d} at {hour:d}:{minute:d} by {who}")
def _first_published(context, day, month, year, hour, minute, who) -> None:
    context.client = FakeAuthoringClient()
    context.first = iso(day, month, year, hour, minute)
    context.first_by = who
    save_item(context.client, fields(), actor="Alex", now=iso(4, "November", 2026, 14, 0))
    publish_item(context.client, LINEAGE, actor=who, now=context.first)


@given('an editor saves a new version on {day:d} {month} {year:d} with the reason "{reason}"')
@when('an editor saves a new version on {day:d} {month} {year:d} with the reason "{reason}"')
def _new_version(context, day, month, year, reason) -> None:
    context.saved_at = iso(day, month, year)
    context.reason = reason
    save_story_version(context.client, LINEAGE, front_matter_yaml="title: Dated again\n", body_markus=f"Changed on {day}.\n", actor="Alex", change_reason=reason, now=context.saved_at)


@when("the editor {who} publishes that version on {day:d} {month} {year:d} at {hour:d}:{minute:d}")
def _publish_new(context, who, day, month, year, hour, minute) -> None:
    context.served_at = iso(day, month, year, hour, minute)
    publish_item(context.client, newest(context.client)["id"], actor=who, now=context.served_at)


@when("the Story is taken down on {day:d} {month} {year:d}")
def _take_down(context, day, month, year) -> None:
    unpublish_item(context.client, newest(context.client)["id"], actor="Sam", now=iso(day, month, year))


@when("an editor gives the Story four stars")
def _rate(context) -> None:
    context.client.update_record("Item", {"id": newest(context.client)["id"], "starRating": 4})


@when("the editor {who} publishes the Story again on {day:d} {month} {year:d} at {hour:d}:{minute:d}")
def _publish_again(context, who, day, month, year, hour, minute) -> None:
    context.client.calls.clear()
    publish_item(context.client, newest(context.client)["id"], actor=who, now=iso(day, month, year, hour, minute))


@then("the Story's published time is still {day:d} {month} {year:d} at {hour:d}:{minute:d}")
def _still_first(context, day, month, year, hour, minute) -> None:
    wanted = iso(day, month, year, hour, minute)
    assert newest(context.client)["publishedAt"] == wanted, newest(context.client)
    assert published_row(context.client)["publishedAt"] == wanted, published_row(context.client)


@then("the served version's published time is {day:d} {month} {year:d} at {hour:d}:{minute:d} by {who}")
def _served(context, day, month, year, hour, minute, who) -> None:
    wanted = iso(day, month, year, hour, minute)
    for row in (newest(context.client), published_row(context.client)):
        assert row["versionPublishedAt"] == wanted and row["versionPublishedBy"] == who, row


@then("the published row says the same two times")
def _same_two(context) -> None:
    served, published = newest(context.client), published_row(context.client)
    for name in ("publishedAt", "versionPublishedAt", "versionPublishedBy"):
        assert served[name] == published[name], (name, served, published)


@then('the version still says it was saved on {day:d} {month} {year:d} by the saving editor, with the reason "{reason}"')
def _own_record(context, day, month, year, reason) -> None:
    row = newest(context.client)
    assert row["versionCreatedBy"] == "Alex" and row["changeReason"] == reason, row
    assert row["versionCreatedAt"].startswith(f"{year:04d}-{MONTHS[month]:02d}-{day:02d}"), row


@then("the new draft carries the first publication time and has no version published time")
def _draft(context) -> None:
    row = newest(context.client)
    assert row["publishedAt"] == context.first and row["versionNumber"] == 2, row
    assert not row.get("versionPublishedAt") and not row.get("versionPublishedBy"), row


@then("no row of the Story was written")
def _nothing(context) -> None:
    assert context.client.write_calls() == [], context.client.write_calls()


# ---- the backfill ----------------------------------------------------------------------------------------------------------------------------------------

def old_style_story(client, versions: list[dict], *, served_number: int, published_at: str) -> None:
    """Rows as publishing left them before this change: no version published fields, the served row's own record overwritten by the publish."""
    previous = None
    for index, spec in enumerate(versions, start=1):
        row_id = LINEAGE if index == 1 else f"{LINEAGE}-v{index}"
        row = {
            "id": row_id, "lineageId": LINEAGE, "versionNumber": index, "versionState": "superseded" if index != served_number else "current",
            "type": "article", "status": "published" if index == served_number else "draft", "slug": "dated", "section": "articles", "title": "Dated",
            "versionCreatedAt": spec.get("at"), "versionCreatedBy": spec.get("by", "Alex"), "changeReason": spec.get("reason", "edited"),
            "updatedAt": f"2026-11-1{index}T00:00:00Z", "stage": "published" if index == served_number else "copywriting", "publishedAt": published_at if index == served_number else None,
        }
        client.tables.setdefault("Item", {})[row_id] = row
        previous = row
    served_id = LINEAGE if served_number == 1 else f"{LINEAGE}-v{served_number}"
    client.tables.setdefault("PublishedItem", {})["published-" + LINEAGE] = {
        "id": "published-" + LINEAGE, "sourceItemId": served_id, "itemLineageId": LINEAGE, "versionNumber": served_number, "type": "article", "status": "published",
        "slug": "dated", "section": "articles", "title": "Dated", "publishedAt": published_at,
    }
    assert previous is not None


@given("a Story whose versions recorded publishes on 4 November and 11 November 2026, now showing 11 November as published")
def _republished(context) -> None:
    context.client = FakeAuthoringClient()
    old_style_story(context.client, [
        {"at": iso(4, "November", 2026, 15, 2), "reason": "publish", "by": "Pat"},
        {"at": iso(11, "November", 2026, 9, 40), "reason": "publish", "by": "Sam"},
    ], served_number=2, published_at=iso(11, "November", 2026, 9, 40))
    context.old = {key: dict(value) for key, value in context.client.tables["Item"].items()}


@given("a Story imported with the date 1 January 2026 whose only recorded publish was 2 November 2026")
def _imported(context) -> None:
    context.client = FakeAuthoringClient()
    old_style_story(context.client, [{"at": iso(2, "November", 2026), "reason": "publish", "by": "importer"}], served_number=1, published_at=iso(1, "January", 2026))
    context.old = {key: dict(value) for key, value in context.client.tables["Item"].items()}


@given("a Story with a version that was taken down and a later version published on 8 November 2026")
def _taken_down(context) -> None:
    context.client = FakeAuthoringClient()
    old_style_story(context.client, [
        {"at": iso(6, "November", 2026), "reason": "unpublish", "by": "Sam"},
        {"at": iso(8, "November", 2026), "reason": "publish", "by": "Sam"},
    ], served_number=2, published_at=iso(8, "November", 2026))
    context.old = {key: dict(value) for key, value in context.client.tables["Item"].items()}


@given("a Story that shows as published but whose versions recorded no publish")
def _no_evidence(context) -> None:
    context.client = FakeAuthoringClient()
    old_style_story(context.client, [{"at": iso(3, "November", 2026), "reason": "edited"}], served_number=1, published_at=iso(3, "November", 2026))
    context.old = {key: dict(value) for key, value in context.client.tables["Item"].items()}


def run_backfill(context, apply: bool) -> None:
    context.client.calls.clear()
    context.report = []
    context.plan = run_backfill_published_dates(context.client, apply=apply, rate=25, sleep=lambda _s: None, echo=context.report.append)


@given("an operator has run the published dates backfill with --apply")
@when("an operator runs the published dates backfill with --apply")
def _apply(context) -> None:
    run_backfill(context, True)


@when("an operator runs the published dates backfill without --apply")
def _dry(context) -> None:
    run_backfill(context, False)


@then("the Story's published time is {day:d} {month} {year:d}")
def _first_is(context, day, month, year) -> None:
    prefix = f"{year:04d}-{MONTHS[month]:02d}-{day:02d}"
    assert published_row(context.client)["publishedAt"].startswith(prefix), published_row(context.client)
    assert newest(context.client)["publishedAt"].startswith(prefix), newest(context.client)


@then("its served version's published time is 11 November 2026")
def _served_is(context) -> None:
    wanted = iso(11, "November", 2026, 9, 40)
    assert published_row(context.client)["versionPublishedAt"] == wanted
    assert newest(context.client)["versionPublishedAt"] == wanted


@then("the served version's publisher is the person the publish recorded")
def _publisher(context) -> None:
    assert published_row(context.client)["versionPublishedBy"] == "Sam"
    assert newest(context.client)["versionPublishedBy"] == "Sam"


@then("the report says what it would write")
def _would_write(context) -> None:
    assert any("would write" in line and "publishedAt=" in line for line in context.report), context.report
    assert context.report[-1].endswith("dry run\tstories 1\trows to write 2\talready right 0\tunclear 0"), context.report[-1]


@then("every version row written still carries its own last changed time")
def _updated_at(context) -> None:
    item_updates = [payload for model, payload in context.client.updates if model == "Item"]
    assert item_updates
    for payload in item_updates:
        assert payload["updatedAt"] == context.old[payload["id"]]["updatedAt"], payload


@then("the report lists the Story as unclear because {reason}")
def _unclear(context, reason: str) -> None:
    expected = {"a take-down overwrote a publish time": "taken down", "no version recorded a publish": "no version recorded a publish"}[reason]
    lines = [line for line in context.report if "\tunclear\t" in line]
    assert len(lines) == 1 and expected in lines[0] and LINEAGE in lines[0], context.report


@then("the Story's published time is not changed")
def _unchanged(context) -> None:
    assert published_row(context.client)["publishedAt"] == context.old[newest(context.client)["id"]]["publishedAt"]
    assert newest(context.client)["publishedAt"] == context.old[newest(context.client)["id"]]["publishedAt"]
