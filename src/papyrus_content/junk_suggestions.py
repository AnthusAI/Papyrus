"""Retire the concept suggestions the vector pass made to nodes that are not concepts (``papyrus references retire-junk-suggestions``).

Before concept cards and suggestions left them out (``papyrus_knowledge_query/concept_kinds.py``), the vector pass suggested paper authors, ``coverage-*``,
``comment-*``, quality-rating and relevance nodes to editors as "related concepts". This lists the open ``auto:vector`` suggestions whose concept is one of
them. A dry run (the default) only lists. ``execute`` marks each one rejected by ``auto:cleanup`` with the reason ``not_a_concept``, through the same
``reference_links.decide`` an editor's rejection uses, so the row leaves every queue and is not suggested again; nothing is deleted. The calibration learns
only from people's decisions, so these rejections teach it nothing.
"""
from __future__ import annotations

from typing import Any

from papyrus_knowledge_query.concept_kinds import is_concept

from .reference_links import REFERENCE_LINK_FEED_KEY, decide
from .suggestion_calibration import FEED_INDEX, _metadata

CLEANUP_ACTOR = "auto:cleanup"
SUGGESTION_REJECTION_REASON = "not_a_concept"


def find_junk_suggestions(client: Any) -> list[dict[str, Any]]:
    """Open vector suggestions to a node that is not a concept: ``{relationId, referenceLineageId, nodeKey, nodeKind, score}``."""
    nodes: dict[str, dict[str, Any] | None] = {}
    found: list[dict[str, Any]] = []
    for row in client.list_by_index(FEED_INDEX, REFERENCE_LINK_FEED_KEY):
        metadata = _metadata(row)
        if row.get("relationState") != "suggested" or row.get("objectKind") != "semanticNode" or not str(metadata.get("suggestedBy") or row.get("classifierId") or "").startswith("vector:"):
            continue
        lineage = str(row.get("objectLineageId"))
        if lineage not in nodes:
            nodes[lineage] = client.get_record("SemanticNode", lineage)
        node = nodes[lineage]
        if node is None or is_concept(node.get("nodeKind"), node.get("nodeKey")):
            continue
        found.append({"relationId": row["id"], "referenceLineageId": row.get("subjectLineageId"), "nodeKey": node.get("nodeKey"), "nodeKind": node.get("nodeKind"), "score": row.get("score")})
    return found


def retire_junk_suggestions(client: Any, *, execute: bool = False, now: str | None = None) -> dict[str, Any]:
    found = find_junk_suggestions(client)
    if execute:
        for entry in found:
            decide(client, entry["relationId"], "rejected", SUGGESTION_REJECTION_REASON, "Not a concept: a bookkeeping node, left out of concept suggestions.", CLEANUP_ACTOR, now=now)
    kinds: dict[str, int] = {}
    for entry in found:
        kinds[str(entry["nodeKind"])] = kinds.get(str(entry["nodeKind"]), 0) + 1
    return {"executed": execute, "suggestions": len(found), "byKind": kinds, "rows": found}
