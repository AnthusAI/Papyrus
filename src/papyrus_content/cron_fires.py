"""The times a five-field cron expression fires in a span of time, as the scheduler runs it (Today's Due today, PPY-b6d5ad).

Kept outside ``agent_definitions`` on purpose: Today runs in a function whose bundle is ``papyrus_content`` and the standard library, and that
package's ``__init__`` loads the definition files with PyYAML. A schedule is checked when its definition is registered
(``agent_definitions.cron.scheduler_expression``); this module only reads one.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

_RANGES = {"minute": (0, 59), "hour": (0, 23), "day of the month": (1, 31), "month": (1, 12), "day of the week": (0, 7)}


class CronError(ValueError):
    """A cron expression the scheduler cannot run."""


def _number(text: str, field: str) -> int:
    low, high = _RANGES[field]
    value = int(text)
    if not low <= value <= high:
        raise CronError(f"{text} is not a {field} ({low} to {high})")
    return value


def _refuse_both_days(cron: str) -> None:
    """Five fields, and not both a day of the month and a day of the week named: the scheduler runs on a day that matches both and cron on either."""
    fields = cron.split()
    if len(fields) != 5:
        raise CronError("cron must be five fields: minute, hour, day of month, month, day of week")
    if fields[2] not in ("*", "?") and fields[4] not in ("*", "?"):
        raise CronError("a day of the month and a day of the week cannot both be named")


_MONTH_NUMBERS = {name: number for number, name in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}
_DAY_NUMBERS = {name: number for number, name in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"])}


def _value(text: str, field: str) -> int:
    names = _MONTH_NUMBERS if field == "month" else _DAY_NUMBERS if field == "day of the week" else {}
    if text.upper() in names:
        return names[text.upper()]
    value = _number(text, field)
    return value % 7 if field == "day of the week" else value


def _plain_values(text: str, field: str) -> set[int]:
    """The values a field of numbers, names, ranges, steps and lists names. ``*`` and ``?`` name the whole range."""
    low, high = _RANGES[field]
    if field == "day of the week":
        high = 6
    found: set[int] = set()
    for item in text.split(","):
        base, slash, step = item.partition("/")
        if base in ("*", "?"):
            first, last = low, high
        elif "-" in base:
            start_text, _, end_text = base.partition("-")
            first, last = _value(start_text, field), _value(end_text, field)
        else:
            first = _value(base, field)
            last = high if slash else first
        found.update(range(first, last + 1, int(step) if slash else 1))
    return found


def _last_day(year: int, month: int) -> int:
    return monthrange(year, month)[1]


def _day_of_month_matches(text: str, day: date) -> bool:
    """A day-of-the-month field against one date, with the scheduler's ``L`` (the last day) and ``15W`` (the weekday nearest the 15th)."""
    last = _last_day(day.year, day.month)
    for item in text.split(","):
        upper = item.upper()
        if upper == "L":
            if day.day == last:
                return True
        elif upper.endswith("W"):
            wanted = min(int(upper[:-1]), last)
            weekday = day.replace(day=wanted).weekday()   # Monday is 0
            nearest = wanted - 1 if weekday == 5 else wanted + 1 if weekday == 6 else wanted
            nearest = wanted + 2 if nearest < 1 else wanted - 2 if nearest > last else nearest
            if day.day == nearest:
                return True
        elif day.day in _plain_values(item, "day of the month"):
            return True
    return False


def _day_of_week_matches(text: str, day: date) -> bool:
    """A day-of-the-week field against one date, with ``5#3`` (the third Friday) and ``5L`` (the last Friday)."""
    sunday_first = (day.weekday() + 1) % 7
    for item in text.split(","):
        upper = item.upper()
        if "#" in upper:
            weekday, _, nth = upper.partition("#")
            if sunday_first == _value(weekday, "day of the week") and (day.day - 1) // 7 + 1 == int(nth):
                return True
        elif upper.endswith("L") and upper != "L":
            if sunday_first == _value(upper[:-1], "day of the week") and day.day + 7 > _last_day(day.year, day.month):
                return True
        elif sunday_first in _plain_values(item, "day of the week"):
            return True
    return False


def fires_between(cron: str, time_zone: str, start: datetime, end: datetime) -> list[datetime]:
    """Every instant (UTC) in ``start`` .. ``end`` (end excluded) at which a five-field ``cron`` in ``time_zone`` fires, as the scheduler runs it:
    the local expression in the named zone, so a clock change keeps the local time. A local time a clock change skips does not exist and does not fire."""
    _refuse_both_days(cron)
    minute_text, hour_text, month_day_text, month_text, week_day_text = cron.split()
    zone = ZoneInfo(time_zone)
    minutes, hours, months = _plain_values(minute_text, "minute"), _plain_values(hour_text, "hour"), _plain_values(month_text, "month")
    found = []
    day, last_day = start.astimezone(zone).date(), end.astimezone(zone).date()
    while day <= last_day:
        named_month_day, named_week_day = month_day_text not in ("*", "?"), week_day_text not in ("*", "?")
        day_matches = (_day_of_month_matches(month_day_text, day) if named_month_day
                       else _day_of_week_matches(week_day_text, day) if named_week_day else True)
        if day.month in months and day_matches:
            for hour in sorted(hours):
                for minute in sorted(minutes):
                    local = datetime.combine(day, time(hour, minute), zone)
                    instant = local.astimezone(timezone.utc)
                    if instant.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
                        continue
                    if start <= instant < end:
                        found.append(instant)
        day += timedelta(days=1)
    return sorted(found)
