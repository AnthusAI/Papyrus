"""Desk review of entities: the partial updates behind ``papyrus knowledge entities accept|reject|rename|describe``.

Pure functions over rows. A node is edited in place (same id, same lineage), so the links that point at it stay valid.
Accepting a node also confirms its extractor links: the desk has said the entity is real, and only confirmed links are
counted by the snapshot. Whether a description has been reviewed is kept in ``changeReason`` as
``description-reviewed:YYYY-MM-DD``; accept, reject and rename leave it alone.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .keys import contains_email, normalize_name, slug
from .loaders import DESCRIPTION_DRAFT_REASON, DESCRIPTION_REVIEWED_PREFIX
from .model import LINK_EXTRACTOR
from .publish_run import STATUS_ACCEPTED, STATUS_REJECTED, is_item_mention, json_object

REVIEW_STATUSES = ("accepted", "generated", "rejected")


class EntityReviewError(ValueError):
    pass


def find_node(rows: Iterable[Mapping[str, Any]], identifier: str) -> dict:
    """The one current node whose node key, id or lineage id is ``identifier``."""
    wanted = identifier.strip()
    matches = [
        dict(row)
        for row in rows
        if row.get("versionState", "current") == "current" and wanted in (row.get("nodeKey"), row.get("id"), row.get("lineageId"))
    ]
    if not matches:
        raise EntityReviewError(f"No entity {identifier!r} (give a node key, id or lineage id).")
    if len(matches) > 1:
        raise EntityReviewError(f"{identifier!r} names {len(matches)} entities: " + ", ".join(sorted(row["id"] for row in matches)))
    return matches[0]


def accept_patches(node: Mapping[str, Any], mention_rows: Iterable[Mapping[str, Any]], *, actor: str, now: str, confirm_links: bool = True) -> list[dict]:
    patches: list[dict] = []
    if node.get("status") != STATUS_ACCEPTED:
        patches.append({"modelName": "SemanticNode", "expected": {"id": node["id"], "status": STATUS_ACCEPTED, "updatedAt": now}})
    if confirm_links:
        for row in mention_rows:
            metadata = json_object(row.get("metadata"))
            if (
                is_item_mention(row)
                and row.get("objectLineageId") == node.get("lineageId")
                and metadata.get("confirmed") is not True
                and metadata.get("linkSource", LINK_EXTRACTOR) == LINK_EXTRACTOR
            ):
                confirmed = {**metadata, "confirmed": True, "confirmedBy": actor}
                patches.append(
                    {
                        "modelName": "SemanticRelation",
                        "expected": {"id": row["id"], "metadata": json.dumps(confirmed, sort_keys=True), "updatedAt": now},
                    }
                )
    return patches


def reject_patches(node: Mapping[str, Any], *, now: str) -> list[dict]:
    if node.get("status") == STATUS_REJECTED:
        return []
    return [{"modelName": "SemanticNode", "expected": {"id": node["id"], "status": STATUS_REJECTED, "updatedAt": now}}]


def rename_patches(node: Mapping[str, Any], new_name: str, others: Iterable[Mapping[str, Any]], *, now: str) -> list[dict]:
    name = " ".join(new_name.split())
    if not name:
        raise EntityReviewError("A name is needed.")
    if contains_email(name):
        raise EntityReviewError("An entity name must not hold an email address.")
    if name == node.get("displayName"):
        return []
    kind = slug(node.get("nodeKind") or "")
    for other in others:
        if (
            other.get("id") != node.get("id")
            and other.get("versionState", "current") == "current"
            and other.get("status") in (STATUS_ACCEPTED, "generated")
            and slug(other.get("nodeKind") or "") == kind
            and normalize_name(name) in {normalize_name(other.get("displayName") or ""), *(normalize_name(alias) for alias in other.get("aliases") or ())}
        ):
            raise EntityReviewError(f"{other['id']} already has the name {name!r}; merge the two by hand.")
    aliases = [alias for alias in node.get("aliases") or () if normalize_name(alias) != normalize_name(name)]
    previous = " ".join(str(node.get("displayName") or "").split())
    if previous and normalize_name(previous) != normalize_name(name) and normalize_name(previous) not in {normalize_name(alias) for alias in aliases}:
        aliases.append(previous)
    return [{"modelName": "SemanticNode", "expected": {"id": node["id"], "displayName": name, "aliases": aliases, "updatedAt": now}}]


def describe_patches(node: Mapping[str, Any], text: str, *, reviewed: bool, today: str, now: str) -> list[dict]:
    description = " ".join(text.split())
    if not description:
        raise EntityReviewError("A description is needed.")
    if contains_email(description):
        raise EntityReviewError("A description must not hold an email address.")
    reason = f"{DESCRIPTION_REVIEWED_PREFIX}{today}" if reviewed else DESCRIPTION_DRAFT_REASON
    return [{"modelName": "SemanticNode", "expected": {"id": node["id"], "description": description, "changeReason": reason, "updatedAt": now}}]
