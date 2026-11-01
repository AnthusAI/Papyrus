"""Edges from a Reference to another Reference or to a concept, written as ``SemanticRelation`` rows.

See docs/idea-context-packs.md sections 2.1 and 2.2. No new model: a row's ``relationState`` is ``current`` (a person
confirmed it, or a deterministic rule derived it), ``suggested`` (a machine proposed it and a person has not looked) or
``rejected`` (a person said no). The state is part of the state keys, so every reader that queries ``...#current`` sees
only confirmed edges and never a suggestion or a rejection.

Tagging a Reference with a concept is a ``related_to`` edge from the reference to the ``semanticNode``. The ``mentions``
predicate stays for text that enrichment extracted.
"""

from __future__ import annotations

import json
from typing import Any

from .ids import hash_short
from .publishing import utc_now_iso
from .relation_types import semantic_relation_type_fields_for_predicate
from .story_reporting import current_reference, latest_story_version

RELATED_TO = "related_to"
CITES = "cites"
SUPPORTS = "supports"
CONTRADICTS = "contradicts"
REFERENCE_LINK_PREDICATES = (RELATED_TO, CITES, SUPPORTS, CONTRADICTS)
SYMMETRIC_PREDICATES = (RELATED_TO,)
PROVENANCES = ("human", "suggested", "derived")
DECISIONS = ("accepted", "rejected")
REFERENCE_LINK_KIND = "reference.link"
REFERENCE_CONCEPT_KIND = "reference.concept"
ITEM_CONCEPT_KIND = "item.concept"
REFERENCE_LINK_FEED_KEY = "reference-links"
STATE_FOR_PROVENANCE = {"human": "current", "derived": "current", "suggested": "suggested"}
STATE_FOR_DECISION = {"accepted": "current", "rejected": "rejected"}


def reference_link_relation_id(predicate: str, first_lineage_id: str, second_lineage_id: str) -> str:
    return f"reference-link-{predicate}-{hash_short([first_lineage_id, second_lineage_id])}"


def _state_keys(subject_kind: str, subject_lineage_id: str, object_kind: str, object_lineage_id: str, predicate: str, state: str) -> dict[str, str]:
    subject_state_key = f"{subject_kind}#{subject_lineage_id}#{state}"
    object_state_key = f"{object_kind}#{object_lineage_id}#{state}"
    return {
        "subjectStateKey": subject_state_key,
        "objectStateKey": object_state_key,
        "objectSubjectStateKey": f"{object_state_key}#{subject_kind}",
        "predicateObjectStateKey": f"{predicate}#{object_state_key}",
    }


