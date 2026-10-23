"""The seam for human review of a synthesis run.

Today a run only records that review is pending. When the review-request system lands, ``request_human_review`` is the one place
that raises ONE soft review per run ("N new story ideas to review", 7-day deadline); the feedback it collects comes back into the
next run through ``--feedback`` (``load_feedback``), which synthesis shows the model and also treats as a reason not to
re-propose an idea a reviewer declined.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("papyrus.ideas")
VERDICTS = ("accept", "decline", "revise")
DEADLINE_DAYS = 7


def request_human_review(run: dict[str, Any], ideas: list[dict[str, Any]]) -> dict[str, Any]:
    """Records that a review is pending for this run's ideas. It raises nothing yet; it returns what it recorded."""
    review = {
        "status": "pending",
        "requested": False,
        "ideas": len(ideas),
        "ideaIds": [idea["ideaId"] for idea in ideas],
        "deadlineDays": DEADLINE_DAYS,
        "note": "No review system is wired in; read the ideas from this run's output.",
    }
    log.info("review pending: %d new story ideas from run %s", len(ideas), run.get("runId"))
    run["review"] = review
    return review


def load_feedback(path: str | None) -> list[dict[str, Any]]:
    """Reviewer feedback on earlier ideas: a JSON list of ``{"title", "verdict": accept|decline|revise, "note"}``."""
    if not path:
        return []
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    entries = data.get("feedback") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ValueError("--feedback must be a JSON list of {title, verdict, note} entries.")
    cleaned = []
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("title") or "").strip() or entry.get("verdict") not in VERDICTS:
            raise ValueError(f"Each feedback entry needs a title and a verdict of {', '.join(VERDICTS)}: {entry!r}")
        cleaned.append({"title": str(entry["title"]).strip(), "verdict": entry["verdict"], "note": str(entry.get("note") or "").strip()})
    return cleaned
