"""A five-field cron expression, as the scheduler runs it (slice C1, PPY-2a53cd). No dependencies, so the definition check can use it too."""
from __future__ import annotations

import re


class CronError(ValueError):
    """A cron expression the scheduler cannot express."""


# --- the cron expression ---------------------------------------------------------------------------------------

_DAY_NAMES = {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"}
_MONTH_NAMES = {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"}
_RANGES = {"minute": (0, 59), "hour": (0, 23), "day of the month": (1, 31), "month": (1, 12), "day of the week": (0, 7)}


def _number(text: str, field: str) -> int:
    low, high = _RANGES[field]
    value = int(text)
    if not low <= value <= high:
        raise CronError(f"{text} is not a {field} ({low} to {high})")
    return value


def _check_atom(atom: str, field: str) -> str:
    """A part that is not a plain number: ``*``, ``?``, a day or month name, or the scheduler's ``L`` and ``W`` forms (``L``, ``15W``, ``5L``)."""
    if atom in ("*", "?") or atom.upper() in _DAY_NAMES | _MONTH_NAMES or re.fullmatch(r"[0-9]*[LW]", atom.upper()):
        return atom.upper()
    raise CronError(f"{atom!r} is not understood in the {field} field")


def _day_of_week_number(text: str) -> str:
    """Standard cron counts Sunday as 0 (or 7) and Saturday as 6; the scheduler counts Sunday as 1 and Saturday as 7."""
    return str(_number(text, "day of the week") % 7 + 1)


def _translate_item(item: str, field: str) -> str:
    base, slash, step = item.partition("/")
    if slash and not step.isdigit():
        raise CronError(f"the step in {item!r} is not a number")
    nth_text = ""
    if field == "day of the week" and "#" in base:
        base, _, nth = base.partition("#")
        if not nth.isdigit() or not 1 <= int(nth) <= 5:
            raise CronError(f"{item!r}: the weekday of the month must be 1 to 5")
        nth_text = f"#{nth}"
    low_text, dash, high_text = base.partition("-")
    parts = [low_text, high_text] if dash else [low_text]
    translated: list[str] = []
    for part in parts:
        if part.isdigit():
            translated.append(_day_of_week_number(part) if field == "day of the week" else str(_number(part, field)))
        else:
            translated.append(_check_atom(part, field))
    if dash and all(part.isdigit() for part in translated) and int(translated[0]) > int(translated[1]):
        raise CronError(f"{item!r} runs past the end of the week or year; name the days in a list instead")
    return "-".join(translated) + nth_text + (f"/{step}" if slash else "")


def _translate_field(text: str, field: str) -> str:
    return ",".join(_translate_item(item, field) for item in text.split(","))


def scheduler_expression(cron: str) -> str:
    """The scheduler's ``cron(minute hour day-of-month month day-of-week year)`` for a five-field cron expression.

    Day of the week is renumbered (Sunday is 1 for the scheduler). The scheduler wants a ``?`` in the day of the month or the day of the week, so a
    schedule that names both (which standard cron reads as either) is refused, never guessed."""
    fields = cron.split()
    if len(fields) != 5:
        raise CronError("cron must be five fields: minute, hour, day of month, month, day of week")
    minute, hour, month_day, month, week_day = fields
    minute, hour, month = _translate_field(minute, "minute"), _translate_field(hour, "hour"), _translate_field(month, "month")
    month_day, week_day = _translate_field(month_day, "day of the month"), _translate_field(week_day, "day of the week")
    if month_day not in ("*", "?") and week_day not in ("*", "?"):
        raise CronError("a day of the month and a day of the week cannot both be named: the scheduler runs on a day that matches both, and cron on either")
    if month_day == "?" and week_day == "?":
        raise CronError("the day of the month and the day of the week cannot both be left open with ?")
    if week_day == "*" and month_day != "?":
        week_day = "?"
    elif month_day == "*" and week_day != "?":
        month_day = "?"
    return f"cron({minute} {hour} {month_day} {month} {week_day} *)"
