"""A retired Story's announcements are taken back (PPY-bf9d26): ``papyrus stories retire`` calls ``withdraw_for_story`` after the Story is retired.

For every Announcement that announces the Story, and only when every Story that Announcement is about is retired (a roundup that still has live Stories stays), each live
Delivery is withdrawn the way ``papyrus announcements withdraw`` does it (``withdrawals.Withdrawals.withdraw``): what has not gone is stopped, and a post on X is deleted through the
site's own X channel. The signed-in command line holds no such channel, so a post that already went is not touched here: it is reported, with the Delivery's id, and the
site's own stack deletes it (``announcements withdraw`` through that channel). A Delivery that cannot be taken back (a sent email) is reported the same way and stays sent.
Nothing is raised for a Delivery that stays: the Story is already retired, and every line says what happened to each Delivery.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .decisions import Announcements
from .deliveries import Deliveries
from .eligibility import load_story
from .records import RecordError
from .withdrawals import Remover, Withdrawals

WITHDRAWN, STAYS = "withdrawn", "stays"


def withdraw_for_story(client: Any, lineage_id: str, *, by: str, files: Any = None, item_url_style: str = "html",
                       removers: Callable[[Mapping[str, Any]], Remover | None] = lambda row: None) -> list[dict[str, str]]:
    """One ``{delivery, outcome, words}`` for each live Delivery of each Announcement that is now only about retired Stories. ``outcome`` is ``withdrawn`` or ``stays``."""
    deliveries = Deliveries(client, files)
    announcements = Announcements(client, deliveries)
    withdrawals = Withdrawals(deliveries, announcements, removers)
    results: list[dict[str, str]] = []
    for entry in announcements.for_story(lineage_id):
        lineages = sorted({link["objectLineageId"] for link in _stories_of(client, entry["announcement"]["id"])})
        if not all(load_story(client, lineage, item_url_style=item_url_style).retired for lineage in lineages):
            continue
        for row in entry["deliveries"]:
            try:
                withdrawals.withdraw(row["id"], by=by)
            except RecordError as stays:
                results.append({"delivery": row["id"], "outcome": STAYS, "words": str(stays)})
            else:
                results.append({"delivery": row["id"], "outcome": WITHDRAWN, "words": f"withdrawn because {lineage_id} was retired"})
    return results


def _stories_of(client: Any, announcement: str) -> list[dict[str, Any]]:
    from . import link_reads

    return link_reads.stories_of_announcement(client, announcement)
