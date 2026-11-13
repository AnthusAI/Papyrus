from __future__ import annotations

import copy
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.backend_copy import (  # noqa: E402
    FieldSpec,
    ModelSchema,
    ObjectInfo,
    apply_plan,
    build_plan,
    tenant_media_source_store,
)
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient  # noqa: E402
from papyrus_content.publishing import ItemFields, publish_item, save_item  # noqa: E402
from papyrus_content.tenancy import (  # noqa: E402
    TENANT_LISTING_QUERIES,
    TenantError,
    tenant_media_path,
    tenant_scoped_index,
    tenant_scoped_value,
    tenant_stamped_payload,
    validate_tenant_id,
)

NOW = "2026-10-18T12:00:00Z"
ENDPOINT = "https://example.invalid/graphql"


class InMemoryGraphQLBackend:
    """AppSync over DynamoDB, in memory. ``rows_read`` counts the rows each read touches the way DynamoDB bills them: a whole-table list
    (``listPublishedItems``, a Scan) reads every row of the table, an index query only the rows of its partition. A read it does not know fails."""

    def __init__(self) -> None:
        self.tables: dict[str, dict[str, dict]] = {}
        self.queries: list[tuple[str, dict]] = []
        self.rows_read = 0

    def __call__(self, query: str, variables: dict | None = None) -> dict:
        variables = variables or {}
        self.queries.append((query, variables))
        mutation = re.search(r"\b(create|update|delete)([A-Z]\w+)\(input", query)
        if mutation:
            return self._mutate(mutation.group(1), mutation.group(2), variables["input"])
        field = re.search(r"\{\s*(\w+)\(", query).group(1)
        return {field: self._read(field, variables)}

    def _mutate(self, action: str, model: str, payload: dict) -> dict:
        table = self.tables.setdefault(model, {})
        if action == "create":
            if payload["id"] in table:
                raise RuntimeError("ConditionalCheckFailedException")
            table[payload["id"]] = copy.deepcopy(payload)
        elif action == "update":
            table[payload["id"]].update(copy.deepcopy(payload))
        else:
            table.pop(payload["id"], None)
        return {f"{action}{model}": {"id": payload["id"]}}

    def _read(self, field: str, variables: dict):
        if field.startswith("get"):
            return copy.deepcopy(self.tables.get(field[3:], {}).get(variables["id"]))
        tenant_listing = {query: model for model, query in TENANT_LISTING_QUERIES.items()}
        if field in tenant_listing:   # the tenantId index: the tenant's partition, sorted by id, one page per request
            partition = sorted((row for row in self.tables.get(tenant_listing[field], {}).values() if row.get("tenantId") == variables["tenantId"]),
                               key=lambda row: row["id"])
            start = int(variables.get("nextToken") or 0)
            page = partition[start:start + variables["limit"]]
            self.rows_read += len(page)
            more = start + len(page) < len(partition)
            return {"items": copy.deepcopy(page), "nextToken": str(start + len(page)) if more else None}
        if field == "itemByTenantSlug":
            rows = [row for row in self.tables.get("Item", {}).values() if row.get("tenantSlug") == variables["tenantSlug"]]
        elif field == "listPublishedItemsByTypeStatusAndPublishedAt":
            rows = [
                row for row in self.tables.get("PublishedItem", {}).values()
                if row.get("typeStatus") == variables["typeStatus"]
            ]
        elif field == "listMediaAssetsByItemAndSortKey":
            rows = [row for row in self.tables.get("MediaAsset", {}).values() if row.get("itemId") == variables["itemId"]]
        elif field == "listPublishedMediaAssetsByItemAndSortKey":
            rows = [
                row for row in self.tables.get("PublishedMediaAsset", {}).values()
                if row.get("publishedItemId") == variables["publishedItemId"]
            ]
        elif field == "listItemsByLineageAndVersion":
            rows = [row for row in self.tables.get("Item", {}).values() if row.get("lineageId") == variables["lineageId"]]
        elif field == "listPublishedItems":
            rows = list(self.tables.get("PublishedItem", {}).values())
        else:
            raise AssertionError(f"unexpected field {field}")
        self.rows_read += len(rows)
        return {"items": copy.deepcopy(rows), "nextToken": None}


