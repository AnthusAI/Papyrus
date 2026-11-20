"""An Assignment is the request between responsibilities (PPY-51f96f, slice F1 of docs/design/always-on-agents-architecture.md).

When one agent needs another's work (the fact-checker needs a source found, the copy editor needs a figure) it asks for it as an ``Assignment`` on the Story. A
person files the same record. The record is the whole conversation: nothing is sent between agents and no Message is written (Messages come only from people).

* **The request.** ``handoff_handlers.request_work`` (the operation ``handoffs_request``, which the one gate answers for an agent) writes one ``Assignment`` whose type is
  ``responsibility.<responsibility>``: the responsibility asked, as the agent catalogue names it. It sits on the Story (``itemLineageId``), says who asked
  (``createdBy``: ``agent:<id>`` or a person) and why (``summary``), and has an ``AssignmentEvent`` ``created``. An agent that asks again with the same words gets the
  Assignment it already made, whatever has happened to it since, so it asks once; a person's request is always new.
* **The wake.** The Assignment change feed (``change_feeds.py``) turns the insert into one wake for each agent that listens for ``Assignment/created`` with
  ``responsibility`` set to its own. The wake key is ``<agent>|<assignment id>|unversioned|created``: that key is the claim, so the agent runs once for it.
  A reopened Assignment wakes again under a key that names the reopening.
* **The run.** The runner calls ``begin`` before the procedure (the Assignment becomes ``claimed`` by the agent) and ``finish`` after it. ``finish`` closes the
  Assignment from the run's outcome: ``acted`` and ``nothing`` complete it and write the result (the run, its outcome and what it said) as the completion
  event's payload, which is what the Story's reporting trail shows; ``asked`` leaves it claimed, because a person's answer will wake the agent; ``failed`` marks it
  ``failed``, records why on the completion event and raises ONE flag for a person. Nothing retries a failed Assignment: a person reopens it.
* **The answer.** A completed Assignment wakes the agent that asked, and only that agent (the feed's ``completed`` change is addressed to ``createdBy``).
  A person who asked is not woken: the Story shows the result.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from . import review_requests
from .handoff_records import CANCELED, CLAIMED, COMPLETED, FAILED, FINAL, OPEN, TYPE_PREFIX, responsibility_of, type_key  # noqa: F401 - the row shape is read by the change feed too
from .model_attachments import build_json_model_payload_attachment, upload_attachment_body

QUEUE_KEY = "handoff"
RESPONSIBILITY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")   # the form the agent policy document keys a responsibility by
FEED_KEY = "assignments"
DEFAULT_PRIORITY = 50
MAX_WHY_CHARACTERS = 2000
CREATED_EVENT, CLAIM_EVENT, COMPLETE_EVENT, FAIL_EVENT = "created", "claim", "complete", "fail"
#: The run events whose wake belongs to the Assignment: a completion wakes the asker about a different job, so it is not one of these.
WORK_EVENTS = ("assignment.created", "assignment.reopened")
ACTED, NOTHING, ASKED, RUN_FAILED = "acted", "nothing", "asked", "failed"


def is_handoff(row: dict[str, Any]) -> bool:
    return responsibility_of(row) is not None


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest(*parts: str) -> str:
    return hashlib.sha256("␟".join(parts).encode("utf-8")).hexdigest()[:16]


def assignment_id(asker: str, responsibility: str, story: str, why: str, once: str = "") -> str:
    """The same ask has the same id: an agent that asks again gets the Assignment it made. A person's ask carries something unique in ``once``."""
    return f"handoff-{_digest(asker, responsibility, story, why, once)}"


def write_payload(client: Any, owner_id: str, content: dict[str, Any], now: str) -> None:
    built = build_json_model_payload_attachment({"ownerKind": "assignmentEvent", "ownerId": owner_id, "ownerLineageId": owner_id, "role": "metadata", "sortKey": "metadata",
                                                 "content": content, "now": now})
    upload_attachment_body(client, built["attachment"], built["body"])
    client.upsert("ModelAttachment", built["attachment"])


