"""The agent-policy function: the only writer of the agent policy document for a signed-in admin (``papyrus_content.agent_policy.function``).

Configuration comes from the environment the stack sets; the tenant comes from the call's context, built before anything is read.
"""

from __future__ import annotations

import os
from typing import Any

import boto3

from papyrus_content.agent_policy import AgentPolicyStore
from papyrus_content.agent_policy.dynamo_catalogue import DynamoCatalogueTable
from papyrus_content.agent_policy.function import handle
from papyrus_content.site_store import SiteStore
from papyrus_content.tenant_context import acting_for, build_event_tenant_context


def _policy_store() -> AgentPolicyStore:
    dynamodb = boto3.resource("dynamodb")
    catalogue = DynamoCatalogueTable({
        "SiteDocument": dynamodb.Table(os.environ["SITE_DOCUMENT_TABLE"]),
        "SiteDocumentVersion": dynamodb.Table(os.environ["SITE_DOCUMENT_VERSION_TABLE"]),
    })
    return AgentPolicyStore(SiteStore(boto3.client("s3"), os.environ["MEDIA_BUCKET"], catalogue))


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    with acting_for(build_event_tenant_context(event)) as context:
        return handle(event, _policy_store(), dict(os.environ), context.tenant_id)
