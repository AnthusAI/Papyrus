"""The publication's own publishing rhythm, and the time it suggests for the next scheduled Story (PPY-92164e; plan: docs/plans/scheduled-publishing-and-announcements.md,
"Spreading out: slot suggestion").

Two small facts are kept, each raised once per *first* publication of a Story (O(1) per publish; a new version of a Story that is already out changes nothing):

* a count of first publications for each hour of the week in the publication's time zone (168 counters, Monday 00:00 is hour 0), and
* the total count with the moment of the first one.

They live in one item of the projection lock table (the small-state table the site's content-actions function already reads and updates), written with one atomic
``UpdateItem`` that adds one to the counters, so two publishes at once both count and nothing reads the Stories. The key names the publication's zone, so a zone
change starts a new history in the new zone's hours rather than mixing two zones' hours.

The suggestion is the earliest hour after both *now* and *the latest scheduled time plus the publication's mean gap between first publications* (the span from the
first one to now, divided by the count) whose hour of the week has the most past publications within the following day. No fixed spacing and no fixed window: a
publication that publishes hourly gets hourly slots, one that publishes twice a week gets that. With no history there is no suggestion, and the answer says why.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

HOURS_IN_WEEK = 7 * 24
KEY_PREFIX = "publication-cadence#"
NO_HISTORY = "No suggestion yet: this publication has no publishing history."
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def hour_of_week(moment: datetime, zone: ZoneInfo) -> int:
    """0 to 167 in the publication's zone, Monday 00:00 being 0."""
    local = moment.astimezone(zone)
    return local.weekday() * 24 + local.hour


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(TIME_FORMAT)


def _parse(text: str) -> datetime:
    return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Cadence:
    """What the publication's first publications look like: ``hours`` maps an hour of the week to how many first publications fell in it."""

    total: int
    first_at: datetime
    hours: Mapping[int, int]

    def mean_gap(self, now: datetime) -> timedelta:
        """The span from the first first-publication to now, divided by how many there have been."""
        return max(now - self.first_at, timedelta(0)) / self.total


@dataclass(frozen=True)
class Suggestion:
    at: datetime
    publications: int
    mean_gap_hours: float


class CadenceStore:
    """The cadence of one publication in one zone, in an item of the lock table."""

    def __init__(self, table: Any, scope: str, zone_name: str) -> None:
        self.table = table
        self.zone_name = zone_name
        self.zone = ZoneInfo(zone_name)
        self.key = f"{KEY_PREFIX}{scope}#{zone_name}"

    def record_first_publication(self, at: datetime) -> int:
        """Count one first publication at ``at``. Returns the hour of the week it was counted in."""
        hour = hour_of_week(at, self.zone)
        self.table.update_item(
            Key={"publication": self.key},
            UpdateExpression="SET #first = if_not_exists(#first, :at) ADD #total :one, #hour :one",
            ExpressionAttributeNames={"#first": "firstAt", "#total": "total", "#hour": f"h{hour}"},
            ExpressionAttributeValues={":at": _utc_text(at), ":one": 1},
        )
        return hour

    def read(self) -> Cadence | None:
        item = self.table.get_item(Key={"publication": self.key}, ConsistentRead=True).get("Item")
        if not item or not int(item.get("total") or 0):
            return None
        hours = {index: int(item[f"h{index}"]) for index in range(HOURS_IN_WEEK) if int(item.get(f"h{index}") or 0) > 0}
        return Cadence(total=int(item["total"]), first_at=_parse(str(item["firstAt"])), hours=hours)


def cadence_from_environment(zone_name: str | None, environ: Mapping[str, str] | None = None, *, table: Any = None) -> CadenceStore | None:
    """The site's cadence store, or None where there is no lock table (a local run) or no time zone (the site does not schedule, and nothing needs the hours)."""
    from .projection.lease import lock_table_from_environment
    from .projection.runtime import SITE_BUCKET_ENV, store_name

    environment = os.environ if environ is None else environ
    if not zone_name or not (environment.get(SITE_BUCKET_ENV) or "").strip():
        return None
    found = table if table is not None else lock_table_from_environment(environment)
    return CadenceStore(found, store_name(environment), zone_name) if found is not None else None


def suggest_time(cadence: Cadence, *, now: datetime, latest_scheduled: datetime | None, zone_name: str) -> Suggestion:
    """The next suggested time: after now and after the latest scheduled time plus the mean gap, in the hour of the following day the publication has used most.

    The window is the 24 hours from the first whole hour after both bounds; the busiest hour of the week in it wins and the earliest of equals. A window with no
    past publication in any of its hours moves on a day at a time (the busiest hours of a week-day publication are not on a Sunday), so a publication with any
    history always gets a suggestion within two weeks of the earliest hour."""
    zone = ZoneInfo(zone_name)
    gap = cadence.mean_gap(now)
    earliest = max(now, (latest_scheduled + gap) if latest_scheduled else now)
    start = earliest.astimezone(zone).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    start = start.astimezone(timezone.utc)
    for day in range(14):   # two weeks: an hour of the week the spring clock change skips comes round again the week after
        window = [start + timedelta(hours=24 * day + step) for step in range(24)]
        best = max(window, key=lambda moment: (cadence.hours.get(hour_of_week(moment, zone), 0), -moment.timestamp()))
        if cadence.hours.get(hour_of_week(best, zone), 0) > 0:
            return Suggestion(at=best.replace(microsecond=0), publications=cadence.total, mean_gap_hours=round(gap.total_seconds() / 3600, 1))
    raise AssertionError("a cadence with a publication has an hour of the week in every fourteen days")
