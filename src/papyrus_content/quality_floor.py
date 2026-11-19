"""The three-star floor: the lowest human rating an item may have to appear on a public page or in a notification.

One rule (PPY-0e8d66, Ryan 2026-11-12): an item is public only when its effective human rating is at or above the site's floor. Unrated is 0 and never qualifies, and a
Cyclotron prediction is a model's guess, not a rating, so it never qualifies either. The floor is a site setting, ``quality.floorStars`` in ``projection.json``
(1 to 5; 3 when the ``quality`` block is present without it), not a number in code. A site with no ``quality`` block has no floor, and nothing changes for it until
it adds one.

Every consumer asks ``meets_floor`` with the stars it already reads through ``item_stars.effective_rating``, so when a rating becomes an aggregate of votes the
floor follows with no change here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DEFAULT_FLOOR_STARS = 3
MIN_FLOOR_STARS = 1
MAX_FLOOR_STARS = 5


@dataclass(frozen=True)
class QualitySettings:
    """``quality`` in ``projection.json``. ``floor_stars`` is ``None`` for a site that has not turned the floor on."""

    floor_stars: int | None = None


def quality_settings_from_mapping(raw: Any) -> QualitySettings:
    if not isinstance(raw, Mapping):
        raise ValueError("quality must be an object")
    unknown = sorted(set(raw) - {"floorStars"})
    if unknown:
        raise ValueError(f"Unknown quality settings: {', '.join(unknown)}")
    value = raw.get("floorStars", DEFAULT_FLOOR_STARS)
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_FLOOR_STARS <= value <= MAX_FLOOR_STARS:
        raise ValueError(f"quality.floorStars must be a whole number from {MIN_FLOOR_STARS} to {MAX_FLOOR_STARS}")
    return QualitySettings(floor_stars=value)


def meets_floor(stars: int | None, floor_stars: int | None) -> bool:
    """True when an item rated ``stars`` (0 or None: unrated) may be public under ``floor_stars``; with no floor everything may."""
    if floor_stars is None:
        return True
    return bool(stars) and stars >= floor_stars
