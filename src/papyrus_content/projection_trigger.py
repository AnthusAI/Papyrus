"""Publish-time projection for the CLI, the same task the newsroom schedules (s3-projection sites only)."""

from __future__ import annotations

import json
import os
from typing import Any

from .projection.runtime import PUBLICATION_KIND_ENV, S3_PROJECTION_KIND, projection_configured

CONTENT_ACTIONS_FUNCTION_ENV = "PAPYRUS_CONTENT_ACTIONS_FUNCTION"
PROJECT_ALL_COMMAND = "papyrus ops content project --all"
SKIP_LINE = f"projection skipped (--no-trigger); run `{PROJECT_ALL_COMMAND}` later to project the published pages"


def site_publication() -> dict[str, Any]:
    """The ``custom.publication`` output of the site's amplify_outputs.json (kind and content-actions function), or ``{}``."""
    from .env import load_amplify_outputs

    try:
        publication = (load_amplify_outputs().get("custom") or {}).get("publication")
    except (ValueError, OSError):
        return {}
    return publication if isinstance(publication, dict) else {}


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


def item_task(item_id: str, *, unpublished: bool) -> dict[str, Any]:
    return {"task": "item", "itemId": item_id, "unpublished": unpublished}


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


def skipped_projection() -> dict[str, Any]:
    return {"skipped": True, "command": PROJECT_ALL_COMMAND}
