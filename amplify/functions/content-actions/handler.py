from __future__ import annotations

import json
import os
from typing import Any

from papyrus_content import request_meter
from papyrus_content.edge_invalidation import distribution_ids_from_environment, invalidate_revalidated_paths
from papyrus_content.graphql_authoring import create_authoring_client
from papyrus_content.markus_renderer.body_features import install_body_features
from papyrus_content.markus_renderer.derive import derive_body
from papyrus_content.projection.deploy_render import deploy_render, drift_metric_line
from papyrus_content.projection.lease import ProjectionLeaseHeld
from papyrus_content.projection.publish_jobs import DONE, FAILED, QUEUED, RUNNING, publish_jobs_from_environment
from papyrus_content.projection.engine import project, project_all, project_item_pages
from papyrus_content.page_refresh.operations import BY_NAME as PAGE_REFRESH_OPERATIONS, run_operation as run_page_refresh, validate as validate_page_refresh
from papyrus_content.page_refresh.budget import DRY_RUN_ABOVE, budget_from_environment
from papyrus_content.page_refresh.service import RefreshError, RefreshService
from papyrus_content.home_page.runtime import stores_for as home_page_stores_for
from papyrus_content.home_page.task import TASK_NAME as HOME_PAGE_SNAPSHOT_TASK, home_page_settings_of, run_home_page_snapshot
from papyrus_content.projection.story_stars_task import TASK_NAME as STORY_STARS_TASK, run_story_stars_task
from papyrus_content.reader_steering.task import TASK_NAME as READER_SNAPSHOT_TASK, run_reader_snapshot
from papyrus_content.projection.runtime import (
    DEAD_LETTER_QUEUE_ENV,
    EDGE_DISTRIBUTION_ENV,
    context_from_environment,
    targeted_invalidation,
    projection_configured,
    public_item_url,
    render_body_preflight,
    render_preflight,
    site_body_features,
)
from papyrus_content.rebuild_trigger import (
    DEFAULT_STAGING_BRANCH,
    reader_target_from_environment,
    trigger_pretext_revalidation,
    trigger_rebuild,
    trigger_staging_build,
)
from papyrus_content.story_reporting import save_story_version
from papyrus_content.story_schedule import TASK_NAME as PUBLISH_SCHEDULED_TASK, Caller, ScheduleError, ScheduleService, run_operation as run_schedule_operation, scheduler_from_environment, ZONE_ENV as PUBLICATION_ZONE_ENV
from papyrus_content.live_schema import wait_for_live_schema
from papyrus_content.publication import ensure_publication_from_environment
from papyrus_content.editorial_checks import GraphQLEditorialStore, ensure_default_policies
from papyrus_content.item_language_backfill import ensure_item_languages
from papyrus_content.reference_intake import IntakeError, intake_email_submission_references, intake_references
from papyrus_content.publish_alerts import PUBLISHED_TASK_KEY, announce_published
from papyrus_content.publishing import (
    ItemFields,
    PublishError,
    publish_item,
    published_item_id_for,
    save_item,
    unpublish_item,
    utc_now_iso,
)


# Save and publish validate a body with the features of the projector that renders the page.
install_body_features(site_body_features)


def parse_input(raw: Any) -> dict:
    parsed = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    if not isinstance(parsed, dict):
        raise PublishError("invalid-input", "The input must be a JSON object.")
    return parsed


def actor_from_event(event: dict) -> str:
    identity = event.get("identity") or {}
    return identity.get("username") or identity.get("sub") or "unknown"


def person_from_event(event: dict) -> str | None:
    """The signed-in newsroom user (a Cognito user pool identity) behind the call, or None for IAM, a direct invoke or anything else.
    Publishing as a person is that person's approval, so an editor is not blocked by their own publish gate."""
    identity = event.get("identity") or {}
    return identity.get("sub") if identity.get("sub") and identity.get("issuer") else None


def failure_response(error: PublishError) -> dict:
    if error.errors:
        errors = [body_error.to_dict() for body_error in error.errors]
    else:
        errors = [{"code": error.code, "message": error.message, "line": None}]
    response = {"ok": False, "errors": errors}
    if error.details:
        response["details"] = error.details   # e.g. {"openSteps": [{"key", "label"}]} for checklist-open
    return response


def derive_markus_action(arguments: dict) -> dict:
    derivation = derive_body(arguments.get("frontMatterYaml"), arguments.get("bodyMarkus") or "")
    if not derivation.ok:
        return {"ok": False, "features": site_body_features().to_dict(), "errors": [body_error.to_dict() for body_error in derivation.errors]}
    response = {
        "ok": True,
        "features": site_body_features().to_dict(),
        "bodyIrBytes": len(json.dumps(derivation.body_ir, separators=(",", ":")).encode("utf-8")),
        "errors": [],
        "warnings": [body_error.to_dict() for body_error in derivation.warnings],   # e.g. an equation shown as TeX, or a video on a site with embeds off
    }
    if arguments.get("includeIr") is True:
        response["bodyIr"] = derivation.body_ir
    return response


PROJECTION_TASK_KEY = "projectionTask"
HOME_PAGE_SNAPSHOT_WORKERS = 8
# A publish answered before its pages are built (PPY-3acc8d): how long a build waits for a busy site before it leaves its story queued for the
# lease holder (and Lambda's retry) instead of blocking for the default two minutes; and how long a publish that projects inline waits, so its
# answer comes back inside the 30 seconds AppSync allows (a held lease then schedules the build).
QUEUED_LEASE_WAIT_SECONDS = 10.0
INLINE_LEASE_WAIT_SECONDS = 20.0
# Draining stops this long before the function's own timeout; what is left is handed to a fresh invocation.
DRAIN_RESERVE_SECONDS = 45.0
ITEM_PAGES_JOB = "__item-pages__"   # the follow-up that renders every item page: one queued run covers every publish before it


INVOKED_FUNCTION_ARN: str | None = None   # this function's own ARN, from the invocation: the Scheduler's target (an environment variable of it would be a circular reference)


def schedule_service(client) -> ScheduleService:
    """The site's scheduled-publishing service: the publication's time zone and its Scheduler come from the environment the deploy set."""
    return ScheduleService(client, zone_name=os.environ.get(PUBLICATION_ZONE_ENV), scheduler=scheduler_from_environment(invoked_function_arn=INVOKED_FUNCTION_ARN))


class ProjectionTaskFailed(Exception):
    """Raised by an asynchronous projection task so Lambda retries it and, finally, sends it to the dead letter queue."""


def send_to_projection_dead_letter_queue(task: dict, error: str) -> None:
    queue_url = (os.environ.get(DEAD_LETTER_QUEUE_ENV) or "").strip()
    if not queue_url:
        return
    try:
        import boto3

        boto3.client("sqs").send_message(
            QueueUrl=queue_url, MessageBody=json.dumps({PROJECTION_TASK_KEY: task, "error": error})
        )
    except Exception:  # noqa: BLE001 - the dead letter is best effort; the response already reports the failure
        pass


