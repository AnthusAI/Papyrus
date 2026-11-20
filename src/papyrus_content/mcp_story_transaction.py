"""Conditional Item version persistence for the agent draft operation."""
from __future__ import annotations
import json
from decimal import Decimal
from typing import Any
from boto3.dynamodb.types import TypeSerializer


def persist_agent_story_version(client: Any, table: str, dynamodb: Any, lineage: str, expected: str,
                                expected_updated_at: str, record: dict) -> None:
    if not table or not expected_updated_at:
        raise ValueError("A current version revision and Item table are required.")
    # Until the media rows can join the same transaction, do not create a draft
    # whose body requires carry-forward, and avoid any post-commit media work.
    envelope = record.get("bodyIr") or {}
    if isinstance(envelope, str):
        envelope = json.loads(envelope)
    if ((envelope.get("papyrus") or {}).get("images") or {}):
        raise ValueError("Drafts with images are not yet available through this tool.")
    prepared = client._prepared_payload("Item", record)
    tenant = client.tenant_id
    prepared.update({"__typename": "Item", "createdAt": record["versionCreatedAt"], "updatedAt": record["versionCreatedAt"]})
    serializer = TypeSerializer()
    def dynamo_safe(value):
        if isinstance(value, float): return Decimal(str(value))
        if isinstance(value, list): return [dynamo_safe(item) for item in value]
        if isinstance(value, dict): return {key: dynamo_safe(item) for key, item in value.items()}
        return value
    encode = lambda obj: {key: serializer.serialize(dynamo_safe(value)) for key, value in obj.items()}
    names = {"#state": "versionState", "#lineage": "lineageId", "#updated": "updatedAt", "#tenant": "tenantId"}
    values = {":current": "current", ":superseded": "superseded", ":lineage": lineage, ":updated": expected_updated_at, ":now": record["versionCreatedAt"]}
    tenant_condition = "attribute_not_exists(#tenant)"
    if tenant:
        values[":tenant"] = tenant
        tenant_condition = "#tenant = :tenant"
    try:
        dynamodb.transact_write_items(TransactItems=[
            {"Update": {"TableName": table, "Key": encode({"id": expected}), "UpdateExpression": "SET #state = :superseded, #updated = :now", "ConditionExpression": f"#state = :current AND #lineage = :lineage AND #updated = :updated AND {tenant_condition}", "ExpressionAttributeNames": names, "ExpressionAttributeValues": encode(values)}},
            {"Put": {"TableName": table, "Item": encode(prepared), "ConditionExpression": "attribute_not_exists(id)"}},
        ])
    except Exception as error:
        response = getattr(error, "response", {})
        reasons = response.get("CancellationReasons", [])
        if response.get("Error", {}).get("Code") == "TransactionCanceledException" and any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons):
            raise ValueError("stale_version: The Story changed; reload it before saving.") from error
        raise
