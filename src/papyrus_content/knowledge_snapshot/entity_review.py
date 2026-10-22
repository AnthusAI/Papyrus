"""Review of entities: the partial updates behind ``papyrus knowledge entities accept|reject|rename|describe``.

Pure functions over rows. A node is edited in place (same id, same lineage), so the links that point at it stay valid.
Accepting a node also confirms its extractor links: the reviewer has said the entity is real, and only confirmed links
are counted by the snapshot. Who accepted a node, who rejected it and who edited its description is kept in
``changeReason`` (see ``actors.py``); each command changes only its own part.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .actors import Actor, decode_review
from .keys import contains_email, normalize_name, kind_key
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


def accept_patches(node: Mapping[str, Any], mention_rows: Iterable[Mapping[str, Any]], *, actor: Actor, now: str, confirm_links: bool = True) -> list[dict]:
    """Accept a node as ``actor``. A node already accepted by the same actor and name is left as it is."""
    patches: list[dict] = []
    marks = decode_review(node.get("changeReason"))
    recorded = marks.accepted_by
    if node.get("status") != STATUS_ACCEPTED or recorded is None or (recorded.actor, recorded.name) != (actor.actor, actor.name):
        patches.append(
            {
                "modelName": "SemanticNode",
                "expected": {
                    "id": node["id"],
                    "status": STATUS_ACCEPTED,
                    "changeReason": marks.replace(accepted_by=actor, rejected_by=None).encode(),
                    "updatedAt": now,
                },
            }
        )
    if confirm_links:
        for row in mention_rows:
            metadata = json_object(row.get("metadata"))
            if (
                is_item_mention(row)
                and row.get("objectLineageId") == node.get("lineageId")
                and metadata.get("confirmed") is not True
                and metadata.get("linkSource", LINK_EXTRACTOR) == LINK_EXTRACTOR
            ):
                confirmed = {**metadata, "confirmed": True, "confirmedBy": actor.to_dict()}
                patches.append(
                    {
                        "modelName": "SemanticRelation",
                        "expected": {"id": row["id"], "metadata": json.dumps(confirmed, sort_keys=True), "updatedAt": now},
                    }
                )
    return patches


def reject_patches(node: Mapping[str, Any], *, actor: Actor, now: str) -> list[dict]:
    if node.get("status") == STATUS_REJECTED:
        return []
    marks = decode_review(node.get("changeReason"))
    return [
        {
            "modelName": "SemanticNode",
            "expected": {
                "id": node["id"],
                "status": STATUS_REJECTED,
                "changeReason": marks.replace(accepted_by=None, rejected_by=actor).encode(),
                "updatedAt": now,
            },
        }
    ]


def rename_patches(node: Mapping[str, Any], new_name: str, others: Iterable[Mapping[str, Any]], *, now: str) -> list[dict]:
    name = " ".join(new_name.split())
    if not name:
        raise EntityReviewError("A name is needed.")
    if contains_email(name):
        raise EntityReviewError("An entity name must not hold an email address.")
    if name == node.get("displayName"):
        return []
    kind = kind_key(node.get("nodeKind") or "")
    for other in others:
        if (
            other.get("id") != node.get("id")
            and other.get("versionState", "current") == "current"
            and other.get("status") in (STATUS_ACCEPTED, "generated")
            and kind_key(other.get("nodeKind") or "") == kind
            and normalize_name(name) in {normalize_name(other.get("displayName") or ""), *(normalize_name(alias) for alias in other.get("aliases") or ())}
        ):
            raise EntityReviewError(f"{other['id']} already has the name {name!r}; merge the two by hand.")
    aliases = [alias for alias in node.get("aliases") or () if normalize_name(alias) != normalize_name(name)]
    previous = " ".join(str(node.get("displayName") or "").split())
    if previous and normalize_name(previous) != normalize_name(name) and normalize_name(previous) not in {normalize_name(alias) for alias in aliases}:
        aliases.append(previous)
    return [{"modelName": "SemanticNode", "expected": {"id": node["id"], "displayName": name, "aliases": aliases, "updatedAt": now}}]


def alias_patches(node: Mapping[str, Any], alias: str, others: Iterable[Mapping[str, Any]], *, actor: Actor, now: str) -> list[dict]:
    """Add ``alias`` to a node as ``actor``, so a name the extractor keeps proposing resolves to this node.

    Nothing changes when the node already answers to the name. A name that another live node of the kind holds is
    refused (merge those by hand); a rejected duplicate holding the name does not count, that is the case this is for.
    """
    name = " ".join(alias.split())
    if not name:
        raise EntityReviewError("An alias is needed.")
    if contains_email(name):
        raise EntityReviewError("An alias must not hold an email address.")
    if node.get("status") == STATUS_REJECTED:
        raise EntityReviewError(f"{node['nodeKey']} is rejected; add the alias to the accepted entity.")
    wanted = normalize_name(name)
    if wanted in {normalize_name(node.get("displayName") or ""), *(normalize_name(existing) for existing in node.get("aliases") or ())}:
        return []
    kind = kind_key(node.get("nodeKind") or "")
    for other in others:
        if (
            other.get("id") != node.get("id")
            and other.get("versionState", "current") == "current"
            and other.get("status") in (STATUS_ACCEPTED, "generated")
            and kind_key(other.get("nodeKind") or "") == kind
            and wanted in {normalize_name(other.get("displayName") or ""), *(normalize_name(existing) for existing in other.get("aliases") or ())}
        ):
            raise EntityReviewError(f"{other['id']} already has the name {name!r}; merge the two by hand.")
    marks = decode_review(node.get("changeReason")).replace(aliased_by=actor)
    return [
        {
            "modelName": "SemanticNode",
            "expected": {"id": node["id"], "aliases": [*(node.get("aliases") or ()), name], "changeReason": marks.encode(), "updatedAt": now},
        }
    ]


def describe_patches(node: Mapping[str, Any], text: str, *, actor: Actor, now: str) -> list[dict]:
    """Set the description as ``actor``: a person's edit makes it ``reviewed``, an AI agent's ``ai_edited``."""
    description = " ".join(text.split())
    if not description:
        raise EntityReviewError("A description is needed.")
    if contains_email(description):
        raise EntityReviewError("A description must not hold an email address.")
    marks = decode_review(node.get("changeReason")).replace(description_edited_by=actor)
    return [{"modelName": "SemanticNode", "expected": {"id": node["id"], "description": description, "changeReason": marks.encode(), "updatedAt": now}}]
