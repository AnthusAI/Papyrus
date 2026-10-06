"""Shared AppSync GraphQL HTTP client for CLI tools and newsroom helpers."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .env import (
    decode_jwt_claims,
    graphql_endpoint,
    graphql_jwt,
    graphql_timeout_seconds,
    is_jwt_expired,
    lambda_auth_header,
    load_dotenv,
    normalize_jwt,
)


def running_in_aws_lambda() -> bool:
    return bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def graphql_use_iam() -> bool:
    if os.environ.get("PAPYRUS_GRAPHQL_JWT", "").strip():
        return False
    if running_in_aws_lambda():
        return True
    return os.environ.get("PAPYRUS_GRAPHQL_USE_IAM", "").strip().lower() in {"1", "true", "yes"}


def resolve_graphql_jwt(*, allow_knowledge_fallback: bool = False) -> str:
    if os.environ.get("PAPYRUS_GRAPHQL_JWT", "").strip():
        return graphql_jwt()
    if allow_knowledge_fallback:
        token = normalize_jwt(os.environ.get("PAPYRUS_KNOWLEDGE_QUERY_JWT", ""))
        if token:
            if is_jwt_expired(decode_jwt_claims(token)):
                raise ValueError(
                    "PAPYRUS_KNOWLEDGE_QUERY_JWT is expired. Run: poetry run papyrus auth refresh-jwt --write-env .env"
                )
            return token
    raise ValueError(
        "Missing PAPYRUS_GRAPHQL_JWT. Run: poetry run papyrus auth refresh-jwt --write-env .env"
    )


def graphql_request_headers(
    *,
    endpoint: str,
    body: bytes,
    token: str | None = None,
    allow_knowledge_fallback: bool = False,
) -> dict[str, str]:
    from .guest_auth import refuse_guest_auth

    refuse_guest_auth("this command")
    if graphql_use_iam():
        return iam_signed_graphql_headers(endpoint, body)
    auth_token = token if token is not None else resolve_graphql_jwt(allow_knowledge_fallback=allow_knowledge_fallback)
    return {
        "Content-Type": "application/json",
        "Authorization": lambda_auth_header(auth_token),
        "x-amz-appsync-authtype": os.environ.get("PAPYRUS_GRAPHQL_AUTH_TYPE", "AWS_LAMBDA").strip() or "AWS_LAMBDA",
    }


def execute_graphql(
    query: str,
    variables: dict[str, Any] | None = None,
    *,
    timeout: float | None = None,
    allow_knowledge_fallback: bool = False,
) -> dict[str, Any]:
    load_dotenv()
    endpoint = graphql_endpoint()
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    headers = graphql_request_headers(
        endpoint=endpoint,
        body=payload,
        allow_knowledge_fallback=allow_knowledge_fallback,
    )
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
    try:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.session import Session
    except Exception as exc:  # pragma: no cover - depends on local deps
        raise ValueError(
            "Missing PAPYRUS_GRAPHQL_JWT and botocore is unavailable for IAM AppSync signing."
        ) from exc

    parsed = urllib.parse.urlparse(endpoint)
    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or region_from_appsync_host(parsed.netloc)
    )
    session = Session()
    credentials = session.get_credentials()
    if credentials is None:
        raise ValueError(
            "Missing PAPYRUS_GRAPHQL_JWT and AWS credentials are unavailable for IAM AppSync signing."
        )
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
