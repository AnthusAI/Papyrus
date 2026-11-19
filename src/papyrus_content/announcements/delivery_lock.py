"""The lock of a Delivery: raised at its lock time, lifted by a person (docs/announcement-records.md, "Editing window", PPY-e8ec54).

**A lock is a fact, not something held.** ``lockedAt`` and ``lockedVersion`` are on the Delivery; nothing expires, nothing waits holding a lease, and a person who never answers
blocks only that Delivery. The version locked is the version that is sent, and the attempt log records it (``attempts``: each entry's ``version``). A late edit after the lock is
refused until a person unlocks the Delivery (``unlock``), and an edit made while an attempt is open is a preferred version (``delivery_versions``).

**The lock time is a follow-up timer.** ``lockAt`` is a time on the row, so it is in ``dueAt`` and has a timer (``delivery_timers``). When it fires it raises a wake and nothing else;
``on_wake`` re-reads the Delivery and checks everything again (``follow_up_timers.check_wake``), and ``lock_at_time`` decides what the time means for this Delivery:

===========  ===============================================================================================================================================
review       at the lock time
===========  ===============================================================================================================================================
``none``     the version the policy approved is locked
``soft``     a person's approval of the current version is locked; with nobody acting, the engine approves the current version as the policy (``approvedBy`` is ``system``,
             ``approvalPolicy`` says whose) and locks it, in one conditional write. Silence until the lock time is the rule.
``hard``     nothing is locked and nothing is sent: the Delivery stays due (Overdue in the list) and one flag is raised, once
===========  ===============================================================================================================================================

An edit and a lock at the same moment leave one winner: both are conditional writes on the row's ``revision``. When the edit wins, the lock is made again against the newer version;
when the lock wins, the edit is refused as late.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .. import follow_up_timers, wake_keys
from .deliveries import Conflict, Deliveries
from .records import BLOCKED, DRAFTED, MANUAL, READY, SOFT, SYSTEM, RecordError, now_iso, open_attempt_of, utc

ENGINE = "deliver"
LOCKED, APPROVED_AND_LOCKED, WAITING_FOR_PERSON, NOT_YET, ALREADY_LOCKED, NOT_READY, BY_HAND, NOTHING = (
    "locked", "approved_and_locked", "waiting_for_person", "not_yet", "already_locked", "not_ready", "by_hand", "nothing")


@dataclass(frozen=True)
class LockOutcome:
    """What the lock time meant for one Delivery: ``action`` is one of the words above, ``row`` the Delivery as it stands, ``reason`` says why in plain words when nothing was locked."""

    action: str
    row: dict[str, Any]
    reason: str | None = None
    flag: str | None = None

    @property
    def locked(self) -> bool:
        return self.action in (LOCKED, APPROVED_AND_LOCKED, ALREADY_LOCKED)


@dataclass(frozen=True)
class Decision:
    """What the lock time means for a Delivery as it was read, before anything is written: ``changes`` is what to write to lock it (None when nothing is locked), ``note`` the
    history line, and ``reason`` why in plain words when nothing is locked."""

    action: str
    changes: Mapping[str, Any] | None = None
    note: str | None = None
    reason: str | None = None


def decide(deliveries: Deliveries, row: Mapping[str, Any], now: str) -> Decision:
    """Decide, from the row alone, whether the lock is raised and what it writes (the table above). Pure: reads and writes nothing."""
    if row.get("lockedAt"):
        return Decision(ALREADY_LOCKED)
    if row.get("mode") == MANUAL:
        return Decision(BY_HAND, reason="a person posts it by hand, so there is nothing to lock for sending")
    if open_attempt_of(row) or row.get("state") not in (DRAFTED, READY, BLOCKED):
        return Decision(NOTHING, reason=f"it is {row.get('state')}: there is nothing to lock")
    if now < row["lockAt"]:
        return Decision(NOT_YET, reason=f"its lock time is {row['lockAt']}")
    if row.get("state") != READY:
        why = "its words are not ready" if row.get("state") == DRAFTED else "it is blocked"
        return Decision(NOT_READY, reason=f"it reached its lock time, but {why}, so it is not locked")
    if deliveries.is_approved(row):
        return Decision(LOCKED, {"lockedAt": now, "lockedVersion": int(row["approvedVersion"])}, f"locked version {row['approvedVersion']}")
    if row.get("approval") == SOFT:
        version = int(row["version"])
        return Decision(APPROVED_AND_LOCKED, {"approvedVersion": version, "approvedBy": SYSTEM, "approvedAt": now, "lockedAt": now, "lockedVersion": version},
                        f"approved version {version} by {_source(row)} at the lock time (soft review: nobody acted) and locked it")
    return Decision(WAITING_FOR_PERSON, reason=f"it reached its lock time at {row['lockAt']} with no approved version, and {row.get('approval')} review needs a person to approve it")


def lock_at_time(deliveries: Deliveries, delivery_id: str, *, now: str | None = None, by: str = ENGINE) -> LockOutcome:
    """Raise the lock when the Delivery's lock time has come, deciding by its review (the table above). Reads the row again each time, so a wake for a time that no longer
    applies does nothing. Safe to call twice: a Delivery already locked is left as it is."""
    now = utc(now or now_iso())
    while True:
        row = deliveries.get(delivery_id)
        if row is None:
            raise RecordError(f"There is no Delivery {delivery_id}.")
        decision = decide(deliveries, row, now)
        if decision.changes is None:
            flag = raise_flag(deliveries, row, decision.reason or "") if decision.action == WAITING_FOR_PERSON else None
            return LockOutcome(decision.action, row, decision.reason, flag=flag)
        try:
            written = deliveries._change(row, dict(decision.changes), by=by, note=decision.note or "locked", now=now)
        except Conflict:
            continue   # an edit or an approval won the row first: read it again and decide again
        return LockOutcome(decision.action, written)


def _source(row: Mapping[str, Any]) -> str:
    policy = str(row.get("approvalPolicy") or "the publication's policy")
    return policy.rsplit(" (agent policy version", 1)[0]


def raise_flag(deliveries: Deliveries, row: Mapping[str, Any], reason: str) -> str:
    """One flag for the Delivery and this reason, so a second wake finds the first."""
    from ..review_requests import raise_review
    from .attempts import FLAG_RAISER, FLAG_SUBJECT, flag_id

    request = raise_review(
        deliveries.client, subject={"type": FLAG_SUBJECT, "id": row["id"]}, mode="flag", raised_by=FLAG_RAISER, request_id=flag_id(row["id"], "not locked: " + reason),
        reason=f"Not locked: {reason}.", ask=f"{row['channel']} {row['accountId']}: nothing is locked or sent for this Delivery. Look at it, then approve it or change what should go out.")
    return request["id"]


def unlock(deliveries: Deliveries, delivery_id: str, *, by: str, now: str | None = None, lock_at: str | None = None, release_at: str | None = None) -> dict[str, Any]:
    """A person lifts the lock so the Delivery can be edited again. The approval of the version it held stays; an edit makes a new, unapproved version.

    The lock time has passed, so a new one is named: ``lock_at`` (by default the release time) and, when the release time has passed too, ``release_at``. The lock is raised again at
    the new time, with the same rules. Refused when nothing is locked, when an attempt is open or the Delivery went (an edit then is a preferred version, and a change to what went out is a
    correction), and when the new times are not in the future in order."""
    now = utc(now or now_iso())
    while True:
        row = deliveries.get(delivery_id)
        if row is None:
            raise RecordError(f"There is no Delivery {delivery_id}.")
        if not row.get("lockedAt"):
            raise RecordError(f"{row['id']} is not locked.")
        if open_attempt_of(row):
            raise RecordError(f"{row['id']} has an attempt open: it goes out as locked, and an edit now is saved as a preferred version.")
        if row.get("state") not in (DRAFTED, READY, BLOCKED):
            raise RecordError(f"{row['id']} is {row.get('state')}; only a Delivery that has not gone is unlocked.")
        release = utc(release_at) or row["releaseAt"]
        lock = utc(lock_at) or release
        if release <= now:
            raise RecordError(f"The release time {release} has passed: name a new one with the unlock.")
        if lock <= now or lock > release:
            raise RecordError(f"The new lock time {lock} is between now and the release time {release}.")
        try:
            return deliveries._change(row, {"lockedAt": None, "lockedVersion": None, "lockAt": lock, "releaseAt": release}, by=by,
                                      note=f"unlocked version {row.get('lockedVersion')} by {by}; it locks again at {lock}", now=now)
        except Conflict:
            continue


def on_wake(deliveries: Deliveries, wake_key: str, *, now: str | None = None, by: str = ENGINE) -> dict[str, Any]:
    """What the run does for a follow-up wake of a Delivery: read the row again, check that it still waits for the time the wake names, raise the lock if its time has come, and say
    whether the Delivery may go now (the attempt worker sends it; nothing is sent here)."""
    now = utc(now or now_iso())
    delivery_id = wake_keys.checked(wake_key).split(wake_keys.SEPARATOR)[1]
    row = deliveries.get(delivery_id)
    answer = follow_up_timers.check_wake(wake_key, row)
    if not answer["waiting"]:
        return {"ran": False, "reason": answer["reason"]}
    outcome = lock_at_time(deliveries, delivery_id, now=now, by=by)
    ok, why = deliveries.releasable(outcome.row, now)
    return {"ran": True, "lock": outcome.action, "reason": outcome.reason, "flag": outcome.flag, "releasable": ok, "why": why, "row": outcome.row}
