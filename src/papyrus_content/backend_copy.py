"""Generic backend-to-backend copy planning and execution (PPY-26f158).

The planner reads rows and S3 objects from a source backend and a target
backend through two small adapter interfaces, decides what an apply would
create, update, copy or skip, and only then writes. A dry run performs the
same reads and never calls a write method. Nothing here ever deletes.
"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

IDENTITY_MODELS = frozenset({"UserProfile", "UserIdentity", "UserRoleAssignment"})
DEFAULT_MODELS = (
    "NewsroomSection",
    "Tag",
    "Edition",
    "Item",
    "MediaAsset",
    "EditionItem",
    "ItemTag",
    "PublishedEdition",
    "PublishedItem",
    "PublishedMediaAsset",
    "PublishedEditionItem",
)
DEFAULT_S3_PREFIXES = ("media/",)
BUILTIN_KEY_FIELD_DEFAULTS = {"Message.responseStatus": "COMPLETED"}
SYSTEM_TIMESTAMP_FIELDS = frozenset({"createdAt", "updatedAt"})
JSON_SCALAR_NAME = "AWSJSON"
MULTIPART_ETAG_MARKER = "-"
NOT_SELECTED_REASON = "not selected"
IDENTITY_REASON = "identity model, never copied"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type_name: str
    is_list: bool = False
    required: bool = False
    enum_values: tuple[str, ...] | None = None

    @property
    def is_json(self) -> bool:
        return self.type_name == JSON_SCALAR_NAME


@dataclass(frozen=True)
class ModelSchema:
    name: str
    key_fields: tuple[str, ...]
    readable: dict[str, FieldSpec]
    writable: dict[str, FieldSpec]
    composite_sort_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int
    etag: str


class RowBackend(Protocol):
    def model_names(self) -> list[str]: ...

    def schema(self, model: str) -> ModelSchema: ...

    def iterate_rows(self, model: str, field_names: list[str]) -> Iterable[dict[str, Any]]: ...

    def create_row(self, model: str, row: dict[str, Any]) -> None: ...

    def update_row(self, model: str, row: dict[str, Any]) -> None: ...


class ObjectStore(Protocol):
    def list_objects(self) -> list[ObjectInfo]: ...

    def copy_object_from(self, source_store: Any, key: str) -> str | None: ...


class CopyRefused(ValueError):
    pass


def canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: canonical_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonical_value(item) for item in value]
    if isinstance(value, float) and value == value and value.is_integer():
        return int(value)
    return value


def normalize_value(spec: FieldSpec | None, value: Any) -> Any:
    if value is None:
        return None
    if spec is not None and spec.is_json and isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value
    return canonical_value(value)


def row_projection(schema_fields: dict[str, FieldSpec], row: dict[str, Any], field_names: Iterable[str]) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    for name in field_names:
        normalized = normalize_value(schema_fields.get(name), row.get(name))
        if normalized is not None:
            projection[name] = normalized
    return projection


def row_hash(projection: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(projection, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def row_key(schema: ModelSchema, row: dict[str, Any]) -> str:
    return "/".join(str(row.get(name)) for name in schema.key_fields)


def row_label(schema: ModelSchema, row: dict[str, Any]) -> str:
    label = row_key(schema, row)
    slug = row.get("slug")
    return f"{label} ({slug})" if slug and str(slug) != label else label


def parse_selection(value: str | None, default: Iterable[str]) -> list[str]:
    if value is None:
        return list(default)
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass
class ModelPlan:
    model: str
    selected: bool
    reason: str = ""
    source_rows: int = 0
    target_rows: int | None = None
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: int = 0
    invalid: list[dict[str, Any]] = field(default_factory=list)
    key_defaulted_rows: int = 0
    key_default_values: dict[str, str] = field(default_factory=dict)
    dropped_fields: list[str] = field(default_factory=list)
    unwritable_timestamps: list[str] = field(default_factory=list)
    target_only_rows: int = 0
    source_hashes: dict[str, str] = field(default_factory=dict)
    target_hashes: dict[str, str] = field(default_factory=dict)
    pending_creates: list[dict[str, Any]] = field(default_factory=list)
    pending_updates: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    written_created: int = 0
    written_updated: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "action": "copy" if self.selected else "skip",
            "reason": self.reason,
            "sourceRows": self.source_rows,
            "targetRows": self.target_rows,
            "created": len(self.created),
            "updated": len(self.updated),
            "unchanged": self.unchanged,
            "invalid": len(self.invalid),
            "keyFieldDefaults": {"count": self.key_defaulted_rows, "fields": dict(sorted(self.key_default_values.items()))},
            "targetOnlyRows": self.target_only_rows,
            "droppedFields": self.dropped_fields,
            "unwritableTimestamps": self.unwritable_timestamps,
            "createIds": self.created,
            "updateIds": self.updated,
            "invalidRows": self.invalid,
            "writtenCreated": self.written_created,
            "writtenUpdated": self.written_updated,
            "errors": self.errors,
        }


@dataclass
class PrefixPlan:
    prefix: str
    source_objects: int = 0
    source_bytes: int = 0
    target_objects: int = 0
    selected: bool = False
    reason: str = ""
    selected_objects: int = 0
    to_copy_missing: list[str] = field(default_factory=list)
    to_copy_different: list[str] = field(default_factory=list)
    unchanged: int = 0
    bytes_to_copy: int = 0
    copied: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prefix": self.prefix,
            "action": "copy" if self.selected else "skip",
            "reason": self.reason,
            "sourceObjects": self.source_objects,
            "sourceBytes": self.source_bytes,
            "targetObjects": self.target_objects,
            "selectedObjects": self.selected_objects,
            "missing": len(self.to_copy_missing),
            "different": len(self.to_copy_different),
            "unchanged": self.unchanged,
            "bytesToCopy": self.bytes_to_copy,
            "copied": self.copied,
            "missingKeys": self.to_copy_missing,
            "differentKeys": self.to_copy_different,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class CopyPlan:
    models: list[ModelPlan]
    prefixes: list[PrefixPlan]
    extra_target_only_objects: int = 0
    applied: bool = False
    errors: list[str] = field(default_factory=list)
    source_objects: list[ObjectInfo] = field(default_factory=list)
    target_objects: list[ObjectInfo] = field(default_factory=list)
    source_account: str | None = None
    target_account: str | None = None

    @property
    def invalid_row_count(self) -> int:
        return sum(len(plan.invalid) for plan in self.models)

    @property
    def ok(self) -> bool:
        return (
            not self.errors
            and self.invalid_row_count == 0
            and not any(plan.errors for plan in self.models)
            and not any(plan.errors for plan in self.prefixes)
        )

    def model(self, name: str) -> ModelPlan:
        return next(plan for plan in self.models if plan.model == name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": "apply" if self.applied else "dry-run",
            "ok": self.ok,
            "sourceAccount": self.source_account,
            "targetAccount": self.target_account,
            "models": [plan.to_dict() for plan in self.models],
            "s3Prefixes": [plan.to_dict() for plan in self.prefixes],
            "targetOnlyObjects": self.extra_target_only_objects,
            "errors": self.errors,
        }


def refuse_identity_models(requested: Iterable[str]) -> None:
    refused = sorted(set(requested) & IDENTITY_MODELS)
    if refused:
        raise CopyRefused(
            f"Identity models are never copied (people re-sign-in): {', '.join(refused)}."
        )


def resolve_selected_models(requested: list[str] | None, source_models: list[str], target_models: list[str]) -> list[str]:
    if requested is None:
        selected = [name for name in DEFAULT_MODELS if name in source_models]
    elif requested == ["all"]:
        selected = [name for name in source_models if name not in IDENTITY_MODELS]
    else:
        selected = list(requested)
    refuse_identity_models(selected)
    unknown = [name for name in selected if name not in source_models or name not in target_models]
    if unknown:
        raise CopyRefused(f"Models missing from the source or the target schema: {', '.join(sorted(unknown))}.")
    return selected


def validate_row(schema: ModelSchema, row: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name in schema.key_fields:
        if row.get(name) in (None, ""):
            problems.append(f"missing-key:{name}")
    for name, spec in schema.writable.items():
        value = row.get(name)
        if value is None:
            if spec.required and name not in schema.key_fields:
                problems.append(f"missing-required:{name}")
            continue
        if spec.enum_values is not None:
            values = value if isinstance(value, list) else [value]
            for item in values:
                if item not in spec.enum_values:
                    problems.append(f"enum-value-rejected:{name}")
                    break
        if spec.is_json and isinstance(value, str):
            try:
                json.loads(value)
            except ValueError:
                problems.append(f"invalid-json:{name}")
    return problems


def shared_field_names(source_schema: ModelSchema, target_schema: ModelSchema) -> list[str]:
    return [name for name in source_schema.readable if name in target_schema.writable]


def comparison_field_names(shared: list[str], key_fields: tuple[str, ...]) -> list[str]:
    return [name for name in shared if name not in SYSTEM_TIMESTAMP_FIELDS and name not in key_fields]


def composite_sort_key_candidates(target_schema: ModelSchema, shared: list[str]) -> list[str]:
    return [name for name in target_schema.composite_sort_fields if name in shared]


def with_key_field_defaults(
    model: str, row: dict[str, Any], candidates: list[str], defaults: dict[str, str]
) -> tuple[dict[str, Any], dict[str, str]]:
    applied = {
        name: defaults[f"{model}.{name}"]
        for name in candidates
        if row.get(name) is None and f"{model}.{name}" in defaults
    }
    return ({**row, **applied} if applied else row), applied


def unresolved_composite_sort_keys(target_schema: ModelSchema, row: dict[str, Any]) -> list[str]:
    return [
        f"null-composite-sort-key:{name}"
        for name in target_schema.composite_sort_fields
        if name in target_schema.writable
        and not target_schema.writable[name].required
        and row.get(name) is None
    ]


def plan_selected_model(
    model: str, source: RowBackend, target: RowBackend, key_field_defaults: dict[str, str]
) -> ModelPlan:
    source_schema = source.schema(model)
    target_schema = target.schema(model)
    plan = ModelPlan(model=model, selected=True, reason="selected")
    shared = shared_field_names(source_schema, target_schema)
    fetch_fields = list(dict.fromkeys([*source_schema.key_fields, *shared]))
    target_fetch_fields = list(dict.fromkeys([*target_schema.key_fields, *shared]))
    plan.dropped_fields = sorted(
        name for name in source_schema.readable
        if name not in target_schema.writable and name not in SYSTEM_TIMESTAMP_FIELDS
    )
    plan.unwritable_timestamps = sorted(
        name for name in SYSTEM_TIMESTAMP_FIELDS
        if name in source_schema.readable and name not in target_schema.writable
    )
    key_candidates = composite_sort_key_candidates(target_schema, shared)
    compare_fields = comparison_field_names(shared, source_schema.key_fields)
    hash_fields = [name for name in shared if name not in SYSTEM_TIMESTAMP_FIELDS]

    target_by_key: dict[str, dict[str, Any]] = {}
    for row in target.iterate_rows(model, target_fetch_fields):
        target_by_key[row_key(target_schema, row)] = row
    plan.target_rows = len(target_by_key)
    seen_keys: set[str] = set()

    for row in source.iterate_rows(model, fetch_fields):
        plan.source_rows += 1
        key = row_key(source_schema, row)
        seen_keys.add(key)
        existing = target_by_key.get(key)
        applied_defaults: dict[str, str] = {}
        if existing is None:
            row, applied_defaults = with_key_field_defaults(model, row, key_candidates, key_field_defaults)
        source_projection = row_projection(source_schema.readable, row, hash_fields)
        plan.source_hashes[key] = row_hash(source_projection)
        problems = validate_row(target_schema, row)
        if existing is None:
            problems += unresolved_composite_sort_keys(target_schema, row)
        if problems:
            plan.invalid.append({"id": row_label(source_schema, row), "problems": problems})
            continue
        if existing is None:
            if applied_defaults:
                plan.key_defaulted_rows += 1
                plan.key_default_values.update(applied_defaults)
            plan.created.append(row_label(source_schema, row))
            plan.pending_creates.append(
                {name: row[name] for name in shared if row.get(name) is not None}
            )
            continue
        changed = [
            name for name in compare_fields
            if normalize_value(source_schema.readable.get(name), row.get(name)) is not None
            and normalize_value(source_schema.readable.get(name), row.get(name))
            != normalize_value(target_schema.writable.get(name), existing.get(name))
        ]
        if not changed:
            plan.unchanged += 1
            continue
        plan.updated.append(row_label(source_schema, row))
        update_row = {name: row[name] for name in source_schema.key_fields}
        update_row.update({name: row[name] for name in changed})
        plan.pending_updates.append(update_row)

    plan.target_only_rows = len([key for key in target_by_key if key not in seen_keys])
    for key, row in target_by_key.items():
        plan.target_hashes[key] = row_hash(row_projection(target_schema.writable, row, hash_fields))
    return plan


def count_rows(backend: RowBackend, model: str) -> int:
    schema = backend.schema(model)
    return sum(1 for _ in backend.iterate_rows(model, list(schema.key_fields)))


def plan_skipped_model(model: str, reason: str, source: RowBackend, target: RowBackend, target_models: list[str]) -> ModelPlan:
    plan = ModelPlan(model=model, selected=False, reason=reason)
    plan.source_rows = count_rows(source, model)
    plan.target_rows = count_rows(target, model) if model in target_models else None
    return plan


def objects_differ(source_object: ObjectInfo, target_object: ObjectInfo) -> bool:
    if source_object.size != target_object.size:
        return True
    comparable = (
        MULTIPART_ETAG_MARKER not in source_object.etag
        and MULTIPART_ETAG_MARKER not in target_object.etag
    )
    return comparable and source_object.etag != target_object.etag


def top_level_prefix(key: str) -> str:
    head, separator, _rest = key.partition("/")
    return f"{head}/" if separator else key


def normalize_prefix(prefix: str) -> str:
    return prefix if prefix.endswith("/") else f"{prefix}/"


def plan_objects(
    source_objects: list[ObjectInfo],
    target_objects: list[ObjectInfo],
    selected_prefixes: list[str],
    selected_keys: list[str] | None = None,
) -> tuple[list[PrefixPlan], int]:
    normalized = [normalize_prefix(prefix) for prefix in selected_prefixes]
    exact_keys = set(selected_keys or [])
    target_by_key = {entry.key: entry for entry in target_objects}
    plans: dict[str, PrefixPlan] = {}
    for entry in source_objects:
        top = top_level_prefix(entry.key)
        plan = plans.setdefault(top, PrefixPlan(prefix=top))
        plan.source_objects += 1
        plan.source_bytes += entry.size
        if entry.key not in exact_keys and not any(entry.key.startswith(prefix) for prefix in normalized):
            continue
        plan.selected = True
        plan.selected_objects += 1
        existing = target_by_key.get(entry.key)
        if existing is None:
            plan.to_copy_missing.append(entry.key)
            plan.bytes_to_copy += entry.size
        elif objects_differ(entry, existing):
            plan.to_copy_different.append(entry.key)
            plan.bytes_to_copy += entry.size
        else:
            plan.unchanged += 1
    for entry in target_objects:
        top = top_level_prefix(entry.key)
        plans.setdefault(top, PrefixPlan(prefix=top)).target_objects += 1
    for plan in plans.values():
        plan.reason = "selected" if plan.selected else NOT_SELECTED_REASON
    source_keys = {entry.key for entry in source_objects}
    target_only = len([entry for entry in target_objects if entry.key not in source_keys])
    return [plans[name] for name in sorted(plans)], target_only


def build_plan(
    source: RowBackend,
    target: RowBackend,
    *,
    requested_models: list[str] | None,
    source_store: ObjectStore | None,
    target_store: ObjectStore | None,
    selected_prefixes: list[str],
    selected_keys: list[str] | None = None,
    key_field_defaults: dict[str, str] | None = None,
    source_account: str | None = None,
    target_account: str | None = None,
) -> CopyPlan:
    defaults = {**BUILTIN_KEY_FIELD_DEFAULTS, **(key_field_defaults or {})}
    source_models = source.model_names()
    target_models = target.model_names()
    selected = resolve_selected_models(requested_models, source_models, target_models)
    plans: list[ModelPlan] = []
    ordered = [*selected, *[name for name in sorted(source_models) if name not in selected]]
    for model in ordered:
        if model in selected:
            plans.append(plan_selected_model(model, source, target, defaults))
        else:
            reason = IDENTITY_REASON if model in IDENTITY_MODELS else NOT_SELECTED_REASON
            plans.append(plan_skipped_model(model, reason, source, target, target_models))
    plan = CopyPlan(models=plans, prefixes=[], source_account=source_account, target_account=target_account)
    if source_store is not None and target_store is not None:
        plan.source_objects = source_store.list_objects()
        plan.target_objects = target_store.list_objects()
        plan.prefixes, plan.extra_target_only_objects = plan_objects(
            plan.source_objects, plan.target_objects, selected_prefixes, selected_keys
        )
        source_keys = {entry.key for entry in plan.source_objects}
        plan.errors += [f"S3 key not found in the source: {key}" for key in selected_keys or [] if key not in source_keys]
    return plan


def apply_plan(
    plan: CopyPlan,
    target: RowBackend,
    source_store: ObjectStore | None,
    target_store: ObjectStore | None,
    *,
    workers: int = 1,
    progress: Callable[[int, int, int], None] | None = None,
) -> None:
    if plan.invalid_row_count:
        raise CopyRefused(
            f"{plan.invalid_row_count} row(s) would be rejected by the target schema; "
            "nothing was written. Fix or exclude them first."
        )
    if workers < 1:
        raise CopyRefused("The number of S3 workers must be at least 1.")
    plan.applied = True
    for model_plan in plan.models:
        for row in model_plan.pending_creates:
            try:
                target.create_row(model_plan.model, row)
                model_plan.written_created += 1
            except Exception as error:
                model_plan.errors.append(f"create failed: {error}")
        for row in model_plan.pending_updates:
            try:
                target.update_row(model_plan.model, row)
                model_plan.written_updated += 1
            except Exception as error:
                model_plan.errors.append(f"update failed: {error}")
    if source_store is None or target_store is None:
        return
    copy_planned_objects(plan, source_store, target_store, workers, progress)


def copy_planned_objects(
    plan: CopyPlan,
    source_store: ObjectStore,
    target_store: ObjectStore,
    workers: int,
    progress: Callable[[int, int, int], None] | None,
) -> None:
    size_by_key = {entry.key: entry.size for entry in plan.source_objects}
    jobs = [
        (prefix_plan, key)
        for prefix_plan in plan.prefixes
        for key in [*prefix_plan.to_copy_missing, *prefix_plan.to_copy_different]
    ]
    lock = threading.Lock()
    finished = {"objects": 0, "bytes": 0}

    def copy_one(job: tuple[PrefixPlan, str]) -> None:
        prefix_plan, key = job
        try:
            warning = target_store.copy_object_from(source_store, key)
            with lock:
                prefix_plan.copied += 1
                if warning:
                    prefix_plan.warnings.append(f"{key}: {warning}")
        except Exception as error:
            with lock:
                prefix_plan.errors.append(f"copy failed for {key}: {error}")
        with lock:
            finished["objects"] += 1
            finished["bytes"] += size_by_key.get(key, 0)
            snapshot = (finished["objects"], len(jobs), finished["bytes"])
        if progress is not None:
            progress(*snapshot)

    if workers == 1:
        for job in jobs:
            copy_one(job)
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(copy_one, jobs))


def render_table(plan: CopyPlan) -> str:
    lines = []
    if plan.source_account or plan.target_account:
        lines.append(f"source account {plan.source_account or '-'}, target account {plan.target_account or '-'}")
    lines += [
        f"{'model':<24}{'action':<6}{'source':>8}{'target':>8}{'create':>8}{'update':>8}{'same':>8}{'invalid':>8}  note",
    ]
    for entry in plan.models:
        target_rows = "-" if entry.target_rows is None else str(entry.target_rows)
        note = entry.reason if not entry.selected else ""
        if entry.selected and entry.dropped_fields:
            note = "target lacks: " + ",".join(entry.dropped_fields)
        if entry.selected and entry.key_defaulted_rows:
            defaults_text = ",".join(f"{name}={value}" for name, value in sorted(entry.key_default_values.items()))
            note = (note + "; " if note else "") + f"{entry.key_defaulted_rows} rows get key defaults: {defaults_text}"
        if entry.selected and entry.target_only_rows:
            note = (note + "; " if note else "") + f"{entry.target_only_rows} target-only rows kept"
        lines.append(
            f"{entry.model:<24}{'copy' if entry.selected else 'skip':<6}{entry.source_rows:>8}{target_rows:>8}"
            f"{len(entry.created):>8}{len(entry.updated):>8}{entry.unchanged:>8}{len(entry.invalid):>8}  {note}"
        )
    if plan.prefixes:
        lines.append("")
        lines.append(
            f"{'s3 prefix':<24}{'action':<6}{'objects':>8}{'MB':>8}{'target':>8}{'missing':>8}{'differ':>8}{'same':>8}  note"
        )
        for entry in plan.prefixes:
            megabytes = f"{entry.source_bytes / 1_000_000:.1f}"
            note = entry.reason if not entry.selected else f"{entry.bytes_to_copy / 1_000_000:.1f} MB to copy"
            lines.append(
                f"{entry.prefix:<24}{'copy' if entry.selected else 'skip':<6}{entry.source_objects:>8}{megabytes:>8}"
                f"{entry.target_objects:>8}{len(entry.to_copy_missing):>8}{len(entry.to_copy_different):>8}{entry.unchanged:>8}  {note}"
            )
        lines.append(f"target-only objects (never deleted): {plan.extra_target_only_objects}")
    return "\n".join(lines)


def dump_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_side_manifest(directory: Path, plan: CopyPlan, side: str) -> None:
    models_directory = directory / "models"
    s3_directory = directory / "s3"
    models_directory.mkdir(parents=True, exist_ok=True)
    s3_directory.mkdir(parents=True, exist_ok=True)
    hashes_attribute = "source_hashes" if side == "source" else "target_hashes"
    rows_attribute = "source_rows" if side == "source" else "target_rows"
    counts = {entry.model: getattr(entry, rows_attribute) for entry in plan.models if getattr(entry, rows_attribute) is not None}
    manifest = {
        entry.model: dict(sorted(getattr(entry, hashes_attribute).items()))
        for entry in plan.models
        if entry.selected
    }
    (models_directory / "counts.json").write_text(dump_json({"counts": dict(sorted(counts.items()))}))
    (models_directory / "content-manifest.json").write_text(dump_json(manifest))
    objects = sorted(plan.source_objects if side == "source" else plan.target_objects, key=lambda entry: entry.key)
    (s3_directory / "media-manifest.json").write_text(
        json.dumps([{"key": o.key, "size": o.size, "etag": o.etag} for o in objects], indent=1) + "\n"
    )
    (s3_directory / "keys.json").write_text(
        json.dumps([{"key": o.key, "size": o.size} for o in objects], indent=1) + "\n"
    )
    summary: dict[str, dict[str, int]] = {}
    for entry in objects:
        item = summary.setdefault(top_level_prefix(entry.key).rstrip("/"), {"objects": 0, "bytes": 0})
        item["objects"] += 1
        item["bytes"] += entry.size
    (s3_directory / "prefix-summary.json").write_text(dump_json(summary))


def write_manifests(directory: Path, plan: CopyPlan) -> None:
    write_side_manifest(directory / "source", plan, "source")
    write_side_manifest(directory / "target", plan, "target")
