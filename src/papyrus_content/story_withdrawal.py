"""Withdraw a published Story and restore it: ``papyrus stories withdraw`` and ``stories restore``.

``stories move --stage spiked`` changes only the board stage and the page stays live; ``ops content unpublish`` removes the data and leaves
the Story in copywriting with no plan and no record. Withdrawal is the safe whole: it prints the exact plan first (the Story's pages and every
index page that lists it, the invalidation paths, their count and cost), refuses above the per-call path cap, unpublishes the Story, has the
site's function project the pages away, spikes the board card, records the withdrawal on the Story and purges exactly the planned paths.
Restore republishes the withdrawn version and purges the same pages. Everything reuses ``publish_item``/``unpublish_item``, the
content-actions function's projection and the guarded refresh operations; nothing here talks to CloudFront.

The record sits in the metadata of the withdrawn version: ``metadata.withdrawal`` =
``{withdrawnVersion, withdrawnBy, withdrawnAt, reason, previousStage, itemId, paths}``. ``paths`` is the purge plan, which restore reuses.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .edge_invalidation import invalidation_cost_note
from .page_refresh.budget import DRY_RUN_ABOVE
from .publishing import PublishError, publish_item, unpublish_item, utc_now_iso
from .record_helpers import to_aws_json
from .story_reporting import MAX_STAGE_MOVES, STAGE_MOVES_KEY, current_story_version, published_story_version, story_versions

WITHDRAWAL_KEY = "withdrawal"
SPIKED = "spiked"
PUBLISHED = "published"
DEFAULT_CAP = 25
SITE_FILES_NOTE = (
    "sitemap and feed files: the projection rewrites them and the site's function purges them under its own capped invalidation (not counted below)"
)

Lane = Callable[[Any, str, dict], dict]
Trigger = Callable[[Any, dict], dict]


class WithdrawalError(ValueError):
    """A request that cannot run; nothing was written. ``code`` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------- the lanes (replaced in tests)


def lane_call(client, name: str, arguments: dict) -> dict:
    """A page-refresh operation through the signed-in mutation or the operator's content-actions function, as ``ops content refresh`` does."""
    from .page_refresh.cli import run_operator, run_signed_in
    from .user_auth_mode import user_auth_requested

    return run_signed_in(client, name, arguments) if user_auth_requested() else run_operator(name, arguments)


def projection_trigger(client, task: dict) -> dict:
    from .projection_trigger import trigger_projection, trigger_projection_as_user
    from .user_auth_mode import user_auth_requested

    return trigger_projection_as_user(client, task) if user_auth_requested() else trigger_projection(task)


def projecting() -> bool:
    """Does this site project pages (so there is something to purge)? Unknown counts as yes, as for publish."""
    from .projection_trigger import projection_enabled, projection_unknown

    return projection_enabled() or projection_unknown()


# ---------------------------------------------------------------------- records


def _metadata(row: dict) -> dict:
    raw = row.get("metadata")
    if isinstance(raw, str):
        return json.loads(raw) if raw.strip() else {}
    return dict(raw or {})


def withdrawal_of(row: dict | None) -> dict | None:
    record = _metadata(row or {}).get(WITHDRAWAL_KEY)
    return record if isinstance(record, dict) else None


def withdrawn_version(client, lineage_id: str) -> tuple[dict, dict] | None:
    """The version that was withdrawn and its record, or None."""
    for row in story_versions(client, lineage_id):
        record = withdrawal_of(row)
        if record:
            return row, record
    return None


def _write_stage(client, row: dict, stage: str, *, previous: str, actor: str, reason: str | None, now: str, record: dict | None) -> None:
    """Sets a version's board stage and its withdrawal record in one write, and logs the move the way ``stories move`` does."""
    stored = client.get_record("Item", row["id"]) or row
    metadata = _metadata(stored)
    if record is None:
        metadata.pop(WITHDRAWAL_KEY, None)
    else:
        metadata[WITHDRAWAL_KEY] = record
    moves = [move for move in metadata.get(STAGE_MOVES_KEY) or [] if isinstance(move, dict)]
    moves.append({"at": now, "from": previous, "to": stage, "by": actor, "reason": reason})
    metadata[STAGE_MOVES_KEY] = moves[-MAX_STAGE_MOVES:]
    client.update_record("Item", {"id": row["id"], "stage": stage, "updatedAt": now, "metadata": to_aws_json(metadata)})


def _sync_checklist(client, lineage_id: str) -> None:
    from .story_checklist import sync_quietly

    sync_quietly(client, lineage_id)