def tenant_client(backend: InMemoryGraphQLBackend, tenant_id: str | None) -> PapyrusGraphQLAuthoringClient:
    client = PapyrusGraphQLAuthoringClient(endpoint=ENDPOINT, header_factory=lambda payload: {}, tenant_id=tenant_id)
    client.graphql = backend
    return client


def publish_article(client, slug: str) -> str:
    item_id = f"item-articles-{slug}"
    save_item(
        client,
        ItemFields(
            type="article",
            slug=slug,
            section="articles",
            front_matter_yaml=f"title: {slug.title()}\n",
            body_markus="Body text.\n",
            aliases=[],
            id=item_id,
        ),
        actor="test",
        now=NOW,
    )
    publish_item(client, item_id, actor="test", now=NOW)
    return item_id


class TenantKeyTests(unittest.TestCase):
    def test_values_are_prefixed_once(self):
        self.assertEqual(tenant_scoped_value("pilobol-us", "article#published"), "pilobol-us#article#published")
        self.assertEqual(tenant_scoped_value("pilobol-us", "pilobol-us#article#published"), "pilobol-us#article#published")
        self.assertEqual(tenant_scoped_value(None, "article#published"), "article#published")

    def test_tenant_ids_are_validated(self):
        self.assertEqual(validate_tenant_id("p-apyr-us"), "p-apyr-us")
        for bad in ("", "Has Caps", "has#hash", "-leading"):
            with self.assertRaises(TenantError):
                validate_tenant_id(bad)

    def test_stamping_covers_tenant_models_only(self):
        item = tenant_stamped_payload(
            "Item", "pilobol-us", {"id": "a", "slug": "hello", "typeStatus": "article#draft", "sectionStatus": "news#draft"}
        )
        self.assertEqual(
            item,
            {
                "id": "a",
                "slug": "hello",
                "tenantId": "pilobol-us",
                "tenantSlug": "pilobol-us#hello",
                "typeStatus": "pilobol-us#article#draft",
                "sectionStatus": "pilobol-us#news#draft",
            },
        )
        self.assertEqual(tenant_stamped_payload("Reference", "pilobol-us", {"id": "r"}), {"id": "r"})
        self.assertEqual(tenant_stamped_payload("Item", None, {"id": "a"}), {"id": "a"})

    def test_partial_updates_only_touch_the_fields_they_carry(self):
        update = tenant_stamped_payload("Item", "pilobol-us", {"id": "a", "typeStatus": "article#published"})
        self.assertEqual(update, {"id": "a", "tenantId": "pilobol-us", "typeStatus": "pilobol-us#article#published"})

    def test_media_paths_move_under_the_tenant(self):
        self.assertEqual(tenant_media_path("pilobol-us", "media/a/b.png"), "media/pilobol-us/a/b.png")
        self.assertEqual(tenant_media_path("pilobol-us", "media/pilobol-us/a/b.png"), "media/pilobol-us/a/b.png")
        self.assertEqual(tenant_media_path("pilobol-us", "https://elsewhere/x.png"), "https://elsewhere/x.png")

    def test_slug_index_is_redirected_for_a_tenant(self):
        self.assertEqual(tenant_scoped_index("pilobol-us", "itemBySlug", "hello"), ("itemByTenantSlug", "pilobol-us#hello"))
        self.assertEqual(tenant_scoped_index(None, "itemBySlug", "hello"), ("itemBySlug", "hello"))
        self.assertEqual(
            tenant_scoped_index("pilobol-us", "mediaAssetsByItemAndSortKey", "item-1"),
            ("mediaAssetsByItemAndSortKey", "item-1"),
        )


