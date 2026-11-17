"""Set an agent's rung on a site (PPY-e6f31e, slice H3): the check, the preview and the write behind ``papyrus agents set-rung``.

A rung is Ryan's decision and a person's alone: only an admin who is a person sets one, with a reason, and every change is a new version of the
site's policy document (``AgentPolicyStore``), so the history stays. Before anything is written the request is checked here:

* the agent is a definition that exists (the engine's core definitions and the site's own) and the rung is one of the ladder;
* **the rung is no higher than the definition allows.** A definition names the lowest rung each operation it uses needs, so the highest of them is the
  most the agent can do; a rung above it would allow nothing more and is refused. Lowering a rung, and ``off``, are always allowed;
* ``publish_auto`` is refused while a hard floor forbids it (``floors.py``).

``plan`` never writes. ``apply`` writes the same change and returns the same shape, with the version it saved.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from papyrus_content.agent_rungs import RUNGS
from papyrus_content.images.handlers import Caller

from . import floors
from .document import PolicyError, check_rung, check_scope
from .store import AgentPolicyStore, may_change


@dataclass(frozen=True)
class RungChange:
    id: str
    responsibility: str
    scope: dict[str, str] | None
    rung: str
    ceiling: str
    reason: str
    before_version: int
    before: dict[str, Any] | None      # the agent's entry in the policy as it stands (None: not named, so at off)
    after_version: int                 # the version the change is, or would be; the same as before_version when it changes nothing
    after: dict[str, Any] | None
    changed: bool
    applied: bool

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "responsibility": self.responsibility, "scope": self.scope, "rung": self.rung, "ceiling": self.ceiling, "reason": self.reason,
                "changed": self.changed, "applied": self.applied,
                "before": {"policyVersion": self.before_version, "entry": self.before},
                "after": {"policyVersion": self.after_version, "entry": self.after}}


def ceiling_of(definition: Any) -> str:
    """The highest rung any operation the definition uses asks for: the most the agent can do."""
    return max(definition.data["operations"].values(), key=RUNGS.index)


def _definition(definitions: Sequence[Any], agent_id: str) -> Any:
    found = next((item for item in definitions if item.id == agent_id), None)
    if found is None:
        raise PolicyError("invalid_input", f"{agent_id} is not an agent definition. Choose one of: {', '.join(sorted(item.id for item in definitions))}.")
    return found


def _refuse_rung(definition: Any, rung: str) -> str:
    check_rung(rung, "rung")
    ceiling = ceiling_of(definition)
    if RUNGS.index(rung) > RUNGS.index(ceiling):
        raise PolicyError("constraint_conflict", f"{definition.id} cannot be set to {rung}: its definition uses no operation that needs more than {ceiling}, so a higher rung allows it nothing more. "
                                           f"Set it to {ceiling} or lower.")
    if rung == floors.PUBLISH_AUTO:
        raise PolicyError("constraint_conflict", floors.publish_auto_refusal(definition.responsibility))
    return ceiling


def plan(policy: AgentPolicyStore, tenant_id: str, caller: Caller, definitions: Sequence[Any], agent_id: str, rung: str, *, reason: str,
         scope: Mapping[str, str] | None = None) -> RungChange:
    """What setting the rung would do, written nowhere. Refuses as the write would."""
    may_change(caller)
    definition = _definition(definitions, agent_id)
    scope = check_scope(scope, "scope") if scope else None
    ceiling = _refuse_rung(definition, rung)
    state, document = policy.prepare(tenant_id, caller, reason, policy.rung_edit(definition.responsibility, rung, scope))
    changed = document != state.document
    return RungChange(agent_id, definition.responsibility, scope, rung, ceiling, reason.strip(), state.version, state.document["agents"].get(definition.responsibility),
                      state.version + 1 if changed else state.version, document["agents"].get(definition.responsibility), changed, False)


def apply(policy: AgentPolicyStore, tenant_id: str, caller: Caller, definitions: Sequence[Any], agent_id: str, rung: str, *, reason: str,
          scope: Mapping[str, str] | None = None) -> RungChange:
    """Check as ``plan`` does, then save the change as a new version. A change that leaves the policy as it is writes nothing."""
    planned = plan(policy, tenant_id, caller, definitions, agent_id, rung, reason=reason, scope=scope)
    if not planned.changed:
        return planned
    saved = policy.set_rung(tenant_id, caller, planned.responsibility, rung, reason=reason, scope=planned.scope)
    return RungChange(planned.id, planned.responsibility, planned.scope, rung, planned.ceiling, planned.reason, planned.before_version, planned.before, saved.version,
                      saved.document["agents"].get(planned.responsibility), True, True)