# ---------------------------------------------------------------------- plans


def _cost_text(cost: dict, count: int) -> str:
    return (f"the first {cost.get('freePathsPerMonth', 1000):,} paths a month are free, then {cost.get('usdPerPathAfterFree', 0.005)} USD each: "
            f"at most {cost.get('usdAtMost', 0)} USD for {count} paths")


def _plan_from_lane(client, lineage_id: str, force_paths: int | None, lane: Lane) -> dict:
    """The Story's pages and the pages that list it, from the same dry run ``ops content refresh --story`` makes."""
    arguments: dict[str, Any] = {"storyLineageId": lineage_id, "dryRun": True}
    if force_paths:
        arguments["forcePaths"] = force_paths
    try:
        result = lane(client, "site_refresh_story", arguments)
    except Exception as error:  # noqa: BLE001 - no lane means no plan, and so no withdrawal
        raise WithdrawalError("plan_failed", f"Could not work out which pages to purge, so nothing was changed: {error}") from error
    invalidation = result.get("invalidation")
    if not invalidation:
        message = (result.get("error") or {}).get("message", "the site gave no plan")
        raise WithdrawalError("plan_failed", f"Could not work out which pages to purge, so nothing was changed: {message}")
    pages = result.get("pages") or {}
    guard = invalidation.get("guard") or {}
    return {
        "storyPages": list(pages.get("story") or []),
        "listingPages": list(pages.get("indexes") or []),
        "paths": list(invalidation["paths"]),
        "count": invalidation["count"],
        "cost": invalidation["cost"],
        "cap": guard.get("cap", DEFAULT_CAP),
        "refusal": (guard.get("refusal") or {}).get("message"),
    }


def _recorded_plan(record: dict, force_paths: int | None) -> dict:
    """Restore reuses the paths planned at withdrawal: the same Story page, twin and listing pages."""
    paths = list(record.get("paths") or [])
    cap = force_paths or DEFAULT_CAP
    refusal = None
    if len(paths) > cap:
        refusal = (f"{len(paths)} paths is over the cap of {cap} paths per call. Nothing was written or invalidated. "
                   f"Force this one call with --force-paths {len(paths)}.")
    return {"storyPages": [], "listingPages": [], "paths": paths, "count": len(paths), "cost": invalidation_cost_note(len(paths)), "cap": cap, "refusal": refusal,
            "recorded": True}


def _purgeable(paths: list[str]) -> list[str]:
    """The planned paths in the forms ``site_refresh_pages`` expands exactly back to themselves (a bare ``/x`` would also pull in ``/x/`` forms)."""
    return [path for path in paths if path.endswith("/") or "." in path.rsplit("/", 1)[-1]]


def _reconcile_purge(client, plan: dict, outcome: dict, force_paths: int | None, lane: Lane) -> dict:
    """The projection function purges what it wrote under its own cap. Purge any planned path it did not, through the guarded refresh operation."""
    from .publish_stages import invalidated_stage

    stage = invalidated_stage(outcome) if outcome.get("ok") is True else {"status": "not-applicable", "paths": []}
    done = set(stage.get("paths") or []) if stage.get("status") == "ok" else set()
    missing = [path for path in plan["paths"] if path not in done]
    report: dict[str, Any] = {"byProjection": sorted(done), "status": stage["status"], "extra": sorted(done - set(plan["paths"]))}
    if not missing:
        report.update(ok=True, purged=[], count=0)
        return report
    arguments: dict[str, Any] = {"paths": _purgeable(missing), "confirm": True}
    if force_paths:
        arguments["forcePaths"] = force_paths
    try:
        result = lane(client, "site_refresh_pages", arguments)
    except Exception as error:  # noqa: BLE001
        report.update(ok=False, purged=[], count=0, error=f"{type(error).__name__}: {error}")
        return report
    invalidation = result.get("invalidation") or {}
    report.update(ok=bool(result.get("ok")), purged=list(invalidation.get("paths") or []), count=invalidation.get("count", 0), status=invalidation.get("status"),
                  requests=invalidation.get("requests", []))
    if result.get("error"):
        report["error"] = result["error"].get("message") if isinstance(result["error"], dict) else str(result["error"])
    return report


# ---------------------------------------------------------------------- withdraw


