"""The Item change feed: a DynamoDB stream consumer on the Item table that puts wakes on the site's agent wake queue (PPY-8a374e).

All the logic is ``papyrus_content.item_change_feed``. This file decodes nothing itself: it builds the collaborators with the function's own role: the
site's listener index (``agent_listeners.ListenerIndex`` over the site store: one point read of the live version, the body from S3 only when the version
moved) and the site's wake queue (``agent_wakes.wake_sender``). Nothing here lists a table.

A batch is processed in order. A record whose wakes cannot all be put on the queue is reported as failed, and Lambda retries from it; every wake key is the same on
the retry, so what was already sent starts nothing twice. Records that are no change (a version marked superseded, a card's counts refreshed) cost nothing.
"""
from __future__ import annotations

import json
import os
from typing import Any

_INDEX: Any = None   # held across invocations of one container: the listener index re-reads the body only when the live version moves


def listener_index(site) -> Any:
    global _INDEX
    if _INDEX is None:
        import boto3

        from papyrus_content.agent_listeners import ListenerIndex
        from papyrus_content.agent_policy.run_gate import SiteCatalogue
        from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
        from papyrus_content.site_store import SiteStore

        if not (site.tenant_id and site.site_bucket):
            raise RuntimeError("the change feed needs the site's tenant id and bucket (PAPYRUS_TENANT_ID, PAPYRUS_SITE_BUCKET) to find who listens")
        os.environ.setdefault("PAPYRUS_GRAPHQL_AUTH", "iam")   # the function's own role signs the calls
        client = PapyrusGraphQLAuthoringClient(endpoint=site.appsync_endpoint)
        _INDEX = ListenerIndex(SiteStore(boto3.client("s3"), site.site_bucket, SiteCatalogue(client)), site.tenant_id)
    return _INDEX


def handler(event: dict[str, Any], context: Any = None, *, index=None, send=None, environment=None) -> dict[str, Any]:
    from papyrus_content import item_change_feed
    from papyrus_content.agent_wakes import wake_sender
    from papyrus_content.localize.dispatch import decode_image

    site = item_change_feed.Site.from_environment(environment if environment is not None else os.environ)
    result = item_change_feed.handle(event.get("Records", []), decode=decode_image, listeners=lambda: (index or listener_index(site)).document(),
                                     send=send or wake_sender(), site=site)
    print(json.dumps({"event": "papyrus_item_change_feed", "records": len(event.get("Records", [])), "wakesSent": result["wakesSent"], "failed": len(result["batchItemFailures"])}))
    return {"batchItemFailures": result["batchItemFailures"]}
