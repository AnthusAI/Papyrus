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
    render_table,
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
        self.composite_sort_fields: dict[str, tuple[str, ...]] = {}

    def model_names(self) -> list[str]:
        return sorted(self.schemas)

    def schema(self, model: str) -> ModelSchema:
        readable, writable = self.schemas[model]
        composite = self.composite_sort_fields.get(model, ())
        kept = {k: v for k, v in writable.items() if k != "createdAt" or k in composite}
        return ModelSchema(model, ("id",), readable, kept, composite_sort_fields=composite)

    def iterate_rows(self, model: str, field_names: list[str]):
        for row in self.tables.get(model, []):
            projected = {name: row.get(name) for name in field_names}
            if self.reorder_json_on_read:
                for name, value in projected.items():
                    if isinstance(value, str) and value.startswith("{"):
                        projected[name] = json.dumps(dict(reversed(list(json.loads(value).items()))))
            yield projected

    def create_row(self, model: str, row: dict) -> None:
        for name in self.composite_sort_fields.get(model, ()):
            if row.get(name) is None:
                raise RuntimeError(f"The composite sort key of the {model} index requires a value for {name}.")
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


def run_copy(context, models=None, apply=False, prefixes=None, keys=None, key_field_defaults=None):
    prefixes = list(DEFAULT_S3_PREFIXES) if prefixes is None else prefixes
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
            selected_keys=keys or [],
            key_field_defaults=key_field_defaults,
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


import contextlib  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import threading  # noqa: E402
from collections import Counter  # noqa: E402
from unittest import mock  # noqa: E402

from botocore.credentials import Credentials  # noqa: E402

from papyrus_content import backend_copy_commands  # noqa: E402
from papyrus_content.backend_copy_aws import (  # noqa: E402
    SOURCE_READ_ONLY_METHODS,
    GraphQLRowBackend,
    MemoryBudget,
    ReadOnlyS3Client,
    S3ObjectStore,
)
from papyrus_content.backend_copy_commands import content_copy_backend, resolve_s3_selection, resolve_transfer_mode  # noqa: E402

MIB = 1024 * 1024
SOURCE_APPSYNC = "https://source123.appsync-api.us-east-1.amazonaws.com/graphql"
TARGET_APPSYNC = "https://target456.appsync-api.us-east-1.amazonaws.com/graphql"
S3_WRITE_METHODS = frozenset(
    {"put_object", "copy", "create_multipart_upload", "upload_part", "complete_multipart_upload", "abort_multipart_upload"}
)


