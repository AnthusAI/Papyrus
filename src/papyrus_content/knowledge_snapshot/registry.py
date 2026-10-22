"""The registry the typed extractor resolves mentions with: every accepted entity, each with all of its names.

Pure: node rows in, the Biblicus registry (a JSON list of ``{key, kind, aliases}``) out. The aliases of an entity are its
display name and every alias it has (a rename keeps the old name as an alias), so ``Mistral`` and ``Mistral AI`` resolve
to the same node when the node holds both. The extractor refuses a registry in which one alias belongs to two entities,
so such an alias is left out of every entity that claims it and reported; the extractor then proposes that mention
instead of guessing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .keys import contains_email, normalize_name
from .publish_run import STATUS_ACCEPTED

_NON_ALPHANUMERIC = re.compile(r"[\W_]+", re.UNICODE)


def alias_identity(alias: str) -> str:
    """The form in which the extractor compares aliases: case folded, every run of other characters one space."""
    return _NON_ALPHANUMERIC.sub(" ", normalize_name(alias)).strip()


def build_registry(node_rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict], list[str]]:
    """``(registry, warnings)`` for the current accepted nodes, ordered by key, aliases in the node's own order."""
    nodes = sorted(
        (row for row in node_rows if row.get("versionState", "current") == "current" and row.get("status") == STATUS_ACCEPTED and row.get("nodeKey")),
        key=lambda row: str(row["nodeKey"]),
    )
    claims: dict[str, set[str]] = {}
    candidates: list[tuple[Mapping[str, Any], list[str]]] = []
    for row in nodes:
        names: list[str] = []
        seen: set[str] = set()
        for name in [row.get("displayName"), *(row.get("aliases") or ())]:
            text = " ".join(str(name or "").split())
            identity = alias_identity(text)
            if not identity or identity in seen or contains_email(text):
                continue
            seen.add(identity)
            names.append(text)
            claims.setdefault(identity, set()).add(str(row["nodeKey"]))
        candidates.append((row, names))
    warnings: list[str] = []
    for identity in sorted(claims):
        if len(claims[identity]) > 1:
            warnings.append(f"alias {identity!r} belongs to {', '.join(sorted(claims[identity]))}; left out of all of them")
    registry = []
    for row, names in candidates:
        aliases = [name for name in names if len(claims[alias_identity(name)]) == 1]
        if aliases:
            registry.append({"key": row["nodeKey"], "kind": row.get("nodeKind"), "aliases": aliases})
    return registry, warnings
