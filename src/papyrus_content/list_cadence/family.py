"""Cadence families: a reader picks one cadence of the same items, so nobody gets an item twice (slice N2, PPY-a19b9d).

Lists that carry the same items at different cadences (every item, daily summary) form a family: they name the same ``family`` in the list settings. A list that
names none is its own family, so a curated weekly newsletter, which repeats items by design, is untouched by a reader's choice in another family.

The rule is the audience's (``notifications/family.py`` enforces it where a reader's lists are written, so subscribing, confirming, saving preferences, importing and
the one-click unsubscribe all go through it). This module holds what needs no store: which family a list is in, who a Delivery may go to, and where a period starts.

* A membership records ``since``: when the reader joined that list.
* An every-item Delivery goes to the readers who are members at the moment it is sent. A reader who has moved to the daily summary is no longer one.
* A periodic Delivery goes to the readers who were members at the period's start (``period_start``). A reader who moves from every item to the daily summary at noon
  has had that day's earlier items once, as they happened, and has the first summary for the next period, not the one already under way.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .settings import PERIODIC


def family_of(list_id: str, entry: Mapping[str, Any] | None) -> str:
    """The family a list belongs to: the one it names, or its own id."""
    return (entry or {}).get("family") or list_id


def families(lists: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """``{list id: family}`` for every list of a settings document."""
    return {list_id: family_of(list_id, entry) for list_id, entry in lists.items()}


def conflicts(chosen: Sequence[str], family_by_list: Mapping[str, str]) -> list[str]:
    """The families that ``chosen`` holds more than one list of, in the order they are first met."""
    held: dict[str, int] = {}
    for list_id in chosen:
        family = family_by_list.get(list_id, list_id)
        held[family] = held.get(family, 0) + 1
    return [family for family, count in held.items() if count > 1]


def period_start(entry: Mapping[str, Any], scheduled_time: datetime) -> datetime:
    """When the period an issue covers began: one period before its scheduled time, counted on the list's own local calendar so a clock change does not move it.

    ``scheduled_time`` is an aware moment. A daily list's period is the day before, a weekly list's the week before."""
    if entry["cadence"] not in PERIODIC:
        raise ValueError(f"A {entry['cadence']} list has no period; it goes to the members at the moment of the send.")
    zone = ZoneInfo(entry["timeZone"])
    local = scheduled_time.astimezone(zone)
    step = timedelta(days=7 if entry["cadence"] == "weekly" else 1)
    return (local.replace(tzinfo=None) - step).replace(tzinfo=zone).astimezone(scheduled_time.tzinfo)
