from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.backend_copy import (  # noqa: E402
    DEFAULT_S3_PREFIXES,
    CopyRefused,
    FieldSpec,
    ModelSchema,
    ObjectInfo,
    apply_plan,
    build_plan,
    write_manifests,
)


def spec(name, type_name="String", required=False, is_list=False, enum_values=None):
    return FieldSpec(name, type_name, is_list, required, enum_values)


ITEM_FIELDS = {
    "id": spec("id", "ID"),
    "slug": spec("slug", required=True),
    "type": spec("type", required=True),
    "title": spec("title"),
    "publishedAt": spec("publishedAt", "AWSDateTime"),
    "editorial": spec("editorial", "AWSJSON"),
    "status": spec("status", "ItemStatus", required=True, enum_values=("draft", "published")),
    "createdAt": spec("createdAt", "AWSDateTime"),
}
TARGET_ITEM_FIELDS = {**ITEM_FIELDS, "bodyIr": spec("bodyIr", "AWSJSON")}
SIMPLE_FIELDS = {"id": spec("id", "ID"), "name": spec("name")}


class InMemoryRowBackend:
    def __init__(self, tables: dict[str, list[dict]], schemas: dict[str, tuple[dict, dict]]) -> None:
        self.tables = {name: copy.deepcopy(rows) for name, rows in tables.items()}
        self.schemas = schemas
        self.writes: list[tuple[str, str, dict]] = []
        self.reorder_json_on_read = False

    def model_names(self) -> list[str]:
        return sorted(self.schemas)

    def schema(self, model: str) -> ModelSchema:
        readable, writable = self.schemas[model]
        return ModelSchema(model, ("id",), readable, {k: v for k, v in writable.items() if k != "createdAt"})

    def iterate_rows(self, model: str, field_names: list[str]):
        for row in self.tables.get(model, []):
            projected = {name: row.get(name) for name in field_names}
            if self.reorder_json_on_read:
                for name, value in projected.items():
                    if isinstance(value, str) and value.startswith("{"):
                        projected[name] = json.dumps(dict(reversed(list(json.loads(value).items()))))
            yield projected

    def create_row(self, model: str, row: dict) -> None:
        self.writes.append(("create", model, row))
        self.tables.setdefault(model, []).append(copy.deepcopy(row))

    def update_row(self, model: str, row: dict) -> None:
        self.writes.append(("update", model, row))
        for existing in self.tables[model]:
            if existing["id"] == row["id"]:
                existing.update(row)


class InMemoryObjectStore:
    def __init__(self, objects: dict[str, tuple[int, str]]) -> None:
        self.objects = dict(objects)
        self.copies: list[str] = []

    def list_objects(self) -> list[ObjectInfo]:
        return [ObjectInfo(key, size, etag) for key, (size, etag) in sorted(self.objects.items())]

    def copy_object_from(self, source_store, key: str) -> None:
        self.copies.append(key)
        self.objects[key] = source_store.objects[key]


def item_row(identifier: str, **changes) -> dict:
    row = {
        "id": identifier,
        "slug": identifier,
        "type": "article",
        "title": identifier,
        "publishedAt": "2026-07-04T00:00:00.000Z",
        "editorial": None,
        "status": "published",
        "createdAt": "2026-07-01T00:00:00.000Z",
    }
    row.update(changes)
    return row


def standard_schemas(target_item_fields=None) -> dict:
    return {
        "Item": (ITEM_FIELDS, ITEM_FIELDS),
        "PublishedItem": (ITEM_FIELDS, ITEM_FIELDS),
        "Reference": (SIMPLE_FIELDS, SIMPLE_FIELDS),
        "UserProfile": (SIMPLE_FIELDS, SIMPLE_FIELDS),
    }


def make_target(context, schemas=None, tables=None) -> None:
    context.target = InMemoryRowBackend(tables or {}, schemas or standard_schemas())
    context.target_store = InMemoryObjectStore({})


def run_copy(context, models=None, apply=False):
    prefixes = list(DEFAULT_S3_PREFIXES)
    store_pair = (context.source_store, context.target_store)
    context.refusal = None
    try:
        context.plan = build_plan(
            context.source,
            context.target,
            requested_models=models,
            source_store=store_pair[0],
            target_store=store_pair[1],
            selected_prefixes=prefixes,
        )
        if apply:
            apply_plan(context.plan, context.target, *store_pair)
    except CopyRefused as error:
        context.refusal = str(error)


@given("a source backend with 2 items, 1 published item and 3 references")
def source_with_rows(context) -> None:
    tables = {
        "Item": [item_row("a"), item_row("b")],
        "PublishedItem": [item_row("a")],
        "Reference": [{"id": f"r{n}", "name": f"ref {n}"} for n in range(3)],
        "UserProfile": [{"id": "u1", "name": "person"}],
    }
    context.source = InMemoryRowBackend(tables, standard_schemas())
    context.source_store = InMemoryObjectStore({"media/a.png": (10, "e1")})


@given("a source backend with a videoml item whose editorial JSON has keys in a different order")
def source_with_videoml(context) -> None:
    editorial = json.dumps({"videoScript": {"scenes": [1, 2], "title": "t"}, "customExcerpt": "x"})
    row = item_row("target--videoml", type="videoml", slug="target--videoml", editorial=editorial)
    context.source = InMemoryRowBackend({"Item": [row]}, standard_schemas())
    context.source_store = InMemoryObjectStore({})
    context.videoml_row = row


