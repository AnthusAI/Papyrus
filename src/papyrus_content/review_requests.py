"""Human review points: flags, timed soft reviews and hard approval gates (PPY-ab6a50).

Review is not a story state. Any step can raise a ReviewRequest about any item (a story, a proposal, a
reference, an automation run, a Cyclotron decision, or a batch of those). Three modes:

* ``flag``         informational. Nothing waits. An editor can acknowledge or steer it.
* ``soft_review``  the request stays open until someone handles it: it has no expiry unless the caller passes a
                   deadline. With a deadline, if nobody answers by then it proceeds, and the request records
                   "proceeded without review" (state ``timed_out``). Without one it is never timed out.
* ``hard_gate``    the process never proceeds without an explicit answer. A hard gate has no deadline.

An answer is ``approve``, ``acknowledge`` (the flag form of approve: nothing was approved, the editor saw it), ``reject`` or ``feedback``, with optional feedback text and an optional ``steer``
(``adjust`` or ``not_this_kind``). Feedback and steering are stored on the request and handed to whatever raised
it: that step reads them back with ``steering_for`` and records that it used them with ``mark_applied``
("You steered X, applied in run Y").

**The deadline is a follow-up timer** (PPY-9b8e59). An open soft review with a deadline carries ``dueAt`` (its deadline); nothing
else does. Raising it sets one follow-up timer (``review_deadline_timers``); an answer or a withdrawal clears ``dueAt`` and the timer.
At the deadline the timer's wake runs ``on_deadline_wake``, which re-reads the request and, if it still waits for exactly that time,
records "proceeded without review" (state ``timed_out``) in one conditional write. Nothing is checked on read and nothing polls.

**Reads are by index.** Every request carries ``reviewStateKey`` (``review#<state>``, the tenant in front on a shared stack), the
partition of the index ``reviewRequestsByState``: ``list_reviews`` reads the partition of the state it is asked for (each state's
own partition when it is asked for none), and no read lists the table.

The client is the authoring client (``get_record``, ``create_record``, ``update_record``, ``list_by_index``), so
the CLI (user or IAM operator credentials), automations and procedures (their managed IAM roles) and the tests
share one implementation. Who may answer is enforced by the backend model's authorization (editors and admins);
``answer_review`` also refuses a caller whose roles are known and lack both.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import follow_up_timers
from .staff_groups import STAFF_GROUPS, has_editor_rights
from .tenant_knowledge_keys import global_key

MODES = ("flag", "soft_review", "hard_gate")
STATES = ("open", "answered", "timed_out", "withdrawn")
DECISIONS = ("approve", "acknowledge", "reject", "feedback")
STEERS = ("adjust", "not_this_kind")
ANSWERING_ROLES = STAFF_GROUPS
RECIPIENT_SCOPES = ("default", "mode", "automation")
RECIPIENT_ROLES = ("editor", "admin")
PROCEEDED_WITHOUT_REVIEW = "proceeded without review"
SUBJECT_TYPES = ("story", "proposal", "reference", "automation_run", "cyclotron_decision", "batch", "label", "delivery", "review_request")   # a label: the id is the thing's entity key, section#id or concept#lineage; a delivery: the Delivery id; a review_request: an overdue deadline
REQUEST_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
MAX_TEXT = 2000
MAX_HISTORY = 50
STATE_INDEX = "reviewRequestsByState"
STATE_KEY_PREFIX = "review#"


class ReviewError(ValueError):
    """A request the review rules refuse; the message is safe to show an editor."""


class ReviewStillOpen(RuntimeError):
    """A wait ended without an answer and without permission to proceed (a hard gate, or a wait cap)."""

    def __init__(self, request: dict[str, Any]):
        super().__init__(f"review {request['id']} is still open ({request['mode']}); it cannot proceed without an answer.")
        self.request = request


# --- small helpers --------------------------------------------------------------------------------------


def review_state_key(state: str) -> str:
    """The partition of the state index for one state, as this stack stores it (the tenant in front on a shared stack)."""
    if state not in STATES:
        raise ReviewError(f"state must be one of {', '.join(STATES)}.")
    return global_key(f"{STATE_KEY_PREFIX}{state}")


def due_at_of(request: dict[str, Any]) -> str | None:
    """The time an open soft review's timer wakes for: its deadline. None for anything else, so the row carries no ``dueAt``."""
    if request.get("mode") == "soft_review" and request.get("state") == "open" and request.get("deadline"):
        return str(request["deadline"])
    return None


