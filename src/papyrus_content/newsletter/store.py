"""All DynamoDB access for the newsletter plugin (single table; layout in docs/newsletter.md).

Rows written here:
  SUB#<hid> / PROFILE        the subscriber (pending, confirmed or unsubscribed), consent evidence and capped history
  SUB#<hid> / LIST#<listId>  one membership; ``gsiList`` is set only while subscribed on a confirmed profile
  SUPP#<hid> / SUPP          suppression (read here, written by later stories)
  RATE#<kind>#<key> / RATE   counters with a TTL

Writes are conditional: a profile is replaced only if its ``rev`` is the one that was read, so two concurrent
requests (or a confirmation racing a resend) cannot both win. Everything the profile and its memberships need to change
together goes in one transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

HISTORY_LIMIT = 50
PENDING_RETENTION_SECONDS = 30 * 24 * 60 * 60
BY_LIST_INDEX = "byList"

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


class Conflict(Exception):
    """The profile changed since it was read (or already exists)."""


def iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def profile_key(hid: str) -> dict[str, str]:
    return {"pk": f"SUB#{hid}", "sk": "PROFILE"}


def list_key(hid: str, list_id: str) -> dict[str, str]:
    return {"pk": f"SUB#{hid}", "sk": f"LIST#{list_id}"}


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _plain(entry) for key, entry in value.items()}
    if isinstance(value, list):
        return [_plain(entry) for entry in value]
    return value


def _ser(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _serializer.serialize(value) for key, value in item.items() if value is not None}


def _de(item: dict[str, Any]) -> dict[str, Any]:
    return _plain({key: _deserializer.deserialize(value) for key, value in item.items()})


def append_history(profile: dict[str, Any], at: float, event: str) -> None:
    history = list(profile.get("history") or [])
    history.append({"at": iso(at), "event": event})
    profile["history"] = history[-HISTORY_LIMIT:]


def membership_row(hid: str, list_id: str, status: str, now: float, *, profile_confirmed: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {**list_key(hid, list_id), "status": status, "at": iso(now)}
    if status == "subscribed" and profile_confirmed:
        row["gsiList"] = list_id
    if status == "pending":
        row["expiresAt"] = int(now) + PENDING_RETENTION_SECONDS
    return row


class Store:
    def __init__(self, table_name: str, client: Any = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("dynamodb")
        self.table_name = table_name
        self.client = client

    def get_profile(self, hid: str) -> dict[str, Any] | None:
        response = self.client.get_item(TableName=self.table_name, Key=_ser(profile_key(hid)), ConsistentRead=True)
        return _de(response["Item"]) if "Item" in response else None

    def memberships(self, hid: str) -> dict[str, dict[str, Any]]:
        response = self.client.query(
            TableName=self.table_name,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues=_ser({":pk": f"SUB#{hid}", ":prefix": "LIST#"}),
            ConsistentRead=True,
        )
        rows = (_de(item) for item in response.get("Items", []))
        return {row["sk"].removeprefix("LIST#"): row for row in rows}

    def is_suppressed(self, hid: str) -> bool:
        response = self.client.get_item(
            TableName=self.table_name, Key=_ser({"pk": f"SUPP#{hid}", "sk": "SUPP"}), ConsistentRead=True
        )
        return "Item" in response

    def save(
        self,
        profile: dict[str, Any],
        expected_rev: int | None,
        put_rows: list[dict[str, Any]] | None = None,
        delete_lists: list[str] | None = None,
    ) -> None:
        """Write the profile (with ``rev`` bumped) and its membership rows in one transaction, or raise ``Conflict``."""
        hid = profile["pk"].removeprefix("SUB#")
        profile["rev"] = 0 if expected_rev is None else expected_rev + 1
        if expected_rev is None:
            condition: dict[str, Any] = {"ConditionExpression": "attribute_not_exists(pk)"}
        else:
            condition = {
                "ConditionExpression": "rev = :rev",
                "ExpressionAttributeValues": _ser({":rev": expected_rev}),
            }
        items: list[dict[str, Any]] = [{"Put": {"TableName": self.table_name, "Item": _ser(profile), **condition}}]
        items += [{"Put": {"TableName": self.table_name, "Item": _ser(row)}} for row in put_rows or []]
        items += [{"Delete": {"TableName": self.table_name, "Key": _ser(list_key(hid, list_id))}} for list_id in delete_lists or []]
        try:
            self.client.transact_write_items(TransactItems=items)
        except self.client.exceptions.TransactionCanceledException as error:
            reasons = error.response.get("CancellationReasons") or []
            if any(reason.get("Code") == "ConditionalCheckFailed" for reason in reasons):
                raise Conflict() from error
            raise

    def count(self, key: str, now: float, lifetime_seconds: int) -> int:
        """Increment a rate counter and return its new value. The row expires on its own."""
        response = self.client.update_item(
            TableName=self.table_name,
            Key=_ser({"pk": f"RATE#{key}", "sk": "RATE"}),
            UpdateExpression="ADD hits :one SET expiresAt = :expires",
            ExpressionAttributeValues=_ser({":one": 1, ":expires": int(now) + lifetime_seconds}),
            ReturnValues="UPDATED_NEW",
        )
        return int(response["Attributes"]["hits"]["N"])
