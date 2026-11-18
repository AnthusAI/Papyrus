"""Passing a stream batch to the change feed from a table's existing reader (PPY-9b9e64, slice B3).

A DynamoDB stream should have at most two readers. Where a table already has two (the Reference table's word index and home page, the Message table's console
responder, Slack delivery and home page), the change feed does not become a third: the reader that stays on the stream hands its batch to the feed function and
reports what the feed could not do. The feed receives the very records the reader got, so it cannot tell this from a mapping of its own.

``PAPYRUS_CHANGE_FEED_FUNCTION`` names the feed function, and ``PAPYRUS_CHANGE_FEED_RELAY_STREAMS`` lists the streams this reader hands over (a reader whose function
reads two streams hands over only the table whose feed sits behind it). The stack sets it on the carrying reader only when the site's ``agents`` stack, which holds the feed,
is deployed with it, and the invoke of a function that does not exist yet is the same absence: a site's first deploy leaves that stack out (amplify/agents/stack.ts), the variable is absent, and there is no feed to hand a batch to.
This file has no imports of its own beyond the standard library and boto3, so a reader's small bundle can carry it alone.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Mapping

FUNCTION_ENVIRONMENT = "PAPYRUS_CHANGE_FEED_FUNCTION"
STREAMS_ENVIRONMENT = "PAPYRUS_CHANGE_FEED_RELAY_STREAMS"   # a JSON list of the stream ARNs this reader hands over (one function may read several streams)


def _invoke(function_name: str, payload: bytes) -> dict[str, Any]:
    import boto3

    client = boto3.client("lambda")
    try:
        answer = client.invoke(FunctionName=function_name, InvocationType="RequestResponse", Payload=payload)
    except client.exceptions.ResourceNotFoundException:
        # The reader's own stack can be updated a few seconds before the stack that holds the feed creates the function, once, in the release that adds it.
        # There are no listeners yet either (the deploy writes the listener index after the stacks), so there is nobody to wake.
        return {}
    body = json.loads(answer["Payload"].read() or b"{}")
    if answer.get("FunctionError"):
        raise RuntimeError(f"the change feed failed: {body.get('errorType')}: {body.get('errorMessage')}")
    return body


def relay(event: Mapping[str, Any], *, environment: Mapping[str, str] | None = None, invoke: Callable[[str, bytes], dict[str, Any]] | None = None) -> list[dict[str, str]]:
    """Gives the feed this batch and returns the records it reports as failed (``batchItemFailures``), to be merged into the reader's own.
    A feed that fails whole raises, so the reader's batch is retried; the feed's wake keys are the same on the retry, so nothing starts twice."""
    environment = environment if environment is not None else os.environ
    name = (environment.get(FUNCTION_ENVIRONMENT) or "").strip()
    streams = set(json.loads(environment.get(STREAMS_ENVIRONMENT) or "[]"))
    records = [record for record in event.get("Records") or [] if record.get("eventSourceARN") in streams]
    if not name or not records:
        return []
    answer = (invoke or _invoke)(name, json.dumps({"Records": records}, default=str).encode("utf-8"))
    return list(answer.get("batchItemFailures") or [])