class TenantClientTests(unittest.TestCase):
    def setUp(self):
        self.backend = InMemoryGraphQLBackend()
        self.papyrus = tenant_client(self.backend, "p-apyr-us")
        self.pilobolus = tenant_client(self.backend, "pilobol-us")

    def test_publishing_stamps_items_and_published_items(self):
        item_id = publish_article(self.pilobolus, "hello")
        item = self.backend.tables["Item"][item_id]
        published = next(iter(self.backend.tables["PublishedItem"].values()))
        for row in (item, published):
            self.assertEqual(row["tenantId"], "pilobol-us")
            self.assertEqual(row["tenantSlug"], "pilobol-us#hello")
            self.assertEqual(row["typeStatus"], "pilobol-us#article#published")
            self.assertEqual(row["sectionStatus"], "pilobol-us#articles#published")

    def test_each_tenant_lists_only_its_own_published_articles(self):
        publish_article(self.papyrus, "shared-slug")
        publish_article(self.pilobolus, "pilobolus-only")
        self.assertEqual([row["slug"] for row in self.papyrus.list_published_articles()], ["shared-slug"])
        self.assertEqual([row["slug"] for row in self.pilobolus.list_published_articles()], ["pilobolus-only"])

    def test_record_listing_is_filtered_by_tenant(self):
        publish_article(self.papyrus, "one")
        publish_article(self.pilobolus, "two")
        self.assertEqual([row["slug"] for row in self.papyrus.list_records("PublishedItem")], ["one"])
        self.assertEqual([row["slug"] for row in self.pilobolus.list_records("PublishedItem")], ["two"])
        self.assertEqual([row["slug"] for row in self.pilobolus.list_published_item_summaries()], ["two"])

    def test_a_tenant_cannot_read_another_tenants_row_by_id(self):
        item_id = publish_article(self.papyrus, "private-to-papyrus")
        self.assertIsNotNone(self.papyrus.get_record("Item", item_id))
        self.assertIsNone(self.pilobolus.get_record("Item", item_id))

    def test_a_tenant_cannot_update_or_delete_another_tenants_row(self):
        item_id = publish_article(self.papyrus, "private-to-papyrus")
        with self.assertRaises(TenantError):
            self.pilobolus.update_record("Item", {"id": item_id, "title": "taken over"})
        with self.assertRaises(TenantError):
            self.pilobolus.delete_record("Item", item_id)
        self.assertNotEqual(self.backend.tables["Item"][item_id].get("title"), "taken over")
        self.assertEqual(self.backend.tables["Item"][item_id]["tenantId"], "p-apyr-us")

    def test_an_id_that_exists_in_another_tenant_is_not_overwritten(self):
        item_id = publish_article(self.papyrus, "same-slug")
        with self.assertRaises(RuntimeError):
            publish_article(self.pilobolus, "same-slug")
        self.assertEqual(self.backend.tables["Item"][item_id]["tenantId"], "p-apyr-us")

    def test_slug_lookup_is_per_tenant(self):
        publish_article(self.papyrus, "about")
        self.assertEqual(len(self.papyrus.list_by_index("itemBySlug", "about")), 1)
        self.assertEqual(self.pilobolus.list_by_index("itemBySlug", "about"), [])

    def test_a_client_without_a_tenant_writes_nothing_tenant_shaped(self):
        plain = tenant_client(self.backend, None)
        item_id = publish_article(plain, "plain")
        self.assertNotIn("tenantId", self.backend.tables["Item"][item_id])
        self.assertEqual(self.backend.tables["Item"][item_id]["typeStatus"], "article#published")


def field(name: str, type_name: str = "String") -> FieldSpec:
    return FieldSpec(name, type_name)


ITEM_SOURCE_FIELDS = {name: field(name) for name in ("id", "slug", "type", "typeStatus", "sectionStatus")}
MEDIA_SOURCE_FIELDS = {name: field(name) for name in ("id", "itemId", "storagePath")}
TENANT_FIELDS = {name: field(name) for name in ("tenantId", "tenantSlug")}


SCHEMA_SOURCES = [REPO_ROOT / "amplify" / "data" / "schema.ts", *sorted((REPO_ROOT / "amplify").glob("plugins/*/schema.ts")),
                  *sorted((REPO_ROOT / "amplify").glob("functions/*/schema.ts"))]
TENANT_INDEX = re.compile(r'index\("tenantId"\)(?:\.\w+\([^()]*\))*?\.queryField\("(\w+)"\)')


