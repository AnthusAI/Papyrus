"""Suggested links from a Reference to related References and to concepts, found by vector search.

See docs/idea-context-packs.md section 3.2. The Reference's own ``reference_summary`` vector is read back from the index
(``GetVectors`` with ``returnData``), so no embedding is computed. That vector is the query for ``QueryVectors`` with metadata
filters. How many neighbours to keep is decided by the largest drop between consecutive similarities (the knee) unless a
caller supplies a calibrated cut. Every kept neighbour is written as a ``suggested`` row; a person's earlier decision is never
overwritten and a rejected neighbour is never offered again.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from papyrus_knowledge_query.vector_index import reference_summary_vector_key

from .reference_links import RELATED_TO, link_concept, link_references
from .story_reporting import current_reference

SUGGESTION_ACTOR = "auto:vector"
SUGGESTION_CLASSIFIER_ID = "vector:text-embedding-3-small"
S3_VECTORS_MAX_TOP_K = 100
REFERENCE_SUMMARY_VECTOR_KIND = "reference_summary"
CONCEPT_VECTOR_KINDS = ("concept_card", "ontology_concept_profile")
EXCLUDED_RELATION_STATES = ("current", "rejected")

CutFunction = Callable[[list[float]], int]


class VectorProvider(Protocol):
    def get_vector(self, key: str) -> list[float] | None: ...

    def query_by_vector(self, vector: list[float], top_k: int, metadata_filter: dict[str, Any] | None) -> list[dict[str, Any]]: ...


def knee_cut_count(similarities: list[float]) -> int:
    """How many of the descending ``similarities`` to keep: everything before the largest drop between consecutive
    scores among the first half. A single score, or none, has no drop and is kept whole."""
    if len(similarities) < 2:
        return len(similarities)
    gap_count = max(1, len(similarities) // 2)
    gaps = [similarities[index] - similarities[index + 1] for index in range(gap_count)]
    return gaps.index(max(gaps)) + 1


def _similarity(match: dict[str, Any]) -> float | None:
    if match.get("similarity") is not None:
        return float(match["similarity"])
    if match.get("distance") is not None:
        return 1.0 - float(match["distance"])
    return None


def _already_decided_or_linked(client, lineage_id: str) -> set[str]:
    other_ends: set[str] = set()
    for state in EXCLUDED_RELATION_STATES:
        key = f"reference#{lineage_id}#{state}"
        for row in client.list_by_index("semanticRelationsBySubjectState", key):
            other_ends.add(str(row.get("objectLineageId")))
        for row in client.list_by_index("semanticRelationsByObjectState", key):
            other_ends.add(str(row.get("subjectLineageId")))
    return other_ends


def _best_by_lineage(matches: list[dict[str, Any]], lineage_of: Callable[[dict[str, Any]], str | None], excluded: set[str]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for match in matches:
        similarity = _similarity(match)
        lineage = lineage_of(match.get("metadata") or {})
        if similarity is None or not lineage or lineage in excluded:
            continue
        if lineage not in best or similarity > best[lineage]["similarity"]:
            best[lineage] = {"lineageId": lineage, "similarity": similarity, "metadata": match.get("metadata") or {}}
    return sorted(best.values(), key=lambda candidate: candidate["similarity"], reverse=True)


def _reference_lineage(metadata: dict[str, Any]) -> str | None:
    return metadata.get("referenceLineageId") or metadata.get("lineageId")


def _concept_lineage(metadata: dict[str, Any]) -> str | None:
    return metadata.get("conceptLineageId") or metadata.get("lineageId")


def _concept_node(client, lineage_id: str) -> dict[str, Any]:
    row = client.get_record("SemanticNode", lineage_id)
    if row is not None:
        return {"id": row["id"], "lineageId": row.get("lineageId") or lineage_id, "versionNumber": row.get("versionNumber")}
    return {"id": lineage_id, "lineageId": lineage_id, "versionNumber": None}


def _kept(candidate: dict[str, Any], outcome: str, calibration: Any | None, kind: str) -> dict[str, Any]:
    entry = {"lineageId": candidate["lineageId"], "similarity": candidate["similarity"], "outcome": outcome}
    mark = getattr(calibration, "label_candidate", None)
    label = (mark(kind, candidate) if mark else calibration.label(kind, candidate["similarity"])) if calibration is not None else None
    if label is not None:
        entry["label"] = label
    return entry


def suggest_for(
    client,
    vector_provider: VectorProvider,
    reference_id: str,
    *,
    corpus_id: str | None = None,
    cut: CutFunction | None = None,
    calibration: Any | None = None,
    dry_run: bool = False,
    actor: str = SUGGESTION_ACTOR,
    now: str | None = None,
) -> dict[str, Any]:
    """Suggests related References and concepts for one Reference, given by record id or lineage id.

    ``vector_provider`` reads the Reference's stored summary vector and queries by vector; no embedding call is made.
    ``cut`` takes the descending similarities and returns how many to keep; it defaults to the learned cut of ``calibration``
    (a ``suggestion_calibration.SuggestionCalibration``) for a kind that has one, else the knee. With a cut, each kept neighbour
    also carries a ``label`` of ``likely`` or ``possible``; without one it carries none. With ``dry_run``
    nothing is written. Returns ``{"referenceId", "lineageId", "dryRun", "skipped", "references", "concepts"}``, where each
    kept neighbour is ``{"lineageId", "similarity", "outcome"}`` and ``outcome`` is ``created``, ``updated``, ``kept`` (a
    person's decision stands) or ``would_write`` for a dry run."""
    reference = current_reference(client, reference_id)
    if reference is None:
        raise ValueError(f"Reference not found: {reference_id}")
    lineage_id = reference.get("lineageId") or reference_id
    result: dict[str, Any] = {"referenceId": reference["id"], "lineageId": lineage_id, "dryRun": dry_run, "skipped": None, "references": [], "concepts": []}
    if calibration is not None:
        result["calibration"] = calibration.record()
    query_vector = vector_provider.get_vector(reference_summary_vector_key(lineage_id))
    if not query_vector:
        result["skipped"] = "no reference_summary vector is indexed for this Reference"
        return result
    excluded = _already_decided_or_linked(client, lineage_id) | {lineage_id}
    corpus = corpus_id or reference.get("corpusId")

    reference_clauses: list[dict[str, Any]] = [
        {"vectorKind": {"$eq": REFERENCE_SUMMARY_VECTOR_KIND}},
        {"curationStatus": {"$eq": "accepted"}},
    ]
    if corpus:
        reference_clauses.append({"corpusId": {"$eq": corpus}})
    reference_matches = vector_provider.query_by_vector(query_vector, S3_VECTORS_MAX_TOP_K, {"$and": reference_clauses})
    related = _best_by_lineage(reference_matches, _reference_lineage, excluded)
    choose_count = cut or (calibration.cut("reference", knee_cut_count) if calibration is not None else None) or knee_cut_count
    for candidate in related[: choose_count([c["similarity"] for c in related])]:
        outcome = "would_write"
        if not dry_run:
            outcome = link_references(
                client, reference["id"], candidate["lineageId"], RELATED_TO, "suggested", actor=actor,
                score=candidate["similarity"], classifier_id=SUGGESTION_CLASSIFIER_ID, now=now,
            )["outcome"]
        result["references"].append(_kept(candidate, outcome, calibration, "reference"))

    concept_matches = vector_provider.query_by_vector(query_vector, S3_VECTORS_MAX_TOP_K, {"vectorKind": {"$in": list(CONCEPT_VECTOR_KINDS)}})
    concepts = _best_by_lineage(concept_matches, _concept_lineage, excluded)
    choose_count = cut or (calibration.cut("concept", knee_cut_count) if calibration is not None else None) or knee_cut_count
    for candidate in concepts[: choose_count([c["similarity"] for c in concepts])]:
        outcome = "would_write"
        if not dry_run:
            outcome = link_concept(
                client, reference["id"], _concept_node(client, candidate["lineageId"]), "suggested", actor=actor,
                score=candidate["similarity"], classifier_id=SUGGESTION_CLASSIFIER_ID, now=now,
            )["outcome"]
        result["concepts"].append(_kept(candidate, outcome, calibration, "concept"))
    return result
