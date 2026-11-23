"""The agent-policy function's decision: who may change the agent policy, and the change.

The caller must be an admin whose token was issued to a person-only app client (``actor_identity.credential_is_person``). Answers ``{"ok": true, "version", "document"}``
or ``{"ok": false, "error": code, "message": words}``.

It is also the newsroom console's door to the announcement review (``announcements_review_show`` and ``announcements_review_set``, PPY-e2829f): the review is the ``announce``
rung of this same document, so the console reads and sets it here, behind the same two checks, with the same code the command line runs
(``announcements.review_handlers.show_review`` and ``set_review_by_person``). Those two answer ``{"ok": true, "result": {...}}``; their tenant is the caller's own.
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


#: The poke-in operations of the operation table (``agent_poke_in.py``) that change or read the policy: the console and the signed-in command line send them here.
POKE_IN_OPERATIONS = ("agents_pause", "agents_resume", "agents_pauses")

#: The announcement review requests the console sends (``announcements.review_handlers``). The review scope is a channel, an Announcement kind or a list.
ANNOUNCEMENT_REVIEW_OPERATIONS = ("announcements_review_show", "announcements_review_set")
ANNOUNCEMENT_REVIEW_SCOPES = ("channel", "kind", "list")


def refusal(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message}


class PokeInServices:
    """What a resume needs beyond the policy: the listener index (which agents listen for changes), the run index (the wakes a pause stopped) and the site's
    wake queue. The function's handler builds them from its own role; a test passes fakes."""

    def __init__(self, listeners, ledger, send):
        self.listeners, self.ledger, self.send = listeners, ledger, send


def handle(event: dict[str, Any], store: AgentPolicyStore, environ: Mapping[str, str], site_tenant_id: str,
           services: PokeInServices | None = None) -> dict[str, Any]:
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
        caller = Caller(kind="person", subject=str(claims.get("email") or identity.get("username") or "console")[:100], is_admin=True)
        if request.get("op") in ANNOUNCEMENT_REVIEW_OPERATIONS:
            return announcement_review(store, site_tenant_id, caller, request)
        if request.get("op") in POKE_IN_OPERATIONS:
            return poke_in(store, site_tenant_id, caller, request, services)
        tenant_id = validate_tenant_id(str(request.get("tenantId") or ""))
        if tenant_id != site_tenant_id:
            return refusal("not_authorized", "That tenant is not this site's.")
        state = apply_request(store, tenant_id, caller, request)
    except PolicyError as error:
        return refusal(error.code, error.message)
    except (ValueError, TenantError) as error:
        return refusal("invalid_input", str(error))
    return {"ok": True, "version": state.version, "document": state.document}


def poke_in(store: AgentPolicyStore, site_tenant_id: str, caller: Caller, request: Mapping[str, Any], services: PokeInServices | None) -> dict[str, Any]:
    """Pause, resume or show the pauses of the caller's own site, with the code the operator's command line runs (``agent_poke_in``). ``caller`` is a person
    who is an admin: the two checks above have passed. Raises ``PolicyError`` or ``ValueError``."""
    from papyrus_content import agent_poke_in

    if request.get("actorKind") == "agent":   # a declaration can only make a call stricter
        return refusal("blocked", "An agent never pauses or resumes agents. A person signed in to the console does. Nothing was saved.")
    tenant_id = validate_tenant_id(site_tenant_id)
    given = request.get("tenantId")
    if given not in (None, "") and given != tenant_id:
        return refusal("not_authorized", "That tenant is not this site's.")
    agent = request.get("agent")
    if agent is not None and (not isinstance(agent, str) or not agent.strip()):
        return refusal("invalid_input", "agent is the agent's name in the agent policy; leave it out for the whole site.")
    if request["op"] == "agents_pauses":
        return {"ok": True, "result": agent_poke_in.pauses(store.read(tenant_id))}
    reason = request.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return refusal("invalid_input", "A pause or a resume needs a reason.")
    if request["op"] == "agents_pause":
        result = agent_poke_in.pause(store, tenant_id, caller, agent=agent, reason=reason)
    else:
        if services is None:
            return refusal("service_unavailable", "This site's agent-policy function cannot read the run index or reach the wake queue, so a resume would lose the "
                                                  "wakes the pause stopped. Nothing was saved.")
        try:
            result = agent_poke_in.resume(store, tenant_id, caller, agent=agent, reason=reason, listeners=services.listeners, ledger=services.ledger, send=services.send)
        except agent_poke_in.PokeInError as error:
            return refusal(error.code, error.message)
    state = store.read(tenant_id)
    return {"ok": True, "result": result, "version": state.version, "document": state.document}


def announcement_review(store: AgentPolicyStore, site_tenant_id: str, caller: Caller, request: Mapping[str, Any]) -> dict[str, Any]:
    """Show or set the announcement review for the caller's own site. ``caller`` is a person: the two checks above have passed. Raises ``PolicyError`` or ``ValueError``."""
    from papyrus_content.announcements.review_handlers import set_review_by_person, show_review

    if request.get("actorKind") == "agent":   # a declaration can only make a call stricter: an agent never changes or reads the review here
        return refusal("blocked", "An agent does not set the announcement review. A person signed in to the console does. Nothing was saved.")
    tenant_id = validate_tenant_id(site_tenant_id)
    given = request.get("tenantId")
    if given not in (None, "") and given != tenant_id:
        return refusal("not_authorized", "That tenant is not this site's.")
    scope: dict[str, str] = {}
    for name in ANNOUNCEMENT_REVIEW_SCOPES:
        value = request.get(name)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            return refusal("invalid_input", f"{name} is a name.")
        scope[name] = value
    if request["op"] == "announcements_review_show":
        return {"ok": True, "result": show_review(store, tenant_id, scope)}
    approval, reason = request.get("approval"), request.get("reason")
    if approval not in ("hard", "soft", "none", "inherit"):
        return refusal("invalid_input", "approval is one of: hard, soft, none, inherit.")
    if not isinstance(reason, str) or not reason.strip():
        return refusal("invalid_input", "A review change needs a reason.")
    return {"ok": True, "result": set_review_by_person(store, tenant_id, caller, approval, scope, reason.strip())}
