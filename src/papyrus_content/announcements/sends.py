"""The day's email sends, one line each, for Today (docs/design/always-on-agents-architecture.md, slice N8).

A send is an email Delivery of an Announcement that was released inside the day. It is read by index only: the released (and withdrawn) Announcements whose release
time falls in the day, each one's Deliveries, and each one's Stories (for the item count). A line holds the lists, the number of items, the Delivery's counts as
Caducus's records added them up, what it cost and where the send stands, in words with a mark. It holds no reader, no address and no text.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..tenancy import rows_for_tenant
from . import links
from .counts import COUNT_KEYS, counts_of, counts_text
from .decisions import INDEX_BY_STATE
from .deliveries import INDEX_BY_ANNOUNCEMENT
from .records import (
    BLOCKED, DELIVERY_WITHDRAWN, DECISION_MODEL, DELIVERY_MODEL, DRAFTED, DRY_RUN, EMAIL, FAILED, READY, RELEASED, SENDING, SENT, SUPERSEDED, WITHDRAWN, attempt_log, utc,
)

#: Where a send stands, as a mark and its words. The words always come with the mark.
STATE_SHOWN: dict[str, tuple[str, str]] = {
    SENT: ("✓", "Sent"), SENDING: ("…", "Sending"), READY: ("…", "Ready, waiting for its time"), DRAFTED: ("…", "Being written"), BLOCKED: ("!", "Waiting"),
    FAILED: ("✗", "Failed"), DRY_RUN: ("–", "Dry run, nothing sent"), DELIVERY_WITHDRAWN: ("–", "Withdrawn"), SUPERSEDED: ("–", "Corrected"),
}
NO_COST = "no cost recorded"


def sends_of_day(client: Any, bounds: Mapping[str, str]) -> list[dict[str, Any]]:
    """The email sends of the day, oldest first. Two index queries (released and withdrawn Announcements by release time) and, for each Announcement, one for its
    Deliveries and one for its Stories."""
    start, end = utc(bounds["start"]), utc(bounds["end"])
    decisions: list[dict[str, Any]] = []
    for state in (RELEASED, WITHDRAWN):
        rows = client.list_by_index(INDEX_BY_STATE, state, sort_condition={"between": [start, end]})
        decisions.extend(row for row in rows_for_tenant(DECISION_MODEL, getattr(client, "tenant_id", None), rows) if start <= row["releaseAt"] < end)
    lines: list[dict[str, Any]] = []
    for decision in sorted(decisions, key=lambda row: (row["releaseAt"], row["id"])):
        deliveries = rows_for_tenant(DELIVERY_MODEL, getattr(client, "tenant_id", None), client.list_by_index(INDEX_BY_ANNOUNCEMENT, decision["id"]))
        live = _live(deliveries)
        email = [row for row in live if row["channel"] == EMAIL]
        if not email:
            continue
        items = len(links.stories_of_announcement(client, decision["id"]))
        lines.extend(send_line(decision, row, items) for row in email)
    return lines


def _live(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The highest generation of each channel and account: a corrected Delivery is not a second send."""
    newest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["channel"], row["accountId"])
        if key not in newest or int(row["generation"]) > int(newest[key]["generation"]):
            newest[key] = row
    return list(newest.values())


def send_line(decision: Mapping[str, Any], delivery: Mapping[str, Any], items: int) -> dict[str, Any]:
    """One send as Today lists it."""
    mark, words = STATE_SHOWN[delivery["state"]]
    last = attempt_log(delivery)[-1] if attempt_log(delivery) else None
    counts = counts_of(delivery)
    return {
        "deliveryId": delivery["id"], "announcementId": decision["id"], "kind": decision["kind"], "releasedAt": decision["releaseAt"],
        "lists": list(delivery.get("audience") or []), "items": items, "state": delivery["state"], "stateShown": f"{mark} {words}", "stateWords": words,
        "attempts": len(attempt_log(delivery)), "lastAttempt": last["outcome"] if last else None,
        "counts": {key: counts[key] for key in COUNT_KEYS}, "countsText": counts_text(counts), "cost": delivery.get("cost"),
    }
