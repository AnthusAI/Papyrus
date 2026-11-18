"""The email channel as Papyrus uses it: a Delivery's attempt is one Caducus ``story.published`` event for the Delivery's lists (docs/announcement-records.md).

Caducus owns the transport and the record of each reader. Papyrus hands it one event for each attempt, ``delivery:<deliveryId>:a<N>``, naming the lists in the
Delivery's ``audience``; Caducus fans the event out over the confirmed subscribers of those lists, one delivery for each reader however many of the lists they are
on, and checks suppression and the reader's choices again when each reader's turn comes. Papyrus never sees an address: it reads the delivery log's rows, and the
Delivery keeps only their counts (``counts.py``).

``CaducusEmail`` is both of the contracts the attempt log and the counts need: ``Transport`` (``submit``, ``delivery``) and ``RecordSource`` (``records``). It is
built over Caducus's own router and delivery log, the same two a site's notifications function runs, so the specs run the real pieces in memory.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from .attempts import ANSWER_FAILED, ANSWER_REFUSED, ANSWER_SENT, QUEUED, Answer
from .counts import event_refusal, reader_rows, total_cost
from .records import EMAIL, RecordError

KIND = "story.published"
PRODUCT = "papyrus"


class CaducusEmail:
    """``facts_of(delivery row, words)`` is what a message says: Caducus needs a ``title`` and takes a ``url`` and a ``summary``."""

    def __init__(self, router: Any, log: Any, site_id: str, facts_of: Callable[[Mapping[str, Any], str], Mapping[str, Any]],
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.router, self.log, self.site_id, self.facts_of, self.clock = router, log, site_id, facts_of, clock

    def submit(self, row: Mapping[str, Any], text: str, event_id: str) -> None:
        """Hand the attempt's event to Caducus's router, which returns before anything is mailed. Handing over an event id twice does nothing the second time."""
        if row["channel"] != EMAIL:
            raise RecordError(f"{row['id']} is a {row['channel']} Delivery; this is the email channel.")
        if not row.get("audience"):
            raise RecordError(f"{row['id']} names no lists, so there is nobody to send it to.")
        self.router.handle_detail({
            "schema": 1, "eventId": event_id, "kind": KIND, "product": PRODUCT, "site": self.site_id, "severity": "info",
            "occurredAt": self.clock().strftime("%Y-%m-%dT%H:%M:%SZ"), "lists": list(row["audience"]), "facts": dict(self.facts_of(row, text)),
        })

    def records(self, event_id: str) -> Sequence[Mapping[str, Any]]:
        return self.log.for_event(event_id)

    def delivery(self, event_id: str) -> Answer | None:
        """What Caducus's rows say about the attempt: nothing yet, readers still queued, a refusal of the whole event, or that every reader's turn has come.

        An attempt is answered ``sent`` when nobody is left queued and at least one reader was mailed or none failed (a send whose readers were all suppressed or
        had turned the list off still ran: its counts say so). It is answered ``failed`` only when readers were tried and every one failed."""
        rows = self.records(event_id)
        refusal = event_refusal(rows)
        if refusal:
            return Answer(ANSWER_REFUSED, code=refusal)
        readers = reader_rows(rows)
        if not readers:
            return None
        if any(row["status"] == "queued" for row in readers):
            return Answer(QUEUED)
        mailed = [row for row in readers if row["status"] in ("sent", "delayed", "delivered", "bounced", "complained")]
        failed = [row for row in readers if row["status"] in ("failed", "rejected", "refused", "dead_lettered")]
        if failed and not mailed:
            return Answer(ANSWER_FAILED, code=str(failed[0].get("reason") or "failed"), cost=total_cost([rows]))
        return Answer(ANSWER_SENT, cost=total_cost([rows]))
