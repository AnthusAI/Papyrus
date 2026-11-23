"""Read and change the agent policy document (PPY-51ea61).

The document is the ``agents`` kind of the site store, so it keeps that store's guarantees: the body is an S3 object, the catalogue
holds only pointers, a save that stops half way is never live, and every version stays. This module adds the rules of this document:

* **Only an admin who is a person changes it.** An agent is ``blocked`` at every rung; an editor is ``not_authorized``. Reading is open
  to anyone who may read the site, because the runner reads it to decide each wake.
* **Every change carries a reason**, which is the version's ``note``; the version row holds who and when. A change that leaves the
  document as it is writes nothing.
* **A change is checked against the version it started from.** If another admin saved first, nothing is written (``stale_version``).
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from papyrus_content.images.handlers import Caller
from papyrus_content.site_store import SiteSaveConflict, SiteStore

from .document import PAUSE_DETAILS, PolicyError, check_rung, check_scope, fresh, scope_of, validate_agent, validate_document
from .resolve import PolicyState

KIND = "agents"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

SITE_FIELDS = ("quietWindow", "coalescing", "budget", "tiers")
AGENT_FIELDS = ("loopLimit", "budgetUsdPerRun")


def may_change(caller: Caller) -> None:
    if caller.kind == "agent":
        raise PolicyError("blocked", "An agent may never change the agent policy, at any rung.")
    if not caller.is_admin:
        raise PolicyError("not_authorized", "Only an admin changes the agent policy.")


class AgentPolicyStore:
    def __init__(self, site_store: SiteStore):
        self._store = site_store

    @property
    def site_store(self) -> SiteStore:
        """The site store the policy is a kind of: the listener index is another kind of the same store."""
        return self._store

    def read(self, tenant_id: str) -> PolicyState:
        """The live policy. A site that has never saved one is version 0 with nothing named, so every agent is at ``off``."""
        version = self._store.current_version(tenant_id, KIND)
        if version == 0:
            return PolicyState(0, fresh())
        return PolicyState(version, validate_document(self._store.read_version(tenant_id, KIND, version)))

    def version_record(self, tenant_id: str, version: int) -> dict[str, Any]:
        """Who (``by``), when (``at``) and why (``reason``) one version was saved."""
        row = self._store.version_record(tenant_id, KIND, version)
        return {"version": version, "by": row.get("createdBy"), "at": row.get("createdAt"), "reason": row.get("note")}

    def prepare(self, tenant_id: str, caller: Caller, reason: str, edit: Callable[[dict], None]) -> tuple[PolicyState, dict]:
        """What ``change`` would save, written nowhere: the live state and the document after ``edit``, checked as ``change`` checks it."""
        may_change(caller)
        if not isinstance(reason, str) or not reason.strip():
            raise PolicyError("invalid_input", "A policy change needs a reason.")
        state = self.read(tenant_id)
        document = copy.deepcopy(state.document)
        edit(document)
        validate_document(document)
        return state, document

    def change(self, tenant_id: str, caller: Caller, reason: str, edit: Callable[[dict], None]) -> PolicyState:
        """Apply ``edit`` to a copy of the live document and save it as the next version. Returns the live state afterwards."""
        state, document = self.prepare(tenant_id, caller, reason, edit)
        if document == state.document:
            return state
        try:
            version = self._store.save(tenant_id, KIND, document, caller.subject, note=reason.strip(), expected_version=state.version)
        except SiteSaveConflict as error:
            raise PolicyError("stale_version", "The policy changed while this change was being made; read it again.") from error
        return PolicyState(version, document)

    # --- the changes people make -----------------------------------------------------------------------------------------------------

    @staticmethod
    def rung_edit(responsibility: str, rung: str, scope: Mapping[str, str] | None = None) -> Callable[[dict], None]:
        """The edit that sets an agent's rung, or with ``scope`` the rung of the override for exactly that scope."""
        check_rung(rung, "rung")
        scope = check_scope(scope, "scope") if scope else None

        def edit(document: dict) -> None:
            entry = document["agents"].setdefault(responsibility, {"rung": "off"})
            if scope is None:
                entry["rung"] = rung
                return
            overrides = entry.setdefault("overrides", [])
            for override in overrides:
                if scope_of(override) == scope:
                    override["rung"] = rung
                    return
            overrides.append({**scope, "rung": rung})

        return edit

    def set_rung(self, tenant_id: str, caller: Caller, responsibility: str, rung: str, *, reason: str,
                 scope: Mapping[str, str] | None = None) -> PolicyState:
        """Set an agent's rung, or with ``scope`` the rung of the override for exactly that scope. Raising and lowering are the same operation."""
        return self.change(tenant_id, caller, reason, self.rung_edit(responsibility, rung, scope))

    def remove_override(self, tenant_id: str, caller: Caller, responsibility: str, scope: Mapping[str, str], *, reason: str) -> PolicyState:
        scope = check_scope(scope, "scope")

        def edit(document: dict) -> None:
            entry = document["agents"].get(responsibility)
            if entry is None or not any(scope_of(o) == scope for o in entry.get("overrides", [])):
                raise PolicyError("invalid_input", f"{responsibility} has no override for that scope.")
            entry["overrides"] = [o for o in entry["overrides"] if scope_of(o) != scope]
            if not entry["overrides"]:
                del entry["overrides"]

        return self.change(tenant_id, caller, reason, edit)

    def pause(self, tenant_id: str, caller: Caller, *, reason: str, responsibility: str | None = None, at: str | None = None) -> PolicyState:
        """Pause one agent, or with no ``responsibility`` the whole site. The reason is shown on every run it stops. The pause keeps when it began
        (``pausedAt``) and who made it (``pausedBy``); pausing again what is already paused changes the reason and keeps when it began, so a resume still
        catches up everything the pause stopped."""
        moment = at or utc_now()

        def edit(document: dict) -> None:
            target = document["site"] if responsibility is None else document["agents"].setdefault(responsibility, {"rung": "off"})
            began = target.get("pausedAt") if target.get("paused") else None
            target["paused"], target["pausedReason"] = True, reason.strip()
            target["pausedAt"], target["pausedBy"] = began or moment, (target.get("pausedBy") if began else None) or caller.subject or "a person"

        return self.change(tenant_id, caller, reason, edit)

    def resume(self, tenant_id: str, caller: Caller, *, reason: str, responsibility: str | None = None) -> PolicyState:
        """Lift a pause. Ticks skipped while paused stay skipped; nothing is replayed here (``agent_poke_in.resume`` sends the change wakes the pause stopped,
        once each). An agent the document does not name is refused by name."""
        def edit(document: dict) -> None:
            if responsibility is not None and responsibility not in document["agents"]:
                raise PolicyError("invalid_input", f"{responsibility} is not named in the agent policy, so there is nothing to resume.")
            target = document["site"] if responsibility is None else document["agents"][responsibility]
            for held in ("paused", "pausedReason", *PAUSE_DETAILS):
                target.pop(held, None)

        return self.change(tenant_id, caller, reason, edit)

    def set_value(self, tenant_id: str, caller: Caller, field: str, value: Any, *, reason: str, responsibility: str | None = None) -> PolicyState:
        """Set the quiet window, the budget or the tiers (site), or an agent's loop limit or per-run budget."""
        allowed = SITE_FIELDS if responsibility is None else AGENT_FIELDS
        if field not in allowed:
            raise PolicyError("invalid_input", f"{'The site' if responsibility is None else responsibility} holds: {', '.join(allowed)}.")

        def edit(document: dict) -> None:
            target = document["site"] if responsibility is None else document["agents"].setdefault(responsibility, {"rung": "off"})
            target[field] = value

        return self.change(tenant_id, caller, reason, edit)
