"""Whether a concept has a public page of its own: the extractor's answer, the editor's decision, and how they combine (PPY-ce6234).

The entity step asks Jev whether a name deserves a wiki page (``entity_extraction.py``). Its answer travels on each proposed entity as
``page_score`` (a probability), ``page_answer`` (yes from 0.5) and ``page_documents`` (how many documents the name is in), and ``publish-run``
keeps it on the concept in one field, ``SemanticNode.pageAnswer``, a JSON object: ``{"score", "answer", "documents", "runId"}``. A later run
updates it; it is the only part of a concept a run writes besides the derived numbers.

An editor's decision is kept apart, in the concept's review marks (``actors.py``: ``pageGivenBy`` or ``pageTakenBy``), so no run can overwrite it.
Who wins: the editor, else the machine's answer, else, for a concept the extractor has not answered for, the page state it already has (a page).
The document count is shown beside the score and never blended into it.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .actors import decode_review

PAGE_FIELD = "pageAnswer"


@dataclass(frozen=True)
class PageAnswer:
    score: float
    answer: bool
    documents: int
    run_id: str | None = None

    def encode(self) -> str:
        return json.dumps({"score": self.score, "answer": self.answer, "documents": self.documents, "runId": self.run_id}, sort_keys=True, separators=(",", ":"))

    def same_as(self, other: "PageAnswer | None") -> bool:
        """The same answer; the run that gave it does not count, so a run that finds nothing new writes nothing."""
        return other is not None and (self.score, self.answer, self.documents) == (other.score, other.answer, other.documents)


def decode_page_answer(raw: Any) -> PageAnswer | None:
    """The answer a stored field holds, or ``None`` when there is none or it is not in the shape."""
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, Mapping):
        return None
    score, answer, documents = raw.get("score"), raw.get("answer"), raw.get("documents")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not isinstance(answer, bool):
        return None
    if isinstance(documents, bool) or not isinstance(documents, int) or documents < 0:
        return None
    run_id = raw.get("runId")
    return PageAnswer(float(score), answer, documents, run_id if isinstance(run_id, str) else None)


def page_override(row: Mapping[str, Any]) -> bool | None:
    """The editor's decision on a concept row: ``True`` (give it a page), ``False`` (take it away) or ``None`` (leave it to the machine). Taking wins."""
    marks = decode_review(row.get("changeReason"))
    if marks.page_taken_by is not None:
        return False
    return True if marks.page_given_by is not None else None


def page_order_key(row: Mapping[str, Any]) -> tuple:
    """Order for listing concepts to review: the highest page score first, then the most documents, then by name. A concept with no answer comes after
    every one that has one (it is not given a score); no threshold applies."""
    answer = decode_page_answer(row.get(PAGE_FIELD))
    name = str(row.get("displayName") or "").casefold()
    if answer is None:
        return (1, 0.0, 0, name, str(row.get("id") or ""))
    return (0, -answer.score, -answer.documents, name, str(row.get("id") or ""))


def page_label(row: Mapping[str, Any]) -> str:
    """``0.83 in 4 documents`` for a listing, plus ``yes``/``no`` for the editor's decision when there is one; ``-`` when the extractor has not answered."""
    answer = decode_page_answer(row.get(PAGE_FIELD))
    shown = "-\t-" if answer is None else f"{answer.score:.2f}\t{answer.documents}"
    override = page_override(row)
    return f"{shown}\t{'' if override is None else ('page: yes' if override else 'page: no')}"
