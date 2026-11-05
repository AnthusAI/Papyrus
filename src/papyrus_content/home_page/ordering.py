"""The one order the public home page puts References in: an editor's rating first, then the Cyclotron's confidence.

Human ratings are a stronger signal than a prediction, so they come first and, where they exist, override it:

1. three, four and five stars, the most stars first;
2. References nobody rated, the highest Cyclotron confidence first;
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

MISSING_CONFIDENCE = 0.5
HIGH_STARS = (5, 4, 3)
LOW_STARS = (2, 1)
RANK_FIELD = "rank"
BUCKETS = ("day", "week")


def valid_stars(value: Any) -> int | None:
    """A rating from one to five, or None (unrated, or not a rating)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        return None
    return int(value) if 1 <= int(value) <= 5 else None


def _primary(stars: int | None, confidence: float) -> tuple[int, float]:
    """The part of the order before the tie-breaks, smaller first: rated up, then unrated by confidence, then rated down."""
    if stars in HIGH_STARS:
        return (0, -float(stars))
    if stars in LOW_STARS:
        return (2, -float(stars))
    return (1, -confidence)


def ordered(
    items: Iterable[T],
    *,
    stars: Callable[[T], int | None],
    confidence: Callable[[T], float],
    newest: Callable[[T], str],
    key: Callable[[T], str],
) -> list[T]:
    """``items`` in the shared order. The accessors say where each signal lives, so the export (which has the stars) and the build (which does not) share this."""
    chosen = sorted(items, key=key)
    chosen.sort(key=newest, reverse=True)
    chosen.sort(key=lambda item: _primary(stars(item), confidence(item)))
    return chosen


def confidence_of(record: Mapping[str, Any]) -> float:
    value = record.get("confidence")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else MISSING_CONFIDENCE


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
    existed has none, and its records are ordered as unrated References (confidence, newest, key), which is what it always did."""
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


def bucket_start(record: Mapping[str, Any], bucket: str) -> str:
    """The bucket a record falls in (``bucket_of``) by the date the selection already orders by: the accepted time, and for a Reference with none (a
    recommended one) its arrival. A rating never changes it, so a rating never moves a Reference to another bucket."""
    return bucket_of(record.get("acceptedAt"), bucket) or bucket_of(record.get("arrivedAt"), bucket)


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

    Without ``as_of`` a bucket is a calendar day or Monday week (``bucket_of``). With it (Stories) a bucket is a rolling window counted back from that day
    (``rolling_age``). Both sorts are stable, so equal items keep the order they came in: with nothing rated every bucket keeps its newest-first order, and the
    whole list is exactly what it was. Nothing is dropped: an older bucket follows the newer ones, ranked inside itself.
    """
    chosen = sorted(items, key=lambda item: _primary(valid_stars(stars(item)), MISSING_CONFIDENCE))
    if as_of is not None:
        return sorted(chosen, key=lambda item: rolling_age(moment(item), bucket, as_of))
    return sorted(chosen, key=lambda item: bucket_of(moment(item), bucket), reverse=True)


def order_in_buckets(records: Iterable[Mapping[str, Any]], bucket: str) -> list[Mapping[str, Any]]:
    """Newest bucket first, and the shared order inside each bucket (a sort on the bucket alone is stable, and ``reverse`` keeps it so)."""
    return sorted(order_public_records(records), key=lambda record: bucket_start(record, bucket), reverse=True)
