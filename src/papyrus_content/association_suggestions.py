"""`papyrus stories suggest-associations` (read only): concept, story, post and Reference candidates for an item, derived from the item's own text.

``stories suggest-links`` starts from the concepts an item already carries, so an untagged item gets nothing and an agent has to invent search phrases. Here ONE
query is built from the item (title, summary, the first ~300 words of the body, existing concept names). Step 1 finds candidate Concepts: the accepted concepts'
names, aliases and #hashtags matched on word boundaries in that text (no model, no key, any lane), ranked by rarity and position (title over summary over body),
plus, when the caller has an embedding key and a vector index, the concepts nearest the query by meaning; without them it is lexical only and says so in one line.
Step 2 hands the top concepts to ``link_suggestions.suggest_links`` as seeds, so related Stories, Posts and References are ranked even before any tag exists.
Nothing is written. The site's sections and publication types are not known here.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .concept_search import accepted_concepts, default_provider, search_concepts
from .concept_tags import concept_page_keys, has_public_page
from .link_suggestions import W_CURATED, Graph, _idf, _lineage, suggest_links
from .section_concepts import concept_label, current_concept_nodes, name_part

BODY_WORDS = 300
SEED_CONCEPTS = 8              # concepts handed to the graph pass
SEED_WEIGHT_MIN, SEED_WEIGHT_MAX = 0.4, 0.8   # below a curated tag (1.0): the text only suggests
W_TITLE, W_SUMMARY, W_BODY = 3.0, 2.0, 1.0
MAX_BODY_HITS = 3
SHORT_NAME = 3                 # names this short or shorter must match in their own letter case ("AI" is not "ai")
MEANING_BONUS = 1.0            # added to a concept that the vector search also found, scaled by similarity
CONCEPT_ARG = {"item": ("papyrus stories link-concept --story", "--concept"), "reference": ("papyrus references link-concept --reference", "--concept")}


def item_text(client: Any, kind: str, ref: str) -> dict[str, Any]:
    """``{"kind", "lineageId", "title", "summary", "body"}`` of a story (``item``) or a Reference, with the body cut to the first ``BODY_WORDS`` words."""
    if kind == "reference":
        from .priming_export import reference_content
        from .story_reporting import current_reference

        row = current_reference(client, ref)
        if row is None:
            raise ValueError(f"Reference not found: {ref}")
        try:
            content = reference_content(client, row, None)
        except Exception:   # noqa: BLE001 - a Reference whose stored text cannot be read is matched on its title alone
            content = {"summary": "", "body": ""}
        title, summary, body = str(row.get("title") or ""), content["summary"], content["body"]
    else:
        from .story_links import resolve_story

        row = resolve_story(client, ref)
        body = row.get("body")
        title, summary, body = str(row.get("headline") or row.get("title") or ""), str(row.get("deck") or ""), "\n".join(body) if isinstance(body, list) else str(body or row.get("bodyMarkus") or "")
    return {"kind": kind, "lineageId": _lineage(row), "title": title, "summary": summary, "body": " ".join(body.split()[:BODY_WORDS])}


def hashtag_names(node: dict[str, Any]) -> list[str]:
    """The names a concept answers to: display name, aliases and the #hashtag (the node key's name part, hyphens and underscores read as spaces)."""
    tag = re.sub(r"[-_]+", " ", name_part(str(node.get("nodeKey") or ""))).strip()
    names: dict[str, str] = {}
    for value in (node.get("displayName"), *(node.get("aliases") or []), tag):
        if value and len(value.strip()) >= 2:
            names.setdefault(" ".join(value.lower().split()), value.strip())   # the written form wins over the same hashtag in lower case
    return list(names.values())


def _occurrences(name: str, text: str) -> int:
    """How often the name stands alone in the text: word boundaries, so a short name is not found inside a longer word."""
    pattern = re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(part) for part in name.split()) + r"(?![A-Za-z0-9])", 0 if len(name) <= SHORT_NAME and name.isupper() else re.IGNORECASE)
    return len(pattern.findall(text))


