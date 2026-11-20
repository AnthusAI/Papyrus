"""The time-bucketed quality ranking: the one order every list of Stories and References follows.

Newest window first, and inside a window the human rating before the model's guess. The rules, with their reasons, are written once in
``docs/quality-ranking.md`` and specified in ``features_backend/references/quality-ranking.feature``. This module is only the algorithm: it knows nothing of Stories,
References, pages or snapshots, and takes accessors for the four things it reads (stars, confidence, arrival, key) and one for the date an item is bucketed by.

**The order inside a window** (:func:`rank`), smaller first:

1. three, four and five stars, the most stars first;
2. nobody rated it: the highest Cyclotron confidence first, and after every scored one those with no confidence at all. A missing confidence is not a number (not
   0.5, and it never ties with a real 0.5): it ranks below every scored item;
3. one and two stars, the most stars first. A low rating is a real downgrade and beats a confident prediction.

Equal items go to the newest arrival, then to the key. Stars are private; the order reveals relative standing and never a count.

**The windows** (:func:`rolling_age`): rolling, in UTC, counted back from ``as_of``, a day and not a time. ``week`` is the last seven days, the seven before that,
and so on; ``day`` is the last day, the day before, and so on. An item with no usable date is in the oldest window; one dated after ``as_of`` is in the newest.
Nothing is dropped: an older window follows the newer ones, each ranked inside itself. A rating never changes an item's window (its date does not move) and time
alone moves it, so the order can change only on the day an item crosses a window.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime, timezone
from typing import Any, TypeVar

T = TypeVar("T")

BUCKETS = ("day", "week")
BUCKET_DAYS = {"day": 1, "week": 7}
HIGH_STARS = (5, 4, 3)
LOW_STARS = (2, 1)
OLDEST_WINDOW = 2**31


def valid_stars(value: Any) -> int | None:
    """A rating from one to five, or None (unrated, or not a rating)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        return None
    return int(value) if 1 <= int(value) <= 5 else None


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _tier(stars: int | None, confidence: float | None) -> tuple[int, int, float]:
    """The part of the order before the tie-breaks, smaller first: rated up, then unrated by confidence (the unscored last), then rated down."""
    if stars in HIGH_STARS:
        return (0, 0, -float(stars))
    if stars in LOW_STARS:
        return (2, 0, -float(stars))
    if confidence is None:
        return (1, 1, 0.0)
    return (1, 0, -confidence)


def rank(
    items: Iterable[T],
    *,
    stars: Callable[[T], int | None],
    confidence: Callable[[T], float | None] = lambda _item: None,
    newest: Callable[[T], Any] | None = None,
    key: Callable[[T], Any] | None = None,
) -> list[T]:
    """``items`` in the shared order. ``stars`` and ``confidence`` say where each signal lives (a value that is not a rating is unrated). Equal items go to the
    greatest ``newest`` and then the smallest ``key``; without either, equal items keep the order they came in."""
    chosen = list(items)
    if key is not None:
        chosen.sort(key=key)
    if newest is not None:
        chosen.sort(key=newest, reverse=True)
    chosen.sort(key=lambda item: _tier(valid_stars(stars(item)), confidence(item)))
    return chosen


def instant_of(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def rolling_age(moment: Any, bucket: str, as_of: date) -> int:
    """How many whole ``bucket`` windows before ``as_of`` the date falls: 0 is the last day (or last seven days), 1 the window before it, and so on.

    ``moment`` is an ISO timestamp or a plain ``YYYY-MM-DD`` date, read in UTC. A date after ``as_of`` is in window 0; no usable date is the oldest window.
    """
    instant = instant_of(moment)
    if instant is None:
        return OLDEST_WINDOW
    days = (as_of - instant.astimezone(timezone.utc).date()).days
    return max(0, days) // BUCKET_DAYS[bucket]


def in_windows(items: Iterable[T], *, moment: Callable[[T], Any], bucket: str, as_of: date) -> list[T]:
    """``items`` with the newest window first. The sort is stable, so inside a window items keep the order they came in: pass them already ranked."""
    return sorted(items, key=lambda item: rolling_age(moment(item), bucket, as_of))


def rank_in_buckets(
    items: Iterable[T],
    *,
    stars: Callable[[T], int | None],
    moment: Callable[[T], Any],
    bucket: str,
    as_of: date,
    confidence: Callable[[T], float | None] = lambda _item: None,
    newest: Callable[[T], Any] | None = None,
    key: Callable[[T], Any] | None = None,
) -> list[T]:
    """The whole algorithm: the newest window first and, inside each, :func:`rank`. Nothing is dropped."""
    return in_windows(rank(items, stars=stars, confidence=confidence, newest=newest, key=key), moment=moment, bucket=bucket, as_of=as_of)
