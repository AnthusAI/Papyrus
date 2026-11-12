"""The announcements function: the X account connection and the announcement settings (PPY-09ee86).

Configuration comes from the environment the stack sets; a missing variable stops the cold start.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import boto3

from papyrus_content.announcements.actions import handle
from papyrus_content.announcements.settings import AnnouncementSettings
from papyrus_content.announcements.stores import DynamoConnection, DynamoSettings, SsmParameters
from papyrus_content.announcements.x_account import XAccounts, XEndpoints

_dynamodb = boto3.resource("dynamodb")
_settings = AnnouncementSettings(DynamoSettings(_dynamodb.Table(os.environ["ANNOUNCEMENT_SETTINGS_TABLE"]), time.time), time.time)
_accounts = XAccounts(
    site_id=os.environ["SITE_ID"],
    endpoints=XEndpoints(
        authorize_url=os.environ["X_AUTHORIZE_URL"], token_url=os.environ["X_TOKEN_URL"],
        revoke_url=os.environ["X_REVOKE_URL"], api_base=os.environ["X_API_BASE"],
    ),
    parameters=SsmParameters(boto3.client("ssm")),
    connection=DynamoConnection(_dynamodb.Table(os.environ["X_CONNECTION_TABLE"]), time.time),
    pauses=_settings,
    lease_seconds=float(os.environ["X_REFRESH_LEASE_SECONDS"]),
)


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    identity = event.get("identity") or {}
    groups = identity.get("groups") if isinstance(identity.get("groups"), list) else []
    claims = identity.get("claims") or {}
    actor = str(claims.get("email") or identity.get("username") or "console")[:100]
    operation = str((event.get("info") or {}).get("fieldName") or "")
    raw = (event.get("arguments") or {}).get("input")
    payload = json.loads(raw) if isinstance(raw, str) and raw else {}
    return handle(operation, payload, [g for g in groups if isinstance(g, str)], actor, _accounts, _settings)
