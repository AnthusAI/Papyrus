"""The editorial checklist of one Story (docs/story-procedure.md, "The checklist").

The Story procedure (``newsroom_process.STEPS``) is the template. Each live step of it becomes one ``StoryStep`` record per Story,
found through one index by Story lineage (``storyStepsByStory``). The record says what happened to the step, who did it and when, why it
was skipped, and what proves it. Nothing here scans: a Story's steps are one index read, and a small summary (counts by state) is kept on
the Story's current version (``metadata.checklist``) so a board card needs no extra query.

* A step is ``open``, ``done``, ``skipped`` or ``not_applicable``. Skipped and not applicable need a reason; a manual step (the four review
  lenses) needs a short findings note to be done. Only a person reopens a step.
* The existing writes (research packet, outline, draft, passed copy-edit check) mark their step done through the evidence logic of
  ``newsroom_process.assess``; ``sync_checklist`` runs once after a write, never on a schedule.
* A template with a new step gives an unpublished Story that step as ``open`` the next time the Story changes.
* Publishing refuses while a required step is open (``require_checklist_closed``, called by ``publishing.publish_item``).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .newsroom_process import (
    DONE,
    LIVE,
    STEPS,
    STEP_BY_KEY,
    TEMPLATE_VERSION,
    assess,
    story_facts,
)
from .record_helpers import to_aws_json

MODEL = "StoryStep"
INDEX = "storyStepsByStory"
SUMMARY_KEY = "checklist"

OPEN = "open"
STEP_DONE = "done"
SKIPPED = "skipped"
NOT_APPLICABLE = "not_applicable"
STATES = (OPEN, STEP_DONE, SKIPPED, NOT_APPLICABLE)
NEEDS_REASON = (SKIPPED, NOT_APPLICABLE)
CLOSED_STATES = (STEP_DONE, SKIPPED, NOT_APPLICABLE)

ACTOR_PERSON = "person"
ACTOR_AGENT = "agent"
ACTOR_SYSTEM = "system"
ACTOR_KINDS = (ACTOR_PERSON, ACTOR_AGENT, ACTOR_SYSTEM)
EVIDENCE_ACTOR = {"kind": ACTOR_SYSTEM, "label": "evidence"}

#: The step the publish action itself completes; the gate never waits for it.
PUBLISH_KEY = "publish"


class ChecklistError(ValueError):
    """A change to a checklist step that the rules refuse."""


def template_steps() -> list:
    """The steps a Story's checklist has: every live step of the procedure, in order. A step that is off or not built cannot be done, so it has no item."""
    return [step for step in STEPS if step.status == LIVE]


def step_order(key: str) -> int:
    return [step.key for step in STEPS].index(key)


def required_keys() -> list[str]:
    """The steps that must be closed before a Story publishes: required (not optional) and live, except publishing itself."""
    return [step.key for step in template_steps() if not step.optional and step.key != PUBLISH_KEY]


def step_id(lineage: str, key: str) -> str:
    return f"step-{lineage}-{key}"


def utc_now() -> str:
    from .publishing import utc_now_iso

    return utc_now_iso()


def read_steps(client, lineage: str) -> list[dict[str, Any]]:
    """The Story's steps, in template order. One index read by Story lineage."""
    rows = [normalize(row) for row in client.list_by_index(INDEX, lineage)]
    return sorted(rows, key=lambda row: (int(row.get("stepOrder") or 0), row["stepKey"]))


def normalize(row: dict[str, Any]) -> dict[str, Any]:
    history = row.get("history")
    if isinstance(history, str):
        try:
            history = json.loads(history) if history else []
        except json.JSONDecodeError:
            history = []
    return {**row, "history": history if isinstance(history, list) else []}


