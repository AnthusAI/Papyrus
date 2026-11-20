"""Caducus's ``x`` channel as the attempt log and the withdraw operation see it (PPY-efd06c; the contract is ``channel.py``).

``XChannel`` is the one adapter between a Delivery on the channel ``x`` and a ``channel.Broadcaster`` (Caducus's router and delivery log):

* ``submit`` hands one attempt's event to Caducus (``delivery:<deliveryId>:a<N>``, the same event id for the same attempt, which Caducus dedupes), with the post exactly as the
  Delivery's words are and the link found in them;
* ``delivery`` reads Caducus's record of the event as the attempt log's ``Answer``: sent (with the post id and what it cost), failed (X's own message), or refused by Caducus's guard (a
  pause, or the budget, with the time the budget cycle ends);
* ``removal`` and ``delete`` take the post down. ``delete`` is never blocked by a pause or the budget (Caducus's contract), and it is safe to call again: the post is deleted
  once, and ``removal`` reads the record of it.

Nothing here posts anything by itself and nothing here knows a mode: a dry run never reaches a channel (``x_announce.py``), and X is off everywhere until the owner turns it on.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .attempts import ANSWER_FAILED, ANSWER_REFUSED, ANSWER_SENT, QUEUED, Answer
from .channel import FAILED, REFUSED, SENT, WITHDRAWN, Broadcaster, DeliveryView
from .post import LINK
from .records import BUDGET_REACHED_CODE, PAUSED_CODE, RecordError

CHANNEL = "x"


@dataclass(frozen=True)
class Removal:
    """The record that a post was deleted at X: who asked, when, and what Caducus has charged for the event in all (the post and its deletion)."""

    by: str | None
    at: str | None
    cost: str | None


def link_of(post: str) -> str:
    """The link a post carries (the last one: the Story's link is added after the drafted line)."""
    found = LINK.findall(post)
    if not found:
        raise RecordError("A post carries the Story's link; the words of this Delivery have none, so it cannot be handed to X.")
    return found[-1]


class XChannel:
    """``budget_wait_until()`` is when the budget cycle ends (UTC), so a refusal for the budget names the time the Delivery may be tried again."""

    def __init__(self, broadcaster: Broadcaster, *, budget_wait_until: Callable[[], str | None] = lambda: None):
        self.broadcaster = broadcaster
        self.budget_wait_until = budget_wait_until

    # --- the attempt log's Transport ---------------------------------------------------------------------------------------------------------------

    def submit(self, row: Mapping[str, Any], text: str, event_id: str) -> None:
        if row["channel"] != CHANNEL:
            raise RecordError(f"{row['id']} is a {row['channel']} Delivery; this is the x channel.")
        self.broadcaster.submit(account_id=row["accountId"], event_id=event_id, text=text, url=link_of(text))

    def delivery(self, event_id: str) -> Answer | None:
        view = self.broadcaster.delivery(event_id)
        if view is None:
            return None
        if view.status not in (SENT, FAILED, REFUSED, WITHDRAWN):
            return Answer(QUEUED)
        # A post that was deleted afterwards was sent: the attempt's answer does not change, and the deletion is read with ``removal``.
        if view.status in (SENT, WITHDRAWN):
            return Answer(ANSWER_SENT, provider_id=view.post_id, cost=view.cost)
        if view.status == FAILED:
            return Answer(ANSWER_FAILED, code=view.reason or "refused by X", cost=view.cost)
        code = BUDGET_REACHED_CODE if "udget" in (view.reason or "") else PAUSED_CODE
        return Answer(ANSWER_REFUSED, code=code, cost=view.cost, wait_until=self.budget_wait_until() if code == BUDGET_REACHED_CODE else None)

    # --- taking a post down -------------------------------------------------------------------------------------------------------------------------

    def removal(self, event_id: str) -> Removal | None:
        """The record of the post's deletion, or None while the post is up (or never was)."""
        view = self.broadcaster.delivery(event_id)
        return _removal(view) if view is not None and view.status == WITHDRAWN else None

    def delete(self, event_id: str, *, by: str) -> Removal:
        """Delete the post at X and return the record of it. Deleting a post already deleted changes nothing and returns its record."""
        already = self.removal(event_id)
        if already is not None:
            return already
        view = self.broadcaster.delivery(event_id)
        if view is None or view.status != SENT:
            raise RecordError(f"The post of {event_id} is not up at X (Caducus records it as {view.status if view else 'unknown'}), so there is nothing to delete.")
        return _removal(self.broadcaster.withdraw(event_id, by=by))


def _removal(view: DeliveryView) -> Removal:
    return Removal(by=view.withdrawn_by, at=view.withdrawn_at, cost=view.cost)
