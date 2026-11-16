"""The queue of concepts a page needs named: ``concept C is needed in language L`` (docs/multilingual-labels.md).

Naming a concept costs model calls and needs the operator lane, so nothing that tags a Story or publishes a translation names a concept itself. It records the need
as one row per concept and language, in the work index (``syncState: wanted``, ``role: wanted``, ``origin: wanted``): no new table, and the next drain finds the rows
with one query per language. Recording is idempotent and cheap, and it never touches a name: a concept that has a label in the language (current, pinned, held or
being remade) is not recorded, and a wanted row is never made over a label. ``drain`` names what is wanted with the label procedure, dearest last, and stops at the
ceiling; what it did not reach stays wanted, so a second run goes on from there.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from .keys import CONCEPT, WANTED, entity_key, sort_key, wanted_id, work_key
from .primary import lineage_of, preferred_name
from .store import LabelStore
from .settings import site_primary_language
from .triggers import needs_name

ORIGIN = "wanted"


def served_languages(client: Any) -> list[str]:
    """The languages the site serves besides its primary one, as the editorial settings list them."""
    row = client.get_record("EditorialCheckSettings", "settings")
    values = json.loads(row["settings"]) if row and isinstance(row.get("settings"), str) else (row or {}).get("settings") or {}
    languages = values.get("languages") or {}
    return [str(tag) for tag in languages.get("enabled") or () if tag and tag != languages.get("primary")]


def record_wanted(client: Any, *, language: str | None, nodes: Iterable[dict[str, Any]], now: str) -> int:
    """Record that each concept in ``nodes`` is needed in ``language``; the number of rows written. The primary language, a concept written in ``language``, one that
    already has a label there and one already recorded write nothing."""
    if not language:
        return 0
    try:
        primary = site_primary_language(client)
    except ValueError:
        return 0   # a site that has not named its primary language yet serves no other language, so no concept is needed in one
    if language == primary:
        return 0
    store = LabelStore(client)
    written = 0
    for node in nodes:
        if node.get("language") == language or not needs_name(client, node, language):
            continue
        key = entity_key(CONCEPT, lineage_of(node))
        row_id = wanted_id(key, language)
        if any(row["id"] == row_id for row in store.of_entity(key, language)):
            continue
        name = preferred_name(node)
        store.create({"id": row_id, "entityKind": CONCEPT, "entityId": lineage_of(node), "entityKey": key, "language": language, "role": WANTED, "text": name,
                      "nameKey": f"{WANTED}#{key}#{language}", "sortKey": sort_key(language, WANTED, name), "origin": ORIGIN, "syncState": WANTED,
                      "workKey": work_key(language, WANTED, store.tenant_id, CONCEPT), "createdAt": now, "updatedAt": now})
        written += 1
    return written


def wanted_rows(client: Any, language: str) -> list[dict[str, Any]]:
    return sorted(LabelStore(client).needing_work(language, WANTED), key=lambda row: row["sortKey"])


def _node_of(client: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    found = [node for node in client.list_by_index("semanticNodesByLineage", row["entityId"]) if node.get("versionState", "current") == "current"]
    return found[0] if found else None


def drain(client: Any, *, localize: Callable[..., list[dict[str, Any]]], languages: list[str] | None = None, ceiling_usd: float | None = None, dry_run: bool = False,
           say: Callable[[str], None] = lambda line: None) -> dict[str, Any]:
    """Name the wanted concepts. ``{named, skipped, remaining, costUsd, stopped}``: a row whose concept already has a name, or no longer exists, is dropped without
    asking; the ceiling is checked before each concept, so one more concept than the ceiling is the most that is ever spent over it."""
    store = LabelStore(client)
    report: dict[str, Any] = {"named": 0, "skipped": 0, "remaining": 0, "costUsd": 0.0, "stopped": False}
    for language in languages if languages is not None else served_languages(client):
        for row in wanted_rows(client, language):
            if ceiling_usd is not None and report["costUsd"] >= ceiling_usd:
                report["stopped"] = True
                report["remaining"] += 1
                continue
            node = _node_of(client, row)
            if node is None or not needs_name(client, node, language):
                report["skipped"] += 1
                if not dry_run:
                    store.delete(row["id"])
                continue
            for made in localize(client, node, language, dry_run=dry_run):
                report["costUsd"] += float(made.get("costUsd") or 0)
                say(f"{made.get('concept') or row['text']}\t{language}\t{made.get('state')}")
            report["named"] += 1
            if not dry_run:
                store.delete(row["id"])
    return report


# ---- the two events that need a name -----------------------------------------------------------------------------------------------------------------------------

def story_concepts(client: Any, lineage: str) -> list[dict[str, Any]]:
    """The accepted concepts the Story ``lineage`` is tagged with (``tagged_with``, or the legacy ``related_to``): what a Story is about is written once, on the original,
    and a translation reads it there."""
    rows = [row for row in client.list_by_index("semanticRelationsBySubjectState", f"item#{lineage}#current")
            if row.get("objectKind") == "semanticNode" and row.get("objectId") and row.get("relationState", "current") == "current"]
    nodes = client.get_records_by_id("SemanticNode", [str(row["objectId"]) for row in rows]) if rows else {}
    return [nodes[str(row["objectId"])] for row in rows if nodes.get(str(row["objectId"]), {}).get("status") == "accepted"]


def published_translation_languages(client: Any, original_lineage: str) -> list[str]:
    """The languages the Story ``original_lineage`` is published in besides its own: one query on the language group and a point read per translation."""
    from ..publishing import published_item_id_for

    languages = set()
    for row in client.list_by_index("itemsByLanguageGroup", original_lineage):
        lineage = row.get("lineageId") or row["id"]
        if lineage != original_lineage and row.get("language") and client.get_record("PublishedItem", published_item_id_for(lineage)) is not None:
            languages.add(str(row["language"]))
    return sorted(languages)


def record_wanted_for_translation(client: Any, original_lineage: str, language: str, *, now: str) -> int:
    """A translation in ``language`` of the Story ``original_lineage`` is being published: the concepts the original is tagged with are needed in ``language``."""
    return record_wanted(client, language=language, nodes=story_concepts(client, original_lineage), now=now)


def record_wanted_for_tagging(client: Any, original_lineage: str, nodes: Iterable[dict[str, Any]], *, now: str) -> int:
    """The Story ``original_lineage`` was tagged with ``nodes``: each is needed in every language the Story is published in."""
    nodes = list(nodes)
    return sum(record_wanted(client, language=language, nodes=nodes, now=now) for language in published_translation_languages(client, original_lineage))


def record_wanted_for_page(client: Any, entity_key_text: str, *, now: str) -> int:
    """A concept's own page was published (``entity_key_text`` is the page's ``entityKey``: the concept's node key, or the part after ``editor_concept--``): its name is
    needed in every language the site serves. A key that is no concept's, or one that is not accepted, writes nothing."""
    languages = served_languages(client)
    if not languages or not entity_key_text:
        return 0
    node = next((found for key in (entity_key_text, f"editor_concept--{entity_key_text}") for found in client.list_by_index("semanticNodesByNodeKey", key)
                 if found.get("versionState", "current") == "current" and found.get("status") == "accepted"), None)
    if node is None:
        return 0
    return sum(record_wanted(client, language=language, nodes=[node], now=now) for language in languages)
