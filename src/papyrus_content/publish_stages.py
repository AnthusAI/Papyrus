"""The stages of ``papyrus ops content publish``, each reported on its own, with an exit code per failed stage (PPY-f3b296, PPY-4611d5, PPY-0515e1).

A publish does four things, and any of the later ones can fail while the earlier ones are done:

* ``saved``: the published data is written (the version number). Failing here means nothing is live.
* ``projected``: the page is built and written to the site's storage. ``still-running`` (the client stopped waiting, the server may be finishing)
  is not ``failed``.
* ``invalidated``: the edge cache is asked to drop the old page. A refused or capped purge never looks like a failed write.
* ``verified``: the public URL is fetched and its ``papyrus-source-version`` marker compared with the published version
  (``page_refresh.service.verify_public_urls``, the check ``update-live`` uses).

Exit codes (documented in ``docs/site-hosting.md``): 0 all well; 1 the data could not be saved or published; 2 the request could not run (bad flags, unknown
story: the operator-error code); 3 a required checklist step is open; 4 the page could not be built; 5 the page is still being built (not confirmed);
6 the edge cache was not purged (refused, failed or over the cap); 7 the public page still shows an older version after ``--verify`` waited.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from .page_refresh.paths import paths_for_page_keys
from .page_refresh.service import _fetch, verdict_of, verify_public_urls

EXIT_OK = 0
EXIT_SAVE_FAILED = 1
EXIT_REQUEST_REFUSED = 2
EXIT_CHECKLIST_OPEN = 3
EXIT_PROJECTION_FAILED = 4
EXIT_PROJECTION_RUNNING = 5
EXIT_INVALIDATION_FAILED = 6
EXIT_VERIFICATION_FAILED = 7

EXIT_CODES = {
    "ok": EXIT_OK,
    "save-failed": EXIT_SAVE_FAILED,
    "request-refused": EXIT_REQUEST_REFUSED,
    "checklist-open": EXIT_CHECKLIST_OPEN,
    "projection-failed": EXIT_PROJECTION_FAILED,
    "projection-running": EXIT_PROJECTION_RUNNING,
    "invalidation-failed": EXIT_INVALIDATION_FAILED,
    "verification-failed": EXIT_VERIFICATION_FAILED,
}
DEFAULT_VERIFY_SECONDS = 60
PUBLIC_URL_ENV = "PAPYRUS_SITE_PUBLIC_URL"


def projected_stage(projection: dict[str, Any]) -> dict[str, Any]:
    """``status``: ``ok`` | ``scheduled`` (the IAM lane hands the work to the function and cannot see the result) | ``skipped`` | ``still-running`` | ``timed-out`` | ``failed``."""
    if not projection:
        return {"status": "not-applicable", "pages": []}
    if projection.get("skipped"):
        return {"status": "skipped", "reason": "--no-trigger", "pages": []}
    pages = list(projection.get("paths") or [])
    status = projection.get("status")
    if projection.get("ok") is None or status == "still-running":
        return {"status": "still-running", "pages": pages, "error": projection.get("error"), "retry": projection.get("retry")}
    if projection.get("ok") is False:
        return {"status": "timed-out" if status == "timed-out" else "failed", "pages": pages, "error": projection.get("error") or "unknown error", "retry": projection.get("retry")}
    if projection.get("scheduled"):
        return {"status": "scheduled", "pages": pages, "reason": "the function builds the page asynchronously; this command cannot see its result (use --verify)"}
    return {"status": "ok", "pages": pages}


def invalidated_stage(projection: dict[str, Any]) -> dict[str, Any]:
    """``status``: ``ok`` | ``skipped`` (the site's setting) | ``capped`` | ``failed`` | ``unknown`` | ``not-applicable``."""
    if not projection or projection.get("skipped") or projection.get("ok") is not True:
        return {"status": "not-applicable", "paths": []}
    outcome = projection.get("invalidation")
    if isinstance(outcome, dict) and outcome.get("status"):
        return {key: outcome[key] for key in ("status", "paths", "skippedPaths", "reason") if key in outcome}
    return {"status": "unknown", "paths": [], "reason": "the answer did not say (the page is built asynchronously, or the function predates this report)"}


def public_urls_for(projection: dict[str, Any], environment: Any = None) -> list[str]:
    """The story's public page under both URL forms, from the page address the function reported (and the site's public URL)."""
    environment = os.environ if environment is None else environment
    item_paths = [key for key in projection.get("itemPaths") or [] if key.endswith(".html")][:1]
    if not item_paths:
        return []
    base = (environment.get(PUBLIC_URL_ENV) or "").strip().rstrip("/")
    url = str(projection.get("url") or "")
    if not base and url:
        key = item_paths[0]
        tail = "/" if key == "index.html" else "/" + key
        base = url[: -len(tail)] if url.endswith(tail) else ""
    if not base:
        return []
    return [base + path for path in paths_for_page_keys(item_paths) if not path.endswith(".md")]


def verified_stage(
    projection: dict[str, Any],
    version: int | None,
    *,
    wait: bool,
    seconds: float = DEFAULT_VERIFY_SECONDS,
    fetch: Callable | None = None,
    sleep: Callable[[float], None] | None = None,
    environment: Any = None,
) -> dict[str, Any]:
    """Fetch the public page once (or, with ``wait``, until it shows ``version``). Stale without ``wait`` is expected on a site that lets pages age out: not a failure."""
    urls = public_urls_for(projection, environment)
    if not urls:
        return {"status": "not-checked", "reason": "no public page address is known (the signed-in lane reports it; set PAPYRUS_SITE_PUBLIC_URL on the operator lane)"}
    arguments: dict[str, Any] = {"fetch": fetch or _fetch}
    if sleep is not None:
        arguments["sleep"] = sleep
    verification = verify_public_urls(urls, version, seconds if wait else 0, **arguments)
    if not verification.get("checked"):
        return {"status": "not-checked", "reason": verification.get("reason")}
    return {"status": "current" if verification["current"] else "stale", "expectedVersion": version, "waited": bool(wait), "urls": verification["urls"]}


def exit_code_of(stages: dict[str, dict[str, Any]], *, verify: bool) -> tuple[int, str]:
    """The first failed stage, in the order the stages run: its code and name in ``EXIT_CODES``."""
    projected, invalidated, verified = stages.get("projected", {}), stages.get("invalidated", {}), stages.get("verified", {})
    if projected.get("status") in ("failed", "timed-out"):
        return EXIT_PROJECTION_FAILED, "projection-failed"
    if projected.get("status") == "still-running":
        return EXIT_PROJECTION_RUNNING, "projection-running"
    if invalidated.get("status") in ("failed", "capped"):
        return EXIT_INVALIDATION_FAILED, "invalidation-failed"
    if verify and verified.get("status") == "stale":
        return EXIT_VERIFICATION_FAILED, "verification-failed"
    return EXIT_OK, "ok"


def settle_late_projection(stages: dict[str, dict[str, Any]]) -> None:
    """A page the client stopped waiting for that the public check then saw at the published version was finished by the server."""
    if stages["projected"].get("status") == "still-running" and stages["verified"].get("status") == "current":
        stages["projected"] = {**stages["projected"], "status": "ok", "note": "finished on the server after the client stopped waiting; confirmed by the public check"}


def verdict_for(stages: dict[str, dict[str, Any]]) -> str:
    """One sentence, from the same words ``update-live`` uses (``page_refresh.service.verdict_of``)."""
    projected, invalidated, verified = stages["projected"], stages["invalidated"], stages["verified"]
    rendered = {"ok": projected.get("status") not in ("failed", "timed-out", "still-running")}
    invalidation = {"ok": invalidated.get("status") not in ("failed", "capped"), "error": invalidated.get("reason") or "the invalidation failed"}
    verification = {"checked": verified.get("status") in ("current", "stale"), "current": True if verified.get("status") == "current" else (False if verified.get("status") == "stale" else None), "reason": verified.get("reason")}
    if projected.get("status") == "still-running":
        return "STILL BUILDING: the data is published and the server is still writing the page; check again with --verify."
    return verdict_of(rendered, invalidation, verification)
