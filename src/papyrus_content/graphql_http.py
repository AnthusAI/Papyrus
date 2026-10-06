"""Shared AppSync GraphQL HTTP client for CLI tools and newsroom helpers.

Every request is signed with SigV4 from the standard AWS credential chain
(environment, shared config and SSO profiles, assumed roles, web identity /
OIDC, container and instance credentials). There is no stored token.
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


def graphql_request_headers(*, endpoint: str, body: bytes) -> dict[str, str]:
    from .guest_auth import refuse_guest_auth

    refuse_guest_auth("this command")
    return iam_signed_graphql_headers(endpoint, body)


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
        raise RuntimeError(f"GraphQL request failed: {error.code} {detail[:500]}") from error
    if parsed.get("errors"):
        messages = "; ".join(str(entry.get("message") or entry) for entry in parsed["errors"])
        raise RuntimeError(f"GraphQL request failed: {messages}")
    return parsed.get("data") or {}


def iam_signed_graphql_headers(endpoint: str, body: bytes) -> dict[str, str]:
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    parsed = urllib.parse.urlparse(endpoint)
    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or region_from_appsync_host(parsed.netloc)
    )
    frozen = _aws_credentials().get_frozen_credentials()
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
