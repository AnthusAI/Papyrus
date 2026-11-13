"""The ``announcements`` function's operations: what the console calls. Editors read; admins change.

Each operation answers ``{"ok": true, ...}`` or ``{"ok": false, "error": code, "message": plain words}``. No answer holds a secret.
"""

from __future__ import annotations

from typing import Any, Callable

from .settings import AnnouncementSettings
from .x_account import AnnouncementError, XAccounts

READS = {"announcementsSettings", "announcementsXStatus", "announcementsXUsage"}
CHANGES = {"announcementsSaveSettings", "announcementsPause", "announcementsXSaveApp", "announcementsXBegin",
           "announcementsXComplete", "announcementsXDisconnect"}
OPERATIONS = sorted(READS | CHANGES)


def handle(operation: str, payload: dict[str, Any], groups: list[str], actor: str, accounts: XAccounts, settings: AnnouncementSettings) -> dict[str, Any]:
    try:
        if operation not in READS | CHANGES:
            raise AnnouncementError("unknown_operation", f"Unknown operation {operation}.")
        allowed = {"admin"} if operation in CHANGES else {"admin", "editor"}
        if not allowed.intersection(groups):
            raise AnnouncementError("forbidden", "Your role cannot do this.")
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
