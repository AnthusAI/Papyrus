"""Tagging a story or a Reference with a concept, rigidly: the shared resolver and wrapper behind ``stories link-concept``, ``references link-concept`` and the
``papyrus_link_concepts`` agent tool, plus the audit behind ``check-links``.

The edge is ``reference_links.link_item_concept`` / ``link_concept`` (docs/idea-context-packs.md section 2.2) with the one predicate ``CONCEPT_TAG_PREDICATE``
(``tagged_with``), kind ``item.concept`` / ``reference.concept``, a current relation to an ``accepted`` SemanticNode. Nothing here can create a concept or a node,
choose a predicate or a state, or match a name loosely:

* A concept is found by exact node key, exact hashtag (the part after ``--``), or exact name or alias, case-insensitive. None found is an error listing the closest
  accepted concepts; several found is an error listing them, so the caller picks a node key; a concept that is not accepted is refused by name.
* An existing current tag (``tagged_with``, the legacy ``related_to``, or a ``mentions`` the enrichment found) is reported and nothing is written; an edge a person
  rejected stays rejected and is reported (only the newsroom reinstates it).
* Each concept is reported with whether it has a public wiki page, because a story shows the concept as a link only once a published wiki page has the concept's slug
  (the part after ``editor_concept--``, else the whole node key) as its ``entityKey``.

``audit_story_links`` and ``audit_reference_links`` are read only and use indexes (the relations by state key, SemanticNodes by id); no table is scanned except the
published-story summaries ``stories check-links`` starts from.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any

from .concept_link_predicates import MENTIONS
from .reference_links import (
    CONCEPT_TAG_PREDICATE,
    CONCEPT_TAG_PREDICATES,
    ITEM_CONCEPT_KIND,
    ITEM_LINK_KIND,
    ITEM_REFERENCE_LINK_KIND,
    LEGACY_CONCEPT_TAG_PREDICATE,
    REFERENCE_CONCEPT_KIND,
    link_concept,
    link_item_concept,
    reference_link_relation_id,
)
from .section_concepts import CONCEPT_KEY_SEPARATOR, concept_label, current_concept_nodes, name_part
from .story_links import STORY_LINK_RELATION, resolve_story
from .story_reporting import STORY_REFERENCE_PREDICATE, current_reference

ACCEPTED = "accepted"
EDITOR_CONCEPT_PREFIX = "editor_concept--"
TARGET_KINDS = ("story", "reference")
PROVENANCES = ("human", "derived")   # a signed-in person; an agent acting for a newsroom procedure
WIKI_PAGE_STATUS_KEY = "wiki_page#published"
STATES = ("current", "suggested", "rejected")


def _flat(text: Any) -> str:
    return " ".join(str(text or "").split()).casefold()


def _lineage(node: dict[str, Any]) -> str:
    return str(node.get("lineageId") or node["id"])


def _label(node: dict[str, Any]) -> str:
    return f"{concept_label(node)} ({node.get('nodeKey')})"


def resolve_concepts(nodes: list[dict[str, Any]], texts: list[str]) -> list[dict[str, Any]]:
    """The accepted concept each text names, exactly, in order, without repeats. An unknown, ambiguous or non-accepted name is an error naming it."""
    found: dict[str, dict[str, Any]] = {}
    for text in texts:
        node = resolve_concept_exact(nodes, text)
        found.setdefault(_lineage(node), node)
    return list(found.values())


def resolve_concept_exact(nodes: list[dict[str, Any]], text: str) -> dict[str, Any]:
    typed = _flat(re.sub(r"^#+", "", str(text).strip()))
    if not typed:
        raise ValueError("A concept name is empty.")

    def keys_of(node: dict[str, Any]) -> tuple[str, str, set[str]]:
        key = _flat(node.get("nodeKey"))
        return key, name_part(key), {_flat(node.get("displayName")), *(_flat(alias) for alias in node.get("aliases") or [])} - {""}

    exact_key = [node for node in nodes if keys_of(node)[0] == typed]
    named = exact_key or [node for node in nodes if typed == keys_of(node)[1] or typed in keys_of(node)[2]]
    named = list({_lineage(node): node for node in named}.values())
    accepted = [node for node in named if node.get("status") == ACCEPTED]
    if len(accepted) == 1:
        return accepted[0]
    if len(accepted) > 1:
        raise ValueError(f"{text!r} means more than one concept; name one by its node key: " + ", ".join(sorted(str(node.get("nodeKey")) for node in accepted)))
    if named:
        raise ValueError(f"The concept {_label(named[0])} has status {named[0].get('status') or 'unknown'}; only accepted concepts can be tags.")
    pool = {}
    for node in nodes:
        if node.get("status") == ACCEPTED:
            for candidate in (_flat(node.get("nodeKey")), name_part(_flat(node.get("nodeKey"))), _flat(node.get("displayName"))):
                if candidate:
                    pool.setdefault(candidate, node)
    close = difflib.get_close_matches(typed, list(pool), n=5, cutoff=0.5)
    suggestions = list(dict.fromkeys(_label(pool[name]) for name in close))
    hint = " Closest accepted concepts: " + "; ".join(suggestions) + "." if suggestions else " No accepted concept is close to it."
    raise ValueError(f"No accepted concept is named {text!r} (exact node key, hashtag, name or alias only; a concept is never created here)." + hint)


def concept_page_keys(client) -> set[str]:
    """The ``entityKey`` of every published wiki page: one index read of the site's published wiki pages."""
    import yaml

    keys: set[str] = set()
    for row in client.list_by_index("publishedItemsByTypeStatus", WIKI_PAGE_STATUS_KEY):
        metadata = row.get("metadata")
        metadata = json.loads(metadata) if isinstance(metadata, str) and metadata else (metadata or {})
        raw = metadata.get("frontMatterYaml")
        try:
            front = yaml.safe_load(raw) if isinstance(raw, str) and raw.strip() else {}
        except yaml.YAMLError:
            front = {}
        key = (front or {}).get("entityKey") if isinstance(front, dict) else None
        if key:
            keys.add(str(key))
    return keys


