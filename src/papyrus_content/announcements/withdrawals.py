"""Withdrawing a Delivery, and deleting the post a correction replaced (PPY-efd06c, PPY-3e0a8a).

**Withdraw** takes a Delivery back. What has not gone is simply stopped: its state becomes ``withdrawn`` and nothing public is touched. What went out is taken back only where the
channel can: a post on X is deleted (Caducus's ``x`` channel, ``x_channel.XChannel``), and the Delivery says who asked and what the deletion cost. A channel that cannot take its
message back (an email that was sent, a post a person made by hand) is refused in words, and the Delivery stays ``sent``: a Delivery never says it was withdrawn when the
message is still out. When every live Delivery of an Announcement is withdrawn, the Announcement is too (``Announcements.after_withdrawal``).

**A correction deletes the old post** (``delete_superseded``). A correction is a new Delivery that names the one it replaces; where the channel can remove the old one (X) the old post
is deleted as part of the correction, and the deletion cost is written on the old Delivery, which stays ``superseded``. Both are safe to repeat: the channel deletes a post once and
answers with its record of the deletion, and the cost is written only when the row does not already carry it, so a crash after the deletion is finished by the same call made again.

The channel is passed in as a ``Remover`` (``delete`` and ``removal`` by the event id of the attempt that sent the post). A lane without one (the signed-in command line holds no rights
on Caducus) can still withdraw what never went; withdrawing what went on X needs the site's own stack, and says so.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol

from .decisions import Announcements
from .deliveries import Deliveries, OpenAttempt
from .records import (
    ATTEMPT_SENT, BLOCKED, DELIVERY_WITHDRAWN, DRAFTED, DRY_RUN, FAILED, READY, SENDING, SENT, SUPERSEDED, RecordError, attempt_log, now_iso, open_attempt_of,
)
from .x_channel import Removal

#: A Delivery in one of these has nothing public out there: withdrawing it only stops it.
NOTHING_OUT = (DRAFTED, READY, BLOCKED, FAILED, DRY_RUN)
#: The channels that can delete what they sent. Email cannot: a correction to an email says in its words that it is one.
DELETES = ("x",)


class CannotTakeBack(RecordError):
    """The channel cannot remove what it sent, so the Delivery is not withdrawn (it is still out there). Corrections say so in their text instead."""


class ChannelUnavailable(RecordError):
    """What a withdrawal needs from the channel (to delete a post) is not wired in this lane. Nothing was changed."""


class Remover(Protocol):
    def delete(self, event_id: str, *, by: str) -> Removal: ...

    def removal(self, event_id: str) -> Removal | None: ...


def sent_event(row: Mapping[str, Any]) -> str | None:
    """The event id of the attempt that put the post out: the last attempt that was sent."""
    for entry in reversed(attempt_log(row)):
        if entry.get("outcome") == ATTEMPT_SENT and entry.get("eventId"):
            return str(entry["eventId"])
    return None


class Withdrawals:
    """``removers`` answers the channel's remover for a Delivery (None when the channel cannot delete, or this lane holds no transport for it)."""

    def __init__(self, deliveries: Deliveries, announcements: Announcements, removers: Callable[[Mapping[str, Any]], Remover | None] = lambda row: None):
        self.deliveries, self.announcements, self.removers = deliveries, announcements, removers

    def _remover(self, row: Mapping[str, Any]) -> Remover:
        if row["channel"] not in DELETES:
            raise CannotTakeBack(f"{row['id']} went out on {row['channel']}, which cannot take a message back; send a correction that says it is one instead.")
        remover = self.removers(row)
        if remover is None:
            raise ChannelUnavailable(f"{row['id']} is a post on {row['channel']}; deleting it needs the site's own {row['channel']} channel, which this lane does not hold.")
        return remover

    # --- withdraw ---------------------------------------------------------------------------------------------------------------------------------

    def withdraw(self, delivery: str, *, by: str, now: str | None = None) -> dict[str, Any]:
        """Take a Delivery back and say who did. Returns the Delivery as it stands. Withdrawing a Delivery already withdrawn changes nothing."""
        now = now or now_iso()
        row = self.deliveries.get(delivery)
        if row is None:
            raise RecordError(f"There is no Delivery {delivery}.")
        if row.get("state") == DELIVERY_WITHDRAWN:
            return row
        if row.get("state") == SUPERSEDED or row.get("supersededBy"):
            raise RecordError(f"{delivery} was replaced by a correction ({row.get('supersededBy')}); withdraw the correction, not the Delivery it replaced.")
        if open_attempt_of(row) or row.get("state") == SENDING:
            raise OpenAttempt(f"{delivery} has an attempt with no answer yet; it is settled before the Delivery is withdrawn, so a post that went is not left behind.")
        if row.get("state") in NOTHING_OUT:
            withdrawn = self.deliveries.finish(row, DELIVERY_WITHDRAWN, by=by, note=f"withdrawn by {by} before it went; nothing public was changed", now=now)
        elif row.get("state") == SENT:
            event = sent_event(row)
            if row["channel"] not in DELETES:
                raise CannotTakeBack(f"{delivery} went out as {row['channel']}, and a message sent that way cannot be recalled; it stays sent, and a correction says what was wrong.")
            if event is None:
                raise CannotTakeBack(f"{delivery} was posted by a person by hand, so it is deleted by hand where it was posted; it stays sent.")
            removal = self._remover(row).delete(event, by=by)
            withdrawn = self.deliveries._change(row, {"state": DELIVERY_WITHDRAWN, **({"cost": removal.cost} if removal.cost is not None else {})}, by=by,
                                                note=f"withdrawn by {by}: the post was deleted" + (f"; Caducus has charged {removal.cost} for it in all" if removal.cost else ""), now=now)
        else:
            raise RecordError(f"{delivery} is {row.get('state')}; it cannot be withdrawn.")
        self.announcements.after_withdrawal(row["announcementId"], by=by, now=now)
        return withdrawn

    # --- a correction ---------------------------------------------------------------------------------------------------------------------------

    def delete_superseded(self, old: Mapping[str, Any], *, by: str, now: str | None = None) -> dict[str, Any]:
        """The Delivery a correction replaced: its post is deleted where the channel can, and the deletion cost is written on it. It stays ``superseded``. A Delivery that never put a
        post out (it was not sent) has nothing to delete. Safe to call again."""
        now = now or now_iso()
        row = self.deliveries.get(old["id"]) or dict(old)
        event = sent_event(row)
        if event is None or row["channel"] not in DELETES:
            return row
        removal = self._remover(row).delete(event, by=by)
        if removal.cost is not None and row.get("cost") != removal.cost:
            return self.deliveries._change(row, {"cost": removal.cost}, by=by, note=f"the post was deleted because a correction replaced it; Caducus has charged {removal.cost} for it in all", now=now)
        return row
