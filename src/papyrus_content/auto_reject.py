"""Automatic rejection of clear misses: opt in, bounded, audited and reversible.

The relevance cyclotron may move a still-pending Reference to rejected only when
the publication switched ``autoReject`` on, the approved-proof gate allows
rejecting clear misses, and the decision for the negative label is at least as
sure as the configured probability. It never accepts. A person who already
touched the Reference is never overruled, and every rejection is a curation
vote recorded on the Reference whose actor kind is ``cyclotron``, so it never counts as a human label
and a person can reverse it like any other curation.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .auto_decision_gate import AUTO_REJECT_CLEAR_MISSES
from .reference_vote import CYCLOTRON, vote_fields

CYCLOTRON_CURATION_ACTOR_KIND = CYCLOTRON
AUTO_REJECT_REASON_CODE = "out_of_scope"


def clear_miss_probability(auto_reject: Mapping[str, Any], gate: Mapping[str, Any], *, label: str,
                           probabilities: Mapping[str, float], labels: Sequence[str], positive_label: str) -> float | None:
    """The reject probability when this decision may be rejected automatically, else None."""
    if not auto_reject.get("enabled"):
        return None
    if not gate.get("allowed") or gate.get("scope") != AUTO_REJECT_CLEAR_MISSES:
        return None
    (negative_label,) = [candidate for candidate in labels if candidate != positive_label]
    if label != negative_label:
        return None
    probability = probabilities.get(negative_label)
    if probability is None or probability < auto_reject["minimumRejectProbability"]:
        return None
    return float(probability)


def auto_rejection_reason(*, cyclotron_id: str, probability: float, proof_id: str) -> str:
    return (f"Rejected automatically by the {cyclotron_id} cyclotron: {probability:.1%} sure this is not relevant, "
            f"under approved proof {proof_id}. A person can reopen it.")


def reject_reference_automatically(client, reference: Mapping[str, Any], *, cyclotron_id: str, probability: float,
                                   proof_id: str, decision_id: str, now: str) -> bool:
    """Reject one still-pending Reference, recording the vote on it. False when it is no longer pending."""
    current = client.get_record("Reference", reference["id"])
    if not current or current.get("versionState") != "current" or current.get("curationStatus") != "pending":
        return False
    reason = auto_rejection_reason(cyclotron_id=cyclotron_id, probability=probability, proof_id=proof_id)
    actor_label = f"Relevance cyclotron ({cyclotron_id})"
    # The vote is recorded on the Reference itself; Messages come only from people. The decision lives in the relevance relation.
    client.update_record("Reference", {
        "id": reference["id"], "curationStatus": "rejected",
        "curationStatusKey": f"{current['corpusId']}#rejected", "curationStatusUpdatedAt": now,
        "curationStatusUpdatedBy": actor_label, "curationStatusReason": reason,
        **vote_fields(CYCLOTRON_CURATION_ACTOR_KIND, reason_code=AUTO_REJECT_REASON_CODE), "updatedAt": now})
    return True
