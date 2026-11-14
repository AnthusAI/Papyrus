"""Publishing prunes the lineage's superseded picture rows, including rows no tenant ever stamped (the Machines on Machines publish failure)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.publishing import ItemFields, publish_item, published_item_id_for, save_item, unpublish_item  # noqa: E402
from papyrus_content.tenancy import TenantError  # noqa: E402
from procedures.newsroom.tests.test_tenancy import NOW, InMemoryGraphQLBackend, publish_article, tenant_client  # noqa: E402

ITEM_ID = "item-articles-copy"


def stale_row(row_id: str, lineage: str = ITEM_ID, tenant: str | None = None) -> dict:
    return {"id": row_id, "publishedItemId": published_item_id_for(lineage), "itemLineageId": lineage, "sourceItemId": f"{lineage}-v1",
            "sortKey": "001#a.png", "storagePath": "media/a.png", "type": "image", **({"tenantId": tenant} if tenant else {})}


def seeded(rows: list[dict]):
    backend = InMemoryGraphQLBackend()
    client = tenant_client(backend, "alpha")
    publish_article(client, "copy")
    for row in rows:
        backend.tables.setdefault("PublishedMediaAsset", {})[row["id"]] = row
    return backend, client


def test_a_row_with_no_tenant_stamp_is_pruned_when_the_lineage_is_republished():
    backend, client = seeded([stale_row("published-media-unstamped")])
    save_item(client, ItemFields(type="article", slug="copy", section="articles", front_matter_yaml="title: Copy two\n", body_markus="New body.\n",
                                 aliases=[], id=ITEM_ID), actor="test", now=NOW)
    result = publish_item(client, ITEM_ID, actor="test", now="2026-10-18T13:00:00Z")
    assert result.deleted_media_ids == ["published-media-unstamped"]
    assert "published-media-unstamped" not in backend.tables["PublishedMediaAsset"]


def test_unpublishing_removes_a_row_with_no_tenant_stamp():
    backend, client = seeded([stale_row("published-media-unstamped")])
    unpublish_item(client, ITEM_ID, actor="test", now=NOW)
    assert not backend.tables["PublishedMediaAsset"]


def test_a_row_that_is_already_gone_is_the_state_delete_wanted():
    _, client = seeded([])
    assert client.delete_lineage_row("PublishedMediaAsset", "published-media-gone", ITEM_ID) is False


def test_a_stamped_row_of_the_lineage_is_deleted():
    backend, client = seeded([stale_row("published-media-own", tenant="alpha")])
    assert client.delete_lineage_row("PublishedMediaAsset", "published-media-own", ITEM_ID) is True
    assert "published-media-own" not in backend.tables["PublishedMediaAsset"]


def test_a_row_of_another_tenant_is_refused_and_kept():
    backend, client = seeded([stale_row("published-media-beta", tenant="beta")])
    with pytest.raises(TenantError, match="tenant beta"):
        client.delete_lineage_row("PublishedMediaAsset", "published-media-beta", ITEM_ID)
    assert "published-media-beta" in backend.tables["PublishedMediaAsset"]


def test_a_row_of_another_lineage_is_refused_and_kept():
    backend, client = seeded([stale_row("published-media-other", lineage="item-articles-other")])
    with pytest.raises(TenantError, match="lineage item-articles-other"):
        client.delete_lineage_row("PublishedMediaAsset", "published-media-other", ITEM_ID)
    assert "published-media-other" in backend.tables["PublishedMediaAsset"]
