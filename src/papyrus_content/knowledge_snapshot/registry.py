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
from pathlib import Path
from typing import Any

import yaml

from .keys import contains_email, kind_key, normalize_name
from .publish_run import STATUS_ACCEPTED

_NON_ALPHANUMERIC = re.compile(r"[\W_]+", re.UNICODE)


def alias_identity(alias: str) -> str:
    """The form in which the extractor compares aliases: case folded, every run of other characters one space."""
    return _NON_ALPHANUMERIC.sub(" ", normalize_name(alias)).strip()


def read_vocabulary_kinds(path: Path) -> list[str]:
    """The ``entity_kinds`` keys of a Biblicus vocabulary file (YAML or JSON), in file order."""
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = body.get("entity_kinds") if isinstance(body, dict) else None
    keys = [str(entry["key"]) for entry in entries or () if isinstance(entry, dict) and entry.get("key")]
    if not keys:
        raise ValueError(f"{path} has no entity_kinds with keys.")
    return keys


def build_registry(node_rows: Iterable[Mapping[str, Any]], vocabulary: Iterable[str] | None = None) -> tuple[list[dict], list[str]]:
    """``(registry, warnings)`` for the current accepted nodes, ordered by key, aliases in the node's own order.

    The kind of an entry is the canonical kind (``model_family``, whatever form the node stores). With the
    ``vocabulary`` keys it is the vocabulary's own key for that kind, and a node whose kind the vocabulary does not have
    is left out and reported, because the extractor refuses a registry with a kind outside its vocabulary. Stored nodes
    are never changed.
    """
    vocabulary_keys = {kind_key(key): key for key in vocabulary} if vocabulary is not None else None
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
        kind = kind_key(str(row.get("nodeKind") or ""))
        if vocabulary_keys is not None:
            if kind not in vocabulary_keys:
                warnings.append(f"{row['nodeKey']} has kind {row.get('nodeKind')!r}, which the vocabulary does not have; left out")
                continue
            kind = vocabulary_keys[kind]
        aliases = [name for name in names if len(claims[alias_identity(name)]) == 1]
        if aliases:
            registry.append({"key": row["nodeKey"], "kind": kind, "aliases": aliases})
    return registry, warnings
