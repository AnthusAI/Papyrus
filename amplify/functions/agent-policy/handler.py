"""The agent-policy function: the only writer of the agent policy document for a signed-in admin (``papyrus_content.agent_policy.function``).

Configuration comes from the environment the stack sets; the tenant comes from the call's context, built before anything is read.
"""

from __future__ import annotations

import os
from typing import Any

import boto3

from papyrus_content.agent_policy import AgentPolicyStore
from papyrus_content.agent_policy.dynamo_catalogue import DynamoCatalogueTable
from papyrus_content.agent_policy.function import PokeInServices, handle
from papyrus_content.site_store import SiteStore
from papyrus_content.tenant_context import acting_for, build_event_tenant_context


def _policy_store() -> AgentPolicyStore:
    dynamodb = boto3.resource("dynamodb")
    catalogue = DynamoCatalogueTable({
        "SiteDocument": dynamodb.Table(os.environ["SITE_DOCUMENT_TABLE"]),
        "SiteDocumentVersion": dynamodb.Table(os.environ["SITE_DOCUMENT_VERSION_TABLE"]),
    })
    return AgentPolicyStore(SiteStore(boto3.client("s3"), os.environ["MEDIA_BUCKET"], catalogue))


def _poke_in_services(store: AgentPolicyStore, tenant_id: str) -> PokeInServices:
    """What a resume reads and sends with the function's own role: the listener index, one agent's runs through the run index, and the site's wake queue; and, for
    the rung board, the site's registered agent definitions through the Automation tenantId index."""
    from papyrus_content.agent_listeners import ListenerIndex
    from papyrus_content.agent_poke_in import RunLedger
    from papyrus_content.agent_wakes import wake_sender
    from papyrus_content.agent_policy.console_rungs import registered_definitions
    from papyrus_content.graphql_authoring import AUTOMATION_FIELDS, PapyrusGraphQLAuthoringClient

    client = PapyrusGraphQLAuthoringClient(endpoint=os.environ["PAPYRUS_GRAPHQL_ENDPOINT"], tenant_id=tenant_id)
    return PokeInServices(ListenerIndex(store.site_store, tenant_id).document, RunLedger(client, tenant_id), wake_sender(),
                          definitions=lambda: registered_definitions(client.list_tenant_rows("Automation", AUTOMATION_FIELDS)))


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    with acting_for(build_event_tenant_context(event)) as context:
        store = _policy_store()
        return handle(event, store, dict(os.environ), context.tenant_id, _poke_in_services(store, context.tenant_id))
