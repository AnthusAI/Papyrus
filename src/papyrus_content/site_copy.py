"""Copy one Papyrus site's backend data into another site's backend (``papyrus ops site copy``).

Data moves DynamoDB table to table in DynamoDB's own typed JSON, so every attribute, timestamp and
``__typename`` is preserved exactly. Only the values listed in ``KEY_REWRITE_FIELDS`` (and the global bucket and
Amplify app id literals) are rewritten. Reference ids are never rewritten: the shared Cyclotron keys its training on
them, so a Reference id that embeds the old key stops the run. Nothing here deletes anything. A dry run reads and
never calls a write method.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

TypedItem = dict[str, Any]

REFERENCE_MODEL = "Reference"
WRITE_BATCH = 25
GET_BATCH = 100
SCAN_PAGE = 500
SAMPLE_COUNT = 3
UNPROCESSED_RETRIES = 12
S3_COPY_WORKERS = 8
RULE_CORPUS_KEY = "corpus-key"
RULE_BUCKET = "bucket-name"
RULE_APP_ID = "amplify-app-id"
RULE_OWNER = "owner-map"

# Where the old corpus key (which is also the site id and tenant id) is rewritten. Top-level field names per model;
# the token is replaced in every string inside the field. Derived from a scan of the p-apyr-us backend: every field
# that held the key as an id, a foreign key, an index key, a payload path or a Cyclotron id.
KEY_REWRITE_FIELDS: dict[str, tuple[str, ...]] = {
    "Assignment": ("id", "corpusId", "queueKey", "queueStatusKey", "title"),
    "AssignmentEvent": ("id", "assignmentId", "queueKey"),
    "Item": ("id", "lineageId", "sectionStatus", "tenantId", "tenantSlug", "typeStatus"),
    "PublishedItem": ("tenantId", "tenantSlug", "sectionStatus", "typeStatus"),
    "MediaAsset": ("tenantId", "storagePath"),
    "PublishedMediaAsset": ("tenantId", "storagePath"),
    "KnowledgeRawPayload": ("id", "ownerId"),
    "ModelAttachment": ("id", "ownerId", "ownerLineageId", "storagePath"),
    "NewsroomSection": ("id", "tenantId"),
    "Reference": ("curationStatusReason", "discoveredByMonitorId"),
    "SemanticRelation": ("classifierId", "metadata"),
}
ID_LIKE_FIELD = re.compile(r"^(id|storedId|.*Ids?|.*LineageIds?|.*Key|.*Keys)$")
OWNER_FIELD = re.compile(r"(Sub|Subs|By)$|^(owner|actor|responseOwner|responseLockOwner)$")
SUB_VALUE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(::.+)?$")
APP_ID_IN_BUCKET = re.compile(r"^amplify-([a-z0-9]+)-")
TABLE_NAME = re.compile(r"^(?P<model>[A-Za-z][A-Za-z0-9_]*)-(?P<api>[a-z0-9]+)-(?P<env>[A-Za-z0-9]+)$")


class SiteCopyError(ValueError):
    """The run cannot start: bad flags, a missing table, mismatched keys. Nothing was written."""


# --------------------------------------------------------------------------------------------------------------
# Typed DynamoDB JSON helpers
# --------------------------------------------------------------------------------------------------------------


def map_strings(value: TypedItem, transform: Callable[[str], str]) -> TypedItem:
    """A copy of a typed attribute with every string (S, SS, and strings inside M and L) transformed."""
    if "S" in value:
        return {"S": transform(value["S"])}
    if "SS" in value:
        return {"SS": [transform(item) for item in value["SS"]]}
    if "M" in value:
        return {"M": {key: map_strings(item, transform) for key, item in value["M"].items()}}
    if "L" in value:
        return {"L": [map_strings(item, transform) for item in value["L"]]}
    return value


def iterate_strings(value: TypedItem) -> Iterator[str]:
    if "S" in value:
        yield value["S"]
    elif "SS" in value:
        yield from value["SS"]
    elif "M" in value:
        for item in value["M"].values():
            yield from iterate_strings(item)
    elif "L" in value:
        for item in value["L"]:
            yield from iterate_strings(item)


def canonical_attribute(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) <= {"SS", "NS", "BS"} and value:
            return {key: sorted(items) for key, items in value.items()}
        return {key: canonical_attribute(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [canonical_attribute(item) for item in value]
    return value


def canonical_item(item: TypedItem) -> str:
    return json.dumps(canonical_attribute(item), sort_keys=True, separators=(",", ":"))


def item_digest(item: TypedItem) -> str:
    return hashlib.sha256(canonical_item(item).encode("utf-8")).hexdigest()


def item_id(item: TypedItem) -> str:
    return str((item.get("id") or {}).get("S") or "")


def attribute_text(item: TypedItem, name: str) -> str:
    return str((item.get(name) or {}).get("S") or "")


# --------------------------------------------------------------------------------------------------------------
# Configuration and rewriting
# --------------------------------------------------------------------------------------------------------------


@dataclass
class CopyConfig:
    from_api: str
    to_api: str | None = None
    key_map: dict[str, str] = field(default_factory=dict)
    from_bucket: str | None = None
    to_bucket: str | None = None
    models: list[str] | None = None
    media_prefixes: list[str] | None = None
    owner_map: dict[str, str] = field(default_factory=dict)
    keep_unmapped_owners: bool = False

    def key_pattern(self) -> re.Pattern[str] | None:
        if not self.key_map:
            return None
        olds = sorted(self.key_map, key=len, reverse=True)
        alternatives = "|".join(re.escape(old) for old in olds)
        return re.compile(rf"(?<![A-Za-z0-9])({alternatives})(?![A-Za-z0-9])")

    def app_ids(self) -> tuple[str, str] | None:
        if not (self.from_bucket and self.to_bucket):
            return None
        source, target = APP_ID_IN_BUCKET.match(self.from_bucket), APP_ID_IN_BUCKET.match(self.to_bucket)
        if source and target and source.group(1) != target.group(1):
            return source.group(1), target.group(1)
        return None


def parse_key_map(text: str | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for pair in [part.strip() for part in (text or "").split(",") if part.strip()]:
        old, separator, new = pair.partition("=")
        old, new = old.strip(), new.strip()
        if not separator or not old or not new:
            raise SiteCopyError(f"--corpus-key-map entries must look like old=new, got {pair!r}.")
        for label, value in (("old", old), ("new", new)):
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", value):
                raise SiteCopyError(f"The {label} key {value!r} must be lowercase letters, digits and hyphens.")
        mapping[old] = new
    return mapping


@dataclass
class Refusal:
    model: str
    record: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"model": self.model, "id": self.record, "reason": self.reason}


@dataclass
class ModelReport:
    model: str
    source: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    conflicts: int = 0
    to_examine: int = 0
    written: int = 0
    rewrites: dict[str, int] = field(default_factory=dict)
    rewritten_fields: dict[str, int] = field(default_factory=dict)
    samples: list[dict[str, str]] = field(default_factory=list)
    mentions: dict[str, int] = field(default_factory=dict)
    owner_classes: dict[str, int] = field(default_factory=dict)
    unmapped_owners: dict[str, int] = field(default_factory=dict)
    refusals: list[Refusal] = field(default_factory=list)
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {key: value for key, value in self.__dict__.items() if key != "refusals"}
        data["refusals"] = [refusal.to_dict() for refusal in self.refusals]
        return data


class Rewriter:
    """Applies the rewrite rules to one record and counts what it changed."""

    def __init__(self, config: CopyConfig) -> None:
        self.config = config
        self.key_pattern = config.key_pattern()
        self.literals: list[tuple[str, str, str]] = []
        if config.from_bucket and config.to_bucket and config.from_bucket != config.to_bucket:
            self.literals.append((RULE_BUCKET, config.from_bucket, config.to_bucket))
        app_ids = config.app_ids()
        if app_ids:
            self.literals.append((RULE_APP_ID, app_ids[0], app_ids[1]))
        self.reference_token = (
            re.compile(rf"reference-[A-Za-z0-9._-]*(?<![A-Za-z0-9])({'|'.join(re.escape(key) for key in config.key_map)})")
            if config.key_map
            else None
        )

    def rewrite_key(self, text: str) -> str:
        return self.key_pattern.sub(lambda match: self.config.key_map[match.group(1)], text) if self.key_pattern else text

    def rewrite_s3_key(self, key: str) -> str:
        return self.rewrite_key(key)

    def transform(self, model: str, source: TypedItem, report: ModelReport) -> tuple[TypedItem, list[Refusal]]:
        refusals: list[Refusal] = []
        record = item_id(source)
        result: TypedItem = {}
        key_fields = set(KEY_REWRITE_FIELDS.get(model, ()))
        for name, value in source.items():
            updated = value
            if name in key_fields and self.key_pattern:
                updated = self.apply_key_rule(model, name, record, updated, report, refusals)
            elif self.key_pattern and any(self.key_pattern.search(text) for text in iterate_strings(value)):
                self.report_unlisted(model, name, record, value, report, refusals)
            for rule, old, new in self.literals:
                updated = self.apply_literal(rule, old, new, model, name, updated, report)
            if OWNER_FIELD.search(name):
                updated = self.apply_owner_rule(model, name, record, updated, report, refusals)
            result[name] = updated
        if model == REFERENCE_MODEL and self.key_pattern and self.key_pattern.search(record):
            refusals.append(Refusal(model, record, "Reference id embeds the corpus key; Reference ids must not change"))
        return result, refusals

    def apply_key_rule(self, model, name, record, value, report, refusals) -> TypedItem:
        count = 0

        def replace(text: str) -> str:
            nonlocal count
            if self.reference_token and self.reference_token.search(text):
                refusals.append(Refusal(model, record, f"{name} holds a Reference id that embeds the corpus key"))
                return text
            rewritten, changes = self.key_pattern.subn(lambda match: self.config.key_map[match.group(1)], text)
            count += changes
            return rewritten

        updated = map_strings(value, replace)
        if count:
            bump(report.rewrites, RULE_CORPUS_KEY, count)
            bump(report.rewritten_fields, f"{model}.{name}", 1)
        return updated

    def apply_literal(self, rule, old, new, model, name, value, report) -> TypedItem:
        count = 0

        def replace(text: str) -> str:
            nonlocal count
            if old in text:
                count += text.count(old)
                return text.replace(old, new)
            return text

        updated = map_strings(value, replace)
        if count:
            bump(report.rewrites, rule, count)
            bump(report.rewritten_fields, f"{model}.{name}", 1)
        return updated

    def report_unlisted(self, model, name, record, value, report, refusals) -> None:
        if model == REFERENCE_MODEL and name == "id":
            return
        bump(report.mentions, f"{model}.{name}", 1)
        if ID_LIKE_FIELD.match(name):
            refusals.append(
                Refusal(model, record, f"{name} embeds the corpus key but has no rewrite rule, so the id cannot be mapped")
            )

    def apply_owner_rule(self, model, name, record, value, report, refusals) -> TypedItem:
        def classify(text: str) -> str:
            if SUB_VALUE.match(text):
                mapped = self.map_owner(text)
                if mapped is not None:
                    bump(report.rewrites, RULE_OWNER, 1)
                    bump(report.rewritten_fields, f"{model}.{name}", 1)
                    bump(report.owner_classes, f"{name}: sub (mapped)", 1)
                    return mapped
                bump(report.owner_classes, f"{name}: sub (unmapped)", 1)
                bump(report.unmapped_owners, text, 1)
                if not self.config.keep_unmapped_owners:
                    refusals.append(Refusal(model, record, f"{name} holds a Cognito sub with no --owner-map entry"))
                return text
            kind = "email" if "@" in text else "service name"
            bump(report.owner_classes, f"{name}: {kind} (kept)", 1)
            return text

        return map_strings(value, classify)

    def map_owner(self, text: str) -> str | None:
        owner_map = self.config.owner_map
        if text in owner_map:
            return owner_map[text]
        sub, separator, rest = text.partition("::")
        if sub in owner_map:
            return owner_map[sub] + (separator + rest if separator else "")
        return None


def bump(counter: dict[str, int], key: str, amount: int) -> None:
    counter[key] = counter.get(key, 0) + amount


# --------------------------------------------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------------------------------------------


def list_table_names(client: Any) -> list[str]:
    names: list[str] = []
    for page in client.get_paginator("list_tables").paginate():
        names.extend(page["TableNames"])
    return names


def tables_by_model(client: Any, api_id: str) -> dict[str, str]:
    """Model name to table name for one AppSync API id (``<Model>-<apiId>-<env>``, env is NONE for Gen 2)."""
    found: dict[str, list[str]] = {}
    for name in list_table_names(client):
        match = TABLE_NAME.match(name)
        if match and match.group("api") == api_id:
            found.setdefault(match.group("model"), []).append(name)
    tables: dict[str, str] = {}
    for model, names in found.items():
        preferred = [name for name in names if name.endswith("-NONE")] or names
        if len(preferred) != 1:
            raise SiteCopyError(f"Model {model} has several tables for API {api_id}: {', '.join(sorted(preferred))}.")
        tables[model] = preferred[0]
    return tables


def key_schema(client: Any, table: str) -> list[tuple[str, str]]:
    description = client.describe_table(TableName=table)["Table"]
    return [(entry["AttributeName"], entry["KeyType"]) for entry in description["KeySchema"]]


def scan_table(client: Any, table: str) -> Iterator[list[TypedItem]]:
    kwargs: dict[str, Any] = {"TableName": table, "Limit": SCAN_PAGE}
    while True:
        page = client.scan(**kwargs)
        yield page.get("Items", [])
        if not page.get("LastEvaluatedKey"):
            return
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def batch_get(client: Any, table: str, key_name: str, ids: list[str]) -> dict[str, TypedItem]:
    found: dict[str, TypedItem] = {}
    for start in range(0, len(ids), GET_BATCH):
        pending = {table: {"Keys": [{key_name: {"S": value}} for value in ids[start : start + GET_BATCH]]}}
        for attempt in range(UNPROCESSED_RETRIES):
            response = client.batch_get_item(RequestItems=pending)
            for item in response.get("Responses", {}).get(table, []):
                found[(item.get(key_name) or {}).get("S", "")] = item
            pending = response.get("UnprocessedKeys") or {}
            if not pending:
                break
            time.sleep(min(2**attempt * 0.05, 5))
        else:
            raise SiteCopyError(f"{table}: keys were still unprocessed after {UNPROCESSED_RETRIES} retries.")
    return found


def batch_write(client: Any, table: str, items: list[TypedItem]) -> None:
    for start in range(0, len(items), WRITE_BATCH):
        pending = {table: [{"PutRequest": {"Item": item}} for item in items[start : start + WRITE_BATCH]]}
        for attempt in range(UNPROCESSED_RETRIES):
            response = client.batch_write_item(RequestItems=pending)
            pending = response.get("UnprocessedItems") or {}
            if not pending:
                break
            time.sleep(min(2**attempt * 0.05, 5))
        else:
            raise SiteCopyError(f"{table}: items were still unprocessed after {UNPROCESSED_RETRIES} retries.")


# --------------------------------------------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------------------------------------------


@dataclass
class MediaReport:
    prefixes: list[str] | None
    source_objects: int = 0
    source_bytes: int = 0
    rewritten_keys: int = 0
    to_copy: int = 0
    to_copy_bytes: int = 0
    already_present: int = 0
    copied: int = 0
    samples: list[dict[str, str]] = field(default_factory=list)
    dangling_storage_paths: int = 0
    dangling_samples: list[str] = field(default_factory=list)
    target_read: bool = False
    refusals: list[Refusal] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = {key: value for key, value in self.__dict__.items() if key != "refusals"}
        data["refusals"] = [refusal.to_dict() for refusal in self.refusals]
        return data


@dataclass
class CopyPlan:
    applied: bool
    target_read: bool
    models: list[ModelReport] = field(default_factory=list)
    media: MediaReport | None = None
    errors: list[str] = field(default_factory=list)
    skipped_models: dict[str, str] = field(default_factory=dict)
    verify: list[dict[str, Any]] = field(default_factory=list)
    verify_media: dict[str, Any] | None = None

    @property
    def refusals(self) -> list[Refusal]:
        found = [refusal for report in self.models for refusal in report.refusals]
        return found + (self.media.refusals if self.media else [])

    @property
    def ok(self) -> bool:
        if self.errors or self.refusals:
            return False
        if self.verify and not all(entry["match"] for entry in self.verify):
            return False
        return not (self.verify_media is not None and not self.verify_media["match"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "applied": self.applied,
            "targetRead": self.target_read,
            "errors": self.errors,
            "skippedModels": self.skipped_models,
            "models": [report.to_dict() for report in self.models],
            "media": self.media.to_dict() if self.media else None,
            "verify": self.verify,
            "verifyMedia": self.verify_media,
        }


class SiteCopier:
    def __init__(
        self,
        config: CopyConfig,
        source_dynamodb: Any,
        target_dynamodb: Any | None = None,
        source_s3: Any | None = None,
        target_s3: Any | None = None,
    ) -> None:
        self.config = config
        self.rewriter = Rewriter(config)
        self.source_dynamodb = source_dynamodb
        self.target_dynamodb = target_dynamodb
        self.source_s3 = source_s3
        self.target_s3 = target_s3

    # -- planning --------------------------------------------------------------------------------------------

    def select_models(self, plan: CopyPlan) -> tuple[dict[str, str], dict[str, str]]:
        source_tables = tables_by_model(self.source_dynamodb, self.config.from_api)
        if not source_tables:
            raise SiteCopyError(f"No tables found for source API {self.config.from_api}.")
        target_tables: dict[str, str] = {}
        if self.target_dynamodb is not None and self.config.to_api:
            target_tables = tables_by_model(self.target_dynamodb, self.config.to_api)
            if not target_tables:
                raise SiteCopyError(f"No tables found for target API {self.config.to_api}.")
        requested = self.config.models
        if requested:
            unknown = [model for model in requested if model not in source_tables]
            if unknown:
                raise SiteCopyError(f"Models not found in the source API: {', '.join(unknown)}.")
        selected = {model: table for model, table in source_tables.items() if not requested or model in requested}
        for model in sorted(source_tables):
            if model not in selected:
                plan.skipped_models[model] = "not selected"
        if target_tables:
            for model in sorted(selected):
                if model not in target_tables:
                    plan.errors.append(f"Model {model} exists in the source but has no table in the target API.")
                    continue
                source_key, target_key = (
                    key_schema(self.source_dynamodb, selected[model]),
                    key_schema(self.target_dynamodb, target_tables[model]),
                )
                if source_key != target_key:
                    plan.errors.append(f"Model {model} key schemas differ: source {source_key}, target {target_key}.")
        return selected, target_tables

    def run(self, apply: bool = False) -> CopyPlan:
        """Plan, and when ``apply`` is true and the plan has no refusals, write. The plan pass never writes."""
        plan = CopyPlan(applied=False, target_read=self.target_dynamodb is not None)
        selected, target_tables = self.select_models(plan)
        for model in sorted(selected):
            plan.models.append(self.copy_model(model, selected[model], target_tables.get(model), write=False))
        if self.config.from_bucket:
            plan.media = self.plan_media(write=False)
        if apply:
            if self.target_dynamodb is None and self.target_s3 is None:
                plan.errors.append("--apply needs a target: pass --to-api and/or --to-media-bucket.")
            if not plan.ok:
                return plan
            plan.models = [
                self.copy_model(model, selected[model], target_tables.get(model), write=True)
                for model in sorted(selected)
                if model in target_tables
            ]
            if self.config.from_bucket and self.target_s3 is not None:
                plan.media = self.plan_media(write=True)
            plan.applied = True
        return plan

    def copy_model(self, model: str, table: str, target_table: str | None, write: bool) -> ModelReport:
        report = ModelReport(model)
        seen: dict[str, str] = {}
        for page in scan_table(self.source_dynamodb, table):
            rewritten: dict[str, TypedItem] = {}
            for source in page:
                report.source += 1
                new_item, refusals = self.rewriter.transform(model, source, report)
                report.refusals.extend(refusals)
                old_id, new_id = item_id(source), item_id(new_item)
                if new_id in seen and seen[new_id] != old_id:
                    report.refusals.append(
                        Refusal(model, new_id, f"ids {seen[new_id]!r} and {old_id!r} both map to this id")
                    )
                seen[new_id] = old_id
                if new_id != old_id and len(report.samples) < SAMPLE_COUNT:
                    report.samples.append({"before": old_id, "after": new_id})
                rewritten[new_id] = new_item
            if self.target_dynamodb is None or target_table is None:
                report.to_examine += len(rewritten)
                continue
            existing = batch_get(self.target_dynamodb, target_table, "id", list(rewritten))
            to_write: list[TypedItem] = []
            for new_id, new_item in rewritten.items():
                current = existing.get(new_id)
                if current is None:
                    report.created += 1
                    to_write.append(new_item)
                elif canonical_item(current) == canonical_item(new_item):
                    report.unchanged += 1
                elif attribute_text(new_item, "updatedAt") > attribute_text(current, "updatedAt") != "":
                    report.updated += 1
                    to_write.append(new_item)
                else:
                    report.conflicts += 1
            if write and to_write and not report.refusals:
                batch_write(self.target_dynamodb, target_table, to_write)
                report.written += len(to_write)
        return report

    # -- media -----------------------------------------------------------------------------------------------

    def list_objects(self, client: Any, bucket: str, prefixes: list[str] | None) -> dict[str, dict[str, Any]]:
        objects: dict[str, dict[str, Any]] = {}
        for prefix in prefixes or [""]:
            for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
                for entry in page.get("Contents", []):
                    objects[entry["Key"]] = {"size": entry["Size"], "etag": entry["ETag"].strip('"')}
        return objects

    def plan_media(self, write: bool) -> MediaReport:
        config = self.config
        report = MediaReport(config.media_prefixes)
        if self.source_s3 is None or not config.from_bucket:
            report.refusals.append(Refusal("media", "-", "no source bucket client"))
            return report
        source_objects = self.list_objects(self.source_s3, config.from_bucket, config.media_prefixes)
        target_objects: dict[str, dict[str, Any]] = {}
        if self.target_s3 is not None and config.to_bucket:
            target_objects = self.list_objects(self.target_s3, config.to_bucket, None)
            report.target_read = True
        copies: list[tuple[str, str]] = []
        seen: dict[str, str] = {}
        for key, info in sorted(source_objects.items()):
            new_key = self.rewriter.rewrite_s3_key(key)
            report.source_objects += 1
            report.source_bytes += info["size"]
            if new_key in seen and seen[new_key] != key:
                report.refusals.append(Refusal("media", new_key, f"keys {seen[new_key]!r} and {key!r} map to one key"))
            seen[new_key] = key
            if new_key != key:
                report.rewritten_keys += 1
                if len(report.samples) < SAMPLE_COUNT:
                    report.samples.append({"before": key, "after": new_key})
            present = target_objects.get(new_key)
            if present and present["size"] == info["size"] and (
                "-" in info["etag"] or "-" in present["etag"] or info["etag"] == present["etag"]
            ):
                report.already_present += 1
            elif report.target_read or self.target_s3 is None:
                report.to_copy += 1
                report.to_copy_bytes += info["size"]
                copies.append((key, new_key))
        self.check_storage_paths(report, seen)
        if write and self.target_s3 is not None and config.to_bucket and not report.refusals:
            report.copied = self.copy_objects(copies)
        return report

    def check_storage_paths(self, report: MediaReport, rewritten_to_source: dict[str, str]) -> None:
        """Storage paths in rows that point at no object in the source bucket. Informational only."""
        if self.config.media_prefixes:
            return
        known = set(rewritten_to_source)
        tables = tables_by_model(self.source_dynamodb, self.config.from_api)
        for model in ("ModelAttachment", "ReferenceAttachment", "Reference"):
            if model not in tables or (self.config.models and model not in self.config.models):
                continue
            for page in scan_table(self.source_dynamodb, tables[model]):
                for item in page:
                    path = attribute_text(item, "storagePath")
                    if path and self.rewriter.rewrite_s3_key(path) not in known:
                        report.dangling_storage_paths += 1
                        if len(report.dangling_samples) < SAMPLE_COUNT:
                            report.dangling_samples.append(f"{model}: {path}")

    def copy_objects(self, copies: list[tuple[str, str]]) -> int:
        assert self.target_s3 is not None and self.config.to_bucket and self.config.from_bucket

        def copy_one(pair: tuple[str, str]) -> None:
            key, new_key = pair
            self.target_s3.copy(
                {"Bucket": self.config.from_bucket, "Key": key},
                self.config.to_bucket,
                new_key,
                SourceClient=self.source_s3,
            )

        with ThreadPoolExecutor(max_workers=S3_COPY_WORKERS) as pool:
            list(pool.map(copy_one, copies))
        return len(copies)

    # -- verify ----------------------------------------------------------------------------------------------

    def verify(self) -> CopyPlan:
        plan = CopyPlan(applied=False, target_read=True)
        if self.target_dynamodb is None and self.target_s3 is None:
            plan.errors.append("--verify needs a target: pass --to-api and/or --to-media-bucket.")
            return plan
        if self.target_dynamodb is not None:
            selected, target_tables = self.select_models(plan)
            for model in sorted(selected):
                if model not in target_tables:
                    continue
                entry, report = self.verify_model(model, selected[model], target_tables[model])
                plan.verify.append(entry)
                plan.models.append(report)
        if self.config.from_bucket and self.target_s3 is not None and self.config.to_bucket:
            plan.verify_media = self.verify_media()
        return plan

    def digests(self, client: Any, table: str, model: str | None, report: ModelReport | None) -> dict[str, str]:
        found: dict[str, str] = {}
        for page in scan_table(client, table):
            for item in page:
                if model is not None and report is not None:
                    item, _ = self.rewriter.transform(model, item, report)
                found[item_id(item)] = item_digest(item)
        return found

    def verify_model(self, model: str, source_table: str, target_table: str) -> tuple[dict[str, Any], ModelReport]:
        report = ModelReport(model)
        source = self.digests(self.source_dynamodb, source_table, model, report)
        target = self.digests(self.target_dynamodb, target_table, None, None)
        missing = sorted(set(source) - set(target))
        extra = sorted(set(target) - set(source))
        different = sorted(key for key in set(source) & set(target) if source[key] != target[key])
        entry = {
            "model": model,
            "sourceCount": len(source),
            "targetCount": len(target),
            "sourceHash": combined_hash(source),
            "targetHash": combined_hash(target),
            "missing": len(missing),
            "extra": len(extra),
            "different": len(different),
            "samples": {"missing": missing[:SAMPLE_COUNT], "extra": extra[:SAMPLE_COUNT], "different": different[:SAMPLE_COUNT]},
        }
        entry["match"] = entry["sourceHash"] == entry["targetHash"] and len(source) == len(target)
        return entry, report

    def verify_media(self) -> dict[str, Any]:
        source = self.list_objects(self.source_s3, self.config.from_bucket, self.config.media_prefixes)
        target = self.list_objects(self.target_s3, self.config.to_bucket, None)
        expected = {self.rewriter.rewrite_s3_key(key): info["size"] for key, info in source.items()}
        actual = {key: info["size"] for key, info in target.items() if key in expected}
        missing = sorted(set(expected) - set(actual))
        different = sorted(key for key in actual if actual[key] != expected[key])
        return {
            "sourceObjects": len(expected),
            "targetObjects": len(actual),
            "sourceBytes": sum(expected.values()),
            "targetBytes": sum(actual.values()),
            "missing": len(missing),
            "differentSize": len(different),
            "samples": {"missing": missing[:SAMPLE_COUNT], "differentSize": different[:SAMPLE_COUNT]},
            "match": not missing and not different,
        }


def combined_hash(digests: dict[str, str]) -> str:
    material = "\n".join(f"{key}\t{digest}" for key, digest in sorted(digests.items()))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------------------------------


def human_bytes(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000
    return f"{count} B"


def render_plan(plan: CopyPlan) -> str:
    lines: list[str] = []
    if plan.models and not plan.verify:
        header = "model" + " " * 21 + "source  create  update  same  kept-target  rewrites"
        lines.append(header)
        for report in plan.models:
            read = plan.target_read and report.to_examine == 0
            counts = (
                f"{report.created:>7} {report.updated:>7} {report.unchanged:>5} {report.conflicts:>12}"
                if read
                else f"{'?':>7} {'?':>7} {'?':>5} {'?':>12}"
            )
            rewrites = ", ".join(f"{rule}={count}" for rule, count in sorted(report.rewrites.items())) or "-"
            lines.append(f"{report.model:<26}{report.source:>6} {counts}  {rewrites}")
        total = sum(report.source for report in plan.models)
        lines.append(f"{'total':<26}{total:>6}")
        if not plan.target_read:
            lines.append("target not read: create/update/same cannot be known without --to-api")
    for report in plan.models:
        for sample in report.samples:
            lines.append(f"  sample {report.model}: {sample['before']}  ->  {sample['after']}")
    totals: dict[str, int] = {}
    for report in plan.models:
        for rule, count in report.rewrites.items():
            bump(totals, rule, count)
    if totals:
        lines.append("rewrites per rule: " + ", ".join(f"{rule}={count}" for rule, count in sorted(totals.items())))
    fields: dict[str, int] = {}
    for report in plan.models:
        for name, count in report.rewritten_fields.items():
            bump(fields, name, count)
    for name, count in sorted(fields.items()):
        lines.append(f"  rewritten {name}: {count} records")
    for report in plan.models:
        for name, count in sorted(report.mentions.items()):
            lines.append(f"  mention left unchanged {name}: {count} records")
    owner_totals: dict[str, int] = {}
    for report in plan.models:
        for name, count in report.owner_classes.items():
            bump(owner_totals, f"{report.model}.{name}", count)
    for name, count in sorted(owner_totals.items()):
        lines.append(f"  owner field {name}: {count}")
    for report in plan.models:
        for value, count in sorted(report.unmapped_owners.items()):
            lines.append(f"  UNMAPPED owner in {report.model}: {value} ({count} records)")
    if plan.media:
        media = plan.media
        lines.append(
            f"media: {media.source_objects} objects, {human_bytes(media.source_bytes)}; "
            f"{media.rewritten_keys} keys rewritten"
            + (
                f"; {media.already_present} already present, {media.to_copy} to copy ({human_bytes(media.to_copy_bytes)})"
                if media.target_read
                else "; target bucket not read"
            )
            + (f"; copied {media.copied}" if media.copied else "")
        )
        for sample in media.samples:
            lines.append(f"  sample key: {sample['before']}  ->  {sample['after']}")
        if media.dangling_storage_paths:
            lines.append(
                f"  {media.dangling_storage_paths} row storage paths point at no object in the source bucket, e.g. "
                + "; ".join(media.dangling_samples)
            )
    for model, reason in plan.skipped_models.items():
        lines.append(f"skipped {model}: {reason}")
    for entry in plan.verify:
        status = "match" if entry["match"] else "MISMATCH"
        lines.append(
            f"verify {entry['model']:<24} {status}  source={entry['sourceCount']} target={entry['targetCount']} "
            f"missing={entry['missing']} extra={entry['extra']} different={entry['different']} hash={entry['sourceHash'][:12]}"
        )
    if plan.verify_media is not None:
        media_verify = plan.verify_media
        lines.append(
            f"verify media {'match' if media_verify['match'] else 'MISMATCH'}  "
            f"source={media_verify['sourceObjects']} target={media_verify['targetObjects']} "
            f"missing={media_verify['missing']} differentSize={media_verify['differentSize']}"
        )
    for message in plan.errors:
        lines.append(f"error: {message}")
    for refusal in plan.refusals[:50]:
        lines.append(f"REFUSED {refusal.model} {refusal.record}: {refusal.reason}")
    if len(plan.refusals) > 50:
        lines.append(f"... and {len(plan.refusals) - 50} more refusals")
    return "\n".join(lines)
