"""Review of typed relations between entities: the partial updates behind ``papyrus knowledge relations accept|reject``.

A relation the extractor proposes starts unconfirmed; the snapshot shows only accepted ones, as neighbours. Who
accepted or rejected it is kept in the row's ``metadata`` (``acceptedBy`` / ``rejectedBy``, see ``actors.py``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .actors import Actor
from .publish_run import NODE_KIND, json_object

PROPOSED = "proposed"
ACCEPTED = "accepted"
REJECTED = "rejected"
RELATION_STATES = (PROPOSED, ACCEPTED, REJECTED)


class RelationReviewError(ValueError):
    pass


def is_node_relation(row: Mapping[str, Any]) -> bool:
    return (
        row.get("subjectKind") == NODE_KIND
        and row.get("objectKind") == NODE_KIND
        and row.get("relationState", "current") == "current"
    )


def review_state(row: Mapping[str, Any]) -> str:
    metadata = json_object(row.get("metadata"))
    if metadata.get("confirmed") is True:
        return ACCEPTED
    return REJECTED if isinstance(metadata.get("rejectedBy"), dict) else PROPOSED


def find_relation(rows: Iterable[Mapping[str, Any]], identifier: str) -> dict:
    wanted = identifier.strip()
    matches = [dict(row) for row in rows if is_node_relation(row) and row.get("id") == wanted]
    if not matches:
        raise RelationReviewError(f"No relation between entities with id {identifier!r}.")
    return matches[0]


def accept_relation_patches(row: Mapping[str, Any], actor: Actor, *, now: str) -> list[dict]:
    if review_state(row) == ACCEPTED:
        return []
    metadata = {key: value for key, value in json_object(row.get("metadata")).items() if key != "rejectedBy"}
    metadata.update(confirmed=True, acceptedBy=actor.to_dict())
    return [{"modelName": "SemanticRelation", "expected": {"id": row["id"], "metadata": json.dumps(metadata, sort_keys=True), "updatedAt": now}}]


def reject_relation_patches(row: Mapping[str, Any], actor: Actor, *, now: str) -> list[dict]:
    if review_state(row) == REJECTED:
        return []
    metadata = {key: value for key, value in json_object(row.get("metadata")).items() if key != "acceptedBy"}
    metadata.update(confirmed=False, rejectedBy=actor.to_dict())
    return [{"modelName": "SemanticRelation", "expected": {"id": row["id"], "metadata": json.dumps(metadata, sort_keys=True), "updatedAt": now}}]
