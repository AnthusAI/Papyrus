"""Change the kind of an entity: ``papyrus knowledge entities retype --key K --kind KIND --actor ai|human``.

The kind is part of the key (``platform--card`` is ``kind--name``), so a node cannot be retyped in place: the key, the
lineage id and the node id all derive from it. A retype therefore migrates the entity:

* a new node is created under the new key (``model--card``) with the same name, aliases, description, status and
  review marks, and ``retypedBy`` recorded as the actor;
* the old node is superseded (``versionState`` and ``status`` ``superseded``), so it is no longer current, no longer
  accepted, never resolved by a later import and left out of the snapshot (its entity file is deleted by the next
  snapshot);
* every current relation that touches the old node (item mentions and relations between entities) is superseded and
  re-created pointing at the new node, with the same metadata, so confirmed links stay confirmed and the entity keeps its
  history of mentions. Relation ids derive from their ends, so running the command again plans nothing.

The old key no longer exists after the retype; a wiki page or link that used it needs the new key. A retype into a key
that a current node already holds is refused: merge the two by hand.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from ..categories_steering import semantic_relation_record
from .actors import Actor, decode_review
from .entity_review import EntityReviewError
from .keys import entity_key, slug
from .publish_run import STATUS_REJECTED, json_object, new_node_row

SUPERSEDED = "superseded"


def _retargeted(row: Mapping[str, Any], old: Mapping[str, Any], new: Mapping[str, Any]) -> dict:
    values = {
        "predicate": row["predicate"],
        "subjectKind": row["subjectKind"],
        "subjectId": row["subjectId"],
        "subjectLineageId": row["subjectLineageId"],
        "subjectVersionNumber": row.get("subjectVersionNumber"),
        "objectKind": row["objectKind"],
        "objectId": row["objectId"],
        "objectLineageId": row["objectLineageId"],
        "objectVersionNumber": row.get("objectVersionNumber"),
        "rank": row.get("rank"),
        "classifierId": row.get("classifierId"),
        "modelVersion": row.get("modelVersion"),
        "confidence": row.get("confidence"),
        "score": row.get("score"),
        "reviewRecommended": row.get("reviewRecommended"),
        "sourceSnapshotId": row.get("sourceSnapshotId"),
        "importRunId": row.get("importRunId"),
        "importedAt": row.get("importedAt"),
        "createdAt": row.get("createdAt"),
        "metadata": json_object(row.get("metadata")),
    }
    for side in ("subject", "object"):
        if values[f"{side}Kind"] == "semanticNode" and values[f"{side}LineageId"] == old["lineageId"]:
            values[f"{side}Id"] = new["id"]
            values[f"{side}LineageId"] = new["lineageId"]
            values[f"{side}VersionNumber"] = new.get("versionNumber") or 1
    return values


def retype_plan(
    node: Mapping[str, Any],
    new_kind: str,
    node_rows: Iterable[Mapping[str, Any]],
    relation_rows: Iterable[Mapping[str, Any]],
    *,
    actor: Actor,
    now: str,
) -> tuple[list[dict], list[dict], str]:
    """``(records, patches, new key)``: rows to create or bring up to date, and partial updates of existing rows."""
    kind = slug(new_kind)
    if not kind:
        raise EntityReviewError("A kind is needed.")
    if node.get("status") == STATUS_REJECTED:
        raise EntityReviewError(f"{node['nodeKey']} is rejected; there is nothing to retype.")
    if kind == slug(node.get("nodeKind") or ""):
        raise EntityReviewError(f"{node['nodeKey']} is already of kind {kind!r}.")
    name = " ".join(str(node.get("displayName") or "").split())
    key = entity_key(kind, name)
    if not key:
        raise EntityReviewError(f"{node['nodeKey']} has no name to build a key from.")
    for other in node_rows:
        if other.get("versionState", "current") == "current" and other.get("nodeKey") == key and other.get("id") != node.get("id"):
            raise EntityReviewError(f"{other['id']} already holds the key {key!r}; merge the two by hand.")
    marks = decode_review(node.get("changeReason")).replace(retyped_by=actor)
    created = new_node_row(
        kind,
        name,
        str(node.get("status")),
        import_run_id=node.get("importRunId"),
        corpus_id=node.get("corpusId"),
        now=now,
        reason=marks.encode(),
    )
    created["aliases"] = list(node.get("aliases") or [])
    if node.get("description"):
        created["description"] = node["description"]
    records: list[dict] = [{"modelName": "SemanticNode", "expected": created}]
    patches: list[dict] = [
        {
            "modelName": "SemanticNode",
            "expected": {"id": node["id"], "versionState": SUPERSEDED, "status": SUPERSEDED, "changeReason": marks.encode(), "updatedAt": now},
        }
    ]
    for row in relation_rows:
        if row.get("relationState", "current") != "current":
            continue
        touches = any(row.get(f"{side}Kind") == "semanticNode" and row.get(f"{side}LineageId") == node.get("lineageId") for side in ("subject", "object"))
        if not touches:
            continue
        moved = semantic_relation_record({**_retargeted(row, node, created), "importedAt": row.get("importedAt") or now})
        records.append({"modelName": "SemanticRelation", "expected": moved["expected"]})
        patches.append({"modelName": "SemanticRelation", "expected": {"id": row["id"], "relationState": SUPERSEDED, "updatedAt": now}})
    return records, patches, key
