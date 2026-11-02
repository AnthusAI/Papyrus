"""Human review of a synthesis run, through review requests (docs/review-requests.md).

A run that creates ideas raises ONE soft review for the batch ("N new story ideas to review", no deadline), idempotent per run. Its links are the
ideas filed in that run (Items at the ``idea`` stage), so the console shows ONE card that opens the Idea column of the Stories board. Editors decide the
ideas there: moving one forward accepts it, moving it to spiked with a reason declines it. The next run reads those stage moves as reviewer feedback
(``ItemStore.feedback``) and what editors said on the request itself (``steering_for``), shows it to the model and records that it used the request's
note (``mark_applied``). ``--feedback FILE`` stays as a manual override.

A site that has not deployed the review models cannot take a request. That never fails a run: the ideas are already stored, and the
run records ``review: {status: not_raised, error}``. The review's links name the idea Items; ideas kept only as
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
        from .items import review_order

        ideas = review_order(ideas)   # clean ones first (ideas with no editorial check keep their place)
        identifiers = [idea.get("itemLineageId") or idea["ideaId"] for idea in ideas]
        as_items = all(idea.get("itemLineageId") for idea in ideas)
        try:
            request = review_requests.raise_batch_review(client, raised_by=RAISED_BY, batch_id=run["runId"], idea_ids=identifiers, noun=noun, link_type="story" if as_items else "idea")
        except Exception as error:  # noqa: BLE001 - the ideas are stored; a site without review requests must not fail the run
            review = {"status": "not_raised", "requested": False, "ideas": len(ideas), "error": f"{type(error).__name__}: {error}"[:300]}
        else:
            review = {
                "status": "requested", "requested": True, "ideas": len(ideas), "requestId": request["id"], "deadline": request.get("deadline"),
                "linkedAs": "story" if as_items else "idea",
            }
    review["ideaIds"] = [idea["ideaId"] for idea in ideas]
    log.info("review %s: %d new story ideas from run %s", review["status"], len(ideas), run.get("runId"))
    run["review"] = review
    return review


CURATION_SUBJECT_PREFIX = "ideas-curation:"
SKIPPED_TITLES_SHOWN = 5   # a sentence in a card, not a limit on the work: the card names the first few so an editor knows where to start
SAID_NOTHING_MORE = ("already_rejected", "no_point_offered")   # skipped reasons: a draft was rejected for adding nothing, now or on an earlier run
REJECTED_FOR_ADDING_NOTHING = ("point_check_failed",)   # invalid reasons of the same kind


def settle_curation_flag(client: Any, run: dict[str, Any], site: str) -> dict[str, Any]:
    """The one curation flag of a publication's monitor-story run (docs/idea-context-packs.md, "More than a summary"). Never raises.

    * The run filed ideas: an open flag of this publication is acknowledged (ideas are flowing again).
    * The run filed nothing because a Reference had nothing to add (``nothing_to_add``), a draft added nothing beyond its source (``point_check_failed``,
      ``no_point_offered``, or ``already_rejected`` on an earlier run with nothing new known since) or there were no candidates at all: ONE flag, mode
      ``flag`` (Notification Center, acknowledge only), is raised, unless one is already open for this publication. It says what would help: accept reasons
      missing, suggested links waiting in Related, the first skipped titles. It is quiet when the run did not get through its candidates (stopped by time or
      cost, so the empty result says nothing about curation), when the suggested links its connections come from are still being written
      (``suggestionsWaiting``), and when it failed to file.

    Needs ``listReviewRequests``, ``updateReviewRequest`` and ``createReviewRequest`` on the site's API (``RouterIdeaPolicy`` and the review policies of
    ``infra/monitoring/papyrus-monitoring.yaml``).
    """
    subject = f"{CURATION_SUBJECT_PREFIX}{site}"
    if client is None:
        return {"status": "not_raised", "note": "No review client was given."}
    try:
        opened = [request for request in review_requests.list_reviews(client, state="open", raised_by=RAISED_BY, mode="flag", subject_id=subject, sweep=False)]
        if run["drafts"]:
            acknowledged = []
            for request in opened:
                review_requests.answer_review(client, request["id"], decision="acknowledge", by=RAISED_BY, feedback=f"Ideas are flowing again: run {run['runId']} filed {len(run['drafts'])}.")
                acknowledged.append(request["id"])
            return {"status": "acknowledged" if acknowledged else "not_needed", "requestIds": acknowledged}
        waiting = [row for row in run["skipped"] if row["reason"] in ("nothing_to_add", *SAID_NOTHING_MORE)]
        rejected_now = [row for row in run["invalid"] if row.get("reason") in REJECTED_FOR_ADDING_NOTHING]
        no_candidates = run["inputs"]["candidates"] == 0
        rated = run.get("ratedNoIdea") or []
        if run.get("stoppedBy") == "file_error" or not (waiting or rejected_now or no_candidates or rated):
            return {"status": "not_needed"}
        if run.get("stoppedBy") in ("time", "cost") or run.get("suggestionsWaiting"):
            return {"status": "not_needed", "note": f"Not raised: the run stopped by {run['stoppedBy']}." if run.get("stoppedBy") in ("time", "cost") else "Not raised: suggested links are still being written."}
        if opened:
            return {"status": "already_open", "requestId": opened[0]["id"]}
        reason, ask = curation_flag_text(run, [*waiting, *rejected_now])
        request = review_requests.raise_review(client, subject={"type": "batch", "id": subject}, mode="flag", reason=reason, ask=ask, raised_by=RAISED_BY)
        return {"status": "raised", "requestId": request["id"], "reason": reason}
    except Exception as error:  # noqa: BLE001 - the run is done; a site without review requests must not fail it
        return {"status": "not_raised", "error": f"{type(error).__name__}: {error}"[:300]}


def curation_flag_text(run: dict[str, Any], skipped: list[dict[str, Any]]) -> tuple[str, str]:
    """(the reason, the ask) of the curation flag: what the run could not connect, and what would help most. Says "ideas", never a stage word.

    ``skipped`` holds the rows that kept the run from filing anything: a Reference with nothing to connect to (``nothing_to_add``), one whose draft said no more
    than its source (``SAID_NOTHING_MORE``, ``REJECTED_FOR_ADDING_NOTHING``), and a pack with only titles."""
    rated = run.get("ratedNoIdea") or []
    rated_ask = ""
    if rated:
        named = "; ".join(f"{row['title'] or row['referenceId']} ({row['stars']} stars: {row.get('explanation') or row['reason']})" for row in rated[:SKIPPED_TITLES_SHOWN])
        rated_ask = f" You rated {len(rated)} {'Reference' if len(rated) == 1 else 'References'} highly and no idea came of {'it' if len(rated) == 1 else 'them'}: {named}."
    if not skipped:
        pending = run["inputs"].get("notAccepted", 0)
        waiting = f" {pending} pending References are waiting to be accepted." if pending else ""
        return ("No ideas today: no accepted References are waiting to be written about.", f"Accept References to give the ideas something to work from.{waiting}{rated_ask}")
    said_nothing = [row for row in skipped if row.get("reason") in (*SAID_NOTHING_MORE, *REJECTED_FOR_ADDING_NOTHING)]
    singles = [row for row in skipped if row not in said_nothing and "found" in row and "referencesWithSummary" not in row["found"]]   # a skipped pack has no accept reason or links of its own
    packs = [row for row in skipped if row not in singles and row not in said_nothing]
    parts, help_with = [], []
    if singles:
        parts.append(f"{len(singles)} accepted {'Reference' if len(singles) == 1 else 'References'} had nothing to connect to")
    if said_nothing:
        parts.append(f"{len(said_nothing)} {'idea' if len(said_nothing) == 1 else 'ideas'} would have said no more than its sources")
    counted = [row for row in [*singles, *said_nothing] if "found" in row]
    if singles or said_nothing:
        unreasoned = sum(not row["found"].get("acceptReason") for row in counted)
        waiting_links = sum(bool(row["found"].get("suggestedLinks")) for row in counted)
        if unreasoned:
            help_with.append(f"add a reason when you accept ({unreasoned} of {len(counted)} have none)")
        if waiting_links:
            help_with.append(f"confirm the suggested links waiting in Related ({waiting_links} {'has' if waiting_links == 1 else 'have'} close matches)")
        help_with.append("comment on the ones you care about")
    if packs:
        parts.append(f"{len(packs)} {'theme' if len(packs) == 1 else 'themes'} had only titles to go on")
    titles = [str(row["title"]) for row in [*singles, *said_nothing][:SKIPPED_TITLES_SHOWN] if row.get("title")]
    more = f", and {len(singles) + len(said_nothing) - len(titles)} more" if len(singles) + len(said_nothing) > len(titles) else ""
    ask = ("What would help most: " + "; ".join(help_with) + "." if help_with else "") + (f" Waiting: {'; '.join(titles)}{more}." if titles else "")
    if said_nothing:
        ask += " One is written again as soon as there is something new to connect it to: a comment, a link, an explanation on a link, or a related Reference."
    if packs:
        ask += " A theme is written from the summaries of its References, and too few of them have one yet; it is looked at again on the next run."
    return (f"No ideas today: {' and '.join(parts)}, so the ideas would only have summarised them.", (ask + rated_ask).strip())


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