def schedule_projection_task(task: dict, error: str) -> bool:
    """Run a projection task later, in this same function, as an asynchronous invocation.

    The function has an on-failure destination (the dead letter queue), so a task
    that keeps failing ends up there for ``papyrus ops content project --reconcile``.
    """
    function_name = (os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or "").strip()
    if not function_name:
        send_to_projection_dead_letter_queue(task, error)
        return False
    try:
        import boto3

        boto3.client("lambda").invoke(
            FunctionName=function_name, InvocationType="Event", Payload=json.dumps({PROJECTION_TASK_KEY: task}).encode("utf-8")
        )
        return True
    except Exception as scheduling_error:  # noqa: BLE001 - fall back to the dead letter queue
        send_to_projection_dead_letter_queue(task, f"{error}; scheduling failed: {scheduling_error}")
        return False


def projection_context(client):
    context = context_from_environment(client)
    context.defer_follow_up = True
    return context


def bulk_projection_context(client):
    """The context for a deploy-time or whole-site render: in targeted mode (the default) it never purges, however few pages it wrote."""
    context = projection_context(client)
    if targeted_invalidation(os.environ):
        context.invalidate = None
    return context


def project_item_action(client, item_id: str, *, unpublished: bool, published_item_id: str | None = None) -> dict:
    """Project one item. ``published_item_id`` is passed only for a real publish: the alert is announced once the page
    is live, here when the projection succeeds, or by the scheduled retry (which carries the same marker) when it did not."""
    if not projection_configured():
        if published_item_id:
            announce_published(item_id, published_item_id)
        return {}
    liveness = {} if unpublished else {"live": False}
    task = {"task": "item", "itemId": item_id, "unpublished": unpublished}
    if published_item_id:
        task[PUBLISHED_TASK_KEY] = {"publishedItemId": published_item_id}
    context = projection_context(client)
    shorten_lease_wait(context, INLINE_LEASE_WAIT_SECONDS)
    try:
        report = project(context, item_id, unpublished=unpublished)
    except Exception as error:  # noqa: BLE001 - a projection failure never fails the save
        message = f"{type(error).__name__}: {error}"
        schedule_projection_task(task, message)
        return {**liveness, "projected": False, "paths": [], "error": message}
    response = {"projected": report.ok, "paths": [*report.written, *report.deleted], "itemPaths": list(report.item_paths), "invalidation": invalidation_outcome(context, report)}
    if not unpublished:
        response["live"] = report.ok
        url = public_item_url(os.environ, report.item_paths)
        if url:
            response["url"] = url
        if report.ok and not report.item_paths:
            # Published is recorded, but the site has no page for this Item (a type with no urls.types entry and no section route, or a link-only section).
            response["noPublicPage"] = True
    if not report.ok:
        message = "; ".join(report.errors)
        schedule_projection_task(task, message)
        response["error"] = message
    if report.unpurged:
        response["edgePurged"] = False
        schedule_unpurged_invalidation(report.unpurged)
    if report.invalidation_capped:
        # targeted mode, over publication.cache.maxInvalidationPaths: the first paths were purged, the rest are named and not retried (never a wildcard)
        response["edgePurged"] = False
        response["invalidationCapped"] = report.invalidation_capped
    if report.follow_up_item_pages:
        schedule_item_pages(item_id)
    if report.ok and published_item_id:
        announce_published(item_id, published_item_id)
    return response


def shorten_lease_wait(context, seconds: float) -> None:
    lease = getattr(context, "lease", None)
    if isinstance(getattr(lease, "wait_seconds", None), (int, float)):
        lease.wait_seconds = min(lease.wait_seconds, seconds)


def schedule_item_pages(except_item_id: str | None) -> None:
    """Schedule the follow-up that renders every item page again, unless one is already queued: that run reads the site when it starts, so it covers this change too."""
    jobs = publish_jobs_from_environment()
    if jobs is not None:
        job, joined = jobs.request(ITEM_PAGES_JOB, None)
        if joined:
            return
        schedule_projection_task({"task": "item-pages", "exceptItemId": except_item_id, "jobId": job["jobId"]}, "follow-up")
        return
    schedule_projection_task({"task": "item-pages", "exceptItemId": except_item_id}, "follow-up")


def invalidation_outcome(context, report) -> dict:
    """What the edge purge of this projection did, as its own outcome (PPY-2745c1): ``ok``, ``skipped`` (the site's setting or no distribution),
    ``failed`` (retried by the function) or ``capped`` (targeted mode over its cap; the rest is named, never a wildcard)."""
    if context.invalidate is None:
        return {"status": "skipped", "reason": "this site does not invalidate on publish (publication.cache.invalidation is off, or it has no CloudFront distribution)", "paths": []}
    if report.unpurged:
        return {"status": "failed", "reason": "the purge was refused or failed; the function retries it", "paths": [], "unpurgedKeys": list(report.unpurged)}
    if report.invalidation_capped:
        return {"status": "capped", "reason": "more paths than publication.cache.maxInvalidationPaths; the first were purged, the rest were not", "paths": list(report.invalidated), "skippedPaths": list(report.invalidation_capped)}
    return {"status": "ok", "paths": list(report.invalidated)}


def schedule_unpurged_invalidation(keys: list[str]) -> None:
    schedule_projection_task({"task": "invalidate", "keys": keys}, "edge invalidation failed")


PAGE_REFRESH_RERENDER_TASK = "page-refresh-rerender"


def refresh_service(client, who: str = "content-actions") -> RefreshService:
    """The page-refresh operations (``papyrus_content/page_refresh``) over this site's projection context and CloudFront distribution.

    This function is the only place the operations purge: it enforces the per-call path cap and dry-run-first. A caller never needs ``cloudfront:CreateInvalidation`` itself."""
    return RefreshService(
        distribution_id=(os.environ.get(EDGE_DISTRIBUTION_ENV) or "").strip() or None,
        context=lambda: projection_context(client),
        budget=budget_from_environment(os.environ),
        public_url=(os.environ.get("PAPYRUS_SITE_PUBLIC_URL") or "").strip() or None,
    )


def rerender_job_key(inputs: dict) -> str:
    """The key of a page re-render's job record: one per distinct request, so the same request while one is queued joins it and a different one does not."""
    parts = [inputs["scope"], inputs.get("storyLineageId") or "", "purge" if inputs.get("invalidate", True) is not False else "no-purge", ",".join(inputs.get("under") or [])]
    return "rerender#" + "#".join(parts)


