"""A Story keeps an editor's star rating on itself, and every new version of it keeps the rating.

Stars are an editor's private judgement of a Story, 1 to 5: what to publish, and later how to rank and feature it. They are the same three fields a
Reference has (``starRating``, ``starRatedAt``, ``starRatedBy``) and follow the same rules: separate from the stage and from publication, the newest
rating wins, and clearing it removes who and when too. ``setItemStars`` (``amplify/functions/category-action/handler.ts``) is the editors' path.

An Item is versioned, and a new version is a new row. ``carry_item_stars`` is the one place a path that builds a new version from an older one copies
the rating over; a Reference lost its stars once because a version path built its row without them. Stars are never copied to ``PublishedItem`` or to
any projection: ``assert_no_item_stars`` is the guard ``publish_item`` runs on every published row it writes.
"""
from __future__ import annotations

from typing import Any, Mapping

ITEM_STAR_FIELDS = ("starRating", "starRatedAt", "starRatedBy")


def carry_item_stars(current: Mapping[str, Any] | None, next_version: dict[str, Any]) -> dict[str, Any]:
    """``next_version`` with the rating of ``current`` on it, unless it already carries one. Returns ``next_version`` itself (changed in place)."""
    if not current or current.get("starRating") is None or next_version.get("starRating") is not None:
        return next_version
    for name in ITEM_STAR_FIELDS:
        next_version[name] = current.get(name)
    return next_version


def item_stars(item: Mapping[str, Any] | None) -> int | None:
    """The Story's rating (1 to 5), or None when nobody rated it."""
    value = (item or {}).get("starRating")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or not 1 <= int(value) <= 5:
        return None
    return int(value)


def assert_no_item_stars(record: Mapping[str, Any]) -> None:
    """Raises when a row bound for public output carries a rating: stars change order in the newsroom and are never published."""
    leaked = [name for name in ITEM_STAR_FIELDS if name in record]
    if leaked:
        raise AssertionError(f"Story stars are private and cannot reach published output: {', '.join(leaked)}")