def state_fields(state: str) -> dict[str, Any]:
    """What every write that leaves a request in ``state`` other than open carries: the state, its index key and no due time."""
    return {"state": state, "reviewStateKey": review_state_key(state), "dueAt": None}


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default if value is None else value


def _text(value: Any, label: str, *, required: bool = False, limit: int = MAX_TEXT) -> str | None:
    cleaned = str(value).strip() if value is not None and value is not True else ""
    if not cleaned:
        if required:
            raise ReviewError(f"{label} is required.")
        return None
    if len(cleaned) > limit:
        raise ReviewError(f"{label} is longer than {limit} characters.")
    return cleaned


def _subject(subject: Any) -> dict[str, str]:
    if not isinstance(subject, dict):
        raise ReviewError("subject must be an object with a type and an id.")
    subject_type = _text(subject.get("type"), "subject.type", required=True, limit=64)
    subject_id = _text(subject.get("id"), "subject.id", required=True, limit=256)
    return {"type": subject_type, "id": subject_id}


def _links(links: Any) -> list[dict[str, str]]:
    if links in (None, ""):
        return []
    if not isinstance(links, list):
        raise ReviewError("links must be a list of {label, url or subject}.")
    cleaned = []
    for link in links:
        if not isinstance(link, dict):
            raise ReviewError("each link must be an object.")
        entry = {key: str(link[key]) for key in ("label", "url", "type", "id") if link.get(key)}
        if not entry.get("url") and not entry.get("id"):
            raise ReviewError("each link needs a url, or a type and an id.")
        cleaned.append(entry)
    return cleaned


def _history(row_history: Any, event: str, *, by: str, at: str, note: str | None = None) -> list[dict[str, Any]]:
    entries = list(_parse(row_history, []) or [])
    entries.append({key: value for key, value in (("at", at), ("event", event), ("by", by), ("note", note)) if value})
    return entries[-MAX_HISTORY:]


# --- the record --------------------------------------------------------------------------------------------


def read_review(row: dict[str, Any]) -> dict[str, Any]:
    """A stored row as the request the CLI and the library return. Plain words for the state a person sees."""
    answer = _parse(row.get("answer"), None)
    state = row.get("state")
    return {
        "id": row.get("id"), "subject": _parse(row.get("subject"), {}), "mode": row.get("mode"),
        "reason": row.get("reason"), "ask": row.get("ask"), "raisedBy": row.get("raisedBy"),
        "raisedAt": row.get("raisedAt"), "deadline": row.get("deadline"), "state": state,
        "answer": answer, "links": _parse(row.get("links"), []), "history": _parse(row.get("history"), []),
        "appliedIn": _parse(row.get("appliedIn"), None), "updatedAt": row.get("updatedAt"),
        "outcome": outcome_of(state, answer),
    }


def outcome_of(state: str | None, answer: dict[str, Any] | None) -> str:
    """What the raising process should do: a one-word answer to "may I continue, and with what"."""
    if state == "answered" and answer:
        return {"approve": "approved", "acknowledge": "approved", "reject": "rejected", "feedback": "feedback"}.get(answer.get("decision"), "answered")
    if state == "timed_out":
        return "proceeded_without_review"
    if state == "withdrawn":
        return "withdrawn"
    return "waiting"


def _stored(request: dict[str, Any]) -> dict[str, Any]:
    payload = {key: request.get(key) for key in ("id", "mode", "reason", "ask", "raisedBy", "raisedAt", "deadline", "state", "updatedAt")}
    payload["reviewStateKey"] = review_state_key(request["state"])
    payload["dueAt"] = due_at_of(request)
    for key in ("subject", "answer", "links", "history", "appliedIn"):
        payload[key] = json.dumps(request[key]) if request.get(key) is not None else None
    return {key: value for key, value in payload.items() if value is not None}


