"""The counts of an email Delivery, taken from Caducus's records (docs/announcement-records.md, "Counts").

Caducus keeps the record of each reader: one delivery-log row for each reader the event reached, with a status that only moves forward. The email Delivery holds
**counts only**, never a reader, an address or a pseudonym, and the counts are always recomputed from Caducus's rows, never added to. Reading the same rows again
changes nothing, so the counts match the transport's records whenever they are refreshed.

The eight counts, each a number of readers:

* ``queued``      Caducus has the reader and has not mailed them yet.
* ``sent``        the provider accepted the message. A message that was later delivered, bounced or complained about is still one that was sent.
* ``delivered``, ``bounced``, ``complained``   what the provider reported about a sent message.
* ``failed``      mailing the reader failed or was rejected.
* ``suppressed``  the reader was suppressed (a permanent bounce or a complaint) when their turn came, so nothing was mailed.
* ``skipped``     the reader turned this list off, or was no longer confirmed, when their turn came, so nothing was mailed.

A reader who is not a confirmed subscriber of any list of the event is never in the fan-out, so Caducus records nothing about them and no count has them: they are
never mailed. A reader who is on two lists of one Delivery is one reader: Caducus keys a message by event, reader and channel.

Every attempt of the Delivery is an event of its own (``delivery:<id>:a<N>``), so a reader can have a row in more than one. A reader is counted once, by the row that
says most about them: a message that was sent beats one that was not.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Protocol, Sequence

from .deliveries import Conflict, Deliveries
from .records import EMAIL, RecordError, attempt_log, json_object, now_iso

COUNT_KEYS = ("queued", "sent", "failed", "suppressed", "skipped", "delivered", "bounced", "complained")

# Caducus's delivery-log statuses, grouped by what each means for the counts.
SENT_STATUSES = ("sent", "delayed", "delivered", "bounced", "complained")
FAILED_STATUSES = ("failed", "rejected", "refused", "dead_lettered")
#: The recipient key of a refusal that belongs to the whole event (no audience, an invalid event), not to a reader.
EVENT_LEVEL_RECIPIENT = "NONE"
# How far a sent message got, lowest to highest: the order of Caducus's own ranks.
PROGRESS = {"sent": 1, "delivered": 2, "delayed": 3, "bounced": 4, "complained": 4}


class RecordSource(Protocol):
    """Caducus's delivery log for one event: every reader's row. Reads only."""

    def records(self, event_id: str) -> Sequence[Mapping[str, Any]]: ...


def reader_rows(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The rows that are about a reader, not about the event as a whole."""
    return [row for row in rows if row.get("recipientKey") != EVENT_LEVEL_RECIPIENT]


def event_refusal(rows: Sequence[Mapping[str, Any]]) -> str | None:
    """Why Caducus refused the whole event, in its words, or None."""
    for row in rows:
        if row.get("recipientKey") == EVENT_LEVEL_RECIPIENT and row.get("status") == "refused":
            return str(row.get("reason") or "refused")
    return None


def _best(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """The row that says most about one reader: the furthest sent message, else the latest row."""
    sent = [row for row in rows if row["status"] in SENT_STATUSES]
    return max(sent, key=lambda row: PROGRESS[row["status"]]) if sent else rows[-1]


def tally(rows_by_event: Sequence[Sequence[Mapping[str, Any]]]) -> dict[str, int]:
    """The eight counts of readers, from the rows of each attempt's event (oldest attempt first)."""
    by_reader: dict[str, list[Mapping[str, Any]]] = {}
    for rows in rows_by_event:
        for row in reader_rows(rows):
            by_reader.setdefault(row["recipientKey"], []).append(row)
    counts = dict.fromkeys(COUNT_KEYS, 0)
    for rows in by_reader.values():
        status = _best(rows)["status"]
        if status == "queued":
            counts["queued"] += 1
        elif status in SENT_STATUSES:
            counts["sent"] += 1
            if status in ("delivered", "bounced", "complained"):
                counts[status] += 1
        elif status in FAILED_STATUSES:
            counts["failed"] += 1
        elif status == "suppressed":
            counts["suppressed"] += 1
        elif status == "skipped_preference":
            counts["skipped"] += 1
        else:
            raise RecordError(f"An email Delivery has no count for the Caducus status {status!r}.")
    return counts


def total_cost(rows_by_event: Sequence[Sequence[Mapping[str, Any]]]) -> str | None:
    """What Caducus charged for every row of the Delivery's events, as a decimal string, or None when nothing was charged."""
    charged = [row for rows in rows_by_event for row in rows if row.get("cost") is not None]
    if not charged:
        return None
    currencies = {row.get("costCurrency") for row in charged}
    if len(currencies) != 1:
        raise RecordError(f"A Delivery's cost is in one currency; Caducus charged in {', '.join(sorted(str(c) for c in currencies))}.")
    return str(sum((Decimal(str(row["cost"])) for row in charged), Decimal(0)))


def counts_of(row: Mapping[str, Any]) -> dict[str, int]:
    """The counts on a Delivery row, all eight, zero where none are recorded."""
    stored = json_object(row.get("counts"))
    return {key: int(stored.get(key) or 0) for key in COUNT_KEYS}


def counts_text(counts: Mapping[str, int]) -> str:
    """``3 sent, 1 suppressed``: every count above zero, in words. Nothing counted reads ``no readers yet``."""
    parts = [f"{counts[key]} {key}" for key in COUNT_KEYS if counts.get(key)]
    return ", ".join(parts) if parts else "no readers yet"


def is_settled(counts: Mapping[str, int]) -> bool:
    """Whether Caducus has nothing left to mail for the Delivery. The other counts can still move, because the provider reports delivery, bounces and complaints later."""
    return not counts.get("queued")


class DeliveryCounts:
    def __init__(self, deliveries: Deliveries):
        self.deliveries = deliveries

    def refresh(self, delivery: str, source: RecordSource, *, by: str, now: str | None = None) -> dict[str, Any]:
        """Recompute the Delivery's counts (and cost) from Caducus's rows of every attempt, and write them when they changed. Returns the Delivery."""
        now = now or now_iso()
        while True:
            row = self.deliveries.get(delivery)
            if row is None:
                raise RecordError(f"There is no Delivery {delivery}.")
            if row["channel"] != EMAIL:
                raise RecordError(f"{delivery} is a {row['channel']} Delivery; only an email Delivery has counts, because only email has a record for each reader.")
            events = [entry["eventId"] for entry in attempt_log(row)]
            rows_by_event = [list(source.records(event_id)) for event_id in events]
            counts, cost = tally(rows_by_event), total_cost(rows_by_event)
            unchanged = counts_of(row) == counts if row.get("counts") else not any(counts.values())   # no record yet and nothing to record is not a change
            if unchanged and cost == row.get("cost"):
                return row
            try:
                return self.deliveries.record_counts(row, counts, cost, by=by, now=now)
            except Conflict:
                continue
