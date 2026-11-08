"""The page-refresh operations, once: the CLI, the MCP tools and the content-actions Lambda all call this (PPY-105508).

Four operations. Three only purge the edge cache, with exact paths and never a wildcard:

* ``site_refresh_pages``: the pages named, under every URL form they are cached under, and their Markdown twins.
* ``site_refresh_story``: one Story's page and twin, and every index page that lists it.
* ``site_refresh_indexes``: the home page, every list page and every section page.

``site_rerender_pages`` rebuilds pages from the hooks and templates the site has deployed now (a change to hooks in Git does not reach an
existing page until the page is rendered again), then purges what it wrote. An explicit refresh always invalidates when asked, whatever the
site's ``publication.cache.invalidation`` default is.

Each result reports the write (re-render only) and the invalidation separately: ``rendered.ok`` and ``invalidation.ok``. ``ok`` is true only when
everything requested worked.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..edge_invalidation import invalidate_exact_paths, invalidation_cost_note
from ..projection.model import SiteIndex
from .paths import InvalidPagePath, expand_site_paths, paths_for_page_keys

STATE_PREFIX = "_state/"
RERENDER_SCOPES = ("story", "indexes", "all")
PAGE_SUFFIXES = (".html", ".md")


class RefreshError(Exception):
    """The request cannot be run (an unknown Story, a missing site setting). ``code`` is stable; nothing was written or invalidated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class RefreshService:
    """``context`` builds the projection context lazily (reading the site's content costs requests, so a plain page refresh never builds one)."""

    distribution_id: str | None
    context: Callable[[], Any] | None = None
    cloudfront: Any = None
    sleep: Callable[[float], None] = time.sleep
    emit_metric: bool = True   # a Lambda logs the path-count metric line; a command line must not print it
    _context: Any = field(default=None, init=False, repr=False)

    def _projection(self) -> Any:
        if self._context is None:
            if self.context is None:
                raise RefreshError("site_unavailable", "This lane cannot read the site's content, so it cannot work out which pages to refresh.")
            self._context = self.context()
        return self._context

    # ------------------------------------------------------------------ the operations

    def refresh_pages(self, paths: Sequence[str], *, dry_run: bool = False) -> dict[str, Any]:
        if not paths:
            raise RefreshError("invalid_input", "Name at least one page path to refresh.")
        try:
            expanded = expand_site_paths(paths)
        except InvalidPagePath as error:
            raise RefreshError("invalid_input", str(error)) from error
        return self._finish("site_refresh_pages", {"paths": list(paths)}, expanded, dry_run=dry_run)

    def refresh_story(self, lineage: str, *, dry_run: bool = False) -> dict[str, Any]:
        context = self._projection()
        site = context.source.site_index()
        summary = find_story(site, lineage)
        projector = context.projector
        own = list(projector.item_page_paths(summary))
        if not own:
            raise RefreshError("no_public_page", f"Story {lineage} has no page on this site, so there is nothing to refresh.")
        index_keys = story_index_keys(projector, site, summary)
        keys = list(dict.fromkeys([*own, *index_keys]))
        result = self._finish("site_refresh_story", {"storyLineageId": lineage, "itemId": summary.item_id}, paths_for_page_keys(keys, url_style_of(projector)), dry_run=dry_run)
        result["pages"] = {"story": own, "indexes": index_keys}
        return result

    def refresh_indexes(self, *, dry_run: bool = False) -> dict[str, Any]:
        context = self._projection()
        projector = context.projector
        keys = index_keys_of(projector, context.source.site_index())
        result = self._finish("site_refresh_indexes", {}, paths_for_page_keys(keys, url_style_of(projector)), dry_run=dry_run)
        result["pages"] = {"indexes": keys}
        return result

    def rerender(self, scope: str, *, lineage: str | None = None, invalidate: bool = True, dry_run: bool = False) -> dict[str, Any]:
        if scope not in RERENDER_SCOPES:
            raise RefreshError("invalid_input", f"scope must be one of {', '.join(RERENDER_SCOPES)}.")
        if (scope == "story") != bool(lineage):
            raise RefreshError("invalid_input", "scope story needs a Story lineage id, and no other scope takes one.")
        context = self._projection()
        context.invalidate = None   # this operation purges, below, with exact paths; the engine's own purge turns a big run into /*
        site = context.source.site_index()
        projector = context.projector
        target: dict[str, Any] = {"scope": scope}
        item_id = None
        if scope == "story":
            summary = find_story(site, lineage)
            item_id = summary.item_id
            target.update({"storyLineageId": lineage, "itemId": item_id})
        if dry_run:
            planned = planned_rerender_keys(projector, site, scope, item_id)
            result = self._finish("site_rerender_pages", target, paths_for_page_keys(planned, url_style_of(projector)) if invalidate else [], dry_run=True, invalidate=invalidate)
            result["rendered"] = {"ok": True, "dryRun": True, "wouldWrite": planned, "count": len(planned), "errors": []}
            return result
        report = run_rerender(context, scope, item_id)
        written = [key for key in report.written if not key.startswith(STATE_PREFIX)]
        rendered = {"ok": report.ok, "written": written, "count": len(written), "deleted": list(report.deleted), "errors": list(report.errors)}
        pages = [key for key in [*written, *report.deleted] if key.endswith(PAGE_SUFFIXES)]
        result = self._finish("site_rerender_pages", target, paths_for_page_keys(pages, url_style_of(projector)) if invalidate else [], dry_run=False, invalidate=invalidate)
        result["rendered"] = rendered
        result["ok"] = bool(rendered["ok"] and result["invalidation"]["ok"])
        return result

    # ------------------------------------------------------------------ the purge

    def _finish(self, operation: str, target: dict, paths: list[str], *, dry_run: bool, invalidate: bool = True) -> dict[str, Any]:
        invalidation = self._invalidate(paths, dry_run=dry_run, requested=invalidate)
        return {
            "ok": invalidation["ok"],
            "operation": operation,
            "dryRun": dry_run,
            "target": target,
            "invalidation": invalidation,
        }

    def _invalidate(self, paths: list[str], *, dry_run: bool, requested: bool) -> dict[str, Any]:
        base: dict[str, Any] = {"paths": paths, "count": len(paths), "cost": invalidation_cost_note(len(paths)), "requests": []}
        if not requested:
            return {**base, "ok": True, "status": "not-requested"}
        if dry_run:
            return {**base, "ok": True, "status": "dry-run"}
        if not paths:
            return {**base, "ok": True, "status": "nothing-to-invalidate"}
        if not self.distribution_id:
            return {**base, "ok": False, "status": "failed", "error": "This site has no CloudFront distribution configured (PAPYRUS_EDGE_DISTRIBUTION_ID), so nothing could be invalidated."}
        try:
            made = invalidate_exact_paths(self.distribution_id, paths, self.cloudfront, sleep=self.sleep, emit_metric=self.emit_metric)
        except Exception as error:  # noqa: BLE001 - reported as the invalidation's outcome, separate from any write
            return {**base, "ok": False, "status": "failed", "requests": list(getattr(error, "made", [])), "error": f"{type(error).__name__}: {error}"}
        return {**base, "ok": True, "status": "invalidated", "requests": made, "distributionId": self.distribution_id}


