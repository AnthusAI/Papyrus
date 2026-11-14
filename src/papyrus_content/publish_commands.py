"""CLI entries for ``papyrus content publish`` and ``unpublish`` (PPY-b3a10e)."""

from __future__ import annotations

import json
import re
import sys
from typing import Any, Callable

from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_options, resolve_mutation_apply
from .projection_trigger import (
    SKIP_LINE,
    item_task,
    projection_enabled,
    projection_unknown,
    retry_command,
    skipped_projection,
    trigger_projection,
    trigger_projection_as_user,
)
from .publish_stages import (
    DEFAULT_VERIFY_SECONDS,
    EXIT_CHECKLIST_OPEN,
    EXIT_OK,
    EXIT_SAVE_FAILED,
    exit_code_of,
    invalidated_stage,
    projected_stage,
    settle_late_projection,
    verdict_for,
    verified_stage,
)
from .publishing import DryRunClient, PublishError, publish_item, unpublish_item
from .rebuild_trigger import (
    DEFAULT_READER_BRANCH,
    DEFAULT_STAGING_BRANCH,
    READER_APP_ID_ENV,
    reader_target_from_environment,
    trigger_pretext_revalidation,
    trigger_rebuild,
    trigger_staging_build,
)

DEFAULT_ACTOR = "papyrus-cli"
# The slug a story gets when it is created (``draft-<section>-<hash>``) until someone runs ``stories set-slug``.
PLACEHOLDER_SLUG = re.compile(r"^draft-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{8,16}$")


def is_placeholder_slug(slug: Any) -> bool:
    return bool(PLACEHOLDER_SLUG.match(str(slug or "")))


def refuse_placeholder_slug(client, item_id: str) -> None:
    item = client.get_record("Item", item_id) or {}
    if is_placeholder_slug(item.get("slug")):
        raise PublishError(
            "placeholder-slug",
            f"{item_id} still has the placeholder slug {item['slug']!r}, so publishing would put the page at that address. "
            f"Give it a real address first: papyrus stories set-slug --story {item_id} --slug <new-slug>",
        )


def resolve_item_id(client, options: dict[str, Any]) -> str:
    item_id = normalize_string(options.get("id"))
    slug = normalize_string(options.get("slug"))
    if bool(item_id) == bool(slug):
        raise ValueError("Pass exactly one of --id <item-id> or --slug <slug>.")
    if item_id:
        return item_id
    section = normalize_string(options.get("section"))
    matches = client.list_by_index("itemBySlug", slug)
    if section:
        matches = [match for match in matches if match.get("section") == section]
    if not matches:
        raise ValueError(f"No item with slug {slug!r}.")
    if len(matches) > 1:
        ids = ", ".join(sorted(match["id"] for match in matches))
        raise ValueError(f"Slug {slug!r} matches more than one item ({ids}); pass --id.")
    return matches[0]["id"]


def run_site_triggers(client, options: dict[str, Any], result, *, unpublished: bool = False) -> dict[str, Any]:
    projecting = projection_enabled() or projection_unknown()
    if options.get("no-trigger"):
        return {"projection": skipped_projection()} if projecting else {}
    triggers: dict[str, Any] = {}
    if projecting:
        task = item_task(result.item_id, unpublished=unpublished, published_item_id=result.published_item_id if result.changed else None)
        from .user_auth_mode import user_auth_requested

        # The signed-in lane has no AWS credentials to invoke the function, so it asks the newsroom's own mutation.
        triggers["projection"] = trigger_projection_as_user(client, task) if user_auth_requested() else trigger_projection(task)
    if not result.changed:
        return triggers
    item = client.get_record("Item", result.item_id) or {}
    # A site whose pages are projected has no Pretext reader to revalidate; the signed-in lane learns that from the projection answer.
    projects_pages = projection_enabled() or bool((triggers.get("projection") or {}).get("projectsPages"))
    if item.get("slug") and not projects_pages:
        try:
            revalidated = trigger_pretext_revalidation([item["slug"]], None)
        except Exception as error:  # noqa: BLE001 - a trigger failure never fails the publish
            revalidated = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        if revalidated is not None:
            triggers["revalidated"] = revalidated
    environment_app_id, environment_branch = reader_target_from_environment()
    app_id = normalize_string(options.get("rebuild-app-id")) or environment_app_id
    if app_id:
        branch = normalize_string(options.get("rebuild-branch")) or environment_branch
        triggers["rebuild"] = trigger_rebuild(reader_app_id=app_id, reader_branch=branch)
    return triggers