@given("a source backend whose items lack the bodyIr field")
def source_without_body_ir(context) -> None:
    context.source = InMemoryRowBackend({"Item": [item_row("a")]}, standard_schemas())
    context.source_store = InMemoryObjectStore({})


@given("a target backend that has bodyIr and an item already holding a converted bodyIr")
def target_with_body_ir(context) -> None:
    schemas = {**standard_schemas(), "Item": (TARGET_ITEM_FIELDS, TARGET_ITEM_FIELDS)}
    make_target(context, schemas, {"Item": [item_row("a", bodyIr='{"v":1}')]})


@given("a source backend with an item missing a field the target requires")
def source_missing_required(context) -> None:
    context.source = InMemoryRowBackend({"Item": [item_row("a", type=None)]}, standard_schemas())
    context.source_store = InMemoryObjectStore({})


@given("an empty target backend")
def empty_target(context) -> None:
    make_target(context)


@given("a source bucket with objects under media, newsroom and corpora")
def source_bucket(context) -> None:
    context.source = InMemoryRowBackend({}, standard_schemas())
    context.source_store = InMemoryObjectStore(
        {
            "media/a.png": (10, "e1"),
            "media/b.mp4": (20, "e2-3"),
            "newsroom/p.json": (5, "e3"),
            "corpora/x.pdf": (7, "e4"),
        }
    )


@given("a target bucket with an extra object that the source lacks")
def target_bucket(context) -> None:
    make_target(context)
    context.target_store = InMemoryObjectStore({"media/extra.png": (1, "e9")})


@given("the target backend returns its JSON fields with reordered keys")
def target_reorders_json(context) -> None:
    context.target.reorder_json_on_read = True


@given("I copy the default models and prefixes with apply")
@when("I copy the default models and prefixes with apply")
def copy_with_apply(context) -> None:
    context.target.writes.clear()
    context.target_store.copies.clear()
    run_copy(context, apply=True)


@when("I copy the default models and prefixes as a dry run")
def copy_dry_run(context) -> None:
    run_copy(context, apply=False)


@when('I copy the models "{names}" as a dry run')
def copy_named_models(context, names: str) -> None:
    run_copy(context, models=names.split(","), apply=False)


@when("I write the fidelity manifests")
def write_the_manifests(context) -> None:
    context.manifest_dir = Path(tempfile.mkdtemp())
    context.add_cleanup(__import__("shutil").rmtree, context.manifest_dir, True)
    run_copy(context, apply=False)
    write_manifests(context.manifest_dir, context.plan)


@then("the plan creates {items:d} Item rows and {published:d} PublishedItem row")
def plan_creates(context, items: int, published: int) -> None:
    assert len(context.plan.model("Item").created) == items
    assert len(context.plan.model("PublishedItem").created) == published


@then('the {model} model is reported as skipped with the reason "{reason}"')
def model_skipped(context, model: str, reason: str) -> None:
    entry = context.plan.model(model)
    assert not entry.selected and entry.reason == reason, entry.to_dict()
    assert entry.source_rows == 3


@then("no rows and no objects were written")
def nothing_written(context) -> None:
    assert context.target.writes == [], context.target.writes
    assert context.target_store.copies == [], context.target_store.copies


@then("every selected model is unchanged")
def everything_unchanged(context) -> None:
    for entry in context.plan.models:
        if entry.selected:
            assert not entry.created and not entry.updated, entry.to_dict()


@then("the target item has the same id, slug, type, publishedAt and editorial content")
def item_preserved(context) -> None:
    stored = context.target.tables["Item"][0]
    original = context.videoml_row
    for name in ("id", "slug", "type", "publishedAt"):
        assert stored[name] == original[name], name
    assert json.loads(stored["editorial"]) == json.loads(original["editorial"])


@then("the item is unchanged and its bodyIr is kept")
def body_ir_kept(context) -> None:
    assert context.plan.model("Item").unchanged == 1
    assert context.target.tables["Item"][0]["bodyIr"] == '{"v":1}'
    assert context.target.writes == []


@then('the copy is refused naming "{name}"')
def refused(context, name: str) -> None:
    assert context.refusal and name in context.refusal, context.refusal


@then("the plan lists {count:d} invalid row")
def invalid_rows(context, count: int) -> None:
    assert context.plan.invalid_row_count == count
    assert "missing-required:type" in context.plan.model("Item").invalid[0]["problems"]


@then("only the media objects are copied")
def only_media(context) -> None:
    assert sorted(context.target_store.copies) == ["media/a.png", "media/b.mp4"]


@then("the extra target object is still there")
def extra_kept(context) -> None:
    assert "media/extra.png" in context.target_store.objects


@then("the newsroom and corpora prefixes are reported as skipped")
def prefixes_skipped(context) -> None:
    by_prefix = {entry.prefix: entry for entry in context.plan.prefixes}
    for prefix in ("newsroom/", "corpora/"):
        assert not by_prefix[prefix].selected and by_prefix[prefix].reason == "not selected"
        assert prefix not in "".join(context.target_store.objects)


@then("the source and target manifests list the same row hashes for Item")
def manifests_match(context) -> None:
    source = json.loads((context.manifest_dir / "source/models/content-manifest.json").read_text())
    target = json.loads((context.manifest_dir / "target/models/content-manifest.json").read_text())
    assert source["Item"] and source["Item"] == target["Item"]


@then("the manifests include an S3 key list with sizes")
def manifests_have_keys(context) -> None:
    keys = json.loads((context.manifest_dir / "target/s3/keys.json").read_text())
    assert {"key": "media/a.png", "size": 10} in keys, keys