# ---------------------------------------------------------------------- what a site says it has


def url_style_of(projector: Any) -> str:
    return str(getattr(getattr(projector, "standard", None), "url_style", None) or "html")


def find_story(site: SiteIndex, ident: str):
    """The published Story with this lineage id (or item id)."""
    wanted = str(ident or "").strip()
    for summary in site.items:
        if wanted and wanted in (summary.lineage_id, summary.item_id):
            return summary
    raise RefreshError("not_found", f"No published Story with lineage id {wanted!r} on this site. Only a published Story has pages to refresh.")


def story_index_keys(projector: Any, site: SiteIndex, summary: Any) -> list[str]:
    """The index pages that list this Story, from the projector's own plan; a projector without one lists the pages it generates."""
    listing = getattr(projector, "listing_keys_of", None)
    if callable(listing):
        return list(listing(site, summary.item_id))
    return sorted(key for key in projector.listing_inputs(site) if key.endswith(PAGE_SUFFIXES))


def index_keys_of(projector: Any, site: SiteIndex) -> list[str]:
    index = getattr(projector, "index_page_keys", None)
    if callable(index):
        return list(index(site))
    return sorted(key for key in projector.listing_inputs(site) if key.endswith(PAGE_SUFFIXES))


def planned_rerender_keys(projector: Any, site: SiteIndex, scope: str, item_id: str | None) -> list[str]:
    if scope == "story":
        summary = next(item for item in site.items if item.item_id == item_id)
        return list(projector.item_page_paths(summary))
    indexes = index_keys_of(projector, site)
    if scope == "indexes":
        return indexes
    items = [key for summary in site.items for key in projector.item_page_paths(summary)]
    return sorted({*items, *projector.listing_inputs(site), *indexes})


def run_rerender(context: Any, scope: str, item_id: str | None):
    from ..projection.engine import project, project_all, project_listings

    if scope == "story":
        return project(context, item_id)
    if scope == "indexes":
        return project_listings(context)
    return project_all(context)
