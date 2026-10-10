"""AWS adapters for ``papyrus ops content copy-backend`` (PPY-26f158).

``GraphQLRowBackend`` discovers models, keys and writable fields from AppSync
introspection, so the same copy works for any Papyrus data schema. Reads and
writes are signed with SigV4 from the caller's AWS credential chain, or from a per-side
boto3 session when a profile is given (PPY-66408d).
"""

from __future__ import annotations

import json
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from .backend_copy import MULTIPART_ETAG_MARKER, FieldSpec, ModelSchema, ObjectInfo
from .graphql_authoring import PapyrusGraphQLAuthoringClient
from .graphql_http import iam_signed_graphql_headers

SCALAR_KINDS = ("SCALAR", "ENUM")
CONNECTION_PATTERN = re.compile(r"Model(.+)Connection")
STACK_PREFIX = "stack:"
COMPOSITE_CONDITION_SUFFIX = "CompositeKeyConditionInput"
INTROSPECTION_QUERY = """
query Introspect {
  __schema {
    queryType { fields { name args { name type { ...T } } type { ...T } } }
    types {
      name kind
      fields { name type { ...T } }
      inputFields { name type { ...T } }
      enumValues { name }
    }
  }
}
fragment T on __Type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
"""
SELECTED_PAGE_SIZE = 100
KEY_ONLY_PAGE_SIZE = 1000


@dataclass(frozen=True)
class BackendLocation:
    endpoint: str
    bucket: str | None
    region: str


def unwrap_type(type_node: dict[str, Any]) -> tuple[str, str, bool, bool]:
    required = type_node.get("kind") == "NON_NULL"
    is_list = False
    node = type_node
    while node.get("ofType"):
        if node["kind"] == "LIST":
            is_list = True
        node = node["ofType"]
    return node["kind"], node["name"], is_list, required


def resolve_location(spec: str, session: Any = None) -> BackendLocation:
    if spec.startswith(STACK_PREFIX):
        if session is None:
            import boto3

            session = boto3
        stack_name = spec[len(STACK_PREFIX):]
        stacks = session.client("cloudformation").describe_stacks(StackName=stack_name)["Stacks"]
        outputs = {entry["OutputKey"]: entry["OutputValue"] for entry in stacks[0].get("Outputs", [])}
        endpoint = outputs.get("awsAppsyncApiEndpoint")
        if not endpoint:
            raise ValueError(f"Stack {stack_name} has no awsAppsyncApiEndpoint output.")
        return BackendLocation(endpoint, outputs.get("bucketName"), outputs.get("storageRegion") or "us-east-1")
    path = Path(spec)
    if not path.exists():
        raise ValueError(f"Outputs file not found: {spec}. Pass an amplify_outputs.json path or stack:<stack-name>.")
    parsed = json.loads(path.read_text(encoding="utf-8"))
    endpoint = (parsed.get("data") or {}).get("url") or parsed.get("aws_appsync_graphqlEndpoint")
    if not endpoint:
        raise ValueError(f"No data.url in {spec}.")
    storage = parsed.get("storage") or {}
    bucket = storage.get("bucket_name") or storage.get("bucketName")
    region = storage.get("aws_region") or (parsed.get("data") or {}).get("aws_region") or "us-east-1"
    return BackendLocation(endpoint, bucket, region)


