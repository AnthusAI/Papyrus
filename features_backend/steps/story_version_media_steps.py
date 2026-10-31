"""Saving a new story version keeps its images (features_backend/story-version-media.feature). The backend is the in-memory fake."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.publishing import ItemFields, PublishError, publish_item, save_item  # noqa: E402
from papyrus_content.story_reporting import save_story_version  # noqa: E402
from fake_client import FakeAuthoringClient  # noqa: E402
from test_story_versioning import LINEAGE, NOW, add_media, media_of  # noqa: E402

FRONT = "title: Hello\n"


def body(src: str | None, n: int) -> str:
    return f"Version {n}.\n" + (f'\n::image{{src="{src}" alt="A chart"}}\n' if src else "")


def save(context, src: str | None, n: int) -> None:
    record = save_story_version(context.client, LINEAGE, front_matter_yaml=FRONT, body_markus=body(src, n),
                                actor="t", change_reason="edit", now=f"2026-10-05T12:0{n}:00Z")
    context.versions[n] = record["id"]


def first_version(context, src: str, with_media: bool) -> None:
    context.client = FakeAuthoringClient()
    context.versions = {1: f"{LINEAGE}-v1"}
    context.src = src
    save_item(context.client, ItemFields(type="article", slug="hello", section="articles", front_matter_yaml=FRONT,
                                         body_markus=body(src, 1), aliases=[], id=f"{LINEAGE}-v1"), actor="t", now=NOW)
    context.client.update_record("Item", {"id": f"{LINEAGE}-v1", "lineageId": LINEAGE, "versionNumber": 1, "versionState": "current"})
    if with_media:
        add_media(context.client, f"{LINEAGE}-v1", src)


@given('a story whose first version uses the image "{src}" with a media row')
def step_with_media(context, src):
    first_version(context, src, True)


@given('a story whose first version uses the image "{src}" without a media row')
def step_without_media(context, src):
    first_version(context, src, False)


@given("the editor saves a second version that drops the image")
def step_drop(context):
    save(context, None, 2)


@when("the editor saves a second version that still uses the image")
def step_second(context):
    save(context, context.src, 2)


@when("the editor saves a third version that uses the image again")
def step_third(context):
    save(context, context.src, 3)


def version_id(context, number: int) -> str:
    return context.versions[number]


@then('the second version has a media row for "{src}"')
def step_second_has(context, src):
    assert [row["itemId"] for row in media_of(context.client, version_id(context, 2))] == [version_id(context, 2)]


@then('the third version has a media row for "{src}"')
def step_third_has(context, src):
    assert [row["itemId"] for row in media_of(context.client, version_id(context, 3))] == [version_id(context, 3)]


@then("the second version can be published")
def step_second_publish(context):
    assert publish_item(context.client, version_id(context, 2), actor="t", now=NOW).changed


@then("the third version can be published")
def step_third_publish(context):
    assert publish_item(context.client, version_id(context, 3), actor="t", now=NOW).changed


@then("the second version has no media rows")
def step_second_none(context):
    assert media_of(context.client, version_id(context, 2)) == []


@then("publishing the second version reports the image as missing")
def step_second_missing(context):
    try:
        publish_item(context.client, version_id(context, 2), actor="t", now=NOW)
    except PublishError as error:
        assert error.code == "image-missing", error.code
    else:
        raise AssertionError("publish should have failed")
