"""Find accepted concepts for free text, ordered by meaning (docs/knowledge-base.md, "Searching concepts"). Read only.

The order is semantic relevance and nothing else: a typed exact (then prefix) name or alias comes first, labelled ``name match``; then the concepts whose
``concept_card`` / ``ontology_concept_profile`` vector is nearest the embedded query, labelled ``meaning``. How many stories or References carry a concept is
shown for information and never ranks anything. Only accepted concepts count (rejected, suggested, generated and bookkeeping kinds are dropped).

The query is embedded once and the index is asked for concept vectors only. Likely duplicates (the same normalized name, or concept cards closer than
``LIKELY_COSINE`` / ``POSSIBLE_COSINE``) are flagged, and an empty or stale concept index is reported with the command that rebuilds it.
"""

from __future__ import annotations

import math
import re
from typing import Any

from papyrus_knowledge_query.concept_kinds import is_concept

from .concept_tags import concept_page_keys, has_public_page
from .link_suggestions import Graph, _lineage, _requests
from .reference_suggestions import CONCEPT_VECTOR_KINDS, S3_VECTORS_MAX_TOP_K
from .section_concepts import concept_label, current_concept_nodes, name_part

LIKELY_COSINE = 0.90      # concept cards at least this alike: "likely duplicate"
POSSIBLE_COSINE = 0.60    # at least this alike AND a shared word of 4+ letters in the names: "possible duplicate" (a suggestion; real pairs such as the two "contextual integrity" cards are only 0.66 alike)
DUPLICATE_COSINE = POSSIBLE_COSINE
CARD_PREFIX = "concept_card-"
REINDEX_COMMAND = ("AWS_PROFILE=<profile> PYTHONPATH=src python -m papyrus_newsroom knowledge-vector-index --action sync"
                   "   # writes a concept_card vector for every accepted concept (concept cards are on by default)")