def raise_review(client, *, subject: dict[str, Any], mode: str, reason: str, raised_by: str, ask: str | None = None,
                 deadline: str | None = None, deadline_days: float | None = None, links: Any = None,
                 request_id: str | None = None, now: datetime | None = None, deadline_timers: Any = None) -> dict[str, Any]:
    """Raise a review request. A given ``request_id`` makes the call idempotent: raising it again returns the existing request.

    A soft review has no deadline unless the caller passes one (``deadline`` or ``deadline_days``): by default it stays open until
    someone handles it and is never timed out. A flag and a hard gate take none. A deadline is a follow-up timer, so a soft review
    with one needs the site's ``deadline_timers`` (``review_deadline_timers.ReviewDeadlineTimers``); it is refused without them.
    A deadline is kept to the whole second, the precision of a timer."""
    if mode not in MODES:
        raise ReviewError(f"mode must be one of {', '.join(MODES)}.")
    if request_id is not None and not REQUEST_ID.match(request_id):
        raise ReviewError("id must be lowercase letters, digits, dots, dashes or underscores.")
    if request_id:
        existing = client.get_record("ReviewRequest", request_id)
        if existing:
            return read_review(existing)
    moment = now or datetime.now(timezone.utc)
    if mode == "soft_review":
        if deadline is not None:
            if parse_time(deadline) is None:
                raise ReviewError("deadline must be an ISO date and time.")
            deadline_at = timer_time(parse_time(deadline))
        elif deadline_days is not None:
            if deadline_days <= 0:
                raise ReviewError("deadline_days must be more than zero.")
            deadline_at = timer_time(moment + timedelta(days=deadline_days))
        else:
            deadline_at = None  # no expiry: the request stays open until someone handles it
    else:
        if deadline is not None or deadline_days is not None:
            raise ReviewError(f"a {mode.replace('_', ' ')} has no deadline: only a soft review waits until one.")
        deadline_at = None
    if deadline_at is not None and deadline_timers is None:
        raise ReviewError("a soft review with a deadline sets a follow-up timer for it, and no timers were given: pass the site's deadline timers.")
    raised_at = now_iso(moment)
    by = _text(raised_by, "raisedBy", required=True, limit=200)
    request = {
        "id": request_id or f"rr-{uuid.uuid4().hex[:16]}",
        "subject": _subject(subject), "mode": mode, "reason": _text(reason, "reason", required=True),
        "ask": _text(ask, "ask"), "raisedBy": by, "raisedAt": raised_at, "deadline": deadline_at,
        "state": "open", "answer": None, "links": _links(links),
        "history": _history(None, "raised", by=by, at=raised_at, note=mode), "appliedIn": None, "updatedAt": raised_at,
    }
    stored = _stored(request)
    client.create_record("ReviewRequest", stored)
    if stored.get("dueAt"):
        deadline_timers.sync(stored)   # after the row exists, so the wake always finds what it was set for
    return read_review(stored)


def get_review(client, request_id: str) -> dict[str, Any]:
    row = client.get_record("ReviewRequest", request_id)
    if not row:
        raise ReviewError(f"review request {request_id} does not exist.")
    return read_review(row)


def rows_in_state(client, state: str) -> list[dict[str, Any]]:
    """Every stored request in one state: one key-condition query on the state index."""
    return client.list_by_index(STATE_INDEX, review_state_key(state))


def list_reviews(client, *, state: str | None = None, mode: str | None = None, raised_by: str | None = None,
                 subject_id: str | None = None) -> list[dict[str, Any]]:
    """Requests newest first, read from the state index: the partition of ``state``, or each state's own partition when none is named."""
    found = [read_review(row) for named in ((state,) if state else STATES) for row in rows_in_state(client, named)]
    return sorted((request for request in found
                   if (mode is None or request["mode"] == mode)
                   and (raised_by is None or request["raisedBy"] == raised_by)
                   and (subject_id is None or request["subject"].get("id") == subject_id)),
                  key=lambda request: request["raisedAt"] or "", reverse=True)


# --- the deadline ------------------------------------------------------------------------------------------


def timer_time(moment: datetime) -> str:
    """A time as a timer and ``dueAt`` hold it: a UTC instant to the whole second."""
    return moment.astimezone(timezone.utc).strftime(follow_up_timers.TIME_FORMAT)


