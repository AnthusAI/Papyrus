"""The rows a concept's own text makes, and keeping them true.

A concept (``SemanticNode``) is written in one language, ``SemanticNode.language``. Its name, its other names and the hashtag of its node key are
``EntityLabel`` rows in that language (origin ``primary``), so a concept is found by any of them with one index query. The node is the truth: nothing
edits these rows by hand, and ``sync_node`` is the only writer of them (the stream consumer of ``amplify/functions/entity-label-sync`` calls it
for every change of a node, and the backfill calls it once for every node that exists).

``primary_text_hash`` is the hash of the text a translation of the concept is made from. A translated label records it; when the node's text changes,
every translated label made from the old text becomes ``stale`` (or ``conflict`` when a person pinned its wording) and shows up in the work index.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..section_concepts import name_part
from .keys import ALIAS, CONCEPT, CONFLICT, CURRENT, HIDDEN, PREFERRED, STALE, entity_key, fold, label_id, name_key, sort_key, work_key
from .store import LabelStore

PRIMARY = "primary"


def lineage_of(node: dict[str, Any]) -> str:
    return str(node.get("lineageId") or node["id"])


def preferred_name(node: dict[str, Any]) -> str:
    """What a concept is called: its name, else the words of its key, else its key, else its id (a concept with no name at all is still found by its id)."""
    return str(node.get("displayName") or "").strip() or name_part(str(node.get("nodeKey") or "")).replace("-", " ") or str(node.get("nodeKey") or "") or lineage_of(node)


def primary_text(node: dict[str, Any]) -> dict[str, Any]:
    """What a translation of the concept is made from: the name, the other names and the description."""
    return {"name": preferred_name(node), "aliases": sorted({" ".join(str(alias).split()) for alias in node.get("aliases") or [] if str(alias).strip()}),
            "description": str(node.get("description") or "").strip()}


def primary_text_hash(node: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(primary_text(node), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def primary_rows(node: dict[str, Any], language: str, *, tenant_id: str | None, now: str) -> list[dict[str, Any]]:
    """The label rows the node's text makes in ``language``: the preferred name, each other name, and the hashtag (the name part of the node key)."""
    lineage = lineage_of(node)
    key = entity_key(CONCEPT, lineage)
    text = primary_text(node)
    seen = {fold(text["name"])}
    names = [(PREFERRED, text["name"])]
    for alias in text["aliases"]:
        if fold(alias) not in seen:
            seen.add(fold(alias))
            names.append((ALIAS, alias))
    hashtag = name_part(str(node.get("nodeKey") or ""))
    if hashtag and fold(hashtag) not in seen:
        names.append((HIDDEN, hashtag))
    rows = []
    for role, name in names:
        row = {"id": label_id(key, language, role, name), "entityKind": CONCEPT, "entityId": lineage, "entityKey": key, "language": language, "role": role, "text": name,
               "nameKey": name_key(language, name, tenant_id, CONCEPT), "sortKey": sort_key(language, role, name), "origin": PRIMARY, "createdAt": now, "updatedAt": now}
        if role == PREFERRED:
            row.update(sourceContentHash=primary_text_hash(node), syncState=CURRENT)
        rows.append(row)
    return rows


_COMPARED = ("text", "role", "nameKey", "sortKey", "sourceContentHash", "syncState")


def sync_node(client: Any, node: dict[str, Any], *, primary_language: str, now: str) -> dict[str, int]:
    """Bring the label rows of one concept to what its text says; counts of ``created``, ``updated``, ``deleted``, ``language`` (1 when the node had no
    language and was given the site's primary language) and ``stale`` (translated labels now out of date). Idempotent: a second call writes nothing."""
    counts = {"created": 0, "updated": 0, "deleted": 0, "language": 0, "stale": 0}
    language = node.get("language")
    if not language:
        client.update_record("SemanticNode", {"id": node["id"], "language": primary_language})
        language, counts["language"] = primary_language, 1
    store = LabelStore(client)
    lineage = lineage_of(node)
    existing = store.of_entity(entity_key(CONCEPT, lineage))
    wanted = {row["id"]: row for row in primary_rows(node, language, tenant_id=store.tenant_id, now=now)}
    mine = {row["id"]: row for row in existing if row.get("origin") == PRIMARY}
    for row_id, row in wanted.items():
        have = mine.get(row_id)
        if have is None:
            store.create(row)
            counts["created"] += 1
        elif any(have.get(name) != row.get(name) for name in _COMPARED if row.get(name) is not None):
            store.update({name: row[name] for name in ("id", "text", "role", "nameKey", "sortKey", "sourceContentHash", "syncState") if name in row} | {"updatedAt": now})
            counts["updated"] += 1
    for row_id in mine.keys() - wanted.keys():
        store.delete(row_id)
        counts["deleted"] += 1
    current_hash = primary_text_hash(node)
    for row in existing:
        if row.get("origin") == PRIMARY or row.get("role") != PREFERRED or row.get("language") == language:
            continue
        if row.get("sourceContentHash") and row["sourceContentHash"] != current_hash and row.get("syncState") == CURRENT:
            state = CONFLICT if row.get("pinned") else STALE
            store.update({"id": row["id"], "syncState": state, "workKey": work_key(row["language"], state, store.tenant_id, CONCEPT), "updatedAt": now})
            counts["stale"] += 1
    return counts
