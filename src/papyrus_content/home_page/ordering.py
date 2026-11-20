"""The order the public home page puts References in, from the shared ranking (``quality_ranking.py``, ``docs/quality-ranking.md``).

The public snapshot (``_data/home-page/references.json``) is readable by anyone, so the stars themselves cannot be in it. ``rank_records`` turns the shared order into
``rank``, a position (1 is first) over every public Reference, and the build orders by that number (``order_public_records``). A position is not a star count, and a
rating that moves nothing changes nothing in the file. The order reveals relative standing, which is its purpose; it never reveals how many stars anyone gave.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from ..quality_ranking import in_windows, instant_of, rank, utc_today

RANK_FIELD = "rank"


def confidence_of(record: Mapping[str, Any]) -> float | None:
    """The record's confidence, or None when it has none (never a stand-in number)."""
    value = record.get("confidence")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _text(record: Mapping[str, Any], name: str) -> str:
    value = record.get(name)
    return value if isinstance(value, str) else ""


def rank_records(entries: Iterable[tuple[Mapping[str, Any], int | None]]) -> dict[str, int]:
    """``{public key: position}`` for ``(public record, stars)`` pairs: 1 is the best. The stars are read here and never leave."""
    found = rank(entries, stars=lambda pair: pair[1], confidence=lambda pair: confidence_of(pair[0]), newest=lambda pair: _text(pair[0], "arrivedAt"), key=lambda pair: _text(pair[0], "key"))
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
    return rank(chosen, stars=lambda _record: None, confidence=confidence_of, newest=lambda record: _text(record, "arrivedAt"), key=lambda record: _text(record, "key"))


def bucket_moment(record: Mapping[str, Any]) -> Any:
    """The date a Reference is bucketed by, the one the selection already orders by: the accepted time, and for a Reference with none (a recommended one)
    its arrival. A rating never changes it, so a rating never moves a Reference to another bucket."""
    return record.get("acceptedAt") if instant_of(record.get("acceptedAt")) is not None else record.get("arrivedAt")


def order_in_buckets(records: Iterable[Mapping[str, Any]], bucket: str, as_of: date | None = None) -> list[Mapping[str, Any]]:
    """The records by rolling window (``quality_ranking.rolling_age``), the newest first, and inside each window their ranks. ``as_of`` is a UTC day, today when
    absent."""
    return in_windows(order_public_records(records), moment=bucket_moment, bucket=bucket, as_of=as_of or utc_today())
