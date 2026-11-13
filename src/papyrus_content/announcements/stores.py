"""The real stores: SSM SecureString parameters and the two Amplify model tables written directly with the function's role."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from .x_account import CONNECTION_ID, utc_iso

SETTINGS_ID = "settings"


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _is_conditional_failure(error: Exception) -> bool:
    return str(getattr(error, "response", {}).get("Error", {}).get("Code", "")) == "ConditionalCheckFailedException"


class SsmParameters:
    def __init__(self, client: Any) -> None:
        self.client = client

    def get(self, name: str) -> str | None:
        try:
            return self.client.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
        except self.client.exceptions.ParameterNotFound:
            return None

    def put(self, name: str, value: str) -> None:
        self.client.put_parameter(Name=name, Value=value, Type="SecureString", Overwrite=True)

    def delete(self, name: str) -> None:
        try:
            self.client.delete_parameter(Name=name)
        except self.client.exceptions.ParameterNotFound:
            pass


class DynamoConnection:
    """The ``XConnection`` row (id ``x``). The lease is a conditional write, as the projection lease is."""

    def __init__(self, table: Any, clock: Any) -> None:
        self.table = table
        self.clock = clock

    def get(self) -> dict[str, Any] | None:
        item = self.table.get_item(Key={"id": CONNECTION_ID}, ConsistentRead=True).get("Item")
        return _plain(item) if item else None

    def save(self, fields: dict[str, Any]) -> None:
        names = {f"#{key}": key for key in fields}
        values = {f":{key}": value for key, value in fields.items()}
        stamp = utc_iso(self.clock())
        names["#updatedAt"], names["#typename"] = "updatedAt", "__typename"
        values[":updatedAt"], values[":typename"] = stamp, "XConnection"
        values[":createdAt"] = stamp
        names["#createdAt"] = "createdAt"
        assignments = [f"#{key} = :{key}" for key in fields] + ["#updatedAt = :updatedAt", "#typename = :typename", "#createdAt = if_not_exists(#createdAt, :createdAt)"]
        self.table.update_item(Key={"id": CONNECTION_ID}, UpdateExpression="SET " + ", ".join(assignments),
                               ExpressionAttributeNames=names, ExpressionAttributeValues=values)

    def acquire_lease(self, holder: str, now: float, until: float) -> bool:
        try:
            self.table.update_item(
                Key={"id": CONNECTION_ID},
                UpdateExpression="SET leaseHolder = :holder, leaseUntil = :until",
                ConditionExpression="attribute_exists(id) AND (attribute_not_exists(leaseHolder) OR leaseHolder = :none OR leaseUntil < :now)",
                ExpressionAttributeValues={":holder": holder, ":until": Decimal(str(until)), ":now": Decimal(str(now)), ":none": ""},
            )
        except Exception as error:
            if _is_conditional_failure(error):
                return False
            raise
        return True

    def release_lease(self, holder: str) -> None:
        try:
            self.table.update_item(Key={"id": CONNECTION_ID}, UpdateExpression="SET leaseHolder = :none",
                                   ConditionExpression="leaseHolder = :holder",
                                   ExpressionAttributeValues={":holder": holder, ":none": ""})
        except Exception as error:
            if not _is_conditional_failure(error):  # an expired lease another invocation took over is not ours to release
                raise


class DynamoSettings:
    """The ``AnnouncementSettings`` row (id ``settings``): one JSON document."""

    def __init__(self, table: Any, clock: Any) -> None:
        self.table = table
        self.clock = clock

    def get(self) -> dict[str, Any] | None:
        item = self.table.get_item(Key={"id": SETTINGS_ID}, ConsistentRead=True).get("Item")
        return _plain(json.loads(item["settings"])) if item else None

    def put(self, settings: dict[str, Any]) -> None:
        stamp = utc_iso(self.clock())
        self.table.update_item(
            Key={"id": SETTINGS_ID},
            UpdateExpression="SET settings = :settings, updatedAt = :stamp, #typename = :typename, createdAt = if_not_exists(createdAt, :stamp)",
            ExpressionAttributeNames={"#typename": "__typename"},
            ExpressionAttributeValues={":settings": json.dumps(settings), ":stamp": stamp, ":typename": "AnnouncementSettings"},
        )
