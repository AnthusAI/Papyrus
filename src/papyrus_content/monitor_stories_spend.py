"""Monitor stories under the spend ledger, the site's budget and the unusual-cost flag (PPY-45c2ef).

The daily monitor-stories job runs in the monitoring router, outside the procedure runner, but its paid work goes through the same three things as the
runner's, not a copy of them:

* **The brake before paid work** (``spend_brake.SpendBrake``). The daily plan of a publication asks it before the vector pass (embeddings are paid), and each
  queued step asks it again before it drafts. Halted, the work does not start. At the site's budget it does not start either and waits: the stop names the
  next cycle start, and the cycle's one flag (``spend_stop.raise_cycle_flag``, the same flag the runner's waiting wakes raise) tells the admins. Nothing is
  lost: a candidate that was not drafted is not marked drafted or rejected, so the first daily plan under the budget (the next cycle, or the next morning
  after a person raises the budget with ``papyrus agents set-budget``) plans it again. A ledger or a policy that cannot be read starts nothing.
* **The ledger after paid work** (``spend_ledger.record_run`` through ``unusual_cost.watch_run``). Each run's model calls and cost are added to the site's
  ``ai`` scope, which is what the budget limits, and to the agent's scope, once (a redelivered step adds nothing).
* **The unusual-cost flag** (``unusual_cost.watch_run``). A run whose every call was priced joins its agent's cost history and is judged against it; an unusual
  cost, or one over ``agents.<agent>.budgetUsdPerRun``, raises one flag and stops nothing.

Two agents, because they are two kinds of work whose costs differ by orders of magnitude, and one history for both would hide an unusual run of either:

* ``monitor_stories``: drafting. One run is one queued step (one candidate, a pack or a single item), or, for a router with no story queue, the whole
  in-process drafting of one publication.
* ``monitor_stories_index``: the vector pass of one daily plan (the embeddings of what changed since the last pass).

The site and its policy come from the router publication: its ``tenantId`` (the ledger's site) and its ``siteBucket`` (where the agent policy lives, read as the
runner reads it). A publication that names neither is a site with no tenant, which has no agent policy to read: it is counted in the ledger as its own site,
``publication:<publicationId>``, with no policy, so it gets the default monthly budget (``spend_brake.DEFAULT_BUDGET_USD``), the halt switch and the unusual-cost
flag like any site. A publication that names one and not the other is a mistake in its router entry: its monitor stories do not start and say why.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping

from . import spend_brake, spend_stop, unusual_cost
# The submodules, not the package: the router's zip leaves agent_policy/__init__ out (infra/monitoring/build.py, ROUTER_EXCLUDED).
from .agent_policy.run_gate import PolicyNotLocated, PolicyUnreadable, RunDecision, SiteCatalogue
from .agent_policy.resolve import PolicyState
from .agent_policy.document import fresh as fresh_policy

DRAFTING_RESPONSIBILITY = "monitor_stories"
INDEX_RESPONSIBILITY = "monitor_stories_index"
NOT_LOCATED, POLICY_UNREADABLE = "not_located", "policy_unreadable"
WAITING_STATUS = "waiting"   # the status of a plan or step stopped at the budget: it waits for the next cycle
NOT_STARTED_STATUS = "not_started"   # halted, or the ledger or the policy cannot be read


@dataclass(frozen=True)
class SitePolicy:
    """The site a publication's spend is counted for, and its agent policy as read for this run."""
    tenant_id: str
    state: Any


@dataclass(frozen=True)
class PaidWorkStop:
    """Why paid work does not start: a ``spend_brake.Stop`` code (``halted``, ``budget_reached``, ``spend_unreadable``), or ``not_located`` or
    ``policy_unreadable``. ``due_at`` is when waiting work runs again, for ``budget_reached`` only."""
    reason_code: str
    reason: str
    due_at: str | None = None

    @property
    def status(self) -> str:
        return WAITING_STATUS if self.reason_code == spend_brake.BUDGET_REACHED else NOT_STARTED_STATUS

    def as_line(self) -> dict[str, Any]:
        return {"status": self.status, "reasonCode": self.reason_code, "reason": self.reason, **({"dueAt": self.due_at} if self.due_at else {})}


@dataclass(frozen=True)
class RunSpend:
    """One run's model use, as the ledger counts it."""
    run_id: str
    responsibility: str
    cost_usd: float | None
    calls: int
    unpriced_calls: int

    def as_dict(self) -> dict[str, Any]:
        return {"runId": self.run_id, "responsibility": self.responsibility, "costUsd": self.cost_usd, "calls": self.calls, "unpricedCalls": self.unpriced_calls}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunSpend":
        return cls(str(data["runId"]), str(data["responsibility"]), None if data.get("costUsd") is None else float(data["costUsd"]), int(data.get("calls") or 0),
                   int(data.get("unpricedCalls") or 0))


