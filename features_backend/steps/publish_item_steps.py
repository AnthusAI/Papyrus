from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.publishing import ItemFields, PublishError, publish_item, save_item, unpublish_item  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

ITEM_ID = "item-articles-hello"
NOW = "2026-10-05T12:00:00Z"


def article_fields(body: str = "Hello world.\n") -> ItemFields:
    return ItemFields(
        type="article",
        slug="hello",
        section="articles",
        front_matter_yaml="title: Hello\n",
        body_markus=body,
        aliases=[],
        id=ITEM_ID,
    )


@given("a saved draft article")
def saved_draft(context) -> None:
    context.client = FakeAuthoringClient()
    save_item(context.client, article_fields(), actor="behave", now=NOW)


@given("I publish the item")
@when("I publish the item")
def publish(context) -> None:
    context.result = publish_item(context.client, ITEM_ID, actor="behave", now=NOW)


@when("I publish the item again")
def publish_again(context) -> None:
    context.client.calls.clear()
    context.result = publish_item(context.client, ITEM_ID, actor="behave", now=NOW)


@when("I unpublish the item")
def unpublish(context) -> None:
    context.result = unpublish_item(context.client, ITEM_ID, actor="behave", now=NOW)


@when('I try to save an article using the directive "{name}"')
def save_invalid(context, name: str) -> None:
    context.client = FakeAuthoringClient()
    context.error = None
    try:
        save_item(context.client, article_fields(f":::{name}\nText.\n:::\n"), actor="behave", now=NOW)
    except PublishError as error:
        context.error = error


@then("the published item exists with version {version:d}")
def published_exists(context, version: int) -> None:
    row = context.client.tables["PublishedItem"]["published-" + ITEM_ID]
    assert row["versionNumber"] == version, row


@then("no published item exists")
def no_published(context) -> None:
    assert not context.client.tables.get("PublishedItem"), context.client.tables.get("PublishedItem")


@then('the item status is "{status}"')
def item_status(context, status: str) -> None:
    assert context.client.tables["Item"][ITEM_ID]["status"] == status


@then("the publish reports no change")
def reports_no_change(context) -> None:
    assert context.result.changed is False


@then("no records were written")
def nothing_written(context) -> None:
    assert context.client.write_calls() == [], context.client.write_calls()


@then('saving fails with code "{code}"')
def saving_fails(context, code: str) -> None:
    assert context.error is not None and context.error.code == code, context.error