def seed_reader_votes(backend: InMemoryGraphQLBackend, tenant_id: str, count: int) -> None:
    table = backend.tables.setdefault("ReaderVote", {})
    for number in range(count):
        vote_id = f"item:{tenant_id}-story-{number}#reader-{number}#quality"
        table[vote_id] = {"id": vote_id, "tenantId": tenant_id, "subjectKey": f"item:{tenant_id}-story-{number}", "readerId": f"reader-{number}",
                          "dimension": "quality", "value": 1, "voterRole": "reader"}


class TenantListingTests(unittest.TestCase):
    """``list_tenant_rows`` reads one tenant's rows through the model's tenantId index (PPY-1ce06f)."""

    def test_it_queries_the_tenant_index_page_by_page_and_never_scans(self):
        backend = InMemoryGraphQLBackend()
        for tenant, count in (("alpha", 7), ("beta", 5), ("gamma", 3)):
            seed_reader_votes(backend, tenant, count)
        rows = tenant_client(backend, "alpha").list_tenant_rows("ReaderVote", "id tenantId subjectKey", page_size=3)
        self.assertEqual(len(rows), 7)
        self.assertEqual({row["tenantId"] for row in rows}, {"alpha"})
        fields = [re.search(r"\{\s*(\w+)\(", query).group(1) for query, _ in backend.queries]
        self.assertEqual(fields, ["listReaderVotesByTenant"] * 3)   # 7 rows in pages of 3: three requests of one Query
        self.assertNotIn("listReaderVotes", fields)
        self.assertEqual({variables["tenantId"] for _, variables in backend.queries}, {"alpha"})
        self.assertEqual(backend.rows_read, 7)

    def test_it_needs_a_tenant_and_a_model_with_a_tenant_index(self):
        backend = InMemoryGraphQLBackend()
        with self.assertRaises(TenantError):
            tenant_client(backend, None).list_tenant_rows("ReaderVote", "id")
        with self.assertRaises(TenantError):
            tenant_client(backend, "alpha").list_tenant_rows("Reference", "id")
        self.assertEqual(backend.queries, [])

    def test_the_listing_map_names_every_tenant_index_of_the_schema(self):
        declared = {match for path in SCHEMA_SOURCES for match in TENANT_INDEX.findall(path.read_text())}
        self.assertEqual(set(TENANT_LISTING_QUERIES.values()), declared)


class InMemoryRowBackend:
    def __init__(self, tables: dict[str, list[dict]], schemas: dict[str, dict]) -> None:
        self.tables = copy.deepcopy(tables)
        self.schemas = schemas
        self.created: list[tuple[str, dict]] = []

    def model_names(self) -> list[str]:
        return sorted(self.schemas)

    def schema(self, model: str) -> ModelSchema:
        return ModelSchema(model, ("id",), self.schemas[model], self.schemas[model])

    def iterate_rows(self, model: str, field_names: list[str]):
        for row in self.tables.get(model, []):
            yield {name: row.get(name) for name in field_names}

    def create_row(self, model: str, row: dict) -> None:
        self.created.append((model, row))
        self.tables.setdefault(model, []).append(copy.deepcopy(row))

    def update_row(self, model: str, row: dict) -> None:
        raise AssertionError("no updates expected")


class InMemoryObjectStore:
    def __init__(self, objects: dict[str, tuple[int, str]]) -> None:
        self.objects = dict(objects)
        self.bucket = "bucket"
        self.client = object()

    def list_objects(self) -> list[ObjectInfo]:
        return [ObjectInfo(key, size, etag) for key, (size, etag) in sorted(self.objects.items())]

    def copy_object_from(self, source_store, key: str) -> None:
        original = source_store.original_key(key) if hasattr(source_store, "original_key") else key
        self.objects[key] = source_store.inner.objects[original] if hasattr(source_store, "inner") else source_store.objects[key]


def single_tenant_source() -> InMemoryRowBackend:
    return InMemoryRowBackend(
        {
            "Item": [{"id": "item-1", "slug": "hello", "type": "article", "typeStatus": "article#published", "sectionStatus": "news#published"}],
            "MediaAsset": [{"id": "media-1", "itemId": "item-1", "storagePath": "media/figure.png"}],
        },
        {"Item": ITEM_SOURCE_FIELDS, "MediaAsset": MEDIA_SOURCE_FIELDS},
    )


