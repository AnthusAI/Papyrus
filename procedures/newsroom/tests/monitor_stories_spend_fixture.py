"""The spend brake and ledger the monitor-stories tests run under (src/papyrus_content/monitor_stories_spend.py): the real brake and the real ledger code over a
fake monitoring table, and a site policy read from memory instead of the site's bucket. A test that is not about spend gets a site far below its budget."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from papyrus_content.agent_policy.resolve import PolicyState
from papyrus_content.monitor_stories_spend import MonitorStoriesSpend, SitePolicy
from papyrus_content.spend_brake_test import HaltableTable

TENANT = "example-tenant"
EMPTY_POLICY = {"schemaVersion": 1, "site": {}, "agents": {}}


class SiteOfRecord:
    """One site's policy, which a scenario may change between runs, read as the Lambda reads it: once per brake check."""

    def __init__(self, document: dict | None = None, *, tenant_id: str = TENANT) -> None:
        self.document, self.tenant_id, self.reads = dict(document or EMPTY_POLICY), tenant_id, 0

    def __call__(self, publication, client) -> SitePolicy:
        self.reads += 1
        return SitePolicy(self.tenant_id, PolicyState(1, self.document))


def monitor_stories_spend(*, ledger=None, site=None, budget: Decimal = Decimal("100"), clock=None) -> MonitorStoriesSpend:
    return MonitorStoriesSpend(ledger if ledger is not None else HaltableTable(), site_policy=site or SiteOfRecord(), default_budget=budget,
                               clock=clock or (lambda: datetime.now(timezone.utc)))
