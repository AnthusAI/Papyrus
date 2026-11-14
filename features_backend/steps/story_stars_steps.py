"""A Story keeps its star rating through every new version, and the rating is never published (features_backend/story-stars.feature)."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.copywriting import _draft_item_for_copywriting  # noqa: E402
from papyrus_content.graphql_authoring import ITEM_FIELDS, LIST_DEFINITIONS, NEWER_REFERENCE_FIELDS, _NEWER_FIELD_SELECTION  # noqa: E402
from papyrus_content.item_stars import ITEM_STAR_FIELDS, assert_no_item_stars  # noqa: E402
from papyrus_content.publishing import ItemFields, project_item_to_published, publish_item, save_item, unpublish_item  # noqa: E402
from papyrus_content.story_reporting import move_story_stage, save_story_version  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

LINEAGE = "item-articles-rated"
ITEM_ID = LINEAGE
NOW = "2026-11-03T12:00:00Z"
RATED_AT = "2026-11-03T11:00:00Z"
RATED_BY = "an editor"


def fields(body: str = "Hello world.\n") -> ItemFields:
    return ItemFields(type="article", slug="rated", section="articles", front_matter_yaml="title: Rated\n", body_markus=body, aliases=[], id=ITEM_ID)


def rate(client, stars: int | None) -> None:
    update = {"id": ITEM_ID, "starRating": stars, "starRatedAt": RATED_AT if stars else None, "starRatedBy": RATED_BY if stars else None}
    client.update_record("Item", update)


def versions(client) -> list[dict]:
    return sorted((row for row in client.tables["Item"].values() if row.get("lineageId") == LINEAGE), key=lambda row: row["versionNumber"])


def newest(client) -> dict:
    return versions(client)[-1]


def has_stars(row: dict, stars: int) -> bool:
    return row.get("starRating") == stars and row.get("starRatedAt") == RATED_AT and row.get("starRatedBy") == RATED_BY


@given("a Story rated {stars:d} stars")
def _rated(context, stars: int) -> None:
    context.client = FakeAuthoringClient()
    save_item(context.client, fields(), actor="behave", now=NOW)
    rate(context.client, stars)


@given("a Story nobody rated")
def _unrated(context) -> None:
    context.client = FakeAuthoringClient()
    save_item(context.client, fields(), actor="behave", now=NOW)


@given("the Story is published")
def _published(context) -> None:
    publish_item(context.client, ITEM_ID, actor="behave", now=NOW)


@when("an editor saves a new version of the Story")
def _new_version(context) -> None:
    save_story_version(context.client, LINEAGE, front_matter_yaml="title: Rated again\n", body_markus="Changed.\n", actor="behave", change_reason="edited", now=NOW)


@when("an editor saves the draft in place")
def _in_place(context) -> None:
    save_item(context.client, fields("Changed in place.\n"), actor="behave", now=NOW)


@when("a copywriting run drafts the next version of the Story")
def _copywriting(context) -> None:
    context.drafted = _draft_item_for_copywriting(
        assignment={"id": "assignment-1", "itemLineageId": LINEAGE, "title": "Rated", "sectionKey": "articles"},
        metadata={}, packet={"recommendedAngle": "A new angle", "summary": "Why it matters."}, target_item_type="article",
        existing_items=list(context.client.tables["Item"].values()), actor_label="behave", now=NOW,
    )


@when('the Story is moved to the "{stage}" stage')
def _moved(context, stage: str) -> None:
    move_story_stage(context.client, LINEAGE, stage, actor="behave", now=NOW)


@when("the Story is published")
def _publish_now(context) -> None:
    publish_item(context.client, ITEM_ID, actor="behave", now=NOW)


@when("the Story is unpublished")
def _unpublish(context) -> None:
    unpublish_item(context.client, ITEM_ID, actor="behave", now=NOW)


@when("an editor changes the rating to {stars:d} stars")
def _change(context, stars: int) -> None:
    context.writes_before = len(context.client.write_calls())
    rate(context.client, stars)
    context.rated_calls = context.client.write_calls()[context.writes_before:]


@when("a published row is built that carries a star rating")
def _leak(context) -> None:
    item = {**newest(context.client), "bodyIr": {"papyrus": {"images": {}}}}
    context.error = None
    try:
        row, _media = project_item_to_published(item, [], published_at=NOW, version_published_at=NOW, version_published_by="behave", version_number=1)
        assert_no_item_stars({**row, "starRating": 4})
    except AssertionError as error:
        context.error = error


@then("the new version has 4 stars from the same editor at the same time")
def _new_has_stars(context) -> None:
    assert has_stars(newest(context.client), 4), newest(context.client)


@then("the draft still has 4 stars from the same editor at the same time")
def _draft_has_stars(context) -> None:
    assert has_stars(context.client.tables["Item"][ITEM_ID], 4), context.client.tables["Item"][ITEM_ID]


@then("the drafted version has 4 stars from the same editor at the same time")
def _drafted_has_stars(context) -> None:
    assert context.drafted["versionNumber"] == 2
    assert has_stars(context.drafted, 4), context.drafted


@then("the new version has no stars")
def _no_stars(context) -> None:
    row = newest(context.client)
    assert row["versionNumber"] == 2 and not any(row.get(name) for name in ITEM_STAR_FIELDS), row


@then("the Story has two versions")
def _two(context) -> None:
    assert len(versions(context.client)) == 2


@then("the Story still has one version")
@then("the Story has one version")
def _one(context) -> None:
    assert len(versions(context.client)) == 1, [row["id"] for row in versions(context.client)]


@then('the Story is at the "{stage}" stage with {stars:d} stars')
def _stage_and_stars(context, stage: str, stars: int) -> None:
    row = context.client.tables["Item"][ITEM_ID]
    assert row["stage"] == stage and has_stars(row, stars), row


@then("the Story still has {stars:d} stars")
def _still(context, stars: int) -> None:
    assert has_stars(context.client.tables["Item"][ITEM_ID], stars), context.client.tables["Item"][ITEM_ID]


@then("the published row has no star field")
def _published_clean(context) -> None:
    published = context.client.tables["PublishedItem"]["published-" + ITEM_ID]
    assert not [name for name in ITEM_STAR_FIELDS if name in published], published


@then("no field of the published row is named like a rating")
def _no_rating_names(context) -> None:
    published = context.client.tables["PublishedItem"]["published-" + ITEM_ID]
    assert not [name for name in published if "star" in name.lower() or "rating" in name.lower() or "rated" in name.lower()], sorted(published)


@then("publishing the Story again changes nothing")
def _republish_noop(context) -> None:
    result = publish_item(context.client, ITEM_ID, actor="behave", now=NOW)
    assert result.changed is False, result
    assert context.client.tables["Item"][ITEM_ID]["starRating"] == 2


@then("it is refused because Story stars are private")
def _refused(context) -> None:
    assert context.error is not None and "private" in str(context.error)


@given("the Story fields the authoring client asks for")
def _asked(context) -> None:
    context.asked = LIST_DEFINITIONS["Item"]["fields"]


@then("they include the three star fields")
def _includes(context) -> None:
    assert all(name in context.asked.split() for name in ITEM_STAR_FIELDS) and all(name in ITEM_FIELDS.split() for name in ITEM_STAR_FIELDS)


@then("a site without them is read without those fields")
def _older_site(context) -> None:
    stripped = _NEWER_FIELD_SELECTION.sub("", "{ id " + context.asked + " }")
    assert not [name for name in ITEM_STAR_FIELDS if name in stripped.split()], stripped
    assert set(ITEM_STAR_FIELDS) <= set(NEWER_REFERENCE_FIELDS)
