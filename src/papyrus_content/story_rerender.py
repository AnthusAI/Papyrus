"""Re-render the story pages a new link changes, right after the link is written, without purging the edge.

A ``see_also`` or concept link only shows on a story's page once something renders that page again; writing the link does not. The link commands
(``stories link-story``, ``stories link-concept``) and the agent tools (``papyrus_link_stories``, ``papyrus_link_concepts``) therefore ask the site to
re-render exactly the published stories whose page changed, through the page-refresh operation ``site_rerender_pages`` with scope ``story`` and
``invalidate: false`` (the lane of ``papyrus ops content rerender --story LINEAGE --no-invalidate``: a signed-in editor asks the ``refreshSitePages``
mutation, an operator invokes the content-actions function). Nothing is purged: the site's HTML lifetime is five minutes, so the change shows within
about five minutes, and CloudFront bills each purged path (compute once on change; docs/surfable-site.md).

The re-render is a job on the server (``rerender_with_job``): the call that starts it answers at once and each later call asks how it stands, so
AppSync's 30 seconds never cut it off. A re-render that fails is a warning, never a failed command, and it never undoes the link. One that has not
ended when the wait is over is reported as still running, and one whose request got no answer as unknown; neither is a failure.
See docs/story-reporting.md ("Linking stories to each other").
"""

from __future__ import annotations

import sys
from typing import Any

from .options import parse_options
from .publishing import published_item_id_for

RERENDER_CAP = 20   # stories re-rendered per command; the rest are listed with their exact commands
VISIBLE_LINE = "visible on the site within about five minutes; nothing was purged"


def manual_command(lineage: str) -> str:
    return f"papyrus ops content rerender --story {lineage} --no-invalidate"


def request_story_rerender(client, lineage: str, *, signed_in: bool = False) -> dict[str, Any]:
    """One story's page re-rendered with no invalidation, over the same two lanes as ``papyrus ops content rerender``. Returns the operation's result."""
    from .page_refresh.cli import operation_for, rerender_with_job, run_operator, run_signed_in
    from .user_auth_mode import user_auth_requested

    name, arguments = operation_for([], parse_options(["--story", lineage, "--no-invalidate", "true"]), rerender=True)
    signed = signed_in or user_auth_requested()
    lane = (lambda lane_name, lane_arguments: run_signed_in(client, lane_name, lane_arguments)) if signed else (lambda lane_name, lane_arguments: run_operator(lane_name, lane_arguments))
    return rerender_with_job(lane, name, arguments, check=f"{manual_command(lineage)} --status")


def signed_in_request(client, lineage: str) -> dict[str, Any]:
    """The request for the agent tools running as a signed-in editor (the MCP server): always the ``refreshSitePages`` lane."""
    return request_story_rerender(client, lineage, signed_in=True)


def is_published(client, lineage: str) -> bool:
    return client.get_record("PublishedItem", published_item_id_for(lineage)) is not None


def _outcome(result: dict[str, Any]) -> tuple[str, str | None]:
    """``("ok", None)`` when the re-render went through, ``("running" | "unknown", why)`` when it has not ended or its request got no answer (neither is a failure), else ``("failed", why)``."""
    if result.get("status") in ("still-running", "unknown"):
        return ("running" if result["status"] == "still-running" else "unknown"), str(result.get("error"))
    if result.get("error"):
        return "failed", str(result["error"].get("message") or result["error"].get("code") or "refused")
    rendered = result.get("rendered") or {}
    if not result.get("ok") or rendered.get("ok") is False:
        return "failed", "; ".join(str(error) for error in rendered.get("errors") or []) or "the re-render did not finish"
    return "ok", None


def progress_line(lineage: str) -> None:
    """Printed before each re-render (stderr, so --json stays clean): one call can take about a minute and the server has no batch path."""
    print(f"rerendering {lineage} (about a minute)...", file=sys.stderr, flush=True)


def rerender_stories(client, lineages: list[str], *, request=None, cap: int = RERENDER_CAP, progress=None) -> dict[str, Any]:
    """Re-renders the published stories among ``lineages`` (deduplicated, unpublished skipped), at most ``cap`` of them, one request each.

    Returns ``{"rerendered": [{"lineageId", "status": "ok" | "running" | "unknown" | "failed", "purged": False, "error"?}], "notRun": [lineage ids over the cap], "warnings": [text]}``.
    Never raises for a failed request: a failure is a row and a warning."""
    request = request or request_story_rerender
    published = [lineage for lineage in dict.fromkeys(str(value) for value in lineages if value) if is_published(client, lineage)]
    run, not_run = published[:cap], published[cap:]
    rows: list[dict[str, Any]] = []
    for lineage in run:
        if progress:
            progress(lineage)
        try:
            status, problem = _outcome(request(client, lineage))
        except Exception as error:  # noqa: BLE001 - a missing lane or a refused request must never fail the link command
            status, problem = "failed", (str(error).strip().splitlines()[0] if str(error).strip() else error.__class__.__name__)
        rows.append({"lineageId": lineage, "status": status, "purged": False, **({"error": problem} if problem else {})})
    warnings = []
    failed = [row for row in rows if row["status"] == "failed"]
    if failed:
        warnings.append(
            "The link was saved, but the page re-render failed for " + ", ".join(row["lineageId"] for row in failed)
            + " (" + "; ".join(f"{row['lineageId']}: {row['error']}" for row in failed) + "). "
            "The pages also update when something next re-renders them. To re-render by hand, no purge: " + "; ".join(manual_command(row["lineageId"]) for row in failed))
    for row in rows:
        if row["status"] in ("running", "unknown"):
            warnings.append(f"The link was saved. The page re-render for {row['lineageId']} has not been confirmed: {row['error']}. This is not a failure. Check how it ended with: {manual_command(row['lineageId'])} --status")
    if not_run:
        warnings.append(f"More than {cap} stories changed, so these were not re-rendered: " + ", ".join(not_run) + ". Run, no purge: " + "; ".join(manual_command(lineage) for lineage in not_run))
    return {"rerendered": rows, "notRun": not_run, "warnings": warnings}


def rerender_after_write(client, lineages: list[str], *, enabled: bool = True, request=None, cap: int = RERENDER_CAP, progress=None) -> dict[str, Any]:
    """The one call every link command and agent tool makes after a real write that created something. ``lineages`` is empty when nothing was written."""
    if not enabled or not lineages:
        return {"rerendered": [], "notRun": [], "warnings": []}
    return rerender_stories(client, lineages, request=request, cap=cap, progress=progress)


def announce(done: dict[str, Any], *, quiet: bool = False) -> None:
    """The CLI's lines: one per re-rendered story (stdout, unless ``quiet`` for --json), the visible-within line, and the warnings on stderr."""
    if not quiet:
        for row in done["rerendered"]:
            print("\t".join(["rerender", row["lineageId"], "no purge", row["status"]]))
        if any(row["status"] == "ok" for row in done["rerendered"]):
            print(VISIBLE_LINE)
    for warning in done["warnings"]:
        print(f"warning\t{warning}", file=sys.stderr)


def tool_result(done: dict[str, Any]) -> dict[str, Any]:
    """The fields the agent tools add to their result."""
    return {"rerendered": done["rerendered"], **({"rerenderWarnings": done["warnings"]} if done["warnings"] else {})}
