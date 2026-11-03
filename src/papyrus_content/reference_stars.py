"""A Reference keeps an editor's star rating on itself, beside its latest vote.

Stars are the editors' interest, from 1 to 5, and nothing else: they do not change the curation status, they are not relevance and they are never sent to
the Cyclotron as a label (``reference_vote.vote_fields`` carries no stars, and ``relevance_decisions`` reads only the vote). The newest rating wins; clearing
it removes who and when too. The fields are ``starRating``, ``starRatedAt`` and ``starRatedBy``; a Reference nobody rated has none.

Readers use ``latest_stars``; writers spread ``star_fields`` into their update. The ``setReferenceStars`` mutation is the editors' path.
"""
from __future__ import annotations

from typing import Any, Mapping

MINIMUM_STARS = 1
MAXIMUM_STARS = 5
#: Three stars say "fine" and nothing else. Above it is interest the idea pipeline follows; below it is interest against (``ideas/editor_signals.py``).
MIDPOINT_STARS = 3


def star_fields(stars: int | None, *, rated_by: str | None = None, rated_at: str | None = None) -> dict[str, Any]:
    """The Reference fields a rating sets. Every field is always present, so clearing the rating (``None``) clears who and when too."""
    if stars is None:
        return {"starRating": None, "starRatedAt": None, "starRatedBy": None}
    if isinstance(stars, bool) or not isinstance(stars, int) or not MINIMUM_STARS <= stars <= MAXIMUM_STARS:
        raise ValueError(f"Stars are a whole number from {MINIMUM_STARS} to {MAXIMUM_STARS}, not {stars!r}.")
    return {"starRating": stars, "starRatedAt": rated_at, "starRatedBy": rated_by}


def latest_stars(reference: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The Reference's rating (``stars``, ``ratedAt``, ``ratedBy``), or None when no editor rated it."""
    if not reference:
        return None
    value = reference.get("starRating")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or not MINIMUM_STARS <= int(value) <= MAXIMUM_STARS:
        return None
    return {"stars": int(value), "ratedAt": reference.get("starRatedAt") or None, "ratedBy": reference.get("starRatedBy") or None}
