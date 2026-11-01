"""Where suggested links are cut and how they are marked, learned from the decisions people made on earlier suggestions.

See docs/idea-context-packs.md section 3.3. Per site, over suggestions a person decided (a ``SemanticRelation`` row whose
``metadata.provenance`` is ``suggested`` and whose ``metadata.decision`` is ``accepted`` or ``rejected``), the cut ``t`` is the smallest
similarity at which the Wilson 95% lower bound of the accept share among decided suggestions scored at or above ``t`` reaches the
target precision. The statistic is ``auto_accept.learn_threshold``, shared, not copied. References and concepts get separate cuts.
Suggestions at or above ``t`` are marked ``likely``, those below ``possible``. With too few decisions there is no cut, nothing is
marked, and the reason is recorded ("no cut: too few decisions").

All suggestion rows share the ``reference-links`` newsroom feed partition, so the decided ones are found with one paginated read of
``semanticRelationsByNewsroomFeedAndCreatedAt``; no per-Reference state keys are needed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .auto_accept import DEFAULT_PRECISION, learn_threshold
from .reference_links import REFERENCE_LINK_FEED_KEY

REFERENCE_KIND = "reference"
CONCEPT_KIND = "concept"
LIKELY = "likely"
POSSIBLE = "possible"
NO_CUT_REASON = "no cut: too few decisions"
FEED_INDEX = "semanticRelationsByNewsroomFeedAndCreatedAt"
OBJECT_KIND_TO_CUT_KIND = {"reference": REFERENCE_KIND, "semanticNode": CONCEPT_KIND}


@dataclass(frozen=True)
class KindCalibration:
    """The cut for one kind of suggestion: ``threshold`` is None when no cut exists, with ``reason`` saying why."""
    threshold: float | None
    decisions: int
    evidence: Mapping[str, Any] = field(default_factory=dict)
    reason: str | None = None

    def record(self) -> dict[str, Any]:
        return {"threshold": self.threshold, "decisions": self.decisions, "reason": self.reason, **self.evidence}


@dataclass(frozen=True)
class SuggestionCalibration:
    reference: KindCalibration
    concept: KindCalibration
    precision: float = DEFAULT_PRECISION

    def for_kind(self, kind: str) -> KindCalibration:
        return self.reference if kind == REFERENCE_KIND else self.concept

    def label(self, kind: str, similarity: float) -> str | None:
        """``likely`` at or above the cut, ``possible`` below it, None when the kind has no cut."""
        threshold = self.for_kind(kind).threshold
        if threshold is None:
            return None
        return LIKELY if similarity >= threshold else POSSIBLE

    def cut(self, kind: str, knee: Callable[[list[float]], int]) -> Callable[[list[float]], int] | None:
        """A cut function for ``suggest_for``: keeps every neighbour at or above the learned cut and at least as many as the knee
        keeps, so ``possible`` neighbours are still offered. None when the kind has no cut (the knee applies)."""
        threshold = self.for_kind(kind).threshold
        if threshold is None:
            return None
        def choose(similarities: list[float]) -> int:
            return max(sum(1 for value in similarities if value >= threshold), knee(similarities))
        return choose

    def record(self) -> dict[str, Any]:
        return {"precision": self.precision, REFERENCE_KIND: self.reference.record(), CONCEPT_KIND: self.concept.record()}


def _metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata")
    if isinstance(raw, str):
        return json.loads(raw or "{}")
    return dict(raw or {})


def decided_suggestions(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[tuple[float, bool]]]:
    """``{kind: [(similarity, accepted)]}`` over the suggestions a person decided; rows decided by automation or without a score are skipped."""
    from .monitoring_router import human_actor
    decided: dict[str, list[tuple[float, bool]]] = {REFERENCE_KIND: [], CONCEPT_KIND: []}
    for row in rows:
        metadata = _metadata(row)
        kind = OBJECT_KIND_TO_CUT_KIND.get(str(row.get("objectKind")))
        if (kind is None or metadata.get("provenance") != "suggested" or row.get("score") is None
                or metadata.get("decision") not in ("accepted", "rejected") or not human_actor(str(metadata.get("decidedBy") or ""))):
            continue
        decided[kind].append((float(row["score"]), metadata["decision"] == "accepted"))
    return decided


def calibrate_kind(decisions: Sequence[tuple[float, bool]], precision: float) -> KindCalibration:
    learned = learn_threshold(decisions, precision)
    if learned["threshold"] is None:
        evidence = {} if learned.get("bestLowerBound") is None else {"bestLowerBound": learned["bestLowerBound"]}
        return KindCalibration(None, len(decisions), evidence, NO_CUT_REASON)
    return KindCalibration(float(learned["threshold"]), len(decisions),
                           {"accepted": learned["accepted"], "above": learned["votes"], "rate": learned["rate"], "lowerBound": learned["lowerBound"]})


def calibrate(rows: Sequence[Mapping[str, Any]], precision: float = DEFAULT_PRECISION) -> SuggestionCalibration:
    decided = decided_suggestions(rows)
    return SuggestionCalibration(calibrate_kind(decided[REFERENCE_KIND], precision), calibrate_kind(decided[CONCEPT_KIND], precision), precision)


def load_calibration(client: Any, precision: float = DEFAULT_PRECISION) -> SuggestionCalibration:
    """One paginated read of the site's link rows, then the cuts learned from the suggestions people decided."""
    return calibrate(client.list_by_index(FEED_INDEX, REFERENCE_LINK_FEED_KEY), precision)