def record_event(client: Any, row: dict[str, Any], event: str, to_status: str, *, actor: str, note: str | None, now: str, payload: dict[str, Any]) -> None:
    event_id = f"assignment-event-{row['id']}-{event}-{_digest(row['id'], event, now, to_status, str(row.get('updatedAt')))[:8]}" if event != CREATED_EVENT else f"assignment-event-{row['id']}-created"
    client.upsert("AssignmentEvent", {"id": event_id, "assignmentId": row["id"], "assignmentTypeKey": row["assignmentTypeKey"], "queueKey": row["queueKey"], "eventType": event,
                                      "fromStatus": row.get("status") if event != CREATED_EVENT else None, "toStatus": to_status, "actorLabel": actor, "note": note, "createdAt": now})
    write_payload(client, event_id, {"source": "handoff", "kind": f"assignment.handoff.{event}", **payload}, now)


def move(client: Any, row: dict[str, Any], status: str, now: str, **fields: Any) -> dict[str, Any]:
    update = {"id": row["id"], "status": status, "queueStatusKey": f"{row['queueKey']}#{status}", "updatedAt": now, **fields}
    client.update_record("Assignment", update)
    return {**row, **update}


# --- the run -------------------------------------------------------------------------------------------------------------------------------------


def assignment_of_request(request: dict[str, Any]) -> str | None:
    """The Assignment a runner request is the work of, or None. Only the wakes made for the responsible agent are (a completion wakes the asker about the same record)."""
    trigger = request.get("trigger") or {}
    subject = (request.get("input") or {}).get("subject") or {}
    if trigger.get("event") not in WORK_EVENTS or subject.get("kind") != "Assignment" or not subject.get("id"):
        return None
    return str(subject["id"])


def begin(client: Any, assignment: str, agent: str, *, now: str | None = None) -> bool:
    """The run's start: an open Assignment becomes claimed by the agent. False when it is no longer open (canceled, or already claimed), which leaves it as it is."""
    row = client.get_record("Assignment", assignment)
    if not row or row.get("status") != OPEN:
        return False
    moment, who = now or utc_now(), f"agent:{agent}"
    record_event(client, row, CLAIM_EVENT, CLAIMED, actor=who, note=None, now=moment, payload={"agent": agent})
    move(client, row, CLAIMED, moment, assigneeType="agent", assigneeId=agent, assigneeKey=who, claimedAt=moment)
    return True


def finish(client: Any, assignment: str, agent: str, *, run_id: str, outcome: str, reason: str | None, summary: str | None, error: str | None, now: str | None = None) -> str | None:
    """The run's end: close the Assignment the agent claimed from how the run ended. Returns the status it now has, or None when the run did not hold it."""
    row = client.get_record("Assignment", assignment)
    who = f"agent:{agent}"
    if not row or row.get("status") != CLAIMED or row.get("assigneeKey") != who:
        return None
    moment = now or utc_now()
    if outcome == ASKED:
        return CLAIMED   # a person's answer wakes the agent again; nothing closes while it waits
    if outcome in (ACTED, NOTHING):
        record_event(client, row, COMPLETE_EVENT, COMPLETED, actor=who, note=summary, now=moment,
               payload={"runId": run_id, "outcome": outcome, "reason": reason, "result": summary, "story": row.get("itemLineageId")})
        move(client, row, COMPLETED, moment, completedAt=moment)
        return COMPLETED
    message = (error or "The run failed.")[:review_requests.MAX_TEXT]
    record_event(client, row, FAIL_EVENT, FAILED, actor=who, note=message, now=moment, payload={"runId": run_id, "outcome": outcome, "reason": reason, "error": message, "story": row.get("itemLineageId")})
    move(client, row, FAILED, moment)
    review_requests.raise_review(
        client, subject={"type": "assignment", "id": assignment}, mode="flag", raised_by=who, request_id=f"handoff-failed-{_digest(assignment, run_id)}",
        reason=f"{agent} could not do the work it was asked for on Story {row.get('itemLineageId')}: {message}", ask="Reopen the Assignment to try again, or cancel it.")
    return FAILED
