"""Automatic rejection of clear misses: opt in, bounded, audited and reversible.

The relevance cyclotron may move a still-pending Reference to rejected only when
the publication switched ``autoReject`` on, the approved-proof gate allows
rejecting clear misses, and the decision for the negative label is at least as
sure as the configured probability. It never accepts. A person who already
touched the Reference is never overruled, and every rejection is a curation
Message whose actor kind is ``cyclotron``, so it never counts as a human label
and a person can reverse it like any other curation.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from .auto_decision_gate import AUTO_REJECT_CLEAR_MISSES
from .catalog import semantic_relation_record
from .ids import hash_short, safe_id

CYCLOTRON_CURATION_ACTOR_KIND = "cyclotron"
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
    """Reject one still-pending Reference with an audited curation Message. False when it is no longer pending."""
    current = client.get_record("Reference", reference["id"])
    if not current or current.get("versionState") != "current" or current.get("curationStatus") != "pending":
        return False
    lineage_id = reference.get("lineageId") or reference["id"]
    reason = auto_rejection_reason(cyclotron_id=cyclotron_id, probability=probability, proof_id=proof_id)
    actor_label = f"Relevance cyclotron ({cyclotron_id})"
    message_id = f"message-reference-curation-{safe_id(lineage_id)}-auto-reject-{hash_short([decision_id])}"
    metadata = {"action": "reject", "curationStatus": "rejected", "reasonCode": AUTO_REJECT_REASON_CODE,
                "referenceId": reference["id"], "referenceLineageId": lineage_id,
                "actorKind": CYCLOTRON_CURATION_ACTOR_KIND, "automatic": True, "cyclotronId": cyclotron_id,
                "probability": probability, "proofId": proof_id, "decisionId": decision_id}
    client.update_record("Reference", {
        "id": reference["id"], "curationStatus": "rejected",
        "curationStatusKey": f"{current['corpusId']}#rejected", "curationStatusUpdatedAt": now,
        "curationStatusUpdatedBy": actor_label, "curationStatusReason": reason, "updatedAt": now})
    client.upsert("Message", {
        "id": message_id, "messageKind": "reference_curation", "messageDomain": "commentary", "status": "active",
        "summary": f"{current.get('title') or lineage_id}: rejected", "source": "cyclotron",
        "authorLabel": actor_label, "content": reason, "responseTarget": "none", "responseStatus": "COMPLETED",
        "responseOwner": "papyrus-relevance-cyclotron", "metadata": json.dumps(metadata, sort_keys=True),
        "createdAt": now, "updatedAt": now, "newsroomFeedKey": "messages"})
    relation = semantic_relation_record({
        "predicate": "comment", "subjectKind": "message", "subjectId": message_id, "subjectLineageId": message_id,
        "subjectVersionNumber": 1, "objectKind": "reference", "objectId": reference["id"],
        "objectLineageId": lineage_id, "objectVersionNumber": reference.get("versionNumber"),
        "importedAt": now, "metadata": {"action": "reject", "curationStatus": "rejected",
                                        "messageKind": "reference_curation"}})["expected"]
    client.upsert("SemanticRelation", relation)
    return True
