"""The newsroom's rung board: every agent's rung on the site, and setting one, from the console with a person's ordinary admin sign-in.

Setting a rung is a person's decision (``set_rung``). Until now only ``papyrus agents set-rung`` did it, so a person needed the command line to raise an agent
one step. The console sends the same request to the site's agent-policy function, behind the same two checks as pause and resume (an admin whose token the
console's own app client issued), and the change runs through ``set_rung.apply``: the agent must be a definition, the rung no higher than the definition
uses, never ``publish_auto`` while its floor stands, and a reason is kept with the new version.

The definitions are the site's registered copies, the ones the deploy wrote on each Automation (``agents apply``): what the site actually runs, site agents
included. A caller with no registry to read (a test, the command line) uses the engine's core definitions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from papyrus_content.agent_rungs import RUNGS
from papyrus_content.images.handlers import Caller

from . import floors, set_rung
from .document import PolicyError
from .store import AgentPolicyStore

CONSOLE_RUNG_OPERATIONS = ("agents_rungs", "agents_set_rung")


@dataclass(frozen=True)
class RegisteredDefinition:
    """A definition as the deploy registered it on an Automation row: what ``set_rung`` reads (``id``, ``responsibility``, ``data``), with no YAML loader, so the
    agent-policy function, which ships without dependencies, can build it."""

    id: str
    data: dict[str, Any]

    @property
    def responsibility(self) -> str:
        return self.data["responsibility"]


DefinitionsSource = Callable[[], Sequence[Any]]


def registered_definitions(rows: Sequence[Mapping[str, Any]]) -> list[RegisteredDefinition]:
    """The live definitions the deploy registered on the site's Automation rows. A retired one, or a row with no registered copy, is no agent."""
    found: list[RegisteredDefinition] = []
    for row in rows:
        data = row.get("definition")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                continue
        if row.get("definitionRetiredAt") or not isinstance(data, dict):
            continue
        if not (data.get("id") and data.get("responsibility") and isinstance(data.get("operations"), dict) and data["operations"]):
            continue
        found.append(RegisteredDefinition(id=str(data["id"]), data=data))
    return sorted(found, key=lambda item: item.id)


def core_definitions() -> list[Any]:
    """The engine's own definitions, read from their YAML: for a caller with no registry to read (a test, the command line). The function always has one."""
    from papyrus_content.agent_definitions.definition import CORE_DIRECTORY, load_sets

    return sorted(load_sets(CORE_DIRECTORY, CORE_DIRECTORY).definitions, key=lambda item: item.id)


def rung_choices(ceiling: str) -> list[str]:
    """The rungs a person may pick for an agent whose definition goes no higher than ``ceiling``: never ``publish_auto`` while its floor stands."""
    return [rung for rung in RUNGS[: RUNGS.index(ceiling) + 1] if rung != floors.PUBLISH_AUTO]


def rung_board(store: AgentPolicyStore, tenant_id: str, definitions: Sequence[Any]) -> dict[str, Any]:
    """Each agent with its rung (``off`` when the policy does not name it), the most its definition uses, and the rungs a person may choose."""
    state = store.read(tenant_id)
    agents = []
    for definition in definitions:
        entry = state.document["agents"].get(definition.responsibility) or {}
        ceiling = set_rung.ceiling_of(definition)
        agents.append({"id": definition.id, "responsibility": definition.responsibility, "rung": entry.get("rung") or "off", "ceiling": ceiling,
                       "choices": rung_choices(ceiling), "overrides": len(entry.get("overrides") or [])})
    return {"policyVersion": state.version, "agents": agents}


def handle_request(store: AgentPolicyStore, site_tenant_id: str, caller: Caller, request: Mapping[str, Any], definitions: DefinitionsSource | None) -> dict[str, Any]:
    """Read the board or set one rung for the caller's own site. ``caller`` is a person who is an admin: the function's two checks have passed. Raises
    ``PolicyError`` or ``ValueError``, which the function turns into a refusal."""
    from papyrus_content.tenancy import validate_tenant_id

    if request.get("actorKind") == "agent":   # a declaration can only make a call stricter
        raise PolicyError("blocked", "An agent never sets a rung here. A person signed in to the console does. Nothing was saved.")
    tenant_id = validate_tenant_id(site_tenant_id)
    given = request.get("tenantId")
    if given not in (None, "") and given != tenant_id:
        raise PolicyError("not_authorized", "That tenant is not this site's.")
    known = list(definitions()) if definitions is not None else core_definitions()
    if request["op"] == "agents_rungs":
        return {"ok": True, "result": rung_board(store, tenant_id, known)}
    agent, rung, reason = request.get("agent"), request.get("rung"), request.get("reason")
    if not isinstance(agent, str) or not agent.strip():
        raise PolicyError("invalid_input", "Name the agent whose rung changes.")
    if not isinstance(rung, str) or not rung.strip():
        raise PolicyError("invalid_input", f"rung is one of: {', '.join(RUNGS)}.")
    if not isinstance(reason, str) or not reason.strip():
        raise PolicyError("invalid_input", "A rung change needs a reason.")
    change = set_rung.apply(store, tenant_id, caller, known, agent.strip(), rung.strip(), reason=reason)
    return {"ok": True, "result": {**change.as_dict(), "board": rung_board(store, tenant_id, known)}}