def withdraw_story(
    client, lineage_id: str, *, actor: str, reason: str | None = None, dry_run: bool = False, run: bool = False, force_paths: int | None = None,
    lane: Lane | None = None, trigger: Trigger | None = None, now: str | None = None,
) -> dict[str, Any]:
    """Withdraws the Story's published version. ``status``: ``dry-run`` | ``needs-run`` | ``refused`` | ``withdrawn`` | ``already-withdrawn``.

    Raises ``WithdrawalError`` for a Story that is not published (nothing was written)."""
    lane, trigger = lane or lane_call, trigger or projection_trigger
    current = current_story_version(client, lineage_id)
    lineage_id = current.get("lineageId") or lineage_id
    published = published_story_version(client, lineage_id)
    base = {"operation": "stories_withdraw", "lineageId": lineage_id, "dryRun": dry_run}
    if published is None:
        found = withdrawn_version(client, lineage_id)
        if found:
            row, record = found
            return {**base, "status": "already-withdrawn", "itemId": row["id"], "record": record}
        raise WithdrawalError("not_published", f"Story {lineage_id} is not published, so there is nothing to withdraw. Nothing was changed.")
    item_id = published["id"]
    result: dict[str, Any] = {**base, "itemId": item_id, "versionNumber": published.get("versionNumber"), "slug": published.get("slug"), "section": published.get("section")}
    plan = _plan_from_lane(client, lineage_id, force_paths, lane) if projecting() else None
    result["plan"] = plan
    if plan and plan["refusal"]:
        return {**result, "status": "refused", "error": {"code": "over_path_cap", "message": plan["refusal"]}}
    if dry_run:
        return {**result, "status": "dry-run"}
    if plan and plan["count"] > DRY_RUN_ABOVE and not run:
        return {**result, "status": "needs-run"}

    now = now or utc_now_iso()
    previous_stage = current.get("stage") or PUBLISHED
    record = {
        "withdrawnVersion": published.get("versionNumber"), "withdrawnBy": actor, "withdrawnAt": now, "reason": reason,
        "previousStage": previous_stage, "itemId": item_id, "paths": plan["paths"] if plan else [],
    }
    unpublish_item(client, item_id, actor=actor, now=now)
    _write_stage(client, published, SPIKED, previous=previous_stage, actor=actor, reason=reason, now=now, record=record)
    if current["id"] != item_id:
        _write_stage(client, current, SPIKED, previous=current.get("stage") or "copywriting", actor=actor, reason=reason, now=now, record=None)
    _sync_checklist(client, lineage_id)
    result.update(status="withdrawn", record=record, ok=True)
    if plan is not None:
        from .projection_trigger import item_task, retry_command

        outcome = trigger(client, item_task(item_id, unpublished=True))
        result["projection"] = outcome
        if outcome.get("ok") is not True:
            result.update(ok=False, retry=retry_command(item_id, unpublished=True))
            return result
        result["purge"] = _reconcile_purge(client, plan, outcome, force_paths, lane)
        result["ok"] = bool(result["purge"]["ok"])
    return result


# ---------------------------------------------------------------------- restore


def restore_story(
    client, lineage_id: str, *, actor: str, dry_run: bool = False, run: bool = False, force_paths: int | None = None,
    lane: Lane | None = None, trigger: Trigger | None = None, now: str | None = None,
) -> dict[str, Any]:
    """Republishes the withdrawn version. ``status``: ``dry-run`` | ``needs-run`` | ``refused`` | ``restored``.

    Raises ``WithdrawalError`` when nothing was withdrawn, or the republish is refused (nothing was written)."""
    lane, trigger = lane or lane_call, trigger or projection_trigger
    current = current_story_version(client, lineage_id)
    lineage_id = current.get("lineageId") or lineage_id
    found = withdrawn_version(client, lineage_id)
    if found is None or published_story_version(client, lineage_id) is not None:
        raise WithdrawalError("not_withdrawn", f"Story {lineage_id} was not withdrawn (there is no withdrawal record, or it is published), so there is nothing to restore. Nothing was changed.")
    row, record = found
    item_id = row["id"]
    base = {"operation": "stories_restore", "lineageId": lineage_id, "dryRun": dry_run, "itemId": item_id, "versionNumber": record.get("withdrawnVersion"), "record": record}
    plan = _recorded_plan(record, force_paths) if projecting() else None
    base["plan"] = plan
    if plan and plan["refusal"]:
        return {**base, "status": "refused", "error": {"code": "over_path_cap", "message": plan["refusal"]}}
    if dry_run:
        return {**base, "status": "dry-run"}
    if plan and plan["count"] > DRY_RUN_ABOVE and not run:
        return {**base, "status": "needs-run"}

    now = now or utc_now_iso()
    try:
        publish_item(client, item_id, actor=actor, now=now)
    except PublishError as error:
        raise WithdrawalError(error.code, f"The withdrawn version cannot be republished yet [{error.code}]: {error.message} Nothing was changed.") from error
    _write_stage(client, row, PUBLISHED, previous=SPIKED, actor=actor, reason="restored after withdrawal", now=now, record=None)
    if current["id"] != item_id:
        # publish_item makes the published version the lineage's current one; a newer working draft stays the working record.
        client.update_record("Item", {"id": current["id"], "versionState": "current"})
        client.update_record("Item", {"id": item_id, "versionState": "superseded"})
        if current.get("stage") == SPIKED:
            _write_stage(client, current, record.get("previousStage") or "copywriting", previous=SPIKED, actor=actor, reason="restored after withdrawal", now=now, record=None)
    _sync_checklist(client, lineage_id)
    result = {**base, "status": "restored", "ok": True}
    if plan is not None:
        from .projection_trigger import item_task, retry_command

        outcome = trigger(client, item_task(item_id, unpublished=False))   # no published_item_id: a restore is not a new publication to announce
        result["projection"] = outcome
        if outcome.get("ok") is not True:
            result.update(ok=False, retry=retry_command(item_id, unpublished=False))
            return result
        result["purge"] = _reconcile_purge(client, plan, outcome, force_paths, lane)
        result["ok"] = bool(result["purge"]["ok"])
    return result