def on_deadline_wake(client, wake_key: str, *, now: datetime | None = None) -> dict[str, Any]:
    """What a soft review's deadline timer does when it fires: re-read the request and, if it still waits for exactly the time the wake names,
    record "proceeded without review" (``timed_out``) in one write conditional on that. An answer, a withdrawal or a deleted request means the wake does nothing.

    Returns ``{"action": "timed_out" | "nothing", "requestId", "reason"}``."""
    record_id = follow_up_timers.record_id_of(wake_key)
    row = client.get_record("ReviewRequest", record_id)
    waits = follow_up_timers.check_wake(wake_key, row)
    if not waits["waiting"]:
        return {"action": "nothing", "requestId": record_id, "reason": waits["reason"]}
    at = now_iso(now)
    written = client.update_record_if("ReviewRequest", {
        "id": record_id, **state_fields("timed_out"), "updatedAt": at,
        "history": json.dumps(_history(row.get("history"), "timed_out", by="system", at=at, note=PROCEEDED_WITHOUT_REVIEW)),
    }, {"state": {"eq": "open"}, "dueAt": {"eq": waits["dueAt"]}})
    if not written:
        return {"action": "nothing", "requestId": record_id, "reason": "Nothing to do: the request changed while the deadline was being recorded."}
    return {"action": "timed_out", "requestId": record_id, "reason": None}


def _clear_deadline(deadline_timers: Any, request: dict[str, Any]) -> None:
    """An answered or withdrawn request has no due time: its entry is deleted when the caller holds the site's timers. A caller without them (the console)
    leaves the entry to fire once, and its wake does nothing, because the request no longer carries the time it names (``follow_up_timers.check_wake``)."""
    if deadline_timers is not None and due_at_of(request):
        deadline_timers.sync({"id": request["id"], "dueAt": None})


# --- answering, withdrawing, steering -----------------------------------------------------------------------


def answer_review(client, request_id: str, *, decision: str, by: str, feedback: str | None = None, steer: str | None = None,
                  roles: list[str] | None = None, now: datetime | None = None, deadline_timers: Any = None) -> dict[str, Any]:
    """Approve, reject, or give feedback (with an optional steer). Only an open request can be answered."""
    if roles is not None and not has_editor_rights(roles):
        raise ReviewError("only editors and admins can answer a review request.")
    if decision not in DECISIONS:
        raise ReviewError(f"decision must be one of {', '.join(DECISIONS)}.")
    if steer is not None and steer not in STEERS:
        raise ReviewError(f"steer must be one of {', '.join(STEERS)}.")
    note = _text(feedback, "feedback")
    if decision == "feedback" and not note and not steer:
        raise ReviewError("feedback needs some text, or a steer.")
    moment = now or datetime.now(timezone.utc)
    request = get_review(client, request_id)
    if request["state"] != "open":
        suffix = f" ({PROCEEDED_WITHOUT_REVIEW})" if request["state"] == "timed_out" else ""
        raise ReviewError(f"review request {request_id} is {request['state'].replace('_', ' ')}{suffix}; it can no longer be answered.")
    if decision == "acknowledge" and request["mode"] != "flag":
        raise ReviewError("only a flag is acknowledged; a soft review or hard gate is approved or rejected.")
    at = now_iso(moment)
    answer = {"decision": decision, "feedback": note, "steer": steer, "by": _text(by, "by", required=True, limit=200), "at": at}
    client.update_record("ReviewRequest", {
        "id": request_id, **state_fields("answered"), "answer": json.dumps(answer), "updatedAt": at,
        "history": json.dumps(_history(request["history"], "answered", by=answer["by"], at=at, note=decision)),
    })
    _clear_deadline(deadline_timers, request)
    return get_review(client, request_id)


def withdraw_review(client, request_id: str, *, by: str, note: str | None = None, now: datetime | None = None, deadline_timers: Any = None) -> dict[str, Any]:
    """The raiser takes the request back (the question no longer applies). Only an open request can be withdrawn."""
    moment = now or datetime.now(timezone.utc)
    request = get_review(client, request_id)
    if request["state"] != "open":
        raise ReviewError(f"review request {request_id} is {request['state'].replace('_', ' ')}; it can no longer be withdrawn.")
    at = now_iso(moment)
    client.update_record("ReviewRequest", {
        "id": request_id, **state_fields("withdrawn"), "updatedAt": at,
        "history": json.dumps(_history(request["history"], "withdrawn", by=by, at=at, note=_text(note, "note"))),
    })
    _clear_deadline(deadline_timers, request)
    return get_review(client, request_id)


