"""Cadence families: a reader picks one cadence of the same items, so nobody gets an item twice (slice N2, PPY-a19b9d).

Lists that carry the same items at different cadences (every item, daily summary) form a family: they name the same ``family`` in the list settings. A list that
names none is its own family, so a curated weekly newsletter, which repeats items by design, is untouched by a reader's choice in another family.

The rule itself is Caducus's (0.4.0, ``caducus.notify.audience``: ``AudienceList.family``, ``AudienceSettings.move_effective_at``; docs/public-audiences.md in
AnthusAI/Caducus), applied where a reader's lists are written, so subscribing, confirming, saving preferences, importing and the one-click unsubscribe all hold it.
This module holds what is Papyrus's: which family a list is in, when a period starts, and the hook that says when a move takes effect.

* A membership records ``since``: when the reader joined that list. A move off a list records ``until``.
* A move takes effect at the **next period start** of the family's periodic list (``mover``), not at once. Until then the reader stays on the list they were on, so an
  item published after a noon switch and before the next period start still reaches them, through that list; the new list's first summary covers the period that starts
  then. Every item reaches the reader by exactly one route. A family with no periodic list has no period to wait for, so a move there is at once.
* An every-item Delivery goes to the members at the moment it is sent. A periodic Delivery goes to the members at the start of its period (``period_start``, passed as
  the event's ``audienceAsOf``), so a reader who has since moved off still gets the summary they were due.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .settings import PERIODIC, WEEKDAYS


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


def _local_time(entry: Mapping[str, Any]) -> time:
    hour, minute = entry["sendAt"]["time"].split(":")
    return time(int(hour), int(minute))


def next_period_start(entry: Mapping[str, Any], now: datetime) -> datetime:
    """The first scheduled time of a periodic list that is after ``now``: when the period that ends there is over and the next one begins.

    Counted on the list's own local calendar (``timeZone``), so a clock change does not move the local time of day. Returned as an aware moment in ``now``'s zone."""
    if entry["cadence"] not in PERIODIC:
        raise ValueError(f"A {entry['cadence']} list has no period; there is no next period start.")
    zone = ZoneInfo(entry["timeZone"])
    local = now.astimezone(zone).replace(tzinfo=None)
    candidate = datetime.combine(local.date(), _local_time(entry))
    if entry["cadence"] == "weekly":
        # datetime.weekday(): Monday is 0; WEEKDAYS starts at Sunday.
        wanted = (WEEKDAYS.index(entry["sendAt"]["day"]) - 1) % 7
        candidate += timedelta(days=(wanted - candidate.weekday()) % 7)
    while candidate <= local:
        candidate += timedelta(days=7 if entry["cadence"] == "weekly" else 1)
    return candidate.replace(tzinfo=zone).astimezone(now.tzinfo)


def mover(lists: Iterable[Mapping[str, Any]]) -> Callable[[str, datetime], datetime]:
    """Caducus's ``move_effective_at`` for a site: ``(family, now)`` to when a move in that family takes effect.

    ``lists`` are list entries that carry ``id`` and, as in the list settings, ``family``, ``cadence``, ``sendAt`` and ``timeZone``. A family's move takes effect at the
    next period start of its periodic list; a family with none moves at once (``now``). A family with two periodic lists is refused: the hook is asked only for the
    family, so it could not say which period the move waits for."""
    periodic: dict[str, Mapping[str, Any]] = {}
    for entry in lists:
        if entry.get("cadence") not in PERIODIC:
            continue
        family = family_of(entry["id"], entry)
        if family in periodic:
            raise ValueError(f"The family {family} has two periodic lists ({periodic[family]['id']} and {entry['id']}); a move would not know which period to wait for.")
        periodic[family] = entry

    def move_effective_at(family: str, now: datetime) -> datetime:
        entry = periodic.get(family)
        return now if entry is None else next_period_start(entry, now)

    return move_effective_at
