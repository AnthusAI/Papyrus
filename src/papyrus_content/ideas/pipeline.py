"""One synthesis run: read, ask the model, validate, drop duplicates, store privately, record the run."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from . import dedupe, duplicate_cut, synthesis
from .digest import ACCEPTED, PENDING, iso
from .review import mark_steering_applied, merge_feedback, read_steering, request_human_review
from .items import IdeaRefused
from .items import ItemStore
from .store import JsonStore

DEFAULT_MAXIMUM_COST_USD = 0.50


class RunRefused(ValueError):
    """The run was stopped before any model call (too expensive, or the input is too small to synthesise)."""


def run_id_for(digest_id: str, now: datetime) -> str:
    return f"ideas-run-{now.strftime('%Y%m%dT%H%M%SZ')}-{hashlib.sha256((digest_id + iso(now)).encode()).hexdigest()[:6]}"


def idea_id_for(run_id: str, title: str) -> str:
    return "idea-" + hashlib.sha256(f"{run_id}|{title}".encode()).hexdigest()[:10]


def comparison_documents(
    context: dict[str, Any], stored_ideas: list[dict[str, Any]], proposal_drafts: list[dict[str, Any]], feedback: list[dict[str, Any]]
) -> list[dedupe.Document]:
    documents = [dedupe.Document("story", story["id"], story["title"], story.get("summary") or "") for story in context.get("stories", [])]
    documents += [
        dedupe.Document("draft", idea["ideaId"], idea["title"], idea.get("angle") or "")
        for idea in stored_ideas
        if idea.get("state") != "declined"
    ]
    documents += [
        dedupe.Document("proposal", row["id"], row["title"], row.get("summary") or "")
        for row in proposal_drafts
        if row.get("state") != "declined"
    ]
    documents += [dedupe.Document("declined", f"feedback-{n}", entry["title"], entry.get("note") or "") for n, entry in enumerate(feedback, 1) if entry["verdict"] == "decline"]
    return documents


def idea_body(idea: dict[str, Any], references: dict[str, dict[str, Any]]) -> str:
    lines = [idea["angle"], "", "## Why it is new", "", idea["noveltyNote"], "", "## What the story would claim", ""]
    for claim in idea["claims"]:
        lines.append(f"- {claim['claim']} ({'; '.join(references[i]['title'] for i in claim['referenceIds'])})")
    lines += ["", "## Cited references", ""]
    for identifier in idea["citedReferenceIds"]:
        reference = references[identifier]
        link = f"[{reference['title']}]({reference['sourceUri']})" if reference.get("sourceUri") else reference["title"]
        note = ", ".join(part for part in (reference.get("source"), reference.get("status")) if part)
        lines.append(f"- {link}" + (f" ({note})" if note else "") + f" `{identifier}`")
    return "\n".join(lines) + "\n"


def idea_record(candidate: dict[str, Any], *, run: dict[str, Any], digest: dict[str, Any], now: datetime) -> dict[str, Any]:
    by_id = {entry["id"]: entry for entry in digest["references"]}
    record = {
        "ideaId": idea_id_for(run["runId"], candidate["title"]),
        "kind": "story_draft",
        "state": "draft",
        "proposer": "ai",
        "proposedBy": "AI",
        "private": True,
        "publication": digest["publication"],
        "runId": run["runId"],
        "digestId": digest["digestId"],
        "createdAt": iso(now),
        **candidate,
        "citations": [
            {key: by_id[identifier].get(key) for key in ("id", "lineageId", "title", "source", "sourceUri", "status", "arrivedAt")}
            for identifier in candidate["citedReferenceIds"]
        ],
    }
    record["body"] = idea_body(record, by_id)
    return record


def count_inputs(digest: dict[str, Any], context: dict[str, Any], documents: list[dedupe.Document], feedback: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = digest["counts"]["byStatus"]
    return {
        "references": digest["counts"]["included"],
        "acceptedReferences": by_status.get(ACCEPTED, 0),
        "pendingReferences": by_status.get(PENDING, 0),
        "stories": len(context.get("stories", [])),
        "storyWindowDays": context.get("storyDays"),
        "earlierDrafts": sum(1 for document in documents if document.kind in {"draft", "proposal"}),
        "feedbackEntries": len(feedback),
        "sections": len(context.get("sections", [])),
        "mission": bool(context.get("mission")),
        "policy": bool(context.get("policy")),
    }


def synthesize(
    *,
    digest: dict[str, Any],
    context: dict[str, Any],
    json_store: JsonStore,
    transport: synthesis.Transport,
    idea_store: ItemStore | None = None,
    review_client: Any = None,
    feedback: list[dict[str, Any]] | None = None,
    model: str = synthesis.DEFAULT_MODEL,
    maximum: int = synthesis.DEFAULT_MAXIMUM_IDEAS,
    threshold: float | None = None,
    maximum_cost_usd: float = DEFAULT_MAXIMUM_COST_USD,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Runs synthesis and returns the run ledger (also saved); the ideas are in ``run['ideas']`` and saved one file each."""
    moment = now or datetime.now(timezone.utc)
    cut = duplicate_cut.resolve_threshold(review_client, threshold)
    threshold = cut.threshold
    run: dict[str, Any] = {
        "duplicateCut": cut.record(),
        "runId": run_id_for(digest["digestId"], moment),
        "kind": "ideas-run",
        "publication": digest["publication"],
        "digestId": digest["digestId"],
        "startedAt": iso(moment),
        "model": model,
        "store": idea_store.kind if idea_store else "json",
        "private": True,
    }
    stored = json_store.ideas()
    steering, steering_ids, steering_error = read_steering(review_client, json_store.batch_titles())
    decisions = idea_store.feedback() if hasattr(idea_store, "feedback") else []   # Items: accepted ideas and spiked ones with their reasons
    feedback = merge_feedback([*steering, *decisions], feedback or [])
    run["steering"] = {"entries": len(steering), "decisions": len(decisions), "requestIds": steering_ids, **({"error": steering_error} if steering_error else {})}
    drafts = idea_store.story_drafts() if idea_store else []
    documents = comparison_documents(context, stored, drafts, feedback)
    run["inputs"] = count_inputs(digest, context, documents, feedback)
    handles = synthesis.handles_for(digest)
    run.update(proposed=0, invalid=[], duplicates=[], ideas=[], usage=None)
    if len(handles) < synthesis.MINIMUM_CITATIONS:
        run["noCall"] = f"The digest has {len(handles)} reference(s); a synthesis needs at least {synthesis.MINIMUM_CITATIONS}."
    else:
        model_input = synthesis.build_input(digest, context, feedback, maximum)
        size = len(synthesis.SYSTEM_PROMPT) + len(str(model_input))
        if size > synthesis.MAXIMUM_INPUT_CHARACTERS:
            raise RunRefused(f"The input is {size} characters (limit {synthesis.MAXIMUM_INPUT_CHARACTERS}). Narrow the window or lower --max-references.")
        estimate = synthesis.estimate_cost_usd(model, size)
        run["estimatedCostUsd"] = estimate
        if estimate is not None and estimate > maximum_cost_usd:
            raise RunRefused(f"Estimated cost ${estimate:.4f} is over --max-cost-usd ${maximum_cost_usd:.2f}.")
        raw, usage = synthesis.call_model(transport, model, model_input)
        run["usage"] = usage.as_dict()
        run["steering"]["notApplied"] = mark_steering_applied(review_client, steering_ids, run["runId"]) if review_client else []
        run["proposed"] = len(raw)
        valid, run["invalid"] = synthesis.validate_ideas(raw, handles, [s["title"] for s in context.get("sections", [])], maximum)
        kept, run["duplicates"] = dedupe.split_duplicates(valid, documents, threshold)
        for candidate in kept:
            idea = idea_record(candidate, run=run, digest=digest, now=moment)
            if idea_store:
                try:
                    idea_store.mark(idea, idea_store.file_idea(idea, idea["body"], digest["digestId"]))
                except IdeaRefused as refusal:   # the editorial check found an error-severity violation: not filed
                    run["invalid"].append(refusal.as_invalid(idea))
                    continue
            json_store.save_idea(idea)
            run["ideas"].append(idea)
    run["ideasCreated"] = len(run["ideas"])
    request_human_review(review_client, run, run["ideas"])
    run["storiesInPrompts"] = context.get("promptStories")
    run["finishedAt"] = iso(datetime.now(timezone.utc))
    json_store.save_run(run)
    return run


