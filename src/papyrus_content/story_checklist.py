"""The editorial checklist of one Story (docs/story-procedure.md, "The checklist").

The Story procedure (``newsroom_process.STEPS``) is the template. Following Kanbus, each live step of it is a sub-task of the Story: an ``Item`` of type
``sub-task`` whose ``parentLineageId`` is the Story's lineage. The ``Item`` table is the newsroom's one issues table; there is no separate table. A
Story's steps are one index read (``itemsByParent``: parent, then ``sortTitle``, the zero-padded step order). Item versioning is the history: every
change is a new version with its creator and time. A small summary (counts by state) is kept on the Story's current version
(``metadata.checklist``) so a board card needs no extra query.

Fields of a sub-task Item: ``lineageId`` ``step-<story>-<key>``, ``title`` (the step's words), ``status`` (the state: ``open``, ``done``, ``skipped``,
``not_applicable``), ``typeStatus``, ``sortTitle``, ``parentLineageId``, ``versionCreatedBy`` / ``versionCreatedAt`` (the actor and time),
``changeReason`` (the reason or findings note) and ``metadata.checklist`` (step key, template version, the command, and this version's actor kind,
sub, reason, note and evidence reference). A sub-task has no stage, no section and no body: it never reaches a board column, a listing or a page,
and ``sub-task`` is a system type (``content_item_lifecycle.SYSTEM_ITEM_TYPES``), so it is never a Story and never publishable.

* A change records the number of the Story version it was made against (``storyVersion``); ``newsroom_process.resolve`` reads a ``done`` of a versioned
  step (copy edit, review lenses) against an earlier version as stale (docs/story-procedure.md, "Staleness").
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
    NOT_APPLICABLE as EVIDENCE_NOT_APPLICABLE,
    DEFAULT_PROCEDURE,
    Procedure,
    STEP_BY_KEY,
    TEMPLATE_VERSION,
    ADDED_AFTER_PUBLISH_KEYS,
    assess,
    procedure_of,
    story_facts,
)
from .record_helpers import to_aws_json

SUB_TASK_TYPE = "sub-task"
INDEX = "itemsByParent"
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
TEMPLATE_ACTOR = {"kind": ACTOR_SYSTEM, "label": "Automatically, from the template"}
#: What proves each step, in the words an editor reads after "Automatically, from ".
EVIDENCE_SOURCES = {
    "choose": "the Story's stage", "direction": "the research direction", "research": "the research packet", "outline": "the outline",
    "draft": "the draft version", "copy_edit": "the copy-edit check", "illustration": "the cover", "rated": "the editor's star rating", "publish": "publishing",
}


def evidence_actor(key: str) -> dict[str, Any]:
    """The actor of a step the records proved: nobody, so the label says where the proof came from."""
    return {"kind": ACTOR_SYSTEM, "label": f"Automatically, from {EVIDENCE_SOURCES.get(key, 'the records')}"}


#: The step the publish action itself completes; the gate never waits for it.
PUBLISH_KEY = "publish"


class ChecklistError(ValueError):
    """A change to a checklist step that the rules refuse. ``open_steps`` lists the steps that block a publish: ``[{"key", "label"}]`` (PPY-0515e1)."""

    def __init__(self, message: str = "", open_steps: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.open_steps = list(open_steps or [])


def template_steps(procedure: Procedure = DEFAULT_PROCEDURE) -> list:
    """The steps a Story's checklist has: every live step of the procedure (the site's own, or the default), in order. A step that is off or not built cannot be done, so it has no item."""
    return [step for step in procedure.steps if step.status == LIVE]


def step_order(key: str, procedure: Procedure = DEFAULT_PROCEDURE) -> int:
    return [step.key for step in procedure.steps].index(key)


def required_keys(procedure: Procedure = DEFAULT_PROCEDURE) -> list[str]:
    """The steps that must be closed before a Story publishes: required (not optional) and live, except publishing itself."""
    return [step.key for step in template_steps(procedure) if not step.optional and step.key != PUBLISH_KEY]


def step_id(lineage: str, key: str) -> str:
    return f"step-{lineage}-{key}"


def utc_now() -> str:
    from .publishing import utc_now_iso

    return utc_now_iso()


def read_steps(client, lineage: str) -> list[dict[str, Any]]:
    """The Story's steps, in template order. One index read by parent (the Story's lineage).

    Each step is the newest version of its sub-task Item; its ``history`` is every version's entry, oldest first."""
    versions: dict[str, list[dict[str, Any]]] = {}
    for row in client.list_by_index(INDEX, lineage):
        if row.get("type") == SUB_TASK_TYPE and isinstance(row.get("lineageId"), str):
            versions.setdefault(row["lineageId"], []).append(row)
    return sorted((_flat(group) for group in versions.values()), key=lambda step: (int(step.get("stepOrder") or 0), step["stepKey"]))