def rerender_job_outcome(result: dict) -> dict:
    """What a finished re-render job tells its asker: what was written and what the purge did, in the fields the command prints."""
    rendered = result.get("rendered") or {}
    invalidation = result.get("invalidation") or {}
    outcome = {
        "rendered": {"ok": bool(rendered.get("ok")), "count": rendered.get("count", 0), "errors": [str(error) for error in rendered.get("errors") or []]},
        "invalidation": {key: invalidation[key] for key in ("ok", "status", "count", "error") if key in invalidation},
    }
    if not result.get("ok"):
        outcome["error"] = "; ".join(outcome["rendered"]["errors"]) or str((invalidation.get("error") or "the re-render did not finish"))
    return outcome


def rerender_status_action(inputs: dict) -> dict:
    """``refreshSitePages`` with ``{"operation": "site_rerender_pages", "jobStatus": true}`` and the ``jobKey`` a re-render answered with (or the same request fields): where a page re-render started with ``async`` stands. Reads one record."""
    jobs = publish_jobs_from_environment()
    key = str(inputs.get("jobKey") or (rerender_job_key(inputs) if inputs.get("scope") else ""))
    if not key.startswith("rerender#"):
        return {"ok": False, "operation": "site_rerender_pages", "error": {"code": "invalid_input", "message": "jobKey (the key a re-render answered with) or the scope of the request is required."}}
    if jobs is None:
        return {"ok": True, "operation": "site_rerender_pages", "jobKey": key, "job": {"state": "unknown", "reason": "this site keeps no job records (no projection lock table)"}}
    return {"ok": True, "operation": "site_rerender_pages", "jobKey": key, "job": job_answer(jobs.status(key))}


def refresh_site_pages_action(arguments: dict, who: str = "content-actions") -> dict:
    """An editor's or agent's page refresh (PPY-105508): the operations the CLI and the MCP tools run, here with the function's own AWS rights.

    Purging is quick and runs now. A re-render of every index page or of the whole site can outlast the request, so once it has passed the
    guard it is scheduled as an asynchronous task that re-renders and then purges what it wrote. A re-render of one Story runs inside the call
    unless the caller asks for ``async`` (the CLI does), which schedules it the same way. A scheduled re-render keeps a job record (``jobKey``,
    ``job``) that ``jobStatus`` reads, so a caller learns how it ended however long it took, and AppSync's 30 s never matter (PPY-4611d5).
    """
    name = str(arguments.get("operation") or "")
    inputs = {key: value for key, value in arguments.items() if key != "operation"}
    if not projection_configured():
        return {"ok": False, "operation": name, "error": {"code": "not_projected", "message": "This site does not project its pages to S3, so there is no edge cache to refresh from here."}}
    operation = PAGE_REFRESH_OPERATIONS.get(name)
    if operation is None:
        return run_page_refresh(name, inputs, refresh_service(None, who))
    if inputs.pop("jobStatus", False) is True:
        return rerender_status_action(inputs)
    background = inputs.pop("async", False) is True
    try:
        validate_page_refresh(operation, inputs)
    except RefreshError as error:
        return {"ok": False, "operation": name, "error": {"code": error.code, "message": error.message}}
    client, _claims = create_authoring_client()
    service = refresh_service(client, who)
    if name == "site_rerender_pages" and (inputs["scope"] != "story" or background) and not inputs.get("dryRun"):
        checked = run_page_refresh(name, {**inputs, "dryRun": True}, service)   # the guard first: nothing is scheduled that would be refused or is only a preview
        guard = (checked.get("invalidation") or {}).get("guard") or {}
        if checked.get("error") or not checked.get("ok"):
            return checked
        if guard.get("refusal"):
            return {**checked, "ok": False, "dryRun": False, "error": guard["refusal"]}
        if not inputs.get("confirm") and checked["invalidation"]["count"] > DRY_RUN_ABOVE:
            return {**checked, "needsRun": True, "hint": "This was a dry run: more than 5 paths need a second, explicit call. Repeat the same request with --run (confirm: true) to do it."}
        task = {"task": PAGE_REFRESH_RERENDER_TASK, "scope": inputs["scope"], "invalidate": inputs.get("invalidate", True), "forcePaths": inputs.get("forcePaths"), "who": who}
        if inputs.get("storyLineageId"):
            task["storyLineageId"] = inputs["storyLineageId"]
        if inputs.get("under"):
            task["under"] = list(inputs["under"])
        jobs = publish_jobs_from_environment()
        job_fields: dict = {}
        if jobs is not None:
            key = rerender_job_key(inputs)
            job, joined = jobs.request(key, None, queue=False)
            job_fields = {"jobKey": key, "job": {**job_answer(job), "joined": joined}}
            task.update({"jobKey": key, "jobId": job["jobId"]})
        if not (job_fields.get("job", {}).get("joined") or schedule_projection_task(task, "page refresh")):
            if jobs is not None:
                jobs.finish(task["jobKey"], task["jobId"], ok=False, outcome={"error": "the re-render could not be scheduled"})
            return {"ok": False, "operation": name, "error": {"code": "not_scheduled", "message": "The re-render could not be scheduled; nothing was written."}}
        return {
            "ok": True, "operation": name, "dryRun": False, "target": {"scope": inputs["scope"], **({"storyLineageId": inputs["storyLineageId"]} if inputs.get("storyLineageId") else {})}, "scheduled": True, **job_fields,
            "rendered": {"ok": None, "scheduled": True, "requested": (checked.get("rendered") or {}).get("count", 0), "errors": []},
            "invalidation": {"ok": True, "status": "scheduled" if inputs.get("invalidate", True) is not False else "not-requested", "paths": checked["invalidation"]["paths"], "count": checked["invalidation"]["count"], "requests": [], "cost": checked["invalidation"]["cost"]},
        }
    return run_page_refresh(name, inputs, service)


def ensure_default_editorial_policies(client) -> None:
    """A deployed site starts with working editorial policies. Never fails the deploy: a problem is logged."""
    try:
        result = ensure_default_policies(GraphQLEditorialStore(execute=client.graphql))
        print(json.dumps({"defaultEditorialPolicies": result}))
    except Exception as error:
        print(json.dumps({"defaultEditorialPoliciesError": str(error)[:500]}))


def run_deploy_render_task(client) -> dict:
    """Render every published page after a backend deploy, then report drift (a dry run: nothing is deleted)."""
    ensure_publication_from_environment(client)
    context = projection_context(client)
    # Before anything reads a language (the render, the editorial policies' checks): rows written before the fields get them, once per site.
    print(json.dumps(ensure_item_languages(client, context.writer, now=utc_now_iso, echo=lambda line: None)))
    ensure_default_editorial_policies(client)
    if targeted_invalidation(os.environ):
        context.invalidate = None  # the default, "targeted": a deploy never purges; pages age out with the HTML lifetime (PPY-2745c1)
    report = deploy_render(context)
    after_release(publish_jobs_from_environment())   # publishes that arrived during the render were queued; build them now
    print(drift_metric_line(report))
    if report.render.unpurged:
        schedule_unpurged_invalidation(report.render.unpurged)
    if not report.ok:
        raise ProjectionTaskFailed("; ".join([*report.render.errors, *report.drift.errors]))
    return report.to_dict()


