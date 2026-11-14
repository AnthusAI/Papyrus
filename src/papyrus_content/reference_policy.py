from __future__ import annotations

import json
import re
from typing import Any

REFERENCE_CURATION_STATUSES = frozenset({"pending", "accepted", "rejected", "archived"})
REFERENCE_REJECTION_REASON_CODES = frozenset(
    {
        "out_of_scope",
        "policy_exclusion",
        "duplicate",
        "low_quality",
        "unavailable",
        "provenance",
        "other",
    }
)
SCOPE_TRAINING_NEGATIVE_REASON_CODES = frozenset({"out_of_scope", "policy_exclusion"})


def normalize_policy_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def normalize_reference_curation_status(value: Any, default_status: str = "pending") -> str:
    normalized = normalize_policy_token(value if value is not None else default_status)
    if normalized in {"accepted", "accept", "ready", "trusted"}:
        return "accepted"
    if normalized in {"rejected", "reject", "discarded"}:
        return "rejected"
    if normalized in {"archived", "archive"}:
        return "archived"
    return "pending"


def is_current_accepted_reference(reference: dict[str, Any] | None) -> bool:
    if not reference:
        return False
    return (
        reference.get("versionState") == "current"
        and normalize_reference_curation_status(reference.get("curationStatus")) == "accepted"
    )


def normalize_reference_rejection_reason_code(value: Any, *, required: bool = False) -> str | None:
    normalized = normalize_policy_token(value)
    if not normalized:
        if required:
            raise ValueError("--reason-code or --note is required for rejected references.")
        return None
    if normalized not in REFERENCE_REJECTION_REASON_CODES:
        raise ValueError(
            f"Unsupported reference rejection reason code '{value}'. "
            f"Use one of: {', '.join(sorted(REFERENCE_REJECTION_REASON_CODES))}."
        )
    return normalized


def reference_reason_code(reference: dict[str, Any] | None) -> str | None:
    """The reason code of the Reference's latest vote (``curationReasonCode``), else one recorded in its metadata."""
    reason = _reason_code_from_metadata({"reasonCode": (reference or {}).get("curationReasonCode")})
    return reason or _reason_code_from_metadata((reference or {}).get("metadata"))


def scope_training_label_for_reference(reference: dict[str, Any] | None) -> str | None:
    if not reference or reference.get("versionState") != "current":
        return None
    status = normalize_reference_curation_status(reference.get("curationStatus"))
    if status == "accepted":
        return "positive"
    if status != "rejected":
        return None
    reason_code = reference_reason_code(reference)
    return "negative" if reason_code in SCOPE_TRAINING_NEGATIVE_REASON_CODES else None


def _reason_code_from_metadata(metadata: Any) -> str | None:
    parsed = _parse_metadata(metadata)
    return normalize_reference_rejection_reason_code(
        parsed.get("reasonCode")
        or parsed.get("reason_code")
        or parsed.get("curationReasonCode")
        or parsed.get("curation_reason_code")
        or parsed.get("rejectionReasonCode")
        or parsed.get("rejection_reason_code")
    )


def _parse_metadata(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
