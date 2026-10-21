"""Group entries by calendar period (weeks with a Monday start, or months) or by the value of a front matter field (``field:<name>``)."""

from __future__ import annotations

import datetime as dt
import re

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


FIELD_PREFIX = "field:"
OTHER_LABEL = "Other"


def valid_group_by(by) -> bool:
    return by in GROUP_BYS or (isinstance(by, str) and by.startswith(FIELD_PREFIX) and bool(by[len(FIELD_PREFIX):].strip()))


def _group_by_field(entries, field: str) -> list[tuple[str, str, tuple]]:
    """Groups in order of first appearance (the listing's own order); entries without the field close the list as "Other"."""
    groups: dict[str, list] = {}
    labels: dict[str, str] = {}
    other: list = []
    for entry in entries:
        value = entry.data.get(field)
        label = str(value).strip() if value is not None and not isinstance(value, (list, dict)) else ""
        if not label:
            other.append(entry)
            continue
        key = slugify(label)
        labels.setdefault(key, label)
        groups.setdefault(key, []).append(entry)
    found = [(key, labels[key], tuple(groups[key])) for key in groups]
    return found + ([(slugify(OTHER_LABEL), OTHER_LABEL, tuple(other))] if other else [])


def slugify(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "group"


def group_entries(entries, by: str) -> list[tuple[str, str, tuple]]:
    """``[(key, label, entries)]`` newest group first, keeping the order of ``entries`` within a group; undated entries are dropped."""
    if by.startswith(FIELD_PREFIX):
        return _group_by_field(entries, by[len(FIELD_PREFIX):].strip())
    groups: dict[str, list] = {}
    for entry in entries:
        key = group_key(entry.date, by)
        if key:
            groups.setdefault(key, []).append(entry)
    return [(key, group_label(key, by), tuple(groups[key])) for key in sorted(groups, reverse=True)]
