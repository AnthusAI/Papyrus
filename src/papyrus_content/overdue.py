"""Overdue: anything due and untouched is shown and flagged (PPY-70cd6a, slice C4 of docs/design/always-on-agents-architecture.md).

A lost timer must never be silent. Every record that waits keeps a named due time it is read by (a Delivery's ``dueKey`` + ``dueAt`` in its sparse due index; an open
soft review's ``dueAt``, read from the open partition of the review request state index). A timer puts one
wake on the queue at that time and the run moves the time on or clears it. A record whose due time is long past and is still in its due index was not run:
its timer was lost, or its wake died. That record is *Overdue*.

* ``read`` is what Today shows: one index query per kind of waiting record, nothing else.
* ``recover`` is what the operations hygiene agent's daily wake does with them: send the record's wake again **with the key its timer would have used**, and
  raise one flag per overdue record. It is the same path as the timer: the wake carries the same key, the queue drops a repeat inside its window, and the
  runner's once-only create answers a repeat after it as a duplicate, so the work is done once. It does no work itself.
* ``wake_now`` is the same for one record, asked by a person (Today's Wake now, ``papyrus agents wake-overdue``; the operation ``agents_wake_overdue``,
  PPY-97180c): the record must be Overdue, and its timer's wake is sent again once, **with the same key**. A person is looking at the record, so no flag is
  raised; the wake's trigger says who sent it again and why (``poke``), and the run record's summary says the same.

"Long past" is not a number chosen here. A wake a timer put on the queue is either run or settled within the queue's own limits: the message stays hidden for the
runner's whole possible length (900 s plus 60 s kept for recording) and is delivered at most twice (amplify/agents/wake-queue.ts). A record that is still due
after both are used up has no wake in flight. ``WAKE_SETTLES_AFTER_SECONDS`` is those limits multiplied; ``overdue_test.py`` holds them against the template.

One flag per overdue record: the flag's id is made from the record and the due time it missed, and raising a review request with an existing id returns the
existing request. Checking again changes nothing; a record that misses a later due time is a new flag. A record that ran late has a new due time or none, so it is
no longer in the index and no longer overdue.

Two kinds of record wait today: Deliveries and soft reviews with a deadline (PPY-9b8e59). A kind of record that waits adds its source here when it has its own due time.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from .announcements.delivery_timers import OWNER as DELIVERY_OWNER, RECORD_KIND as DELIVERY_KIND
from .announcements.deliveries import Deliveries
from .announcements.records import utc
from .review_deadline_timers import RECORD_KIND as REVIEW_KIND

OVERDUE_KINDS = (DELIVERY_KIND, REVIEW_KIND)
WOKEN_NOW = "wake_overdue"       # the poke kind on a timer wake a person sent again
MAX_SUMMARY_CHARACTERS = 500

RUNNER_TIMEOUT_SECONDS = 900          # the runner template's Timeout
RECORDING_MARGIN_SECONDS = 60         # procedure_runner.SECONDS_KEPT_FOR_RECORDING
MAXIMUM_RECEIVES = 2                  # a wake is delivered at most twice
WAKE_SETTLES_AFTER_SECONDS = (RUNNER_TIMEOUT_SECONDS + RECORDING_MARGIN_SECONDS) * MAXIMUM_RECEIVES

FLAG_PREFIX = "overdue-"
RAISED_BY = "operations-hygiene"
MARK, WORD = "⏰", "Overdue"


def settled_before(now: datetime) -> str:
    """The due time at or before which a record still in the due index has no wake in flight."""
    return utc((now or datetime.now(timezone.utc)) - timedelta(seconds=WAKE_SETTLES_AFTER_SECONDS))


def overdue_deliveries(client: Any, now: datetime) -> list[dict[str, Any]]:
    """The Deliveries still waiting for a time that passed long enough ago: one query on the sparse due index."""
    return Deliveries(client).due(settled_before(now))


def overdue_review_deadlines(client: Any, now: datetime, open_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The open soft reviews whose deadline passed long enough ago and are still open: one query on the open partition of the state index, or the rows of that
    partition the caller has already read (``open_rows``)."""
    from . import review_requests

    rows = review_requests.rows_in_state(client, "open") if open_rows is None else open_rows
    return [row for row in rows if waits_with_no_wake_in_flight(row, now)]


def waits_with_no_wake_in_flight(row: Mapping[str, Any], now: datetime) -> bool:
    """A record still waiting for a due time (it has ``dueAt``, so it is in its due index) that passed long enough ago that no wake is in flight."""
    return bool(row.get("dueAt")) and str(row["dueAt"]) <= settled_before(now)