def run_home_page_snapshot_task(client, task: dict | None = None) -> dict:
    """Bring the site's public Reference file up to date. A site whose projection.json has no ``homePage`` setting ignores the task.

    The stream trigger schedules it as ``incremental``: only the Reference rows it recorded as changed are read again, so the cost of a change does not
    grow with the corpus (``papyrus_content/home_page/incremental.py``). Any other run reads the whole corpus and leaves the private state for the next one.
    """
    context = projection_context(client)
    state_store, dirty_store, batch = home_page_stores_for(task or {})
    report = run_home_page_snapshot(
        context,
        client,
        home_page_settings_of(context.projector),
        client_factory=lambda: create_authoring_client()[0],
        workers=HOME_PAGE_SNAPSHOT_WORKERS,
        state_store=state_store,
        dirty=batch,
    )
    if report.get("errors"):
        raise ProjectionTaskFailed("; ".join(report["errors"]))
    if dirty_store is not None and batch is not None:
        dirty_store.acknowledge(batch)  # only after the run succeeded: a failed run is read again from the same list
    return {"ok": True, **report}


def run_projection_task(task: dict, lambda_context=None) -> dict:
    """An asynchronous projection task. Raising makes Lambda retry it, then send the event to the dead letter queue."""
    try:
        return _run_projection_task(task, lambda_context)
    except ProjectionLeaseHeld as held:  # another projection of this publication outlasted the wait: retry later
        raise ProjectionTaskFailed(str(held)) from held


def _deadline_of(lambda_context) -> float:
    """The time (``time.monotonic``) by which draining must stop, from the invocation's remaining time; an hour when there is none (a test)."""
    import time

    remaining = getattr(lambda_context, "get_remaining_time_in_millis", None)
    seconds = remaining() / 1000.0 if callable(remaining) else 3600.0
    return time.monotonic() + seconds - DRAIN_RESERVE_SECONDS


def build_item_job(client, context, jobs, item_id: str, job_id: str | None, *, unpublished: bool = False, published: dict | None = None):
    """Build one item's pages under the lease the caller holds, with its job record kept up to date. Returns the report."""
    request_meter.add_units(1)   # the build budget grows with the Stories built in this invocation, never with the size of the site
    if jobs is not None:
        jobs.take(item_id)
        job_id = jobs.start(item_id, job_id)
        published = published or jobs.announcement(item_id)
    try:
        report = project(context, item_id, unpublished=unpublished)
    except Exception as error:
        if jobs is not None and job_id:
            jobs.finish(item_id, job_id, ok=False, outcome={"error": f"{type(error).__name__}: {error}"[:1000]})
        raise
    if report.unpurged:
        schedule_unpurged_invalidation(report.unpurged)
    if report.follow_up_item_pages:
        schedule_item_pages(item_id)
    if jobs is not None and job_id:
        outcome = {"paths": [*report.written, *report.deleted], "itemPaths": list(report.item_paths), "unchanged": len(report.unchanged), "invalidation": invalidation_outcome(context, report)}
        url = public_item_url(os.environ, report.item_paths)
        if url:
            outcome["url"] = url
        if not report.ok:
            outcome["error"] = "; ".join(report.errors)
        jobs.finish(item_id, job_id, ok=report.ok, outcome=outcome)
    if report.ok and not unpublished and isinstance(published, dict):
        # A real publish (the CLI marks it, as does the newsroom's retry): the page is live, so tell the newsletter.
        announce_published(item_id, published.get("publishedItemId"))
    return report


def build_item_pages_job(client, context, jobs, job_id: str | None, except_item_id: str | None):
    request_meter.add_units(1)
    if jobs is not None:
        jobs.take(ITEM_PAGES_JOB)
        job_id = jobs.start(ITEM_PAGES_JOB, job_id)
    try:
        report = project_item_pages(context, except_item_id=except_item_id)
    except Exception as error:
        if jobs is not None:
            jobs.finish(ITEM_PAGES_JOB, job_id, ok=False, outcome={"error": f"{type(error).__name__}: {error}"[:1000]})
        raise
    if jobs is not None:
        jobs.finish(ITEM_PAGES_JOB, job_id, ok=report.ok, outcome={"written": len(report.written), **({"error": "; ".join(report.errors)} if not report.ok else {})})
    return report


def drain_queue(client, context, jobs, deadline: float, *, done: set[str]) -> list[str]:
    """While this invocation holds the lease, build what is queued (publishes that found the site busy), until the deadline. Returns what it built."""
    import time

    if jobs is None:
        return []
    built: list[str] = []
    while time.monotonic() < deadline:
        waiting = sorted(jobs.queued_items() - done)
        if not waiting:
            break
        item_id = waiting[0]
        done.add(item_id)
        fresh = projection_context(client)
        fresh.lease = context.lease   # the hold this invocation already has (nested holds share it)
        try:
            if item_id == ITEM_PAGES_JOB:
                build_item_pages_job(client, bulk_projection_context_from(fresh), jobs, None, None)
            else:
                build_item_job(client, fresh, jobs, item_id, None)
            built.append(item_id)
        except ProjectionLeaseHeld:
            raise
        except Exception as error:  # noqa: BLE001 - one story that fails must not stop the others; its job says why, and it is retried
            print(json.dumps({"event": "papyrus_publish_drain_failed", "itemId": item_id, "error": f"{type(error).__name__}: {error}"[:500]}))
            schedule_projection_task({"task": "item", "itemId": item_id}, f"drain: {error}")
    return built


def bulk_projection_context_from(context):
    if targeted_invalidation(os.environ):
        context.invalidate = None
    return context


def after_release(jobs) -> None:
    """Something was queued while this invocation was finishing: hand it to a fresh invocation rather than leave it waiting for a retry."""
    if jobs is None:
        return
    try:
        if jobs.queued_items():
            schedule_projection_task({"task": "drain"}, "queued publishes")
    except Exception as error:  # noqa: BLE001 - the queued builds' own retries still run
        print(json.dumps({"event": "papyrus_publish_drain_not_scheduled", "error": f"{type(error).__name__}: {error}"[:500]}))


