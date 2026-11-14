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

import datetime as dt
import email.utils
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..edge_invalidation import FREE_PATHS_PER_MONTH, USD_PER_PATH_AFTER_FREE, invalidate_exact_paths, invalidation_cost_note
from .budget import DRY_RUN_ABOVE, Budget
from ..projection.model import SiteIndex
from ..publishing import published_item_id_for
from .paths import InvalidPagePath, expand_site_paths, forms_of_path, keys_under, normalize_prefixes, paths_for_page_keys

STATE_PREFIX = "_state/"
RERENDER_SCOPES = ("story", "indexes", "all")
PAGE_SUFFIXES = (".html", ".md")


class RefreshError(Exception):
    """The request cannot be run (an unknown Story, a missing site setting). ``code`` is stable; nothing was written or invalidated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    """GET a public URL as a reader's browser would (no cache-busting), for ``update_live``'s check of the edge."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "papyrus-page-refresh/1"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - the site's own public URL
            return response.status, {key.lower(): value for key, value in response.headers.items()}, response.read(2_000_000)
    except urllib.error.HTTPError as error:
        return error.code, {key.lower(): value for key, value in error.headers.items()}, b""


@dataclass
class RefreshService:
    """``context`` builds the projection context lazily (reading the site's content costs requests, so a plain page refresh never builds one).

    Every purge passes the guard: a per-call path cap and dry-run-first above 5 paths (``budget.py``).
    """

    distribution_id: str | None
    context: Callable[[], Any] | None = None
    cloudfront: Any = None
    sleep: Callable[[float], None] = time.sleep
    emit_metric: bool = True   # a Lambda logs the path-count metric line; a command line must not print it
    budget: Budget = field(default_factory=Budget)
    public_url: str | None = None
    fetch: Callable[[str], tuple[int, dict[str, str], bytes]] = _fetch
    _context: Any = field(default=None, init=False, repr=False)

    def _projection(self) -> Any:
        if self._context is None:
            if self.context is None:
                raise RefreshError("site_unavailable", "This lane cannot read the site's content, so it cannot work out which pages to refresh.")
            self._context = self.context()
        return self._context

    # ------------------------------------------------------------------ the operations

    def refresh_pages(self, paths: Sequence[str], *, dry_run: bool = False, confirm: bool = False, force_paths: int | None = None) -> dict[str, Any]:
        if not paths:
            raise RefreshError("invalid_input", "Name at least one page path to refresh.")
        try:
            expanded = expand_site_paths(paths)
        except InvalidPagePath as error:
            raise RefreshError("invalid_input", str(error)) from error
        return self._finish("site_refresh_pages", {"paths": list(paths)}, expanded, dry_run=dry_run, confirm=confirm, force_paths=force_paths)

    def refresh_story(self, lineage: str, *, dry_run: bool = False, confirm: bool = False, force_paths: int | None = None) -> dict[str, Any]:
        context = self._projection()
        site = context.source.site_index()
        summary = find_story(site, lineage)
        projector = context.projector
        own, index_keys = story_keys(projector, site, summary, lineage)
        keys = list(dict.fromkeys([*own, *index_keys]))
        result = self._finish("site_refresh_story", {"storyLineageId": lineage, "itemId": summary.item_id}, paths_for_page_keys(keys, url_style_of(projector)), dry_run=dry_run, confirm=confirm, force_paths=force_paths)
        result["pages"] = {"story": own, "indexes": index_keys}
        return result

    def refresh_indexes(self, *, dry_run: bool = False, confirm: bool = False, force_paths: int | None = None) -> dict[str, Any]:
        context = self._projection()
        projector = context.projector
        keys = index_keys_of(projector, context.source.site_index())
        result = self._finish("site_refresh_indexes", {}, paths_for_page_keys(keys, url_style_of(projector)), dry_run=dry_run, confirm=confirm, force_paths=force_paths)
        result["pages"] = {"indexes": keys}
        return result

    def rerender(self, scope: str, *, lineage: str | None = None, invalidate: bool = True, dry_run: bool = False, confirm: bool = False, force_paths: int | None = None, under: Sequence[str] | None = None) -> dict[str, Any]:
        if scope not in RERENDER_SCOPES:
            raise RefreshError("invalid_input", f"scope must be one of {', '.join(RERENDER_SCOPES)}.")
        if (scope == "story") != bool(lineage):
            raise RefreshError("invalid_input", "scope story needs a Story lineage id, and no other scope takes one.")
        if under and scope != "indexes":
            raise RefreshError("invalid_input", "--under (under) limits a re-render of the index pages: use it with --indexes.")
        try:
            prefixes = normalize_prefixes(under) if under else []
        except InvalidPagePath as error:
            raise RefreshError("invalid_input", str(error)) from error
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
        planned = planned_rerender_keys(projector, site, scope, item_id)
        if prefixes:
            every = planned
            planned = keys_under(every, prefixes, url_style_of(projector))
            if not planned:
                raise RefreshError("no_pages_match", f"No index page has a URL path starting with {', '.join(prefixes)}. This site has {len(every)} index page files; the first are: {', '.join('/' + key for key in every[:8])}.")
            target["under"] = prefixes
        planned_paths = paths_for_page_keys(planned, url_style_of(projector)) if invalidate else []
        verdict = self._guard(planned_paths, dry_run=dry_run, confirm=confirm, force_paths=force_paths, requested=invalidate)
        if verdict["dry"] or verdict["refusal"]:
            result = self._finish("site_rerender_pages", target, planned_paths, dry_run=dry_run, invalidate=invalidate, confirm=confirm, force_paths=force_paths, verdict=verdict)
            result["rendered"] = {"ok": True, "dryRun": True, "wouldWrite": planned, "count": len(planned), "errors": []}
            return result
        report = run_rerender(context, scope, item_id, only=planned if prefixes else None)
        written = [key for key in report.written if not key.startswith(STATE_PREFIX)]
        rendered = {"ok": report.ok, "written": written, "count": len(written), "unchanged": len(report.unchanged), "deleted": list(report.deleted), "errors": list(report.errors)}
        # An editor's explicit re-render purges every page it rendered, including pages whose stored bytes were already current: the edge may
        # still hold an older copy, and these paths were counted and approved by the guard above. Only a publish skips unchanged pages (PPY-3acc8d).
        pages = [key for key in dict.fromkeys([*written, *report.unchanged, *report.deleted]) if key.endswith(PAGE_SUFFIXES)]
        result = self._finish("site_rerender_pages", target, paths_for_page_keys(pages, url_style_of(projector)) if invalidate else [], dry_run=False, invalidate=invalidate, confirm=True, force_paths=force_paths)
        result["rendered"] = rendered
        result["ok"] = bool(rendered["ok"] and result["invalidation"]["ok"])
        return result

    def update_live(self, lineage: str, *, dry_run: bool = False, confirm: bool = False, force_paths: int | None = None, verify_seconds: int = 30) -> dict[str, Any]:
        """The whole editing loop for one Story: re-project its page and twin, purge exactly those pages and the index pages that list it (both URL
        forms), and check the public URL shows the published version (the source-version marker)."""
        context = self._projection()
        context.invalidate = None
        site = context.source.site_index()
        summary = find_story(site, lineage)
        projector = context.projector
        own, index_keys = story_keys(projector, site, summary, lineage)
        keys = list(dict.fromkeys([*own, *index_keys]))
        paths = paths_for_page_keys(keys, url_style_of(projector))
        target = {"storyLineageId": lineage, "itemId": summary.item_id, "publishedVersion": summary.version_number}
        verdict = self._guard(paths, dry_run=dry_run, confirm=confirm, force_paths=force_paths, requested=True)
        if verdict["dry"] or verdict["refusal"]:
            result = self._finish("site_update_live", target, paths, dry_run=dry_run, confirm=confirm, force_paths=force_paths, verdict=verdict)
            result["pages"] = {"story": own, "indexes": index_keys}
            result["rendered"] = {"ok": True, "dryRun": True, "wouldWrite": own, "count": len(own), "errors": []}
            return result
        report = run_rerender(context, "story", summary.item_id)
        written = [key for key in report.written if not key.startswith(STATE_PREFIX)]
        rendered = {"ok": report.ok, "written": written, "count": len(written), "deleted": list(report.deleted), "errors": list(report.errors)}
        purged = paths_for_page_keys(list(dict.fromkeys([*keys, *(key for key in written if key.endswith(PAGE_SUFFIXES))])), url_style_of(projector))
        result = self._finish("site_update_live", target, purged, dry_run=False, confirm=True, force_paths=force_paths)
        result["rendered"] = rendered
        result["pages"] = {"story": own, "indexes": index_keys}
        verification = self._verify(own, summary.version_number, verify_seconds) if result["invalidation"]["ok"] and rendered["ok"] else {"checked": False, "reason": "not attempted: the write or the invalidation did not succeed"}
        result["verification"] = verification
        result["verdict"] = verdict_of(rendered, result["invalidation"], verification)
        result["ok"] = bool(rendered["ok"] and result["invalidation"]["ok"] and verification.get("current") is not False)
        return result

    def _verify(self, own_keys: list[str], version: int | None, seconds: int) -> dict[str, Any]:
        """Fetch the story's public page under both URL forms until each shows ``version`` in its source-version marker, or the time is up."""
        if not self.public_url:
            return {"checked": False, "reason": "this site has no public URL configured (PAPYRUS_SITE_PUBLIC_URL)"}
        html_keys = [key for key in own_keys if key.endswith(".html")][:1]
        urls = [self.public_url.rstrip("/") + path for path in paths_for_page_keys(html_keys) if not path.endswith(".md")]
        return verify_public_urls(urls, version, seconds, fetch=self.fetch, sleep=self.sleep)

    # ------------------------------------------------------------------ inspect: what is wrong with a page, stage by stage

    def inspect(self, *, lineage: str | None = None, path: str | None = None, fix: bool = False, confirm: bool = False, force_paths: int | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
        """Read-only evidence for each stage (the record, the projected page, the edge) and one verdict. With ``fix`` the minimal repair runs, then it looks again."""
        if bool(lineage) == bool(path):
            raise RefreshError("invalid_input", "Pass exactly one of a Story lineage id or a page path.")
        context = self._projection()
        site = context.source.site_index()
        projector = context.projector
        if path:
            wanted = set(forms_of_path(path))
            summary = next((item for item in site.items if wanted & set(paths_for_page_keys(projector.item_page_paths(item), url_style_of(projector)))), None)
            if summary is None:
                return self._not_published(path, None)
            lineage = summary.lineage_id or summary.item_id
        else:
            summary = next((item for item in site.items if lineage in (item.lineage_id, item.item_id)), None)
        report = self._inspect_once(context, projector, summary, lineage, now)
        if fix and report["verdictCode"] in ("never-reprojected", "edge-stale"):
            if report["verdictCode"] == "never-reprojected":
                repair = self.update_live(lineage, confirm=confirm, force_paths=force_paths, verify_seconds=0)
            else:
                repair = self.refresh_pages(report["projected"]["urlPaths"], confirm=confirm, force_paths=force_paths)
            report = {**self._inspect_once(context, projector, summary, lineage, now), "fix": {"ran": bool(repair.get("invalidation", {}).get("status") in ("invalidated",)), "result": repair}}
        return report

    def _not_published(self, ident: str, record: dict | None) -> dict[str, Any]:
        return {"ok": False, "operation": "site_inspect", "verdictCode": "not-published", "verdict": f"NOT PUBLISHED: {ident} has no published version on this site, so there is no page to be stale.", "record": record or {}, "projected": None, "edge": None}

    def _inspect_once(self, context: Any, projector: Any, summary: Any, lineage: str, now: dt.datetime | None) -> dict[str, Any]:
        from .marker import source_version_of

        client = context.source._client
        versions = [
            {"version": row.get("versionNumber"), "state": row.get("versionState"), "stage": row.get("stage"), "author": row.get("authorLabel") or row.get("createdBy") or row.get("updatedBy"), "at": row.get("versionCreatedAt") or row.get("updatedAt")}
            for row in sorted(client.list_by_index("itemsByLineageAndVersion", lineage), key=lambda row: row.get("versionNumber") or 0)
        ]
        pointer = client.get_record("PublishedItem", published_item_id_for(lineage))
        record = {"versions": versions, "currentVersion": next((v["version"] for v in reversed(versions) if v["state"] == "current"), None),
                  "published": {"version": pointer.get("versionNumber"), "publishedAt": pointer.get("publishedAt")} if pointer else None}
        if pointer is None or summary is None:
            return self._not_published(lineage, record)
        published_version = summary.version_number
        keys = list(projector.item_page_paths(summary))
        url_style = url_style_of(projector)
        html_key = next((key for key in keys if key.endswith(".html")), None)
        projected: dict[str, Any] = {"pages": {}, "urlPaths": [path for path in paths_for_page_keys(keys, url_style)]}
        for key in keys:
            stored = context.writer.head(key)
            body = context.writer.get(key) if stored else None
            projected["pages"][key] = None if stored is None else {"lastModified": stored.last_modified, "papyrusVersion": stored.version, "sourceVersion": source_version_of(body)}
        main = projected["pages"].get(html_key) if html_key else None
        rendered_from = (main or {}).get("sourceVersion") or (main or {}).get("papyrusVersion")
        edge = self._edge_evidence(html_key, keys, url_style, source_version_of)
        record["publishedVersion"] = published_version
        base = {"operation": "site_inspect", "target": {"storyLineageId": lineage, "itemId": summary.item_id}, "record": record, "projected": projected, "edge": edge}
        if main is None or rendered_from != published_version:
            return {**base, "ok": False, "verdictCode": "never-reprojected", "verdict": f"PUBLISHED BUT NEVER RE-PROJECTED: the record's published version is {published_version}, the stored page was rendered from {rendered_from}. Run: papyrus ops content update-live --story {lineage} (or inspect --fix)."}
        stale = self._edge_is_stale(edge, main, published_version, now)
        if stale:
            return {**base, "ok": False, "verdictCode": "edge-stale", "verdict": f"PROJECTED BUT THE EDGE IS STALE: the site store holds version {published_version}; {stale}. Run: papyrus ops content refresh --path {projected['urlPaths'][0]} (or inspect --fix)."}
        return {**base, "ok": True, "verdictCode": "current", "verdict": f"EVERYTHING CURRENT: version {published_version} is stored and the edge serves it."}

    def _edge_evidence(self, html_key: str | None, keys: list[str], url_style: str, source_version_of: Callable) -> dict[str, Any]:
        if not self.public_url or not html_key:
            return {"checked": False, "reason": "this site has no public URL configured (PAPYRUS_SITE_PUBLIC_URL)"}
        seen: dict[str, Any] = {}
        for path in [p for p in paths_for_page_keys([html_key, *[k for k in keys if k.endswith(".md")]], url_style)]:
            url = self.public_url.rstrip("/") + path
            try:
                status, headers, body = self.fetch(url)
                cache_control = headers.get("cache-control", "")
                smax = next((part.split("=")[1] for part in cache_control.split(",") if "s-maxage=" in part), None)
                seen[path] = {"status": status, "age": headers.get("age"), "lastModified": headers.get("last-modified"), "etag": headers.get("etag"), "xCache": headers.get("x-cache"), "sMaxAge": smax, "sourceVersion": source_version_of(body)}
            except Exception as error:  # noqa: BLE001 - evidence, not a crash
                seen[path] = {"status": None, "error": f"{type(error).__name__}: {error}"}
        return {"checked": True, "urls": seen}

    @staticmethod
    def _edge_is_stale(edge: dict, main: dict, published_version: int | None, now: dt.datetime | None) -> str | None:
        if not edge.get("checked"):
            return None
        stored_at = dt.datetime.fromisoformat(main["lastModified"]) if main.get("lastModified") else None
        clock = now or dt.datetime.now(dt.timezone.utc)
        for path, seen in edge["urls"].items():
            if path.endswith(".md") or seen.get("status") is None:
                continue
            if seen.get("sourceVersion") is not None:
                if seen["sourceVersion"] != published_version:
                    return f"{path} serves version {seen['sourceVersion']}"
                continue
            served = seen.get("lastModified")
            if stored_at and served:
                try:
                    served_at = email.utils.parsedate_to_datetime(served)
                except (TypeError, ValueError):
                    served_at = None
                if served_at and served_at < stored_at:
                    return f"{path} serves a copy last modified {served} (age {seen.get('age')} s), older than the stored page ({main['lastModified']}); the cached copy has no version marker"
            age = seen.get("age")
            if stored_at and age and age.isdigit() and clock - dt.timedelta(seconds=int(age)) < stored_at:
                return f"{path} was cached {age} s ago, before the page was stored at {main['lastModified']} (the cached copy has no version marker)"
        return None

    # ------------------------------------------------------------------ the guard and the purge

    def _guard(self, paths: list[str], *, dry_run: bool, confirm: bool, force_paths: int | None, requested: bool = True) -> dict[str, Any]:
        """Decide before anything is written: dry run (asked for, or the default above 5 paths without ``confirm``), or a refusal."""
        count = len(paths)
        cap = force_paths if force_paths else self.budget.path_cap
        refusal = None
        if requested and count > cap:
            refusal = {
                "code": "over_path_cap",
                "message": f"{count} paths is over the cap of {cap} paths per call. Nothing was written or invalidated. Narrow the request, or force this one call with --force-paths {count} (setting: publication.cache.maxInvalidationPaths). The first {FREE_PATHS_PER_MONTH:,} paths a month are free, then {USD_PER_PATH_AFTER_FREE} USD each.",
            }
        by_default = requested and not dry_run and not confirm and count > DRY_RUN_ABOVE
        return {"dry": bool(requested and (dry_run or by_default)), "needsRun": bool(by_default), "refusal": refusal, "cap": cap}

    def _finish(self, operation: str, target: dict, paths: list[str], *, dry_run: bool, invalidate: bool = True, confirm: bool = False, force_paths: int | None = None, verdict: dict | None = None) -> dict[str, Any]:
        guard = verdict or self._guard(paths, dry_run=dry_run, confirm=confirm, force_paths=force_paths, requested=invalidate)
        invalidation = self._invalidate(paths, guard=guard, requested=invalidate, operation=operation)
        result: dict[str, Any] = {"ok": invalidation["ok"], "operation": operation, "dryRun": invalidation["status"] == "dry-run", "target": target, "invalidation": invalidation}
        if guard["needsRun"] and invalidation["status"] == "dry-run":
            result["needsRun"] = True
            result["hint"] = "This was a dry run: more than 5 paths need a second, explicit call. Repeat the same request with --run (confirm: true) to do it."
        if guard["refusal"] and not dry_run:
            result["ok"] = False
            result["error"] = guard["refusal"]
        return result

    def _invalidate(self, paths: list[str], *, guard: dict, requested: bool, operation: str) -> dict[str, Any]:
        base: dict[str, Any] = {"paths": paths, "count": len(paths), "cost": invalidation_cost_note(len(paths)), "requests": [], "guard": {key: guard[key] for key in ("cap",)}}
        if guard["refusal"]:
            base["guard"]["refused"] = guard["refusal"]["code"]
            base["guard"]["refusal"] = guard["refusal"]
        if not requested:
            return {**base, "ok": True, "status": "not-requested"}
        if guard["dry"]:
            return {**base, "ok": True, "status": "dry-run"}
        if guard["refusal"]:
            return {**base, "ok": False, "status": "refused", "error": guard["refusal"]["message"]}
        if not paths:
            return {**base, "ok": True, "status": "nothing-to-invalidate"}
        if not self.distribution_id:
            return {**base, "ok": False, "status": "failed", "error": "This site has no CloudFront distribution configured (PAPYRUS_EDGE_DISTRIBUTION_ID), so nothing could be invalidated."}
        try:
            made = invalidate_exact_paths(self.distribution_id, paths, self.cloudfront, sleep=self.sleep, emit_metric=self.emit_metric)
        except Exception as error:  # noqa: BLE001 - reported as the invalidation's outcome, separate from any write
            return {**base, "ok": False, "status": "failed", "requests": list(getattr(error, "made", [])), "error": f"{type(error).__name__}: {error}"}
        return {**base, "ok": True, "status": "invalidated", "requests": made, "distributionId": self.distribution_id}


def verify_public_urls(urls: Sequence[str], version: int | None, seconds: float, *, fetch: Callable = _fetch, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Fetch these public URLs until each shows ``version`` in its source-version marker, or ``seconds`` pass. The one check ``update-live`` and
    ``content publish --verify`` share (PPY-f3b296); ``current`` is true only when every URL answered 200 with that version."""
    from .marker import source_version_of

    if not urls:
        return {"checked": False, "reason": "there is no public page URL to check"}
    deadline = time.monotonic() + max(0, seconds)
    seen: dict[str, Any] = {}
    while True:
        for url in urls:
            try:
                status, headers, body = fetch(url)
                seen[url] = {"status": status, "sourceVersion": source_version_of(body), "age": headers.get("age"), "xCache": headers.get("x-cache")}
            except Exception as error:  # noqa: BLE001 - a fetch failure is evidence, not a crash
                seen[url] = {"status": None, "error": f"{type(error).__name__}: {error}"}
        current = all(entry.get("status") == 200 and entry.get("sourceVersion") == version for entry in seen.values())
        if current or time.monotonic() >= deadline:
            return {"checked": True, "expectedVersion": version, "current": current, "urls": seen}
        sleep(5)


#: Invalidation statuses that mean the edge was told to drop the pages (``update-live``'s ``invalidated`` and ``nothing-to-invalidate``, and
#: ``content publish``'s stage status ``ok``). Any other status that is not a failure (``skipped``, ``unknown``, ``not-applicable``) means no purge
#: was made, so no verdict may say PURGED.
PURGED_STATUSES = frozenset({"invalidated", "nothing-to-invalidate", "ok"})


def verdict_of(rendered: dict, invalidation: dict, verification: dict) -> str:
    """The one sentence both ``update-live`` and ``content publish`` print. ``invalidation`` carries ``ok``, ``status`` and ``error``/``reason``;
    PURGED appears only when its status says the edge was told to drop the pages."""
    if not rendered.get("ok"):
        return "NOT LIVE: the page could not be re-projected."
    if not invalidation.get("ok"):
        return f"PROJECTED BUT NOT PURGED: {invalidation.get('error', 'the invalidation failed')}"
    if verification.get("current") is True:
        return "LIVE: the public page shows the published version."
    purged = invalidation.get("status") in PURGED_STATUSES
    if verification.get("checked"):
        if not purged:
            return f"NOT PURGED, THE PAGE IS STALE: {_no_purge_reason(invalidation)}; the public page does not show the published version and will not until the edge cache expires."
        return "PURGED BUT THE EDGE IS STILL STALE: the invalidation was accepted; the public page does not show the published version yet. Check again in a minute."
    not_checked = verification.get("reason", "the public page was not checked")
    if not purged:
        return f"PROJECTED, NOT PURGED, NOT VERIFIED: {_no_purge_reason(invalidation)}; {not_checked}"
    return f"PURGED, NOT VERIFIED: {not_checked}"


def _no_purge_reason(invalidation: dict) -> str:
    return f"no cache purge was made ({invalidation.get('status')}: {invalidation.get('reason') or 'no reason given'})"


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


def story_keys(projector: Any, site: SiteIndex, summary: Any, lineage: str) -> tuple[list[str], list[str]]:
    own = list(projector.item_page_paths(summary))
    if not own:
        raise RefreshError("no_public_page", f"Story {lineage} has no page on this site, so there is nothing to refresh.")
    return own, story_index_keys(projector, site, summary)


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


def run_rerender(context: Any, scope: str, item_id: str | None, only: Sequence[str] | None = None):
    from ..projection.engine import project, project_all, project_listings

    if scope == "story":
        return project(context, item_id)
    if scope == "indexes":
        return project_listings(context, only=only)
    return project_all(context)