def _verify_seconds(options: dict[str, Any]) -> float:
    raw = normalize_string(options.get("verify-seconds"))
    return float(raw) if raw and raw.replace(".", "", 1).isdigit() else float(DEFAULT_VERIFY_SECONDS)


def _stage_lines(stages: dict[str, dict[str, Any]]) -> list[str]:
    saved, projected, invalidated, verified = stages["saved"], stages["projected"], stages["invalidated"], stages["verified"]
    pages = len(projected.get("pages") or [])
    lines = [f"  saved: ok (published version {saved.get('versionNumber')})"]
    lines.append(f"  projected: {projected['status']}" + (f", {pages} pages written" if pages else "") + (f" ({projected['error']})" if projected.get("error") else ""))
    lines.append(f"  cache invalidated: {invalidated['status']}" + (f", {len(invalidated.get('paths') or [])} paths" if invalidated.get("paths") else "")
                 + (f", {len(invalidated['skippedPaths'])} NOT purged" if invalidated.get("skippedPaths") else ""))
    lines.append(f"  publicly verified: {verified['status']}" + (f" ({verified['reason']})" if verified.get("reason") else ""))
    return lines


def _run(flags: list[str], label: str, action: Callable[..., Any], *, unpublished: bool = False) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, label)
    client, claims = create_authoring_client()
    actor = normalize_string((claims or {}).get("sub")) or DEFAULT_ACTOR
    item_id = resolve_item_id(client, options)
    target = client if apply else DryRunClient(client)
    try:
        if not unpublished:
            refuse_placeholder_slug(client, item_id)
            if apply:
                from .projection.runtime import render_preflight

                render_preflight(client, item_id)   # only where this process projects (the operator's lane); the signed-in lane's function does it
        result = action(target, item_id, actor=actor)
    except PublishError as error:
        payload = {
            "ok": False,
            "code": error.code,
            "message": error.message,
            "errors": [entry.to_dict() for entry in error.errors],
            **error.details,   # checklist-open: "openSteps": [{"key", "label"}]
        }
        exit_code = EXIT_CHECKLIST_OPEN if error.code == "checklist-open" else EXIT_SAVE_FAILED
        payload.update({"stage": "saved", "exitCode": exit_code})
        if options.get("json"):
            print(json.dumps(payload, indent=2))
        else:
            print(f"{label} failed [{error.code}]: {error.message}")
            for step in error.details.get("openSteps") or []:
                print(f"  open step: {step['key']}: {step['label']}")
        raise SystemExit(exit_code)
    planned = [] if apply else target.planned
    triggers: dict[str, Any] = {}
    if apply and (result.changed or projection_enabled() or projection_unknown()):
        triggers = run_site_triggers(client, options, result, unpublished=unpublished)
    projection = triggers.get("projection") or {}
    stages: dict[str, dict[str, Any]] = {"saved": {"status": "ok", "changed": result.changed, "versionNumber": result.version_number, "dryRun": not apply}}
    verify = bool(options.get("verify")) and apply and not unpublished
    if apply:
        stages["projected"] = projected_stage(projection)
        stages["invalidated"] = invalidated_stage(projection)
        stages["verified"] = (
            verified_stage(projection, result.version_number, wait=verify, seconds=_verify_seconds(options))
            if not unpublished and projection.get("ok") is not False
            else {"status": "not-checked", "reason": "unpublish, or the page was not built"}
        )
        settle_late_projection(stages)
        exit_code, failed_stage = exit_code_of(stages, verify=verify)
    else:
        exit_code, failed_stage = EXIT_OK, "ok"
    payload = {
        "ok": exit_code == EXIT_OK,
        "dryRun": not apply,
        "changed": result.changed,
        "itemId": result.item_id,
        "publishedItemId": result.published_item_id,
        "versionNumber": result.version_number,
        "planned": planned,
        **triggers,
    }
    if apply:
        payload.update({"stages": stages, "exitCode": exit_code, "failedStage": failed_stage, "verdict": verdict_for(stages)})
    failure = None
    if exit_code != EXIT_OK:
        retry = retry_command(result.item_id, unpublished=unpublished)
        payload.update({"dataPublished": not unpublished, "pagePublished": stages["projected"]["status"] == "ok", "retry": retry})
        verb = "unpublished" if unpublished else "published"
        if failed_stage == "projection-failed":
            failure = (
                f"{label} FAILED to project the page: the data is {verb} but the page "
                f"is not {'removed' if unpublished else 'live'} ({stages['projected'].get('error') or 'unknown error'}). Retry with: {retry}"
            )
        elif failed_stage == "projection-running":
            failure = (
                f"{label} STILL RUNNING: the data is {verb} and the server has not yet confirmed the page ({stages['projected'].get('error') or 'no answer yet'}). "
                f"This is not a failure. Check with: {retry} --verify (running it again changes nothing already done)"
            )
        elif failed_stage == "invalidation-failed":
            failure = (
                f"{label}: the page is written but the edge cache was NOT fully purged ({stages['invalidated']['status']}: "
                f"{stages['invalidated'].get('reason') or 'no reason given'}). The old page can show until it expires. Not a write failure."
            )
        else:
            failure = f"{label}: the page is written and purged but the public URL still shows an older version after waiting ({stages['verified'].get('expectedVersion')} expected)."
        payload["message"] = failure
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        if failure:
            raise SystemExit(exit_code)
        return
    state = "changed" if result.changed else "unchanged"
    print(f"{label}: {result.item_id} {state} (published version {result.version_number})")
    for entry in planned:
        print(f"  would {entry['operation']} {entry['model']} {entry['id']}")
    for key, outcome in triggers.items():
        if key == "projection" and outcome.get("skipped"):
            print(f"  {SKIP_LINE}")
        else:
            print(f"  {key}: {json.dumps(outcome)}")
    if apply:
        for line in _stage_lines(stages):
            print(line)
    if failure:
        print(failure, file=sys.stderr)
        raise SystemExit(exit_code)


