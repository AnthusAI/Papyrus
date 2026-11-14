"""Shared AppSync GraphQL HTTP client for CLI tools and newsroom helpers.

The signed-in lane (`papyrus login`, Cognito user authorization) is the default.
The operator lane (the standard AWS credential chain, SigV4) is used only when
named (`papyrus --auth iam`, PAPYRUS_GRAPHQL_AUTH=iam). Nothing falls back from
one lane to the other: no lane named and no session is a refusal that says what
to do. Renewable user secrets live only in OS secure storage.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .env import graphql_endpoint, graphql_timeout_seconds, load_dotenv
from .operator_errors import GraphQLRequestError, OperatorError, credential_recovery_guidance

CREDENTIAL_REJECTION_STATUS_CODES = frozenset({401, 403})

_credential_session: Any = None


def _aws_credentials() -> Any:
    global _credential_session
    try:
        from botocore.session import Session
    except Exception as exc:  # pragma: no cover - depends on local deps
        raise ValueError("botocore is unavailable, so AppSync requests cannot be signed with IAM.") from exc
    if _credential_session is None:
        _credential_session = Session()
    credentials = _credential_session.get_credentials()
    if credentials is None:
        raise ValueError(
            "No AWS credentials found for IAM AppSync signing. Set AWS_PROFILE to an SSO or role profile "
            "(for example `aws sso login --profile <profile>`), or run with an OIDC or build role."
        )
    return credentials


def aws_credentials_available() -> bool:
    try:
        _aws_credentials()
    except ValueError:
        return False
    return True


def require_lane_ready() -> None:
    """Raise, with the one thing to do, when the lane this process uses cannot sign a request (before any work starts)."""
    from .user_auth_mode import NOT_SIGNED_IN, iam_requested, signed_in_anywhere
    if iam_requested():
        _aws_credentials()
    elif not signed_in_anywhere():
        raise OperatorError(NOT_SIGNED_IN)


def graphql_request_headers(*, endpoint: str, body: bytes) -> dict[str, str]:
    from .guest_auth import refuse_guest_auth

    refuse_guest_auth("this command")
    from .user_auth_mode import iam_requested
    if iam_requested():
        return iam_signed_graphql_headers(endpoint, body)
    require_lane_ready()
    from .cli_user_auth import selected_headers
    return selected_headers(endpoint)


def execute_graphql(
    query: str,
    variables: dict[str, Any] | None = None,
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    load_dotenv()
    endpoint = graphql_endpoint()
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    headers = graphql_request_headers(endpoint=endpoint, body=payload)
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout or graphql_timeout_seconds()) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        message = f"GraphQL request failed: {error.code} {detail[:500]}"
        if error.code in CREDENTIAL_REJECTION_STATUS_CODES:
            message = f"{message}\n{credential_recovery_guidance()}"
        raise GraphQLRequestError(message, status_code=error.code) from error
    except urllib.error.URLError as error:
        raise GraphQLRequestError(f"GraphQL request failed: cannot reach {endpoint}: {error.reason}") from error
    if parsed.get("errors"):
        messages = "; ".join(str(entry.get("message") or entry) for entry in parsed["errors"])
        raise GraphQLRequestError(f"GraphQL request failed: {messages}")
    return parsed.get("data") or {}


def iam_signed_graphql_headers(endpoint: str, body: bytes, session: Any = None) -> dict[str, str]:
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    parsed = urllib.parse.urlparse(endpoint)
    if session is None:
        region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or region_from_appsync_host(parsed.netloc)
        )
        credentials = _aws_credentials()
    else:
        region = region_from_appsync_host(parsed.netloc)
        credentials = session.get_credentials()
        if credentials is None:
            raise ValueError("The given AWS session has no credentials to sign AppSync requests.")
    frozen = credentials.get_frozen_credentials()
    request = AWSRequest(
        method="POST",
        url=endpoint,
        data=body,
        headers={
            "content-type": "application/json",
            "host": parsed.netloc,
        },
    )
    SigV4Auth(frozen, "appsync", region).add_auth(request)
    return {str(key): str(value) for key, value in request.headers.items()}


def region_from_appsync_host(host: str) -> str:
    match = re.search(r"\.appsync-api\.([a-z0-9-]+)\.amazonaws\.com", host)
    return match.group(1) if match else "us-east-1"
