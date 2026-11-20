"""The ``announcements`` function's operations: what the console calls. Editors read; admins change.

Each operation answers ``{"ok": true, ...}`` or ``{"ok": false, "error": code, "message": plain words}``. No answer holds a secret.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Mapping

from ..appsync_event import NoOperation, operation_name
from .settings import AnnouncementSettings
from .x_account import AnnouncementError, XAccounts

READS = {"announcementsSettings", "announcementsXStatus", "announcementsXUsage"}
CHANGES = {"announcementsSaveSettings", "announcementsPause", "announcementsXSaveApp", "announcementsXBegin",
           "announcementsXComplete", "announcementsXDisconnect"}
OPERATIONS = sorted(READS | CHANGES)
PERSON_CLIENT_IDS_VARIABLE = "PERSON_ONLY_CLIENT_IDS"


def person_client_ids(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """The app clients a person signs in with (the console). A credential issued to any other client, such as the CLI's that an agent shares, is not a person's."""
    raw = (os.environ if environ is None else environ).get(PERSON_CLIENT_IDS_VARIABLE, "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def credential_is_person(claims: Mapping[str, Any], environ: Mapping[str, str] | None = None) -> bool:
    """True only when the token was issued to a person-only app client. No configured client means no credential is a person's: the rule fails closed."""
    issued_to = {str(claims.get(name)) for name in ("aud", "client_id") if claims.get(name)}
    return bool(issued_to & person_client_ids(environ))


def handle_event(event: Mapping[str, Any], accounts: XAccounts, settings: AnnouncementSettings) -> dict[str, Any]:
    """What the function does with one AppSync request: the operation is the GraphQL field (``appsync_event.operation_name``),
    the payload is the ``input`` argument, and the caller's groups and name come from the identity."""
    try:
        operation = operation_name(event)
    except NoOperation as error:
        return {"ok": False, "error": "no_operation", "message": str(error)}
    identity = event.get("identity") or {}
    groups = identity.get("groups") if isinstance(identity.get("groups"), list) else []
    claims = identity.get("claims") or {}
    actor = str(claims.get("email") or identity.get("username") or "console")[:100]
    try:
        payload = _payload((event.get("arguments") or {}).get("input"))
    except ValueError:
        return {"ok": False, "error": "invalid_input", "message": "The request input must be a JSON object."}
    return handle(operation, payload, [g for g in groups if isinstance(g, str)], actor, accounts, settings, person_credential=credential_is_person(claims))


def _payload(raw: Any) -> dict[str, Any]:
    """The ``input`` argument is AWSJSON: a JSON object, or its text. Absent means an empty request."""
    if raw is None:
        return {}
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(parsed, dict):
        raise ValueError("input is not a JSON object")
    return parsed


def turns_announcements_on(operation: str, payload: dict[str, Any], settings: AnnouncementSettings) -> bool:
    if operation != "announcementsSaveSettings":
        return False
    proposed = payload.get("settings") or {}
    return isinstance(proposed, dict) and proposed.get("mode") == "on" and settings.read().get("mode") != "on"


def handle(operation: str, payload: dict[str, Any], groups: list[str], actor: str, accounts: XAccounts, settings: AnnouncementSettings, *, person_credential: bool = True) -> dict[str, Any]:
    try:
        if operation not in READS | CHANGES:
            raise AnnouncementError("unknown_operation", f"Unknown operation {operation}.")
        allowed = {"admin"} if operation in CHANGES else {"admin", "editor"}
        if not allowed.intersection(groups):
            raise AnnouncementError("forbidden", "Your role cannot do this.")
        if not person_credential and turns_announcements_on(operation, payload, settings):
            raise AnnouncementError("person_only", "Only a person signed in to the console can turn announcements On. This credential is not one. Nothing was saved.")
        return {"ok": True, **_run(operation, payload, actor, accounts, settings)}
    except KeyError as error:
        return {"ok": False, "error": "missing_field", "message": f"The request is missing {error.args[0]}."}
    except AnnouncementError as error:
        return {"ok": False, "error": error.code, "message": error.message}


def _run(operation: str, payload: dict[str, Any], actor: str, accounts: XAccounts, settings: AnnouncementSettings) -> dict[str, Any]:
    status = accounts.status
    table: dict[str, Callable[[], dict[str, Any]]] = {
        "announcementsSettings": lambda: {"settings": settings.read()},
        "announcementsXStatus": lambda: {"status": status()},
        "announcementsXUsage": lambda: {"usage": accounts.usage()},
        "announcementsSaveSettings": lambda: {"settings": settings.save(payload["settings"], status()["connection"])},
        "announcementsPause": lambda: {"settings": settings.manual_pause(bool(payload["paused"]), actor)},
        "announcementsXSaveApp": lambda: {"status": accounts.save_app(payload["clientId"], payload["clientSecret"], actor)},
        "announcementsXBegin": lambda: accounts.begin(payload["redirectUri"]),
        "announcementsXComplete": lambda: {"status": accounts.complete(payload["code"], payload["state"], payload["redirectUri"], actor)},
        "announcementsXDisconnect": lambda: {"status": accounts.disconnect(actor), "settings": settings.read()},
    }
    return table[operation]()
