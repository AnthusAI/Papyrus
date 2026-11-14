"""The ``story-stars`` projection task: an editor rated a Story, so record the rating and re-render the listings whose order it changed.

``setItemStars`` (``amplify/functions/category-action/handler.ts``) starts it once per rating, with the Item version it changed. The task reads that one
row (no scan of Items), sets the Story's entry in the private rating store (``story_stars.py``) and, when the Story is published, runs the ordinary stale
listing pass: the projector orders every listing with the new rating, each listing page whose digest (its entries in order) changed is written, and the
rest are not touched. A Story nobody has published yet only gets its entry: no page shows it.

The pass reads the published summaries once, as every listing refresh does. It reads no Item rows beyond the one that changed and renders no item page.
"""

from __future__ import annotations

from typing import Any

from ..item_stars import item_stars
from ..publishing import published_item_id_for
from .engine import project_stale_listings
from .source import is_projectable
from .story_stars import UNRATED

TASK_NAME = "story-stars"


def run_story_stars_task(context: Any, client: Any, task: dict[str, Any]) -> dict[str, Any]:
    """Report ``{recorded, published, pagesRewritten, rewritten}``; ``skipped`` says why nothing was done."""
    store = getattr(context.source, "star_store", None)
    if store is None:
        return {"ok": True, "skipped": "this backend has no projection lock table, so ratings are not kept", "pagesRewritten": 0}
    item_id = str(task.get("itemId") or "")
    item = client.get_record("Item", item_id) if item_id else None
    if item is None:
        return {"ok": True, "skipped": f"no Item {item_id}", "pagesRewritten": 0}
    lineage_id = str(item.get("lineageId") or item_id)
    stars = item_stars(item) or UNRATED
    if store.load().get(lineage_id) == stars:
        return {"ok": True, "recorded": False, "pagesRewritten": 0}
    store.record({lineage_id: stars})
    published = client.get_record("PublishedItem", published_item_id_for(lineage_id))
    if published is None or not is_projectable(published, context.source.extra_types):
        return {"ok": True, "recorded": True, "published": False, "pagesRewritten": 0}
    report = project_stale_listings(context)
    return {"ok": report.ok, "recorded": True, "published": True, "pagesRewritten": len(report.written), "rewritten": list(report.written), "errors": list(report.errors)}
