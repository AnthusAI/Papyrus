"""What a periodic list has already sent and what it has not (slice N3, PPY-b71153).

An item is eligible for a list's next issue when it qualified since the list's last *sent* Delivery, not in "this calendar period". So the boundary a run needs is the
time of that Delivery, and the issues that need cancelling are the earlier ones of the list that never went: when the next period's Announcement is made, each is
cancelled with a reason and its items are eligible again (they qualified after the last sent issue, and that has not changed).

Both come from one read of the sending account's Deliveries, newest first, which stops at the list's last sent one. A periodic list's id is in the audience of its own
issues only (an every-item message names every-item lists), so the audience says whose Delivery it is.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from papyrus_content.announcements import records
from papyrus_content.announcements.decisions import UNSENT_STATES, Announcements
from papyrus_content.announcements.deliveries import Deliveries

CHANNEL = "email"
CARRIED_FORWARD = "not released before the next period; items carried forward"


@dataclass(frozen=True)
class History:
    """``last_sent_at``: when the list's last sent issue went (None when it never sent one), or when its attempt opened when that attempt has no answer yet, because
    its items are on their way. ``unsent``: the Deliveries of the list's later issues that have not gone, newest first."""

    last_sent_at: str | None
    unsent: tuple[dict[str, Any], ...]


def sent_at(row: Mapping[str, Any]) -> str:
    """When a sent Delivery's attempt closed as sent."""
    closed = [entry["closedAt"] for entry in records.attempt_log(row) if entry.get("outcome") == records.ATTEMPT_SENT and entry.get("closedAt")]
    if not closed:
        raise records.RecordError(f"{row['id']} is sent but no attempt of it closed as sent.")
    return str(closed[-1])


def read_history(deliveries: Deliveries, account_id: str, list_id: str) -> History:
    unsent: list[dict[str, Any]] = []
    for row in deliveries.for_account(CHANNEL, account_id):
        if list_id not in (row.get("audience") or ()):
            continue
        state = row.get("state")
        if state == records.SENT:
            return History(sent_at(row), tuple(unsent))
        if state == records.SENDING:
            attempt = records.open_attempt_of(row)
            if attempt is None:
                raise records.RecordError(f"{row['id']} is sending and has no open attempt.")
            return History(str(attempt["at"]), tuple(unsent))
        if state in UNSENT_STATES:
            unsent.append(row)
    return History(None, tuple(unsent))


def carry_forward(announcements: Announcements, history: History, current_key: str, scheduled_time: str, *, by: str, now: str | None = None) -> tuple[str, ...]:
    """Cancel the list's earlier issues that never went, each with the reason; return the once-only keys of the Announcements cancelled. The issue being made is not
    one of them, and neither is a later one."""
    current = records.announcement_id(current_key)
    cancelled: list[str] = []
    for delivery in history.unsent:
        if delivery["announcementId"] == current:
            continue
        announcement = announcements.get(delivery["announcementId"])
        if announcement is None or announcement.get("state") not in (records.PLANNED, records.RELEASED):
            continue
        if announcement["releaseAt"] >= records.utc(scheduled_time):
            continue
        announcements.cancel_unsent(announcement, reason=CARRIED_FORWARD, by=by, now=now)
        cancelled.append(announcement["dedupeKey"])
    return tuple(cancelled)
