"""The site store's catalogue read and written straight in DynamoDB, for the ``agent-policy`` function (its own role, not a person's).

Same four methods as ``SiteCatalogueTable``. The index on ``documentId`` is found by asking the table which index has that key, so no generated index name is assumed.
"""
from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

CONDITION_FAILED = "ConditionalCheckFailedException"
ROW_FIELDS = {"SiteDocument": ("id", "tenantId", "kind", "currentVersion", "s3Key", "sha256", "schemaVersion", "updatedBy", "updatedAt"),
              "SiteDocumentVersion": ("id", "tenantId", "documentId", "version", "s3Key", "sha256", "createdBy", "createdAt", "note")}


class DynamoCatalogueTable:
    def __init__(self, tables: dict[str, Any]):
        self._tables = tables

    def get(self, model: str, row_id: str) -> dict[str, Any] | None:
        return self._tables[model].get_item(Key={"id": row_id}, ConsistentRead=True).get("Item")

    def create(self, model: str, row: dict[str, Any]) -> None:
        item = {name: value for name, value in row.items() if value is not None}
        item.setdefault("__typename", model)
        try:
            self._tables[model].put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == CONDITION_FAILED:
                raise KeyError(row["id"]) from error
            raise

    def update_if(self, model: str, row_id: str, changes: dict[str, Any], expected: dict[str, Any]) -> bool:
        names = {f"#c{index}": name for index, name in enumerate(changes)} | {f"#e{index}": name for index, name in enumerate(expected)}
        values = {f":c{index}": value for index, value in enumerate(changes.values())} | {f":e{index}": value for index, value in enumerate(expected.values())}
        update = "SET " + ", ".join(f"#c{index} = :c{index}" for index in range(len(changes)))
        condition = " AND ".join(f"#e{index} = :e{index}" for index in range(len(expected)))
        try:
            self._tables[model].update_item(Key={"id": row_id}, UpdateExpression=update, ConditionExpression=condition,
                                            ExpressionAttributeNames=names, ExpressionAttributeValues=values)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == CONDITION_FAILED:
                return False
            raise
        return True

    def latest_version(self, document_id: str) -> dict[str, Any] | None:
        table = self._tables["SiteDocumentVersion"]
        index = next(item["IndexName"] for item in table.meta.client.describe_table(TableName=table.name)["Table"].get("GlobalSecondaryIndexes", [])
                     if item["KeySchema"][0]["AttributeName"] == "documentId")
        from boto3.dynamodb.conditions import Key

        items = table.query(IndexName=index, KeyConditionExpression=Key("documentId").eq(document_id), ScanIndexForward=False, Limit=1).get("Items") or []
        return items[0] if items else None