# ---------------------------------------------------------------------- text


def render_lines(result: dict[str, Any]) -> list[str]:
    """The CLI's output, one text form for the plan and the outcome."""
    verb = "withdraw" if result["operation"] == "stories_withdraw" else "restore"
    lineage, status = result["lineageId"], result["status"]
    if status == "already-withdrawn":
        record = result["record"]
        return [f"stories\twithdraw\talready-withdrawn\t{lineage}\tversion {record.get('withdrawnVersion')}\tby {record.get('withdrawnBy')} at {record.get('withdrawnAt')}",
                f"  reason: {record.get('reason') or 'none given'}", f"  nothing was changed. To bring it back: papyrus stories restore --story {lineage}"]
    lines: list[str] = []
    plan = result.get("plan")
    head = f"stories\t{verb}\tplan\t{lineage}\titem {result['itemId']}\tversion {result.get('versionNumber')}"
    lines.append(head + ("\tdry run: nothing written" if result.get("dryRun") else ""))
    if plan is None:
        lines.append("  this site does not project pages: only the data changes, and there is nothing to purge")
    else:
        if plan.get("recorded"):
            lines.append("  pages as planned when it was withdrawn (the listing pages are rebuilt from the data as it is now):")
        else:
            lines.append(f"  story page and Markdown twin: {', '.join(plan['storyPages']) or 'none'}")
            lines.append(f"  index pages that list it (home, lists, sections, archives, tags; {len(plan['listingPages'])}): {', '.join(plan['listingPages']) or 'none'}")
        lines.append(f"  {SITE_FILES_NOTE}")
        lines.append(f"  invalidation: {plan['count']} paths (per-call cap {plan['cap']})")
        lines.append(f"  cost: {_cost_text(plan['cost'], plan['count'])}")
        lines.extend(f"    {path}" for path in plan["paths"])
    if status == "refused":
        lines.append(f"stories\t{verb}\trefused\t{lineage}\t{result['error']['message']}")
    elif status == "needs-run":
        lines.append(f"stories\t{verb}\tnot run\t{lineage}\tmore than {DRY_RUN_ABOVE} paths is a dry run until you repeat the command with --run")
    elif status == "dry-run":
        lines.append(f"stories\t{verb}\tdry-run\t{lineage}\tnothing written, nothing purged")
    else:
        past = "withdrawn" if verb == "withdraw" else "restored"
        lines.append(f"stories\t{verb}\t{past}\t{lineage}\tstage {SPIKED if verb == 'withdraw' else PUBLISHED}")
        outcome = result.get("projection")
        if outcome is not None:
            lines.append(f"  projection: {'ok' if outcome.get('ok') is True else 'FAILED'}" + (f" ({outcome['error']})" if outcome.get("error") else ""))
            if result.get("retry"):
                lines.append(f"  the data is {past} but the pages were not updated. Retry with: {result['retry']}")
        purge = result.get("purge")
        if purge is not None:
            lines.append(f"  purged by the projection function: {len(purge['byProjection'])} paths ({purge['status']})")
            lines.append(f"  purged by this command: {purge['count']} paths" + (f" FAILED: {purge['error']}" if purge.get("error") else ""))
            lines.extend(f"    {path}" for path in purge["purged"])
    return lines