def _stored_metadata(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    metadata = row.get("metadata")
    if isinstance(metadata, str):
        return json.loads(metadata or "{}")
    return dict(metadata or {})


def _require_provenance(provenance: str) -> None:
    if provenance not in PROVENANCES:
        raise ValueError(f"provenance must be one of {', '.join(PROVENANCES)}.")


def _require_reference(client, reference_id: str) -> dict[str, Any]:
    reference = current_reference(client, reference_id)
    if reference is None:
        raise ValueError(f"Reference not found: {reference_id}")
    return reference


def _write_edge(
    client,
    *,
    relation_id: str,
    kind: str,
    predicate: str,
    subject: dict[str, Any],
    object_: dict[str, Any],
    provenance: str,
    actor: str,
    score: float | None,
    confidence: float | None,
    classifier_id: str | None,
    model_version: str | None,
    note: str | None,
    now: str,
) -> dict[str, Any]:
    existing = client.get_record("SemanticRelation", relation_id)
    if provenance == "suggested" and existing and existing.get("relationState") != "suggested":
        return {"relationId": relation_id, "relationState": existing["relationState"], "outcome": "kept"}
    state = STATE_FOR_PROVENANCE[provenance]
    previous = _stored_metadata(existing)
    metadata = {
        **previous,
        "kind": kind,
        "provenance": provenance,
        "suggestedBy": classifier_id if provenance == "suggested" else previous.get("suggestedBy"),
        "addedBy": previous.get("addedBy") or actor,
        "addedAt": previous.get("addedAt") or now,
        "decidedBy": previous.get("decidedBy"),
        "decidedAt": previous.get("decidedAt"),
        "decision": previous.get("decision"),
        "reasonCode": previous.get("reasonCode"),
        "note": note or previous.get("note"),
    }
    if provenance != "suggested" and not previous.get("decision"):
        metadata.update({"decidedBy": actor, "decidedAt": now, "decision": "accepted"})
    record = {
        "id": relation_id,
        "relationState": state,
        "predicate": predicate,
        **semantic_relation_type_fields_for_predicate(predicate),
        "subjectKind": subject["kind"],
        "subjectId": subject["id"],
        "subjectLineageId": subject["lineageId"],
        "subjectVersionNumber": subject.get("versionNumber"),
        "objectKind": object_["kind"],
        "objectId": object_["id"],
        "objectLineageId": object_["lineageId"],
        "objectVersionNumber": object_.get("versionNumber"),
        **_state_keys(subject["kind"], subject["lineageId"], object_["kind"], object_["lineageId"], predicate, state),
        "subjectVersionKey": f"{subject['kind']}#{subject['id']}",
        "objectVersionKey": f"{object_['kind']}#{object_['id']}",
        "score": score,
        "confidence": confidence,
        "rank": 1,
        "classifierId": classifier_id,
        "modelVersion": model_version,
        "reviewRecommended": state == "suggested",
        "importedAt": now,
        "updatedAt": now,
        "newsroomFeedKey": REFERENCE_LINK_FEED_KEY,
        "metadata": json.dumps(metadata, sort_keys=True),
    }
    outcome = client.upsert("SemanticRelation", record)
    return {"relationId": relation_id, "relationState": state, "outcome": outcome}


def _reference_end(reference: dict[str, Any], reference_id: str) -> dict[str, Any]:
    return {
        "kind": "reference",
        "id": reference["id"],
        "lineageId": reference.get("lineageId") or reference_id,
        "versionNumber": reference.get("versionNumber"),
    }


def link_references(
    client,
    a: str,
    b: str,
    predicate: str,
    provenance: str,
    *,
    actor: str,
    score: float | None = None,
    confidence: float | None = None,
    classifier_id: str | None = None,
    model_version: str | None = None,
    note: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Writes (or updates) one edge between two References, given by record id or lineage id.

    ``related_to`` is symmetric: one row, the lower lineage id as subject. ``cites``, ``supports`` and ``contradicts``
    point from ``a`` to ``b``. A second write of the same pair and predicate updates the row; a suggestion never
    overwrites an edge a person already confirmed or rejected.
    """
    if predicate not in REFERENCE_LINK_PREDICATES:
        raise ValueError(f"predicate must be one of {', '.join(REFERENCE_LINK_PREDICATES)}.")
    _require_provenance(provenance)
    now = now or utc_now_iso()
    first = _reference_end(_require_reference(client, a), a)
    second = _reference_end(_require_reference(client, b), b)
    if first["lineageId"] == second["lineageId"]:
        raise ValueError("A reference cannot be linked to itself.")
    if predicate in SYMMETRIC_PREDICATES and second["lineageId"] < first["lineageId"]:
        first, second = second, first
    return _write_edge(
        client,
        relation_id=reference_link_relation_id(predicate, first["lineageId"], second["lineageId"]),
        kind=REFERENCE_LINK_KIND,
        predicate=predicate,
        subject=first,
        object_=second,
        provenance=provenance,
        actor=actor,
        score=score,
        confidence=confidence,
        classifier_id=classifier_id,
        model_version=model_version,
        note=note,
        now=now,
    )


def link_concept(
    client,
    reference: str,
    node: dict[str, Any],
    provenance: str,
    *,
    actor: str,
    score: float | None = None,
    confidence: float | None = None,
    classifier_id: str | None = None,
    model_version: str | None = None,
    note: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Tags a Reference with a concept: a ``related_to`` edge from the reference to the ``semanticNode`` row ``node``.

    ``node`` is the SemanticNode row (``id``, ``lineageId``, ``versionNumber``). ``mentions`` is not used here; it stays
    for text that enrichment extracted.
    """
    _require_provenance(provenance)
    now = now or utc_now_iso()
    reference_end = _reference_end(_require_reference(client, reference), reference)
    node_end = {"kind": "semanticNode", "id": node["id"], "lineageId": node.get("lineageId") or node["id"], "versionNumber": node.get("versionNumber")}
    return _write_edge(
        client,
        relation_id=reference_link_relation_id(RELATED_TO, reference_end["lineageId"], node_end["lineageId"]),
        kind=REFERENCE_CONCEPT_KIND,
        predicate=RELATED_TO,
        subject=reference_end,
        object_=node_end,
        provenance=provenance,
        actor=actor,
        score=score,
        confidence=confidence,
        classifier_id=classifier_id,
        model_version=model_version,
        note=note,
        now=now,
    )


def link_item_concept(
    client,
    item_lineage_id: str,
    node: dict[str, Any],
    provenance: str,
    *,
    actor: str,
    note: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Tags a story (an Item, by lineage id) with a concept: a ``related_to`` edge from the item to the ``semanticNode`` row ``node``, so the
    story shows on the concept's page. Same row conventions as ``link_concept``; ``related_to`` allows an item as its subject."""
    _require_provenance(provenance)
    now = now or utc_now_iso()
    story = latest_story_version(client, item_lineage_id)
    item_end = {"kind": "item", "id": story["id"], "lineageId": item_lineage_id, "versionNumber": story.get("versionNumber")}
    node_end = {"kind": "semanticNode", "id": node["id"], "lineageId": node.get("lineageId") or node["id"], "versionNumber": node.get("versionNumber")}
    return _write_edge(
        client,
        relation_id=reference_link_relation_id(RELATED_TO, item_lineage_id, node_end["lineageId"]),
        kind=ITEM_CONCEPT_KIND,
        predicate=RELATED_TO,
        subject=item_end,
        object_=node_end,
        provenance=provenance,
        actor=actor,
        score=None,
        confidence=None,
        classifier_id=None,
        model_version=None,
        note=note,
        now=now,
    )


def decide(
    client,
    relation_id: str,
    decision: str,
    reason_code: str | None,
    note: str | None,
    actor: str,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Records a person's accept or reject of an edge: the new state, its state keys, and who decided and why."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}.")
    row = client.get_record("SemanticRelation", relation_id)
    if row is None:
        raise ValueError(f"Reference link not found: {relation_id}")
    now = now or utc_now_iso()
    state = STATE_FOR_DECISION[decision]
    metadata = {
        **_stored_metadata(row),
        "decidedBy": actor,
        "decidedAt": now,
        "decision": decision,
        "reasonCode": reason_code,
        "note": note,
    }
    client.update_record(
        "SemanticRelation",
        {
            "id": relation_id,
            "relationState": state,
            **_state_keys(row["subjectKind"], row["subjectLineageId"], row["objectKind"], row["objectLineageId"], row["predicate"], state),
            "reviewRecommended": False,
            "updatedAt": now,
            "metadata": json.dumps(metadata, sort_keys=True),
        },
    )
    return {"relationId": relation_id, "relationState": state, "decision": decision}
