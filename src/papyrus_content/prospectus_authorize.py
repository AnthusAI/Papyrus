"""Fail-closed Prospectus authorization for the Lambda resolvers (twin of ``lib/prospectus-authorize.ts``).

An account-scoped operation is allowed only when Prospectus says so, for the account the caller named, at the moment of
the call. Pool groups alone are never authorization. The site's function role signs the request (SigV4, service
``execute-api``) and the caller's own access token travels in ``X-Prospectus-Human-Token``.

Any doubt denies: a missing endpoint, token or account, a network failure, a server error, an answer for another account.
Only ``reenrollment_required`` is passed through unchanged, as :class:`ReenrollmentRequired`, so the CLI and console can
tell the person to sign in again. The module imports nothing outside the standard library and botocore, because Lambda
bundles ship ``papyrus_content`` without the CLI login code.

The AppSync JavaScript resolvers do the same job in ``amplify/data/resolvers/prospectus-authorize.js``.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

ACCOUNT_HEADER = "x-prospectus-account"
HUMAN_TOKEN_HEADER = "x-prospectus-human-token"
ENABLE_ENVIRONMENT_VARIABLE = "PAPYRUS_PROSPECTUS_AUTHORIZE"
ENDPOINT_ENVIRONMENT_VARIABLE = "PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT"
REQUEST_TIMEOUT_SECONDS = 5.0

CONSOLE_READ = "console:read"
CONSOLE_WRITE = "console:write"
MEMBERS_READ = "members:read"

READ_FIELD_PREFIXES = ("list", "get", "search", "count", "describe")
MEMBERS_READ_FIELDS = frozenset({"listAccountMembers", "getAccountMembers"})
ACCOUNT_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")

DENIED_ACCOUNT_INVALID = "account_invalid"
DENIED_TOKEN_MISSING = "human_token_required"
DENIED_UNAVAILABLE = "prospectus_unavailable"
DENIED_ACCOUNT_MISMATCH = "account_mismatch"
DENIED_NOT_ALLOWED = "not_allowed"
DENIED_FORBIDDEN = "forbidden"
DENIED_UNAUTHENTICATED = "unauthenticated"


class AccountRequired(Exception):
    """The request named no account (``X-Prospectus-Account``). The class name is the GraphQL error type."""


class ReenrollmentRequired(Exception):
    """Prospectus no longer recognises this login. The class name is the GraphQL error type the CLI maps."""


class AuthorizationDenied(Exception):
    """Prospectus did not allow the operation, or could not be asked. The class name is the GraphQL error type."""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    account_id: str
    operation: str
    reason: str | None = None
    role: str | None = None


Transport = Callable[[str, dict[str, str], bytes], "tuple[int, Any]"]


def operation_for(field_name: str) -> str:
    """The Prospectus operation a GraphQL field needs: reads are ``console:read``, everything else ``console:write``."""
    if field_name in MEMBERS_READ_FIELDS:
        return MEMBERS_READ
    if field_name.startswith(READ_FIELD_PREFIXES):
        return CONSOLE_READ
    return CONSOLE_WRITE


def authorization_enabled(environment: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environment is None else environment
    return str(source.get(ENABLE_ENVIRONMENT_VARIABLE, "")).strip().lower() in {"1", "true", "yes", "on"}


def _region_for(host: str, environment: Mapping[str, str]) -> str:
    match = re.search(r"\.execute-api\.([a-z0-9-]+)\.amazonaws\.com", host)
    if match:
        return match.group(1)
    return environment.get("AWS_REGION") or environment.get("AWS_DEFAULT_REGION") or "us-east-1"


def _signed_post(url: str, headers: dict[str, str], body: bytes) -> "tuple[int, Any]":
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.session import Session

    credentials = Session().get_credentials()
    if credentials is None:
        raise OSError("no AWS credentials to sign the Prospectus request")
    host = urllib.parse.urlparse(url).netloc
    request = AWSRequest(method="POST", url=url, data=body, headers={**headers, "host": host})
    SigV4Auth(credentials.get_frozen_credentials(), "execute-api", _region_for(host, os.environ)).add_auth(request)
    prepared = urllib.request.Request(url, data=body, headers=dict(request.headers.items()), method="POST")
    try:
        with urllib.request.urlopen(prepared, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, _parsed(response.read())
    except urllib.error.HTTPError as error:
        return error.code, _parsed(error.read())


def _parsed(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _denied(account_id: str, operation: str, reason: str) -> Decision:
    return Decision(allowed=False, account_id=account_id, operation=operation, reason=reason)


def authorize(
    account_id: str,
    operation: str,
    human_token: str | None,
    *,
    endpoint: str | None = None,
    transport: Transport | None = None,
) -> Decision:
    """Ask Prospectus whether the token's person may perform ``operation`` on ``account_id`` right now.

    Call it immediately before each effect: the answer is point-in-time. Raises :class:`ReenrollmentRequired` when
    Prospectus answers ``401`` or ``403`` with ``reenrollment_required``; every other failure is a denied decision.
    """
    if not isinstance(account_id, str) or not ACCOUNT_IDENTIFIER_PATTERN.match(account_id):
        return _denied(str(account_id), operation, DENIED_ACCOUNT_INVALID)
    if not human_token:
        return _denied(account_id, operation, DENIED_TOKEN_MISSING)
    base = (endpoint if endpoint is not None else os.environ.get(ENDPOINT_ENVIRONMENT_VARIABLE, "")).strip()
    if not base.startswith("https://"):
        return _denied(account_id, operation, DENIED_UNAVAILABLE)
    url = f"{base.rstrip('/')}/v1/accounts/{account_id}/authorize"
    body = json.dumps({"operation": operation}).encode("utf-8")
    headers = {"content-type": "application/json", HUMAN_TOKEN_HEADER: human_token}
    try:
        status, answer = (transport or _signed_post)(url, headers, body)
    except (OSError, urllib.error.URLError, ValueError):
        return _denied(account_id, operation, DENIED_UNAVAILABLE)
    answer = answer if isinstance(answer, dict) else {}
    if status in (401, 403) and answer.get("error") == "reenrollment_required":
        raise ReenrollmentRequired("reenrollment_required")
    if status == 200:
        if answer.get("allowed") is not True:
            return _denied(account_id, operation, DENIED_NOT_ALLOWED)
        if answer.get("accountId") != account_id:
            return _denied(account_id, operation, DENIED_ACCOUNT_MISMATCH)
        return Decision(allowed=True, account_id=account_id, operation=operation, role=answer.get("role"))
    if status == 403:
        return _denied(account_id, operation, DENIED_FORBIDDEN)
    if status == 401:
        return _denied(account_id, operation, DENIED_UNAUTHENTICATED)
    return _denied(account_id, operation, DENIED_UNAVAILABLE)


def is_site_function_caller(identity: Mapping[str, Any] | None) -> bool:
    """True for an IAM principal of the function's own account: the backend's own machine calls, not a signed-in person.

    A Cognito identity-pool user is also an IAM principal, but it carries a Cognito identity; a user-pool caller carries
    a subject or claims. Neither is a site function.
    """
    if not isinstance(identity, Mapping):
        return False
    account = identity.get("accountId")
    arn = identity.get("userArn")
    parts = arn.split(":") if isinstance(arn, str) else []
    if not account or len(parts) < 6 or parts[0] != "arn" or parts[4] != account:
        return False
    markers = ("cognitoIdentityId", "cognitoIdentityPoolId", "cognitoIdentityAuthType", "sub", "claims")
    return not any(identity.get(key) for key in markers)


def _lowercase_headers(event: Mapping[str, Any]) -> dict[str, str]:
    request = event.get("request") if isinstance(event, Mapping) else None
    raw = request.get("headers") if isinstance(request, Mapping) else None
    return {str(key).lower(): str(value) for key, value in raw.items()} if isinstance(raw, Mapping) else {}


def require_authorized(
    event: Mapping[str, Any],
    field_name: str,
    *,
    environment: Mapping[str, str] | None = None,
    endpoint: str | None = None,
    transport: Transport | None = None,
) -> Decision | None:
    """Gate one Lambda resolver call. Returns ``None`` when the flag is off or the caller is a site function.

    Raises :class:`AccountRequired`, :class:`ReenrollmentRequired` or :class:`AuthorizationDenied`; returns the allowed
    decision otherwise. Call it again before each later effect that must not outlive a revoked membership.
    """
    if not authorization_enabled(environment):
        return None
    if is_site_function_caller(event.get("identity")):
        return None
    headers = _lowercase_headers(event)
    account_id = headers.get(ACCOUNT_HEADER, "").strip()
    if not account_id:
        raise AccountRequired("account_required")
    decision = authorize(
        account_id,
        operation_for(field_name),
        headers.get(HUMAN_TOKEN_HEADER),
        endpoint=endpoint if endpoint is not None else (environment or os.environ).get(ENDPOINT_ENVIRONMENT_VARIABLE),
        transport=transport,
    )
    if not decision.allowed:
        raise AuthorizationDenied(decision.reason or DENIED_NOT_ALLOWED)
    return decision
