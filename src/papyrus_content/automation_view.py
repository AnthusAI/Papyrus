"""The console's Automation page reads through this function: `automationOverview` for editors and admins, read only (PPY-9ff95b).

The Lambda that calls this holds `dynamodb:GetItem` and `dynamodb:Query` on the monitoring table and
`appsync:GraphQL` on two fields of its own site's API (`listAutomations`, `getProcedureRun`). It writes nothing.
It returns the automation records with their router link and recent runs (src/papyrus_content/automations.py).
Trigger rows are read only for the publication this site is, so an editor cannot read another publication's runs.
Errors are states, never stack traces; the cause goes to the log by type only.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from .automations import DEFAULT_RUN_LIMIT, automation_overview, monitoring_reader_from_environment

LOG = logging.getLogger(__name__)
EDITOR_GROUPS = frozenset({"editor", "admin"})


def default_client_factory(env):
    def factory():
        os.environ.setdefault("PAPYRUS_GRAPHQL_AUTH", "iam")   # the function's own role signs the call
        from .graphql_authoring import PapyrusGraphQLAuthoringClient
        return PapyrusGraphQLAuthoringClient(endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"))
    return factory


def handle(event: dict, *, env=None, reader_factory=None, client_factory=None, now: float | None = None) -> dict:
    """AppSync resolver entry: `automationOverview(automationId)`."""
    env = os.environ if env is None else env
    groups = (event.get("identity") or {}).get("groups")
    groups = [group for group in groups if isinstance(group, str)] if isinstance(groups, list) else []
    if not set(groups) & EDITOR_GROUPS:
        return {"error": "forbidden"}
    automation_id = (event.get("arguments") or {}).get("automationId") or None
    if automation_id is not None and not isinstance(automation_id, str):
        return {"error": "bad_request"}
    try:
        client = (client_factory or default_client_factory(env))()
        try:
            reader = (reader_factory or (lambda: monitoring_reader_from_environment(env)))()
        except Exception as error:   # records still list without the monitoring table
            LOG.error("monitoring table unavailable: %s", type(error).__name__)
            reader = None
        stamp = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return automation_overview(client, reader=reader, limit=DEFAULT_RUN_LIMIT, automation_id=automation_id,
                                   site_endpoint=env.get("PAPYRUS_GRAPHQL_ENDPOINT"), now=stamp)
    except Exception as error:   # the browser gets a state; the cause goes to the log by type only
        LOG.error("automation overview failed: %s", type(error).__name__)
        return {"state": "unavailable"}
