"""The runner reads the policy before it starts a run (PPY-c8175e, slice E1 follow-up).

``PolicyGate.decide`` answers one wake: may a run start, and under which policy version and rung. Four things hold:

* **An automation is adopted before it is enforced.** Its ``Automation`` record names a ``responsibility``, set by a person with
  ``papyrus automations adopt``; nothing here infers one. An automation with none is ``not_adopted``: nothing starts.
* **A responsibility the site's policy does not name is ``off``** (E1), and an ``off`` or paused one starts nothing. There is no
  default that starts a run when the policy says nothing.
* **The policy is read at the start of every run**, the live version only: one get of the catalogue row, one get of the version
  row, one read of the body from S3 (``SiteStore``). A policy that cannot be read raises ``PolicyUnreadable``; the runner records the
  run as failed. Nothing starts as before.
* **The engine's own follow-ups are not an agent's wake** (``engine_follow_ups.py``): a soft review's deadline wake starts with no adopted
  automation and no rung; only the site's pause stops it.
* **A person's own command is not an agent's wake.** ``PersonStart`` is the gate for a run a person starts in their own session
  (``papyrus stories localize``): a person's action is never limited by an agent's rung (architecture section 5.4). It records no
  responsibility, rung or policy version, because none applied.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .resolve import decide_start
from .store import AgentPolicyStore

SITE_DOCUMENT_FIELDS = "id tenantId kind currentVersion s3Key sha256 schemaVersion updatedBy updatedAt"
SITE_DOCUMENT_VERSION_FIELDS = "id tenantId documentId version s3Key sha256 createdBy createdAt note"

NOT_ADOPTED, RUNG_OFF, PAUSED = "not_adopted", "rung_off", "paused"


class PolicyUnreadable(Exception):
    """The site's policy could not be read, so no decision can be made. The run does not start."""


class PolicyNotLocated(PolicyUnreadable):
    """The request names no site policy (no tenant id or no site bucket), so there is nowhere to read one."""


@dataclass(frozen=True)
class RunDecision:
    start: bool
    responsibility: str | None = None
    rung: str | None = None
    policy_version: int | None = None
    reason_code: str | None = None     # not_adopted, rung_off or paused when nothing starts
    reason: str | None = None          # the same in words, for the run record and the person reading it
    state: Any = field(default=None, compare=False, repr=False)   # the policy as read for this run: the run's gate answers come from it
    paid: bool | None = None           # the registered definition's `paid`; None when no definition says, which the spend brake counts as paid (PPY-9376f8)

    def run_fields(self) -> dict[str, Any]:
        """What the run's record carries, started or skipped. Absent for a person's own run."""
        if self.responsibility is None and self.rung is None:
            return {}
        return {"responsibility": self.responsibility, "rung": self.rung, "policyVersion": self.policy_version}


def registered_paid(row: dict[str, Any]) -> bool | None:
    """Whether the automation's registered definition calls a paid model (``paid`` in agent_definitions), or None when it has no registered definition."""
    definition = row.get("definition")
    if isinstance(definition, str):
        try:
            definition = json.loads(definition)
        except ValueError:
            return None
    paid = definition.get("paid") if isinstance(definition, dict) else None
    return paid if isinstance(paid, bool) else None


class Gate(Protocol):
    def decide(self, request: dict) -> RunDecision: ...


class UnlocatedPolicy:
    """The gate for a request that does not say where the site's policy is: it refuses, so the runner records the refusal on the run."""

    def decide(self, request: dict) -> RunDecision:
        raise PolicyNotLocated("the request names no site policy: tenantId and siteBucket are required, so no run starts without one")


class PersonStart:
    """A run a person started in their own session. Never limited by an agent's rung."""

    def decide(self, request: dict) -> RunDecision:
        return RunDecision(True)


class SiteCatalogue:
    """The read side of the site store's catalogue over the site's API: ``get(model, id)`` for ``SiteDocument`` and ``SiteDocumentVersion``."""

    QUERIES = {"SiteDocument": ("getSiteDocument", SITE_DOCUMENT_FIELDS), "SiteDocumentVersion": ("getSiteDocumentVersion", SITE_DOCUMENT_VERSION_FIELDS)}

    def __init__(self, client):
        self._client = client

    def get(self, model: str, row_id: str) -> dict[str, Any] | None:
        field, fields = self.QUERIES[model]
        query = f"query {field[0].upper() + field[1:]}($id: ID!) {{ {field}(id: $id) {{ {fields} }} }}"
        return (self._client.graphql(query, {"id": row_id}) or {}).get(field)


class PolicyGate:
    """Decides from the site's own records. ``client`` is the site's GraphQL client, ``s3`` an S3 client, ``bucket`` the site's bucket."""

    def __init__(self, client, *, policy: AgentPolicyStore, tenant_id: str):
        self._client, self._policy, self._tenant_id = client, policy, tenant_id

    @classmethod
    def for_site(cls, client, *, s3, bucket: str, tenant_id: str) -> "PolicyGate":
        from papyrus_content.site_store import SiteStore

        return cls(client, policy=AgentPolicyStore(SiteStore(s3, bucket, SiteCatalogue(client))), tenant_id=tenant_id)

    def decide(self, request: dict) -> RunDecision:
        from ..engine_follow_ups import engine_follow_up_of

        if engine_follow_up_of(request):
            return self._decide_engine_follow_up()
        automation_id = (request.get("trigger") or {}).get("automationId")
        if not automation_id:
            return RunDecision(False, reason_code=NOT_ADOPTED, reason="This run names no automation, so no responsibility is adopted for it.")
        row = self._client.get_record("Automation", automation_id)
        responsibility = (row or {}).get("responsibility")
        if not responsibility:
            what = "does not exist" if row is None else "has not been adopted onto a responsibility"
            return RunDecision(False, reason_code=NOT_ADOPTED, reason=f"Automation {automation_id} {what}. Adopt it with: papyrus automations adopt.")
        try:
            state = self._policy.read(self._tenant_id)
        except Exception as error:
            raise PolicyUnreadable(f"The agent policy could not be read: {type(error).__name__}: {error}") from error
        decision = decide_start(state, responsibility, {})
        if decision.start:
            return RunDecision(True, responsibility, decision.rung, decision.policy_version, state=state, paid=registered_paid(row))
        code = PAUSED if decision.reason_code == "paused" else RUNG_OFF
        return RunDecision(False, responsibility, decision.rung, decision.policy_version, code, decision.reason)

    def _decide_engine_follow_up(self) -> RunDecision:
        """One of the engine's own follow-ups (engine_follow_ups.py): no agent is adopted for it and no rung applies; only the site's pause stops it."""
        try:
            state = self._policy.read(self._tenant_id)
        except Exception as error:
            raise PolicyUnreadable(f"The agent policy could not be read: {type(error).__name__}: {error}") from error
        site = state.document.get("site", {})
        if site.get("paused"):
            return RunDecision(False, reason_code=PAUSED, reason=f"The site is paused: {site.get('pausedReason')}")
        return RunDecision(True)
