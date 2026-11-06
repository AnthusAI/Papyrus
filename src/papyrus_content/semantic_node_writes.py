"""The one rule for machine writes to a concept (``SemanticNode``): create it when missing, never change it when it exists.

A person's edits in the wiki (name, description, aliases, anything else) must survive every run. So an automated writer
either creates a node with ``create_only_record``, or, for a node that exists, writes a partial update of
``DERIVED_FIELDS`` only (``derived_fields_patch``; ``pageAnswer`` is the extractor's answer whether the concept has a page, which an editor's own decision, kept in ``changeReason``, outranks). Two exceptions are kept: a ``generated`` node becomes ``accepted``
when a published Story's front matter names it (``acceptance_patch``), and the acceptance mark in ``changeReason`` of a
node that same path created (``acceptance_mark_patch``).
"""

from __future__ import annotations

from typing import Any, Mapping

SEMANTIC_NODE_MODEL = "SemanticNode"

DERIVED_FIELDS = frozenset(
    {
        "authorityScore",
        "authorityRank",
        "acceptedReferenceMentionCount",
        "distinctSourceKindCount",
        "relationCount",
        "pageAnswer",
        "updatedAt",
    }
)

IDENTITY_FIELDS = frozenset({"displayName", "description", "aliases", "nodeKind", "nodeKey", "status"})


def is_identity_field(field_name: str) -> bool:
    """Every field that is not derived is identity: a machine never changes it on an existing node."""
    return field_name not in DERIVED_FIELDS


def create_only_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """A planned node write that creates the node and does nothing when it already exists."""
    return {"modelName": SEMANTIC_NODE_MODEL, "expected": dict(row), "createOnly": True}


def derived_fields_patch(existing: Mapping[str, Any], wanted: Mapping[str, Any], *, now: str) -> dict[str, Any] | None:
    """The partial update that brings the derived numbers of ``existing`` to ``wanted``, or ``None`` when they already match.

    Identity fields in ``wanted`` are ignored."""
    changed = {
        name: wanted[name]
        for name in sorted(DERIVED_FIELDS - {"updatedAt"})
        if name in wanted and existing.get(name) != wanted[name]
    }
    if not changed:
        return None
    return {"id": existing["id"], **changed, "updatedAt": now}


def derived_node_patch(existing: Mapping[str, Any], wanted: Mapping[str, Any], *, now: str) -> dict[str, Any] | None:
    """``derived_fields_patch`` as a planned patch of a publish plan (model name and expected row), or ``None`` when nothing differs."""
    patch = derived_fields_patch(existing, wanted, now=now)
    return None if patch is None else {"modelName": SEMANTIC_NODE_MODEL, "expected": patch}


def derived_fields_patch_change(existing: Mapping[str, Any], wanted: Mapping[str, Any], *, now: str) -> dict[str, Any] | None:
    patch = derived_fields_patch(existing, wanted, now=now)
    if patch is None:
        return None
    return {"modelName": SEMANTIC_NODE_MODEL, "expected": patch, "current": dict(existing), "action": "update"}


def acceptance_patch(existing: Mapping[str, Any], *, reason: str, now: str) -> dict[str, Any] | None:
    """Exception: a ``generated`` node moves to ``accepted`` on a published Story's front matter. Never from ``rejected`` or anything else."""
    if existing.get("status") != "generated":
        return None
    return {"modelName": SEMANTIC_NODE_MODEL, "expected": {"id": existing["id"], "status": "accepted", "changeReason": reason, "updatedAt": now}}


def acceptance_mark_patch(existing: Mapping[str, Any], *, reason: str, now: str) -> dict[str, Any]:
    """Exception: the acceptance mark in ``changeReason`` of a node the front-matter path itself created."""
    return {"modelName": SEMANTIC_NODE_MODEL, "expected": {"id": existing["id"], "changeReason": reason, "updatedAt": now}}
