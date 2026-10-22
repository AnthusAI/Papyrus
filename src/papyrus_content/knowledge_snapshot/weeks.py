"""ISO weeks as integers: week 0 starts on Monday 1970-01-05, so weeks subtract and compare like numbers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

EPOCH_MONDAY = date(1970, 1, 5)


def parse_day(value: str | date | datetime) -> date:
    """The UTC calendar day of a date, a datetime or an ISO string."""
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 10:
        return date.fromisoformat(text)
    return parse_day(datetime.fromisoformat(text.replace("Z", "+00:00")))


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_number(day: date) -> int:
    return (week_start(day) - EPOCH_MONDAY).days // 7


def week_monday(number: int) -> date:
    return EPOCH_MONDAY + timedelta(days=7 * number)


def week_label(number: int) -> str:
    """The ISO week label of a week number, for example ``2026-W43``."""
    year, week, _weekday = week_monday(number).isocalendar()
    return f"{year}-W{week:02d}"


def current_monday(today: date) -> date:
    return week_start(today)


def iso_timestamp(value: str | date | datetime) -> str:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
