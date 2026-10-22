"""All DynamoDB access for the newsletter plugin (single table; layout in docs/newsletter.md).

Rows written here:
  SUB#<hid> / PROFILE        the subscriber (pending, confirmed or unsubscribed), consent evidence and capped history
  SUB#<hid> / LIST#<listId>  one membership; ``gsiList`` is set only while subscribed on a confirmed profile
  SUPP#<hid> / SUPP          suppression (written by ``records``)
  RATE#<kind>#<key> / RATE   counters with a TTL
  COUNT#<listId> / COUNT     membership counters ``confirmed`` / ``pending`` / ``unsubscribed`` for one list
  COUNT#SITE / COUNT         profile counters (same three names), ``suppressed``, and ``seeded`` once ``recount`` has run

The COUNT rows are kept by the code that changes the data, never read-modify-write: ``Store.save`` adds the deltas to the
same transaction as the membership rows, ``records.put_suppression`` / ``delete_suppression`` / ``erase_subscriber`` adjust
them next to their own write. DynamoDB TTL deleting an expired pending row bypasses all of that, so ``recount`` (a scan)
rewrites every row from the truth; the panel's overview runs it when the site row is not ``seeded``.

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
SITE_COUNT_ID = "SITE"  # list ids start with a lowercase letter, so this cannot collide
PROFILE_BUCKETS = ("confirmed", "pending", "unsubscribed")
MEMBERSHIP_BUCKET = {"subscribed": "confirmed", "pending": "pending", "unsubscribed": "unsubscribed"}

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


def count_key(list_id: str) -> dict[str, str]:
    return {"pk": f"COUNT#{list_id}", "sk": "COUNT"}


class Deltas:
    """Counter changes per count row (``COUNT#<id>``): ``{id: {bucket: change}}``. Zero changes are dropped."""

    def __init__(self) -> None:
        self.changes: dict[str, dict[str, int]] = {}

    def add(self, count_id: str, bucket: str | None, amount: int) -> None:
        if bucket is None or amount == 0:
            return
        row = self.changes.setdefault(count_id, {})
        row[bucket] = row.get(bucket, 0) + amount

    def move(self, count_id: str, old: str | None, new: str | None) -> None:
        if old != new:
            self.add(count_id, old, -1)
            self.add(count_id, new, 1)

    def items(self) -> list[tuple[str, dict[str, int]]]:
        return [(count_id, {k: v for k, v in row.items() if v}) for count_id, row in self.changes.items() if any(row.values())]


def _count_update(table: str, count_id: str, row: dict[str, int]) -> dict[str, Any]:
    names = {f"#b{index}": bucket for index, bucket in enumerate(row)}
    values = {f":d{index}": amount for index, amount in enumerate(row.values())}
    expression = "ADD " + ", ".join(f"#b{index} :d{index}" for index in range(len(row)))
    return {
        "TableName": table,
        "Key": _ser(count_key(count_id)),
        "UpdateExpression": expression,
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": _ser(values),
    }


def removal_deltas(profile: dict[str, Any] | None, memberships: dict[str, dict[str, Any]], suppressed: bool) -> Deltas:
    """What leaves the counters when a subscriber is erased."""
    deltas = Deltas()
    if profile is not None:
        deltas.move(SITE_COUNT_ID, profile.get("status"), None)
    for list_id, row in memberships.items():
        deltas.move(list_id, MEMBERSHIP_BUCKET.get(str(row.get("status"))), None)
    if suppressed:
        deltas.add(SITE_COUNT_ID, "suppressed", -1)
    return deltas


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
        before_profile = self.get_profile(hid) if expected_rev is not None else None
        before_rows = self.memberships(hid) if before_profile is not None else {}
        deltas = Deltas()
        deltas.move(SITE_COUNT_ID, (before_profile or {}).get("status"), profile.get("status"))
        for row in put_rows or []:
            list_id = str(row["sk"]).removeprefix("LIST#")
            deltas.move(
                list_id,
                MEMBERSHIP_BUCKET.get(str(before_rows.get(list_id, {}).get("status"))),
                MEMBERSHIP_BUCKET.get(str(row.get("status"))),
            )
        for list_id in delete_lists or []:
            if list_id in before_rows and not any(str(row["sk"]) == f"LIST#{list_id}" for row in put_rows or []):
                deltas.move(list_id, MEMBERSHIP_BUCKET.get(str(before_rows[list_id].get("status"))), None)
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
        items += [{"Update": _count_update(self.table_name, count_id, row)} for count_id, row in deltas.items()]
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

    # -- membership counters ------------------------------------------------------------------------------------

    def apply_deltas(self, deltas: Deltas) -> None:
        """Add counter changes outside a transaction (suppression and erasure)."""
        for count_id, row in deltas.items():
            update = _count_update(self.table_name, count_id, row)
            self.client.update_item(**update)

    def get_counts(self, count_id: str) -> dict[str, int]:
        response = self.client.get_item(TableName=self.table_name, Key=_ser(count_key(count_id)), ConsistentRead=True)
        row = _de(response["Item"]) if "Item" in response else {}
        return {name: value for name, value in row.items() if name not in ("pk", "sk")}

    def recount(self, list_ids: list[str], now: float) -> dict[str, Any]:
        """Scan every subscriber row and rewrite all COUNT rows. The one-off repair for drift (TTL expiry, interrupted writes)."""
        site = {"confirmed": 0, "pending": 0, "unsubscribed": 0, "suppressed": 0}
        per_list: dict[str, dict[str, int]] = {list_id: {"confirmed": 0, "pending": 0, "unsubscribed": 0} for list_id in list_ids}
        start: dict[str, Any] | None = None
        while True:
            page = self.client.scan(
                TableName=self.table_name,
                FilterExpression="begins_with(pk, :sub) OR begins_with(pk, :supp)",
                ProjectionExpression="pk, sk, #status, expiresAt",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues=_ser({":sub": "SUB#", ":supp": "SUPP#"}),
                **({"ExclusiveStartKey": start} if start else {}),
            )
            for raw in page.get("Items", []):
                row = _de(raw)
                if "expiresAt" in row and row["expiresAt"] < now:  # TTL has passed; DynamoDB deletes it eventually
                    continue
                if row["pk"].startswith("SUPP#"):
                    site["suppressed"] += 1
                elif row["sk"] == "PROFILE":
                    bucket = str(row.get("status"))
                    if bucket in PROFILE_BUCKETS:
                        site[bucket] += 1
                elif row["sk"].startswith("LIST#"):
                    bucket = MEMBERSHIP_BUCKET.get(str(row.get("status")), "")
                    if bucket:
                        per_list.setdefault(row["sk"].removeprefix("LIST#"), {"confirmed": 0, "pending": 0, "unsubscribed": 0})[bucket] += 1
            start = page.get("LastEvaluatedKey")
            if not start:
                break
        for list_id, counts in per_list.items():
            self.client.put_item(TableName=self.table_name, Item=_ser({**count_key(list_id), **counts}))
        self.client.put_item(TableName=self.table_name, Item=_ser({**count_key(SITE_COUNT_ID), **site, "seeded": True, "seededAt": iso(now)}))
        return {"site": site, "lists": per_list}
