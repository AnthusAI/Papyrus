"""Group entries by calendar period: weeks (Monday start) or months."""

from __future__ import annotations

import datetime as dt

GROUP_BYS = ("week", "month")


def group_key(date: str, by: str) -> str:
    """``YYYY-MM-DD`` of the Monday for ``week``, ``YYYY-MM`` for ``month``; empty for an undated entry."""
    try:
        day = dt.date.fromisoformat(date)
    except ValueError:
        return ""
    if by == "week":
        return (day - dt.timedelta(days=day.weekday())).isoformat()
    if by == "month":
        return f"{day:%Y-%m}"
    raise ValueError(f"group by must be one of {GROUP_BYS}")


def group_label(key: str, by: str) -> str:
    if by == "week":
        day = dt.date.fromisoformat(key)
        return f"Week of {day:%B} {day.day}, {day.year}"
    return f"{dt.date.fromisoformat(key + '-01'):%B %Y}"


def group_entries(entries, by: str) -> list[tuple[str, str, tuple]]:
    """``[(key, label, entries)]`` newest group first, keeping the order of ``entries`` within a group; undated entries are dropped."""
    groups: dict[str, list] = {}
    for entry in entries:
        key = group_key(entry.date, by)
        if key:
            groups.setdefault(key, []).append(entry)
    return [(key, group_label(key, by), tuple(groups[key])) for key in sorted(groups, reverse=True)]
