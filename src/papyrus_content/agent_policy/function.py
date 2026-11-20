"""The agent-policy function's decision: who may change the agent policy, and the change.

The caller must be an admin whose token was issued to a person-only app client (``actor_identity.credential_is_person``). Answers ``{"ok": true, "version", "document"}``
or ``{"ok": false, "error": code, "message": words}``.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from papyrus_content.actor_identity import credential_is_person
from papyrus_content.images.handlers import Caller
from papyrus_content.tenancy import TenantError, validate_tenant_id

from .document import PolicyError
from .remote import apply_request
from .store import AgentPolicyStore


def refusal(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message}


def handle(event: dict[str, Any], store: AgentPolicyStore, environ: Mapping[str, str], site_tenant_id: str) -> dict[str, Any]:
    identity = event.get("identity") or {}
    groups = identity.get("groups") if isinstance(identity.get("groups"), list) else []
    claims = identity.get("claims") or {}
    if "admin" not in groups:
        return refusal("not_authorized", "Only an admin changes the agent policy.")
    if not credential_is_person(claims, environ):
        return refusal("human_required", "Only a person signed in to the console changes the agent policy. This credential is not one. Nothing was saved.")
    try:
        raw = (event.get("arguments") or {}).get("input")
        request = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(request, dict):
            return refusal("invalid_input", "The request input must be a JSON object.")
        tenant_id = validate_tenant_id(str(request.get("tenantId") or ""))
        if tenant_id != site_tenant_id:
            return refusal("not_authorized", "That tenant is not this site's.")
        caller = Caller(kind="person", subject=str(claims.get("email") or identity.get("username") or "console")[:100], is_admin=True)
        state = apply_request(store, tenant_id, caller, request)
    except PolicyError as error:
        return refusal(error.code, error.message)
    except (ValueError, TenantError) as error:
        return refusal("invalid_input", str(error))
    return {"ok": True, "version": state.version, "document": state.document}