def periodic_bytes(size: int, offset: int = 0) -> bytes:
    pattern = bytes(range(251))
    return (pattern * (size // 251 + 2))[offset % 251: offset % 251 + size]


def plain_etag(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def multipart_etag(parts: list[bytes]) -> str:
    digests = b"".join(hashlib.md5(part).digest() for part in parts)
    return f"{hashlib.md5(digests).hexdigest()}-{len(parts)}"


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self.stream = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def close(self) -> None:
        self.stream.close()


class FakePaginator:
    def __init__(self, client) -> None:
        self.client = client

    def paginate(self, Bucket: str):
        entries = [
            {"Key": key, "Size": len(item["data"]), "ETag": f'"{item["etag"]}"'}
            for key, item in sorted(self.client.objects.items())
        ]
        return [{"Contents": entries[:2]}, {"Contents": entries[2:]}] if len(entries) > 2 else [{"Contents": entries}]


class FakeS3Client:
    def __init__(self, objects: dict | None = None, peer=None) -> None:
        self.objects = dict(objects or {})
        self.peer = peer
        self.calls: list[tuple[str, str]] = []
        self.part_sizes: dict[str, list[int]] = {}
        self.uploads: dict[str, dict] = {}
        self.lock = threading.Lock()

    def record(self, name: str, key: str = "") -> None:
        with self.lock:
            self.calls.append((name, key))

    def get_paginator(self, name: str) -> FakePaginator:
        self.record("get_paginator")
        return FakePaginator(self)

    def head_object(self, Bucket: str, Key: str, PartNumber: int | None = None) -> dict:
        self.record("head_object", Key)
        item = self.objects[Key]
        length = len(item["data"])
        if PartNumber == 1 and item.get("part_size"):
            length = min(item["part_size"], length)
        return {"ContentLength": length, "ETag": f'"{item["etag"]}"', **item["settings"]}

    def get_object(self, Bucket: str, Key: str, IfMatch: str | None = None) -> dict:
        self.record("get_object", Key)
        item = self.objects[Key]
        assert IfMatch is None or IfMatch == f'"{item["etag"]}"'
        return {"Body": FakeBody(item["data"])}

    def put_object(self, Bucket: str, Key: str, Body: bytes, **settings) -> dict:
        self.record("put_object", Key)
        etag = plain_etag(Body)
        self.objects[Key] = {"data": Body, "etag": etag, "settings": settings}
        return {"ETag": f'"{etag}"'}

    def create_multipart_upload(self, Bucket: str, Key: str, **settings) -> dict:
        self.record("create_multipart_upload", Key)
        upload_id = f"upload-{Key}"
        self.uploads[upload_id] = {"parts": {}, "settings": settings}
        return {"UploadId": upload_id}

    def upload_part(self, Bucket: str, Key: str, UploadId: str, PartNumber: int, Body: bytes) -> dict:
        self.record("upload_part", Key)
        self.uploads[UploadId]["parts"][PartNumber] = Body
        return {"ETag": f'"{plain_etag(Body)}"'}

    def complete_multipart_upload(self, Bucket: str, Key: str, UploadId: str, MultipartUpload: dict) -> dict:
        self.record("complete_multipart_upload", Key)
        upload = self.uploads.pop(UploadId)
        parts = [upload["parts"][entry["PartNumber"]] for entry in MultipartUpload["Parts"]]
        etag = multipart_etag(parts)
        self.part_sizes[Key] = [len(part) for part in parts]
        self.objects[Key] = {"data": b"".join(parts), "etag": etag, "settings": upload["settings"]}
        return {"ETag": f'"{etag}"'}

    def abort_multipart_upload(self, Bucket: str, Key: str, UploadId: str) -> None:
        self.record("abort_multipart_upload", Key)
        self.uploads.pop(UploadId, None)

    def copy(self, CopySource: dict, Bucket: str, Key: str) -> None:
        self.record("copy", Key)
        self.objects[Key] = dict(self.peer.objects[Key])

    def written(self) -> list[tuple[str, str]]:
        return [call for call in self.calls if call[0] in S3_WRITE_METHODS]


def fake_object(data: bytes, etag: str, settings: dict, part_size: int | None = None) -> dict:
    return {"data": data, "etag": etag, "settings": settings, "part_size": part_size}


def cross_account_objects() -> dict:
    small = periodic_bytes(1000)
    big_parts = [periodic_bytes(8 * MIB, 1), periodic_bytes(8 * MIB, 2), periodic_bytes(4 * MIB, 3)]
    single = periodic_bytes(12 * MIB, 4)
    return {
        "media/small.txt": fake_object(
            small,
            plain_etag(small),
            {"ContentType": "text/plain", "CacheControl": "max-age=60", "Metadata": {"origin": "legacy", "kind": "note"}},
        ),
        "media/big-multipart.bin": fake_object(
            b"".join(big_parts),
            multipart_etag(big_parts),
            {"ContentType": "video/mp4", "ContentDisposition": "inline", "Metadata": {"origin": "legacy"}},
            part_size=8 * MIB,
        ),
        "media/single-12.bin": fake_object(single, plain_etag(single), {"ContentType": "application/octet-stream"}),
    }


class FakeStsClient:
    def __init__(self, session) -> None:
        self.session = session

    def get_caller_identity(self) -> dict:
        self.session.calls.append(("sts", "get_caller_identity"))
        return {"Account": self.session.account}


class FakeCloudFormationClient:
    def __init__(self, session) -> None:
        self.session = session

    def describe_stacks(self, StackName: str) -> dict:
        self.session.calls.append(("cloudformation", "describe_stacks"))
        outputs = {
            "awsAppsyncApiEndpoint": self.session.appsync_endpoint,
            "bucketName": self.session.bucket,
            "storageRegion": "us-east-1",
        }
        return {"Stacks": [{"Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in outputs.items()]}]}


class FakeSession:
    def __init__(self, account: str, access_key: str, appsync_endpoint: str, bucket: str) -> None:
        self.account = account
        self.access_key = access_key
        self.appsync_endpoint = appsync_endpoint
        self.bucket = bucket
        self.calls: list[tuple[str, str]] = []
        self.s3 = FakeS3Client()

    def get_credentials(self):
        return Credentials(self.access_key, "secret-" + self.access_key)

    def client(self, service: str, **_options):
        if service == "sts":
            return FakeStsClient(self)
        if service == "cloudformation":
            return FakeCloudFormationClient(self)
        return self.s3


def make_sessions(context, source_account="111111111111", target_account="222222222222") -> None:
    context.sessions = {
        "legacy": FakeSession(source_account, "AKIASOURCEKEY", SOURCE_APPSYNC, "source-bucket"),
        "papyrus-production": FakeSession(target_account, "AKIATARGETKEY", TARGET_APPSYNC, "target-bucket"),
    }


def session_factory_for(context):
    return lambda profile: context.sessions[profile]


class TrackingBudget(MemoryBudget):
    def __init__(self, limit_bytes: int) -> None:
        super().__init__(limit_bytes)
        self.peak_bytes = 0

    @contextlib.contextmanager
    def hold(self, size_bytes: int):
        with super().hold(size_bytes):
            self.peak_bytes = max(self.peak_bytes, self._in_use)
            yield


class FlakyObjectStore(InMemoryObjectStore):
    def __init__(self, objects, failing_key: str) -> None:
        super().__init__(objects)
        self.failing_key = failing_key
        self.attempts: list[str] = []
        self.lock = threading.Lock()

    def copy_object_from(self, source_store, key: str):
        with self.lock:
            self.attempts.append(key)
        if key == self.failing_key:
            raise RuntimeError("simulated S3 failure")
        with self.lock:
            self.copies.append(key)
            self.objects[key] = source_store.objects[key]


def copy_with_stores(context, workers: int = 1) -> None:
    context.source = InMemoryRowBackend({}, standard_schemas())
    if not hasattr(context, "target") or context.target is None:
        context.target = InMemoryRowBackend({}, standard_schemas())
    context.plan = build_plan(
        context.source,
        context.target,
        requested_models=None,
        source_store=context.source_store,
        target_store=context.target_store,
        selected_prefixes=["media/"],
        source_account=getattr(context, "plan_source_account", None),
        target_account=getattr(context, "plan_target_account", None),
    )
    apply_plan(context.plan, context.target, context.source_store, context.target_store, workers=workers)


@given("a source session and a target session with different credentials")
def different_credentials(context) -> None:
    make_sessions(context)


@when("each side signs an AppSync request")
def each_side_signs(context) -> None:
    source = GraphQLRowBackend(SOURCE_APPSYNC, read_only=True, session=context.sessions["legacy"])
    target = GraphQLRowBackend(TARGET_APPSYNC, read_only=False, session=context.sessions["papyrus-production"])
    context.source_headers = source.client.header_factory(b"{}")
    context.target_headers = target.client.header_factory(b"{}")


@then("the source request is signed with the source access key only")
def signed_with_source(context) -> None:
    authorization = context.source_headers["Authorization"]
    assert "Credential=AKIASOURCEKEY/" in authorization and "AKIATARGETKEY" not in authorization


@then("the target request is signed with the target access key only")
def signed_with_target(context) -> None:
    authorization = context.target_headers["Authorization"]
    assert "Credential=AKIATARGETKEY/" in authorization and "AKIASOURCEKEY" not in authorization


@given("a source bucket and a target bucket that differ by one missing media object")
def buckets_differ_by_one(context) -> None:
    first, second = periodic_bytes(100), periodic_bytes(200, 5)
    shared = fake_object(first, plain_etag(first), {})
    context.source_client = FakeS3Client(
        {"media/a.txt": shared, "media/b.txt": fake_object(second, plain_etag(second), {})}
    )
    context.target_client = FakeS3Client({"media/a.txt": shared}, peer=context.source_client)


@when("I copy with the command defaults and apply")
def copy_with_defaults(context) -> None:
    context.transfer = resolve_transfer_mode(None, None, None)
    context.source_store = S3ObjectStore("src", "us-east-1", client=ReadOnlyS3Client(context.source_client))
    context.target_store = S3ObjectStore("dst", "us-east-1", client=context.target_client, transfer=context.transfer)
    context.target = None
    copy_with_stores(context)


@then("the transfer mode is server-side")
def mode_is_server_side(context) -> None:
    assert context.transfer == "server-side", context.transfer


@then("the missing media object was copied with a server-side copy and nothing was streamed")
def copied_server_side(context) -> None:
    assert context.target_client.written() == [("copy", "media/b.txt")], context.target_client.calls
    assert not [call for call in context.source_client.calls if call[0] in ("get_object", "head_object")]


@then("the plan reports no source or target account")
def plan_without_accounts(context) -> None:
    payload = context.plan.to_dict()
    assert payload["sourceAccount"] is None and payload["targetAccount"] is None
    assert "account" not in render_table(context.plan)


@given("a source session in account {source:d} and a target session in account {target:d}")
def sessions_in_accounts(context, source: int, target: int) -> None:
    make_sessions(context, str(source), str(target))


def run_command(context, flags: list[str]) -> str:
    context.command_error = None
    buffer = io.StringIO()
    with mock.patch.object(
        backend_copy_commands, "GraphQLRowBackend", lambda endpoint, read_only, session: InMemoryRowBackend({}, standard_schemas())
    ), contextlib.redirect_stdout(buffer):
        try:
            content_copy_backend(flags, session_factory=session_factory_for(context))
        except (ValueError, SystemExit) as error:
            context.command_error = error
    return buffer.getvalue()


COMMAND_BASE = [
    "--source-outputs", "stack:source-stack", "--target-outputs", "stack:target-stack",
    "--source-profile", "legacy", "--target-profile", "papyrus-production", "--json",
]


@when("I run copy-backend expecting target account {account:d} with apply")
def run_expecting_wrong_target(context, account: int) -> None:
    run_command(context, [*COMMAND_BASE, "--expect-target-account", str(account), "--apply"])


@then("the command stops naming account {account:d}")
def command_stops(context, account: int) -> None:
    assert isinstance(context.command_error, ValueError) and str(account) in str(context.command_error)


@then("only the caller identity was read in either session")
def only_identity_read(context) -> None:
    for session in context.sessions.values():
        assert session.calls == [("sts", "get_caller_identity")], session.calls
        assert session.s3.calls == []


@when("I run a dry run expecting accounts {source:d} and {target:d}")
def run_matching_dry_run(context, source: int, target: int) -> None:
    output = run_command(
        context, [*COMMAND_BASE, "--expect-source-account", str(source), "--expect-target-account", str(target)]
    )
    assert context.command_error is None, context.command_error
    context.command_plan = json.loads(output)


@then("the plan reports source account {source:d} and target account {target:d}")
def plan_reports_accounts(context, source: int, target: int) -> None:
    assert context.command_plan["sourceAccount"] == str(source)
    assert context.command_plan["targetAccount"] == str(target)
    assert context.command_plan["mode"] == "dry-run"


@given(
    "a cross-account source bucket with a small object, a 20 MiB object uploaded in 8 MiB parts and a 12 MiB single upload"
)
def cross_account_source(context) -> None:
    context.source_client = FakeS3Client(cross_account_objects())
    context.source_store = S3ObjectStore("src", "us-east-1", client=ReadOnlyS3Client(context.source_client))
    context.target = None


@given("an empty cross-account target bucket")
def cross_account_target(context) -> None:
    context.target_client = FakeS3Client()
    context.target_store = S3ObjectStore("dst", "us-east-1", client=context.target_client, transfer="stream")


@given("I copy the objects in stream mode")
@when("I copy the objects in stream mode")
def copy_in_stream_mode(context) -> None:
    context.source_client.calls.clear()
    context.target_client.calls.clear()
    copy_with_stores(context)
    assert context.plan.ok, context.plan.to_dict()


@when("I copy the objects in stream mode with {workers:d} workers and a {budget:d} MiB memory budget")
def copy_with_budget(context, workers: int, budget: int) -> None:
    context.tracking_budget = TrackingBudget(budget * MIB)
    context.target_store.memory_budget = context.tracking_budget
    copy_with_stores(context, workers=workers)
    assert context.plan.ok, context.plan.to_dict()


@then("every key exists in the target with the same size, content type, cache control and metadata")
def stream_preserved(context) -> None:
    for key, original in context.source_client.objects.items():
        stored = context.target_client.objects[key]
        assert stored["data"] == original["data"], key
        for name in ("ContentType", "CacheControl", "ContentDisposition", "Metadata"):
            assert stored["settings"].get(name) == original["settings"].get(name), (key, name)


@then("the ETags of all three objects equal the source ETags")
def stream_etags(context) -> None:
    for key, original in context.source_client.objects.items():
        assert context.target_client.objects[key]["etag"] == original["etag"], key
    assert context.plan.prefixes[0].warnings == []


@then("the 20 MiB object was uploaded in 3 parts of at most 8 MiB")
def stream_parts(context) -> None:
    assert context.target_client.part_sizes["media/big-multipart.bin"] == [8 * MIB, 8 * MIB, 4 * MIB]


@then("no object is read from the source and nothing is written to the target")
def nothing_streamed(context) -> None:
    assert not [call for call in context.source_client.calls if call[0] in ("get_object", "head_object")]
    assert context.target_client.written() == []


@then("the source client received only list, head and get calls")
def source_read_only(context) -> None:
    names = {name for name, _key in context.source_client.calls}
    assert names and names <= SOURCE_READ_ONLY_METHODS, names


@then("a write attempted through the source store is refused")
def source_write_refused(context) -> None:
    try:
        context.source_store.client.put_object(Bucket="src", Key="media/x", Body=b"x")
    except RuntimeError as error:
        assert "read-only" in str(error)
        return
    raise AssertionError("A write through the source store was not refused.")


@given("a source bucket with 40 small objects under media where one key cannot be copied")
def many_objects_one_failing(context) -> None:
    context.source = InMemoryRowBackend({}, standard_schemas())
    objects = {f"media/object-{number:02d}.bin": (number + 1, f"etag{number}") for number in range(40)}
    context.source_store = FlakyObjectStore(objects, "media/object-17.bin")
    context.source_store.objects = objects


@when("I copy with {workers:d} workers and apply")
def copy_with_workers(context, workers: int) -> None:
    flaky = FlakyObjectStore({}, "media/object-17.bin")
    context.target_store = flaky
    context.target = InMemoryRowBackend({}, standard_schemas())
    copy_with_stores(context, workers=workers)
    context.flaky = flaky


@then("every copyable object was copied exactly once")
def copied_once(context) -> None:
    attempts = Counter(context.flaky.attempts)
    assert len(attempts) == 40 and set(attempts.values()) == {1}, attempts
    assert len(context.flaky.copies) == 39 and len(set(context.flaky.copies)) == 39


@then("the plan reports {count:d} error naming the failed key")
def one_error(context, count: int) -> None:
    errors = [message for entry in context.plan.prefixes for message in entry.errors]
    assert len(errors) == count and "media/object-17.bin" in errors[0], errors
    assert context.plan.ok is False


@then("the other {count:d} objects are present in the target")
def others_present(context, count: int) -> None:
    present = [key for key in context.flaky.objects if key != "media/object-17.bin"]
    assert len(present) == count


@then("no more than {limit:d} MiB were held in memory at once")
def memory_bounded(context, limit: int) -> None:
    assert 0 < context.tracking_budget.peak_bytes <= limit * MIB, context.tracking_budget.peak_bytes


MESSAGE_FIELDS = {
    "id": spec("id", "ID"),
    "messageKind": spec("messageKind", required=True),
    "content": spec("content"),
    "responseTarget": spec("responseTarget"),
    "responseStatus": spec("responseStatus"),
    "createdAt": spec("createdAt", "AWSDateTime", required=True),
}
TICKET_FIELDS = {"id": spec("id", "ID"), "lane": spec("lane"), "title": spec("title")}
MESSAGE_CREATED_AT = "2026-03-01T10:00:00.000Z"


def message_row(identifier: str, response_status, response_target=None) -> dict:
    return {
        "id": identifier,
        "messageKind": "ingestion_rationale",
        "content": f"body of {identifier}",
        "responseTarget": response_target,
        "responseStatus": response_status,
        "createdAt": MESSAGE_CREATED_AT,
    }


@given("a source backend with 3 messages of which 2 leave responseStatus null")
def source_with_null_status_messages(context) -> None:
    rows = [message_row("m1", None), message_row("m2", None), message_row("m3", "RUNNING", "cloud")]
    context.source_rows = rows
    context.source = InMemoryRowBackend({"Message": rows}, {"Message": (MESSAGE_FIELDS, MESSAGE_FIELDS)})
    context.source_store = InMemoryObjectStore({})


@given("a target backend whose Message index rejects a null responseStatus")
def target_rejecting_null_status(context) -> None:
    context.target = InMemoryRowBackend({}, {"Message": (MESSAGE_FIELDS, MESSAGE_FIELDS)})
    context.target.composite_sort_fields = {"Message": ("responseStatus", "createdAt")}
    context.target_store = InMemoryObjectStore({})


@when("I copy the Message model with apply")
@given("I copy the Message model with apply")
def copy_message_model_with_apply(context) -> None:
    context.target.writes.clear()
    run_copy(context, models=["Message"], apply=True, prefixes=[])


@when("I copy the Message model as a dry run")
def copy_message_model_dry_run(context) -> None:
    run_copy(context, models=["Message"], apply=False, prefixes=[])


@when('I copy the Message model with apply and the key-field default "{assignment}"')
def copy_message_model_with_override(context, assignment: str) -> None:
    name, value = assignment.split("=")
    run_copy(context, models=["Message"], apply=True, prefixes=[], key_field_defaults={name: value})


@then("all {count:d} Message rows were written")
def all_messages_written(context, count: int) -> None:
    assert not context.plan.model("Message").errors, context.plan.model("Message").errors
    assert len(context.target.tables["Message"]) == count


@then("the {count:d} rows that had a null responseStatus now carry {value}")
def null_status_rows_defaulted(context, count: int, value: str) -> None:
    stored = {row["id"]: row for row in context.target.tables["Message"]}
    assert [stored[name]["responseStatus"] for name in ("m1", "m2")] == [value, value]
    assert stored["m3"]["responseStatus"] == "RUNNING"


@then("the business fields and the null responseTarget of every row are unchanged")
def business_fields_unchanged(context) -> None:
    stored = {row["id"]: row for row in context.target.tables["Message"]}
    for original in context.source_rows:
        for name in ("id", "messageKind", "content", "createdAt"):
            assert stored[original["id"]][name] == original[name], name
        assert stored[original["id"]].get("responseTarget") == original["responseTarget"]


@then("the plan reports {count:d} Message rows given key-field defaults")
def plan_reports_key_defaults(context, count: int) -> None:
    payload = context.plan.model("Message").to_dict()
    assert payload["keyFieldDefaults"] == {"count": count, "fields": {"responseStatus": "COMPLETED"}}, payload


@then("the plan is ok and lists {count:d} invalid rows")
def plan_ok_without_invalid(context, count: int) -> None:
    assert context.plan.ok and context.plan.invalid_row_count == count


@then("the printed table names the Message key-field defaults")
def table_names_key_defaults(context) -> None:
    assert "2 rows get key defaults: responseStatus=COMPLETED" in render_table(context.plan)


@given("a source backend with a Ticket whose composite sort-key field lane is null")
def source_with_null_lane_ticket(context) -> None:
    context.source = InMemoryRowBackend(
        {"Ticket": [{"id": "t1", "lane": None, "title": "t"}]}, {"Ticket": (TICKET_FIELDS, TICKET_FIELDS)}
    )
    context.source_store = InMemoryObjectStore({})


@given("a target backend whose Ticket index rejects a null lane")
def target_rejecting_null_lane(context) -> None:
    context.target = InMemoryRowBackend({}, {"Ticket": (TICKET_FIELDS, TICKET_FIELDS)})
    context.target.composite_sort_fields = {"Ticket": ("lane",)}
    context.target_store = InMemoryObjectStore({})


@when("I copy the Ticket model with apply")
def copy_ticket_model(context) -> None:
    run_copy(context, models=["Ticket"], apply=True, prefixes=[])


@then('the plan lists the Ticket row as invalid with "{problem}"')
def ticket_invalid(context, problem: str) -> None:
    assert context.plan.model("Ticket").invalid[0]["problems"] == [problem], context.plan.model("Ticket").invalid
    assert not context.plan.ok


@given("a source bucket with the corpora keys steering, steering backup and another file")
def source_with_corpora_keys(context) -> None:
    context.source = InMemoryRowBackend({}, standard_schemas())
    context.source_store = InMemoryObjectStore(
        {
            "corpora/papyrus-steering.yml": (888, "e1"),
            "corpora/papyrus-steering.yml.bak": (9, "e2"),
            "corpora/other.yml": (4, "e3"),
        }
    )


@when('I copy with the exact S3 key "{key}" and no prefixes')
def copy_with_exact_key(context, key: str) -> None:
    run_copy(context, apply=True, prefixes=[], keys=[key])


@then("only the corpora/papyrus-steering.yml object is copied")
def only_steering_copied(context) -> None:
    assert context.target_store.copies == ["corpora/papyrus-steering.yml"], context.target_store.copies
    assert context.plan.ok


@then('the plan reports an error naming "{key}"')
def plan_error_names_key(context, key: str) -> None:
    assert not context.plan.ok and any(key in message for message in context.plan.errors), context.plan.errors


@when('I resolve the S3 selection for prefixes "{prefixes}" and keys "{keys}"')
def resolve_with_both(context, prefixes: str, keys: str) -> None:
    context.selection = resolve_s3_selection(prefixes, keys)


@when('I resolve the S3 selection for no prefixes option and keys "{keys}"')
def resolve_with_keys_only(context, keys: str) -> None:
    context.selection = resolve_s3_selection(None, keys)


@when("I resolve the S3 selection for no prefixes option and no keys option")
def resolve_with_neither(context) -> None:
    context.selection = resolve_s3_selection(None, None)


@then('the prefixes are "{prefixes}" and the keys are "{keys}"')
def selection_both(context, prefixes: str, keys: str) -> None:
    assert context.selection == ([prefixes], [keys]), context.selection


@then('there are no prefixes and the keys are "{keys}"')
def selection_keys_only(context, keys: str) -> None:
    assert context.selection == ([], [keys]), context.selection


@then('the prefixes are "{prefixes}" and there are no keys')
def selection_default(context, prefixes: str) -> None:
    assert context.selection == ([prefixes], []), context.selection
