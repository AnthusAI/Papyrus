"""The order published Stories are listed in: the newest bucket first, and inside a bucket the editors' stars.

Listings used to be newest first. A Story an editor rated now ranks inside its bucket the way a Reference does (``home_page/ordering.py``, one order of
ratings for both): five, four and three stars first, then Stories nobody rated, then two and one stars; Stories that rank equal keep their newest-first
order. A Story bucket is a ROLLING window counted back from the day of the projection, in UTC: ``week`` is the last seven days, the seven before that, and
so on; ``day`` is the last day, the day before, and so on (``listings.bucket``, and ``bucket`` on a listing include); ``none`` keeps the plain newest-first
order. Nothing is dropped: Stories of earlier buckets follow the newer ones, each bucket ranked inside itself, so an old five-star Story never rises
above a newer bucket. With no ratings at all the list is exactly what it was.

A Story moves to an older bucket with time alone, so the order depends on the day it is computed. The day (not the time) is what counts, so a listing can
change at most once a day. Pages are corrected whenever something already re-renders them (a publish that touches them, a rating, a release's render, a
reconcile); nothing is scheduled to walk the corpus.

The stars are private (``item_stars.py``). They are read at projection time into ``SiteIndex.story_stars``, used here to order and printed nowhere: a
``StandardEntry`` carries no star field, a card renders nothing about them, and the fingerprint of a listing is its entries in order, so a rating that
moves a Story changes the pages that list it and no other.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date

from ...home_page.ordering import rank_in_buckets
from .config import NO_BUCKET
from .entries import StandardEntry


def rank_entries(entries: Iterable[StandardEntry], stars: Mapping[str, int], bucket: str, as_of: date) -> list[StandardEntry]:
    """``entries`` (newest first) in the Story ranking as of the UTC day ``as_of``. A site with no rated Story, or ``bucket="none"``, gets the list back unchanged."""
    chosen = list(entries)
    if not stars or bucket == NO_BUCKET:
        return chosen
    return rank_in_buckets(chosen, stars=lambda entry: stars.get(entry.summary.lineage_id or ""), moment=lambda entry: entry.date, bucket=bucket, as_of=as_of)