def is_overdue(kind: str, row: Mapping[str, Any], now: datetime) -> bool:
    """The rule the due index reads apply, for one record read by its id: a Delivery with a pending time, or an open soft review with a deadline, whose
    due time passed long enough ago."""
    if kind == REVIEW_KIND and row.get("state") != "open":
        return False
    return waits_with_no_wake_in_flight(row, now)


def flag_id(kind: str, record_id: str, due_at: str) -> str:
    """The id of the one flag for one record that missed one due time."""
    return FLAG_PREFIX + hashlib.sha256(f"{kind}:{record_id}:{due_at}".encode("utf-8")).hexdigest()[:32]


def shown(kind: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """One overdue record as Today lists it, in words with a mark."""
    waiting = row.get("waitingFor") or ("deadline" if kind == REVIEW_KIND else None)
    return {"kind": kind, "id": row["id"], "dueAt": row["dueAt"], "waitingFor": waiting, "flagId": flag_id(kind, row["id"], row["dueAt"]),
            "shown": f"{MARK} {WORD}: {kind} {row['id']} was due {row['dueAt']}" + (f" ({waiting})" if waiting else "") + " and nothing ran"}


def read(client: Any, now: datetime | None = None, *, open_review_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Every overdue record, oldest due time first. Read only. ``open_review_rows`` is the open partition of the review request state index when the caller has read it."""
    moment = now or datetime.now(timezone.utc)
    found = [*(shown(DELIVERY_KIND, row) for row in overdue_deliveries(client, moment)),
             *(shown(REVIEW_KIND, row) for row in overdue_review_deadlines(client, moment, open_review_rows))]
    return sorted(found, key=lambda entry: (entry["dueAt"], entry["id"]))


def recover(client: Any, *, deliveries: Deliveries, wake_request: Callable[[Mapping[str, Any]], dict[str, Any]], send: Callable[[dict[str, Any]], Any],
            review_deadline_wake_request: Callable[[Mapping[str, Any]], dict[str, Any]], now: datetime | None = None,
            raised_by: str = RAISED_BY) -> list[dict[str, Any]]:
    """The hygiene agent's daily wake: for each overdue record send its wake again with the key its timer would have used, and raise its one flag.

    ``wake_request(row)`` is the runner request a Delivery's own timer sends (``DeliveryTimers.wake_request``) and ``review_deadline_wake_request(row)`` the one a soft
    review's deadline timer sends (``ReviewDeadlineTimers.wake_request``); ``send`` puts it on the site's wake queue.
    Returns one entry per overdue record: its wake key and whether this call raised the flag or it already existed."""
    from . import review_requests

    moment = now or datetime.now(timezone.utc)
    results = []
    for row in overdue_deliveries(client, moment):
        entry = shown(DELIVERY_KIND, row)
        request = wake_request(row)
        send(request)
        existing = client.get_record("ReviewRequest", entry["flagId"])
        review_requests.raise_review(
            client, subject={"type": "delivery", "id": row["id"]}, mode="flag", raised_by=raised_by, request_id=entry["flagId"], now=moment,
            reason=f"Overdue: {DELIVERY_KIND} {row['id']} was due {row['dueAt']} and no run started. Its wake was sent again with its original key.",
            ask="Check the Delivery; it runs once when its wake is delivered.")
        results.append({**entry, "wakeKey": request["wakeKey"], "flag": "existing" if existing else "raised"})
    for row in overdue_review_deadlines(client, moment):
        entry = shown(REVIEW_KIND, row)
        request = review_deadline_wake_request(row)
        send(request)
        existing = client.get_record("ReviewRequest", entry["flagId"])
        review_requests.raise_review(
            client, subject={"type": "review_request", "id": row["id"]}, mode="flag", raised_by=raised_by, request_id=entry["flagId"], now=moment,
            reason=f"Overdue: soft review {row['id']} was due {row['dueAt']} and is still open. Its deadline wake was sent again with its original key.",
            ask="Check the request; it proceeds without review once its deadline wake runs.")
        results.append({**entry, "wakeKey": request["wakeKey"], "flag": "existing" if existing else "raised"})
    return results


# --- one record, by a person ---------------------------------------------------------------------------------------------------------------------------


class OverdueWakeError(Exception):
    """A Wake now on an Overdue record that is not carried out. ``code`` is one of the operation table's error codes."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def site_timer_wake_requests(environment: Mapping[str, str], *, appsync_endpoint: str) -> dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]]:
    """For each kind of record that waits, the request its own follow-up timer sends (``DeliveryTimers.wake_request``, ``ReviewDeadlineTimers.wake_request``),
    built from the site's names in ``environment`` as the site's functions name them. A site that names them not is refused when a wake is asked for."""
    from .announcements.delivery_timers import DeliveryTimers
    from .follow_up_timers import FollowUpError
    from .review_deadline_timers import ReviewDeadlineTimerError, ReviewDeadlineTimers

    def built(make):
        def wake_request(row: Mapping[str, Any]) -> dict[str, Any]:
            try:
                return make().wake_request(row)
            except (FollowUpError, ReviewDeadlineTimerError) as missing:
                raise OverdueWakeError("service_unavailable", f"This site's follow-up timers are not named here ({missing}), so nothing was sent.") from missing
        return wake_request

    return {DELIVERY_KIND: built(lambda: DeliveryTimers.from_environment(environment, appsync_endpoint=appsync_endpoint)),
            REVIEW_KIND: built(lambda: ReviewDeadlineTimers.from_environment(environment, appsync_endpoint=appsync_endpoint))}


def woken_by_person(request: Mapping[str, Any], *, by: str, reason: str, at: str) -> dict[str, Any]:
    """The timer's own request with the same wake key, whose trigger says who sent it again, why, and which wake it repeats. The queue deduplicates by the key,
    so this is the timer's wake and not another one."""
    trigger = dict(request.get("trigger") or {})
    summary = f"{by} woke it now ({reason.strip()}); this repeats: {trigger.get('summary') or request['wakeKey']}"
    trigger.update(summary=summary[:MAX_SUMMARY_CHARACTERS], poke={"kind": WOKEN_NOW, "by": by, "reason": reason.strip(), "at": at, "repeats": request["wakeKey"]})
    return {**dict(request), "trigger": trigger}


def not_overdue_words(kind: str, row: Mapping[str, Any], now: datetime) -> str:
    if kind == REVIEW_KIND and row.get("state") != "open":
        return f"{kind} {row['id']} is {row.get('state')}, so it waits for nothing and has no timer wake to send again."
    if not row.get("dueAt"):
        return f"{kind} {row['id']} waits for nothing, so it has no timer wake to send again."
    return (f"{kind} {row['id']} is not Overdue: it waits until {row['dueAt']}, and its timer's wake is due or still in flight. "
            f"It is Overdue only once that time is {WAKE_SETTLES_AFTER_SECONDS // 60} minutes past with nothing run.")


def wake_now(client: Any, *, kind: str, record_id: str, reason: str, by: str, person: bool,
             wake_requests: Mapping[str, Callable[[Mapping[str, Any]], dict[str, Any]]], send: Callable[[dict[str, Any]], Any],
             now: datetime | None = None) -> dict[str, Any]:
    """Wake now on one Overdue record: read it by its id, and send its own timer's wake again once, with the same key. ``wake_requests`` is
    ``site_timer_wake_requests`` (or the timers themselves); ``send`` puts the request on the site's wake queue. Raises ``OverdueWakeError``."""
    if not person:
        raise OverdueWakeError("human_required", "Wake now is a person's request. Nothing was sent.")
    if not reason.strip():
        raise OverdueWakeError("invalid_input", "Say why the record is woken now: the reason is kept on its run.")
    if kind not in OVERDUE_KINDS:
        raise OverdueWakeError("invalid_input", f"Only an Overdue {' or '.join(OVERDUE_KINDS)} is woken this way.")
    moment = now or datetime.now(timezone.utc)
    row = client.get_record(kind, record_id)
    if row is None:
        raise OverdueWakeError("not_found", f"There is no {kind} {record_id} on this site. Nothing was sent.")
    if not is_overdue(kind, row, moment):
        raise OverdueWakeError("constraint_conflict", not_overdue_words(kind, row, moment) + " Nothing was sent.")
    request = woken_by_person(wake_requests[kind](row), by=by, reason=reason, at=utc(moment))
    send(request)
    waiting = shown(kind, row)["waitingFor"]
    return {"record": kind, "id": row["id"], "dueAt": row["dueAt"], "waitingFor": waiting, "wakeKey": request["wakeKey"], "requestedBy": by,
            "reason": reason.strip(),
            "shown": f"{kind} {row['id']} was woken now by {by}: the wake its timer sends for {row['dueAt']} went on the site's queue again, with the same key, so it runs once."}