def content_publish(flags: list[str]) -> None:
    _run(flags, "content publish", publish_item)


def content_unpublish(flags: list[str]) -> None:
    _run(flags, "content unpublish", unpublish_item, unpublished=True)


def content_rebuild(flags: list[str]) -> None:
    options = parse_options(flags)
    wants_reader = bool(options.get("reader"))
    wants_staging = bool(options.get("staging"))
    if wants_reader == wants_staging:
        raise ValueError("Pass exactly one of --reader or --staging.")
    app_id = normalize_string(options.get("app-id"))
    if wants_reader:
        app_id = app_id or reader_target_from_environment()[0]
        if not app_id:
            raise ValueError(f"Pass --app-id <id> or set {READER_APP_ID_ENV}.")
        branch = normalize_string(options.get("branch")) or DEFAULT_READER_BRANCH
        outcome = trigger_rebuild(reader_app_id=app_id, reader_branch=branch)
    else:
        if not app_id:
            raise ValueError("Pass --app-id <id> (the CMS Amplify app).")
        branch = normalize_string(options.get("branch")) or DEFAULT_STAGING_BRANCH
        outcome = trigger_staging_build(cms_app_id=app_id, staging_branch=branch)
    print(json.dumps(outcome, indent=2))
    if outcome.get("error"):
        raise SystemExit(1)