class GraphQLRowBackend:
    def __init__(self, endpoint: str, *, read_only: bool, client: Any = None, session: Any = None) -> None:
        self.read_only = read_only
        if client is None and session is not None:
            client = PapyrusGraphQLAuthoringClient(
                endpoint,
                header_factory=lambda body: iam_signed_graphql_headers(endpoint, body, session),
            )
        self.client = client or PapyrusGraphQLAuthoringClient(endpoint)
        self._types: dict[str, dict[str, Any]] | None = None
        self._queries: dict[str, dict[str, Any]] = {}
        self._schemas: dict[str, ModelSchema] = {}

    def _load(self) -> None:
        if self._types is not None:
            return
        schema = self.client.graphql(INTROSPECTION_QUERY)["__schema"]
        self._types = {entry["name"]: entry for entry in schema["types"]}
        self._queries = {entry["name"]: entry for entry in schema["queryType"]["fields"]}

    def model_names(self) -> list[str]:
        self._load()
        assert self._types is not None
        names = []
        for type_name in self._types:
            match = CONNECTION_PATTERN.fullmatch(type_name)
            if match and match.group(1) in self._types and f"Create{match.group(1)}Input" in self._types:
                names.append(match.group(1))
        return sorted(names)

    def _enum_values(self, enum_name: str) -> tuple[str, ...]:
        assert self._types is not None
        return tuple(value["name"] for value in self._types[enum_name].get("enumValues") or [])

    def _field_spec(self, name: str, type_node: dict[str, Any]) -> FieldSpec | None:
        kind, type_name, is_list, required = unwrap_type(type_node)
        if kind not in SCALAR_KINDS:
            return None
        enum_values = self._enum_values(type_name) if kind == "ENUM" else None
        return FieldSpec(name, type_name, is_list, required, enum_values)

    def _list_field_name(self, model: str) -> str:
        connection = f"Model{model}Connection"
        candidates = []
        for name, query in self._queries.items():
            if not name.startswith("list") or unwrap_type(query["type"])[1] != connection:
                continue
            argument_names = {argument["name"] for argument in query["args"]}
            if not {"limit", "nextToken"} <= argument_names:
                continue
            if any(argument["type"]["kind"] == "NON_NULL" for argument in query["args"]):
                continue
            candidates.append(name)
        if not candidates:
            raise ValueError(f"No plain list query found for model {model}.")
        return min(candidates, key=lambda name: (len(name), name))

    def _composite_sort_fields(self, model: str) -> tuple[str, ...]:
        assert self._types is not None
        connection = f"Model{model}Connection"
        names: list[str] = []
        for query in self._queries.values():
            if unwrap_type(query["type"])[1] != connection:
                continue
            for argument in query["args"]:
                condition_name = unwrap_type(argument["type"])[1]
                if not condition_name.endswith(COMPOSITE_CONDITION_SUFFIX):
                    continue
                equality = next(item for item in self._types[condition_name]["inputFields"] if item["name"] == "eq")
                key_type = unwrap_type(equality["type"])[1]
                names += [item["name"] for item in self._types[key_type]["inputFields"]]
        return tuple(dict.fromkeys(names))

    def schema(self, model: str) -> ModelSchema:
        if model in self._schemas:
            return self._schemas[model]
        self._load()
        assert self._types is not None
        readable: dict[str, FieldSpec] = {}
        for entry in self._types[model]["fields"]:
            spec = self._field_spec(entry["name"], entry["type"])
            if spec is not None:
                readable[entry["name"]] = spec
        writable: dict[str, FieldSpec] = {}
        for entry in self._types[f"Create{model}Input"]["inputFields"]:
            spec = self._field_spec(entry["name"], entry["type"])
            if spec is not None:
                writable[entry["name"]] = spec
        composite_sort_fields = self._composite_sort_fields(model)
        get_query = self._queries.get(f"get{model}")
        key_fields = tuple(argument["name"] for argument in get_query["args"]) if get_query else ("id",)
        schema = ModelSchema(model, key_fields, readable, writable, composite_sort_fields)
        self._schemas[model] = schema
        return schema

    def iterate_rows(self, model: str, field_names: list[str]) -> Iterable[dict[str, Any]]:
        schema = self.schema(model)
        available = [name for name in field_names if name in schema.readable]
        list_field = self._list_field_name(model)
        query = (
            "query($limit: Int, $nextToken: String) { "
            f"{list_field}(limit: $limit, nextToken: $nextToken) {{ items {{ {' '.join(available)} }} nextToken }} }}"
        )
        page_size = KEY_ONLY_PAGE_SIZE if set(available) <= set(schema.key_fields) else SELECTED_PAGE_SIZE
        next_token = None
        while True:
            data = self.client.graphql(query, {"limit": page_size, "nextToken": next_token})
            connection = data.get(list_field) or {}
            for row in connection.get("items") or []:
                if row:
                    yield row
            next_token = connection.get("nextToken")
            if not next_token:
                return

    def _write(self, verb: str, model: str, row: dict[str, Any]) -> None:
        if self.read_only:
            raise RuntimeError("This backend is opened read-only; refusing to write.")
        self._load()
        schema = self.schema(model)
        input_payload = {name: value for name, value in row.items() if name in schema.writable}
        mutation = (
            f"mutation($input: {verb.capitalize()}{model}Input!) "
            f"{{ {verb}{model}(input: $input) {{ {schema.key_fields[0]} }} }}"
        )
        self.client.graphql(mutation, {"input": input_payload})

    def create_row(self, model: str, row: dict[str, Any]) -> None:
        self._write("create", model, row)

    def update_row(self, model: str, row: dict[str, Any]) -> None:
        self._write("update", model, row)