def run_queued_build(client, task: dict, lambda_context=None) -> dict:
    """An ``item``, ``item-pages`` or ``drain`` task: take the lease (waiting a few seconds at most), build, build what else is queued, let go.

    A build that finds the site busy leaves its story queued for whoever holds the lease and fails, so Lambda retries it once later; a retry
    whose job a drain already finished does nothing."""
    kind = task.get("task")
    jobs = publish_jobs_from_environment()
    item_id = ITEM_PAGES_JOB if kind == "item-pages" else task.get("itemId")
    job_id = task.get("jobId")
    if jobs is not None and item_id and job_id:
        current = jobs.status(item_id)
        if current is not None and current.get("jobId") == job_id and current.get("state") in (DONE, FAILED):
            return {"ok": current.get("state") == DONE, "alreadyBuilt": True, "jobId": job_id, "state": current.get("state")}
    context = bulk_projection_context(client) if kind == "item-pages" else projection_context(client)
    if jobs is None:
        # No lock table (a local run): no records, no queue; the engine takes the lease itself, as it always did.
        if kind == "item-pages":
            report = build_item_pages_job(client, context, None, None, task.get("exceptItemId"))
        elif kind == "item":
            report = build_item_job(client, context, None, item_id, None, unpublished=bool(task.get("unpublished")), published=task.get(PUBLISHED_TASK_KEY))
        else:
            return {"ok": True, "drained": []}
        if not report.ok:
            raise ProjectionTaskFailed("; ".join(report.errors))
        return {"ok": True, "paths": [*report.written, *report.deleted]}
    shorten_lease_wait(context, QUEUED_LEASE_WAIT_SECONDS)
    deadline = _deadline_of(lambda_context)
    report = None
    built: list[str] = []
    try:
        with context.leased():
            done: set[str] = set()
            if kind == "item-pages":
                report = build_item_pages_job(client, context, jobs, job_id, task.get("exceptItemId"))
                done.add(ITEM_PAGES_JOB)
            elif kind == "item":
                report = build_item_job(client, context, jobs, item_id, job_id, unpublished=bool(task.get("unpublished")), published=task.get(PUBLISHED_TASK_KEY))
                done.add(item_id)
            built = drain_queue(client, context, jobs, deadline, done=done)
    except ProjectionLeaseHeld:
        if jobs is not None and item_id:
            jobs.enqueue(item_id)   # whoever holds the lease builds it before letting go; this task's retry is the backstop
            if job_id:
                jobs.touch(item_id, job_id)
        if kind == "drain":
            return {"ok": True, "busy": True}
        raise
    after_release(jobs)
    if report is None:
        return {"ok": True, "drained": built}
    if not report.ok:
        raise ProjectionTaskFailed("; ".join(report.errors))
    return {"ok": True, "paths": [*report.written, *report.deleted], "drained": built}


def run_page_refresh_rerender_task(client, task: dict) -> dict:
    """A scheduled page re-render, with its job record kept up to date: running when it starts, done or failed (with the outcome) when it ends."""
    jobs = publish_jobs_from_environment()
    key, job_id = task.get("jobKey"), task.get("jobId")
    tracked = jobs is not None and bool(key) and bool(job_id)
    if tracked:
        current = jobs.status(key)
        if current is not None and current.get("jobId") == job_id and current.get("state") == DONE:
            return {"ok": True, "alreadyBuilt": True, "jobId": job_id}
        jobs.start(key, job_id)
    try:
        result = refresh_service(client, task.get("who") or "scheduled").rerender(task["scope"], lineage=task.get("storyLineageId"), invalidate=task.get("invalidate", True) is not False, confirm=True, force_paths=task.get("forcePaths"), under=task.get("under"))
    except Exception as error:
        if tracked:
            jobs.finish(key, job_id, ok=False, outcome={"error": f"{type(error).__name__}: {error}"[:1000]})
        raise
    if tracked:
        jobs.finish(key, job_id, ok=bool(result["ok"]), outcome=rerender_job_outcome(result))
    if not result["ok"]:
        raise ProjectionTaskFailed(json.dumps({"rendered": result.get("rendered"), "invalidation": {field: result["invalidation"].get(field) for field in ("status", "error")}}))
    return result


def _run_projection_task(task: dict, lambda_context=None) -> dict:
    client, _claims = create_authoring_client()
    if task.get("task") in ("item", "item-pages", "drain"):
        return run_queued_build(client, task, lambda_context)
    if task.get("task") == "all":
        report = project_all(bulk_projection_context(client))
        after_release(publish_jobs_from_environment())
    elif task.get("task") == "deploy-render":
        wait_for_live_schema(client)   # the deploy that adds attributes updates the schema and this code together; the schema can lag
        return run_deploy_render_task(client)
    elif task.get("task") == READER_SNAPSHOT_TASK:
        return run_reader_snapshot(projection_context(client), client, poll_retirements=task.get("retirementPoll") is True).to_dict()
    elif task.get("task") == HOME_PAGE_SNAPSHOT_TASK:
        return run_home_page_snapshot_task(client, task)
    elif task.get("task") == STORY_STARS_TASK:
        result = run_story_stars_task(projection_context(client), client, task)
        if result.get("errors"):
            raise ProjectionTaskFailed("; ".join(result["errors"]))
        return result
    elif task.get("task") == PAGE_REFRESH_RERENDER_TASK:
        return run_page_refresh_rerender_task(client, task)
    elif task.get("task") == PUBLISH_SCHEDULED_TASK:
        return publish_scheduled_action(client, task)
    elif task.get("task") == "invalidate":
        invalidate = projection_context(client).invalidate
        if invalidate is None:
            return {"ok": True, "paths": []}
        return {"ok": True, "paths": invalidate(list(task["keys"]))}
    else:
        raise ProjectionTaskFailed(f"Unknown projection task {task.get('task')!r}")
    if report.unpurged:
        schedule_unpurged_invalidation(report.unpurged)
    if not report.ok:
        raise ProjectionTaskFailed("; ".join(report.errors))
    return {"ok": True, "paths": [*report.written, *report.deleted]}


def sync_story_checklist(client, record: dict) -> None:
    """Brings a Story's checklist up to date after a console save (best effort: the save stands whatever happens here)."""
    from papyrus_content.content_item_lifecycle import is_story_item_type
    from papyrus_content.story_checklist import sync_quietly

    if is_story_item_type(record.get("type")):
        sync_quietly(client, record.get("lineageId") or record["id"])


def set_story_step_action(arguments: dict, event: dict) -> dict:
    """Marks one step of a Story's checklist done, skipped, not applicable or open again, as the signed-in person.
    ``agent`` names an agent acting through that person's session: the change is recorded as the agent's, on that person's behalf, and an agent cannot reopen a step."""
    from papyrus_content.story_checklist import ACTOR_AGENT, ACTOR_PERSON, ChecklistError, add_note, set_step

    person = person_from_event(event)
    if not person:
        return {"ok": False, "errors": [{"code": "not-signed-in", "message": "Sign in as an editor to change a checklist step.", "line": None}]}
    agent = (arguments.get("agent") or "").strip()
    label = agent or (arguments.get("actorLabel") or "").strip() or (event.get("identity") or {}).get("username") or "editor"
    client, _claims = create_authoring_client()
    actor = {"kind": ACTOR_AGENT if agent else ACTOR_PERSON, "label": label, "sub": person}
    try:
        if not arguments.get("state"):   # no state: a note on the step, whatever its state, changing nothing else
            row = add_note(client, arguments["lineageId"], arguments["stepKey"], arguments.get("note") or "", actor=actor)
        else:
            row = set_step(
                client, arguments["lineageId"], arguments["stepKey"], arguments["state"], actor=actor,
                reason=arguments.get("reason"), note=arguments.get("note"), evidence=arguments.get("evidence"),
            )
    except ChecklistError as error:
        return {"ok": False, "errors": [{"code": "checklist-rejected", "message": str(error), "line": None}]}
    return {"ok": True, "step": {"stepKey": row["stepKey"], "state": row["state"], "changedAt": row.get("changedAt")}}


