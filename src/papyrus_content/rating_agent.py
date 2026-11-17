"""The rating agent's daily work (PPY-d85860, slice L1; definition ``agent_definitions/core/rate.yaml``, procedure ``rate_items``).

It reads the published Stories nobody has rated, newest first, by the site's head stage index, and asks the bulk-tier model one question about each:
three stars (the default), four (clearly better than the usual Story) or five. A five is never a rating: it is listed as a candidate for a person and
nothing more. A model answer that is none of these is listed as unjudged and never becomes a rating.

What the agent may *write* is the site's agent policy, never this module. The run asks the one gate whether it may call ``ratings_set`` (the rung the
operation table names, ``draft``). At ``observe`` the gate says a person would have to; the run then records what it would rate and why, writes no rating
and files no review request. When the site's policy later raises the rung, this same code writes the threes and fours through the same gate, with no
change here. Every read and write goes through ``images.handlers.execute`` with the run's own ``GateRun``, so each answer is kept for the run record.

Reading is bounded by the run, not by a count: Stories come one page at a time until the index ends or the run's own deadline is near, and the run
says which. The index is a partition read of the published head rows, newest first; a table is never scanned.

Outcome: ``nothing`` (reason ``nothing_unrated``) when no Story needed a rating; otherwise ``acted`` (reason ``proposed`` when nothing was written,
``rated`` when ratings were written) with the counts. A run in which the model failed for every Story it asked about fails: nothing half-done is left
looking done.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping

from papyrus_content import model_usage
from papyrus_content.agent_gate import GateRun
from papyrus_content.agent_gate.run_context import AgentRun, from_environment
from papyrus_content.content_item_lifecycle import is_story_item_type
from papyrus_content.images.handlers import Caller
from papyrus_content.item_stars import item_stars
from papyrus_content.model_defaults import DEFAULT_SMALL_LLM_MODEL

RESPONSIBILITY = "rate"
INDEX = "itemsByHeadStageForRating"   # graphql_authoring.INDEX_DEFINITIONS: one row per Story, the published partition, newest first
PUBLISHED = "published"
WRITE_OPERATION, GUIDELINES_OPERATION = "ratings_set", "guidelines_resolve"
MACHINE_STARS = (3, 4)
FIVE = 5
MODEL = DEFAULT_SMALL_LLM_MODEL   # the repository's standard cheap model for bulk work; one call per Story
NOTHING_UNRATED, PROPOSED, RATED = "nothing_unrated", "proposed", "rated"

INSTRUCTIONS = """You rate published Stories for a publication, one at a time, with a star rating that people later rely on to decide what the site features.

Three stars is the default: a sound Story that does what the publication publishes. Give four stars only when this Story is clearly better than the usual Story, in the reporting, the evidence or the writing. Answer five only for a Story that is exceptional; five is never a rating a machine gives, it flags the Story for a person to decide, so use it sparingly. Do not answer one or two: a Story under three stars should not have been published, and you are not asked to judge that.

Judge the Story on its own words, against the publication's writing guidelines when they are given. Give one plain sentence as the reason, naming what made the Story better than usual or why it is ordinary. Do not pad it."""

SCHEMA = {
    "type": "json_schema", "name": "story_rating", "strict": True,
    "schema": {"type": "object", "additionalProperties": False, "required": ["stars", "reason"],
               "properties": {"stars": {"type": "integer", "enum": [3, 4, 5]}, "reason": {"type": "string"}}},
}


class RatingError(Exception):
    """The run cannot do its work, so it fails: the message says why."""


