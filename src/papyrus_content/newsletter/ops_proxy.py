"""AppSync entry for the newsroom's newsletter operations.

Amplify custom operations need an Amplify-defined function, and the ``newsletter`` function lives in the plugin stack, so this
thin function (``amplify/plugins/newsletter/ops``) forwards each operation to it. It forwards the verified identity claims it
needs (username, sub, groups, email) and the JSON input unchanged; ``newsletter`` checks the groups again.
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

FIELD_ACTIONS = {
    "newsletterIssues": "issue_list",
    "newsletterIssue": "issue_get",
    "newsletterApproveIssue": "issue_approve",
    "newsletterCancelIssue": "issue_cancel",
    "newsletterStopIssue": "issue_stop",
    "newsletterTestSend": "issue_test_send",
    "newsletterCreateDraft": "issue_create_draft",
    "newsletterPreview": "issue_preview",
    "newsletterOverview": "panel_overview",
    "newsletterSubscribers": "panel_subscribers",
    "newsletterExport": "panel_export",
    "newsletterErase": "panel_erase",
    "newsletterResume": "panel_resume",
    "newsletterIssueDeliveries": "panel_deliveries",
}


def forwarded_identity(identity: Mapping[str, Any] | None) -> dict[str, Any]:
    identity = identity or {}
    claims = identity.get("claims") if isinstance(identity.get("claims"), dict) else {}
    groups = identity.get("groups") if isinstance(identity.get("groups"), list) else claims.get("cognito:groups")
    return {
        "username": identity.get("username"),
        "sub": identity.get("sub"),
        "groups": [group for group in groups if isinstance(group, str)] if isinstance(groups, list) else [],
        "email": claims.get("email") if isinstance(claims.get("email"), str) else None,
    }


def handle(event: Mapping[str, Any], *, client: Any = None, environment: Mapping[str, str] = os.environ) -> Any:
    field = event.get("fieldName") or (event.get("info") or {}).get("fieldName")
    action = FIELD_ACTIONS.get(field) if isinstance(field, str) else None
    if action is None:
        return {"ok": False, "error": "unknown_operation"}
    raw = (event.get("arguments") or {}).get("input")
    payload = {"action": action, "input": raw, "identity": forwarded_identity(event.get("identity"))}
    if client is None:
        import boto3

        client = boto3.client("lambda")
    response = client.invoke(
        FunctionName=environment["NEWSLETTER_FUNCTION_NAME"], InvocationType="RequestResponse", Payload=json.dumps(payload).encode("utf-8")
    )
    result = json.loads(response["Payload"].read() or b"{}")
    if response.get("FunctionError") or not isinstance(result, dict):
        return {"ok": False, "error": "unavailable"}
    body = result.get("body")
    return body if isinstance(body, dict) else {"ok": False, "error": "unavailable"}
