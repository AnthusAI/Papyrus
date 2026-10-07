"""AWS adapters for ``papyrus ops content copy-backend`` (PPY-26f158).

``GraphQLRowBackend`` discovers models, keys and writable fields from AppSync
introspection, so the same copy works for any Papyrus data schema. Reads and
writes are signed with SigV4 from the caller's AWS credential chain.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .backend_copy import FieldSpec, ModelSchema, ObjectInfo
from .graphql_authoring import PapyrusGraphQLAuthoringClient

SCALAR_KINDS = ("SCALAR", "ENUM")
CONNECTION_PATTERN = re.compile(r"Model(.+)Connection")
STACK_PREFIX = "stack:"
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


def resolve_location(spec: str) -> BackendLocation:
    if spec.startswith(STACK_PREFIX):
        import boto3

        stack_name = spec[len(STACK_PREFIX):]
        stacks = boto3.client("cloudformation").describe_stacks(StackName=stack_name)["Stacks"]
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
    def __init__(self, endpoint: str, *, read_only: bool, client: Any = None) -> None:
        self.read_only = read_only
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
        get_query = self._queries.get(f"get{model}")
        key_fields = tuple(argument["name"] for argument in get_query["args"]) if get_query else ("id",)
        schema = ModelSchema(model, key_fields, readable, writable)
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


class S3ObjectStore:
    def __init__(self, bucket: str, region: str, client: Any = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("s3", region_name=region)
        self.bucket = bucket
        self.client = client

    def list_objects(self) -> list[ObjectInfo]:
        paginator = self.client.get_paginator("list_objects_v2")
        objects = [
            ObjectInfo(entry["Key"], int(entry["Size"]), str(entry["ETag"]).strip('"'))
            for page in paginator.paginate(Bucket=self.bucket)
            for entry in page.get("Contents", [])
        ]
        return sorted(objects, key=lambda entry: entry.key)

    def copy_object_from(self, source_store: Any, key: str) -> None:
        self.client.copy({"Bucket": source_store.bucket, "Key": key}, self.bucket, key)