class ModelFailed(Exception):
    """One model call failed or its answer could not be read. ``reason`` is a short code listed against the Story."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Services:
    """Everything the agent reaches outside itself for. A test replaces each one; the run never reaches the network from inside this module otherwise."""
    stories: Callable[[], Iterator[dict[str, Any]]]                 # the published head rows, newest first, one page at a time
    judge: Callable[[dict[str, Any], str], dict[str, Any]]          # (story row, guidelines text) -> {"stars", "reason"}; raises ModelFailed
    execute: Callable[..., dict[str, Any]]                          # images.handlers.execute: the one door every operation goes through
    clock: Callable[[], float] = time.time
    handlers: dict[str, Any] | None = None                          # the operation handlers to run; None means the real ones


@dataclass
class Tally:
    looked_at: int = 0
    proposals: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    unjudged: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    left_alone: list[dict[str, Any]] = field(default_factory=list)
    written: list[dict[str, Any]] = field(default_factory=list)
    stopped: str | None = None


def eligible(row: Mapping[str, Any]) -> bool:
    """A published Story that nobody has rated and that is not a translation (a translation is judged through its source)."""
    return (is_story_item_type(row.get("type")) and row.get("stage") == PUBLISHED and not row.get("sourceLineageId") and item_stars(row) is None)


def published_unrated(client: Any) -> Iterator[dict[str, Any]]:
    """The rows of the published head partition that still need a rating, newest first. Stop reading and no further page is fetched."""
    try:
        for row in client.iterate_newest_first(INDEX, PUBLISHED):
            if eligible(row):
                yield row
    except Exception as error:
        raise RatingError(f"The published Stories could not be read from the head stage index ({type(error).__name__}: {error}). The site needs the deploy that adds the "
                          "index and `papyrus stories head-index` run on it; the agent never scans a table instead.") from error


def story_id(row: Mapping[str, Any]) -> str:
    return str(row.get("lineageId") or row["id"])


def _title(row: Mapping[str, Any]) -> str:
    return str(row.get("headline") or row.get("title") or "")


def story_message(row: Mapping[str, Any], guidelines: str) -> str:
    story = {"title": _title(row), "deck": row.get("deck") or "", "section": row.get("section") or "", "body": row.get("bodyMarkus") or ""}
    parts = [f"Writing guidelines of this publication:\n{guidelines}" if guidelines else "This publication has no writing guidelines on file.",
             "Story:\n" + json.dumps(story, ensure_ascii=False)]
    return "\n\n".join(parts)


def openai_judge(api_key: str, *, transport: Any = None) -> Callable[[dict[str, Any], str], dict[str, Any]]:
    """The model call: one Story, one structured answer, through the Responses API. Each call is reported to the run's usage."""
    from papyrus_content.ideas import synthesis

    send = transport or synthesis.openai_transport(api_key)

    def judge(row: dict[str, Any], guidelines: str) -> dict[str, Any]:
        payload = {"model": MODEL, "instructions": INSTRUCTIONS, "input": story_message(row, guidelines), "text": {"format": SCHEMA}, "store": False}
        try:
            body = send(synthesis.RESPONSES_URL, {"Content-Type": "application/json"}, payload)
        except synthesis.SynthesisError:
            raise ModelFailed("model_failed") from None
        used = synthesis.usage_of(body, MODEL)
        model_usage.record({"agent": "rate_items", "model": MODEL, "provider": "openai", "promptTokens": used.input_tokens,
                            "completionTokens": used.output_tokens, "cachedTokens": used.cached_input_tokens})
        answer = synthesis.response_text(body)
        if body.get("status") == "incomplete" or not answer:
            raise ModelFailed("model_answer_empty")
        try:
            decided = json.loads(answer)
            return {"stars": decided["stars"], "reason": str(decided.get("reason") or "").strip()}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ModelFailed("model_answer_unreadable") from None

    return judge


