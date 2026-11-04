"""Publish-time projection for the CLI, the same task the newsroom schedules (s3-projection sites only)."""

from __future__ import annotations

import json
import os
from typing import Any

from .publish_alerts import PUBLISHED_TASK_KEY
from .projection.runtime import PUBLICATION_KIND_ENV, S3_PROJECTION_KIND, projection_configured

CONTENT_ACTIONS_FUNCTION_ENV = "PAPYRUS_CONTENT_ACTIONS_FUNCTION"
PROJECT_ALL_COMMAND = "papyrus ops content project --all"
SKIP_LINE = f"projection skipped (--no-trigger); run `{PROJECT_ALL_COMMAND}` later to project the published pages"


def _selected_outputs() -> dict | None:
    """The site's amplify_outputs.json when there is one and it belongs to the site chosen; None otherwise (never another site's file)."""
    from .env import load_amplify_outputs, outputs_belong_to_selection

    try:
        outputs = load_amplify_outputs()
    except (ValueError, OSError):
        return None
    return outputs if outputs_belong_to_selection(outputs) else None


def site_publication() -> dict[str, Any]:
    """The ``custom.publication`` output of the site's amplify_outputs.json (kind and content-actions function), or ``{}``."""
    outputs = _selected_outputs()
    publication = (outputs.get("custom") or {}).get("publication") if outputs else None
    return publication if isinstance(publication, dict) else {}


def projection_unknown() -> bool:
    """True on the signed-in lane when nothing says whether the site projects its pages: no environment override and no
    amplify_outputs.json of the chosen site (the signed-in CLI needs no such file). The newsroom's own publish mutation knows,
    and does nothing for a site that does not project, so the signed-in lane asks it instead of silently skipping the page."""
    from .user_auth_mode import user_auth_requested

    if (os.environ.get(PUBLICATION_KIND_ENV) or "").strip():
        return False
    return user_auth_requested() and _selected_outputs() is None


def projection_requested() -> bool:
    """Whether a publish should ask for the page to be projected: the site is known to project, or this lane cannot tell."""
    return projection_enabled() or projection_unknown()


def projection_enabled() -> bool:
    """The environment (the Lambda, or an operator override) decides first; otherwise the deployed backend's outputs do."""
    if (os.environ.get(PUBLICATION_KIND_ENV) or "").strip():
        return projection_configured()
    return site_publication().get("kind") == S3_PROJECTION_KIND


def content_actions_function() -> str:
    configured = (os.environ.get(CONTENT_ACTIONS_FUNCTION_ENV) or "").strip()
    if configured:
        return configured
    return str(site_publication().get("contentActionsFunction") or "").strip()


def item_task(item_id: str, *, unpublished: bool, published_item_id: str | None = None) -> dict[str, Any]:
    """``published_item_id`` marks a real publish, so the function tells the newsletter once the page is projected."""
    task: dict[str, Any] = {"task": "item", "itemId": item_id, "unpublished": unpublished}
    if published_item_id and not unpublished:
        task[PUBLISHED_TASK_KEY] = {"publishedItemId": published_item_id}
    return task


ALL_TASK: dict[str, Any] = {"task": "all"}


def _invoke_lambda(function_name: str, payload: dict[str, Any]) -> None:
    import boto3

    boto3.client("lambda").invoke(
        FunctionName=function_name, InvocationType="Event", Payload=json.dumps(payload).encode("utf-8")
    )


def _run_locally(task: dict[str, Any]) -> None:
    from .graphql_authoring import create_authoring_client
    from .projection.engine import project, project_all, project_item_pages
    from .projection.runtime import context_from_environment

    client, _claims = create_authoring_client()
    context = context_from_environment(client)
    if task["task"] == "all":
        report = project_all(context)
    else:
        report = project(context, task["itemId"], unpublished=bool(task["unpublished"]))
        if report.ok and report.follow_up_item_pages:
            report = project_item_pages(context, except_item_id=task["itemId"])
    if not report.ok:
        raise RuntimeError("; ".join(report.errors))


def trigger_projection(task: dict[str, Any]) -> dict[str, Any]:
    """Schedule the projection task on the content-actions function, or run it here when no function is configured.

    Never raises: a projection failure must not fail a publish that already succeeded.
    """
    try:
        function_name = content_actions_function()
        if function_name:
            _invoke_lambda(function_name, {"projectionTask": task})
            return {"ok": True, "scheduled": task["task"], "via": function_name}
        _run_locally(task)
        return {"ok": True, "ran": task["task"], "via": "local"}
    except Exception as error:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
            "retry": PROJECT_ALL_COMMAND,
        }


def retry_command(item_id: str, *, unpublished: bool) -> str:
    """The command that repeats an item's publish (or unpublish) and so its projection; it changes nothing that is already done."""
    return f"papyrus ops content {'unpublish' if unpublished else 'publish'} --id {item_id}"


def trigger_projection_as_user(client, task: dict[str, Any]) -> dict[str, Any]:
    """The signed-in lane has no AWS credentials, so it cannot invoke the content-actions function the way the IAM lane does.

    It asks the newsroom's own ``publishItem`` (or ``unpublishItem``) mutation instead, as the console's Publish button does.
    Both are idempotent: the records are already written, so the function finds nothing to change, projects the page and
    returns the outcome (``projected``, ``paths``, ``live``, ``url``, ``error``). A projection it could not finish is retried by the
    function itself too. Never raises.
    """
    mutation = "unpublishItem" if task.get("unpublished") else "publishItem"
    try:
        data = client.graphql(
            f"mutation Project($input: AWSJSON!) {{ {mutation}(input: $input) }}",
            {"input": json.dumps({"id": task["itemId"]})},
        )
        response = data.get(mutation)
        response = json.loads(response) if isinstance(response, str) else (response or {})
        # The function answers ``projected`` only for a site that projects its pages, so this is how the signed-in lane learns which kind it is.
        projects = "projected" in response
        if response.get("ok") is False:
            errors = "; ".join(str(entry.get("message") or entry) for entry in response.get("errors") or [])
            return {"ok": False, "error": errors or f"{mutation} refused the request", "retry": retry_command(task["itemId"], unpublished=bool(task.get("unpublished")))}
        if response.get("projected") is False:
            return {
                "ok": False,
                "error": response.get("error") or "the newsroom could not project the page",
                "projectsPages": True,
                "retry": retry_command(task["itemId"], unpublished=bool(task.get("unpublished"))),
            }
        outcome: dict[str, Any] = {"ok": True, "ran": task["task"], "via": f"{mutation} mutation"}
        if projects:
            outcome["projectsPages"] = True
        if response.get("url"):
            outcome["url"] = response["url"]
        return outcome
    except Exception as error:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
            "retry": retry_command(task["itemId"], unpublished=bool(task.get("unpublished"))),
        }


def skipped_projection() -> dict[str, Any]:
    return {"skipped": True, "command": PROJECT_ALL_COMMAND}
