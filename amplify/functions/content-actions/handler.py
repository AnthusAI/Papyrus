from __future__ import annotations

import json
import os
from typing import Any

from papyrus_content.edge_invalidation import distribution_ids_from_environment, invalidate_revalidated_paths
from papyrus_content.graphql_authoring import create_authoring_client
from papyrus_content.markus_renderer.body_features import install_body_features
from papyrus_content.markus_renderer.derive import derive_body
from papyrus_content.projection.deploy_render import deploy_render, drift_metric_line
from papyrus_content.projection.lease import ProjectionLeaseHeld
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
from papyrus_content.publication import ensure_publication_from_environment
from papyrus_content.editorial_checks import GraphQLEditorialStore, ensure_default_policies
from papyrus_content.reference_intake import IntakeError, intake_email_submission_references, intake_references
from papyrus_content.publish_alerts import PUBLISHED_TASK_KEY, announce_published
from papyrus_content.publishing import (
    ItemFields,
    PublishError,
    publish_item,
    published_item_id_for,
    save_item,
    unpublish_item,
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
    return {"ok": False, "errors": errors}


def derive_markus_action(arguments: dict) -> dict:
    derivation = derive_body(arguments.get("frontMatterYaml"), arguments.get("bodyMarkus") or "")
    if not derivation.ok:
        return {"ok": False, "features": site_body_features().to_dict(), "errors": [body_error.to_dict() for body_error in derivation.errors]}
    response = {
        "ok": True,
        "features": site_body_features().to_dict(),
        "bodyIrBytes": len(json.dumps(derivation.body_ir, separators=(",", ":")).encode("utf-8")),
        "errors": [],
    }
    if arguments.get("includeIr") is True:
        response["bodyIr"] = derivation.body_ir
    return response


PROJECTION_TASK_KEY = "projectionTask"
HOME_PAGE_SNAPSHOT_WORKERS = 8


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
    try:
        report = project(projection_context(client), item_id, unpublished=unpublished)
    except Exception as error:  # noqa: BLE001 - a projection failure never fails the save
        message = f"{type(error).__name__}: {error}"
        schedule_projection_task(task, message)
        return {**liveness, "projected": False, "paths": [], "error": message}
    response = {"projected": report.ok, "paths": [*report.written, *report.deleted]}
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
    if report.follow_up_item_pages:
        schedule_projection_task({"task": "item-pages", "exceptItemId": item_id}, "follow-up")
    if report.ok and published_item_id:
        announce_published(item_id, published_item_id)
    return response


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


def refresh_site_pages_action(arguments: dict, who: str = "content-actions") -> dict:
    """An editor's or agent's page refresh (PPY-105508): the operations the CLI and the MCP tools run, here with the function's own AWS rights.

    Purging is quick and runs now. A re-render of every index page or of the whole site can outlast the request, so once it has passed the
    guard it is scheduled as an asynchronous task that re-renders and then purges what it wrote; the answer says so.
    """
    name = str(arguments.get("operation") or "")
    inputs = {key: value for key, value in arguments.items() if key != "operation"}
    if not projection_configured():
        return {"ok": False, "operation": name, "error": {"code": "not_projected", "message": "This site does not project its pages to S3, so there is no edge cache to refresh from here."}}
    operation = PAGE_REFRESH_OPERATIONS.get(name)
    if operation is None:
        return run_page_refresh(name, inputs, refresh_service(None, who))
    try:
        validate_page_refresh(operation, inputs)
    except RefreshError as error:
        return {"ok": False, "operation": name, "error": {"code": error.code, "message": error.message}}
    client, _claims = create_authoring_client()
    service = refresh_service(client, who)
    if name == "site_rerender_pages" and inputs["scope"] != "story" and not inputs.get("dryRun"):
        checked = run_page_refresh(name, {**inputs, "dryRun": True}, service)   # the guard first: nothing is scheduled that would be refused or is only a preview
        guard = (checked.get("invalidation") or {}).get("guard") or {}
        if checked.get("error") or not checked.get("ok"):
            return checked
        if guard.get("refusal"):
            return {**checked, "ok": False, "dryRun": False, "error": guard["refusal"]}
        if not inputs.get("confirm") and checked["invalidation"]["count"] > DRY_RUN_ABOVE:
            return {**checked, "needsRun": True, "hint": "This was a dry run: more than 5 paths need a second, explicit call. Repeat the same request with --run (confirm: true) to do it."}
        task = {"task": PAGE_REFRESH_RERENDER_TASK, "scope": inputs["scope"], "invalidate": inputs.get("invalidate", True), "forcePaths": inputs.get("forcePaths"), "who": who}
        if not schedule_projection_task(task, "page refresh"):
            return {"ok": False, "operation": name, "error": {"code": "not_scheduled", "message": "The re-render could not be scheduled; nothing was written."}}
        return {
            "ok": True, "operation": name, "dryRun": False, "target": {"scope": inputs["scope"]}, "scheduled": True,
            "rendered": {"ok": None, "scheduled": True, "count": 0, "errors": []},
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
    ensure_default_editorial_policies(client)
    context = projection_context(client)
    report = deploy_render(context)
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


def run_projection_task(task: dict) -> dict:
    """An asynchronous projection task. Raising makes Lambda retry it, then send the event to the dead letter queue."""
    try:
        return _run_projection_task(task)
    except ProjectionLeaseHeld as held:  # another projection of this publication outlasted the wait: retry later
        raise ProjectionTaskFailed(str(held)) from held


def _run_projection_task(task: dict) -> dict:
    client, _claims = create_authoring_client()
    if task.get("task") == "item-pages":
        report = project_item_pages(projection_context(client), except_item_id=task.get("exceptItemId"))
    elif task.get("task") == "item":
        report = project(projection_context(client), task["itemId"], unpublished=bool(task.get("unpublished")))
        if report.follow_up_item_pages:
            schedule_projection_task({"task": "item-pages", "exceptItemId": task["itemId"]}, "follow-up")
    elif task.get("task") == "all":
        report = project_all(projection_context(client))
    elif task.get("task") == "deploy-render":
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
        result = refresh_service(client, task.get("who") or "scheduled").rerender(task["scope"], lineage=task.get("storyLineageId"), invalidate=task.get("invalidate", True) is not False, confirm=True, force_paths=task.get("forcePaths"))
        if not result["ok"]:
            raise ProjectionTaskFailed(json.dumps({"rendered": result.get("rendered"), "invalidation": {key: result["invalidation"].get(key) for key in ("status", "error")}}))
        return result
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
    published = task.get(PUBLISHED_TASK_KEY)
    if task.get("task") == "item" and not task.get("unpublished") and isinstance(published, dict):
        # A real publish (the CLI marks it, as does the newsroom's retry): the page is live, so tell the newsletter.
        announce_published(task["itemId"], published.get("publishedItemId"))
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


def publish_item_action(arguments: dict, actor: str, approved_by: str | None = None) -> dict:
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
    }
    if result.changed and live is not None and live.get("type") and live.get("type") != candidate.get("type"):
        # The type decides the address (urls.types), so the live page moves; the projection leaves a redirect from the old address.
        response["typeChangedFrom"] = live["type"]
    if result.changed:
        response.update(site_triggers_for(client, arguments["id"]))
    response.update(
        project_item_action(client, arguments["id"], unpublished=False, published_item_id=result.published_item_id if result.changed else None)
    )
    return response


def unpublish_item_action(arguments: dict, actor: str) -> dict:
    client, _claims = create_authoring_client()
    result = unpublish_item(client, arguments["id"], actor=actor)
    response = {"ok": True, "changed": result.changed}
    if result.changed:
        response.update(site_triggers_for(client, arguments["id"]))
    response.update(project_item_action(client, arguments["id"], unpublished=True))
    return response


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


def handler(event, context):
    if PROJECTION_TASK_KEY in event:
        return run_projection_task(event[PROJECTION_TASK_KEY])
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
        if field == "suggestReferenceLinks":
            return suggest_reference_links_action(arguments)
        if field == "refreshSitePages":
            return refresh_site_pages_action(arguments, actor)
        if field == "requestStagingBuild":
            return request_staging_build_action()
    except PublishError as error:
        return failure_response(error)
    raise ValueError(f"Unsupported field {field}")
