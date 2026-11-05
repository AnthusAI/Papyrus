"""The order published Stories are listed in: the newest bucket first, and inside a bucket the editors' stars.

Listings used to be newest first. A Story an editor rated now ranks inside its bucket the way a Reference does (``home_page/ordering.py``, one rule for
both): five, four and three stars first, then Stories nobody rated, then two and one stars; Stories that rank equal keep their newest-first order. A bucket
is a calendar week starting Monday, or a day, **in UTC** (``listings.bucket``, and ``bucket`` on a listing include); ``none`` keeps the plain newest-first
order. Nothing is dropped: Stories of earlier buckets follow the newer ones, each bucket ranked inside itself, so an old five-star Story never rises above
the newer buckets. With no ratings at all the list is exactly what it was.

The stars are private (``item_stars.py``). They are read at projection time into ``SiteIndex.story_stars``, used here to order and printed nowhere: a
``StandardEntry`` carries no star field, a card renders nothing about them, and the fingerprint of a listing is its entries in order, so a rating that
moves a Story changes the pages that list it and no other.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ...home_page.ordering import rank_in_buckets
from .config import NO_BUCKET
from .entries import StandardEntry


def rank_entries(entries: Iterable[StandardEntry], stars: Mapping[str, int], bucket: str) -> list[StandardEntry]:
    """``entries`` (newest first) in the Story ranking. A site with no rated Story, or ``bucket="none"``, gets the list back unchanged."""
    chosen = list(entries)
    if not stars or bucket == NO_BUCKET:
        return chosen
    return rank_in_buckets(chosen, stars=lambda entry: stars.get(entry.summary.lineage_id or ""), moment=lambda entry: entry.date, bucket=bucket)
