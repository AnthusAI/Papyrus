"""Steps for features_backend/publish-prunes-unstamped-media.feature: a tenant client on the in-memory AppSync stand-in the tenancy tests use."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.publishing import ItemFields, publish_item, published_item_id_for, save_item, unpublish_item  # noqa: E402
from papyrus_content.tenancy import TenantError  # noqa: E402
from procedures.newsroom.tests.test_tenancy import InMemoryGraphQLBackend, publish_article, tenant_client  # noqa: E402

ITEM_ID = "item-articles-copy"
OLD_ROW = "published-media-old"
PUBLISHED_AT = "2026-10-18T12:00:00Z"
REPUBLISHED_AT = "2026-10-18T13:00:00Z"


def picture_row(lineage: str = ITEM_ID, tenant: str | None = None) -> dict:
    return {"id": OLD_ROW, "publishedItemId": published_item_id_for(lineage), "itemLineageId": lineage, "sourceItemId": f"{lineage}-v1",
            "sortKey": "001#a.png", "storagePath": "media/a.png", "type": "image", **({"tenantId": tenant} if tenant else {})}


def live_story(context, row: dict | None = None) -> None:
    context.backend = InMemoryGraphQLBackend()
    context.client = tenant_client(context.backend, "alpha")
    publish_article(context.client, "copy")
    if row:
        context.backend.tables.setdefault("PublishedMediaAsset", {})[OLD_ROW] = row


@given("a Story is live")
def story_live(context) -> None:
    live_story(context)


@given("a Story is live and its old picture row was written without a tenant stamp")
def story_live_unstamped(context) -> None:
    live_story(context, picture_row())


@given("a Story is live and a picture row listed under it belongs to another tenant")
def story_live_other_tenant(context) -> None:
    live_story(context, picture_row(tenant="beta"))


@given("a Story is live and a picture row listed under it belongs to another Story")
def story_live_other_story(context) -> None:
    live_story(context, picture_row(lineage="item-articles-other"))


@when("the editor publishes a newer version of the Story")
def publish_newer(context) -> None:
    save_item(context.client, ItemFields(type="article", slug="copy", section="articles", front_matter_yaml="title: Copy two\n",
                                         body_markus="New body.\n", aliases=[], id=ITEM_ID), actor="behave", now=PUBLISHED_AT)
    context.result = publish_item(context.client, ITEM_ID, actor="behave", now=REPUBLISHED_AT)


@when("the editor takes the Story off the site")
def take_off(context) -> None:
    unpublish_item(context.client, ITEM_ID, actor="behave", now=REPUBLISHED_AT)


@when("the publish prunes a picture row that another publish of the Story already deleted")
def prune_gone(context) -> None:
    context.error = None
    context.deleted = context.client.delete_lineage_row("PublishedMediaAsset", OLD_ROW, ITEM_ID)


@when("the publish prunes that row")
def prune_row(context) -> None:
    context.error = None
    try:
        context.client.delete_lineage_row("PublishedMediaAsset", OLD_ROW, ITEM_ID)
    except TenantError as error:
        context.error = error


@then("the newer version is live")
def newer_live(context) -> None:
    assert context.result.changed, context.result


@then("the old picture row is gone")
def old_row_gone(context) -> None:
    assert OLD_ROW not in context.backend.tables.get("PublishedMediaAsset", {})


@then("the Story has no published picture rows")
def no_rows(context) -> None:
    assert not context.backend.tables.get("PublishedMediaAsset"), context.backend.tables.get("PublishedMediaAsset")


@then("the prune reports nothing deleted and no error")
def nothing_deleted(context) -> None:
    assert context.deleted is False and context.error is None


@then("the prune is refused and the row is kept")
def refused_and_kept(context) -> None:
    assert isinstance(context.error, TenantError), context.error
    assert OLD_ROW in context.backend.tables["PublishedMediaAsset"]