def has_public_page(node: dict[str, Any], page_keys: set[str]) -> bool:
    key = str(node.get("nodeKey") or "")
    slug = key[len(EDITOR_CONCEPT_PREFIX):] if key.startswith(EDITOR_CONCEPT_PREFIX) else key
    return slug in page_keys or key in page_keys


def _existing_tag(client, state_kind: str, lineage: str, node: dict[str, Any]) -> dict[str, Any] | None:
    """The edge from this story or Reference to this concept in any predicate the readers accept, in the current or rejected state, else None."""
    node_lineage, node_id = _lineage(node), node["id"]
    for state in ("current", "rejected"):
        for row in client.list_by_index("semanticRelationsBySubjectState", f"{state_kind}#{lineage}#{state}"):
            if (row.get("objectKind") == "semanticNode" and row.get("predicate") in (*CONCEPT_TAG_PREDICATES, MENTIONS)
                    and str(row.get("objectLineageId") or row.get("objectId")) in {node_lineage, node_id}):
                return row
    return None


def tag_with_concepts(client, target_kind: str, target: str, concepts: list[str], *, actor: str | None, provenance: str, note: str | None = None, apply: bool = True,
                      on_row: Any = None) -> dict[str, Any]:
    """Tags a story or a Reference with accepted concepts. Everything is resolved before anything is written; one row per concept:
    ``nodeKey``, ``name``, ``outcome`` (``write``, ``exists``, ``rejected`` or ``dry run``), ``predicate`` of an existing edge, ``legacy`` (it is ``related_to``),
    ``publicPage`` and a ``warning`` when the concept has no public page or the edge was rejected."""
    if target_kind not in TARGET_KINDS:
        raise ValueError(f"target_kind must be one of {', '.join(TARGET_KINDS)}.")
    if provenance not in PROVENANCES:
        raise ValueError(f"provenance must be one of {', '.join(PROVENANCES)}.")
    if not [value for value in concepts if str(value).strip()]:
        raise ValueError("At least one concept is required.")
    if apply and not actor:
        raise ValueError("A tag needs to record who added it.")
    if target_kind == "story":
        story = resolve_story(client, target)
        lineage, state_kind = story.get("lineageId") or story["id"], "item"
    else:
        reference = current_reference(client, target)
        if reference is None:
            raise ValueError(f"Reference not found: {target}")
        lineage, state_kind = reference.get("lineageId") or reference["id"], "reference"
    nodes = resolve_concepts(current_concept_nodes(client), [str(value) for value in concepts])
    pages = concept_page_keys(client)
    rows = []
    for node in nodes:
        row: dict[str, Any] = {"target": lineage, "nodeKey": node.get("nodeKey"), "name": concept_label(node), "publicPage": has_public_page(node, pages)}
        existing = _existing_tag(client, state_kind, lineage, node)
        if existing and existing.get("relationState") == "rejected":
            row.update(outcome="rejected", predicate=existing.get("predicate"), warning="A person rejected this tag; nothing was written. Use the newsroom to reinstate it.")
        elif existing:
            row.update(outcome="exists", predicate=existing.get("predicate"), legacy=existing.get("predicate") == LEGACY_CONCEPT_TAG_PREDICATE)
        elif not apply:
            row["outcome"] = "dry run"
        else:
            if target_kind == "story":
                done = link_item_concept(client, lineage, node, provenance, actor=actor, note=note, story=story, predicate=CONCEPT_TAG_PREDICATE)
            else:
                done = link_concept(client, lineage, node, provenance, actor=actor, note=note, predicate=CONCEPT_TAG_PREDICATE)
            row.update(outcome="rejected" if done.get("outcome") == "rejected" else "write", relationId=done["relationId"])
        if row["outcome"] != "rejected" and not row["publicPage"]:
            row["warning"] = f"{row['name']} has no public wiki page yet, so the page will not show this concept as a link until one is published."
        rows.append(row)
        if on_row:
            on_row(row)
    return {"target": lineage, "targetKind": target_kind, "dryRun": not apply, "concepts": rows}