def default_services(environ: Mapping[str, str]) -> Services:
    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.images.handlers import execute

    api_key = str(environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RatingError("The run has no model key (OPENAI_API_KEY), so nothing can be judged. The site's key is PPY-6af46b.")
    client, _ = create_authoring_client()
    return Services(stories=lambda: published_unrated(client), judge=openai_judge(api_key), execute=execute)


def _read_guidelines(services: Services, caller: Caller) -> str:
    """The site's writing guidelines as text for the model, read through the gate (a read, allowed from observe). A site with none gives an empty text."""
    from papyrus_content.guidelines.agent_text import writing_text

    answer = services.execute(GUIDELINES_OPERATION, {"kind": "writing"}, caller, services.handlers)
    if not answer.get("ok"):
        raise RatingError(f"The site's writing guidelines could not be read: {answer['error']['code']}: {answer['error']['message']}")
    result = answer["result"]
    return writing_text(result["document"]) if result.get("found") else ""


def _write(services: Services, caller: Caller, row: Mapping[str, Any], proposal: dict[str, Any], tally: Tally) -> None:
    answer = services.execute(WRITE_OPERATION, {"story": proposal["story"], "stars": proposal["stars"]}, caller, services.handlers)
    if answer.get("ok"):
        tally.written.append({"story": proposal["story"], "stars": proposal["stars"], "ratedBy": answer["result"]["ratedBy"]})
    elif answer["error"]["code"] == "constraint_conflict":   # a person rated it while the run was working: theirs stands
        tally.left_alone.append({"story": proposal["story"], "reason": "already_rated"})
    else:
        raise RatingError(f"The rating of {proposal['story']} was refused: {answer['error']['code']}: {answer['error']['message']}")


def work(run: AgentRun, services: Services) -> tuple[Tally, GateRun, bool]:
    caller = Caller(kind="agent", subject=RESPONSIBILITY, gate_run=GateRun(run.policy, run.responsibility, run.run_id))
    gate_run: GateRun = caller.gate_run
    guidelines = _read_guidelines(services, caller)
    may_write = gate_run.ask(WRITE_OPERATION).allowed   # the one question: what the site's policy lets this agent do, answered by the one gate
    tally, longest = Tally(), 0.0
    for row in services.stories():
        if run.deadline is not None and run.deadline - services.clock() <= longest:
            tally.stopped = "deadline"
            break
        tally.looked_at += 1
        started = services.clock()
        try:
            decided = services.judge(dict(row), guidelines)
        except ModelFailed as failure:
            tally.failed.append({"story": story_id(row), "title": _title(row), "reason": failure.reason})
            longest = max(longest, services.clock() - started)
            continue
        longest = max(longest, services.clock() - started)
        stars, reason = decided.get("stars"), str(decided.get("reason") or "")
        entry = {"story": story_id(row), "title": _title(row), "reason": reason}
        if stars == FIVE:
            tally.candidates.append(entry)   # a person decides a five: listed, never proposed, never written
        elif stars in MACHINE_STARS and not isinstance(stars, bool):
            proposal = {**entry, "stars": stars}
            tally.proposals.append(proposal)
            if may_write:
                _write(services, caller, row, proposal, tally)
        else:
            tally.unjudged.append({**entry, "reason": "model_answer_invalid"})
    return tally, gate_run, may_write


def summary_of(tally: Tally, rung: str | None) -> str:
    parts = [f"{len(tally.proposals)} {'rating' if len(tally.proposals) == 1 else 'ratings'}", f"{len(tally.candidates)} five-star "
             f"{'candidate' if len(tally.candidates) == 1 else 'candidates'} for a person"]
    done = f"wrote {len(tally.written)}" if tally.written else "wrote none"
    problems = len(tally.failed) + len(tally.unjudged)
    return (f"Looked at {tally.looked_at} unrated {'Story' if tally.looked_at == 1 else 'Stories'}: {', '.join(parts)}; {done} (rung {rung})."
            + (f" {problems} could not be judged." if problems else "") + (" Stopped at the run's deadline." if tally.stopped else ""))


def compact_record(gate_run: GateRun) -> dict[str, Any]:
    """The gate's answers for the run record, each distinct answer once with how many times it was given (a run that writes asks once per rating)."""
    counted: dict[str, dict[str, Any]] = {}
    for entry in gate_run.record()["gate"]:
        key = json.dumps(entry, sort_keys=True)
        counted[key] = {**entry, "count": counted[key]["count"] + 1} if key in counted else {**entry, "count": 1}
    return {"policyVersion": gate_run.policy.version, "gate": list(counted.values())}


def rate_items(environ: Mapping[str, str] | None = None, services: Services | None = None) -> dict[str, Any]:
    """Do one day's rating work. Returns the procedure's result with ``run_outcome`` and ``run_outcome_reason`` for the runner."""
    environment = os.environ if environ is None else environ
    run = from_environment(environment)
    if run is None or run.responsibility != RESPONSIBILITY:
        raise RatingError("The rating agent runs only on an agent's wake, adopted as the responsibility \"rate\": it needs the policy the runner read for the run.")
    services = services or default_services(environment)
    tally, gate_run, _ = work(run, services)
    rung = next((answer.rung for answer in gate_run.answers if answer.rung), None)
    result = {"rung": rung, "looked_at": tally.looked_at, "proposed": len(tally.proposals), "candidates": len(tally.candidates), "written": len(tally.written),
              "proposals": tally.proposals, "five_star_candidates": tally.candidates, "unjudged": tally.unjudged, "failed": tally.failed,
              "left_alone": tally.left_alone, "written_ratings": tally.written, "stopped": tally.stopped, "gate_answers": compact_record(gate_run)}
    if tally.looked_at and not (tally.proposals or tally.candidates or tally.unjudged or tally.left_alone):
        raise RatingError(f"The model failed for every one of the {tally.looked_at} Stories it was asked about ({tally.failed[0]['reason']}), so nothing was rated.")
    if not tally.looked_at:
        return {**result, "summary": "No published Story is waiting for a rating.", "run_outcome": "nothing", "run_outcome_reason": NOTHING_UNRATED}
    return {**result, "summary": summary_of(tally, rung), "run_outcome": "acted", "run_outcome_reason": RATED if tally.written else PROPOSED}
