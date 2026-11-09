"""The time windows of a topic run: whole days, counted back from a day, on the Reference's SOURCE date.

A window is ``days`` days ending on (and including) ``end``. The previous window of equal length ends the day before this one starts. Source
dates are ISO text (``2026-11-05`` or ``2026-11-05T09:30:00Z``), so a window is asked of the date index as two strings: the first day, and the
last day's final instant. Text sorts the same way the dates do.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

PRESETS = {"7d": 7, "14d": 14, "28d": 28}
DEFAULT_WINDOW = "14d"
DAY_END = "T23:59:59.999Z"


@dataclass(frozen=True)
class Window:
    start: date   # the first day, included
    end: date     # the last day, included
    days: int

    @property
    def low(self) -> str:
        """The smallest source date text in the window."""
        return self.start.isoformat()

    @property
    def high(self) -> str:
        """The largest source date text in the window."""
        return self.end.isoformat() + DAY_END

    def contains(self, source_date: str | None) -> bool:
        """Whether a Reference's source date text is inside the window (the same comparison the index makes)."""
        return bool(source_date) and self.low <= str(source_date) <= self.high

    def describe(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "days": self.days}


def parse_day(text: str | None, *, today: date | None = None) -> date:
    """``text`` as a day (``YYYY-MM-DD``); today in UTC when it is empty."""
    if not text:
        return today or datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError as error:
        raise ValueError(f"{text!r} is not a day; use YYYY-MM-DD.") from error


def current_window(name: str | None, as_of: date) -> Window:
    days = PRESETS[name or DEFAULT_WINDOW]
    return Window(start=as_of - timedelta(days=days - 1), end=as_of, days=days)


def previous_window(window: Window) -> Window:
    end = window.start - timedelta(days=1)
    return Window(start=end - timedelta(days=window.days - 1), end=end, days=window.days)