SERVER_SIDE_TRANSFER = "server-side"
STREAM_TRANSFER = "stream"
S3_PART_SIZE_BYTES = 8 * 1024 * 1024
STREAM_MEMORY_BUDGET_BYTES = 256 * 1024 * 1024
STREAM_READ_CHUNK_BYTES = 1024 * 1024
PRESERVED_OBJECT_SETTINGS = ("ContentType", "CacheControl", "ContentDisposition", "ContentEncoding", "ContentLanguage")
SOURCE_READ_ONLY_METHODS = frozenset({"get_paginator", "list_objects_v2", "head_object", "get_object"})


class ReadOnlyS3Client:
    """Wraps the source S3 client so only list, head and get calls can ever be made."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        if name not in SOURCE_READ_ONLY_METHODS:
            raise RuntimeError(f"The source bucket is read-only; refusing S3 call {name}.")
        return getattr(self._client, name)


class MemoryBudget:
    """Bounds the bytes held in memory by all stream workers together."""

    def __init__(self, limit_bytes: int) -> None:
        self.limit_bytes = limit_bytes
        self._in_use = 0
        self._condition = threading.Condition()

    @contextmanager
    def hold(self, size_bytes: int) -> Iterator[None]:
        claim = min(max(size_bytes, 1), self.limit_bytes)
        with self._condition:
            self._condition.wait_for(lambda: self._in_use == 0 or self._in_use + claim <= self.limit_bytes)
            self._in_use += claim
        try:
            yield
        finally:
            with self._condition:
                self._in_use -= claim
                self._condition.notify_all()


def read_exactly(body: Any, size_bytes: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size_bytes:
        chunk = body.read(min(STREAM_READ_CHUNK_BYTES, size_bytes - len(chunks)))
        if not chunk:
            raise RuntimeError(f"The source stream ended after {len(chunks)} of {size_bytes} bytes.")
        chunks.extend(chunk)
    return bytes(chunks)


class S3ObjectStore:
    def __init__(
        self,
        bucket: str,
        region: str,
        client: Any = None,
        session: Any = None,
        transfer: str = SERVER_SIDE_TRANSFER,
        memory_budget_bytes: int = STREAM_MEMORY_BUDGET_BYTES,
    ) -> None:
        if client is None:
            if session is None:
                import boto3

                session = boto3
            client = session.client("s3", region_name=region)
        self.bucket = bucket
        self.client = client
        self.transfer = transfer
        self.memory_budget = MemoryBudget(memory_budget_bytes)

    def list_objects(self) -> list[ObjectInfo]:
        paginator = self.client.get_paginator("list_objects_v2")
        objects = [
            ObjectInfo(entry["Key"], int(entry["Size"]), str(entry["ETag"]).strip('"'))
            for page in paginator.paginate(Bucket=self.bucket)
            for entry in page.get("Contents", [])
        ]
        return sorted(objects, key=lambda entry: entry.key)

    def copy_object_from(self, source_store: Any, key: str) -> str | None:
        if self.transfer == SERVER_SIDE_TRANSFER:
            self.client.copy({"Bucket": source_store.bucket, "Key": key}, self.bucket, key)
            return None
        return self._stream_object_from(source_store, key)

    def _source_part_size(self, source_store: Any, key: str, size_bytes: int) -> int:
        try:
            first_part = source_store.client.head_object(Bucket=source_store.bucket, Key=key, PartNumber=1)
            part_size = int(first_part["ContentLength"])
        except Exception:
            return S3_PART_SIZE_BYTES
        return part_size if 0 < part_size <= size_bytes else S3_PART_SIZE_BYTES

    def _stream_object_from(self, source_store: Any, key: str) -> str | None:
        head = source_store.client.head_object(Bucket=source_store.bucket, Key=key)
        source_etag_raw = str(head["ETag"])
        source_etag = source_etag_raw.strip('"')
        size_bytes = int(head["ContentLength"])
        settings: dict[str, Any] = {name: head[name] for name in PRESERVED_OBJECT_SETTINGS if head.get(name)}
        if head.get("Metadata"):
            settings["Metadata"] = dict(head["Metadata"])
        multipart_source = MULTIPART_ETAG_MARKER in source_etag
        reproducible = multipart_source or size_bytes <= self.memory_budget.limit_bytes
        if multipart_source:
            part_size = self._source_part_size(source_store, key, size_bytes)
        else:
            part_size = size_bytes if reproducible else S3_PART_SIZE_BYTES
        body = source_store.client.get_object(Bucket=source_store.bucket, Key=key, IfMatch=source_etag_raw)["Body"]
        try:
            if multipart_source or not reproducible:
                target_etag = self._upload_in_parts(body, key, size_bytes, part_size, settings)
            else:
                with self.memory_budget.hold(size_bytes):
                    data = read_exactly(body, size_bytes)
                    target_etag = str(
                        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **settings)["ETag"]
                    ).strip('"')
        finally:
            close = getattr(body, "close", None)
            if close:
                close()
        if target_etag == source_etag:
            return None
        if not multipart_source and reproducible:
            raise RuntimeError(f"ETag mismatch after copy: source {source_etag}, target {target_etag}.")
        target_size = int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])
        if target_size != size_bytes:
            raise RuntimeError(f"Size mismatch after copy: source {size_bytes}, target {target_size}.")
        return (
            f"ETag not reproduced (source {source_etag}, target {target_etag}); "
            "size verified, content not checksum-verified."
        )

    def _upload_in_parts(self, body: Any, key: str, size_bytes: int, part_size: int, settings: dict[str, Any]) -> str:
        upload_id = self.client.create_multipart_upload(Bucket=self.bucket, Key=key, **settings)["UploadId"]
        try:
            parts = []
            remaining = size_bytes
            part_number = 1
            while remaining > 0:
                want = min(part_size, remaining)
                with self.memory_budget.hold(want):
                    data = read_exactly(body, want)
                    uploaded = self.client.upload_part(
                        Bucket=self.bucket, Key=key, UploadId=upload_id, PartNumber=part_number, Body=data
                    )
                parts.append({"ETag": uploaded["ETag"], "PartNumber": part_number})
                remaining -= want
                part_number += 1
            completed = self.client.complete_multipart_upload(
                Bucket=self.bucket, Key=key, UploadId=upload_id, MultipartUpload={"Parts": parts}
            )
        except Exception:
            self.client.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)
            raise
        return str(completed["ETag"]).strip('"')
