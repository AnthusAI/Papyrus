"""The poke-in operations on the command line's lanes (``agents_pause``, ``agents_resume``, ``agents_pauses``, ``agents_wake``; ``agent_poke_in.py``).

Signed in (the user lane), a change goes through the same door the newsroom uses: a pause or a resume to the site's agent-policy function (``agentPolicyChange``),
which refuses a credential that is not a person's and catches up the stopped wakes with its own role; wake now to the Automation page's function (``agentWake``),
which admits editors and admins. The operator's AWS lane runs the same code here, over the site store, the run index and the wake queue it can reach itself.
Showing the pauses reads the policy document directly on both lanes: an admin may read it.

It is its own module, imported by the call from the operation table's handlers, because the image service and the monitoring router never carry it.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .agent_policy.document import PolicyError
from .images.handlers import Caller, Handler, ImageOperationError, Outcome

AGENT_POLICY_CHANGE = "mutation AgentPolicyChange($input: AWSJSON) { agentPolicyChange(input: $input) }"
AGENT_WAKE = "mutation AgentWake($input: AWSJSON!) { agentWake(input: $input) }"
POLICY_OPERATIONS = ("agents_pause", "agents_resume")


def _answer(raw: Any, door: str) -> dict:
    answer = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(answer, dict):
        raise ImageOperationError("service_unavailable", f"The site's {door} gave no answer. It may not be on this site yet. Nothing was changed.")
    if not answer.get("ok"):
        code = str(answer.get("error") or "service_unavailable")
        if code == "forbidden":
            code = "not_authorized"
        known = code if code in ("invalid_input", "not_authorized", "human_required", "blocked", "not_found", "stale_version", "constraint_conflict") else "service_unavailable"
        raise ImageOperationError(known, str(answer.get("message") or answer.get("reason") or f"The site's {door} refused the request."))
    return answer["result"]


def _site_store(client):
    from .agent_definitions.cli import _site_store_for

    return _site_store_for(client)


def _operator_caller(client, caller: Caller) -> Caller:
    from .images.profile_handlers import identify

    return identify(client, caller)


def _tenant(client) -> str:
    tenant_id = getattr(client, "tenant_id", None)
    if not tenant_id:
        raise ImageOperationError("invalid_input", "The site's tenant is not known: pass --site, or sign in to the site, so the agents of one site are changed.", details={"path": "--site"})
    return tenant_id


def _policy_change(client, name: str, arguments: dict, caller: Caller) -> dict:
    from . import agent_poke_in
    from .agent_listeners import ListenerIndex
    from .agent_policy import AgentPolicyStore
    from .agent_wakes import wake_sender
    from .user_auth_mode import user_auth_requested

    tenant_id = _tenant(client)
    request = {"op": name, "agent": arguments.get("agent"), "reason": arguments["reason"], "tenantId": tenant_id}
    if user_auth_requested():
        return _answer(client.graphql(AGENT_POLICY_CHANGE, {"input": json.dumps(request)})["agentPolicyChange"], "agent-policy function")
    store = AgentPolicyStore(_site_store(client))
    person = _operator_caller(client, caller)
    try:
        if name == "agents_pause":
            return agent_poke_in.pause(store, tenant_id, person, agent=arguments.get("agent"), reason=arguments["reason"])
        return agent_poke_in.resume(store, tenant_id, person, agent=arguments.get("agent"), reason=arguments["reason"],
                                    listeners=ListenerIndex(store.site_store, tenant_id).document, ledger=agent_poke_in.RunLedger(client, tenant_id), send=wake_sender())
    except (PolicyError, agent_poke_in.PokeInError) as error:
        raise ImageOperationError(error.code, error.message) from error


def show_pauses(client, arguments: dict, caller: Caller) -> dict:
    from . import agent_poke_in
    from .agent_policy import AgentPolicyStore

    return agent_poke_in.pauses(AgentPolicyStore(_site_store(client)).read(_tenant(client)))


def wake_now(client, arguments: dict, caller: Caller) -> dict:
    from . import agent_poke_in
    from .agent_wakes import wake_sender
    from .user_auth_mode import user_auth_requested

    if user_auth_requested():
        request = {"op": "agents_wake", **{name: arguments[name] for name in ("agent", "subject", "reason")}}
        return _answer(client.graphql(AGENT_WAKE, {"input": json.dumps(request)})["agentWake"], "Automation page function")
    tenant_id = _tenant(client)
    person = _operator_caller(client, caller)
    try:
        return agent_poke_in.wake(agent_poke_in.RunLedger(client, tenant_id), wake_sender(), person, agent=arguments["agent"], subject=arguments["subject"],
                                  reason=arguments["reason"])
    except (PolicyError, agent_poke_in.PokeInError) as error:
        raise ImageOperationError(error.code, error.message) from error


POKE_IN_HANDLERS: dict[str, Callable[..., dict]] = {
    "agents_pause": lambda client, arguments, caller: _policy_change(client, "agents_pause", arguments, caller),
    "agents_resume": lambda client, arguments, caller: _policy_change(client, "agents_resume", arguments, caller),
    "agents_pauses": show_pauses,
    "agents_wake": wake_now,
}


def signed_in_handlers(client_factory: Callable[[], Any] | None = None) -> dict[str, Handler]:
    """Each call opens the authoring client of whoever runs it: the person's own session, or the operator's role."""
    def factory():
        if client_factory is not None:
            return client_factory()
        from .graphql_authoring import create_authoring_client

        return create_authoring_client()[0]

    def wrap(function):
        def handler(arguments: dict, caller: Caller) -> Outcome:
            client = factory()
            return Outcome(function(client, arguments, caller), str(getattr(client, "tenant_id", "") or ""))
        return handler

    return {name: wrap(function) for name, function in POKE_IN_HANDLERS.items()}
