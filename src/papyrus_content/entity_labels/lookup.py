"""Finding concepts by name with index queries: the node key, then the name in the languages asked (every name, other name and hashtag is a label row).

No function here lists the concept table. ``find_concepts`` reads one partition per reading; ``current_node`` reads one lineage.
"""
from __future__ import annotations

import re
from typing import Any

from ..section_concepts import CONCEPT_KEY_SEPARATOR, concept_slug
from .keys import CONCEPT, fold
from .primary import lineage_of
from .store import LabelStore


def current_node(client: Any, lineage_id: str) -> dict[str, Any] | None:
    """The current version of one concept: one query on the lineage."""
    rows = [row for row in client.list_by_index("semanticNodesByLineage", lineage_id) if row.get("versionState", "current") == "current"]
    return max(rows, key=lambda row: int(row.get("versionNumber") or 0), default=None)


def current_nodes(client: Any, lineage_ids: list[str]) -> dict[str, dict[str, Any]]:
    found = {}
    for lineage in dict.fromkeys(lineage_ids):
        node = current_node(client, lineage)
        if node is not None:
            found[lineage] = node
    return found


def lookup_languages(client: Any, language: str | None = None) -> list[str]:
    """The languages a typed name is read in: the caller's, then the site's primary."""
    return list(dict.fromkeys(tag for tag in (language, client.primary_language()) if tag))


def find_concepts(client: Any, text: str, *, languages: list[str] | None = None) -> list[dict[str, Any]]:
    """The concepts a typed name, alias, ``#hashtag`` or node key can mean, from the surest reading to the loosest; the first reading that finds any wins.

    The readings: an exact node key; the name (the preferred name, another name or the hashtag of the key) in each language asked, in order; the hashtag
    spelling of the typed words. A ``#hashtag (kind)`` is narrowed to concepts of that kind. Rejected concepts are returned too: the caller decides what
    a status means. Sorted by node key."""
    typed = fold(re.sub(r"^#+", "", text.strip()))
    kind_filter = None
    suffix = re.match(r"^(.*) \(([^()]*)\)$", typed)
    if suffix and text.strip().startswith("#"):
        typed, kind_filter = suffix.group(1).strip(), suffix.group(2).strip()
    if not typed:
        return []
    labels = LabelStore(client)
    languages = languages if languages is not None else lookup_languages(client)

    def of_kind(node: dict[str, Any]) -> bool:
        return kind_filter is None or str(node.get("nodeKey") or "").lower().split(CONCEPT_KEY_SEPARATOR, 1)[0] == kind_filter

    def by_key() -> list[dict[str, Any]]:
        return [row for row in client.list_by_index("semanticNodesByNodeKey", typed) if row.get("versionState", "current") == "current"]

    def by_name(name: str):
        def read() -> list[dict[str, Any]]:
            for language in languages:
                lineages = [row["entityId"] for row in labels.named(language, name, CONCEPT)]
                if lineages:
                    return list(current_nodes(client, lineages).values())
            return []
        return read

    readings = [by_key, by_name(typed)]
    slug = concept_slug(typed)
    if slug and slug != typed:
        readings.append(by_name(slug))
    for read in readings:
        distinct = {lineage_of(node): node for node in read() if of_kind(node)}
        if distinct:
            return sorted(distinct.values(), key=lambda node: str(node.get("nodeKey") or ""))
    return []
