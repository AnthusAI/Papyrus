"""The gate between suggesting and deciding: no automatic decision without a fresh, human-approved proof.

An approved proof is a cross-validated report a person committed through the
reviewed approval flow. It authorizes automatic decisions only while it is
fresh: few labels have arrived since it was run and it is not too old. Even
then the widest permission is rejecting clear misses; accepting is never
automatic.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

DEFAULT_NEW_LABELS_BEFORE_REPROOF = 10
DEFAULT_PROOF_MAXIMUM_AGE_DAYS = 30
AUTO_REJECT_CLEAR_MISSES = "reject-clear-misses"
MINIMUM_PROOF_AGREEMENT_AT_FULL_LABELS = 0.9


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_approved_proof(path: str | None) -> Mapping[str, Any] | None:
    if not path:
        return None
    proof_file = Path(path)
    return json.loads(proof_file.read_text(encoding="utf-8")) if proof_file.exists() else None


def labels_at_proof_time(approved_proof: Mapping[str, Any]) -> int:
    return int((approved_proof.get("heldOut") or {}).get("size") or 0)


def proof_is_due(approved_proof: Mapping[str, Any] | None, *, human_label_count: int, now: str,
                 new_labels_before_reproof: int = DEFAULT_NEW_LABELS_BEFORE_REPROOF,
                 maximum_age_days: int = DEFAULT_PROOF_MAXIMUM_AGE_DAYS) -> str | None:
    """Why a new proof should be run as a draft, or None when the approved proof is still fresh."""
    if approved_proof is None:
        return "no approved proof"
    new_labels = human_label_count - labels_at_proof_time(approved_proof)
    if new_labels >= new_labels_before_reproof:
        return f"{new_labels} new human labels since the approved proof"
    age_days = (_instant(now) - _instant(str(approved_proof["ranAt"]))).days
    if age_days > maximum_age_days:
        return f"approved proof is {age_days} days old"
    return None


def auto_decision_gate(approved_proof: Mapping[str, Any] | None, *, human_label_count: int, now: str,
                       new_labels_before_reproof: int = DEFAULT_NEW_LABELS_BEFORE_REPROOF,
                       maximum_age_days: int = DEFAULT_PROOF_MAXIMUM_AGE_DAYS) -> dict[str, Any]:
    """What automatic decisions are allowed right now, and the reason when none are."""
    stale_reason = proof_is_due(approved_proof, human_label_count=human_label_count, now=now,
                                new_labels_before_reproof=new_labels_before_reproof,
                                maximum_age_days=maximum_age_days)
    if stale_reason is not None:
        return {"allowed": False, "scope": None, "reason": stale_reason, "humanLabelCount": human_label_count}
    final_agreement = approved_proof["points"][-1]["agreement"]
    if final_agreement is None or final_agreement < MINIMUM_PROOF_AGREEMENT_AT_FULL_LABELS:
        return {"allowed": False, "scope": None, "humanLabelCount": human_label_count,
                "reason": f"approved proof agreement {final_agreement} is below {MINIMUM_PROOF_AGREEMENT_AT_FULL_LABELS}"}
    return {"allowed": True, "scope": AUTO_REJECT_CLEAR_MISSES, "reason": None,
            "proofId": approved_proof["proofId"], "humanLabelCount": human_label_count}
