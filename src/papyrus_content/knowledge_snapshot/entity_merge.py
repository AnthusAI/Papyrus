"""Merge two entities that are one thing: ``papyrus knowledge entities merge --from KEY --into KEY --actor ai|human``.

``--from`` is the duplicate, ``--into`` the entity that stays. Like ``retype`` (``entity_retype.py``) it migrates rather than edits, because the keys and ids
of both nodes derive from their names:

* the duplicate is superseded (``versionState`` and ``status`` ``superseded``): no longer current, never resolved by a later import, left out of the
  snapshot (its entity file goes at the next snapshot, and its wiki page is left as it is: ``wiki sync`` never takes a page down);
* its name and every alias it had become aliases of the surviving entity (``aliasedBy`` and ``mergedBy`` record the actor and the day), so the registry
  resolves the old spelling to the surviving node from then on; a description the survivor lacks is taken from the duplicate;
* every current relation that touches the duplicate (item mentions and relations between entities) is superseded and re-created on the surviving
  entity with the same metadata, so confirmed links stay confirmed. A relation the surviving entity already has (the same item, or the same relation
  between the same two entities) is kept as it is and the duplicate's copy is only superseded; a relation between the two nodes themselves is only
  superseded. Relation ids derive from their ends, so running the plan again finds nothing to do.

The merge is refused when the duplicate is rejected, the survivor is not accepted, the two are of different kinds (retype first), or an alias to move is
already held by a third live entity of the kind.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..categories_steering import semantic_relation_record
from .actors import Actor, decode_review
from .entity_retype import SUPERSEDED, _retargeted
from .entity_review import EntityReviewError
from .keys import normalize_name, kind_key
from .publish_run import STATUS_ACCEPTED, STATUS_REJECTED


def _is_live(node: Mapping[str, Any]) -> bool:
    return node.get("versionState", "current") == "current" and node.get("status") != SUPERSEDED


def _lineage(node: Mapping[str, Any]) -> str:
    return str(node.get("lineageId") or node.get("id"))


def merged_aliases(duplicate: Mapping[str, Any], survivor: Mapping[str, Any]) -> list[str]:
    """The survivor's aliases followed by the duplicate's name and aliases that it does not answer to already, in order."""
    held = {normalize_name(survivor.get("displayName") or "")}
    aliases: list[str] = []
    for name in [*(survivor.get("aliases") or ()), duplicate.get("displayName"), *(duplicate.get("aliases") or ())]:
        text = " ".join(str(name or "").split())
        if text and normalize_name(text) not in held:
            held.add(normalize_name(text))
            aliases.append(text)
    return aliases


def merge_plan(
    duplicate: Mapping[str, Any],
    survivor: Mapping[str, Any],
    node_rows: Iterable[Mapping[str, Any]],
    relation_rows: Iterable[Mapping[str, Any]],
    *,
    actor: Actor,
    now: str,
) -> tuple[list[dict], list[dict]]:
    """``(records, patches)``: relation rows to create, and partial updates of existing rows. ``relation_rows`` are the relations of both nodes."""
    if _lineage(duplicate) == _lineage(survivor):
        raise EntityReviewError("An entity cannot be merged into itself.")
    if duplicate.get("status") == STATUS_REJECTED:
        raise EntityReviewError(f"{duplicate['nodeKey']} is rejected; there is nothing to merge.")
    if survivor.get("status") != STATUS_ACCEPTED:
        raise EntityReviewError(f"{survivor['nodeKey']} is {survivor.get('status')}, not accepted; accept it first, or merge into the accepted entity.")
    if not _is_live(duplicate) or not _is_live(survivor):
        raise EntityReviewError("Both entities must be current.")
    if kind_key(duplicate.get("nodeKind") or "") != kind_key(survivor.get("nodeKind") or ""):
        raise EntityReviewError(f"{duplicate['nodeKey']} and {survivor['nodeKey']} are of different kinds; retype one first (`knowledge entities retype`).")
    aliases = merged_aliases(duplicate, survivor)
    kind = kind_key(survivor.get("nodeKind") or "")
    for other in node_rows:
        if _lineage(other) in (_lineage(duplicate), _lineage(survivor)) or not _is_live(other) or other.get("status") not in (STATUS_ACCEPTED, "generated"):
            continue
        if kind_key(other.get("nodeKind") or "") != kind:
            continue
        taken = {normalize_name(name) for name in [other.get("displayName"), *(other.get("aliases") or ())] if name}
        clash = next((alias for alias in aliases if normalize_name(alias) in taken), None)
        if clash is not None:
            raise EntityReviewError(f"{other['id']} already has the name {clash!r}; merge that one first.")

    marks = decode_review(survivor.get("changeReason")).replace(aliased_by=actor, merged_by=actor)
    survivor_patch: dict[str, Any] = {"id": survivor["id"], "changeReason": marks.encode(), "updatedAt": now}
    if aliases != list(survivor.get("aliases") or ()):
        survivor_patch["aliases"] = aliases
    if not str(survivor.get("description") or "").strip() and str(duplicate.get("description") or "").strip():
        survivor_patch["description"] = duplicate["description"]
    gone_marks = decode_review(duplicate.get("changeReason")).replace(merged_by=actor)
    patches: list[dict] = [
        {"modelName": "SemanticNode", "expected": survivor_patch},
        {"modelName": "SemanticNode", "expected": {"id": duplicate["id"], "versionState": SUPERSEDED, "status": SUPERSEDED, "changeReason": gone_marks.encode(), "updatedAt": now}},
    ]

    current = [row for row in relation_rows if row.get("relationState", "current") == "current"]
    existing_ids = {row["id"] for row in current}
    planned: set[str] = set()
    records: list[dict] = []
    for row in current:
        touches = any(row.get(f"{side}Kind") == "semanticNode" and row.get(f"{side}LineageId") == duplicate.get("lineageId") for side in ("subject", "object"))
        if not touches:
            continue
        patches.append({"modelName": "SemanticRelation", "expected": {"id": row["id"], "relationState": SUPERSEDED, "updatedAt": now}})
        moved = semantic_relation_record({**_retargeted(row, duplicate, survivor), "importedAt": row.get("importedAt") or now})
        expected = moved["expected"]
        both_ends_are_the_survivor = (
            expected["subjectKind"] == expected["objectKind"] == "semanticNode" and expected["subjectLineageId"] == expected["objectLineageId"]
        )
        if both_ends_are_the_survivor or expected["id"] in existing_ids or expected["id"] in planned:
            continue  # a relation the survivor already has, or one between the two nodes: only the duplicate's copy goes
        planned.add(expected["id"])
        records.append({"modelName": "SemanticRelation", "expected": expected})
    return records, patches
