"""Related Concepts and suggested links, computed from the graph with no model call (docs/story-reporting.md, "Suggesting related content").

Two hops. First the related *concepts* of a concept (``related_concepts``): editor-confirmed concept-to-concept links with their written explanation, aliases
and ``same_as``, then concepts that co-occur on the same published stories and accepted References, with a lift-style strength so hubs do not dominate.
Then the *carriers* (``suggest_links``): the published stories and accepted References that carry the story's own concepts (weight 1.0 curated, 0.4 mentioned)
or a related concept (about 0.5 confirmed, about 0.3 times strength co-occurring), scored by rarity (IDF), so a person or model judges a short ranked list.

Every read goes through an index or a batched get (25 keys to a request); no table is scanned (the one exception is the concept catalogue the exact resolver
of ``stories link-concept`` already reads). Nothing here writes.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .concept_link_predicates import CONCEPT_KIND, CONCEPT_LINK_PREDICATES, MENTIONS
from .reference_links import SEE_ALSO
from .section_concepts import concept_label

SUBJECT_STATE = "semanticRelationsBySubjectState"
OBJECT_STATE = "semanticRelationsByObjectState"
STORY_TYPES = ("article", "post")
CONCEPT_LINK_PREDICATES_BETWEEN = ("related_to", "same_as", "alias_of")
EVIDENCE = "uses_evidence"
BATCH = 25

SAMPLE_CARRIERS = 60          # newest carriers of a concept read for co-occurrence
MIN_CO_COUNT = 2             # a concept must appear with this one on at least this many carriers
MIN_LIFT = 1.5
NEIGHBOURS_PER_CONCEPT = 8    # related concepts of one story concept that are scanned for carriers
W_CURATED, W_MENTIONED = 1.0, 0.4
W_CONFIRMED, W_COOCCURRENCE, W_LINKED = 0.5, 0.3, 0.3
MENTION_CARRIER_FACTOR = 0.6   # the candidate only mentions the concept (extracted text) rather than being tagged
HUB_SHARE, HUB_IDF = 0.25, 0.1  # a concept carried by more than 25% of the stories counts at a low weight
RECENCY_BONUS = 0.1            # at most +10% for a candidate published today, fading over a year


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata")
    if isinstance(raw, str) and raw:
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _lineage(row: dict[str, Any]) -> str:
    return str(row.get("lineageId") or row["id"])


def _index_many(client: Any, index: str, keys: list[str]) -> dict[str, list[dict[str, Any]]]:
    keys = [key for key in dict.fromkeys(keys) if key]
    if not keys:
        return {}
    if hasattr(client, "index_many"):
        return client.index_many(index, keys)
    return {key: list(client.list_by_index(index, key)) for key in keys}


def _get_many(client: Any, model: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = [value for value in dict.fromkeys(ids) if value]
    if not ids:
        return {}
    if hasattr(client, "get_many"):
        return client.get_many(model, ids)
    return client.get_records_by_id(model, ids)


def _requests(client: Any) -> int:
    from . import request_meter

    return request_meter.current_run().requests


def _parse_time(text: Any) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _explanation(relation: dict[str, Any]) -> str | None:
    from .ideas.signal_inputs import explanation_of

    return explanation_of(relation)


def _person_confirmed(relation: dict[str, Any]) -> bool:
    metadata = _metadata(relation)
    decided_by = str(metadata.get("decidedBy") or "")
    return bool(metadata.get("confirmed")) or (metadata.get("decision") == "accepted" and bool(decided_by) and not decided_by.startswith("auto:"))


class Graph:
    """The cached reads one run needs: concept nodes by id, the carriers of a concept, the concept edges of a carrier, the published stories."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self._nodes: dict[str, dict[str, Any]] = {}
        self._object_rows: dict[str, list[dict[str, Any]]] = {}      # concept lineage -> every row pointing at it
        self._subject_rows: dict[str, list[dict[str, Any]]] = {}     # concept lineage -> every row it points from
        self._edges: dict[str, list[dict[str, Any]]] = {}            # "item#L#current" / "reference#L#current" -> rows
        self._published: dict[str, dict[str, Any]] | None = None
        self._references: dict[str, dict[str, Any]] = {}

    # ---- stories -------------------------------------------------------------------------------------------------------------------------------------

    @property
    def published(self) -> dict[str, dict[str, Any]]:
        """Published articles and posts by lineage id (one read of the published summaries)."""
        if self._published is None:
            self._published = {str(row["itemLineageId"]): row for row in self.client.list_published_item_summaries()
                               if row.get("itemLineageId") and row.get("type") in STORY_TYPES}
        return self._published

    # ---- concepts ------------------------------------------------------------------------------------------------------------------------------------

    def nodes(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """The concept rows for these row ids, accepted ones only."""
        missing = [value for value in dict.fromkeys(ids) if value and value not in self._nodes]
        for node_id, row in _get_many(self.client, "SemanticNode", missing).items():
            self._nodes[node_id] = row
        for node_id in missing:
            self._nodes.setdefault(node_id, {})
        return {value: self._nodes[value] for value in ids if self._nodes.get(value) and self._nodes[value].get("status") == "accepted"}

    def load_concepts(self, lineages: list[str]) -> None:
        """Both directions of every concept's relations in two batched index reads (the object side also holds the stories and References that carry it)."""
        need_object = [f"semanticNode#{value}#current" for value in lineages if value not in self._object_rows]
        for key, rows in _index_many(self.client, OBJECT_STATE, need_object).items():
            self._object_rows[key.split("#")[1]] = rows
        need_subject = [f"semanticNode#{value}#current" for value in lineages if value not in self._subject_rows]
        for key, rows in _index_many(self.client, SUBJECT_STATE, need_subject).items():
            self._subject_rows[key.split("#")[1]] = rows

    def carriers(self, lineage: str) -> dict[str, dict[str, Any]]:
        """``{"item:<lineage>" | "reference:<lineage>": strongest edge}`` of the published stories and References that carry the concept (``tagged_with`` beats ``mentions``)."""
        found: dict[str, dict[str, Any]] = {}
        for row in self._object_rows.get(lineage, []):
            if row.get("subjectKind") not in ("item", "reference") or row.get("predicate") not in CONCEPT_LINK_PREDICATES or row.get("relationState") not in (None, "current"):
                continue
            owner = str(row.get("subjectLineageId") or "")
            if not owner or (row["subjectKind"] == "item" and owner not in self.published):
                continue
            key = f"{row['subjectKind']}:{owner}"
            if key not in found or (found[key].get("predicate") == MENTIONS and row.get("predicate") != MENTIONS):
                found[key] = row
        return found

    def document_frequency(self, lineage: str) -> tuple[int, int]:
        """``(published stories, References)`` that carry the concept."""
        kinds = Counter(key.split(":", 1)[0] for key in self.carriers(lineage))
        return kinds["item"], kinds["reference"]

    def total_documents(self) -> int:
        """The size of the carrier universe: the published stories plus a lower bound of the accepted References (the most any examined concept is carried by)."""
        references = max((self.document_frequency(lineage)[1] for lineage in self._object_rows), default=0)
        return max(len(self.published) + references, 1)

    def accepted_references(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """The accepted References among these row ids (a batched get)."""
        missing = [value for value in dict.fromkeys(ids) if value and value not in self._references]
        for ref_id, row in _get_many(self.client, "Reference", missing).items():
            self._references[ref_id] = row
        for ref_id in missing:
            self._references.setdefault(ref_id, {})
        return {value: self._references[value] for value in ids if self._references.get(value, {}).get("curationStatus") == "accepted"}

    def edges(self, owners: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Current relations whose subject is each ``item:<lineage>`` / ``reference:<lineage>``."""
        keys = {owner: f"{owner.split(':', 1)[0]}#{owner.split(':', 1)[1]}#current" for owner in owners}
        need = [key for key in keys.values() if key not in self._edges]
        self._edges.update(_index_many(self.client, SUBJECT_STATE, need))
        return {owner: self._edges.get(key, []) for owner, key in keys.items()}

    # ---- hop one -------------------------------------------------------------------------------------------------------------------------------------

    def related(self, concepts: list[dict[str, Any]], *, limit: int | None = None) -> dict[str, list[dict[str, Any]]]:
        """The concepts near each of the (accepted) concept rows, keyed by lineage: ``reason`` confirmed | alias | linked | cooccurrence, with the written
        ``explanation``, the co-occurrence ``count`` out of ``sampled`` carriers, ``lift``, ``strength`` (0 to 1) and the scan ``weight``."""
        lineages = [_lineage(node) for node in concepts]
        self.load_concepts(lineages)
        by_lineage = {_lineage(node): node for node in concepts}
        result: dict[str, list[dict[str, Any]]] = {lineage: [] for lineage in lineages}
        # (a) and (b): concept-to-concept links, in either direction
        link_rows: dict[str, list[tuple[dict[str, Any], str, str]]] = {lineage: [] for lineage in lineages}
        other_ids: list[str] = []
        for lineage in lineages:
            for row in self._subject_rows.get(lineage, []) + self._object_rows.get(lineage, []):
                if (row.get("subjectKind") == CONCEPT_KIND and row.get("objectKind") == CONCEPT_KIND and row.get("predicate") in CONCEPT_LINK_PREDICATES_BETWEEN
                        and row.get("relationState") in (None, "current")):
                    outgoing = str(row.get("subjectLineageId")) == lineage
                    other = str(row.get("objectLineageId") if outgoing else row.get("subjectLineageId"))
                    other_id = str(row.get("objectId") if outgoing else row.get("subjectId"))
                    if other and other != lineage:
                        link_rows[lineage].append((row, other, other_id))
                        other_ids.append(other_id)
        linked_nodes = self.nodes(other_ids)
        for lineage in lineages:
            seen: set[str] = set()
            for row, other, other_id in link_rows[lineage]:
                node = linked_nodes.get(other_id)
                if node is None or other in seen:
                    continue
                seen.add(other)
                predicate = str(row.get("predicate"))
                person = _person_confirmed(row)
                reason = "alias" if predicate in ("same_as", "alias_of") else ("confirmed" if person else "linked")
                result[lineage].append({"lineageId": _lineage(node), "nodeKey": node.get("nodeKey"), "name": concept_label(node), "reason": reason, "predicate": predicate,
                                        "explanation": _explanation(row), "weight": W_CONFIRMED if reason in ("confirmed", "alias") else W_LINKED})
        # (c): co-occurrence on the newest carriers
        samples: dict[str, list[str]] = {}
        for lineage in lineages:
            carriers = self.carriers(lineage)
            ordered = sorted(carriers, key=lambda key: str(carriers[key].get("createdAt") or ""), reverse=True)
            samples[lineage] = ordered[:SAMPLE_CARRIERS]
        reference_rows = {owner: self.carriers(lineage)[owner] for lineage in lineages for owner in samples[lineage] if owner.startswith("reference:")}
        accepted = self.accepted_references([str(row.get("subjectId")) for row in reference_rows.values()])
        for lineage in lineages:
            samples[lineage] = [owner for owner in samples[lineage] if not owner.startswith("reference:") or str(self.carriers(lineage)[owner].get("subjectId")) in accepted]
        edges = self.edges([owner for owners in samples.values() for owner in owners])
        counts: dict[str, Counter] = {}
        concept_ids: dict[str, str] = {}
        for lineage in lineages:
            counts[lineage] = Counter()
            for owner in samples[lineage]:
                for row in edges.get(owner, []):
                    other = str(row.get("objectLineageId") or "")
                    if row.get("objectKind") == CONCEPT_KIND and row.get("predicate") in CONCEPT_LINK_PREDICATES and other and other != lineage:
                        counts[lineage][other] += 1
                        concept_ids[other] = str(row.get("objectId"))
        top: dict[str, list[tuple[str, int]]] = {}
        for lineage in lineages:
            top[lineage] = [(other, count) for other, count in counts[lineage].most_common(40) if count >= MIN_CO_COUNT][:20]
        accepted_nodes = self.nodes([concept_ids[other] for pairs in top.values() for other, _ in pairs])
        usable = {other for pairs in top.values() for other, _ in pairs if concept_ids[other] in accepted_nodes}
        self.load_concepts(sorted(usable))
        total = self.total_documents()
        for lineage in lineages:
            already = {entry["lineageId"] for entry in result[lineage]}
            sampled = max(len(samples[lineage]), 1)
            own_df = sum(self.document_frequency(lineage))
            for other, count in top[lineage]:
                if other not in usable or other in already:
                    continue
                other_df = max(sum(self.document_frequency(other)), 1)
                lift = (count / sampled) / (other_df / total)
                if lift < MIN_LIFT:
                    continue
                strength = min(1.0, math.log10(lift) / 2)
                node = accepted_nodes[concept_ids[other]]
                result[lineage].append({"lineageId": other, "nodeKey": node.get("nodeKey"), "name": concept_label(node), "reason": "cooccurrence", "count": count,
                                        "sampled": sampled, "lift": round(lift, 2), "strength": round(strength, 2), "weight": round(W_COOCCURRENCE * strength, 3)})
            result[lineage].sort(key=lambda entry: ({"confirmed": 0, "alias": 1, "linked": 2, "cooccurrence": 3}[entry["reason"]], -(entry.get("strength") or 0), -entry.get("count", 0), entry["name"]))
            if limit is not None:
                result[lineage] = result[lineage][:limit]
            del own_df
        return result


def related_concepts(client: Any, concept: str, *, limit: int = 15) -> dict[str, Any]:
    """The concepts near one concept (read only). The concept is found by the same exact resolver as ``stories link-concept``; it is never created or guessed."""
    from .concept_tags import concept_page_keys, has_public_page, resolve_concept_exact
    from .section_concepts import current_concept_nodes

    before = _requests(client)
    node = resolve_concept_exact(current_concept_nodes(client), concept)
    graph = Graph(client)
    related = graph.related([node], limit=limit)[_lineage(node)]
    return {"concept": {"lineageId": _lineage(node), "nodeKey": node.get("nodeKey"), "name": concept_label(node), "publicPage": has_public_page(node, concept_page_keys(client))},
            "carriers": dict(zip(("stories", "references"), graph.document_frequency(_lineage(node)))), "related": related, "requests": _requests(client) - before}


# ---- hop two ---------------------------------------------------------------------------------------------------------------------------------------------

KIND_LABELS = {"articles": "See also", "posts": "Posts", "references": "Related findings"}


def _idf(graph: Graph, lineage: str, total: int) -> float:
    stories, references = graph.document_frequency(lineage)
    value = max(math.log((total + 1) / (stories + references + 1)), 0.05)
    if len(graph.published) and stories / len(graph.published) > HUB_SHARE:
        value = min(value, HUB_IDF)
    return value


def suggest_links(client: Any, story_ref: str, *, kinds: tuple[str, ...] = ("articles", "posts", "references"), limit: int = 5, min_score: float = 0.0,
                  now: datetime | None = None) -> dict[str, Any]:
    """Ranked candidates to link from a story (read only): other published articles and posts, and accepted References, that share its concepts directly or through a related concept."""
    from .story_links import resolve_story

    before = _requests(client)
    story = resolve_story(client, story_ref)
    lineage = _lineage(story)
    graph = Graph(client)
    rows = _index_many(client, SUBJECT_STATE, [f"item#{lineage}#current"]).get(f"item#{lineage}#current", [])
    incoming = _index_many(client, OBJECT_STATE, [f"item#{lineage}#current"]).get(f"item#{lineage}#current", [])
    concept_ids: dict[str, tuple[str, float]] = {}   # node row id -> (lineage, weight)
    linked_stories, linked_references = {lineage}, set()
    for row in rows:
        if row.get("relationState") not in (None, "current"):
            continue
        if row.get("objectKind") == CONCEPT_KIND and row.get("predicate") in CONCEPT_LINK_PREDICATES:
            weight = W_CURATED if row.get("predicate") != MENTIONS else W_MENTIONED
            key = str(row.get("objectId"))
            if key not in concept_ids or concept_ids[key][1] < weight:
                concept_ids[key] = (str(row.get("objectLineageId")), weight)
        elif row.get("predicate") == SEE_ALSO and row.get("objectKind") == "item":
            linked_stories.add(str(row.get("objectLineageId")))
        elif row.get("objectKind") == "reference" and row.get("predicate") in (SEE_ALSO, EVIDENCE):
            linked_references.add(str(row.get("objectLineageId")))
    for row in incoming:
        if row.get("predicate") == SEE_ALSO and row.get("subjectKind") == "item" and row.get("relationState") in (None, "current"):
            linked_stories.add(str(row.get("subjectLineageId")))
    accepted = graph.nodes(list(concept_ids))
    own: dict[str, dict[str, Any]] = {}   # concept lineage -> {"node", "weight"}
    for node_id, node in accepted.items():
        own[_lineage(node)] = {"node": node, "weight": concept_ids[node_id][1]}
    result: dict[str, Any] = {"story": {"lineageId": lineage, "title": story.get("headline") or story.get("title") or lineage}, "concepts": [], "candidates": {kind: [] for kind in kinds},
                              "linkedStories": len(linked_stories) - 1, "linkedReferences": len(linked_references)}
    if not own:
        result["note"] = "The story has no accepted concepts, so there is nothing to start from. Tag it with `papyrus stories link-concept` first."
        result["requests"] = _requests(client) - before
        return result
    neighbours = graph.related([entry["node"] for entry in own.values()], limit=NEIGHBOURS_PER_CONCEPT)
    scan = set(own)
    contributions: dict[str, dict[str, dict[str, Any]]] = {}   # concept lineage -> {"name", "weight", "path"}
    for lineage_id, entry in own.items():
        contributions[lineage_id] = {"name": concept_label(entry["node"]), "weight": entry["weight"], "path": "direct"}
    for source, found in neighbours.items():
        for neighbour in found:
            other = neighbour["lineageId"]
            if other in own:
                continue
            current = contributions.get(other)
            weight = neighbour["weight"] * own[source]["weight"] if neighbour["reason"] == "cooccurrence" else neighbour["weight"]
            if current is None or weight > current["weight"]:
                contributions[other] = {"name": neighbour["name"], "weight": weight, "path": f"via {concept_label(own[source]['node'])}, then {neighbour['name']}"}
            scan.add(other)
    graph.load_concepts(sorted(scan))
    total = graph.total_documents()
    result["concepts"] = [{"lineageId": key, "name": value["name"], "weight": round(value["weight"], 3), "path": value["path"]} for key, value in contributions.items()]
    scores: dict[str, dict[str, Any]] = {}
    for concept_lineage, info in contributions.items():
        idf = _idf(graph, concept_lineage, total)
        for owner, edge in graph.carriers(concept_lineage).items():
            kind, owner_lineage = owner.split(":", 1)
            if (kind == "item" and owner_lineage in linked_stories) or (kind == "reference" and owner_lineage in linked_references):
                continue
            factor = MENTION_CARRIER_FACTOR if edge.get("predicate") == MENTIONS else 1.0
            entry = scores.setdefault(owner, {"score": 0.0, "shared": [], "best": (0.0, ""), "subjectId": edge.get("subjectId")})
            part = info["weight"] * idf * factor
            entry["score"] += part
            entry["shared"].append((part, info["name"]))
            if part > entry["best"][0]:
                entry["best"] = (part, info["path"])
    moment = now or datetime.now(timezone.utc)

    def finish(kind: str, owner: str, entry: dict[str, Any], title: str, kind_label: str, when: Any, extra: dict[str, Any]) -> dict[str, Any]:
        stamp = _parse_time(when)
        recency = max(0.0, 1 - (moment - stamp).days / 365) if stamp else 0.0
        shared = [name for _, name in sorted(entry["shared"], reverse=True)]
        return {"id": owner.split(":", 1)[1], "score": round(entry["score"] * (1 + RECENCY_BONUS * recency), 3), "title": title, "type": kind_label, "date": str(when or "")[:10],
                "shared": list(dict.fromkeys(shared)), "path": entry["best"][1], **extra}

    story_ranked = sorted(((owner, entry) for owner, entry in scores.items() if owner.startswith("item:")), key=lambda pair: -pair[1]["score"])
    for owner, entry in story_ranked:
        summary = graph.published[owner.split(":", 1)[1]]
        kind = "articles" if summary.get("type") == "article" else "posts"
        if kind in kinds:
            built = finish(kind, owner, entry, summary.get("title") or owner, summary.get("type"), summary.get("publishedAt"), {})
            built["command"] = f"papyrus stories link-story --story {lineage} --to {built['id']}"
            result["candidates"][kind].append(built)
    if "references" in kinds:
        ranked = sorted(((owner, entry) for owner, entry in scores.items() if owner.startswith("reference:")), key=lambda pair: -pair[1]["score"])
        pool = ranked[:max(limit * 6, 30)]
        found = graph.accepted_references([str(entry["subjectId"]) for _, entry in pool])
        for owner, entry in pool:
            row = found.get(str(entry["subjectId"]))
            if row is None:
                continue
            host = _host(row.get("sourceUri"))
            built = finish("references", owner, entry, row.get("title") or owner, host or "reference", row.get("sourcePublishedAt") or row.get("createdAt"), {"host": host})
            built["command"] = f"papyrus stories link-story --story {lineage} --reference {built['id']}"
            result["candidates"]["references"].append(built)
    for kind in kinds:
        ordered = sorted(result["candidates"][kind], key=lambda item: -item["score"])
        result["candidates"][kind] = [item for item in ordered if item["score"] >= min_score][:limit]
    result["requests"] = _requests(client) - before
    return result


def _host(uri: Any) -> str:
    from urllib.parse import urlparse

    return (urlparse(str(uri or "")).hostname or "").removeprefix("www.")
