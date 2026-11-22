"""The ``announcements`` function's operations: what the console calls. Editors read; admins change.

Each operation answers ``{"ok": true, ...}`` or ``{"ok": false, "error": code, "message": plain words}``. No answer holds a secret.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from ..actor_identity import PERSON_CLIENT_IDS_VARIABLE, credential_is_person, person_client_ids  # noqa: F401
from ..appsync_event import NoOperation, operation_name
from .settings import AnnouncementSettings
from . import opportunity_search
from .x_account import AnnouncementError, XAccounts

READS = {"announcementsSettings", "announcementsXStatus", "announcementsXUsage", "announcementsXSpend"}
CHANGES = {"announcementsSaveSettings", "announcementsPause", "announcementsXSaveApp", "announcementsXBegin",
           "announcementsXComplete", "announcementsXDisconnect"}
PAID_SEARCH = "opportunitiesXSearch"
OPERATIONS = sorted(READS | CHANGES | {PAID_SEARCH})


#: The group an IAM role of the function's own AWS account acts in: the shared procedure runner that runs the announce agent signs its calls with its role, which carries no
#: Cognito group. It may make the read operations only; every change stays an admin's.
OPERATOR = "operator"


def is_operator_of_this_account(identity: Mapping[str, Any], account_id: str | None) -> bool:
    """An IAM principal (a role or user) of ``account_id``. A Cognito user, or an identity-pool user, is not one."""
    if not account_id:
        return False
    arn = identity.get("userArn")
    return (isinstance(arn, str) and arn.startswith("arn:") and identity.get("accountId") == account_id
            and not identity.get("cognitoIdentityId") and not identity.get("sub") and not identity.get("claims"))


def handle_event(event: Mapping[str, Any], accounts: XAccounts, settings: AnnouncementSettings, ledger: Callable[[], Any] | None = None,
                 *, account_id: str | None = None) -> dict[str, Any]:
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
    if is_operator_of_this_account(identity, account_id):
        groups, actor = [OPERATOR], str(identity.get("userArn"))[:100]
    try:
        payload = _payload((event.get("arguments") or {}).get("input"))
    except ValueError:
        return {"ok": False, "error": "invalid_input", "message": "The request input must be a JSON object."}
    if operation == PAID_SEARCH:
        try:
            if not {"editor", "admin"}.intersection(groups):
                raise AnnouncementError("forbidden", "Your role cannot search for this site.")
            opportunity_search.authorize(identity, credential_is_person(claims))
            return {"ok": True, **opportunity_search.search(payload, accounts, settings, ledger)}
        except AnnouncementError as error:
            return {"ok": False, "error": error.code, "message": error.message}
    person = credential_is_person(claims)
    return handle(operation, payload, [g for g in groups if isinstance(g, str)], actor, accounts, settings, ledger,
                  person_credential=person, authorize_search_settings=lambda: opportunity_search.authorize(identity, person))


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


def changes_search_settings(proposed: Any, current: Mapping[str, Any]) -> bool:
    if not isinstance(proposed, dict):
        return False
    options = current.get("opportunities") or {}
    if "opportunities" in proposed and proposed["opportunities"] != options:
        return True
    return bool(options.get("enabled") and "billingCycleDay" in proposed and proposed["billingCycleDay"] != current.get("billingCycleDay"))


def handle(operation: str, payload: dict[str, Any], groups: list[str], actor: str, accounts: XAccounts, settings: AnnouncementSettings,
           ledger: Callable[[], Any] | None = None, *, person_credential: bool = True,
           authorize_search_settings: Callable[[], None] | None = None) -> dict[str, Any]:
    try:
        if operation not in READS | CHANGES:
            raise AnnouncementError("unknown_operation", f"Unknown operation {operation}.")
        allowed = {"admin"} if operation in CHANGES else {"admin", "editor", OPERATOR}
        if not allowed.intersection(groups):
            raise AnnouncementError("forbidden", "Your role cannot do this.")
        if not person_credential and turns_announcements_on(operation, payload, settings):
            raise AnnouncementError("person_only", "Only a person signed in to the console can turn announcements On. This credential is not one. Nothing was saved.")
        if operation == "announcementsSaveSettings" and changes_search_settings(payload.get("settings"), settings.read()):
            if authorize_search_settings is None:
                raise AnnouncementError("person_only", "Only an admin signed in to the newsroom can change X search settings.")
            authorize_search_settings()
        return {"ok": True, **_run(operation, payload, actor, accounts, settings, ledger)}
    except KeyError as error:
        return {"ok": False, "error": "missing_field", "message": f"The request is missing {error.args[0]}."}
    except AnnouncementError as error:
        return {"ok": False, "error": error.code, "message": error.message}


def _run(operation: str, payload: dict[str, Any], actor: str, accounts: XAccounts, settings: AnnouncementSettings, ledger: Callable[[], Any] | None = None) -> dict[str, Any]:
    status = accounts.status
    table: dict[str, Callable[[], dict[str, Any]]] = {
        "announcementsSettings": lambda: {"settings": settings.read()},
        "announcementsXStatus": lambda: {"status": status()},
        "announcementsXUsage": lambda: {"usage": accounts.usage()},
        "announcementsXSpend": lambda: {"spent": _spent(ledger, payload["accountId"], payload["cycleStart"])},
        "announcementsSaveSettings": lambda: {"settings": settings.save(payload["settings"], status()["connection"])},
        "announcementsPause": lambda: {"settings": settings.manual_pause(bool(payload["paused"]), actor)},
        "announcementsXSaveApp": lambda: {"status": accounts.save_app(payload["clientId"], payload["clientSecret"], actor)},
        "announcementsXBegin": lambda: accounts.begin(payload["redirectUri"]),
        "announcementsXComplete": lambda: {"status": accounts.complete(payload["code"], payload["state"], payload["redirectUri"], actor)},
        "announcementsXDisconnect": lambda: {"status": accounts.disconnect(actor), "settings": settings.read()},
    }
    return table[operation]()


def _spent(ledger: Callable[[], Any] | None, account_id: str, cycle_start: str) -> str | None:
    """What the account has spent on X in the cycle that starts on ``cycle_start``, from the spend ledger (the dollars as a decimal string, or None when nothing was charged)."""
    from datetime import date

    from ..spend_ledger import SpendError

    if ledger is None:
        raise AnnouncementError("not_configured", "This site's function has no spend ledger.")
    try:
        return ledger().spent(str(account_id), date.fromisoformat(str(cycle_start)))
    except (SpendError, ValueError) as error:
        raise AnnouncementError("spend_unreadable", str(error)) from error
