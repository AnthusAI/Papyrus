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

Deadline mechanism, v0: **checked on read.** ``expire_due`` marks every open soft review whose deadline has
passed as ``timed_out``; ``list_reviews``, ``get_review``, ``answer_review`` and ``wait_for_review`` all call it
first, and so does the console when it loads. No scheduled function is needed because nothing else has to
happen at the deadline: the raising process decides to proceed when it reads the timed-out state, and the
console shows the state the moment someone looks. A scheduled sweep is a later addition for email at the
deadline.

The client is the authoring client (``get_record``, ``create_record``, ``update_record``, ``list_records``), so
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

MODES = ("flag", "soft_review", "hard_gate")
STATES = ("open", "answered", "timed_out", "withdrawn")
DECISIONS = ("approve", "acknowledge", "reject", "feedback")
STEERS = ("adjust", "not_this_kind")
ANSWERING_ROLES = frozenset({"editor", "admin"})
RECIPIENT_SCOPES = ("default", "mode", "automation")
RECIPIENT_ROLES = ("editor", "admin")
PROCEEDED_WITHOUT_REVIEW = "proceeded without review"
SUBJECT_TYPES = ("story", "proposal", "reference", "automation_run", "cyclotron_decision", "batch")
REQUEST_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
MAX_TEXT = 2000
MAX_HISTORY = 50


class ReviewError(ValueError):
    """A request the review rules refuse; the message is safe to show an editor."""


class ReviewStillOpen(RuntimeError):
    """A wait ended without an answer and without permission to proceed (a hard gate, or a wait cap)."""

    def __init__(self, request: dict[str, Any]):
        super().__init__(f"review {request['id']} is still open ({request['mode']}); it cannot proceed without an answer.")
        self.request = request


# --- small helpers --------------------------------------------------------------------------------------


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
    for key in ("subject", "answer", "links", "history", "appliedIn"):
        payload[key] = json.dumps(request[key]) if request.get(key) is not None else None
    return {key: value for key, value in payload.items() if value is not None}