# ---- the audit -------------------------------------------------------------------------------------------------------------------------------------------------

def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata")
    return json.loads(raw) if isinstance(raw, str) and raw else (raw or {})


def _relations_for(client, keys: list[str]) -> dict[str, list[dict[str, Any]]]:
    if hasattr(client, "index_many"):
        return client.index_many("semanticRelationsBySubjectState", keys)
    return {key: client.list_by_index("semanticRelationsBySubjectState", key) for key in keys}


def _finding(owner: str, row: dict[str, Any], problem: str, detail: str = "") -> dict[str, Any]:
    return {"owner": owner, "relationId": row.get("id"), "predicate": row.get("predicate"), "state": row.get("relationState"),
            "object": row.get("objectLineageId"), "problem": problem, "detail": detail}


def _audit_concept_edges(owner: str, rows: list[dict[str, Any]], official_kind: str, nodes: dict[str, dict[str, Any]], pages: set[str]) -> list[dict[str, Any]]:
    findings = []
    seen: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        node = nodes.get(str(row.get("objectId")))
        predicate, state = row.get("predicate"), row.get("relationState")
        seen.setdefault(str(row.get("objectLineageId")), []).append(row)
        if predicate not in (MENTIONS, *CONCEPT_TAG_PREDICATES):
            findings.append(_finding(owner, row, "wrong predicate", f"expected {CONCEPT_TAG_PREDICATE} (or mentions from enrichment)"))
        elif predicate == LEGACY_CONCEPT_TAG_PREDICATE:
            findings.append(_finding(owner, row, "legacy: migrate", f"related_to is the old name of {CONCEPT_TAG_PREDICATE}"))
        if state != "current":
            findings.append(_finding(owner, row, "state not current", str(state)))
        if node is None:
            findings.append(_finding(owner, row, "concept missing", "no SemanticNode with that id"))
        elif node.get("status") != ACCEPTED:
            findings.append(_finding(owner, row, "concept not accepted", f"status {node.get('status')}"))
        elif predicate in CONCEPT_TAG_PREDICATES and not has_public_page(node, pages):
            findings.append(_finding(owner, row, "concept has no public page", str(node.get("nodeKey"))))
        if predicate in CONCEPT_TAG_PREDICATES and _metadata(row).get("kind") != official_kind:
            findings.append(_finding(owner, row, "wrong kind", f"expected {official_kind}, found {_metadata(row).get('kind')}"))
    for concept, group in seen.items():
        if len(group) > 1:
            findings.append(_finding(owner, group[0], "duplicate", f"{len(group)} edges to the same concept: " + ", ".join(sorted(str(row.get('predicate')) for row in group))))
    return findings


