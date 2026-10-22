from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .env import resolve_corpora_file
from .ids import safe_id

DEFAULT_RELATION_TYPES_PATH = resolve_corpora_file("corpora/papyrus-semantic-relation-types.yml")

RELATION_DOMAINS = frozenset(
    {
        "knowledge",
        "editorial",
        "commentary",
        "workflow",
        "evidence",
        "publication",
        "ontology",
        "generic",
        "classification",
        "curation",
        "summarization",
    }
)


def normalize_relation_type_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return normalized.strip("_")


def normalize_string_array(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(entry or "").strip() for entry in value if str(entry or "").strip()]


def string_or_default(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def normalize_semantic_relation_type_seed(entry: dict[str, Any], index: int, filepath: Path) -> dict[str, Any]:
    key = normalize_relation_type_key(entry.get("key"))
    if not key:
        raise ValueError(f"Relation type at index {index} in {filepath} is missing key.")
    domain = string_or_default(entry.get("domain"), "generic")
    if domain not in RELATION_DOMAINS:
        raise ValueError(f"Relation type {key} in {filepath} has unsupported domain {domain}.")
    return {
        "key": key,
        "label": string_or_default(entry.get("label"), key.replace("_", " ")),
        "inverseLabel": string_or_default(
            entry.get("inverseLabel"),
            string_or_default(entry.get("label"), key.replace("_", " ")),
        ),
        "description": string_or_default(entry.get("description"), ""),
        "domain": domain,
        "status": string_or_default(entry.get("status"), "active"),
        "allowedSubjectKinds": normalize_string_array(entry.get("allowedSubjectKinds")),
        "allowedObjectKinds": normalize_string_array(entry.get("allowedObjectKinds")),
        "isDirectional": bool(entry.get("isDirectional", True)),
        "isSymmetric": bool(entry.get("isSymmetric")),
        "isTransitive": bool(entry.get("isTransitive")),
        "contextPackTags": normalize_string_array(entry.get("contextPackTags")),
        "createdAt": entry.get("createdAt") if isinstance(entry.get("createdAt"), str) else None,
        "metadata": entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {},
    }


def load_semantic_relation_type_seeds(filepath: str | Path | None = None) -> list[dict[str, Any]]:
    path = Path(filepath) if filepath else DEFAULT_RELATION_TYPES_PATH
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or parsed.get("schemaVersion") != 1 or not isinstance(parsed.get("relationTypes"), list):
        raise ValueError(f"Invalid semantic relation type seed file: {path}")
    return [
        normalize_semantic_relation_type_seed(entry, index, path)
        for index, entry in enumerate(parsed["relationTypes"])
        if isinstance(entry, dict)
    ]


@lru_cache(maxsize=4)
def load_relation_type_lookup(filepath: str | None = None) -> dict[str, dict[str, Any]]:
    types = load_semantic_relation_type_seeds(filepath)
    return {entry["key"]: entry for entry in types}


def semantic_relation_type_id_for(key: str) -> str:
    return f"semantic-relation-type-{safe_id(key)}"


def semantic_relation_type_fields_for_predicate(
    predicate: str,
    types: list[dict[str, Any]] | None = None,
) -> dict[str, str | None]:
    lookup = {entry["key"]: entry for entry in types} if types is not None else load_relation_type_lookup()
    key = normalize_relation_type_key(predicate)
    relation_type = lookup.get(key)
    if relation_type is None:
        return {"relationTypeKey": key, "relationDomain": "generic"}
    return {
        "relationTypeId": semantic_relation_type_id_for(relation_type["key"]),
        "relationTypeKey": relation_type["key"],
        "relationDomain": relation_type.get("domain") or "generic",
    }


def semantic_relation_type_record(type_entry: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    timestamp = now or _utc_now()
    return {
        "id": semantic_relation_type_id_for(type_entry["key"]),
        "key": type_entry["key"],
        "label": type_entry["label"],
        "inverseLabel": type_entry["inverseLabel"],
        "description": type_entry["description"],
        "domain": type_entry["domain"],
        "status": type_entry["status"],
        "allowedSubjectKinds": type_entry["allowedSubjectKinds"],
        "allowedObjectKinds": type_entry["allowedObjectKinds"],
        "isDirectional": type_entry["isDirectional"],
        "isSymmetric": type_entry["isSymmetric"],
        "isTransitive": type_entry["isTransitive"],
        "contextPackTags": type_entry["contextPackTags"],
        "createdAt": type_entry.get("createdAt") or timestamp,
        "updatedAt": timestamp,
        "metadata": json.dumps(type_entry.get("metadata") or {}),
    }


def build_semantic_relation_type_records(
    types: list[dict[str, Any]],
    *,
    now: str | None = None,
) -> list[dict[str, Any]]:
    timestamp = now or _utc_now()
    return [
        {
            "modelName": "SemanticRelationType",
            "expected": semantic_relation_type_record(type_entry, now=timestamp),
        }
        for type_entry in types
    ]


def relation_type_fields_equal(relation: dict[str, Any], expected: dict[str, Any]) -> bool:
    return (
        (relation.get("relationTypeId") or None) == (expected.get("relationTypeId") or None)
        and (relation.get("relationTypeKey") or None) == (expected.get("relationTypeKey") or None)
        and (relation.get("relationDomain") or None) == (expected.get("relationDomain") or None)
    )


def build_semantic_relation_backfill_records(
    relations: list[dict[str, Any]],
    types: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    seed_types = types if types is not None else load_semantic_relation_type_seeds()
    changes: list[dict[str, Any]] = []
    for relation in relations:
        predicate = relation.get("relationTypeKey") or relation.get("predicate")
        fields = semantic_relation_type_fields_for_predicate(str(predicate or ""), seed_types)
        expected = {
            "id": relation["id"],
            "relationTypeId": fields.get("relationTypeId"),
            "relationTypeKey": fields.get("relationTypeKey"),
            "relationDomain": fields.get("relationDomain"),
        }
        changes.append(
            {
                "modelName": "SemanticRelation",
                "expected": expected,
                "current": relation,
                "unknownType": not fields.get("relationTypeId"),
                "action": "noop" if relation_type_fields_equal(relation, expected) else "update",
            }
        )
    return changes


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
