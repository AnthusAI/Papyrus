"""The email channel as Papyrus uses it: a Delivery's attempt is one Caducus ``story.published`` event for the Delivery's lists (docs/announcement-records.md).

Caducus owns the transport and the record of each reader. Papyrus hands it one event for each attempt, ``delivery:<deliveryId>:a<N>``, naming the lists in the
Delivery's ``audience``; Caducus fans the event out over the confirmed subscribers of those lists, one delivery for each reader however many of the lists they are
on, and checks suppression and the reader's choices again when each reader's turn comes. Papyrus never sees an address: it reads the delivery log's rows, and the
Delivery keeps only their counts (``counts.py``).

A periodic Delivery (a daily or weekly summary) names ``audienceAsOf``, the start of the period it covers (``list_cadence/family.period_start`` of its release time):
its readers are the members of the list at that instant, so a reader who switched cadence since still gets the summary they were due and one who joined after it does
not. An every-item Delivery omits it: its readers are the members at the moment it is sent (docs/notifications.md, cadence families).

``CaducusEmail`` is both of the contracts the attempt log and the counts need: ``Transport`` (``submit``, ``delivery``) and ``RecordSource`` (``records``). It is
built over Caducus's own router and delivery log, the same two a site's notifications function runs, so the specs run the real pieces in memory.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from papyrus_content.list_cadence.family import period_start
from papyrus_content.list_cadence.settings import PERIODIC

from .attempts import ANSWER_FAILED, ANSWER_REFUSED, ANSWER_SENT, QUEUED, Answer
from .counts import event_refusal, reader_rows, total_cost
from .records import EMAIL, RecordError

KIND = "story.published"
PRODUCT = "papyrus"


class CaducusEmail:
    """``facts_of(delivery row, words)`` is what a message says: Caducus needs a ``title`` and takes a ``url`` and a ``summary``. ``lists`` are the site's list
    settings by list id (``cadence``, ``sendAt``, ``timeZone``), which say whether a Delivery's list is periodic."""

    def __init__(self, router: Any, log: Any, site_id: str, facts_of: Callable[[Mapping[str, Any], str], Mapping[str, Any]],
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), lists: Mapping[str, Mapping[str, Any]] | None = None):
        self.router, self.log, self.site_id, self.facts_of, self.clock = router, log, site_id, facts_of, clock
        self.lists = lists or {}

    def audience_as_of(self, row: Mapping[str, Any]) -> str | None:
        """The start of the period a periodic Delivery covers, or None for an every-item Delivery (its readers are the members now)."""
        periodic = [self.lists[list_id] for list_id in row["audience"] if self.lists.get(list_id, {}).get("cadence") in PERIODIC]
        if not periodic:
            return None
        if len(periodic) != len(row["audience"]):
            raise RecordError(f"{row['id']} mixes periodic and every-item lists; a summary names one list and has one period.")
        if len(periodic) != 1:
            raise RecordError(f"{row['id']} names {len(periodic)} periodic lists; a summary names one list and has one period.")
        released = datetime.fromisoformat(str(row["releaseAt"]).replace("Z", "+00:00"))
        return period_start(periodic[0], released).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def submit(self, row: Mapping[str, Any], text: str, event_id: str) -> None:
        """Hand the attempt's event to Caducus's router, which returns before anything is mailed. Handing over an event id twice does nothing the second time."""
        if row["channel"] != EMAIL:
            raise RecordError(f"{row['id']} is a {row['channel']} Delivery; this is the email channel.")
        if not row.get("audience"):
            raise RecordError(f"{row['id']} names no lists, so there is nobody to send it to.")
        as_of = self.audience_as_of(row)
        self.router.handle_detail({
            "schema": 1, "eventId": event_id, "kind": KIND, "product": PRODUCT, "site": self.site_id, "severity": "info",
            "occurredAt": self.clock().strftime("%Y-%m-%dT%H:%M:%SZ"), "lists": list(row["audience"]), "facts": dict(self.facts_of(row, text)),
            **({"audienceAsOf": as_of} if as_of else {}),
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
