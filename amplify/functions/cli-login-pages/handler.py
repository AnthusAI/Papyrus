"""The `/cli/*` approval pages of `papyrus login --remote`, served by the cli-login library's own `ApprovalPages`.

The site's Next.js app forwards `/cli/approve` and `/cli/callback` here by IAM invoke. This function runs the
library's pages unchanged: it only turns the forwarded request into the pages' arguments and the pages' answer
back into a response, and calls the site's broker with IAM. It imports nothing from papyrus_content, and its
bundle is built from the same pinned cli-login release as the CLI and the broker (see amplify/cli-login/bundle.ts).

Request (from the forwarder): {"method", "path", "query": {name: value}, "headers": {lowercase name: value}, "body": str}
Response: {"status", "headers": [[name, value], ...] (a name may repeat, e.g. Set-Cookie), "body"}
"""
from __future__ import annotations

import json
import os
from http.cookies import SimpleCookie
from urllib.parse import parse_qsl

from cli_login.broker.pages import ApprovalPages

MAXIMUM_BODY_BYTES = 64 * 1024
UNAVAILABLE = {"ok": False, "error": "unavailable"}


def broker_invoker(function_arn: str, client=None):
    """Call the broker's private operations with IAM; any failure is the broker's own `unavailable` answer."""
    def invoke(payload: dict) -> dict:
        try:
            nonlocal client
            if client is None:
                import boto3

                client = boto3.client("lambda")
            response = client.invoke(FunctionName=function_arn, InvocationType="RequestResponse", Payload=json.dumps(payload).encode())
            if response.get("FunctionError"):
                return dict(UNAVAILABLE)
            answer = json.loads(response["Payload"].read())
            return answer if isinstance(answer, dict) else dict(UNAVAILABLE)
        except Exception:  # noqa: BLE001 - the pages say only that the link is no longer valid
            return dict(UNAVAILABLE)

    return invoke


def pages_from_environment(environment=os.environ, client=None) -> ApprovalPages:
    return ApprovalPages(
        broker_invoker(environment["BROKER_FUNCTION_ARN"], client),
        authorize_endpoint=environment["AUTHORIZE_ENDPOINT"],
        product=environment["PRODUCT"],
        privileges=environment["PRIVILEGES"],
        identity_provider=environment.get("IDENTITY_PROVIDER") or None,
    )


def _cookies(header: str) -> dict[str, str]:
    jar = SimpleCookie()
    try:
        jar.load(header or "")
    except Exception:  # noqa: BLE001 - an unreadable cookie header is no cookies
        return {}
    return {name: morsel.value for name, morsel in jar.items()}


def respond(pages: ApprovalPages, request: dict) -> dict:
    method, path = str(request.get("method", "")).upper(), request.get("path", "")
    headers = {str(k).lower(): str(v) for k, v in (request.get("headers") or {}).items()}
    query = {str(k): str(v) for k, v in (request.get("query") or {}).items()}
    body = request.get("body") or ""
    if len(body.encode()) > MAXIMUM_BODY_BYTES:
        return {"status": 413, "headers": [["Cache-Control", "no-store"]], "body": "Request too large."}
    if path == "/cli/approve":
        form = dict(parse_qsl(body, keep_blank_values=True)) if method == "POST" else {}
        page = pages.approve(method, query, form, _cookies(headers.get("cookie", "")))
    elif path == "/cli/callback" and method == "GET":
        page = pages.callback(query, _cookies(headers.get("cookie", "")))
    else:
        return {"status": 404, "headers": [["Cache-Control", "no-store"]], "body": "Not found."}
    return {"status": page.status, "headers": [[name, value] for name, value in page.headers], "body": page.body}


_pages = None


def handler(event, context):  # pragma: no cover - wiring only; respond() is specified directly
    global _pages
    if _pages is None:
        _pages = pages_from_environment()
    return respond(_pages, event)
