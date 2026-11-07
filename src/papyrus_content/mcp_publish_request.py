"""Request existing human publication approval without publishing the Story."""
from __future__ import annotations
from typing import Any
from boto3.dynamodb.types import TypeSerializer
from . import publish_gate
from .publishing import DryRunClient, PublishError, publish_item
from .publish_commands import refuse_placeholder_slug
from .projection.runtime import render_preflight


class _ConditionalReviewClient:
    """Only the gate's ReviewRequest creation can write through this proxy."""
    def __init__(self, client, dynamodb, item_table: str, review_table: str, item: dict):
        self.client, self.dynamodb, self.item_table, self.review_table, self.item = client, dynamodb, item_table, review_table, item
        self.created = None

    def __getattr__(self, name):
        if name in {"get_record", "list_records", "list_by_index"}: return getattr(self.client, name)
        raise AttributeError(name)

    def create_record(self, model: str, payload: dict):
        if model != "ReviewRequest" or not self.item_table or not self.review_table:
            raise ValueError("Publish approval storage is unavailable.")
        if not self.item.get("updatedAt") or not self.item.get("contentHash"):
            raise ValueError("A version revision and content hash are required.")
        prepared = self.client._prepared_payload(model, payload)
        prepared.update({"__typename": "ReviewRequest", "createdAt": payload["raisedAt"], "updatedAt": payload["updatedAt"]})
        serializer = TypeSerializer()
        encode = lambda values: {key: serializer.serialize(value) for key, value in values.items()}
        names = {"#state": "versionState", "#lineage": "lineageId", "#updated": "updatedAt", "#hash": "contentHash", "#tenant": "tenantId"}
        values = {":current": "current", ":lineage": self.item["lineageId"], ":updated": self.item["updatedAt"], ":hash": self.item["contentHash"]}
        try:
            self.dynamodb.transact_write_items(TransactItems=[
                {"ConditionCheck": {"TableName": self.item_table, "Key": encode({"id": self.item["id"]}), "ConditionExpression": "#state = :current AND #lineage = :lineage AND #updated = :updated AND #hash = :hash AND attribute_not_exists(#tenant)", "ExpressionAttributeNames": names, "ExpressionAttributeValues": encode(values)}},
                {"Put": {"TableName": self.review_table, "Item": encode(prepared), "ConditionExpression": "attribute_not_exists(id)"}},
            ])
        except Exception as error:
            response = getattr(error, "response", {})
            if response.get("Error", {}).get("Code") == "TransactionCanceledException" and any(r.get("Code") == "ConditionalCheckFailed" for r in response.get("CancellationReasons", [])):
                raise ValueError("stale_version: Story or approval request changed; refresh and retry.") from error
            raise
        self.created = payload


def request_publish(client: Any, dynamodb: Any, item_table: str, review_table: str, *, lineage: str, expected: str, actor: str) -> dict:
    if getattr(client, "tenant_id", None):
        raise PermissionError("Publish requests are unavailable on tenant-scoped backends.")
    versions = client.list_by_index("itemsByLineageAndVersion", lineage)
    current = [row for row in versions if row.get("versionState") == "current"]
    if len(current) != 1 or current[0].get("id") != expected or current[0].get("lineageId") != lineage or current[0].get("status") != "draft":
        raise ValueError("stale_version: The current draft changed; reload it.")
    item = client.get_record("Item", expected)
    if not item or item.get("lineageId") != lineage or item.get("versionState") != "current" or item.get("status") != "draft" or not item.get("contentHash") or not item.get("updatedAt"):
        raise ValueError("stale_version: The current draft changed; reload it.")
    refuse_placeholder_slug(client, expected)
    render_preflight(client, expected)
    try:
        # Reuse all the publish validation, with every write captured rather than performed.
        publish_item(DryRunClient(client), expected, actor=actor, approved_by=None)
    except PublishError as error:
        if error.code not in (publish_gate.APPROVAL_REQUIRED, publish_gate.APPROVAL_REJECTED): raise
    # Never publish here. The gate creates or reuses only an approval request for this content hash.
    proxy = _ConditionalReviewClient(client, dynamodb, item_table, review_table, item)
    try:
        publish_gate.ensure_publish_approval(proxy, item, approved_by=None, actor=actor)
    except PublishError as error:
        if error.code not in (publish_gate.APPROVAL_REQUIRED, publish_gate.APPROVAL_REJECTED): raise
        if proxy.created:
            return {"status": "pending", "requestId": proxy.created["id"], "versionId": expected}
        requests = publish_gate._requests_for(client, publish_gate.request_prefix(item))
        selected = next((r for r in requests if r["state"] == "open"), None) if error.code == publish_gate.APPROVAL_REQUIRED else next((r for r in requests if r["outcome"] in ("rejected", "feedback")), None)
        if not selected: raise ValueError("Approval status changed; refresh and retry.")
        return {"status": "pending" if error.code == publish_gate.APPROVAL_REQUIRED else "rejected", "requestId": selected["id"], "versionId": expected}
    result = {"status": "console_handoff", "versionId": expected, "message": "Publish this version from the staff console."}
    if publish_gate.publish_approval(client) == publish_gate.REQUIRED:
        requests = publish_gate._requests_for(client, publish_gate.request_prefix(item))
        approved = next((r for r in requests if r["outcome"] == "approved" and publish_gate.approver_kind_of(r) in publish_gate.accepted_approver_kinds(publish_gate.REQUIRED)), None)
        if approved: result.update({"requestId": approved["id"], "approval": "approved"})
    return result
