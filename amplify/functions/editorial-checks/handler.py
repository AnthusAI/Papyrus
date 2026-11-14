"""The editorial-checks function: routes its GraphQL fields to papyrus_content.editorial_checks."""

from __future__ import annotations

from typing import Any

from papyrus_content.editorial_checks import GraphQLEditorialStore, Services, event_field_name, handle, load_provider_keys
from papyrus_content.tenant_context import acting_for, build_event_tenant_context
from papyrus_cost_usage import SiteUsage

# Amplify passes secrets to Python functions as placeholders; resolve them once per cold start.
load_provider_keys()
# The site's Prospectus usage sender (amplify/cost-attribution.ts sets its environment). A partial setup fails the cold start.
USAGE = SiteUsage.from_environment()


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    try:
        context = build_event_tenant_context(event)   # one context per call; a shared stack refuses before any read
        with acting_for(context):
            store = GraphQLEditorialStore(tenant_id=context.tenant_id)
            return handle(event_field_name(event), event.get("arguments") or {}, Services(store=store, usage=USAGE))
    finally:
        # A frozen Lambda loses what is only in memory: send before the invocation returns. Never raises.
        USAGE.flush()
