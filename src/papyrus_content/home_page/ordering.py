"""The one order the public home page puts References in: an editor's rating first, then the Cyclotron's confidence.

Human ratings are a stronger signal than a prediction, so they come first and, where they exist, override it:

1. three, four and five stars, the most stars first;
2. References nobody rated, the highest Cyclotron confidence first, and after them the ones with no confidence at all (an accepted Reference the
   Cyclotron never scored). A missing confidence is not a number: it is not 0.5 and does not tie with a real 0.5, it simply ranks below every scored one;
3. one and two stars, the most stars first, so a low rating is a real downgrade and beats a confident prediction.

Equal References go to the newest arrival, then to the key. Stars are private: they change this order and are never printed or published. The public
snapshot (``_data/home-page/references.json``) is readable by anyone, so the stars themselves cannot be in it. ``rank_records`` turns the order into
``rank``, a position (1 is first) in this order over every public Reference, and the build orders by that number (``order_public_records``). A position is
not a star count, and a rating that moves nothing changes nothing in the file. The order itself reveals relative standing, which is its purpose; it never
reveals how many stars anyone gave.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any, TypeVar

T = TypeVar("T")

HIGH_STARS = (5, 4, 3)
LOW_STARS = (2, 1)
RANK_FIELD = "rank"
BUCKETS = ("day", "week")


def valid_stars(value: Any) -> int | None:
    """A rating from one to five, or None (unrated, or not a rating)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        return None
    return int(value) if 1 <= int(value) <= 5 else None


def _primary(stars: int | None, confidence: float | None) -> tuple[int, int, float]:
    """The part of the order before the tie-breaks, smaller first: rated up, then unrated by confidence (the unscored last), then rated down."""
    if stars in HIGH_STARS:
        return (0, 0, -float(stars))
    if stars in LOW_STARS:
        return (2, 0, -float(stars))
    if confidence is None:
        return (1, 1, 0.0)
    return (1, 0, -confidence)


def ordered(
    items: Iterable[T],
    *,
    stars: Callable[[T], int | None],
    confidence: Callable[[T], float | None],
    newest: Callable[[T], str],
    key: Callable[[T], str],
) -> list[T]:
    """``items`` in the shared order. The accessors say where each signal lives, so the export (which has the stars) and the build (which does not) share this."""
    chosen = sorted(items, key=key)
    chosen.sort(key=newest, reverse=True)
    chosen.sort(key=lambda item: _primary(stars(item), confidence(item)))
    return chosen


def confidence_of(record: Mapping[str, Any]) -> float | None:
    """The record's confidence, or None when it has none (never a stand-in number)."""
    value = record.get("confidence")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _text(record: Mapping[str, Any], name: str) -> str:
    value = record.get(name)
    return value if isinstance(value, str) else ""


def rank_records(entries: Iterable[tuple[Mapping[str, Any], int | None]]) -> dict[str, int]:
    """``{public key: position}`` for ``(public record, stars)`` pairs: 1 is the best. The stars are read here and never leave."""
    pairs = list(entries)
    found = ordered(pairs, stars=lambda pair: pair[1], confidence=lambda pair: confidence_of(pair[0]), newest=lambda pair: _text(pair[0], "arrivedAt"), key=lambda pair: _text(pair[0], "key"))
    return {_text(pair[0], "key"): position for position, pair in enumerate(found, start=1)}


def has_ranks(records: Iterable[Mapping[str, Any]]) -> bool:
    chosen = list(records)
    return bool(chosen) and all(isinstance(record.get(RANK_FIELD), int) and not isinstance(record.get(RANK_FIELD), bool) for record in chosen)


def order_public_records(records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Public records in the shared order. A record carries its ``rank`` when the snapshot was written with ratings known; a snapshot written before ranks
    existed has none, and its records are ordered as unrated References (confidence, the unscored last, newest, key)."""
    chosen = list(records)
    if has_ranks(chosen):
        return sorted(chosen, key=lambda record: (record[RANK_FIELD], _text(record, "key")))
    return ordered(chosen, stars=lambda _record: None, confidence=confidence_of, newest=lambda record: _text(record, "arrivedAt"), key=lambda record: _text(record, "key"))


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def bucket_of(moment: Any, bucket: str) -> str:
    """The day (``day``) or the Monday of the week (``week``) an instant falls in, as ``YYYY-MM-DD`` in UTC; empty when it has no usable date.

    ``moment`` is an ISO timestamp or a plain ``YYYY-MM-DD`` date. This is the one bucket rule: References and Stories both use it, so a bucket means the same
    on every list. Time zone: UTC, the same for every site.
    """
    instant = _instant(moment)
    if instant is None:
        return ""
    day: date = instant.astimezone(timezone.utc).date()
    if bucket == "week":
        day -= timedelta(days=day.weekday())
    return day.isoformat()


def bucket_moment(record: Mapping[str, Any]) -> Any:
    """The date a Reference is bucketed by, the one the selection already orders by: the accepted time, and for a Reference with none (a recommended one)
    its arrival. A rating never changes it, so a rating never moves a Reference to another bucket."""
    return record.get("acceptedAt") if _instant(record.get("acceptedAt")) is not None else record.get("arrivedAt")


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


BUCKET_DAYS = {"day": 1, "week": 7}


def rolling_age(moment: Any, bucket: str, as_of: date) -> int:
    """How many whole ``bucket`` windows before ``as_of`` the date falls: 0 is the last day (or last seven days), 1 the window before it, and so on.

    Windows are counted back from ``as_of`` (a UTC day), not from the calendar, so "week" means the last seven days, the seven before that, and so on. A
    date after ``as_of`` is in window 0; no usable date is the oldest window. ``as_of`` is a day, not a time, so the order can change only when the day does.
    """
    instant = _instant(moment)
    if instant is None:
        return 2**31
    days = (as_of - instant.astimezone(timezone.utc).date()).days
    return max(0, days) // BUCKET_DAYS[bucket]


def rank_in_buckets(
    items: Iterable[T], *, stars: Callable[[T], int | None], moment: Callable[[T], Any], bucket: str, as_of: date | None = None
) -> list[T]:
    """``items`` (already newest first) with the newest bucket first and, inside each bucket, the shared order of ratings: 5, 4, 3 stars, then unrated, then 2 and 1.

    Without ``as_of`` a bucket is a calendar day or Monday week (``bucket_of``). With it a bucket is a rolling window counted back from that day
    (``rolling_age``). Both sorts are stable, so equal items keep the order they came in: with nothing rated every bucket keeps its newest-first order, and the
    whole list is exactly what it was. Nothing is dropped: an older bucket follows the newer ones, ranked inside itself.
    """
    chosen = sorted(items, key=lambda item: _primary(valid_stars(stars(item)), None))
    if as_of is not None:
        return sorted(chosen, key=lambda item: rolling_age(moment(item), bucket, as_of))
    return sorted(chosen, key=lambda item: bucket_of(moment(item), bucket), reverse=True)


def order_in_buckets(records: Iterable[Mapping[str, Any]], bucket: str, as_of: date | None = None) -> list[Mapping[str, Any]]:
    """Newest window first, and the shared order inside each window (a sort on the window alone is stable). References use the same ROLLING windows as
    Stories: ``week`` is the last seven days counted back from the UTC day ``as_of``, the seven before that, and so on; ``day`` likewise. ``as_of`` is a day,
    so the result can change only when the day changes, and only for a Reference whose window changed. Nothing is dropped. Without ``as_of`` it is today (UTC)."""
    day = as_of or utc_today()
    return sorted(order_public_records(records), key=lambda record: rolling_age(bucket_moment(record), bucket, day))
