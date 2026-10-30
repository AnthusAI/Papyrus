"""Shadow mode for the relevance cyclotron: suggestions beside what editors actually decided.

A cyclotron decision is a suggestion. It never changes a Reference's curation
status. When an editor later accepts or rejects the Reference, the suggestion
and the editor's own decision sit side by side, and only decisions made before
the editor's review count towards live agreement, and only reviews a person
explicitly made.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .catalog import _record
from .ids import safe_id
from .reference_vote import latest_vote
from .relevance_decisions import human_label_for_review

SHADOW_AGREEMENT_PAYLOAD_KIND = "cyclotron-shadow-agreement"
USAGE_PAYLOAD_KIND = "cyclotron-usage"
SHADOW_AGREEMENT_SCHEMA = "cyclotron-shadow-agreement/v1"


def shadow_agreement_payload_id(cyclotron_id: str) -> str:
    return f"knowledge-raw-payload-cyclotron-shadow-agreement-{safe_id(cyclotron_id)}"


def usage_payload_id(cyclotron_id: str) -> str:
    return f"knowledge-raw-payload-cyclotron-usage-{safe_id(cyclotron_id)}"


def live_agreement(comparisons: Sequence[Mapping[str, Any]], *, positive_label: str, now: str) -> dict[str, Any]:
    """Agreement of suggestions with human decisions made after them, for one publication."""
    from .priming_proof import agreement_metrics

    outcomes = [(comparison["editorLabel"], comparison["suggestedLabel"]) for comparison in comparisons]
    return {"schema": SHADOW_AGREEMENT_SCHEMA, "positiveLabel": positive_label, "computedAt": now,
            "comparisons": len(outcomes), **agreement_metrics(outcomes, positive_label=positive_label)}


def comparison_of_suggestion_with_human_decision(reference: Mapping[str, Any], decision_relation: Mapping[str, Any],
                                                 *, labels: Sequence[str]) -> dict[str, Any] | None:
    """The suggestion and the editor's label, or None when it is not an honest comparison.

    Not honest: no human label, or the suggestion was made after the editor reviewed.
    """
    editor_label = human_label_for_review(reference, labels=labels)
    if editor_label is None:
        return None
    metadata = json.loads(decision_relation.get("metadata") or "{}")
    suggested_at = str(metadata.get("decidedAt") or decision_relation.get("importedAt") or "")
    reviewed_at = str(latest_vote(reference)["createdAt"] or "")
    if not suggested_at or not reviewed_at or suggested_at >= reviewed_at:
        return None
    return {"referenceLineageId": reference["lineageId"], "suggestedLabel": metadata.get("label"),
            "editorLabel": editor_label, "suggestedAt": suggested_at, "reviewedAt": reviewed_at,
            "version": metadata.get("version")}


def shadow_agreement_record(cyclotron_id: str, agreement: Mapping[str, Any], *, now: str) -> dict[str, Any]:
    return _record("KnowledgeRawPayload", {
        "id": shadow_agreement_payload_id(cyclotron_id),
        "ownerType": "cyclotron",
        "ownerId": safe_id(cyclotron_id),
        "payloadKind": SHADOW_AGREEMENT_PAYLOAD_KIND,
        "createdAt": now,
        "updatedAt": now,
        "payload": json.dumps(dict(agreement), sort_keys=True),
    })


def usage_record(cyclotron_id: str, *, day: str, decisions: int, now: str) -> dict[str, Any]:
    return _record("KnowledgeRawPayload", {
        "id": usage_payload_id(cyclotron_id),
        "ownerType": "cyclotron",
        "ownerId": safe_id(cyclotron_id),
        "payloadKind": USAGE_PAYLOAD_KIND,
        "createdAt": now,
        "updatedAt": now,
        "payload": json.dumps({"day": day, "decisions": decisions}, sort_keys=True),
    })


def decisions_remaining_today(recorded_usage: Mapping[str, Any] | None, *, maximum_per_day: int | None,
                              today: str) -> int | None:
    """How many more decisions today's cap allows; None when the publication has no cap."""
    if maximum_per_day is None:
        return None
    used = int(recorded_usage["decisions"]) if recorded_usage and recorded_usage.get("day") == today else 0
    return max(0, maximum_per_day - used)


def utc_day(instant: str) -> str:
    return datetime.fromisoformat(instant.replace("Z", "+00:00")).astimezone(timezone.utc).date().isoformat()


def reproducibility_provenance(plan, cyclotron) -> dict[str, Any]:
    """What produced a suggestion beyond the model version: the labels in play and the doctrine behind the rubric."""
    classifier = plan.definition.classifiers[0]
    taught = sorted((str(row["item"].id), str(row["label"])) for row in cyclotron.labels())
    primed = sorted(str(identifier) for addition in cyclotron.priming_additions()
                    for identifiers in addition.get("examples", {}).values() for identifier in identifiers)
    doctrine = json.dumps({"rubrics": dict(plan.seed_rubrics), "question": classifier.question,
                           "labels": list(classifier.labels)}, sort_keys=True)
    return {
        "labelSet": list(classifier.labels),
        "doctrineFingerprint": hashlib.sha256(doctrine.encode("utf-8")).hexdigest()[:16],
        "teachingFingerprint": hashlib.sha256(json.dumps([taught, primed]).encode("utf-8")).hexdigest()[:16],
        "teachingLabels": len(taught),
        "primingExamples": len(primed),
    }
