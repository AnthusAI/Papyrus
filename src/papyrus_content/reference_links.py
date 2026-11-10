"""Edges from a Reference to another Reference or to a concept, written as ``SemanticRelation`` rows.

See docs/idea-context-packs.md sections 2.1 and 2.2. No new model: a row's ``relationState`` is ``current`` (a person
confirmed it, or a deterministic rule derived it), ``suggested`` (a machine proposed it and a person has not looked) or
``rejected`` (a person said no). The state is part of the state keys, so every reader that queries ``...#current`` sees
only confirmed edges and never a suggestion or a rejection.

Tagging a Reference with a concept is a ``tagged_with`` edge (``related_to`` before 2026-11-09; see CONCEPT_TAG_PREDICATES) from the reference to the ``semanticNode``. The ``mentions``
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
# Concept tagging (a story or a Reference "tagged with" a concept) is `tagged_with`. `related_to` was the name before 2026-11-09; rows under it still exist
# (written before the rename), so every reader accepts both until `papyrus relations migrate-concept-tags` has run: CONCEPT_TAG_PREDICATES. Every writer now writes
# CONCEPT_TAG_PREDICATE; the legacy name is only read, and migrated.
TAGGED_WITH = "tagged_with"
CONCEPT_TAG_PREDICATE = TAGGED_WITH
LEGACY_CONCEPT_TAG_PREDICATE = RELATED_TO
CONCEPT_TAG_PREDICATES = (CONCEPT_TAG_PREDICATE, LEGACY_CONCEPT_TAG_PREDICATE)
SEE_ALSO = "see_also"   # story to story: "read this too" (one meaning; a story pair is never `related_to`)
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
ITEM_LINK_KIND = "item.link"
ITEM_REFERENCE_LINK_KIND = "item.reference-link"   # story -> Reference see_also, named like its neighbours item.link and item.concept
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


relation_state_keys = _state_keys   # the four state keys of an edge, for the one migration that rewrites them (concept_tag_migration.py)


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


def _require_tag_predicate(predicate: str) -> None:
    if predicate not in CONCEPT_TAG_PREDICATES:
        raise ValueError(f"A concept tag is one of {', '.join(CONCEPT_TAG_PREDICATES)}.")


def _legacy_tag_outcome(client, subject_lineage_id: str, object_lineage_id: str, predicate: str, provenance: str) -> dict[str, Any] | None:
    """What a ``tagged_with`` writer must honour in the same pair's row under the legacy ``related_to`` name (until ``relations migrate-concept-tags`` has run).

    A person's rejection there is kept (no writer flips it back, whatever the name), and a machine writer (a suggestion or a derived tag) does not add a second row beside a
    legacy one that is still current or suggested. A person's tag is written: it is the confirmed row, and the migration skips a pair that already has one."""
    if predicate != CONCEPT_TAG_PREDICATE:
        return None
    legacy_id = reference_link_relation_id(LEGACY_CONCEPT_TAG_PREDICATE, subject_lineage_id, object_lineage_id)
    legacy = client.get_record("SemanticRelation", legacy_id)
    if not legacy or legacy.get("relationState") == "superseded":
        return None
    if legacy.get("relationState") == "rejected":
        meta = _stored_metadata(legacy)
        return {"relationId": legacy_id, "relationState": "rejected", "outcome": "rejected", "decidedBy": meta.get("decidedBy"), "decidedAt": meta.get("decidedAt")}
    if provenance != "human":
        return {"relationId": legacy_id, "relationState": legacy["relationState"], "outcome": "kept"}
    return None


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
    if existing and existing.get("relationState") == "rejected":
        # A person rejected this edge. No writer flips it back (a suggestion, a derived link or a tag): only a person's decision does, through ``decide``.
        return {"relationId": relation_id, "relationState": "rejected", "outcome": "rejected",
                "decidedBy": _stored_metadata(existing).get("decidedBy"), "decidedAt": _stored_metadata(existing).get("decidedAt")}
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
        # score sorts two indexes on this model and DynamoDB refuses a null index key; a person's link is certain (as in catalog.semantic_relation_record).
        "score": score if score is not None else 1,
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
    predicate: str = CONCEPT_TAG_PREDICATE,
) -> dict[str, Any]:
    """Tags a Reference with a concept: a ``tagged_with`` edge from the reference to the ``semanticNode`` row ``node``.

    ``node`` is the SemanticNode row (``id``, ``lineageId``, ``versionNumber``). ``mentions`` is not used here; it stays
    for text that enrichment extracted.
    """
    _require_provenance(provenance)
    _require_tag_predicate(predicate)
    now = now or utc_now_iso()
    reference_end = _reference_end(_require_reference(client, reference), reference)
    node_end = {"kind": "semanticNode", "id": node["id"], "lineageId": node.get("lineageId") or node["id"], "versionNumber": node.get("versionNumber")}
    legacy = _legacy_tag_outcome(client, reference_end["lineageId"], node_end["lineageId"], predicate, provenance)
    if legacy is not None:
        return legacy
    return _write_edge(
        client,
        relation_id=reference_link_relation_id(predicate, reference_end["lineageId"], node_end["lineageId"]),
        kind=REFERENCE_CONCEPT_KIND,
        predicate=predicate,
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
    story: dict[str, Any] | None = None,
    predicate: str = CONCEPT_TAG_PREDICATE,
) -> dict[str, Any]:
    """Tags a story (an Item, by lineage id) with a concept: a ``tagged_with`` edge from the item to the ``semanticNode`` row ``node``, so the
    story shows on the concept's page. Same row conventions as ``link_concept``; ``tagged_with`` allows an item as its subject.
    ``story`` is the record the caller has just written; the lineage index is eventually consistent (see ``link_reference_to_story``)."""
    _require_provenance(provenance)
    _require_tag_predicate(predicate)
    now = now or utc_now_iso()
    story = story or latest_story_version(client, item_lineage_id)
    item_end = {"kind": "item", "id": story["id"], "lineageId": item_lineage_id, "versionNumber": story.get("versionNumber")}
    node_end = {"kind": "semanticNode", "id": node["id"], "lineageId": node.get("lineageId") or node["id"], "versionNumber": node.get("versionNumber")}
    legacy = _legacy_tag_outcome(client, item_lineage_id, node_end["lineageId"], predicate, provenance)
    if legacy is not None:
        return legacy
    return _write_edge(
        client,
        relation_id=reference_link_relation_id(predicate, item_lineage_id, node_end["lineageId"]),
        kind=ITEM_CONCEPT_KIND,
        predicate=predicate,
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


def link_items(
    client,
    first: dict[str, Any],
    second: dict[str, Any],
    provenance: str,
    *,
    actor: str,
    note: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Links two stories (Items, as their current records) with the one official ``see_also`` edge, kind ``item.link``.

    Symmetric like reference links: one row, the lower lineage id as subject, the deterministic id from the pair, so A to B and B to A are one row.
    A rejected edge is never flipped back (see ``_write_edge``)."""
    _require_provenance(provenance)
    now = now or utc_now_iso()
    ends = sorted(({"kind": "item", "id": story["id"], "lineageId": story.get("lineageId") or story["id"], "versionNumber": story.get("versionNumber")}
                   for story in (first, second)), key=lambda end: end["lineageId"])
    if ends[0]["lineageId"] == ends[1]["lineageId"]:
        raise ValueError("A story cannot be linked to itself.")
    return _write_edge(
        client,
        relation_id=reference_link_relation_id(SEE_ALSO, ends[0]["lineageId"], ends[1]["lineageId"]),
        kind=ITEM_LINK_KIND,
        predicate=SEE_ALSO,
        subject=ends[0],
        object_=ends[1],
        provenance=provenance,
        actor=actor,
        score=None,
        confidence=None,
        classifier_id=None,
        model_version=None,
        note=note,
        now=now,
    )


def link_item_reference_see_also(
    client,
    item_lineage_id: str,
    reference: str,
    provenance: str,
    *,
    actor: str,
    note: str | None = None,
    now: str | None = None,
    story: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Links a story to a Reference with the official ``see_also`` edge ("read this source too"), kind ``item.reference-link``.

    Directional: the story is the subject, the Reference (a record id or a lineage id) the object. The id is deterministic from the predicate, the story
    lineage and the Reference lineage, so a repeat finds the row: a current (or suggested) edge is reported as ``exists`` and nothing is written, and a rejected
    edge is never flipped back (``outcome`` ``rejected``). Only an accepted Reference can be linked: the public page shows accepted References only.
    ``story`` is the story's record when the caller has it (the lineage index is eventually consistent)."""
    _require_provenance(provenance)
    now = now or utc_now_iso()
    found = _require_reference(client, reference)
    if found.get("curationStatus") != "accepted":
        raise ValueError(f"Reference {reference} is {found.get('curationStatus') or 'not accepted'}; only accepted References can be linked to a story, because only those are shown on the page.")
    reference_end = _reference_end(found, reference)
    story = story or latest_story_version(client, item_lineage_id)
    item_end = {"kind": "item", "id": story["id"], "lineageId": item_lineage_id, "versionNumber": story.get("versionNumber")}
    relation_id = reference_link_relation_id(SEE_ALSO, item_lineage_id, reference_end["lineageId"])
    existing = client.get_record("SemanticRelation", relation_id)
    if existing and existing.get("relationState") in ("current", "suggested"):
        return {"relationId": relation_id, "relationState": existing["relationState"], "outcome": "exists"}
    return _write_edge(
        client,
        relation_id=relation_id,
        kind=ITEM_REFERENCE_LINK_KIND,
        predicate=SEE_ALSO,
        subject=item_end,
        object_=reference_end,
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
