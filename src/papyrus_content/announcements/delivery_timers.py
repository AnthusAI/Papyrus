"""A Delivery's due time as a follow-up timer (PPY-3ff011, used by PPY-e8ec54).

``Deliveries`` calls ``sync`` wherever it writes a Delivery's ``dueAt`` (the earliest of its release time, its lock time and its next attempt time). The timer fires once, puts a wake
for the ``deliver`` owner on the site's wake queue and deletes itself; the run reads the Delivery again (``delivery_lock.on_wake``). A time that moves moves the entry, and a Delivery
with nothing pending has no entry.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ..follow_up_timers import FollowUpTimers

OWNER = "deliver"
RECORD_KIND = "Delivery"


class DeliveryTimers:
    """``base`` is the runner request every start carries (procedure, publication, policy location), as for any follow-up; the Delivery's id is added as the input."""

    def __init__(self, timers: FollowUpTimers, base: Mapping[str, Any] | Callable[[Mapping[str, Any]], Mapping[str, Any]]):
        self.timers, self._base = timers, base

    def sync(self, row: Mapping[str, Any]) -> None:
        due = row.get("dueAt")
        request = dict(self._base(row) if callable(self._base) else self._base)
        request["input"] = {**(request.get("input") if isinstance(request.get("input"), dict) else {}), "deliveryId": row["id"]}
        self.timers.sync(RECORD_KIND, row["id"], due, owner=OWNER, base=request, waiting_for=waiting_for(row) if due else None)


def waiting_for(row: Mapping[str, Any]) -> str:
    """What the earliest pending time is for, in the words a wake carries."""
    due = row.get("dueAt")
    if due and due == row.get("nextAttemptAt") and row.get("waitingFor"):
        return str(row["waitingFor"])
    if due and due == row.get("lockAt") and not row.get("lockedAt") and row.get("lockAt") != row.get("releaseAt"):
        return "lock"
    return "release"
