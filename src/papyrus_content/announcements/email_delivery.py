"""The deliver side of email for one site: every email Delivery whose time has come goes through its account's one worker to Caducus (``email_channel.CaducusEmail``).

``CaducusEmail`` is built over the router and delivery log of the site's own notifications function (``notifications.runtime``), so a site without the email queue has none and
nothing is sent: an email Delivery waits, as a due Delivery of any channel does when its channel is not wired. A Delivery that may not go yet (its release or lock time, an edit
window, an approval) is left for its own timer's wake (``attempts.NotReleasable``).
"""
from __future__ import annotations

from typing import Any

from .attempts import AccountWorker, NotReleasable
from .deliveries import Deliveries
from .email_channel import CaducusEmail
from .records import EMAIL, now_iso

BY = "deliver"


def send_due_email(deliveries: Deliveries, email: CaducusEmail | None, now: str | None = None) -> list[dict[str, Any]]:
    """Send the email Deliveries that are due, each through the worker of its own account. Returns each Delivery as written; empty where the site has no email channel."""
    if email is None:
        return []
    now = now or now_iso()
    sent = []
    for row in deliveries.due(now):
        if row["channel"] != EMAIL:
            continue
        try:
            sent.append(AccountWorker(deliveries, email, EMAIL, row["accountId"]).send(row["id"], by=BY, now=now))
        except NotReleasable:
            continue
    return sent
