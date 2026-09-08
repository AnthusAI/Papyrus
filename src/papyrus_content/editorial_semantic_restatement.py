from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .editorial_diagnosis_schema import stable_finding_id, stable_repetition_group_id
from .editorial_embedders import SentenceEmbedder, resolve_local_embedder
from .editorial_style import SimilarityThresholds
from .editorial_text import is_rhetorical_refrain, sentence_spans

_CONCEPT_RESTAEMENT_KIND = "concept_restatement"


@dataclass(frozen=True)
class SemanticRestatementResult:
    similarity: dict[str, Any] | None
    groups: list[dict[str, Any]]


def analyze_semantic_restatement(
    draft_text: str,
    *,
    thresholds: SimilarityThresholds,
    redundancy_groups: list[dict[str, Any]],
    embedder: SentenceEmbedder | None = None,
) -> SemanticRestatementResult:
    if thresholds.embedder == "off":
        return SemanticRestatementResult(similarity=None, groups=[])

    resolved = embedder if embedder is not None else resolve_local_embedder()
    if resolved is None:
        return SemanticRestatementResult(similarity=None, groups=[])

    spans = sentence_spans(draft_text)
    if len(spans) < thresholds.restatement_min_sentences:
        return SemanticRestatementResult(similarity=None, groups=[])

    sentences = tuple(sentence for sentence, _, _ in spans)
    vectors = resolved.embed(sentences)
    if len(vectors) != len(sentences):
        raise ValueError("Embedder returned a different number of vectors than sentences.")

    clusters = _cluster_sentences(vectors, cosine_threshold=thresholds.cosine_threshold)
    redundancy_spans = _redundancy_member_spans(redundancy_groups)
    groups: list[dict[str, Any]] = []
    seen_group_ids: set[str] = set()

    for cluster_indices in clusters:
        if len(cluster_indices) < thresholds.restatement_min_sentences:
            continue
        members = []
        for index in cluster_indices:
            sentence, start, end = spans[index]
            members.append(
                {
                    "id": stable_finding_id(_CONCEPT_RESTAEMENT_KIND, draft_text, start, end),
                    "kind": _CONCEPT_RESTAEMENT_KIND,
                    "excerpt": sentence,
                    "span": {"start": start, "end": end},
                    "rationale": "Sentence restates the same claim as other clustered passages.",
                }
            )
        if is_rhetorical_refrain(members):
            continue
        if _cluster_fully_explained_by_redundancy(members, redundancy_spans):
            continue
        group_id = stable_repetition_group_id(
            _CONCEPT_RESTAEMENT_KIND,
            [member["id"] for member in members],
        )
        if group_id in seen_group_ids:
            continue
        seen_group_ids.add(group_id)
        groups.append(
            {
                "id": group_id,
                "kind": _CONCEPT_RESTAEMENT_KIND,
                "members": members,
                "rationale": (
                    f"{len(members)} sentences cluster as near-paraphrases "
                    f"(cosine >= {thresholds.cosine_threshold:g})."
                ),
            }
        )

    similarity = {
        "sentenceCount": len(spans),
        "clusterCount": len(clusters),
        "embedder": resolved.embedder_id,
    }
    return SemanticRestatementResult(similarity=similarity, groups=groups)


def _cluster_sentences(vectors: list[list[float]], *, cosine_threshold: float) -> list[list[int]]:
    clusters: list[list[int]] = []
    centroids: list[list[float]] = []

    for index, vector in enumerate(vectors):
        assigned = False
        for cluster_index, centroid in enumerate(centroids):
            if _cosine_similarity(vector, centroid) >= cosine_threshold:
                clusters[cluster_index].append(index)
                centroids[cluster_index] = _mean_vector([vectors[i] for i in clusters[cluster_index]])
                assigned = True
                break
        if not assigned:
            clusters.append([index])
            centroids.append(list(vector))

    return clusters


def _mean_vector(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    size = len(vectors[0])
    totals = [0.0] * size
    for vector in vectors:
        for index, value in enumerate(vector):
            totals[index] += value
    count = float(len(vectors))
    return [value / count for value in totals]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _redundancy_member_spans(redundancy_groups: list[dict[str, Any]]) -> set[tuple[int, int]]:
    spans: set[tuple[int, int]] = set()
    for group in redundancy_groups:
        if group.get("kind") != "redundancy":
            continue
        for member in group.get("members", []):
            span = member.get("span")
            if not isinstance(span, dict):
                continue
            start = span.get("start")
            end = span.get("end")
            if isinstance(start, int) and isinstance(end, int):
                spans.add((start, end))
    return spans


def _cluster_fully_explained_by_redundancy(
    members: list[dict[str, Any]],
    redundancy_spans: set[tuple[int, int]],
) -> bool:
    if not redundancy_spans:
        return False
    for member in members:
        span = member.get("span")
        if not isinstance(span, dict):
            return False
        start = span.get("start")
        end = span.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            return False
        if (start, end) not in redundancy_spans:
            return False
    return True
