"""Relevance decisions and the cyclotron status, recorded in Papyrus's own models.

No new tables. A decision is a ``SemanticRelation`` with predicate
``relevance_decision_is`` from a ``Reference`` to the ``SemanticNode``
``relevance.<label>``. It reuses the relation's ``score`` (probability of the
positive label), ``confidence``, ``classifierId``, ``modelVersion`` (the
cyclotron version) and ``reviewRecommended`` fields. A newer decision
supersedes the older one. The cyclotron status snapshot is a
``KnowledgeRawPayload`` whose JSON lives in a ``raw_payload`` attachment, the
same pattern as the Newsroom summary snapshot.

Reviews stay the existing ``reviewReferenceCuration`` mutation and its
``reference_curation`` Message; ``relevance_label_for_review`` applies the
existing scope-training rule to turn one into a cyclotron label.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from .catalog import _record, semantic_relation_record
from .ids import hash_short, safe_id
from .reference_policy import scope_training_label_for_reference

RELEVANCE_RELATION = "relevance_decision_is"
DECISION_NODE_KIND = "relevanceDecision"
STATUS_PAYLOAD_KIND = "cyclotron-status"


def decision_node_key(label: str) -> str:
    return f"relevance.{safe_id(label)}"


def decision_node_lineage_id(label: str) -> str:
    return f"semantic-node-{safe_id(decision_node_key(label))}"


def decision_node_record(label: str, *, now: str) -> dict[str, Any]:
    """The SemanticNode a decision points at, one per label."""
    key = decision_node_key(label)
    display = f"Relevance: {label}"
    description = f"The relevance cyclotron decided {label} for a candidate source."
    return _record("SemanticNode", {
        "id": f"{decision_node_lineage_id(label)}-v1",
        "lineageId": decision_node_lineage_id(label),
        "versionNumber": 1,
        "versionState": "current",
        "versionCreatedAt": now,
        "versionCreatedBy": "papyrus-cyclotron",
        "changeReason": "relevanceDecision-seed",
        "contentHash": hash_short([key, DECISION_NODE_KIND, display, description]),
        "nodeKey": key,
        "nodeKind": DECISION_NODE_KIND,
        "displayName": display,
        "description": description,
        "aliases": [label],
        "status": "accepted",
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "semanticNodes",
    })


def relevance_decision_records(reference: Mapping[str, Any], decision: Mapping[str, Any], *, cyclotron_id: str,
                               positive_label: str, now: str,
                               current_relations: Sequence[Mapping[str, Any]] = (),
                               question: str | None = None, labels: Sequence[str] | None = None,
                               review_control: str | None = None) -> list[dict[str, Any]]:
    """Records for one decision (the SDK's Decision.to_json()) and the decisions it supersedes."""
    (classifier, result), = decision["classifiers"].items()
    label = result["label"]
    probabilities = result.get("probabilities") or {}
    review = decision["review"]
    relation = semantic_relation_record({
        "predicate": RELEVANCE_RELATION,
        "subjectKind": "reference",
        "subjectId": reference["id"],
        "subjectLineageId": reference.get("lineageId") or reference["id"],
        "subjectVersionNumber": reference.get("versionNumber"),
        "objectKind": "semanticNode",
        "objectId": f"{decision_node_lineage_id(label)}-v1",
        "objectLineageId": decision_node_lineage_id(label),
        "objectVersionNumber": 1,
        "score": probabilities.get(positive_label, result.get("confidence") if label == positive_label else None),
        "confidence": result.get("confidence"),
        "rank": 1,
        "classifierId": f"{cyclotron_id}/{classifier}",
        "modelVersion": str(result["version"]),
        "reviewRecommended": bool(review["selected"]),
        "importedAt": now,
        "metadata": {
            "decisionId": decision["decisionId"],
            "cyclotronId": cyclotron_id,
            "classifier": classifier,
            "label": label,
            "probabilities": probabilities,
            "version": result["version"],
            "fingerprint": result.get("fingerprint"),
            "reviewReason": review.get("reason"),
            "reviewDetail": review.get("detail"),
            "propensity": review.get("propensity"),
            "decidedAt": decision.get("createdAt"),
            # What the References tab needs to show the review control.
            "question": question,
            "labels": list(labels) if labels else list(probabilities),
            "positiveLabel": positive_label,
            "reviewControl": review_control,
        },
    })
    relation["expected"]["id"] = f"semantic-relation-{hash_short([RELEVANCE_RELATION, decision['decisionId']])}"
    superseded = [
        _record("SemanticRelation", {**_strip(existing), "relationState": "superseded", "updatedAt": now})
        for existing in current_relations
        if existing.get("predicate") == RELEVANCE_RELATION and existing.get("relationState") == "current"
        and existing.get("subjectLineageId") == (reference.get("lineageId") or reference["id"])
        and existing.get("id") != relation["expected"]["id"]
    ]
    return [decision_node_record(label, now=now), relation, *superseded]


def current_relevance_decision(relations: Sequence[Mapping[str, Any]], reference_lineage_id: str) -> Mapping[str, Any] | None:
    """The one current decision relation for a reference lineage, if any."""
    current = [relation for relation in relations if relation.get("predicate") == RELEVANCE_RELATION
               and relation.get("relationState") == "current" and relation.get("subjectLineageId") == reference_lineage_id]
    if len(current) > 1:
        raise ValueError(f"Reference {reference_lineage_id} has {len(current)} current relevance decisions.")
    return current[0] if current else None


def status_payload_id(cyclotron_id: str) -> str:
    return f"knowledge-raw-payload-cyclotron-status-{safe_id(cyclotron_id)}"


def status_snapshot_record(cyclotron_id: str, status: Mapping[str, Any], *, now: str) -> dict[str, Any]:
    """The cyclotron-status/v1 snapshot as a KnowledgeRawPayload with a raw_payload attachment."""
    if status.get("schema") != "cyclotron-status/v1":
        raise ValueError("status must be a cyclotron-status/v1 snapshot")
    return _record("KnowledgeRawPayload", {
        "id": status_payload_id(cyclotron_id),
        "ownerType": "cyclotron",
        "ownerId": safe_id(cyclotron_id),
        "payloadKind": STATUS_PAYLOAD_KIND,
        "createdAt": now,
        "updatedAt": now,
        "payload": json.dumps(dict(status), sort_keys=True),
    })


def relevance_label_for_review(reference: Mapping[str, Any], messages: Sequence[Mapping[str, Any]],
                               *, labels: Sequence[str]) -> str | None:
    """The cyclotron label an editor's curation implies, by the existing scope-training rule.

    Accepted is the positive label; rejected as out of scope or a policy
    exclusion is the negative label; any other outcome gives no label.
    """
    outcome = scope_training_label_for_reference(dict(reference), [dict(message) for message in messages])
    positive, negative = labels
    return {"positive": positive, "negative": negative}.get(outcome)


def _strip(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("__")}
