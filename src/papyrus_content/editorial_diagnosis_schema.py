from __future__ import annotations

import re
from typing import Any

from .editorial_style import _FORBIDDEN_KEY_PATTERN
from .ids import hash_short

SCHEMA_VERSION = 1

REQUIRED_TOP_LEVEL_KEYS = (
    "schemaVersion",
    "document_intent",
    "audience",
    "generic_passages",
    "unsupported_claims",
    "repetition_groups",
    "voice_observations",
    "required_facts",
)

FINDING_ARRAY_KEYS = (
    "generic_passages",
    "unsupported_claims",
    "voice_observations",
    "required_facts",
)

FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "revised_text",
        "rewritten_prose",
        "revisedProse",
        "options",
        "patches",
        "revisedText",
        "embedder",
    }
)

FINDING_DECISIONS = frozenset({"skip", "rewrite", "delete", "keep", "add"})

STABLE_ID_PATTERN = re.compile(r"^finding-[a-f0-9]{16}$")


class EditorialDiagnosisValidationError(ValueError):
    """Raised when diagnostic JSON fails schema validation."""


def stable_finding_id(kind: str, draft_text: str, start: int, end: int) -> str:
    excerpt = draft_text[start:end].strip()
    return f"finding-{hash_short([SCHEMA_VERSION, kind, start, end, excerpt])}"


def stable_repetition_group_id(member_ids: list[str]) -> str:
    return f"finding-{hash_short([SCHEMA_VERSION, 'redundancy', sorted(member_ids)])}"


def assert_no_forbidden_output_keys(value: Any, key_path: str = "") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            current_path = f"{key_path}.{key_text}" if key_path else key_text
            if key_text in FORBIDDEN_OUTPUT_KEYS:
                raise EditorialDiagnosisValidationError(
                    f"Diagnostic JSON contains forbidden rewrite field '{current_path}'"
                )
            normalized = re.sub(r"[^a-z0-9]", "", key_text.lower())
            if _FORBIDDEN_KEY_PATTERN.search(normalized):
                raise EditorialDiagnosisValidationError(
                    f"Diagnostic JSON contains forbidden detector-score field '{current_path}'"
                )
            assert_no_forbidden_output_keys(nested, current_path)
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            assert_no_forbidden_output_keys(nested, f"{key_path}[{index}]")


def validate_diagnosis(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise EditorialDiagnosisValidationError("Diagnostic JSON must be a mapping.")

    assert_no_forbidden_output_keys(payload)

    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise EditorialDiagnosisValidationError(
            f"Unsupported schemaVersion: expected {SCHEMA_VERSION}."
        )

    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in payload]
    if missing:
        raise EditorialDiagnosisValidationError(f"Diagnostic JSON missing keys: {', '.join(missing)}")

    if not isinstance(payload.get("document_intent"), str) or not payload["document_intent"].strip():
        raise EditorialDiagnosisValidationError("document_intent must be a non-empty string.")
    if not isinstance(payload.get("audience"), str) or not payload["audience"].strip():
        raise EditorialDiagnosisValidationError("audience must be a non-empty string.")

    for array_key in FINDING_ARRAY_KEYS:
        entries = payload.get(array_key)
        if not isinstance(entries, list):
            raise EditorialDiagnosisValidationError(f"{array_key} must be a list.")
        for index, entry in enumerate(entries):
            _validate_finding(entry, f"{array_key}[{index}]")

    repetition_groups = payload.get("repetition_groups")
    if not isinstance(repetition_groups, list):
        raise EditorialDiagnosisValidationError("repetition_groups must be a list.")
    for index, group in enumerate(repetition_groups):
        _validate_repetition_group(group, f"repetition_groups[{index}]")

    density = payload.get("density")
    if density is not None:
        _validate_density(density)

    return payload


def _validate_density(density: Any) -> None:
    if not isinstance(density, dict):
        raise EditorialDiagnosisValidationError("density must be a mapping.")
    if "embedder" in density:
        raise EditorialDiagnosisValidationError("density must not include an embedder field.")
    for field in ("wordCount", "sentenceCount"):
        value = density.get(field)
        if not isinstance(value, int) or value < 0:
            raise EditorialDiagnosisValidationError(f"density.{field} must be a non-negative integer.")
    for field in ("lexicalDensity", "gzipRatio"):
        value = density.get(field)
        if not isinstance(value, (int, float)) or value < 0:
            raise EditorialDiagnosisValidationError(f"density.{field} must be a non-negative number.")


def _validate_finding(entry: Any, location: str) -> None:
    if not isinstance(entry, dict):
        raise EditorialDiagnosisValidationError(f"{location} must be a mapping.")
    finding_id = entry.get("id")
    if not isinstance(finding_id, str) or not STABLE_ID_PATTERN.match(finding_id):
        raise EditorialDiagnosisValidationError(f"{location}.id must match finding-<16 hex chars>.")
    for field in ("kind", "excerpt", "rationale"):
        if not isinstance(entry.get(field), str) or not str(entry[field]).strip():
            raise EditorialDiagnosisValidationError(f"{location}.{field} must be a non-empty string.")
    span = entry.get("span")
    if not isinstance(span, dict):
        raise EditorialDiagnosisValidationError(f"{location}.span must be a mapping.")
    for coord in ("start", "end"):
        if not isinstance(span.get(coord), int) or span[coord] < 0:
            raise EditorialDiagnosisValidationError(f"{location}.span.{coord} must be a non-negative integer.")
    if span["end"] < span["start"]:
        raise EditorialDiagnosisValidationError(f"{location}.span end must be >= start.")


def _validate_repetition_group(group: Any, location: str) -> None:
    if not isinstance(group, dict):
        raise EditorialDiagnosisValidationError(f"{location} must be a mapping.")
    group_id = group.get("id")
    if not isinstance(group_id, str) or not STABLE_ID_PATTERN.match(group_id):
        raise EditorialDiagnosisValidationError(f"{location}.id must match finding-<16 hex chars>.")
    if group.get("kind") != "redundancy":
        raise EditorialDiagnosisValidationError(f"{location}.kind must be redundancy.")
    members = group.get("members")
    if not isinstance(members, list) or not members:
        raise EditorialDiagnosisValidationError(f"{location}.members must be a non-empty list.")
    for index, member in enumerate(members):
        _validate_finding(member, f"{location}.members[{index}]")
    if not isinstance(group.get("rationale"), str) or not group["rationale"].strip():
        raise EditorialDiagnosisValidationError(f"{location}.rationale must be a non-empty string.")