def save_item_draft_action(arguments: dict, actor: str, approved_by: str | None = None) -> dict:
    client, _claims = create_authoring_client()
    if arguments.get("newVersion") and arguments.get("id"):
        existing = client.get_record("Item", arguments["id"])
        if existing is None:
            raise PublishError("not-found", "That story was not found.")
        try:
            record = save_story_version(
                client,
                existing.get("lineageId") or existing["id"],
                front_matter_yaml=arguments.get("frontMatterYaml"),
                body_markus=arguments.get("bodyMarkus") or "",
                actor=actor,
                change_reason=arguments.get("changeReason") or "edited in the newsroom",
                item_type=arguments.get("type") or None,
            )
        except ValueError as error:
            raise PublishError("story-not-saved", str(error)) from error
        sync_story_checklist(client, record)
        return {
            "ok": True,
            "item": {
                "id": record["id"],
                "contentHash": record["contentHash"],
                "status": record["status"],
                "slug": record["slug"],
                "versionNumber": record.get("versionNumber"),
            },
        }
    if arguments.get("id"):
        live = client.get_record("Item", arguments["id"])
        if live is not None and live.get("status") == "published" and live.get("type") != arguments["type"]:
            # Saving in place republishes the page at once, which would move its address under readers without anyone choosing it.
            raise PublishError(
                "type-locked",
                f"This story is live as the type {live.get('type')}. Save it as a new version to change its type: the live address moves only when that version is published.",
            )
    if arguments.get("id"):
        live = client.get_record("Item", arguments["id"])
        if live is not None and live.get("status") == "published":
            # Saving a published item in place republishes it as it is saved, so its page is checked before anything is written.
            render_body_preflight(arguments.get("frontMatterYaml"), arguments.get("bodyMarkus") or "")
    fields = ItemFields(
        type=arguments["type"],
        slug=arguments["slug"],
        section=arguments.get("section"),
        front_matter_yaml=arguments.get("frontMatterYaml"),
        body_markus=arguments.get("bodyMarkus") or "",
        aliases=list(arguments.get("aliases") or []),
        id=arguments.get("id"),
    )
    record = save_item(client, fields, actor=actor, expected_content_hash=arguments.get("expectedContentHash"))
    sync_story_checklist(client, record)   # a Story the editor creates here gets its checklist; one they change catches up with the template
    response = {
        "ok": True,
        "item": {
            "id": record["id"],
            "contentHash": record["contentHash"],
            "status": record["status"],
            "slug": record["slug"],
            "versionNumber": record.get("versionNumber"),
        },
    }
    if record["status"] == "published" and projection_configured():
        published = publish_item(client, record["id"], actor=actor, approved_by=approved_by)
        response["item"]["versionNumber"] = published.version_number
        response.update(project_item_action(client, record["id"], unpublished=False))
    return response


def site_triggers_for(client, item_id: str) -> dict:
    triggers: dict = {}
    reader_app_id, reader_branch = reader_target_from_environment()
    revalidate_base_url = (os.environ.get("PAPYRUS_REVALIDATE_BASE_URL") or "").strip()
    if revalidate_base_url:
        try:
            item = client.get_record("Item", item_id) or {}
            slugs = [item["slug"]] if item.get("slug") else []
            revalidated = trigger_pretext_revalidation(slugs, None, base_url=revalidate_base_url)
            triggers["revalidated"] = revalidated if revalidated is not None else {"ok": False, "reason": "not-configured"}
            distribution_ids = distribution_ids_from_environment(os.environ)
            if distribution_ids and revalidated is not None:
                triggers["edgeInvalidated"] = invalidate_revalidated_paths(distribution_ids, revalidated)
        except Exception as error:  # noqa: BLE001 - a trigger failure never fails the publish
            triggers["revalidated"] = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    if reader_app_id:
        triggers["rebuild"] = trigger_rebuild(reader_app_id=reader_app_id, reader_branch=reader_branch)
    return triggers


def job_answer(job: dict | None) -> dict:
    """What a caller is told about a build: its job id and state, and once it ended, its outcome (pages, the page's URL, the edge purge, an error)."""
    if not job:
        return {"state": "unknown"}
    found = {key: job[key] for key in ("jobId", "state", "version", "requestedAt", "startedAt", "finishedAt", "stale") if key in job}
    found.update(job.get("outcome") or {})
    return found


def projection_status_action(arguments: dict) -> dict:
    """``publishItem`` with ``{"id", "jobStatus": true}``: where the build of this story's pages stands. Reads one record; changes nothing."""
    if not projection_configured():
        return {"ok": True, "projection": {"state": "not-applicable"}}
    jobs = publish_jobs_from_environment()
    if jobs is None:
        return {"ok": True, "projection": {"state": "unknown", "reason": "this site keeps no build records (no projection lock table)"}}
    client, _claims = create_authoring_client()
    candidate = client.get_record("Item", arguments["id"]) or {}
    job = jobs.status(arguments["id"])
    answer = job_answer(job)
    if job is not None and job.get("state") in (QUEUED, RUNNING) and not job.get("stale"):
        answer["queued"] = arguments["id"] in jobs.queued_items() if job.get("state") == QUEUED else False
    return {"ok": True, "itemId": arguments["id"], "lineageId": candidate.get("lineageId"), "projection": answer}


def start_projection_job(client, item_id: str, *, version: int | None, published_item_id: str | None, unpublished: bool = False) -> dict:
    """Start building a story's pages (or, for ``unpublished``, taking them down) in the background, or join the build already queued or running for it.
    Returns what the caller is told. The build decides from the stored state whether the page stays or goes, so a queued unpublish is built by the same drain."""
    context = projection_context(client)
    item_paths: list[str] = []
    row = context.source.published_row(item_id)
    if row is not None:
        from papyrus_content.projection.source import summary_from_row

        item_paths = list(context.projector.item_page_paths(summary_from_row(row)))
    answer: dict = {"projected": None, "scheduled": True, "itemPaths": item_paths, "live": False}
    url = public_item_url(os.environ, item_paths)
    if url:
        answer["url"] = url
    task = {"task": "item", "itemId": item_id, "unpublished": unpublished}
    if published_item_id:
        task[PUBLISHED_TASK_KEY] = {"publishedItemId": published_item_id}
    jobs = publish_jobs_from_environment()
    if jobs is None:
        answer["projection"] = {"state": "scheduled" if schedule_projection_task(task, "publish") else "not-scheduled"}
        return answer
    job, joined = jobs.request(item_id, version, announce={"publishedItemId": published_item_id} if published_item_id else None)
    if not joined:
        if not schedule_projection_task({**task, "jobId": job["jobId"]}, "publish"):
            jobs.finish(item_id, job["jobId"], ok=False, outcome={"error": "the build could not be started"})
            job = jobs.status(item_id)
    answer["projection"] = {**job_answer(job), "joined": joined}
    return answer