def lexical_matches(nodes: list[dict[str, Any]], text: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{lineage: {"node", "position", "where", "matched"}}`` for each accepted concept named in the text; ``position`` is the title, summary and body weight."""
    found: dict[str, dict[str, Any]] = {}
    for node in nodes:
        best: dict[str, Any] | None = None
        for name in hashtag_names(node):
            where = [(label, weight, _occurrences(name, text[label])) for label, weight in (("title", W_TITLE), ("summary", W_SUMMARY), ("body", W_BODY))]
            position = sum(weight * (min(hits, MAX_BODY_HITS) if label == "body" else min(hits, 1)) for label, weight, hits in where)
            if position and (best is None or position > best["position"]):
                best = {"node": node, "position": position, "where": [label for label, _, hits in where if hits], "matched": name}
        if best:
            found[_lineage(node)] = best
    return found


def meaning_matches(client: Any, query: str) -> tuple[dict[str, float], str | None]:
    """``({lineage: similarity}, note)`` from the vector index when this lane can embed (an embedding key and an index); otherwise ``({}, one-line note)``."""
    if not os.environ.get("OPENAI_API_KEY"):
        return {}, "Meaning search skipped (no embedding key in this lane); concepts matched by name only."
    try:
        provider = default_provider()
    except Exception as error:   # noqa: BLE001 - an unreadable index configuration is a lexical-only run
        return {}, f"Meaning search skipped ({error}); concepts matched by name only."
    if provider is None:
        return {}, "Meaning search skipped (no vector index is configured); concepts matched by name only."
    result = search_concepts(client, provider, query, limit=SEED_CONCEPTS * 2)
    found = {entry["lineageId"]: entry["similarity"] for entry in result["results"] if entry["reason"] == "meaning" and entry["similarity"] is not None}
    return found, None if found else (result.get("indexNote") or "Meaning search found no concept vectors; concepts matched by name only.").split("\n")[0]


def suggest_associations(client: Any, kind: str, ref: str, *, kinds: tuple[str, ...] = ("articles", "posts", "references"), limit: int = 5, concept_limit: int = 10) -> dict[str, Any]:
    """Ranked candidate concepts and related stories, posts and References for one story (``kind="item"``) or Reference (``"reference"``). Read only."""
    text = item_text(client, kind, ref)
    nodes = accepted_concepts(current_concept_nodes(client))
    by_lineage = {_lineage(node): node for node in nodes}
    lexical = lexical_matches(nodes, text)
    query = " ".join(part for part in (text["title"], text["summary"], text["body"]) if part)
    meaning, note = meaning_matches(client, query) if query else ({}, None)
    graph = Graph(client)
    graph.load_concepts(sorted(set(lexical) | set(meaning)))   # two batched reads: the carriers that make a concept rare or common
    total = graph.total_documents()
    scored = []
    for lineage in set(lexical) | set(meaning):
        position = lexical[lineage]["position"] if lineage in lexical else 0.0
        score = position * _idf(graph, lineage, total) + MEANING_BONUS * (meaning.get(lineage) or 0.0)
        scored.append((score, lineage))
    scored.sort(key=lambda pair: (-pair[0], concept_label(by_lineage[pair[1]]).lower()))
    top = scored[0][0] if scored else 1.0
    seeds = [(by_lineage[lineage], round(SEED_WEIGHT_MIN + (SEED_WEIGHT_MAX - SEED_WEIGHT_MIN) * score / top, 3)) for score, lineage in scored[:SEED_CONCEPTS] if score > 0]
    related = suggest_links(client, text["lineageId"], kinds=kinds, limit=limit, seeds=seeds, owner_kind=kind)
    tagged = {entry["lineageId"] for entry in related["concepts"] if entry["weight"] >= W_CURATED}   # a curated tag outweighs every text seed
    pages = concept_page_keys(client)
    prefix, flag = CONCEPT_ARG[kind]
    concepts = []
    for score, lineage in scored[:concept_limit]:
        node, hit = by_lineage[lineage], lexical.get(lineage)
        concepts.append({"lineageId": lineage, "name": concept_label(node), "nodeKey": node.get("nodeKey"), "score": round(score, 3),
                         "reason": "name and meaning" if hit and lineage in meaning else ("name" if hit else "meaning"), "where": hit["where"] if hit else [],
                         "matched": hit["matched"] if hit else None, "similarity": meaning.get(lineage), "publicPage": has_public_page(node, pages),
                         "alreadyTagged": lineage in tagged,
                         "command": None if lineage in tagged else f"{prefix} {text['lineageId']} {flag} \"{node.get('nodeKey')}\""})
    notes = [value for value in (note, "No accepted concept is named in the item's text and it carries none, so there is nothing to rank from." if related.get("note") else None) if value]
    return {"item": {"kind": "reference" if kind == "reference" else "story", "lineageId": text["lineageId"], "title": text["title"]}, "concepts": concepts,
            "scanned": related["concepts"], "candidates": related["candidates"], "linkedStories": related["linkedStories"], "linkedReferences": related["linkedReferences"],
            "notes": notes, "requests": related["requests"]}