def default_provider() -> Any | None:
    """The site's vector index (``PAPYRUS_S3_VECTOR_INDEX_ARN`` or ``amplify_outputs.json``), or None when none is configured."""
    import os

    from papyrus_knowledge_query.services import S3VectorsProvider
    from papyrus_knowledge_query.vector_index import _vector_index_from_outputs

    arn = os.environ.get("PAPYRUS_S3_VECTOR_INDEX_ARN") or _vector_index_from_outputs()
    return S3VectorsProvider(vector_index_arn=arn, region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")) if arn else None


EMBEDDING_KEY_HELP = ("Search by meaning needs an embedding key: OPENAI_API_KEY must be set in this shell and valid. The signed-in editor lane has no embedding key "
                      "(unlike `papyrus references search`, which embeds on the server through the searchReferences query); a server-side lane for concept search "
                      "(a query field next to searchReferences) is a follow-up. Name matches below still work.")


def embedding_failure(error: Exception) -> str:
    text = str(error)
    if "401" in text or "OPENAI_API_KEY" in text or "Unauthorized" in text:
        return EMBEDDING_KEY_HELP + f" ({text})"
    return f"Search by meaning failed: {text}"


def normalized(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def name_words(text: Any) -> frozenset[str]:
    return frozenset(word for word in re.split(r"[^a-z0-9]+", str(text or "").lower()) if word)


def same_name(left: Any, right: Any) -> bool:
    """Equal once case, spaces and punctuation are ignored, or the same set of words in any order."""
    return normalized(left) == normalized(right) or (bool(name_words(left)) and name_words(left) == name_words(right))


def accepted_concepts(catalogue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [node for node in catalogue if node.get("status") == "accepted" and is_concept(node.get("nodeKind"), node.get("nodeKey"))]


def _names(node: dict[str, Any]) -> list[str]:
    return [value for value in {node.get("displayName"), name_part(str(node.get("nodeKey") or "")), *(node.get("aliases") or [])} if value]


def name_matches(nodes: list[dict[str, Any]], query: str) -> list[tuple[str, dict[str, Any]]]:
    """``(how, node)`` for each concept whose name or alias equals (``exact``) or starts with (``prefix``) the typed text; exact first, then alphabetical."""
    typed = normalized(re.sub(r"^#+", "", query))
    if not typed:
        return []
    found: list[tuple[int, str, str, dict[str, Any]]] = []
    for node in nodes:
        forms = [normalized(name) for name in _names(node)]
        if typed in forms:
            found.append((0, concept_label(node).lower(), "exact", node))
        elif any(form.startswith(typed) for form in forms):
            found.append((1, concept_label(node).lower(), "prefix", node))
    return [(how, node) for _, _, how, node in sorted(found, key=lambda entry: entry[:2])]


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


def _similarity(match: dict[str, Any]) -> float | None:
    if match.get("similarity") is not None:
        return float(match["similarity"])
    return 1.0 - float(match["distance"]) if match.get("distance") is not None else None


def index_health(provider: Any, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """How many accepted concepts have a concept_card vector at all (a batched existence check; no embedding is computed)."""
    checker = getattr(provider, "existing_keys", None)
    total = len(nodes)
    if checker is None:
        return {"acceptedConcepts": total, "withVector": None, "status": "unknown"}
    keys = [f"{CARD_PREFIX}{_lineage(node)}" for node in nodes]
    present = set(checker(keys))
    with_vector = sum(1 for key in keys if key in present)
    if total and with_vector == 0:
        status = "empty"
    elif with_vector < total:
        status = "stale"   # any accepted concept without a card cannot be found by meaning, so even one is said aloud
    else:
        status = "ok"
    absent = [concept_label(node) for node, key in zip(nodes, keys) if key not in present]
    result = {"acceptedConcepts": total, "withVector": with_vector, "missing": total - with_vector, "missingExamples": absent[:5], "status": status}
    if status != "ok":
        word = "has no concept vectors at all" if status == "empty" else f"is missing a concept vector for {total - with_vector} of {total} accepted concepts (for example {', '.join(absent[:5])})"
        result["message"] = f"The concept index {word}, so search by meaning is {'unavailable' if status == 'empty' else 'incomplete'}; name matches still work. Rebuild it with: {REINDEX_COMMAND}"
    return result


def _flag_duplicates(entries: list[dict[str, Any]], nodes_all: list[dict[str, Any]], provider: Any, nodes: dict[str, dict[str, Any]]) -> None:
    """Three tiers on each result: ``same name`` (any accepted concept with an equal name), ``likely duplicate`` (concept cards at least ``LIKELY_COSINE`` alike) and
    ``possible duplicate`` (at least ``POSSIBLE_COSINE`` alike and a shared word of 4+ letters in the names: a suggestion for a person to check)."""
    for entry in entries:
        node = nodes[entry["lineageId"]]
        entry["duplicates"] = [{"nodeKey": other.get("nodeKey"), "name": concept_label(other), "why": "same name"}
                               for other in nodes_all if _lineage(other) != entry["lineageId"] and same_name(node.get("displayName"), other.get("displayName"))]
    getter = getattr(provider, "get_vector", None)
    if getter is None:
        return
    vectors = {entry["lineageId"]: getter(f"{CARD_PREFIX}{entry['lineageId']}") for entry in entries}
    for index, entry in enumerate(entries):
        for other in entries[index + 1:]:
            left, right = vectors.get(entry["lineageId"]), vectors.get(other["lineageId"])
            if not left or not right:
                continue
            score = cosine(left, right)
            shared = {word for word in name_words(entry["name"]) & name_words(other["name"]) if len(word) >= 4}
            if score >= LIKELY_COSINE:
                why = f"likely duplicate: concept cards {score:.2f} alike"
            elif score >= POSSIBLE_COSINE and shared:
                why = f"possible duplicate (a suggestion): concept cards {score:.2f} alike and both say {', '.join(sorted(shared))}"
            else:
                continue
            for mine, theirs in ((entry, other), (other, entry)):
                if not any(item["nodeKey"] == theirs["nodeKey"] for item in mine["duplicates"]):
                    mine["duplicates"].append({"nodeKey": theirs["nodeKey"], "name": theirs["name"], "why": why})


def search_concepts(client: Any, provider: Any | None, query: str | None, *, limit: int = 10, list_all: bool = False) -> dict[str, Any]:
    """Accepted concepts for free text (``query``) or, with ``list_all``, every accepted concept alphabetically. ``provider`` embeds and queries the vector index
    (``embed_text``, ``query_by_vector``, optional ``get_vector`` and ``existing_keys``); with none, only names are matched and the result says so."""
    before = _requests(client)
    nodes = accepted_concepts(current_concept_nodes(client))
    by_lineage = {_lineage(node): node for node in nodes}
    result: dict[str, Any] = {"query": query, "mode": "list" if list_all else "search", "acceptedConcepts": len(nodes), "results": [], "duplicateCosine": {"likely": LIKELY_COSINE, "possible": POSSIBLE_COSINE}}
    pages = concept_page_keys(client)
    if list_all:
        picked = [{"lineageId": _lineage(node), "reason": "listed", "similarity": None} for node in sorted(nodes, key=lambda node: concept_label(node).lower())]
    else:
        if not query or not query.strip():
            raise ValueError("Give the text to search for, or --list.")
        picked = [{"lineageId": _lineage(node), "reason": f"name match ({how})", "similarity": None} for how, node in name_matches(nodes, query)]
        seen = {entry["lineageId"] for entry in picked}
        if provider is None:
            result["indexNote"] = "No vector index is configured (PAPYRUS_S3_VECTOR_INDEX_ARN or amplify_outputs.json), so only names were matched."
        else:
            result["health"] = index_health(provider, nodes)
            matches: list[dict[str, Any]] = []
            try:
                vector = provider.embed_text(query)
                matches = provider.query_by_vector(vector, S3_VECTORS_MAX_TOP_K, {"vectorKind": {"$in": list(CONCEPT_VECTOR_KINDS)}})
            except Exception as error:   # the key or the network; the name matches are still good
                result["indexNote"] = embedding_failure(error)
                result["embeddingKeyProblem"] = result["indexNote"].startswith(EMBEDDING_KEY_HELP[:30])
            best: dict[str, float] = {}
            for match in matches:
                metadata = match.get("metadata") or {}
                lineage = str(metadata.get("conceptLineageId") or metadata.get("lineageId") or "")
                score = _similarity(match)
                if lineage in by_lineage and score is not None and score > best.get(lineage, -1.0):
                    best[lineage] = score
            for entry in picked:
                entry["similarity"] = best.get(entry["lineageId"])
            for lineage, score in sorted(best.items(), key=lambda pair: -pair[1]):
                if lineage not in seen:
                    picked.append({"lineageId": lineage, "reason": "meaning", "similarity": score})
            if not best and "indexNote" not in result:
                result["indexNote"] = "The index returned no accepted concept vectors for this search."
        picked = picked[:limit]
    entries = []
    for rank, entry in enumerate(picked, 1):
        node = by_lineage[entry["lineageId"]]
        entries.append({"rank": rank, "name": concept_label(node), "nodeKey": node.get("nodeKey"), "lineageId": entry["lineageId"], "reason": entry["reason"],
                        "similarity": None if entry["similarity"] is None else round(entry["similarity"], 4), "publicPage": has_public_page(node, pages)})
    if entries and not list_all:
        graph = Graph(client)
        graph.load_concepts([entry["lineageId"] for entry in entries])   # two batched reads for the informational counts
        for entry in entries:
            entry["stories"], entry["references"] = graph.document_frequency(entry["lineageId"])
    _flag_duplicates(entries, nodes, None if list_all else provider, by_lineage)
    result["results"] = entries
    result["requests"] = _requests(client) - before
    return result
