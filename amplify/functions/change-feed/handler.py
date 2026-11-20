"""The change feed for Reference, ReviewRequest, Message, LocalizationRequest and Delivery (PPY-9b9e64).

All the logic is ``papyrus_content.change_feeds``; this builds its collaborators with the function's own role, as the Item feed's handler does: the site's listener
index (one point read of the live version, the body from S3 only when the version moved), the site's wake queue, and one point read of a Message thread by id,
made only when some agent listens for a posted Message. Nothing here lists a table.

The records come from this function's own stream mappings or, for a table that already has two stream readers, from the reader that stays on the stream and
hands its batch over (``papyrus_content.change_feed_relay``).
"""
from __future__ import annotations

import json
import os
from typing import Any

_INDEX: Any = None      # held across invocations of one container: the listener index re-reads the body only when the live version moves
_CLIENT: Any = None


def _client(site) -> Any:
    global _CLIENT
    if _CLIENT is None:
        from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient

        os.environ.setdefault("PAPYRUS_GRAPHQL_AUTH", "iam")   # the function's own role signs the calls
        _CLIENT = PapyrusGraphQLAuthoringClient(endpoint=site.appsync_endpoint)
    return _CLIENT


def listener_index(site) -> Any:
    global _INDEX
    if _INDEX is None:
        import boto3

        from papyrus_content.agent_listeners import ListenerIndex
        from papyrus_content.agent_policy.run_gate import SiteCatalogue
        from papyrus_content.site_store import SiteStore

        if not (site.tenant_id and site.site_bucket):
            raise RuntimeError("the change feed needs the site's tenant id and bucket (PAPYRUS_TENANT_ID, PAPYRUS_SITE_BUCKET) to find who listens")
        _INDEX = ListenerIndex(SiteStore(boto3.client("s3"), site.site_bucket, SiteCatalogue(_client(site))), site.tenant_id)
    return _INDEX


def handler(event: dict[str, Any], context: Any = None, *, index=None, send=None, environment=None, thread_of=None) -> dict[str, Any]:
    from papyrus_content import change_feeds, item_change_feed
    from papyrus_content.agent_wakes import wake_sender
    from papyrus_content.localize.dispatch import decode_image

    env = environment if environment is not None else os.environ
    site = item_change_feed.Site.from_environment(env)
    result = change_feeds.handle(event.get("Records", []), streams=change_feeds.Streams.from_environment(env), decode=decode_image,
                                 listeners=lambda: (index or listener_index(site)).document(), send=send or wake_sender(), site=site,
                                 thread_of=thread_of or (lambda thread_id: _client(site).get_record("MessageThread", thread_id)))
    print(json.dumps({"event": "papyrus_change_feed", "records": len(event.get("Records", [])), "wakesSent": result["wakesSent"], "failed": len(result["batchItemFailures"])}))
    return {"batchItemFailures": result["batchItemFailures"]}
