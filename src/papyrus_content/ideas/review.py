"""Human review of a synthesis run, through review requests (docs/review-requests.md).

A run that creates ideas raises ONE soft review for the batch ("N new story ideas to review", no deadline), idempotent per run.
The next run reads what editors said (``steering_for``), shows it to the model as reviewer feedback and records that it used it
(``mark_applied``). ``--feedback FILE`` stays as a manual override.

A site that has not deployed the review models cannot take a request. That never fails a run: the ideas are already stored, and the
run records ``review: {status: not_raised, error}``. The review's links name the Proposal ids when ideas are Proposals; ideas kept as
JSON are linked by idea id (the console cannot open those), which is a known limit of the JSON store.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .. import review_requests

log = logging.getLogger("papyrus.ideas")
RAISED_BY = "idea-pipeline"
VERDICTS = ("accept", "decline", "revise")
VERDICT_OF_DECISION = {"approve": "accept", "acknowledge": "accept", "reject": "decline", "feedback": "revise"}


def request_human_review(client: Any, run: dict[str, Any], ideas: list[dict[str, Any]], noun: str = "story idea") -> dict[str, Any]:
    """Raises one soft review for the run's ideas and records the outcome in ``run['review']``. Never raises."""
    if not ideas:
        review = {"status": "none", "requested": False, "ideas": 0, "note": "No ideas were created, so there is nothing to review."}
    elif client is None:
        review = {"status": "pending", "requested": False, "ideas": len(ideas), "note": "No review client was given."}
    else:
        identifiers = [idea.get("proposalId") or idea["ideaId"] for idea in ideas]
        try:
            request = review_requests.raise_batch_review(client, raised_by=RAISED_BY, batch_id=run["runId"], proposal_ids=identifiers, noun=noun)
        except Exception as error:  # noqa: BLE001 - the ideas are stored; a site without review requests must not fail the run
            review = {"status": "not_raised", "requested": False, "ideas": len(ideas), "error": f"{type(error).__name__}: {error}"[:300]}
        else:
            review = {
                "status": "requested", "requested": True, "ideas": len(ideas), "requestId": request["id"], "deadline": request.get("deadline"),
                "linkedAs": "proposal" if all(idea.get("proposalId") for idea in ideas) else "idea",
            }
    review["ideaIds"] = [idea["ideaId"] for idea in ideas]
    log.info("review %s: %d new story ideas from run %s", review["status"], len(ideas), run.get("runId"))
    run["review"] = review
    return review


def feedback_from_steering(notes: list[dict[str, Any]], prior_ideas: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Reviewer feedback entries from steering notes. A batch's note applies to each idea the batch held (``prior_ideas``: batch id to titles)."""
    entries = []
    for note in notes:
        verdict = VERDICT_OF_DECISION.get(note.get("decision") or "", "revise")
        text = " ".join(part for part in (note.get("feedback"), f"Steer: {note['steer']}." if note.get("steer") else None) if part)
        titles = prior_ideas.get(note["subject"].get("id")) or [f"Batch {note['subject'].get('id')}"]
        entries += [{"title": title, "verdict": verdict, "note": text, "requestId": note["requestId"]} for title in titles]
    return entries


def read_steering(client: Any, prior_ideas: dict[str, list[str]]) -> tuple[list[dict[str, Any]], list[str], str | None]:
    """(feedback entries, request ids to mark applied, error). A site without review requests gives no steering and an error note."""
    if client is None:
        return [], [], None
    try:
        notes = review_requests.steering_for(client, raised_by=RAISED_BY)
    except Exception as error:  # noqa: BLE001
        return [], [], f"{type(error).__name__}: {error}"[:300]
    return feedback_from_steering(notes, prior_ideas), [note["requestId"] for note in notes], None


def mark_steering_applied(client: Any, request_ids: list[str], run_id: str) -> list[str]:
    """Records that this run used the steering; returns the ids that could not be marked (never raises)."""
    failed = []
    for request_id in dict.fromkeys(request_ids):
        try:
            review_requests.mark_applied(client, request_id, run_id=run_id, by=RAISED_BY)
        except Exception as error:  # noqa: BLE001
            log.warning("could not mark %s applied: %s", request_id, error)
            failed.append(request_id)
    return failed


def load_feedback(path: str | None) -> list[dict[str, Any]]:
    """Manual reviewer feedback: a JSON list of ``{"title", "verdict": accept|decline|revise, "note"}``. It overrides steering for the same title."""
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


def merge_feedback(steering: list[dict[str, Any]], manual: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Steering first, then the manual file; a manual entry replaces a steering entry with the same title."""
    overridden = {entry["title"].lower() for entry in manual}
    return [entry for entry in steering if entry["title"].lower() not in overridden] + manual