def _checklist_meta(row: dict[str, Any]) -> dict[str, Any]:
    value = _metadata_of(row).get(SUMMARY_KEY)
    return value if isinstance(value, dict) else {}


def _flat(group: list[dict[str, Any]]) -> dict[str, Any]:
    """One step from its versions of the sub-task Item: the newest is the step; every version's entry is its history."""
    ordered = sorted(group, key=lambda row: int(row.get("versionNumber") or 0))
    current = ordered[-1]
    meta = _checklist_meta(current)
    entry = meta.get("entry") if isinstance(meta.get("entry"), dict) else {}
    return {
        "id": current["lineageId"], "itemId": current["id"], "storyLineageId": current.get("parentLineageId"), "stepKey": meta.get("stepKey"),
        "stepOrder": meta.get("stepOrder", 0), "templateVersion": meta.get("templateVersion"), "title": current.get("title"), "command": meta.get("command"),
        "state": current.get("status"), "actorKind": entry.get("actorKind"), "actorLabel": entry.get("actorLabel"), "actorSub": entry.get("actorSub"),
        "changedAt": entry.get("at") or current.get("versionCreatedAt"), "reason": entry.get("reason"), "note": entry.get("note"),
        "evidence": entry.get("evidence"), "storyVersion": entry.get("storyVersion"), "history": _history_of(ordered), "versionNumber": int(current.get("versionNumber") or len(ordered)),
        "notes": [note for note in (meta.get("notes") or []) if isinstance(note, dict)],
    }


