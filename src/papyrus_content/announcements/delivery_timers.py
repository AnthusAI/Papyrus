"""A Delivery's due time as a follow-up timer (PPY-3ff011, used by PPY-e8ec54; the scheduled send, PPY-e2829f).

``Deliveries`` calls ``sync`` wherever it writes a Delivery's ``dueAt`` (the earliest of its release time, its lock time and its next attempt time). The timer fires once, puts a wake
for the ``deliver`` owner on the site's wake queue and deletes itself. The wake starts the engine's procedure ``deliver_due`` with no adopted agent (``engine_follow_ups``): it reads
the Delivery again, raises the lock when its lock time has come and sends what is due (``deliver_due.py``). A time that moves moves the entry, and a Delivery with nothing pending has
no entry.

Every writer of Delivery rows that can move ``dueAt`` holds the site's timers (``from_environment``): the announce agent's run and the ``deliver_due`` run in the procedure runner, and
the image service's announcements write door (a person's review change, release, edit or unlock). A writer without them leaves an entry that fires once and does nothing, and a new
time with no entry is Overdue (overdue.py).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ..follow_up_timers import FollowUpTimers, follow_up_request, site_follow_ups

OWNER = "deliver"
RECORD_KIND = "Delivery"
#: The procedure a Delivery's wake starts. It is the engine's, not an agent's: it locks and sends the one Delivery named in its input, and whatever else of X is due.
PROCEDURE_KEY = "deliver_due"


class DeliveryTimers:
    """``base`` is the runner request every start carries (procedure, publication, policy location), as for any follow-up; the Delivery's id and the time it waits for are added as
    the input, which is what the ``deliver_due`` procedure reads."""

    def __init__(self, timers: FollowUpTimers, base: Mapping[str, Any] | Callable[[Mapping[str, Any]], Mapping[str, Any]]):
        self.timers, self._base = timers, base

    @classmethod
    def from_environment(cls, environment: Mapping[str, str], *, appsync_endpoint: str, client: Any = None) -> DeliveryTimers:
        """The timers of the site this process works for (``follow_up_timers.site_follow_ups``). The site's tenant and bucket are required: the runner refuses a wake that does
        not say where the site's agent policy is, and a Delivery's wake must run."""
        timers, base = site_follow_ups(environment, appsync_endpoint=appsync_endpoint, procedure_key=PROCEDURE_KEY, actor_label="Papyrus scheduled send",
                                       needed_for="a Delivery with a release or lock time", require_policy_location=True, client=client)
        return cls(timers, base)

    def _base_request(self, row: Mapping[str, Any]) -> dict[str, Any]:
        request = dict(self._base(row) if callable(self._base) else self._base)
        request["input"] = {**(request.get("input") if isinstance(request.get("input"), dict) else {}), "deliveryId": row["id"],
                            **({"dueAt": row["dueAt"]} if row.get("dueAt") else {})}
        return request

    def sync(self, row: Mapping[str, Any]) -> None:
        due = row.get("dueAt")
        self.timers.sync(RECORD_KIND, row["id"], due, owner=OWNER, base=self._base_request(row), waiting_for=waiting_for(row) if due else None)

    def wake_request(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """The runner request this Delivery's timer sends for the time it waits for, with the same wake key. Overdue recovery sends it again (overdue.py)."""
        return follow_up_request(self._base_request(row), owner=OWNER, record_id=row["id"], due_at=row["dueAt"], waiting_for=waiting_for(row))


def waiting_for(row: Mapping[str, Any]) -> str:
    """What the earliest pending time is for, in the words a wake carries."""
    due = row.get("dueAt")
    if due and due == row.get("nextAttemptAt") and row.get("waitingFor"):
        return str(row["waitingFor"])
    if due and due == row.get("lockAt") and not row.get("lockedAt") and row.get("lockAt") != row.get("releaseAt"):
        return "lock"
    return "release"