def summary_of(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {state: sum(1 for row in rows if row.get("state") == state) for state in STATES}
    required = set(required_keys())
    return {
        "templateVersion": TEMPLATE_VERSION,
        "total": len(rows),
        **counts,
        "requiredOpen": [row["stepKey"] for row in rows if row.get("state") == OPEN and row["stepKey"] in required],
    }


def progress_text(summary: dict[str, Any]) -> str:
    """The card line, for example ``4/9 · 2 skipped``: closed with a done or not-applicable answer over all, then the skipped count."""
    answered = int(summary.get("done") or 0) + int(summary.get("not_applicable") or 0)
    text = f"{answered}/{int(summary.get('total') or 0)}"
    return text + (f" · {summary['skipped']} skipped" if summary.get("skipped") else "")


def _metadata_of(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else {}
        except json.JSONDecodeError:
            value = {}
    return dict(value) if isinstance(value, dict) else {}


def refresh_summary(client, lineage: str, rows: list[dict[str, Any]], *, now: str | None = None) -> dict[str, Any]:
    """Keeps the counts on the Story's latest version so a board card shows progress with no extra query. Written only when they changed."""
    from .story_reporting import latest_story_version

    summary = summary_of(rows)
    latest = latest_story_version(client, lineage)
    metadata = _metadata_of(latest)
    if metadata.get(SUMMARY_KEY) != summary:
        metadata[SUMMARY_KEY] = summary
        # updatedAt moves with it: the board reads "changed since" by that time, so the card shows the new progress.
        client.update_record("Item", {"id": latest["id"], "updatedAt": now or utc_now(), "metadata": to_aws_json(metadata)})
    return summary


def _entry(state: str, actor: dict[str, Any], now: str, *, reason=None, note=None, evidence=None) -> dict[str, Any]:
    return {key: value for key, value in {
        "at": now, "state": state, "actorKind": actor["kind"], "actorLabel": actor.get("label"), "actorSub": actor.get("sub"),
        "reason": reason, "note": note, "evidence": evidence,
    }.items() if value not in (None, "")}


def _new_row(lineage: str, key: str, now: str) -> dict[str, Any]:
    step = STEP_BY_KEY[key]
    return {
        "id": step_id(lineage, key), "storyLineageId": lineage, "stepKey": key, "stepOrder": step_order(key),
        "templateVersion": TEMPLATE_VERSION, "title": step.title, "command": step.command.replace("{story}", lineage), "state": OPEN,
        "history": [], "createdAt": now, "updatedAt": now,
    }


def _apply(row: dict[str, Any], state: str, actor: dict[str, Any], now: str, *, reason=None, note=None, evidence=None) -> dict[str, Any]:
    entry = _entry(state, actor, now, reason=reason, note=note, evidence=evidence)
    return {
        **row, "state": state, "actorKind": actor["kind"], "actorLabel": actor.get("label"), "actorSub": actor.get("sub"),
        "changedAt": now, "reason": reason, "note": note, "evidence": evidence, "updatedAt": now,
        "history": [*row.get("history", []), entry],
    }


def _write(client, row: dict[str, Any], *, created: bool) -> None:
    payload = {**row, "history": to_aws_json(row.get("history", []))}
    if created:
        payload = {key: value for key, value in payload.items() if value is not None}
        client.create_record(MODEL, payload)
    else:
        client.update_record(MODEL, payload)


def evidence_text(key: str, facts: dict[str, Any]) -> str:
    """What proves the step, as a short reference to a record."""
    if key == "choose":
        return f"Story is at the {facts['stage']} stage"
    if key == "direction":
        return "Assignment " + next((a["id"] for a in facts["assignments"] if a["hasDirection"]), "?")
    if key == "research":
        return "Assignment " + next((a["id"] for a in facts["assignments"] if a["hasResearchPacket"]), "?") + " research packet"
    if key == "outline":
        marker = facts["metadata"].get("outline") or {}
        return f"Item {marker.get('versionId') or facts['versionId']} outline marker"
    if key == "draft":
        return f"Item {facts['versionId']} (version {facts['versionNumber']})"
    if key == "copy_edit":
        return f"Editorial check of Item {facts['versionId']}"
    if key == PUBLISH_KEY:
        return "Story is published"
    return f"Item {facts['versionId']}"


def _reopened_by_person(row: dict[str, Any]) -> bool:
    history = row.get("history") or []
    return bool(history) and history[-1].get("state") == OPEN and history[-1].get("actorKind") == ACTOR_PERSON


def sync_checklist(client, lineage: str, *, facts: dict[str, Any] | None = None, assessment: dict[str, Any] | None = None,
                   now: str | None = None) -> dict[str, Any]:
    """Brings the Story's checklist up to date once, after a change: creates a missing item (the whole checklist for a new Story, a new
    template step for an unpublished one), marks an open item done when its evidence exists, and refreshes the summary.

    A published Story gets no new template steps: its checklist is a record of what happened. An item a person reopened is not marked done
    again by evidence, and an item already skipped, not applicable or done is left as it is."""
    now = now or utc_now()
    facts = facts or story_facts(client, lineage)
    assessment = assessment or assess(facts)
    states = {row["key"]: row["state"] for row in assessment["steps"]}
    rows = {row["stepKey"]: row for row in read_steps(client, lineage)}
    kept_as_record = facts["stage"] == "published" and bool(rows)   # a published Story that has a checklist gets no new template steps
    created, completed = [], []
    for step in template_steps():
        existing = rows.get(step.key)
        if existing is None:
            if kept_as_record:
                continue
            row = _new_row(lineage, step.key, now)
            if states.get(step.key) == DONE:
                row = _apply(row, STEP_DONE, EVIDENCE_ACTOR, now, evidence=evidence_text(step.key, facts))
                completed.append(step.key)
            _write(client, row, created=True)
            rows[step.key] = row
            created.append(step.key)
        elif existing["state"] == OPEN and states.get(step.key) == DONE and not _reopened_by_person(existing):
            row = _apply(existing, STEP_DONE, EVIDENCE_ACTOR, now, evidence=evidence_text(step.key, facts))
            _write(client, row, created=False)
            rows[step.key] = row
            completed.append(step.key)
    ordered = sorted(rows.values(), key=lambda row: (int(row.get("stepOrder") or 0), row["stepKey"]))
    summary = refresh_summary(client, lineage, ordered, now=now)
    return {"created": created, "completed": completed, "summary": summary}


def sync_quietly(client, lineage: str, *, facts=None, assessment=None) -> dict[str, Any] | None:
    """``sync_checklist`` for a write that has already happened: a failure prints one line to stderr and never changes the write's result."""
    try:
        return sync_checklist(client, lineage, facts=facts, assessment=assessment)
    except Exception as error:  # noqa: BLE001 - the checklist follows the write; the write stands
        print(f"checklist\tnot updated\t{type(error).__name__}: {str(error)[:160]}", file=sys.stderr)
        return None


def ensure_for_new_story(client, lineage: str) -> dict[str, Any] | None:
    """Called by every path that creates a Story, once, right after the Story exists."""
    return sync_quietly(client, lineage)


def set_step(client, lineage: str, key: str, state: str, *, actor: dict[str, Any], reason: str | None = None, note: str | None = None,
             evidence: str | None = None, now: str | None = None) -> dict[str, Any]:
    """Marks one step done, skipped, not applicable, or open again, and records who did it and when.

    ``actor`` is ``{"kind": "person" | "agent", "label": ..., "sub": ...}``. A skip or a not-applicable answer needs a reason; a manual step
    (a review lens) needs a findings note to be done; only a person reopens a step."""
    step = STEP_BY_KEY.get(key)
    if step is None:
        raise ChecklistError(f"Unknown step {key!r}. The steps are: {', '.join(item.key for item in template_steps())}.")
    if state not in STATES:
        raise ChecklistError(f"The state must be one of {', '.join(STATES)}.")
    if actor.get("kind") not in (ACTOR_PERSON, ACTOR_AGENT) or not str(actor.get("label") or actor.get("sub") or "").strip():
        raise ChecklistError("A change needs an actor: a person or an agent, with a name.")
    reason = (reason or "").strip() or None
    note = (note or "").strip() or None
    if state in NEEDS_REASON and not reason:
        raise ChecklistError(f"Marking step '{key}' {state.replace('_', ' ')} needs a reason.")
    if state == STEP_DONE and step.manual and not note:
        raise ChecklistError(f"Marking step '{key}' done needs a short findings note.")
    if state == OPEN and actor["kind"] != ACTOR_PERSON:
        raise ChecklistError("Only a person reopens a step.")
    now = now or utc_now()
    rows = {row["stepKey"]: row for row in read_steps(client, lineage)}
    if not rows:
        sync_checklist(client, lineage, now=now)
        rows = {row["stepKey"]: row for row in read_steps(client, lineage)}
    existing = rows.get(key)
    created = existing is None
    if created and step.status != LIVE:
        raise ChecklistError(f"Step '{key}' is not live in the procedure yet, so it has no checklist item.")
    row = _apply(existing or _new_row(lineage, key, now), state, actor, now, reason=reason, note=note, evidence=evidence)
    _write(client, row, created=created)
    rows[key] = row
    refresh_summary(client, lineage, sorted(rows.values(), key=lambda item: (int(item.get("stepOrder") or 0), item["stepKey"])), now=now)
    return row


def open_required(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required = set(required_keys())
    return [row for row in rows if row["stepKey"] in required and row.get("state") == OPEN]


def require_checklist_closed(client, item: dict[str, Any]) -> None:
    """The publish rule: a Story publishes only when every required step is done, skipped with a reason or not applicable with a reason.

    A Story that has no checklist yet (made before this existed) gets one first, marked done where evidence exists, so nothing slips through
    for want of a record. Raises ``ChecklistError`` naming each open step and the command that closes it."""
    from .content_item_lifecycle import is_story_item_type

    if not is_story_item_type(item.get("type")):
        return
    lineage = item.get("lineageId") or item["id"]
    rows = read_steps(client, lineage)
    if not rows or any(step.key not in {row["stepKey"] for row in rows} for step in template_steps() if step.key != PUBLISH_KEY):
        sync_checklist(client, lineage)
        rows = read_steps(client, lineage)
    blocking = open_required(rows)
    if blocking:
        lines = [f"{STEP_BY_KEY[row['stepKey']].title} ({row['stepKey']})" for row in blocking]
        raise ChecklistError(
            "Publishing is blocked: these required steps are open: " + "; ".join(lines) + ". Mark each done, skipped with a reason or "
            f"not applicable with a reason: papyrus stories step --story {lineage} --step <step> --state <state> --reason <why>."
        )


def mark_published(client, lineage: str, *, actor_label: str) -> None:
    """After a publish succeeds, the publish step is done. Best effort: the page is live whatever happens here."""
    try:
        existing = {row["stepKey"]: row for row in read_steps(client, lineage)}
        row = existing.get(PUBLISH_KEY)
        if row is not None and row.get("state") != STEP_DONE:
            set_step(client, lineage, PUBLISH_KEY, STEP_DONE, actor={"kind": ACTOR_PERSON, "label": actor_label}, evidence="Story is published")
    except Exception as error:  # noqa: BLE001
        print(f"checklist\tnot updated\t{type(error).__name__}: {str(error)[:160]}", file=sys.stderr)


def steps_for_display(rows: list[dict[str, Any]], lineage: str) -> list[dict[str, Any]]:
    """Each stored step with its title and the command that moves it on, for ``stories next`` and for a panel."""
    shown = []
    for row in rows:
        step = STEP_BY_KEY.get(row["stepKey"])
        if step is None:
            continue
        shown.append({**row, "title": step.title, "role": step.role, "command": step.command.replace("{story}", lineage)})
    return shown


def backfill(client, *, apply: bool, stages: tuple[str, ...] | None = None, page_size: int = 50, report=None) -> dict[str, int]:
    """The one-time sweep: a checklist for every existing Story, published ones included, paged by stage.

    Steps are marked done where evidence exists (the same logic as a live write) and left open otherwise. A Story that already has a full
    checklist is counted and not touched. With ``apply`` False nothing is written and the counts say what would be."""
    from .content_item_lifecycle import CONTENT_ITEM_STAGES, is_story_item_type

    counts = {"stories": 0, "already_complete": 0, "created_items": 0, "done_by_evidence": 0, "failed": 0}
    seen: set[str] = set()
    for stage in stages or CONTENT_ITEM_STAGES:
        for row in client.iterate_newest_first("itemsByStage", stage, page_size=page_size):
            lineage = row.get("lineageId") or row["id"]
            if lineage in seen or not is_story_item_type(row.get("type")):
                continue
            seen.add(lineage)
            counts["stories"] += 1
            try:
                outcome = _backfill_one(client, lineage, apply=apply)
            except Exception as error:  # noqa: BLE001 - one bad Story never stops the sweep
                counts["failed"] += 1
                print(f"stories\tchecklist-backfill\tfailed\t{lineage}\t{type(error).__name__}: {str(error)[:160]}", file=sys.stderr)
                continue
            if outcome is None:
                counts["already_complete"] += 1
            else:
                counts["created_items"] += len(outcome["created"])
                counts["done_by_evidence"] += len(outcome["completed"])
            if report:
                report(lineage, outcome)
    return counts


def _backfill_one(client, lineage: str, *, apply: bool) -> dict[str, Any] | None:
    rows = {row["stepKey"]: row for row in read_steps(client, lineage)}
    facts = story_facts(client, lineage)
    assessment = assess(facts)
    states = {row["key"]: row["state"] for row in assessment["steps"]}
    # A published Story's checklist is a record: it gets its whole checklist once, never a later template step (see sync_checklist).
    missing = [] if (rows and facts["stage"] == "published") else [step.key for step in template_steps() if step.key not in rows]
    completable = [key for key, row in rows.items() if row["state"] == OPEN and states.get(key) == DONE and not _reopened_by_person(row)]
    if not missing and not completable:
        return None
    if apply:
        return sync_checklist(client, lineage, facts=facts, assessment=assessment)
    return {"created": missing, "completed": [key for key in [*missing, *completable] if states.get(key) == DONE]}


def checklist_lines(shown: list[dict[str, Any]]) -> list[str]:
    """The stored checklist as tab-separated lines for ``papyrus stories next``: an ``item`` line each, then the progress."""
    if not shown:
        return ["\t".join(["checklist", "none", "no checklist yet; a write to the Story makes one"])]
    lines = []
    for row in shown:
        who = f"{row.get('actorKind')}:{row.get('actorLabel')}" if row.get("actorKind") else ""
        detail = row.get("reason") or row.get("note") or row.get("evidence") or ""
        lines.append("\t".join(["item", row["stepKey"], row["state"], row["title"], who, str(row.get("changedAt") or ""), detail]))
    lines.append("\t".join(["checklist", "progress", progress_text(summary_of(shown))]))
    return lines