def publish_item_action(arguments: dict, actor: str, approved_by: str | None = None) -> dict:
    if arguments.get("jobStatus"):
        return projection_status_action(arguments)
    client, _claims = create_authoring_client()
    candidate = client.get_record("Item", arguments["id"]) or {}
    live = client.get_record("PublishedItem", published_item_id_for(candidate.get("lineageId") or arguments["id"]))
    render_preflight(client, arguments["id"])   # a page the site cannot render is refused before any published data is written
    result = publish_item(client, arguments["id"], actor=actor, approved_by=approved_by)
    response = {
        "ok": True,
        "changed": result.changed,
        "publishedId": result.published_item_id,
        "versionNumber": result.version_number,
        **remove_schedules(client, candidate, int(candidate["versionNumber"]) if candidate.get("versionNumber") else None),   # publishing now ends the schedule
    }
    if result.changed and live is not None and live.get("type") and live.get("type") != candidate.get("type"):
        # The type decides the address (urls.types), so the live page moves; the projection leaves a redirect from the old address.
        response["typeChangedFrom"] = live["type"]
    if result.changed:
        response.update(site_triggers_for(client, arguments["id"]))
    published_item_id = result.published_item_id if result.changed else None
    if arguments.get("async") is True and projection_configured():
        # The CLI asks for this (PPY-3acc8d): the data is saved now and the pages are built in the background; it asks for the job's status.
        response.update(start_projection_job(client, arguments["id"], version=result.version_number, published_item_id=published_item_id))
        return response
    response.update(project_item_action(client, arguments["id"], unpublished=False, published_item_id=published_item_id))
    return response


def remove_schedules(client, item: dict, version_number: int | None) -> dict:
    """A publish or a takedown makes a Story's schedule meaningless: remove the schedules of its versions up to ``version_number`` (all of them when None). The publish
    has already happened, so a failure here is reported and never undoes it; the schedule then finds its version published (or the Story gone) and does nothing."""
    from papyrus_content.content_item_lifecycle import is_story_item_type

    if not is_story_item_type(item.get("type")):
        return {}
    try:
        removed = schedule_service(client).clear_through(str(item.get("lineageId") or item["id"]), version_number)
    except Exception as error:  # noqa: BLE001 - reported to the caller in the answer
        return {"schedule": {"removed": [], "error": f"{type(error).__name__}: {error}"}}
    return {"schedule": {"removed": removed}} if removed else {}


def unpublish_item_action(arguments: dict, actor: str) -> dict:
    client, _claims = create_authoring_client()
    candidate = client.get_record("Item", arguments["id"]) or {}
    result = unpublish_item(client, arguments["id"], actor=actor)
    response = {"ok": True, "changed": result.changed}
    if candidate:
        response.update(remove_schedules(client, candidate, None))
    if result.changed:
        response.update(site_triggers_for(client, arguments["id"]))
    if arguments.get("async") is True and projection_configured():
        # As for a publish (PPY-f171b4): rewriting the listings, feeds and redirects can outlast AppSync's 30 seconds, so the data is saved now,
        # the work runs in the background, and the caller asks for the job's status until it ends.
        response.update(start_projection_job(client, arguments["id"], version=None, published_item_id=None, unpublished=True))
        return response
    response.update(project_item_action(client, arguments["id"], unpublished=True))
    return response


def caller_from_event(event: dict) -> Caller:
    identity = event.get("identity") or {}
    groups = identity.get("groups")
    return Caller(actor=actor_from_event(event), person=person_from_event(event), groups=tuple(groups or ()) if identity.get("sub") else None)


def schedule_item_action(arguments: dict, event: dict) -> dict:
    """``scheduleItem`` ``{"operation": "schedule" | "schedule_list", "arguments": {...}}``: the one operation table of scheduled publishing (story_schedule.OPERATIONS)."""
    client, _claims = create_authoring_client()
    try:
        service = schedule_service(client)
    except ScheduleError as error:
        return error.to_response()
    return run_schedule_operation(str(arguments.get("operation") or ""), arguments.get("arguments") or {}, service, caller_from_event(event))


def publish_scheduled_action(client, task: dict) -> dict:
    """The Scheduler's event at the scheduled moment: claim the schedule once, then publish its pinned version by the normal publish path (see story_schedule.py).
    A refusal of the publish (an open checklist, an unrendered page) fails the run so Lambda retries it and then sends it to the dead letter queue; the version stays
    scheduled and is shown as overdue."""
    service = schedule_service(client)

    def publish(row: dict) -> dict:
        by = str(row.get("scheduledBy") or "unknown")
        return publish_item_action({"id": row["id"], "async": True}, f"scheduled by {by}", by)

    try:
        return service.run_scheduled_publish(str(task["itemId"]), str(task["scheduledPublishAt"]), publish)
    except PublishError as error:
        raise ProjectionTaskFailed(f"scheduled publish of {task['itemId']} refused [{error.code}]: {error.message}") from error


def move_story_stage_action(arguments: dict, actor: str) -> dict:
    from papyrus_content.story_reporting import move_story_stage

    client, _claims = create_authoring_client()
    try:
        result = move_story_stage(client, arguments["lineageId"], arguments["stage"], actor=actor, reason=arguments.get("reason"))
    except ValueError as error:
        return {"ok": False, "errors": [{"code": "invalid-stage", "message": str(error), "line": None}]}
    return {"ok": True, **result}


def suggest_reference_links_action(arguments: dict) -> dict:
    """Suggests related References and concepts for one Reference from the site's vector index and files them as suggested links.
    The Reference's stored summary vector is the query, so no embedding is computed and no OpenAI key is needed."""
    from papyrus_knowledge_query.services import S3VectorsProvider

    from papyrus_content.reference_suggestions import suggest_for

    reference_id = str(arguments.get("referenceId") or "").strip()
    if not reference_id:
        raise PublishError("invalid-input", "referenceId is required.")
    index_arn = (os.environ.get("PAPYRUS_S3_VECTOR_INDEX_ARN") or "").strip()
    if not index_arn:
        return {"ok": False, "errors": [{"code": "knowledge-index-not-configured", "message": "Suggestions need the knowledge index.", "line": None}]}
    client, _claims = create_authoring_client()
    provider = S3VectorsProvider(vector_index_arn=index_arn, region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))
    try:
        return {"ok": True, **suggest_for(client, provider, reference_id)}
    except ValueError as error:
        return {"ok": False, "errors": [{"code": "suggestion-rejected", "message": str(error), "line": None}]}