def multi_tenant_target(tables: dict | None = None) -> InMemoryRowBackend:
    return InMemoryRowBackend(
        tables or {},
        {
            "Item": {**ITEM_SOURCE_FIELDS, **TENANT_FIELDS},
            "MediaAsset": {**MEDIA_SOURCE_FIELDS, "tenantId": field("tenantId")},
        },
    )


class StampedCopyTests(unittest.TestCase):
    def plan_and_apply(self, target, source_store=None, target_store=None):
        source = single_tenant_source()
        selected_source_store = tenant_media_source_store(source_store, "pilobol-us") if source_store else None
        plan = build_plan(
            source,
            target,
            requested_models=["Item", "MediaAsset"],
            source_store=selected_source_store,
            target_store=target_store,
            selected_prefixes=["media/"],
            tenant_id="pilobol-us",
        )
        return plan

    def test_rows_are_stamped_for_the_tenant(self):
        target = multi_tenant_target()
        plan = self.plan_and_apply(target)
        self.assertTrue(plan.ok, plan.to_dict())
        apply_plan(plan, target, None, None)
        item = target.tables["Item"][0]
        self.assertEqual(item["tenantId"], "pilobol-us")
        self.assertEqual(item["tenantSlug"], "pilobol-us#hello")
        self.assertEqual(item["typeStatus"], "pilobol-us#article#published")
        self.assertEqual(item["sectionStatus"], "pilobol-us#news#published")
        media = target.tables["MediaAsset"][0]
        self.assertEqual(media["tenantId"], "pilobol-us")
        self.assertEqual(media["storagePath"], "media/pilobol-us/figure.png")

    def test_applying_twice_changes_nothing_the_second_time(self):
        target = multi_tenant_target()
        apply_plan(self.plan_and_apply(target), target, None, None)
        written_before = len(target.created)
        second = self.plan_and_apply(target)
        self.assertTrue(second.ok)
        self.assertTrue(all(not plan.created and not plan.updated for plan in second.models if plan.selected))
        self.assertEqual(len(target.created), written_before)

    def test_an_id_owned_by_another_tenant_blocks_the_whole_apply(self):
        target = multi_tenant_target(
            {"Item": [{"id": "item-1", "slug": "hello", "type": "article", "tenantId": "p-apyr-us"}]}
        )
        plan = self.plan_and_apply(target)
        self.assertFalse(plan.ok)
        self.assertIn("tenant p-apyr-us", plan.model("Item").invalid[0]["problems"][0])

    def test_an_unstamped_target_row_with_the_same_id_also_blocks(self):
        target = multi_tenant_target({"Item": [{"id": "item-1", "slug": "hello", "type": "article"}]})
        self.assertFalse(self.plan_and_apply(target).ok)

    def test_a_target_without_the_tenant_schema_is_a_plan_error(self):
        target = InMemoryRowBackend({}, {"Item": ITEM_SOURCE_FIELDS, "MediaAsset": MEDIA_SOURCE_FIELDS})
        plan = self.plan_and_apply(target)
        self.assertFalse(plan.ok)
        self.assertIn("tenantId", plan.model("Item").errors[0])

    def test_media_objects_are_copied_under_the_tenant_prefix(self):
        source_store = InMemoryObjectStore(
            {"media/figure.png": (10, "etag-1"), "corpora/steering.yml": (5, "etag-2")}
        )
        target_store = InMemoryObjectStore({})
        target = multi_tenant_target()
        plan = self.plan_and_apply(target, source_store, target_store)
        wrapped_source = tenant_media_source_store(source_store, "pilobol-us")
        apply_plan(plan, target, wrapped_source, target_store)
        self.assertEqual(sorted(target_store.objects), ["media/pilobol-us/figure.png"])
        self.assertEqual(plan.prefixes[0].to_copy_missing, ["media/pilobol-us/figure.png"])


if __name__ == "__main__":
    unittest.main()
