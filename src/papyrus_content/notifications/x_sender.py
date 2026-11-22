"""The consumer of the site's ``x`` queue: post one queued announcement (the counterpart of Caducus's ``email_sender.handle_batch``).

Caducus 0.4.0 ships the ``x`` channel and the routing that queues for it, and a consumer for the email queue only; this is the X one. A message names a delivery. The channel checks the delivery is
still queued (a repeat is a no-op), claims it before the request, and never repeats a request whose outcome is unknown without reading the account's recent posts first. When the outcome is
unknown (``UnknownOutcome``) or the account's token cannot be had the message goes back to the queue, so the next receive is the check before the retry; a refusal by X is recorded as failed and
is not retried.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Mapping

from caducus.notify.delivery_log import FINAL

QUEUED = "queued"   # Caducus's status of a delivery not yet handed to X


def handle_batch(store: Any, channel: Any, sqs_event: Mapping[str, Any], *, posted: Callable[[str], Any] | None = None) -> Dict[str, Any]:
    """``posted(event_id)`` runs once the event's delivery has left the queue (just posted, or a repeat of one already handled): the site closes its Delivery's attempt from Caducus's
    record (``announcements/settle_after_post.py``). A failure there returns the message, and the next receive settles again; posting is not repeated."""
    failures = []
    for record in sqs_event["Records"]:
        try:
            body = json.loads(record["body"])
            row = store.get("EVENT#" + body["eventId"], "DELIVERY#" + body["deliveryId"])
            if row is not None and row["status"] not in FINAL:
                channel.send(row)
                row = store.get("EVENT#" + body["eventId"], "DELIVERY#" + body["deliveryId"])
            if posted is not None and row is not None and row["status"] != QUEUED:
                posted(body["eventId"])
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
