"""Agent policy changes made through the site's ``agent-policy`` function, so the server decides who may make them.

A signed-in admin used to write the policy document with their own AWS credentials, which an agent working in their session also holds, so nothing on the server
could tell the two apart. Now the signed-in lane sends each change to the function as a plain request. The function checks the credential (an admin, signed in
through a person-only app client), refuses ``publish_auto`` while the hard floor stands, and writes the version with its own role. ``RemoteAgentPolicyStore`` reads
as the local store does and sends every change; ``apply_request`` is the function's side of the same five changes.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from papyrus_content.images.handlers import Caller

from . import floors
from .document import PolicyError, check_rung
from .resolve import PolicyState
from .store import AgentPolicyStore

OPERATIONS = ("set_rung", "remove_override", "pause", "resume", "set_value")


class RemoteAgentPolicyStore(AgentPolicyStore):
    """``send(request) -> {"ok": True, "version": n, "document": {...}}`` or ``{"ok": False, "error": code, "message": words}``."""

    def __init__(self, site_store: Any, send: Callable[[dict[str, Any]], Mapping[str, Any]]):
        super().__init__(site_store)
        self._send = send

    def _change_by_request(self, tenant_id: str, request: dict[str, Any]) -> PolicyState:
        answer = self._send({"tenantId": tenant_id, **request})
        if not answer.get("ok"):
            raise PolicyError(str(answer.get("error") or "invalid_input"), str(answer.get("message") or "The agent policy function refused the change."))
        return PolicyState(int(answer["version"]), answer["document"])

    def change(self, tenant_id, caller, reason, edit):
        """A free-form edit would be written with the caller's own credentials, which hold no write on the policy: only the named changes exist here."""
        raise PolicyError("invalid_input", "On the signed-in lane the agent policy changes only through the agent-policy function's named changes.")

    def set_rung(self, tenant_id, caller, responsibility, rung, *, reason, scope=None):
        return self._change_by_request(tenant_id, {"op": "set_rung", "responsibility": responsibility, "rung": rung, "reason": reason, "scope": dict(scope) if scope else None})

    def remove_override(self, tenant_id, caller, responsibility, scope, *, reason):
        return self._change_by_request(tenant_id, {"op": "remove_override", "responsibility": responsibility, "scope": dict(scope), "reason": reason})

    def pause(self, tenant_id, caller, *, reason, responsibility=None):
        return self._change_by_request(tenant_id, {"op": "pause", "responsibility": responsibility, "reason": reason})

    def resume(self, tenant_id, caller, *, reason, responsibility=None):
        return self._change_by_request(tenant_id, {"op": "resume", "responsibility": responsibility, "reason": reason})

    def set_value(self, tenant_id, caller, field, value, *, reason, responsibility=None):
        return self._change_by_request(tenant_id, {"op": "set_value", "field": field, "value": value, "responsibility": responsibility, "reason": reason})


def apply_request(store: AgentPolicyStore, tenant_id: str, caller: Caller, request: Mapping[str, Any]) -> PolicyState:
    """The function's side: check the request and make the same change the local store would. Raises ``PolicyError``."""
    operation = request.get("op")
    if operation not in OPERATIONS:
        raise PolicyError("invalid_input", f"An agent policy change is one of: {', '.join(OPERATIONS)}.")
    reason = request.get("reason")
    if not isinstance(reason, str):
        raise PolicyError("invalid_input", "A policy change needs a reason.")
    responsibility = request.get("responsibility")
    if responsibility is not None and not isinstance(responsibility, str):
        raise PolicyError("invalid_input", "responsibility is the agent's name.")
    if operation == "set_rung":
        check_rung(request.get("rung"), "rung")
        if request["rung"] == floors.PUBLISH_AUTO:
            raise PolicyError("constraint_conflict", floors.publish_auto_refusal(str(responsibility)))
        return store.set_rung(tenant_id, caller, _named(responsibility), request["rung"], reason=reason, scope=request.get("scope") or None)
    if operation == "remove_override":
        return store.remove_override(tenant_id, caller, _named(responsibility), request.get("scope") or {}, reason=reason)
    if operation == "pause":
        return store.pause(tenant_id, caller, reason=reason, responsibility=responsibility)
    if operation == "resume":
        return store.resume(tenant_id, caller, reason=reason, responsibility=responsibility)
    return store.set_value(tenant_id, caller, str(request.get("field")), request.get("value"), reason=reason, responsibility=responsibility)


def _named(responsibility: str | None) -> str:
    if not responsibility:
        raise PolicyError("invalid_input", "Name the agent.")
    return responsibility
