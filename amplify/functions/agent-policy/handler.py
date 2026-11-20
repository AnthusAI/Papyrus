"""The agent-policy function: the only writer of the agent policy document for a signed-in admin (``papyrus_content.agent_policy.function``).

Configuration comes from the environment the stack sets; a missing variable stops the cold start.
"""

from __future__ import annotations

import os
from typing import Any

import boto3

from papyrus_content.agent_policy import AgentPolicyStore
from papyrus_content.agent_policy.dynamo_catalogue import DynamoCatalogueTable
from papyrus_content.agent_policy.function import handle
from papyrus_content.site_store import SiteStore

_dynamodb = boto3.resource("dynamodb")
_store = AgentPolicyStore(SiteStore(boto3.client("s3"), os.environ["MEDIA_BUCKET"], DynamoCatalogueTable({
    "SiteDocument": _dynamodb.Table(os.environ["SITE_DOCUMENT_TABLE"]),
    "SiteDocumentVersion": _dynamodb.Table(os.environ["SITE_DOCUMENT_VERSION_TABLE"]),
})))


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    return handle(event, _store, dict(os.environ))
