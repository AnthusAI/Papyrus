"""The site's own duplicate cut for ideas, learned from what its editors did with earlier ideas (docs/idea-context-packs.md sections 5.2 and 8).

An idea an editor spiked as a duplicate is a positive label; an idea an editor moved forward is a negative one (an idea spiked for another reason
says nothing about duplication and is left out). Each decided idea is scored with the same scorer the dedupe uses, against the stories and the
other ideas that existed before it, and its best match is its similarity. The cut ``t`` is the smallest similarity at which the Wilson 95% lower
bound (``auto_accept.learn_threshold``, shared, not copied) of the duplicate share among decided ideas scored at or above ``t`` reaches the site's
target precision. With too few decisions there is no learned cut: the fixed fallback of 0.5 applies and the run record says
"no learned cut: too few decisions". The scorer is a seam (``dedupe.ScorerFactory``): a vector score can replace the word score later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..auto_accept import DEFAULT_PRECISION, learn_threshold
from ..story_from_reference import _current_versions
from . import dedupe
from .context import STORY_TYPES
from .items import generated_of
from .labels import decided_ideas

DUPLICATE_REASON_CODE = "duplicate"
NO_LEARNED_CUT_REASON = "no learned cut: too few decisions"
DUPLICATE_WORDING = re.compile(r"\bduplicat", re.IGNORECASE)


@dataclass(frozen=True)
class DuplicateCut:
    """The threshold a run applies. ``learned`` is False while the fallback applies, with ``reason`` saying why."""

    threshold: float
    learned: bool
    decisions: int
    evidence: Mapping[str, Any] = field(default_factory=dict)
    reason: str | None = None

    def record(self) -> dict[str, Any]:
        return {"threshold": self.threshold, "learned": self.learned, "decisions": self.decisions, "reason": self.reason, **self.evidence}


def names_duplication(generated: Mapping[str, Any], reason: str) -> bool:
    """Whether the editor's decision names duplication: the reason code ``duplicate`` on ``generated.decision``, or duplication in a note or in the stage-move reason."""
    recorded = generated.get("decision") if isinstance(generated.get("decision"), dict) else {}
    return (recorded.get("reasonCode") == DUPLICATE_REASON_CODE
            or bool(DUPLICATE_WORDING.search(str(recorded.get("note") or "")))
            or bool(DUPLICATE_WORDING.search(reason or "")))


def _created(item: Mapping[str, Any]) -> str:
    return str(item.get("publishedAt") or item.get("versionCreatedAt") or item.get("createdAt") or "")


def _text(item: Mapping[str, Any]) -> str:
    return dedupe.idea_text(str(item.get("title") or ""), str(item.get("deck") or ""))


def scored_decisions(client: Any, scorer_factory: dedupe.ScorerFactory = dedupe.WordScorer) -> list[tuple[float, bool]]:
    """``(similarity, was_duplicate)`` for every decided idea that has something earlier to resemble."""
    items = [item for item in _current_versions(client.list_records("Item")) if item.get("type") in STORY_TYPES and str(item.get("title") or "").strip()]
    decided = [(item, generated, decision) for item, generated, decision in decided_ideas(client)]
    if not decided:
        return []
    score = scorer_factory([_text(item) for item in items])
    votes: list[tuple[float, bool]] = []
    for idea, generated, decision in decided:
        duplicate = decision["label"] == "exclude" and names_duplication(generated, decision["reason"])
        if decision["label"] == "exclude" and not duplicate:
            continue
        idea_created = str(idea.get("versionCreatedAt") or idea.get("createdAt") or "")
        earlier = [other for other in items if other["id"] != idea["id"] and (other.get("lineageId") or other["id"]) != (idea.get("lineageId") or idea["id"])
                   and not (idea_created and _created(other) and _created(other) > idea_created)]
        if not earlier:
            continue
        votes.append((max(score(_text(idea), _text(other)) for other in earlier), duplicate))
    return votes


def learn_duplicate_cut(votes: Sequence[tuple[float, bool]], precision: float = DEFAULT_PRECISION) -> DuplicateCut:
    learned = learn_threshold(votes, precision)
    if learned["threshold"] is None:
        evidence = {} if learned.get("bestLowerBound") is None else {"bestLowerBound": learned["bestLowerBound"]}
        return DuplicateCut(dedupe.FALLBACK_THRESHOLD, False, len(votes), {"precision": precision, "fallback": dedupe.FALLBACK_THRESHOLD, **evidence}, NO_LEARNED_CUT_REASON)
    return DuplicateCut(float(learned["threshold"]), True, len(votes),
                        {"precision": precision, "duplicates": learned["accepted"], "above": learned["votes"], "rate": learned["rate"], "lowerBound": learned["lowerBound"]})


def resolve_threshold(client: Any, threshold: float | None, precision: float = DEFAULT_PRECISION,
                      scorer_factory: dedupe.ScorerFactory = dedupe.WordScorer) -> DuplicateCut:
    """The operator's ``--dedupe-threshold`` when one is given, otherwise the cut learned from this site's decisions."""
    if threshold is not None:
        return DuplicateCut(threshold, False, 0, {}, "set by the operator")
    if client is None:
        return DuplicateCut(dedupe.FALLBACK_THRESHOLD, False, 0, {"fallback": dedupe.FALLBACK_THRESHOLD}, NO_LEARNED_CUT_REASON)
    return learn_duplicate_cut(scored_decisions(client, scorer_factory), precision)