def raise_review(client, *, subject: dict[str, Any], mode: str, reason: str, raised_by: str, ask: str | None = None,
                 deadline: str | None = None, deadline_days: float | None = None, links: Any = None,
                 request_id: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Raise a review request. A given ``request_id`` makes the call idempotent: raising it again returns the existing request.

    A soft review has no deadline unless the caller passes one (``deadline`` or ``deadline_days``): by default it stays open until
    someone handles it and is never timed out. A flag and a hard gate take none."""
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
            deadline_at = now_iso(parse_time(deadline))
        elif deadline_days is not None:
            if deadline_days <= 0:
                raise ReviewError("deadline_days must be more than zero.")
            deadline_at = now_iso(moment + timedelta(days=deadline_days))
        else:
            deadline_at = None  # no expiry: the request stays open until someone handles it
    else:
        if deadline is not None or deadline_days is not None:
            raise ReviewError(f"a {mode.replace('_', ' ')} has no deadline: only a soft review waits until one.")
        deadline_at = None
    raised_at = now_iso(moment)
    by = _text(raised_by, "raisedBy", required=True, limit=200)
    request = {
        "id": request_id or f"rr-{uuid.uuid4().hex[:16]}",
        "subject": _subject(subject), "mode": mode, "reason": _text(reason, "reason", required=True),
        "ask": _text(ask, "ask"), "raisedBy": by, "raisedAt": raised_at, "deadline": deadline_at,
        "state": "open", "answer": None, "links": _links(links),
        "history": _history(None, "raised", by=by, at=raised_at, note=mode), "appliedIn": None, "updatedAt": raised_at,
    }
    client.create_record("ReviewRequest", _stored(request))
    return read_review(_stored(request))


def get_review(client, request_id: str, *, sweep: bool = True, now: datetime | None = None) -> dict[str, Any]:
    row = client.get_record("ReviewRequest", request_id)
    if not row:
        raise ReviewError(f"review request {request_id} does not exist.")
    if sweep:
        _expire_row(client, row, now or datetime.now(timezone.utc))
        row = client.get_record("ReviewRequest", request_id) or row
    return read_review(row)


def list_reviews(client, *, state: str | None = None, mode: str | None = None, raised_by: str | None = None,
                 subject_id: str | None = None, sweep: bool = True, now: datetime | None = None) -> list[dict[str, Any]]:
    if sweep:
        expire_due(client, now=now)
    found = [read_review(row) for row in client.list_records("ReviewRequest")]
    return sorted((request for request in found
                   if (state is None or request["state"] == state) and (mode is None or request["mode"] == mode)
                   and (raised_by is None or request["raisedBy"] == raised_by)
                   and (subject_id is None or request["subject"].get("id") == subject_id)),
                  key=lambda request: request["raisedAt"] or "", reverse=True)


# --- the deadline ------------------------------------------------------------------------------------------


def is_due(request: dict[str, Any], moment: datetime) -> bool:
    deadline = parse_time(request.get("deadline"))
    return request.get("mode") == "soft_review" and request.get("state") == "open" and deadline is not None and deadline <= moment


def _expire_row(client, row: dict[str, Any], moment: datetime) -> bool:
    request = read_review(row)
    if not is_due(request, moment):
        return False
    at = now_iso(moment)
    client.update_record("ReviewRequest", {
        "id": request["id"], "state": "timed_out", "updatedAt": at,
        "history": json.dumps(_history(row.get("history"), "timed_out", by="system", at=at, note=PROCEEDED_WITHOUT_REVIEW)),
    })
    return True


def expire_due(client, *, now: datetime | None = None) -> list[str]:
    """Mark every open soft review past its deadline as timed out ("proceeded without review"). Idempotent. Returns the ids."""
    moment = now or datetime.now(timezone.utc)
    return [row["id"] for row in client.list_records("ReviewRequest") if _expire_row(client, row, moment)]


# --- answering, withdrawing, steering -----------------------------------------------------------------------


def answer_review(client, request_id: str, *, decision: str, by: str, feedback: str | None = None, steer: str | None = None,
                  roles: list[str] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Approve, reject, or give feedback (with an optional steer). Only an open request can be answered."""
    if roles is not None and not ANSWERING_ROLES & set(roles):
        raise ReviewError("only editors and admins can answer a review request.")
    if decision not in DECISIONS:
        raise ReviewError(f"decision must be one of {', '.join(DECISIONS)}.")
    if steer is not None and steer not in STEERS:
        raise ReviewError(f"steer must be one of {', '.join(STEERS)}.")
    note = _text(feedback, "feedback")
    if decision == "feedback" and not note and not steer:
        raise ReviewError("feedback needs some text, or a steer.")
    moment = now or datetime.now(timezone.utc)
    request = get_review(client, request_id, now=moment)
    if request["state"] != "open":
        suffix = f" ({PROCEEDED_WITHOUT_REVIEW})" if request["state"] == "timed_out" else ""
        raise ReviewError(f"review request {request_id} is {request['state'].replace('_', ' ')}{suffix}; it can no longer be answered.")
    if decision == "acknowledge" and request["mode"] != "flag":
        raise ReviewError("only a flag is acknowledged; a soft review or hard gate is approved or rejected.")
    at = now_iso(moment)
    answer = {"decision": decision, "feedback": note, "steer": steer, "by": _text(by, "by", required=True, limit=200), "at": at}
    client.update_record("ReviewRequest", {
        "id": request_id, "state": "answered", "answer": json.dumps(answer), "updatedAt": at,
        "history": json.dumps(_history(request["history"], "answered", by=answer["by"], at=at, note=decision)),
    })
    return get_review(client, request_id, sweep=False)


def withdraw_review(client, request_id: str, *, by: str, note: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """The raiser takes the request back (the question no longer applies). Only an open request can be withdrawn."""
    moment = now or datetime.now(timezone.utc)
    request = get_review(client, request_id, now=moment)
    if request["state"] != "open":
        raise ReviewError(f"review request {request_id} is {request['state'].replace('_', ' ')}; it can no longer be withdrawn.")
    at = now_iso(moment)
    client.update_record("ReviewRequest", {
        "id": request_id, "state": "withdrawn", "updatedAt": at,
        "history": json.dumps(_history(request["history"], "withdrawn", by=by, at=at, note=_text(note, "note"))),
    })
    return get_review(client, request_id, sweep=False)


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
    request = get_review(client, request_id, sweep=False)
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
    return get_review(client, request_id, sweep=False)


# --- waiting (what a CLI-run process calls) -------------------------------------------------------------------


def wait_for_review(client, request_id: str, *, poll_seconds: float = 30.0, max_wait_seconds: float | None = None,
                    sleep: Callable[[float], None] = time.sleep,
                    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict[str, Any]:
    """Block the caller as the request's mode says. Returns the request; its ``outcome`` says what to do next.

    * flag:         returns at once with outcome ``waiting`` (nothing waits; read steering later with ``steering_for``).
    * soft_review:  polls until answered, or until the deadline passes, then returns outcome
                    ``proceeded_without_review`` (and the request is recorded as timed out).
    * hard_gate:    polls until answered or withdrawn. It never returns ``proceeded_without_review``. If
                    ``max_wait_seconds`` runs out first it raises ReviewStillOpen and the gate stays open.
    A ``max_wait_seconds`` on a soft review that ends before its deadline also raises ReviewStillOpen."""
    started = clock()
    while True:
        request = get_review(client, request_id, now=clock())
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


def raise_batch_review(client, *, raised_by: str, batch_id: str, proposal_ids: list[str], noun: str = "story idea",
                       deadline_days: float | None = None, links: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """ONE soft review for a run that produced a batch of proposals: "N new story ideas to review".

    The subject is the batch; each proposal is a link. Idempotent per ``batch_id``, so a re-run of the same synthesis
    does not raise a second request. Feedback comes back through ``steering_for(client, raised_by=raised_by)``."""
    if not proposal_ids:
        raise ReviewError("a batch review needs at least one proposal.")
    count = len(proposal_ids)
    plural = noun if count == 1 else f"{noun}s"
    safe = re.sub(r"[^a-z0-9._-]+", "-", batch_id.lower()).strip("-")[:100]
    entries = [{"type": "proposal", "id": proposal_id, "label": f"{noun} {index}"} for index, proposal_id in enumerate(proposal_ids, 1)]
    return raise_review(
        client, subject={"type": "batch", "id": batch_id}, mode="soft_review", raised_by=raised_by,
        reason=f"{count} new {plural} to review",
        ask="Approve to keep them all, reject to drop the batch, or steer with a note about what kind of ideas you want.",
        deadline_days=deadline_days, links=[*entries, *(_links(links))], request_id=f"rr-batch-{safe}", now=now)


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
    rules = {row["id"]: row for row in client.list_records("ReviewRecipientRule")}
    chosen, source = None, "site_owner"
    for rule_id, label in ((f"automation.{automation}" if automation else None, f"automation {automation}"),
                           (f"mode.{mode}", f"mode {mode}"), ("default", "default")):
        if rule_id and rule_id in rules:
            chosen, source = rules[rule_id], label
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


# --- the command line ---------------------------------------------------------------------------------------------------


def _line(request: dict[str, Any]) -> str:
    subject = request["subject"]
    if request["mode"] == "soft_review" and request["state"] == "open":
        when = f"proceeds {request['deadline']}" if request["deadline"] else "open until handled"
    else:
        when = request["outcome"]
    return "\t".join(["reviews", request["id"], request["mode"], request["state"], f"{subject.get('type')}:{subject.get('id')}", when, request["reason"] or ""])


def run_command(command: str, flags: list[str]) -> None:
    """`papyrus reviews list|show|raise|answer|withdraw|wait|steering|applied|recipients`."""
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

    if command == "list":
        found = list_reviews(client, state=options.get("state") if isinstance(options.get("state"), str) else None,
                             mode=options.get("mode") if isinstance(options.get("mode"), str) else None,
                             raised_by=options.get("raised-by") if isinstance(options.get("raised-by"), str) else None)
        show(found)
        if not as_json:
            for request in found:
                print(_line(request))
    elif command == "show":
        request = get_review(client, need("id"))
        show(request)
        if not as_json:
            print(_line(request))
            print(f"ask\t{request['ask'] or '-'}\nraisedBy\t{request['raisedBy']} at {request['raisedAt']}")
            if request["answer"]:
                answer = request["answer"]
                print(f"answer\t{answer['decision']}\t{answer.get('steer') or '-'}\t{answer.get('feedback') or '-'}\t{answer['by']} at {answer['at']}")
            if request["appliedIn"]:
                print(f"applied\trun {request['appliedIn']['runId']} at {request['appliedIn']['at']}")
            for entry in request["history"]:
                print(f"history\t{entry['at']}\t{entry['event']}\t{entry.get('by', '')}\t{entry.get('note', '')}")
    elif command == "raise":
        subject = {"type": need("subject-type"), "id": need("subject-id")}
        links = json.loads(options["links"]) if isinstance(options.get("links"), str) else None
        arguments = dict(subject=subject, mode=need("mode"), reason=need("reason"), ask=options.get("ask") if isinstance(options.get("ask"), str) else None,
                         raised_by=options.get("raised-by") if isinstance(options.get("raised-by"), str) else actor,
                         deadline=options.get("deadline") if isinstance(options.get("deadline"), str) else None,
                         deadline_days=float(options["deadline-days"]) if isinstance(options.get("deadline-days"), str) else None,
                         links=links, request_id=options.get("id") if isinstance(options.get("id"), str) else None)
        if parse_boolean_option(options.get("wait"), False, "--wait"):
            request = review_gate(client, poll_seconds=float(options.get("poll-seconds") or 30),
                                  max_wait_seconds=float(options["max-wait-seconds"]) if isinstance(options.get("max-wait-seconds"), str) else None,
                                  **arguments)
        else:
            request = raise_review(client, **arguments)
        show(request, _line(request))
    elif command == "answer":
        request = answer_review(client, need("id"), decision=need("decision"), by=actor,
                                feedback=options.get("feedback") if isinstance(options.get("feedback"), str) else None,
                                steer=options.get("steer") if isinstance(options.get("steer"), str) else None)
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
    else:
        raise ValueError(f"Unsupported papyrus reviews command: {command}")