def _fetch_nodes(client, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    ids = [str(row["objectId"]) for row in rows if row.get("objectKind") == "semanticNode" and row.get("objectId")]
    return client.get_records_by_id("SemanticNode", ids) if ids else {}


def audit_story_links(client, lineage_ids: list[str]) -> list[dict[str, Any]]:
    """Every story-to-story and story-to-concept relation of these stories that is not the official shape (read only)."""
    from .publishing import published_item_id_for

    keys = [f"item#{lineage}#{state}" for lineage in lineage_ids for state in STATES]
    by_key = _relations_for(client, keys)
    pages = concept_page_keys(client)
    findings: list[dict[str, Any]] = []
    all_rows = {lineage: [row for state in STATES for row in by_key.get(f"item#{lineage}#{state}") or []] for lineage in lineage_ids}
    nodes = _fetch_nodes(client, [row for rows in all_rows.values() for row in rows])
    reference_ids = [str(row["objectId"]) for rows in all_rows.values() for row in rows if row.get("objectKind") == "reference" and row.get("objectId")]
    references = client.get_records_by_id("Reference", reference_ids) if reference_ids else {}
    pairs: dict[frozenset, list[dict[str, Any]]] = {}
    for lineage, rows in all_rows.items():
        concept_rows = [row for row in rows if row.get("objectKind") == "semanticNode"]
        findings.extend(_audit_concept_edges(lineage, concept_rows, ITEM_CONCEPT_KIND, nodes, pages))
        for row in (row for row in rows if row.get("objectKind") == "reference" and row.get("predicate") != STORY_REFERENCE_PREDICATE):
            if row.get("predicate") != STORY_LINK_RELATION:
                findings.append(_finding(lineage, row, "wrong predicate", f"expected {STORY_LINK_RELATION} or {STORY_REFERENCE_PREDICATE}"))
                continue
            if row.get("relationState") != "current":
                findings.append(_finding(lineage, row, "state not current", str(row.get("relationState"))))
            if _metadata(row).get("kind") != ITEM_REFERENCE_LINK_KIND:
                findings.append(_finding(lineage, row, "wrong kind", f"expected {ITEM_REFERENCE_LINK_KIND}, found {_metadata(row).get('kind')}"))
            found = references.get(str(row.get("objectId")))
            if found is None:
                findings.append(_finding(lineage, row, "reference missing", "no Reference with that id"))
            elif found.get("curationStatus") != ACCEPTED:
                findings.append(_finding(lineage, row, "reference not accepted", f"status {found.get('curationStatus')}"))
        for row in (row for row in rows if row.get("objectKind") == "item"):
            pairs.setdefault(frozenset((str(row.get("subjectLineageId")), str(row.get("objectLineageId")))), []).append(row)
            if row.get("predicate") != STORY_LINK_RELATION:
                findings.append(_finding(lineage, row, "wrong predicate", f"expected {STORY_LINK_RELATION}"))
            else:
                if row.get("relationState") != "current":
                    findings.append(_finding(lineage, row, "state not current", str(row.get("relationState"))))
                if _metadata(row).get("kind") != ITEM_LINK_KIND:
                    findings.append(_finding(lineage, row, "wrong kind", f"expected {ITEM_LINK_KIND}, found {_metadata(row).get('kind')}"))
                other = str(row.get("objectLineageId"))
                if other != lineage and client.get_record("PublishedItem", published_item_id_for(other)) is None:
                    findings.append(_finding(lineage, row, "target not published", other))
    for pair, group in pairs.items():
        unique = {row["id"]: row for row in group}
        if len(unique) > 1:
            findings.append(_finding(sorted(pair)[0], next(iter(unique.values())), "duplicate pair", f"{len(unique)} edges between the same two stories: " + ", ".join(sorted(unique))))
    return sorted(findings, key=lambda f: (f["owner"], str(f["relationId"]), f["problem"]))


def audit_reference_links(client, lineage_ids: list[str]) -> list[dict[str, Any]]:
    """Every Reference-to-concept relation of these References that is not the official shape (read only; index reads, 25 keys per request)."""
    keys = [f"reference#{lineage}#{state}" for lineage in lineage_ids for state in STATES]
    by_key = _relations_for(client, keys)
    pages = concept_page_keys(client)
    all_rows = {lineage: [row for state in STATES for row in by_key.get(f"reference#{lineage}#{state}") or [] if row.get("objectKind") == "semanticNode"] for lineage in lineage_ids}
    nodes = _fetch_nodes(client, [row for rows in all_rows.values() for row in rows])
    findings: list[dict[str, Any]] = []
    for lineage, rows in all_rows.items():
        findings.extend(_audit_concept_edges(lineage, rows, REFERENCE_CONCEPT_KIND, nodes, pages))
    return sorted(findings, key=lambda f: (f["owner"], str(f["relationId"]), f["problem"]))
