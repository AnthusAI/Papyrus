"""submitSignup: the only operation of the signup plugin that a guest can call.

A guest sends a form name and an email-like value. This handler throttles the
caller, validates and length-limits every argument, drops honeypot and too-fast
submissions without telling the sender, and writes one SignupEntry through the
GraphQL API under an id derived from the content, so repeating a submission
changes nothing. Guests never read entries back.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

STATUS_ACCEPTED = "accepted"
STATUS_INVALID = "invalid"
STATUS_EXPIRED = "expired"
STATUS_THROTTLED = "throttled"

MAXIMUM_ARGUMENT_CHARACTERS = 1000
MAXIMUM_VALUE_CHARACTERS = 254
MINIMUM_FILL_SECONDS = 2
MAXIMUM_AGE_SECONDS = 24 * 60 * 60
RATE_WINDOW_SECONDS = 60
COUNTER_LIFETIME_SECONDS = 5 * 60
DEFAULT_ADDRESS_LIMIT_PER_WINDOW = 20
DEFAULT_IDENTITY_LIMIT_PER_WINDOW = 5
FORBIDDEN_FIRST_CHARACTERS = "=+-@"
FORM_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
RENDERED_AT = re.compile(r"[0-9]{1,16}")
LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
EMAIL_LIKE = re.compile(rf"[A-Za-z0-9.!#$%&'*+/=?^_`{{|}}~-]{{1,64}}@{LABEL}(?:\.{LABEL})+")
CREATE_ENTRY_MUTATION = (
    "mutation CreateSignupEntry($input: CreateSignupEntryInput!) { createSignupEntry(input: $input) { id } }"
)
ALREADY_STORED_MARKERS = ("ConditionalCheckFailed", "conditional request failed")


@dataclass(frozen=True)
class SignupSettings:
    forms: frozenset[str]
    address_limit: int = DEFAULT_ADDRESS_LIMIT_PER_WINDOW
    identity_limit: int = DEFAULT_IDENTITY_LIMIT_PER_WINDOW


def settings_from_environment(environment: dict[str, str] | None = None) -> SignupSettings:
    environment = os.environ if environment is None else environment
    forms = frozenset(name.strip() for name in environment.get("PAPYRUS_SIGNUP_FORMS", "").split(",") if name.strip())
    return SignupSettings(
        forms=forms,
        address_limit=int(environment.get("PAPYRUS_SIGNUP_ADDRESS_LIMIT", DEFAULT_ADDRESS_LIMIT_PER_WINDOW)),
        identity_limit=int(environment.get("PAPYRUS_SIGNUP_IDENTITY_LIMIT", DEFAULT_IDENTITY_LIMIT_PER_WINDOW)),
    )


def result(status: str, message: str = "") -> dict[str, str]:
    return {"status": status, "message": message}


def normalized_value(value: str) -> str:
    local, _, domain = value.partition("@")
    return f"{local}@{domain.lower()}"


def entry_identifier(form: str, value: str) -> str:
    return hashlib.sha256(f"{form}\n{normalized_value(value)}".encode("utf-8")).hexdigest()[:32]


def valid_value(value: str) -> bool:
    return (
        0 < len(value) <= MAXIMUM_VALUE_CHARACTERS
        and value[0] not in FORBIDDEN_FIRST_CHARACTERS
        and EMAIL_LIKE.fullmatch(value) is not None
    )


def caller_address(headers: dict[str, str] | None) -> str:
    """The address AppSync appended last: a sender can add earlier entries, never the last."""
    forwarded = {name.lower(): text for name, text in (headers or {}).items()}.get("x-forwarded-for", "")
    entries = [part.strip() for part in forwarded.split(",") if part.strip()]
    return entries[-1] if entries else "unknown"


def rate_key(kind: str, subject: str, now_seconds: float) -> str:
    window = int(now_seconds // RATE_WINDOW_SECONDS)
    return f"{kind}#{hashlib.sha256(subject.encode('utf-8')).hexdigest()[:24]}#{window}"


def parse_rendered_at(text: str) -> float | None:
    return int(text) / 1000.0 if RENDERED_AT.fullmatch(text) else None


def submit_signup(
    arguments: dict[str, Any],
    *,
    address: str,
    identity_id: str | None,
    now_seconds: float,
    settings: SignupSettings,
    count_hit: Callable[[str, int], int],
    store_entry: Callable[[dict[str, str]], bool],
) -> dict[str, str]:
    if count_hit(rate_key("address", address, now_seconds), COUNTER_LIFETIME_SECONDS) > settings.address_limit:
        return result(STATUS_THROTTLED, "Too many requests. Try again in a minute.")
    if identity_id and count_hit(rate_key("identity", identity_id, now_seconds), COUNTER_LIFETIME_SECONDS) > settings.identity_limit:
        return result(STATUS_THROTTLED, "Too many requests. Try again in a minute.")

    form, value = arguments.get("form"), arguments.get("value")
    honeypot, rendered_at = arguments.get("website"), arguments.get("renderedAt")
    texts = [form, value, honeypot, rendered_at]
    if any(text is not None and not isinstance(text, str) for text in texts):
        return result(STATUS_INVALID, "Malformed request.")
    if any(text is not None and len(text) > MAXIMUM_ARGUMENT_CHARACTERS for text in texts):
        return result(STATUS_INVALID, "Request too large.")
    if not isinstance(form, str) or not FORM_NAME.fullmatch(form) or form not in settings.forms:
        return result(STATUS_INVALID, "Unknown form.")
    if not isinstance(value, str) or not valid_value(value):
        return result(STATUS_INVALID, "Enter a valid email address.")
    rendered_seconds = parse_rendered_at(rendered_at) if isinstance(rendered_at, str) else None
    if rendered_seconds is None:
        return result(STATUS_INVALID, "Malformed request.")
    age_seconds = now_seconds - rendered_seconds
    if age_seconds > MAXIMUM_AGE_SECONDS:
        return result(STATUS_EXPIRED, "This form has expired. Reload the page and try again.")
    if honeypot or age_seconds < MINIMUM_FILL_SECONDS:
        return result(STATUS_ACCEPTED)

    submitted_at = datetime.fromtimestamp(now_seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    store_entry(
        {
            "id": entry_identifier(form, value),
            "form": form,
            "value": normalized_value(value),
            "submittedAt": submitted_at,
        }
    )
    return result(STATUS_ACCEPTED)


def counting_hits(table_name: str, client: Any = None) -> Callable[[str, int], int]:
    import boto3

    table_client = client or boto3.client("dynamodb")

    def count_hit(key: str, lifetime_seconds: int) -> int:
        response = table_client.update_item(
            TableName=table_name,
            Key={"pk": {"S": key}},
            UpdateExpression="ADD hits :one SET expiresAt = :expires",
            ExpressionAttributeValues={
                ":one": {"N": "1"},
                ":expires": {"N": str(int(time.time()) + lifetime_seconds)},
            },
            ReturnValues="UPDATED_NEW",
        )
        return int(response["Attributes"]["hits"]["N"])

    return count_hit


def storing_entries(endpoint: str, region: str) -> Callable[[dict[str, str]], bool]:
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    def store_entry(entry: dict[str, str]) -> bool:
        body = json.dumps({"query": CREATE_ENTRY_MUTATION, "variables": {"input": entry}}).encode("utf-8")
        request = AWSRequest(method="POST", url=endpoint, data=body, headers={"content-type": "application/json"})
        SigV4Auth(boto3.Session().get_credentials().get_frozen_credentials(), "appsync", region).add_auth(request)
        http_request = urllib.request.Request(endpoint, data=body, headers=dict(request.headers.items()), method="POST")
        with urllib.request.urlopen(http_request, timeout=10) as response:
            payload = json.loads(response.read())
        errors = payload.get("errors") or []
        if not errors:
            return True
        if all(any(marker in str(error) for marker in ALREADY_STORED_MARKERS) for error in errors):
            return False
        raise RuntimeError(f"createSignupEntry failed: {errors}")

    return store_entry


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, str]:
    identity = event.get("identity") or {}
    headers = (event.get("request") or {}).get("headers")
    return submit_signup(
        event.get("arguments") or {},
        address=caller_address(headers),
        identity_id=identity.get("cognitoIdentityId"),
        now_seconds=time.time(),
        settings=settings_from_environment(),
        count_hit=counting_hits(os.environ["PAPYRUS_SIGNUP_RATE_TABLE"]),
        store_entry=storing_entries(os.environ["PAPYRUS_GRAPHQL_ENDPOINT"], os.environ["AWS_REGION"]),
    )