def drafting_spend(run_id: str, run: Mapping[str, Any]) -> RunSpend:
    """The drafting's model use from a ``draft_monitor_stories`` run. A model with no price makes every call unpriced: such a call is never counted as free."""
    from .ideas import synthesis

    usage = run.get("usage") or {}
    calls = int(usage.get("calls") or 0)
    priced = usage.get("costUsd") is not None and synthesis.PRICES.get(run.get("model") or usage.get("model")) is not None
    return RunSpend(run_id, DRAFTING_RESPONSIBILITY, float(usage["costUsd"]) if priced else None, calls, 0 if priced else calls)


def index_spend(run_id: str, vectors: Mapping[str, Any]) -> RunSpend:
    """The vector pass's model use: its embedding requests and what they cost (priced from the characters embedded, monitoring_vectors.embedding_cost_usd)."""
    return RunSpend(run_id, INDEX_RESPONSIBILITY, float(vectors.get("costUsd") or 0.0), int(vectors.get("embeddingRequests") or 0), 0)


UNTENANTED_SITE_PREFIX = "publication:"


def untenanted_site(publication_id: str) -> SitePolicy:
    """A publication on a site with no tenant: counted as its own site in the ledger, with no saved policy (the default budget, every agent setting unset)."""
    return SitePolicy(f"{UNTENANTED_SITE_PREFIX}{publication_id}", PolicyState(0, fresh_policy()))


def site_policy_from_bucket(s3: Any) -> Callable[[Mapping[str, Any], Any], SitePolicy]:
    """How the Lambda reads a publication's site and policy: the policy document in the publication's ``siteBucket``, through the site's own API, as the
    procedure runner reads it (``PolicyGate.for_site``)."""
    from .agent_policy.store import AgentPolicyStore
    from .site_store import SiteStore

    def read(publication: Mapping[str, Any], client: Any) -> SitePolicy:
        missing = [name for name in ("tenantId", "siteBucket") if not publication.get(name)]
        if len(missing) == 2 and publication.get("publicationId"):
            return untenanted_site(str(publication["publicationId"]))
        if missing:
            raise PolicyNotLocated(f"The router publication {publication.get('publicationId')} names no {' and no '.join(missing)}, so its spend cannot be counted "
                                   "against its site's budget and its monitor stories do not start. Add them to its entry in infra/monitoring/router-config.")
        tenant_id = str(publication["tenantId"])
        try:
            state = AgentPolicyStore(SiteStore(s3, publication["siteBucket"], SiteCatalogue(client))).read(tenant_id)
        except Exception as error:
            raise PolicyUnreadable(f"The agent policy could not be read: {type(error).__name__}: {error}") from error
        return SitePolicy(tenant_id, state)

    return read


class MonitorStoriesSpend:
    """The brake and the ledger for monitor stories. ``table`` is the shared monitoring table (the ledger's home); ``site_policy`` reads a publication's site
    and policy (``site_policy_from_bucket`` in the Lambda)."""

    def __init__(self, table: Any, *, site_policy: Callable[[Mapping[str, Any], Any], SitePolicy], default_budget: Decimal | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.table, self.site_policy, self.clock = table, site_policy, clock
        self.brake = spend_brake.SpendBrake(table, default_budget=default_budget, clock=clock)

    @classmethod
    def from_environment(cls, table: Any) -> "MonitorStoriesSpend":
        import boto3  # provided by the Lambda runtime

        return cls(table, site_policy=site_policy_from_bucket(boto3.client("s3")))

    def stop_before_paid_work(self, publication: Mapping[str, Any], client: Any, responsibility: str) -> tuple[PaidWorkStop | None, SitePolicy | None]:
        """Whether this publication's paid work may start now. At the budget the cycle's one flag is raised (raising it again changes nothing)."""
        try:
            site = self.site_policy(publication, client)
        except PolicyNotLocated as error:
            return PaidWorkStop(NOT_LOCATED, str(error)), None
        except PolicyUnreadable as error:
            return PaidWorkStop(POLICY_UNREADABLE, str(error)), None
        stop = self.brake.stop_for({"tenantId": site.tenant_id}, RunDecision(True, responsibility, state=site.state, paid=True))
        if stop is None:
            return None, site
        if stop.reason_code == spend_brake.BUDGET_REACHED:
            spend_stop.raise_cycle_flag(client, stop)
        return PaidWorkStop(stop.reason_code, stop.reason, stop.due_at), site

    def count(self, client: Any, site: SitePolicy, spend: RunSpend) -> dict[str, Any] | None:
        """Judge one finished run's cost against its agent's history, flag it when it is unusual or over the owner's per-run budget, and add it to the ledger,
        once. None for a run that made no model call."""
        counted = unusual_cost.spend_for_run(tenant_id=site.tenant_id, responsibility=spend.responsibility, document=site.state.document, cost_usd=spend.cost_usd,
                                             calls=spend.calls, unpriced_calls=spend.unpriced_calls)
        if counted is None:
            return None
        return unusual_cost.watch_run(self.table, client, {"runId": spend.run_id, "spend": counted}, moment=self.clock())
