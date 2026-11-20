"""A periodic list is a scheduled wake: its cadence, time and zone become the cron expression and zone of one schedule entry (slice N1).

The schedule reconciler (``agent_definitions/schedules.py``) keeps the entry; this module only says what each list wants. A list that is every-item wants none:
it is woken by a page going live or a rating changing.
"""
from __future__ import annotations

from typing import Any, Mapping

from .settings import PERIODIC, WEEKDAYS

#: Standard cron counts Sunday as 0.
_CRON_DAY = {name: str(position) for position, name in enumerate(WEEKDAYS)}


def cron_of(entry: Mapping[str, Any]) -> str:
    """The five-field cron expression for a periodic list's local time: every day, or on one weekday."""
    hour, minute = entry["sendAt"]["time"].split(":")
    day = _CRON_DAY[entry["sendAt"]["day"]] if entry["cadence"] == "weekly" else "*"
    return f"{int(minute)} {int(hour)} * * {day}"


def wanted(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """``{list id: {agent, cron, timeZone}}`` for each list that needs a clock."""
    return {list_id: {"agent": entry["agent"], "cron": cron_of(entry), "timeZone": entry["timeZone"]}
            for list_id, entry in sorted(document["lists"].items()) if entry["cadence"] in PERIODIC}