def _history_of(ordered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The state changes, oldest first. A version that only added a note repeats the entry before it and is not a change."""
    history: list[dict[str, Any]] = []
    for row in ordered:
        entry = _checklist_meta(row).get("entry") or {}
        if not history or history[-1] != entry:
            history.append(entry)
    return history


def summary_of(rows: list[dict[str, Any]], procedure: Procedure = DEFAULT_PROCEDURE) -> dict[str, Any]:
    counts = {state: sum(1 for row in rows if row.get("state") == state) for state in STATES}
    required = set(required_keys(procedure))
    return {
        "templateVersion": TEMPLATE_VERSION,
        "total": len(rows),
        **counts,
        "requiredOpen": [row["stepKey"] for row in rows if row.get("state") == OPEN and row["stepKey"] in required],
    }


def progress_text(summary: dict[str, Any], stale: int = 0) -> str:
    """The card line, for example ``4/9 · 2 skipped``: closed with a done or not-applicable answer over all, then the skipped count.

    ``stale`` is for ``stories next``: done steps recorded against an earlier version are not counted as answered, and the line says how many."""
    answered = int(summary.get("done") or 0) + int(summary.get("not_applicable") or 0) - stale
    text = f"{answered}/{int(summary.get('total') or 0)}"
    return text + (f" · {summary['skipped']} skipped" if summary.get("skipped") else "") + (f" · {stale} stale" if stale else "")


def _metadata_of(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else {}
        except json.JSONDecodeError:
            value = {}
    return dict(value) if isinstance(value, dict) else {}


def refresh_summary(client, lineage: str, rows: list[dict[str, Any]], *, now: str | None = None, procedure: Procedure | None = None) -> dict[str, Any]:
    """Keeps the counts on the Story's latest version so a board card shows progress with no extra query. Written only when they changed."""
    from .story_reporting import latest_story_version

    summary = summary_of(rows, procedure or procedure_of(client))
    latest = latest_story_version(client, lineage)
    metadata = _metadata_of(latest)
    if metadata.get(SUMMARY_KEY) != summary:
        metadata[SUMMARY_KEY] = summary
        # updatedAt moves with it: the board reads "changed since" by that time, so the card shows the new progress.
        client.update_record("Item", {"id": latest["id"], "updatedAt": now or utc_now(), "metadata": to_aws_json(metadata)})
    return summary


def _entry(state: str, actor: dict[str, Any], now: str, *, reason=None, note=None, evidence=None, story_version=None) -> dict[str, Any]:
    return {key: value for key, value in {
        "at": now, "state": state, "actorKind": actor["kind"], "actorLabel": actor.get("label"), "actorSub": actor.get("sub"),
        "reason": reason, "note": note, "evidence": evidence, "storyVersion": story_version,
    }.items() if value not in (None, "")}


def _new_row(lineage: str, key: str, procedure: Procedure = DEFAULT_PROCEDURE) -> dict[str, Any]:
    step = procedure.by_key[key]
    return {
        "id": step_id(lineage, key), "storyLineageId": lineage, "stepKey": key, "stepOrder": step_order(key, procedure),
        "templateVersion": TEMPLATE_VERSION, "title": step.title, "command": step.command.replace("{story}", lineage), "history": [], "notes": [],
        "versionNumber": 0,
    }


def _apply(row: dict[str, Any], state: str, actor: dict[str, Any], now: str, *, reason=None, note=None, evidence=None, story_version=None) -> dict[str, Any]:
    """``story_version`` is the number of the Story version the change was made against (see ``newsroom_process.resolve`` for what goes stale)."""
    entry = _entry(state, actor, now, reason=reason, note=note, evidence=evidence, story_version=story_version)
    return {
        **row, "state": state, "actorKind": actor["kind"], "actorLabel": actor.get("label"), "actorSub": actor.get("sub"),
        "changedAt": now, "reason": reason, "note": note, "evidence": evidence, "storyVersion": story_version, "history": [*row.get("history", []), entry],
        "versionNumber": int(row.get("versionNumber") or 0) + 1, "written": {"by": entry.get("actorLabel") or entry.get("actorSub"), "at": now, "reason": reason or note or state},
    }


def _write(client, row: dict[str, Any], *, supersede: bool = True) -> None:
    """Writes the step's newest change as the next version of its sub-task Item (versions are the history). The version before it is marked
    superseded unless ``supersede`` is False (a role that may create Items but not update them); the newest version is the step either way.
    A version carries the state entry of the last change and the step's whole log of notes, so a note adds a version and changes no state."""
    number = int(row["versionNumber"])
    entry = row["history"][-1]
    written = row["written"]
    state = row["state"]
    payload = {
        "id": f"{row['id']}-v{number}", "lineageId": row["id"], "versionNumber": number, "versionState": "current", "versionCreatedAt": written["at"],
        "versionCreatedBy": written["by"], "changeReason": written["reason"],
        "type": SUB_TASK_TYPE, "status": state, "typeStatus": f"{SUB_TASK_TYPE}#{state}", "slug": row["id"], "title": row["title"],
        "sortTitle": f"{int(row['stepOrder']):03d}", "parentLineageId": row["storyLineageId"], "updatedAt": written["at"],
        "metadata": to_aws_json({SUMMARY_KEY: {
            "stepKey": row["stepKey"], "stepOrder": row["stepOrder"], "templateVersion": row["templateVersion"], "command": row.get("command"), "entry": entry,
            "notes": row.get("notes") or [],
        }}),
    }
    if number > 1:
        payload["previousVersionId"] = f"{row['id']}-v{number - 1}"
    client.create_record("Item", {key: value for key, value in payload.items() if value is not None})
    if number > 1 and supersede:
        client.update_record("Item", {"id": f"{row['id']}-v{number - 1}", "versionState": "superseded"})


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
    if key == "illustration":
        from .story_illustration import cover_evidence

        return cover_evidence(facts.get("illustration"))[1]
    if key == RATED_KEY:
        from .story_rating import rating_evidence

        return rating_evidence(facts.get("rating"))[1]
    if key == PUBLISH_KEY:
        return "Story is published"
    return f"Item {facts['versionId']}"


def _reopened_by_person(row: dict[str, Any]) -> bool:
    history = row.get("history") or []
    return bool(history) and history[-1].get("state") == OPEN and history[-1].get("actorKind") == ACTOR_PERSON


def sync_checklist(client, lineage: str, *, facts: dict[str, Any] | None = None, assessment: dict[str, Any] | None = None,
                   now: str | None = None, write_summary: bool = True) -> dict[str, Any]:
    """Brings the Story's checklist up to date once, after a change: creates a missing item (the whole checklist for a new Story, a new
    template step for an unpublished one), marks an open item done when its evidence exists, and refreshes the summary.

    A published Story gets no new template steps: its checklist is a record of what happened. An item a person reopened is not marked done
    again by evidence, and an item already skipped, not applicable or done is left as it is."""
    now = now or utc_now()
    facts = facts or story_facts(client, lineage)
    procedure = Procedure.from_spec(facts.get("procedureSpec"))
    assessment = assessment or assess(facts)
    states = {row["key"]: row.get("evidence", row["state"]) for row in assessment["steps"]}   # what the records prove, never the stored answer
    version = int(facts["versionNumber"])
    rows = {row["stepKey"]: row for row in read_steps(client, lineage)}
    kept_as_record = facts["stage"] == "published" and bool(rows)   # a published Story that has a checklist gets no new template steps
    created, completed = [], []
    for step in template_steps(procedure):
        existing = rows.get(step.key)
        if existing is None:
            if kept_as_record:
                continue
            if states.get(step.key) == EVIDENCE_NOT_APPLICABLE:
                continue   # a Story type the step is not required for has no item for it (it joins the checklist if the type changes)
            if facts["stage"] == "published" and step.key in ADDED_AFTER_PUBLISH_KEYS and states.get(step.key) != DONE:
                continue   # published before the step existed: the record gets no failing item; a revision closes it (see require_checklist_closed)
            row = _new_row(lineage, step.key, procedure)
            if states.get(step.key) == DONE:
                row = _apply(row, STEP_DONE, evidence_actor(step.key), now, evidence=evidence_text(step.key, facts), story_version=version)
                completed.append(step.key)
            else:
                row = _apply(row, OPEN, TEMPLATE_ACTOR, now, story_version=version)
            _write(client, row, supersede=write_summary)
            rows[step.key] = row
            created.append(step.key)
        elif existing["state"] == OPEN and states.get(step.key) == DONE and not _reopened_by_person(existing):
            row = _apply(existing, STEP_DONE, evidence_actor(step.key), now, evidence=evidence_text(step.key, facts), story_version=version)
            _write(client, row, supersede=write_summary)
            rows[step.key] = row
            completed.append(step.key)
        elif (existing["state"] == STEP_DONE and step.versioned and not step.manual and states.get(step.key) == DONE
              and existing.get("storyVersion") != version and not _reopened_by_person(existing)):
            # A versioned step the records can prove (the copy edit) whose evidence now holds for a newer version: record it again for that version.
            row = _apply(existing, STEP_DONE, evidence_actor(step.key), now, evidence=evidence_text(step.key, facts), story_version=version)
            _write(client, row, supersede=write_summary)
            rows[step.key] = row
            completed.append(step.key)
    ordered = sorted(rows.values(), key=lambda row: (int(row.get("stepOrder") or 0), row["stepKey"]))
    # The research worker's role may create Items but not update them: it leaves the card summary (and the old version's mark) for the next change by an editor.
    summary = refresh_summary(client, lineage, ordered, now=now, procedure=procedure) if write_summary else summary_of(ordered, procedure)
    return {"created": created, "completed": completed, "summary": summary}


def sync_quietly(client, lineage: str, *, facts=None, assessment=None, write_summary: bool = True, read_cover: bool = True) -> dict[str, Any] | None:
    """``sync_checklist`` for a write that has already happened: a failure prints one line to stderr and never changes the write's result."""
    try:
        return sync_checklist(client, lineage, facts=facts, assessment=assessment, write_summary=write_summary)
    except Exception as error:  # noqa: BLE001 - the checklist follows the write; the write stands
        print(f"checklist\tnot updated\t{type(error).__name__}: {str(error)[:160]}", file=sys.stderr)
        return None


def ensure_for_new_story(client, lineage: str) -> dict[str, Any] | None:
    """Called by every path that creates a Story, once, right after the Story exists, under a role that can read the site's documents (the checklist follows the site's procedure)."""
    return sync_quietly(client, lineage)


def _current_version_number(client, lineage: str) -> int | None:
    """The number of the Story's current version, recorded with a change so a later version can tell the record is of an earlier one. None if unreadable."""
    from .story_reporting import current_story_version

    try:
        return int(current_story_version(client, lineage).get("versionNumber") or 0) or None
    except Exception:  # noqa: BLE001
        return None


ILLUSTRATION_KEY = "illustration"


def illustration_resolution(lineage: str) -> str:
    """How to resolve an unresolved Illustration, in the words every refusal uses."""
    return (
        "Give the Story a stored cover: a stock picture picked in the newsroom's Cover image, or a figure (`papyrus figures render`, then "
        f"`papyrus stories save-version --story {lineage} --body-file draft.md --images ./pictures`, with the cover as front matter `image`); the step then closes by itself. "
        f"Or a person records an exception: `papyrus stories step --story {lineage} --step illustration --state skipped --reason <why>`."
    )


def _illustration_rules(client, lineage: str, key: str, state: str, actor: dict[str, Any], evidence: str | None) -> str | None:
    """The two rules only Illustration has: it is done only when the records prove it (never by hand), and an exception is a person's decision.
    Returns the evidence reference to record when it is done."""
    if key != ILLUSTRATION_KEY:
        return evidence
    if state == STEP_DONE:
        from .story_illustration import DONE as COVER_DONE, cover_evidence

        found, text = cover_evidence(story_facts(client, lineage).get("illustration"))
        if found != COVER_DONE:
            raise ChecklistError(f"Illustration cannot be marked done by hand: {text}. {illustration_resolution(lineage)}")
        return text
    if state in NEEDS_REASON and actor.get("kind") != ACTOR_PERSON:
        raise ChecklistError(
            "Only a person records an exception for Illustration (an agent asks an editor to). "
            f"An editor runs `papyrus stories step --story {lineage} --step illustration --state {state} --reason <why>`."
        )
    return evidence


RATED_KEY = "rated"


def rated_resolution(lineage: str) -> str:
    """How to resolve an unrated Story, in the words every refusal uses."""
    return f"An editor rates the Story: `papyrus stories set-stars --story {lineage} --stars N` (N from 1 to 5); the step then closes by itself."


def _rated_rules(client, lineage: str, key: str, state: str, evidence: str | None) -> str | None:
    """The one rule only Rated has: it is closed only by the rating itself. It is done only when the records prove it, and it has no exception: a Story
    a site requires rated is rated, never skipped. Returns the evidence reference to record when it is done."""
    if key != RATED_KEY:
        return evidence
    if state == STEP_DONE:
        from .story_rating import DONE as RATED_DONE, rating_evidence

        found, text = rating_evidence(story_facts(client, lineage).get("rating"))
        if found != RATED_DONE:
            raise ChecklistError(f"Rated cannot be marked done by hand: {text}. {rated_resolution(lineage)}")
        return text
    if state in NEEDS_REASON:
        raise ChecklistError(f"Rated cannot be {state.replace('_', ' ')}: a site that requires a rating publishes only rated Stories. {rated_resolution(lineage)}")
    return evidence


def set_step(client, lineage: str, key: str, state: str, *, actor: dict[str, Any], reason: str | None = None, note: str | None = None,
             evidence: str | None = None, now: str | None = None) -> dict[str, Any]:
    """Marks one step done, skipped, not applicable, or open again, and records who did it and when.

    ``actor`` is ``{"kind": "person" | "agent", "label": ..., "sub": ...}``. A skip or a not-applicable answer needs a reason; a manual step
    (a review lens) needs a findings note to be done; only a person reopens a step."""
    procedure = procedure_of(client)
    step = procedure.by_key.get(key)
    if step is None:
        raise ChecklistError(f"Unknown step {key!r}. The steps are: {', '.join(item.key for item in template_steps(procedure))}.")
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
    evidence = _illustration_rules(client, lineage, key, state, actor, evidence)
    evidence = _rated_rules(client, lineage, key, state, evidence)
    now = now or utc_now()
    rows = {row["stepKey"]: row for row in read_steps(client, lineage)}
    if not rows:
        sync_checklist(client, lineage, now=now)
        rows = {row["stepKey"]: row for row in read_steps(client, lineage)}
    existing = rows.get(key)
    if existing is None and step.status != LIVE:
        raise ChecklistError(f"Step '{key}' is not live in the procedure yet, so it has no checklist item.")
    row = _apply(existing or _new_row(lineage, key, procedure), state, actor, now, reason=reason, note=note, evidence=evidence, story_version=_current_version_number(client, lineage))
    _write(client, row)
    rows[key] = row
    refresh_summary(client, lineage, sorted(rows.values(), key=lambda item: (int(item.get("stepOrder") or 0), item["stepKey"])), now=now)
    return row


def add_note(client, lineage: str, key: str, text: str, *, actor: dict[str, Any], now: str | None = None, supersede: bool = True) -> dict[str, Any]:
    """Adds a note to a step, whatever its state, for context later. Notes only accumulate: each is who (a person or an agent, by name), when and its
    text, newest last; there is no way to edit or delete one, and a correction is a new note. The step's state, reason and findings do not change.
    A note is one more version of the step's sub-task Item (created, never updated), so versions still record who and when."""
    procedure = procedure_of(client)
    if procedure.by_key.get(key) is None:
        raise ChecklistError(f"Unknown step {key!r}. The steps are: {', '.join(item.key for item in template_steps(procedure))}.")
    if actor.get("kind") not in (ACTOR_PERSON, ACTOR_AGENT) or not str(actor.get("label") or actor.get("sub") or "").strip():
        raise ChecklistError("A note needs an author: a person or an agent, with a name.")
    text = (text or "").strip()
    if not text:
        raise ChecklistError("A note needs some text.")
    now = now or utc_now()
    rows = {row["stepKey"]: row for row in read_steps(client, lineage)}
    if not rows:
        sync_checklist(client, lineage, now=now)
        rows = {row["stepKey"]: row for row in read_steps(client, lineage)}
    existing = rows.get(key)
    if existing is None:
        raise ChecklistError(f"Step '{key}' is not live in the procedure yet, so it has no checklist item.")
    note = {k: v for k, v in {"at": now, "actorKind": actor["kind"], "actorLabel": actor.get("label"), "actorSub": actor.get("sub"), "text": text}.items() if v}
    row = {**existing, "notes": [*existing.get("notes", []), note], "versionNumber": int(existing.get("versionNumber") or 0) + 1,
           "written": {"by": actor.get("label") or actor.get("sub"), "at": now, "reason": f"note: {text[:80]}"}}
    _write(client, row, supersede=supersede)
    return row


def notes_text(rows: list[dict[str, Any]]) -> str:
    """The step notes as plain text for an agent's context (the context pack): one block per step that has notes, oldest first."""
    blocks = []
    for row in rows:
        notes = row.get("notes") or []
        if not notes:
            continue
        lines = [f"Notes on the step {row['stepKey']} ({row.get('title') or row['stepKey']}), oldest first:"]
        lines += [f"- {note.get('actorLabel') or note.get('actorSub') or 'someone'} ({note.get('actorKind') or 'unknown'}), {note.get('at')}: {note.get('text')}" for note in notes]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def mark_imported(client, lineage: str, source: str, *, now: str | None = None) -> bool:
    """A Story that was imported (not written in the newsroom) gets a checklist with every step but publishing marked not applicable, reason
    ``imported from <source>``. Nothing is touched when the Story already has a checklist. Returns whether it made one."""
    now = now or utc_now()
    if read_steps(client, lineage):
        return False
    actor = {"kind": ACTOR_SYSTEM, "label": "Automatically, from the import"}
    rows = []
    procedure = procedure_of(client)
    for step in template_steps(procedure):
        row = _new_row(lineage, step.key, procedure)
        row = _apply(row, OPEN if step.key == PUBLISH_KEY else NOT_APPLICABLE, actor if step.key != PUBLISH_KEY else TEMPLATE_ACTOR, now,
                     reason=None if step.key == PUBLISH_KEY else f"imported from {source}", story_version=_current_version_number(client, lineage))
        _write(client, row)
        rows.append(row)
    refresh_summary(client, lineage, rows, now=now)
    return True


def mark_imported_quietly(client, lineage: str, source: str) -> None:
    """``mark_imported`` for an import that has already saved the Story: a failure prints one line to stderr and never fails the import."""
    try:
        mark_imported(client, lineage, source)
    except Exception as error:  # noqa: BLE001
        print(f"checklist\tnot updated\t{type(error).__name__}: {str(error)[:160]}", file=sys.stderr)


def open_required(rows: list[dict[str, Any]], procedure: Procedure = DEFAULT_PROCEDURE) -> list[dict[str, Any]]:
    required = set(required_keys(procedure))
    return [row for row in rows if row["stepKey"] in required and row.get("state") == OPEN]


def require_checklist_closed(client, item: dict[str, Any]) -> None:
    """The publish rule: a Story publishes only when every required step is done, skipped with a reason or not applicable with a reason.

    A Story that has no checklist yet (made before this existed) gets one first, marked done where evidence exists, so nothing slips through
    for want of a record. Raises ``ChecklistError`` naming each open step and the command that closes it."""
    from .content_item_lifecycle import is_story_item_type

    if not is_story_item_type(item.get("type")):
        return
    lineage = item.get("lineageId") or item["id"]
    procedure = procedure_of(client)   # a procedure that cannot be read stops the publish: nothing guesses which one the site has
    rows = read_steps(client, lineage)
    if not rows or any(step.key not in {row["stepKey"] for row in rows} for step in template_steps(procedure) if step.key != PUBLISH_KEY):
        sync_checklist(client, lineage)
        rows = read_steps(client, lineage)
    titles = {key: step.title for key, step in {**STEP_BY_KEY, **procedure.by_key}.items()}
    blocking = [row for row in open_required(rows, procedure) if row["stepKey"] not in (ILLUSTRATION_KEY, RATED_KEY)]
    lines = [f"{titles[row['stepKey']]} ({row['stepKey']})" for row in blocking]
    open_steps = [{"key": row["stepKey"], "label": titles[row["stepKey"]]} for row in blocking]
    problem = illustration_problem(client, item, rows) if ILLUSTRATION_KEY in procedure.by_key else None
    if problem:
        lines.append(f"{titles[ILLUSTRATION_KEY]} ({ILLUSTRATION_KEY}): {problem}")
        open_steps.append({"key": ILLUSTRATION_KEY, "label": titles[ILLUSTRATION_KEY]})
    unrated = rated_problem(client, item) if RATED_KEY in procedure.by_key else None
    if unrated:
        lines.append(f"{titles[RATED_KEY]} ({RATED_KEY}): {unrated}")
        open_steps.append({"key": RATED_KEY, "label": titles[RATED_KEY]})
    if lines:
        raise ChecklistError(
            "Publishing is blocked: these required steps are open: " + "; ".join(lines) + ". Mark each done, skipped with a reason or "
            f"not applicable with a reason: papyrus stories step --story {lineage} --step <step> --state <state> --reason <why>."
            + (f" For Illustration: {illustration_resolution(lineage)}" if problem else "")
            + (f" For Rated: {rated_resolution(lineage)}" if unrated else ""),
            open_steps,
        )


def illustration_problem(client, item: dict[str, Any], rows: list[dict[str, Any]]) -> str | None:
    """Why the version being published still has an unresolved Illustration, or None. Read from the records of that version, not from the stored item alone:
    an exception (skipped or not applicable, with its reason) stands; otherwise the cover must be proved for this very version, so a step recorded done
    before the cover was removed does not pass. A Story published before the step existed has no item and is judged the same way, so its revision must close it."""
    from .story_illustration import DONE as COVER_DONE, NOT_APPLICABLE as COVER_NOT_REQUIRED, cover_evidence, inputs_for_item

    step = next((row for row in rows if row["stepKey"] == ILLUSTRATION_KEY), None)
    if step is not None and step.get("state") in (SKIPPED, NOT_APPLICABLE):
        return None
    found, text = cover_evidence(inputs_for_item(client, item, _metadata_of(item)))
    if found in (COVER_DONE, COVER_NOT_REQUIRED):
        return None
    return text


def rated_problem(client, item: dict[str, Any]) -> str | None:
    """Why the version being published is not rated where the site requires it, or None. Read from the rating on that very version, never from a stored
    answer: a rating is carried onto every new version of a Story, so a republish of a rated Story passes, and clearing the rating makes the next publish
    refuse. There is no exception to record. A Story already published stays published whatever its rating; only a publish or republish is gated."""
    from .story_rating import DONE as RATED_DONE, NOT_APPLICABLE as RATED_NOT_REQUIRED, inputs_for_item, rating_evidence

    found, text = rating_evidence(inputs_for_item(client, item))
    return None if found in (RATED_DONE, RATED_NOT_REQUIRED) else text


def mark_published(client, lineage: str, *, actor_label: str) -> None:
    """After a publish succeeds, the publish step is done. Best effort: the page is live whatever happens here."""
    try:
        existing = {row["stepKey"]: row for row in read_steps(client, lineage)}
        row = existing.get(PUBLISH_KEY)
        if row is not None and row.get("state") != STEP_DONE:
            set_step(client, lineage, PUBLISH_KEY, STEP_DONE, actor={"kind": ACTOR_PERSON, "label": actor_label}, evidence="Story is published")
    except Exception as error:  # noqa: BLE001
        print(f"checklist\tnot updated\t{type(error).__name__}: {str(error)[:160]}", file=sys.stderr)


def steps_for_display(rows: list[dict[str, Any]], lineage: str, procedure: Procedure = DEFAULT_PROCEDURE) -> list[dict[str, Any]]:
    """Each stored step with its title and the command that moves it on, for ``stories next`` and for a panel."""
    shown = []
    for row in rows:
        step = procedure.by_key.get(row["stepKey"])
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
    procedure = Procedure.from_spec(facts.get("procedureSpec"))
    assessment = assess(facts)
    states = {row["key"]: row["state"] for row in assessment["steps"]}
    # A published Story's checklist is a record: it gets its whole checklist once, never a later template step (see sync_checklist).
    missing = [] if (rows and facts["stage"] == "published") else [
        step.key for step in template_steps(procedure) if step.key not in rows and states.get(step.key) != EVIDENCE_NOT_APPLICABLE
        and not (facts["stage"] == "published" and step.key in ADDED_AFTER_PUBLISH_KEYS and states.get(step.key) != DONE)
    ]
    completable = [key for key, row in rows.items() if row["state"] == OPEN and states.get(key) == DONE and not _reopened_by_person(row)]
    if not missing and not completable:
        return None
    if apply:
        return sync_checklist(client, lineage, facts=facts, assessment=assessment)
    return {"created": missing, "completed": [key for key in [*missing, *completable] if states.get(key) == DONE]}


def checklist_lines(shown: list[dict[str, Any]], stale: int = 0) -> list[str]:
    """The stored checklist as tab-separated lines for ``papyrus stories next``: an ``item`` line each, then the progress."""
    if not shown:
        return ["\t".join(["checklist", "none", "no checklist yet; a write to the Story makes one"])]
    lines = []
    for row in shown:
        who = f"{row.get('actorKind')}:{row.get('actorLabel')}" if row.get("actorKind") else ""
        detail = row.get("reason") or row.get("note") or row.get("evidence") or ""
        lines.append("\t".join(["item", row["stepKey"], row["state"], row["title"], who, str(row.get("changedAt") or ""), detail]))
        for note in row.get("notes") or []:
            lines.append("\t".join(["note", row["stepKey"], f"{note.get('actorKind')}:{note.get('actorLabel') or note.get('actorSub')}", str(note.get("at") or ""), str(note.get("text") or "").replace("\n", " ")]))
    lines.append("\t".join(["checklist", "progress", progress_text(summary_of(shown), stale)]))
    return lines