def steering_for(client, *, raised_by: str | None = None, subject_type: str | None = None, subject_id: str | None = None,
                 include_applied: bool = False) -> list[dict[str, Any]]:
    """What editors said about requests this step raised: the generic way to read steering back.

    Returns answered requests that carry feedback or a steer (or a rejection) and that no run has recorded using yet."""
    found = []
    for request in list_reviews(client, state="answered", raised_by=raised_by):
        if subject_type and request["subject"].get("type") != subject_type:
            continue
        if subject_id and request["subject"].get("id") != subject_id:
            continue
        answer = request["answer"] or {}
        if not (answer.get("feedback") or answer.get("steer") or answer.get("decision") == "reject"):
            continue
        if request["appliedIn"] and not include_applied:
            continue
        found.append({"requestId": request["id"], "subject": request["subject"], "reason": request["reason"],
                      "decision": answer.get("decision"), "feedback": answer.get("feedback"), "steer": answer.get("steer"),
                      "by": answer.get("by"), "at": answer.get("at"), "appliedIn": request["appliedIn"]})
    return sorted(found, key=lambda entry: entry["at"] or "")


def mark_applied(client, request_id: str, *, run_id: str, by: str, note: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Record that a run used the steering on this request. The console shows "You steered X, applied in run Y"."""
    request = get_review(client, request_id)
    if request["state"] != "answered":
        raise ReviewError(f"review request {request_id} was not answered, so there is no steering to apply.")
    if request["appliedIn"]:
        return request
    at = now_iso(now)
    applied = {"runId": _text(run_id, "runId", required=True, limit=200), "by": by, "at": at, "note": _text(note, "note")}
    client.update_record("ReviewRequest", {
        "id": request_id, "appliedIn": json.dumps(applied), "updatedAt": at,
        "history": json.dumps(_history(request["history"], "applied", by=by, at=at, note=f"run {applied['runId']}")),
    })
    return get_review(client, request_id)


# --- waiting (what a CLI-run process calls) -------------------------------------------------------------------


def wait_for_review(client, request_id: str, *, poll_seconds: float = 30.0, max_wait_seconds: float | None = None,
                    sleep: Callable[[float], None] = time.sleep,
                    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict[str, Any]:
    """Block the caller as the request's mode says. Returns the request; its ``outcome`` says what to do next.

    * flag:         returns at once with outcome ``waiting`` (nothing waits; read steering later with ``steering_for``).
    * soft_review:  polls until answered, or until its deadline timer has recorded it as timed out, then returns outcome
                    ``proceeded_without_review``.
    * hard_gate:    polls until answered or withdrawn. It never returns ``proceeded_without_review``. If
                    ``max_wait_seconds`` runs out first it raises ReviewStillOpen and the gate stays open.
    A ``max_wait_seconds`` on a soft review that ends before its deadline also raises ReviewStillOpen."""
    started = clock()
    while True:
        request = get_review(client, request_id)
        if request["mode"] == "flag" or request["state"] != "open":
            return request
        if max_wait_seconds is not None and (clock() - started).total_seconds() >= max_wait_seconds:
            raise ReviewStillOpen(request)
        sleep(poll_seconds)


def review_gate(client, *, wait: bool = True, poll_seconds: float = 30.0, max_wait_seconds: float | None = None,
                sleep: Callable[[float], None] = time.sleep, **raise_arguments: Any) -> dict[str, Any]:
    """Raise a review and (unless ``wait`` is false) wait for it by its mode. The one call most procedures need."""
    request = raise_review(client, **raise_arguments)
    if not wait:
        return request
    return wait_for_review(client, request["id"], poll_seconds=poll_seconds, max_wait_seconds=max_wait_seconds, sleep=sleep)


# --- the idea pipeline hook ---------------------------------------------------------------------------------------


def raise_batch_review(client, *, raised_by: str, batch_id: str, idea_ids: list[str], noun: str = "story idea",
                       deadline_days: float | None = None, links: Any = None, now: datetime | None = None, link_type: str = "story",
                       extend: bool = False, deadline_timers: Any = None) -> dict[str, Any]:
    """ONE soft review for a run that produced a batch of generated story ideas: "N new story ideas to review".

    The subject is the batch; each idea is a link (``link_type="story"``: the lineage id of the Item at the ``idea`` stage, which the console shows in
    the Idea column of the Stories board; an idea kept only as a local JSON file is linked as ``"idea"``, which the console cannot open). Editors decide the
    ideas on the board: moving one forward accepts it, moving it to spiked with a reason declines it. Idempotent per ``batch_id``, so a re-run of the same
    synthesis does not raise a second request. Feedback comes back through ``steering_for(client, raised_by=raised_by)``.

    With ``extend`` a batch that is still open takes the new ideas into its links and its count instead (a plan whose ideas are filed one step at a time
    raises its request with the first idea and adds the rest); one already answered is left as it is, the ideas being on the board in any case."""
    if not idea_ids:
        raise ReviewError("a batch review needs at least one idea.")
    count = len(idea_ids)
    plural = noun if count == 1 else f"{noun}s"
    safe = re.sub(r"[^a-z0-9._-]+", "-", batch_id.lower()).strip("-")[:100]
    entries = [{"type": link_type, "id": idea_id, "label": f"{noun} {index}"} for index, idea_id in enumerate(idea_ids, 1)]
    existing = client.get_record("ReviewRequest", f"rr-batch-{safe}") if extend else None
    if existing:
        return _extend_batch(client, existing, entries, noun, now)
    return raise_review(
        client, subject={"type": "batch", "id": batch_id}, mode="soft_review", raised_by=raised_by,
        reason=f"{count} new {plural} to review",
        ask="Move an idea forward to accept it, or move it to Spiked with a reason to decline it. Open the Idea column of the Stories board. A reason tells the idea pipeline what you do not want.",
        deadline_days=deadline_days, links=[*entries, *(_links(links))], request_id=f"rr-batch-{safe}", now=now, deadline_timers=deadline_timers)


def _extend_batch(client, row: dict[str, Any], entries: list[dict[str, str]], noun: str, now: datetime | None) -> dict[str, Any]:
    request = read_review(row)
    known = {(link.get("type"), link.get("id")) for link in request["links"]}
    added = [entry for entry in entries if (entry["type"], entry["id"]) not in known]
    if request["state"] != "open" or not added:
        return request
    links = [*request["links"], *({**entry, "label": f"{noun} {len(request['links']) + position}"} for position, entry in enumerate(added, 1))]
    count = len([link for link in links if link.get("type") == entries[0]["type"]])
    at = now_iso(now)
    client.update_record("ReviewRequest", {
        "id": request["id"], "links": json.dumps(links), "reason": f"{count} new {noun if count == 1 else noun + 's'} to review", "updatedAt": at,
        "history": json.dumps(_history(request["history"], "ideas_added", by=request["raisedBy"], at=at, note=f"{len(added)} more")),
    })
    return read_review(client.get_record("ReviewRequest", request["id"]) or row)


# --- who is told ---------------------------------------------------------------------------------------------------


def set_recipient_rule(client, *, scope: str, key: str | None, roles: list[str], emails: list[str], by: str,
                       now: datetime | None = None) -> dict[str, Any]:
    """Write a recipient rule. ``scope`` is default (no key), mode (key = a mode) or automation (key = an automation id)."""
    if scope not in RECIPIENT_SCOPES:
        raise ReviewError(f"scope must be one of {', '.join(RECIPIENT_SCOPES)}.")
    if scope == "default" and key:
        raise ReviewError("the default rule has no key.")
    if scope == "mode" and key not in MODES:
        raise ReviewError(f"a mode rule needs a key that is one of {', '.join(MODES)}.")
    if scope == "automation" and not _text(key, "key"):
        raise ReviewError("an automation rule needs the automation id as its key.")
    bad = [role for role in roles if role not in RECIPIENT_ROLES]
    if bad:
        raise ReviewError(f"roles must be {' or '.join(RECIPIENT_ROLES)}: {', '.join(bad)}.")
    for email in emails:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ReviewError(f"{email!r} is not an email address.")
    record = {"id": scope if scope == "default" else f"{scope}.{key}", "scope": scope, "key": key, "roles": sorted(set(roles)),
              "emails": sorted(set(emails)), "updatedBy": by, "updatedAt": now_iso(now)}
    payload = {name: value for name, value in record.items() if value is not None}
    if client.get_record("ReviewRecipientRule", record["id"]):
        client.update_record("ReviewRecipientRule", payload)
    else:
        client.create_record("ReviewRecipientRule", payload)
    return record


def resolve_recipients(client, *, mode: str, automation: str | None = None, site_owner: str | None = None) -> dict[str, Any]:
    """Who to tell about a request of this mode from this automation. The most specific rule wins:
    the automation's rule, then the mode's, then the default rule, then the site owner (the ``site_owner`` argument or
    ``PAPYRUS_SITE_OWNER_EMAIL``), and with no owner set, the site's admins. Editors and admins named by a rule are
    the active holders of that role in the site's user list; extra emails are added as written."""
    chosen, source = None, "site_owner"
    for rule_id, label in ((f"automation.{automation}" if automation else None, f"automation {automation}"),
                           (f"mode.{mode}", f"mode {mode}"), ("default", "default")):
        rule = client.get_record("ReviewRecipientRule", rule_id) if rule_id else None   # a rule's id is its scope and key, so each is one read
        if rule:
            chosen, source = rule, label
            break
    if chosen is None:
        owner = site_owner or os.environ.get("PAPYRUS_SITE_OWNER_EMAIL")
        if owner:
            return {"emails": [owner], "source": "site_owner", "roles": []}
        chosen, source = {"roles": ["admin"], "emails": []}, "site_owner (no owner set: the admins)"
    roles = list(chosen.get("roles") or [])
    emails = set(chosen.get("emails") or [])
    if roles:
        for row in client.list_records("UserRoleAssignment"):
            if row.get("role") in roles and row.get("status") == "active" and row.get("email"):
                emails.add(row["email"])
    return {"emails": sorted(emails), "source": source, "roles": roles}


# --- the state index, once ------------------------------------------------------------------------------------------------


def backfill_state_index(client, *, apply: bool) -> dict[str, Any]:
    """Give every request stored before the state index its ``reviewStateKey`` and, for an open soft review with a deadline, its ``dueAt``, so the index holds
    every request. The one read of the whole model, run once when a site takes the index (docs/releasing.md); every read afterwards is by index. Requests raised
    before the index have no follow-up timer: their deadlines are Overdue (overdue.py) and recovered through the same wake."""
    from . import request_meter

    with request_meter.sweep("reviews index-backfill"):
        rows = client.list_records("ReviewRequest")
    missing = []
    for row in rows:
        request = read_review(row)
        wanted = {"reviewStateKey": review_state_key(request["state"]), "dueAt": due_at_of(request)}
        if wanted["dueAt"] is not None:
            wanted["dueAt"] = timer_time(parse_time(wanted["dueAt"]))
        if any(row.get(name) != value for name, value in wanted.items()):
            missing.append({"id": row["id"], **wanted})
    if apply:
        for change in missing:
            client.update_record("ReviewRequest", change)
    return {"applied": apply, "requests": [change["id"] for change in missing]}


# --- the command line ---------------------------------------------------------------------------------------------------


def _line(request: dict[str, Any]) -> str:
    subject = request["subject"]
    if request["mode"] == "soft_review" and request["state"] == "open":
        when = f"proceeds {request['deadline']}" if request["deadline"] else "open until handled"
    else:
        when = request["outcome"]
    return "\t".join(["reviews", request["id"], request["mode"], request["state"], f"{subject.get('type')}:{subject.get('id')}", when, request["reason"] or ""])


def review_lines(request: dict[str, Any]) -> list[str]:
    lines = [_line(request), f"ask\t{request['ask'] or '-'}\nraisedBy\t{request['raisedBy']} at {request['raisedAt']}"]
    if request["answer"]:
        answer = request["answer"]
        lines.append(f"answer\t{answer['decision']}\t{answer.get('steer') or '-'}\t{answer.get('feedback') or '-'}\t{answer['by']} at {answer['at']}")
    if request["appliedIn"]:
        lines.append(f"applied\trun {request['appliedIn']['runId']} at {request['appliedIn']['at']}")
    for entry in request["history"]:
        lines.append(f"history\t{entry['at']}\t{entry['event']}\t{entry.get('by', '')}\t{entry.get('note', '')}")
    return lines


def operator_reviews_list(client, *, state=None, mode=None, raised_by=None, subject_type=None, subject_id=None) -> dict[str, Any]:
    found = list_reviews(client, state=state, mode=mode, raised_by=raised_by, subject_id=subject_id)
    return {"reviews": [request for request in found if subject_type is None or request["subject"].get("type") == subject_type]}


def operator_review_answer(client, request_id: str, *, decision: str, feedback: str | None = None, steer: str | None = None) -> dict[str, Any]:
    return {"review": answer_review(client, request_id, decision=decision, by=os.environ.get("PAPYRUS_ACTOR_LABEL") or "papyrus-cli", feedback=feedback, steer=steer)}


def run_command(command: str, flags: list[str]) -> None:
    """`papyrus reviews raise|withdraw|wait|steering|applied|recipients|index-backfill`; list, show and answer run through the command registry."""
    from .graphql_authoring import create_authoring_client
    from .options import parse_boolean_option, parse_options

    options = parse_options(flags)
    as_json = parse_boolean_option(options.get("json"), False, "--json")
    client = create_authoring_client()[0]
    actor = os.environ.get("PAPYRUS_ACTOR_LABEL") or "papyrus-cli"

    def show(payload: Any, line: str | None = None) -> None:
        if as_json:
            print(json.dumps({"ok": True, "command": f"reviews {command}", "result": payload}, indent=2, default=str))
        elif line is not None:
            print(line)

    def need(name: str) -> str:
        value = options.get(name)
        if not isinstance(value, str):
            raise ReviewError(f"papyrus reviews {command} needs --{name}.")
        return value

    if command == "raise":
        subject = {"type": need("subject-type"), "id": need("subject-id")}
        links = json.loads(options["links"]) if isinstance(options.get("links"), str) else None
        arguments = dict(subject=subject, mode=need("mode"), reason=need("reason"), ask=options.get("ask") if isinstance(options.get("ask"), str) else None,
                         raised_by=options.get("raised-by") if isinstance(options.get("raised-by"), str) else actor,
                         deadline=options.get("deadline") if isinstance(options.get("deadline"), str) else None,
                         deadline_days=float(options["deadline-days"]) if isinstance(options.get("deadline-days"), str) else None,
                         links=links, request_id=options.get("id") if isinstance(options.get("id"), str) else None)
        if arguments["mode"] == "soft_review" and (arguments["deadline"] is not None or arguments["deadline_days"] is not None):
            from .review_deadline_timers import ReviewDeadlineTimers

            arguments["deadline_timers"] = ReviewDeadlineTimers.from_environment(os.environ, appsync_endpoint=client.endpoint)
        if parse_boolean_option(options.get("wait"), False, "--wait"):
            request = review_gate(client, poll_seconds=float(options.get("poll-seconds") or 30),
                                  max_wait_seconds=float(options["max-wait-seconds"]) if isinstance(options.get("max-wait-seconds"), str) else None,
                                  **arguments)
        else:
            request = raise_review(client, **arguments)
        show(request, _line(request))
    elif command == "withdraw":
        request = withdraw_review(client, need("id"), by=actor, note=options.get("note") if isinstance(options.get("note"), str) else None)
        show(request, _line(request))
    elif command == "wait":
        request = wait_for_review(client, need("id"), poll_seconds=float(options.get("poll-seconds") or 30),
                                  max_wait_seconds=float(options["max-wait-seconds"]) if isinstance(options.get("max-wait-seconds"), str) else None)
        show(request, _line(request))
    elif command == "steering":
        found = steering_for(client, raised_by=options.get("raised-by") if isinstance(options.get("raised-by"), str) else None,
                             include_applied=parse_boolean_option(options.get("all"), False, "--all"))
        show(found)
        if not as_json:
            for entry in found:
                print("\t".join(["steering", entry["requestId"], entry["decision"] or "", entry["steer"] or "-", entry["feedback"] or "-"]))
    elif command == "applied":
        request = mark_applied(client, need("id"), run_id=need("run"), by=actor)
        show(request, _line(request))
    elif command == "recipients":
        if parse_boolean_option(options.get("set"), False, "--set"):
            rule = set_recipient_rule(
                client, scope=need("scope"), key=options.get("key") if isinstance(options.get("key"), str) else None,
                roles=[part for part in str(options.get("roles") or "").split(",") if part],
                emails=[part for part in str(options.get("emails") or "").split(",") if part], by=actor)
            show(rule, f"reviews\trecipients\t{rule['id']}\troles={','.join(rule['roles']) or '-'}\temails={len(rule['emails'])}")
        else:
            resolved = resolve_recipients(client, mode=options.get("mode") if isinstance(options.get("mode"), str) else "hard_gate",
                                          automation=options.get("automation") if isinstance(options.get("automation"), str) else None)
            show(resolved, f"reviews\trecipients\t{resolved['source']}\t{len(resolved['emails'])} address(es)")
    elif command == "index-backfill":
        changed = backfill_state_index(client, apply=parse_boolean_option(options.get("apply"), False, "--apply"))
        show(changed, f"reviews\tindex-backfill\t{len(changed['requests'])} request(s) {'written' if changed['applied'] else 'to write (pass --apply)'}")
    else:
        raise ValueError(f"Unsupported papyrus reviews command: {command}")
