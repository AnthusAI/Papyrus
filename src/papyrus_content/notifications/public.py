"""The reader-facing actions the ``/api/notifications`` routes send (subscribe, confirm, preferences, unsubscribe, state).

Caducus 0.2.0 routes only to operators named in the host's AWS configuration. It has no reader directory, consent record
or preferences yet, and this adapter does not invent them. Every reader action therefore answers ``unavailable`` and stores
nothing, so the routes are in place and a later Caducus release lights them up without a route change.
"""

from __future__ import annotations

from typing import Any, Mapping

READER_ACTIONS = frozenset(
    {"subscribe", "confirm", "confirm_page_state", "preferences_state", "update_preferences", "unsubscribe", "delete_subscriber"}
)


def handle(event: Mapping[str, Any]) -> dict[str, Any]:
    return {"statusCode": 503, "body": {"status": "unavailable"}}
