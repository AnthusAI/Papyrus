from __future__ import annotations

import json
import os
from typing import Any

from papyrus_content.edge_invalidation import distribution_ids_from_environment, invalidate_revalidated_paths
from papyrus_content.graphql_authoring import create_authoring_client
from papyrus_content.markus_renderer.derive import derive_body
from papyrus_content.projection.deploy_render import deploy_render, drift_metric_line
from papyrus_content.projection.engine import project, project_all, project_item_pages
from papyrus_content.projection.runtime import (
    DEAD_LETTER_QUEUE_ENV,
    context_from_environment,
    projection_configured,
    public_item_url,
)
from papyrus_content.rebuild_trigger import (
    DEFAULT_STAGING_BRANCH,
    reader_target_from_environment,
    trigger_pretext_revalidation,
    trigger_rebuild,
    trigger_staging_build,
)
from papyrus_content.story_reporting import save_story_version
from papyrus_content.publishing import (
    ItemFields,
    PublishError,
    publish_item,
    save_item,
    unpublish_item,
)


def parse_input(raw: Any) -> dict:
    parsed = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    if not isinstance(parsed, dict):
        raise PublishError("invalid-input", "The input must be a JSON object.")
    return parsed


def actor_from_event(event: dict) -> str:
    identity = event.get("identity") or {}
    return identity.get("username") or identity.get("sub") or "unknown"


def failure_response(error: PublishError) -> dict:
    if error.errors:
        errors = [body_error.to_dict() for body_error in error.errors]
    else:
        errors = [{"code": error.code, "message": error.message, "line": None}]
    return {"ok": False, "errors": errors}


def derive_markus_action(arguments: dict) -> dict:
    derivation = derive_body(arguments.get("frontMatterYaml"), arguments.get("bodyMarkus") or "")
    if not derivation.ok:
        return {"ok": False, "errors": [body_error.to_dict() for body_error in derivation.errors]}
    response = {
        "ok": True,
        "bodyIrBytes": len(json.dumps(derivation.body_ir, separators=(",", ":")).encode("utf-8")),
        "errors": [],
    }
    if arguments.get("includeIr") is True:
        response["bodyIr"] = derivation.body_ir
    return response


PROJECTION_TASK_KEY = "projectionTask"


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


def project_item_action(client, item_id: str, *, unpublished: bool) -> dict:
    if not projection_configured():
        return {}
    liveness = {} if unpublished else {"live": False}
    task = {"task": "item", "itemId": item_id, "unpublished": unpublished}
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
    if not report.ok:
        message = "; ".join(report.errors)
        schedule_projection_task(task, message)
        response["error"] = message
    if report.unpurged:
        response["edgePurged"] = False
        schedule_unpurged_invalidation(report.unpurged)
    if report.follow_up_item_pages:
        schedule_projection_task({"task": "item-pages", "exceptItemId": item_id}, "follow-up")
    return response


def schedule_unpurged_invalidation(keys: list[str]) -> None:
    schedule_projection_task({"task": "invalidate", "keys": keys}, "edge invalidation failed")


def run_deploy_render_task(client) -> dict:
    """Render every published page after a backend deploy, then report drift (a dry run: nothing is deleted)."""
    context = projection_context(client)
    report = deploy_render(context)
    print(drift_metric_line(report))
    if report.render.unpurged:
        schedule_unpurged_invalidation(report.render.unpurged)
    if not report.ok:
        raise ProjectionTaskFailed("; ".join([*report.render.errors, *report.drift.errors]))
    return report.to_dict()


def run_projection_task(task: dict) -> dict:
    """An asynchronous projection task. Raising makes Lambda retry it, then send the event to the dead letter queue."""
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


def save_item_draft_action(arguments: dict, actor: str) -> dict:
    client, _claims = create_authoring_client()
    if arguments.get("newVersion") and arguments.get("id"):
        existing = client.get_record("Item", arguments["id"])
        if existing is None:
            raise PublishError("not-found", "That story was not found.")
        record = save_story_version(
            client,
            existing.get("lineageId") or existing["id"],
            front_matter_yaml=arguments.get("frontMatterYaml"),
            body_markus=arguments.get("bodyMarkus") or "",
            actor=actor,
            change_reason=arguments.get("changeReason") or "edited in the newsroom",
        )
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
        published = publish_item(client, record["id"], actor=actor)
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


def publish_item_action(arguments: dict, actor: str) -> dict:
    client, _claims = create_authoring_client()
    result = publish_item(client, arguments["id"], actor=actor)
    response = {
        "ok": True,
        "changed": result.changed,
        "publishedId": result.published_item_id,
        "versionNumber": result.version_number,
    }
    if result.changed:
        response.update(site_triggers_for(client, arguments["id"]))
    response.update(project_item_action(client, arguments["id"], unpublished=False))
    return response


def unpublish_item_action(arguments: dict, actor: str) -> dict:
    client, _claims = create_authoring_client()
    result = unpublish_item(client, arguments["id"], actor=actor)
    response = {"ok": True, "changed": result.changed}
    if result.changed:
        response.update(site_triggers_for(client, arguments["id"]))
    response.update(project_item_action(client, arguments["id"], unpublished=True))
    return response


def request_staging_build_action() -> dict:
    cms_app_id = (os.environ.get("PAPYRUS_CMS_AMPLIFY_APP_ID") or "").strip()
    if not cms_app_id:
        return {"ok": False, "errors": [{"code": "staging-build-not-configured", "message": "This site has no staging build configured.", "line": None}]}
    staging_branch = (os.environ.get("PAPYRUS_STAGING_BRANCH") or "").strip() or DEFAULT_STAGING_BRANCH
    build = trigger_staging_build(cms_app_id=cms_app_id, staging_branch=staging_branch)
    return {"ok": True, "build": build}


def handler(event, context):
    if PROJECTION_TASK_KEY in event:
        return run_projection_task(event[PROJECTION_TASK_KEY])
    field = event["fieldName"]
    arguments = parse_input(event["arguments"]["input"])
    actor = actor_from_event(event)
    try:
        if field == "deriveMarkus":
            return derive_markus_action(arguments)
        if field == "saveItemDraft":
            return save_item_draft_action(arguments, actor)
        if field == "publishItem":
            return publish_item_action(arguments, actor)
        if field == "unpublishItem":
            return unpublish_item_action(arguments, actor)
        if field == "requestStagingBuild":
            return request_staging_build_action()
    except PublishError as error:
        return failure_response(error)
    raise ValueError(f"Unsupported field {field}")