def render_report(run: dict[str, Any], digest: dict[str, Any]) -> str:
    """The markdown a person reads: each idea with its citations, then what was dropped and what the run cost."""
    usage = run.get("usage") or {}
    inputs = run["inputs"]
    lines = [
        f"# Story ideas v0: {run['publication']}",
        "",
        f"Run `{run['runId']}` on digest `{digest['digestId']}` ({digest['window']['since'][:10]} to {digest['window']['until'][:10]}). "
        "Proposed by AI. These are private drafts for review; nothing here is published.",
        "",
        f"- References read: {inputs['references']} ({inputs['acceptedReferences']} accepted, {inputs['pendingReferences']} pending, not yet reviewed by an editor)",
        f"- Stories compared against: {inputs['stories']} (published in the last {inputs['storyWindowDays']} days, plus in flight); earlier drafts: {inputs['earlierDrafts']}",
        f"- Ideas created: {run['ideasCreated']}; invalid ideas dropped: {len(run['invalid'])}; near-duplicates dropped: {len(run['duplicates'])}",
        f"- Model {run['model']}: {usage.get('inputTokens', 0)} input and {usage.get('outputTokens', 0)} output tokens, cost ${usage.get('costUsd') if usage.get('costUsd') is not None else 'unknown'}",
        "",
    ]
    for number, idea in enumerate(run["ideas"], start=1):
        lines += [f"## {number}. {idea['title']}", "", f"Section: {idea['section']}. State: draft. Proposed by AI. Idea `{idea['ideaId']}`.", "", idea["body"].rstrip(), ""]
    if not run["ideas"]:
        lines += ["No ideas were kept.", ""]
    for heading, rows, describe in (
        ("Dropped as near-duplicates", run["duplicates"], lambda r: f"{r['title']} (resembles {r['similarTo']['kind']} \"{r['similarTo']['title']}\", similarity {r['similarTo']['score']})"),
        ("Dropped as invalid", run["invalid"], lambda r: f"{r['title'] or '(untitled)'}: {r['reason']}"),
    ):
        if rows:
            lines += [f"## {heading}", ""] + [f"- {describe(row)}" for row in rows] + [""]
    if run.get("noCall"):
        lines += [f"No model call was made: {run['noCall']}", ""]
    return "\n".join(lines)