def request_staging_build_action() -> dict:
    cms_app_id = (os.environ.get("PAPYRUS_CMS_AMPLIFY_APP_ID") or "").strip()
    if not cms_app_id:
        return {"ok": False, "errors": [{"code": "staging-build-not-configured", "message": "This site has no staging build configured.", "line": None}]}
    staging_branch = (os.environ.get("PAPYRUS_STAGING_BRANCH") or "").strip() or DEFAULT_STAGING_BRANCH
    build = trigger_staging_build(cms_app_id=cms_app_id, staging_branch=staging_branch)
    return {"ok": True, "build": build}


def add_story_agent_note_action(arguments: dict, person: str | None) -> dict:
    """An AI agent's note on a Story, saved as a ModelAttachment owned by the Story (``story_agent_notes``), never as a Message.
    The backend stamps who ran the agent from the signed-in identity; the agent's name is only a label. Callers are editors and admins (the schema's groups)."""
    from papyrus_content.story_agent_notes import save_agent_note

    if not person:
        return {"ok": False, "errors": [{"code": "not-signed-in", "message": "Sign in as an editor to add an agent note.", "line": None}]}
    client, _claims = create_authoring_client()
    try:
        version = arguments.get("versionNumber")
        result = save_agent_note(
            client, arguments["lineageId"], agent=arguments.get("agent"), body=arguments.get("body"), summary=arguments.get("summary") or None,
            reference_lineage_id=arguments.get("referenceLineageId") or None, version_number=int(version) if version not in (None, "") else None,
            by_sub=person, by_kind="user",
        )
    except (KeyError, ValueError) as error:
        return {"ok": False, "errors": [{"code": "agent-note-rejected", "message": str(error), "line": None}]}
    return {"ok": True, **result}


def create_story_from_reference_action(arguments: dict, actor: str) -> dict:
    """One tap in the newsroom: a draft story started from a Reference (``story_from_reference.create_story_from_reference``). Never changes the Reference's status."""
    from papyrus_content.ideas.signal_queue import ReferenceSummaries
    from papyrus_content.story_from_reference import create_story_from_reference

    client, _claims = create_authoring_client()
    summaries = ReferenceSummaries(client)
    try:
        result = create_story_from_reference(
            client, arguments["referenceId"], actor=actor, item_type=arguments.get("itemType") or None, again=bool(arguments.get("again")), summary_of=summaries.read,
        )
    except ValueError as error:
        return {"ok": False, "errors": [{"code": "story-not-created", "message": str(error), "line": None}]}
    return {"ok": True, **result}


SWEEP_TASKS = frozenset({"all", "deploy-render", PAGE_REFRESH_RERENDER_TASK})   # whole-site renders: their reads are a named sweep, never over budget


def metered_caller(event: dict) -> tuple[str, bool]:
    """The request meter's name for one invocation (``lambda:content-actions:<field or task>``), and whether it is a whole-site sweep."""
    if PROJECTION_TASK_KEY in event:
        name = str((event.get(PROJECTION_TASK_KEY) or {}).get("task") or "task")
        return f"lambda:content-actions:{name}", name in SWEEP_TASKS
    if "refreshSitePages" in event:
        return "lambda:content-actions:refreshSitePages", False
    return f"lambda:content-actions:{event.get('fieldName') or 'unknown'}", False


def handler(event, context=None):
    """One metered run per invocation: its AppSync requests are counted and summarised in one ``papyrus_request_summary`` log line (docs/request-meter.md)."""
    global INVOKED_FUNCTION_ARN
    INVOKED_FUNCTION_ARN = getattr(context, "invoked_function_arn", None)
    caller, sweep = metered_caller(event)
    with request_meter.run(caller, emit="log", sweep=sweep):
        return _handle(event, context)


def _handle(event, context=None):
    if PROJECTION_TASK_KEY in event:
        return run_projection_task(event[PROJECTION_TASK_KEY], context)
    if "refreshSitePages" in event:   # a direct invocation by an operator's profile: the operator lane needs no CloudFront rights of its own
        return refresh_site_pages_action(event["refreshSitePages"], str(event.get("who") or "operator"))
    field = event["fieldName"]
    arguments = parse_input(event["arguments"]["input"])
    actor = actor_from_event(event)
    try:
        if field == "intakePendingReferences":
            client, _claims = create_authoring_client()
            try:
                created = intake_references(client, arguments, event.get("identity") or {})
                from papyrus_content.reference_prediction_queue import queue_after_intake
                return {**created, "prediction": queue_after_intake(created, arguments)}   # one Cyclotron prediction per new Reference, requested once, here
            except IntakeError as error:
                return {"ok": False, "errors": [{"code": "intake-rejected", "message": str(error)}]}
        if field == "intakeEmailSubmissionReferences":
            client, _claims = create_authoring_client()
            try:
                from papyrus_content.monitoring_view import default_email_store_factory
                receipt_store = default_email_store_factory(os.environ)()
                return intake_email_submission_references(
                    client, arguments, event.get("identity") or {}, receipt_store=receipt_store)
            except IntakeError as error:
                return {"ok": False, "errors": [{"code": "intake-rejected", "message": str(error)}]}
        if field == "correctReferenceCapture":
            from papyrus_content.reference_curation_store import CurationError, correct_reference_capture

            client, _claims = create_authoring_client()
            try:
                return correct_reference_capture(client, arguments, event.get("identity") or {})
            except CurationError as error:
                return {"ok": False, "errors": [{"code": "correction-rejected", "message": str(error)}]}
        if field == "deriveMarkus":
            return derive_markus_action(arguments)
        if field == "saveItemDraft":
            return save_item_draft_action(arguments, actor, person_from_event(event))
        if field == "publishItem":
            return publish_item_action(arguments, actor, person_from_event(event))
        if field == "createStoryFromReference":
            return create_story_from_reference_action(arguments, actor)
        if field == "moveStoryStage":
            return move_story_stage_action(arguments, actor)
        if field == "setStoryStep":
            return set_story_step_action(arguments, event)
        if field == "addStoryAgentNote":
            return add_story_agent_note_action(arguments, person_from_event(event))
        if field == "unpublishItem":
            return unpublish_item_action(arguments, actor)
        if field == "scheduleItem":
            return schedule_item_action(arguments, event)
        if field == "suggestReferenceLinks":
            return suggest_reference_links_action(arguments)
        if field == "refreshSitePages":
            return refresh_site_pages_action(arguments, actor)
        if field == "requestStagingBuild":
            return request_staging_build_action()
    except PublishError as error:
        return failure_response(error)
    raise ValueError(f"Unsupported field {field}")
