"""Close a sent X Delivery's attempt from Caducus's record, right after the site's X function posted it (PPY-8037b8).

The announce agent hands an attempt to Caducus (``delivery:<deliveryId>:a<N>``) and reads back ``queued``: the post itself is made later, by the site's X function, one
at a time. Nothing used to read Caducus's record after that, so every sent Delivery stayed ``sending`` with its attempt ``started``: the Announcements list showed it as
sending or Outcome unknown, and the account's post count for the cycle missed it. The X function now settles the Delivery as soon as it has posted, with the attempt log's
own rule (``attempts.AccountWorker.settle``): it reads what Caducus recorded and closes the attempt sent, refused or failed. It never posts again: Caducus has a record of
an event it just handled, and the worker hands an event over again only when Caducus has none (it dedupes on the event id in any case).
"""
from __future__ import annotations

from typing import Any

from .attempts import AccountWorker
from .x_channel import CHANNEL

EVENT_PREFIX = "delivery:"
SETTLED_BY = "x function"


def delivery_of_event(event_id: str) -> str | None:
    """The Delivery id inside an attempt's Caducus event id (``channel.attempt_event_id``), or None for an event that is not a Delivery's attempt."""
    if not event_id.startswith(EVENT_PREFIX) or ":a" not in event_id:
        return None
    delivery, _, number = event_id[len(EVENT_PREFIX):].rpartition(":a")
    return delivery if delivery and number.isdigit() else None


def settle_after_post(deliveries: Any, transport: Any, event_id: str, *, now: str | None = None) -> dict[str, Any] | None:
    """Settle the X Delivery whose attempt ``event_id`` names. Returns the Delivery as written, or None when the event is not an X Delivery's attempt."""
    delivery = delivery_of_event(event_id)
    if delivery is None:
        return None
    row = deliveries.get(delivery)
    if row is None or row.get("channel") != CHANNEL:
        return None
    return AccountWorker(deliveries, transport, CHANNEL, row["accountId"]).settle(delivery, by=SETTLED_BY, now=now)
