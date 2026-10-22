"""Weekly counts and the change figure (PPY-eb5f28). Pure functions over week numbers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

WINDOW_WEEKS = 4
MINIMUM_PRIOR_FOR_PERCENT = 5
MINIMUM_HISTORY_FOR_PERCENT = 8
NEW_BELOW_WEEKS = 4
SERIES_SHORT = 8
SERIES_LONG = 26


@dataclass(frozen=True)
class Change:
    last4: int
    prior4: int
    percent: int | None

    def to_dict(self) -> dict:
        return {"last4": self.last4, "prior4": self.prior4, "percent": self.percent}


def series(counts: Mapping[int, int], as_of_week: int, length: int) -> list[int]:
    """``length`` weekly counts, oldest first; the last is the ``as_of_week``."""
    return [int(counts.get(as_of_week - offset, 0)) for offset in range(length - 1, -1, -1)]


def weekly_counts(week_numbers: Iterable[int]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for number in week_numbers:
        counts[number] = counts.get(number, 0) + 1
    return counts


def percent_change(last4: int, prior4: int) -> int | None:
    """``round(100 * (last4 - prior4) / prior4)`` with halves rounded away from zero, or ``None`` on a base under five."""
    if prior4 < MINIMUM_PRIOR_FOR_PERCENT:
        return None
    delta = last4 - prior4
    magnitude = (200 * abs(delta) + prior4) // (2 * prior4)
    return magnitude if delta >= 0 else -magnitude


def change_of(values: list[int], history: int | None = None) -> Change:
    """The last four weeks against the four before them, from a series that ends at the as-of week.

    With ``history`` (weeks since the first confirmed link) the percent is also withheld under eight weeks: the one
    place the cold-start rule for a percent lives."""
    last4 = sum(values[-WINDOW_WEEKS:])
    prior4 = sum(values[-2 * WINDOW_WEEKS : -WINDOW_WEEKS])
    percent = percent_change(last4, prior4)
    if history is not None and history < MINIMUM_HISTORY_FOR_PERCENT:
        percent = None
    return Change(last4=last4, prior4=prior4, percent=percent)


def weeks_of_history(first_week: int, as_of_week: int) -> int:
    return max(0, as_of_week - first_week + 1)


def is_new(history_weeks: int) -> bool:
    return history_weeks < NEW_BELOW_WEEKS
