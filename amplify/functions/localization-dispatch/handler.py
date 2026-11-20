"""The translate-on-publish dispatcher: a DynamoDB stream consumer on the LocalizationRequest table (docs/story-translation-procedure.md).

All the logic is ``papyrus_content.localize.dispatch``; this file decodes the stream records and builds the collaborators with the function's own role:
the site's authoring client, the monitoring table (as the automation-view function reads and writes it), the site's wake queue (where a procedure start is put) and the content-actions
function. A batch whose handling fails reports every record as failed, so Lambda retries it (the stream's retry limit and the function's dead letter queue
follow); the work itself is idempotent (a claim per record, a publish that finds the translation live).
"""
from __future__ import annotations

import json
import os
from typing import Any

from papyrus_content.localize.dispatch import decode_image, handle_changes

CONTENT_ACTIONS_ENV = "PAPYRUS_CONTENT_ACTIONS_FUNCTION"


def invoke_content_actions(task: dict[str, Any]) -> None:
    import boto3

    boto3.client("lambda").invoke(FunctionName=os.environ[CONTENT_ACTIONS_ENV], InvocationType="Event",
                                  Payload=json.dumps({"projectionTask": task}).encode("utf-8"))


def handler(event: dict[str, Any], context: Any = None, *, client=None, table=None, runner=None, publisher=None) -> dict[str, Any]:
    from papyrus_content.automations import MonitoringReader, MonitoringWriter, monitoring_table_from_environment
    from papyrus_content.agent_wakes import wake_sender
    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient

    images = [{"old": decode_image(record["dynamodb"].get("OldImage")), "new": decode_image(record["dynamodb"].get("NewImage"))}
              for record in event.get("Records", []) if record.get("eventName") in ("INSERT", "MODIFY")]
    if not images:
        return {"batchItemFailures": []}
    os.environ.setdefault("PAPYRUS_GRAPHQL_AUTH", "iam")   # the function's own role signs the calls
    endpoint = os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT")
    table = table if table is not None else monitoring_table_from_environment(os.environ)
    try:
        handle_changes(images, client or PapyrusGraphQLAuthoringClient(endpoint=endpoint),
                       reader=MonitoringReader(table) if table is not None else None, writer=MonitoringWriter(table) if table is not None else None,
                       invoke=runner or wake_sender(), invoke_publish=publisher or invoke_content_actions,
                       site_endpoint=endpoint)
    except Exception as error:
        print(json.dumps({"event": "papyrus_localization_dispatch_failed", "error": f"{type(error).__name__}: {error}"[:500]}))
        return {"batchItemFailures": [{"itemIdentifier": record["dynamodb"]["SequenceNumber"]} for record in event["Records"]]}
    return {"batchItemFailures": []}
