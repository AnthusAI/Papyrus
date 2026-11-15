"""The concept name writer: a DynamoDB stream consumer on the SemanticNode table (docs/multilingual-labels.md).

All the logic is ``papyrus_content.entity_labels.stream``; this file decodes the stream records and builds the site's authoring client with the function's
own role. A batch whose handling fails reports every record as failed, so Lambda retries it; the work is idempotent (a sync of an unchanged concept writes
nothing).
"""
from __future__ import annotations

import json
import os
from typing import Any

from papyrus_content.entity_labels.stream import events_from_stream, handle_changes


def handler(event: dict[str, Any], context: Any = None, *, client=None) -> dict[str, Any]:
    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient

    events = events_from_stream(event.get("Records", []))
    if not events:
        return {"batchItemFailures": []}
    os.environ.setdefault("PAPYRUS_GRAPHQL_AUTH", "iam")   # the function's own role signs the calls
    try:
        totals = handle_changes(events, client or PapyrusGraphQLAuthoringClient(endpoint=os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT")))
    except Exception as error:
        print(json.dumps({"event": "papyrus_concept_label_sync_failed", "error": f"{type(error).__name__}: {error}"[:500]}))
        return {"batchItemFailures": [{"itemIdentifier": record["dynamodb"]["SequenceNumber"]} for record in event["Records"]]}
    if totals["nodes"] or totals["deleted"]:
        print(json.dumps({"event": "papyrus_concept_label_sync", **totals}))
    return {"batchItemFailures": []}
