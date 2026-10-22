"""Subscriber-adjacent rows: suppression, site state, the send ledger, issue counters, the recent event log and erasure.

Layout (docs/newsletter.md):
  SUPP#<hid> / SUPP                 reason bounce | complaint | manual
  STATE / SITE                      paused flag with reason and time
  ISSUE#<id> / SEND#<hid>           the send ledger (written by the sending story). Each row carries ``gsiHid`` = <hid>, which
                                    puts it in the sparse GSI ``byHid`` so erasure finds a subscriber's rows with one query.
  ISSUE#<id> / META                 ``counts`` map of issue counters
  EVENTS / <iso>#<messageId>#<type> recent SES events for the newsroom, no address, 90 days
"""

from __future__ import annotations

from typing import Any

from .store import Store, _de, _ser, iso, list_key, profile_key

LEDGER_HID_ATTRIBUTE = "gsiHid"
BY_HID_INDEX = "byHid"
EVENT_RETENTION_SECONDS = 90 * 24 * 60 * 60
SUPPRESSION_REASONS = ("bounce", "complaint", "manual")


def suppression_key(hid: str) -> dict[str, str]:
    return {"pk": f"SUPP#{hid}", "sk": "SUPP"}


def ledger_key(issue: str, hid: str) -> dict[str, str]:
    return {"pk": f"ISSUE#{issue}", "sk": f"SEND#{hid}"}


def get_suppression(store: Store, hid: str) -> dict[str, Any] | None:
    response = store.client.get_item(TableName=store.table_name, Key=_ser(suppression_key(hid)), ConsistentRead=True)
    return _de(response["Item"]) if "Item" in response else None


def put_suppression(store: Store, hid: str, reason: str, now: float, issue: str = "") -> None:
    if reason not in SUPPRESSION_REASONS:
        raise ValueError(f"Unknown suppression reason {reason!r}")
    item = {**suppression_key(hid), "reason": reason, "at": iso(now), "issue": issue or None}
    store.client.put_item(TableName=store.table_name, Item=_ser(item))


def delete_suppression(store: Store, hid: str) -> None:
    store.client.delete_item(TableName=store.table_name, Key=_ser(suppression_key(hid)))


def get_state(store: Store) -> dict[str, Any]:
    response = store.client.get_item(TableName=store.table_name, Key=_ser({"pk": "STATE", "sk": "SITE"}), ConsistentRead=True)
    return _de(response["Item"]) if "Item" in response else {}


def put_state(store: Store, state: dict[str, Any]) -> None:
    store.client.put_item(TableName=store.table_name, Item=_ser({"pk": "STATE", "sk": "SITE", **state}))


def ledger_row_keys(store: Store, hid: str) -> list[dict[str, str]]:
    """Every send-ledger row of one subscriber, by the sparse GSI (no scan)."""
    keys: list[dict[str, str]] = []
    start: dict[str, Any] | None = None
    while True:
        extra = {"ExclusiveStartKey": start} if start else {}
        response = store.client.query(
            TableName=store.table_name,
            IndexName=BY_HID_INDEX,
            KeyConditionExpression=f"{LEDGER_HID_ATTRIBUTE} = :hid",
            ExpressionAttributeValues=_ser({":hid": hid}),
            **extra,
        )
        keys += [{"pk": item["pk"]["S"], "sk": item["sk"]["S"]} for item in response.get("Items", [])]
        start = response.get("LastEvaluatedKey")
        if not start:
            return keys


def batch_delete(store: Store, keys: list[dict[str, str]]) -> None:
    for offset in range(0, len(keys), 25):
        pending = [{"DeleteRequest": {"Key": _ser(key)}} for key in keys[offset : offset + 25]]
        for _attempt in range(8):
            response = store.client.batch_write_item(RequestItems={store.table_name: pending})
            pending = response.get("UnprocessedItems", {}).get(store.table_name, [])
            if not pending:
                break
        else:
            raise RuntimeError("Could not delete every row")


def erase_subscriber(store: Store, hid: str) -> int:
    """Remove the profile, every list row, the suppression row and every ledger row. Returns the number of rows removed."""
    keys = [list_key(hid, list_id) for list_id in store.memberships(hid)]
    keys += ledger_row_keys(store, hid)
    keys += [suppression_key(hid), profile_key(hid)]
    batch_delete(store, keys)
    return len(keys)


def update_ledger(store: Store, issue: str, hid: str, status: str, unless: tuple[str, ...], now: float) -> bool:
    """Set a ledger row's status unless it already holds one of ``unless``. A missing row is a no-op. True if it changed."""
    placeholders = {f":u{index}": value for index, value in enumerate(unless)}
    condition = "attribute_exists(pk)"
    if placeholders:
        condition += f" AND NOT (#status IN ({', '.join(placeholders)}))"
    try:
        store.client.update_item(
            TableName=store.table_name,
            Key=_ser(ledger_key(issue, hid)),
            UpdateExpression="SET #status = :status, eventAt = :at",
            ConditionExpression=condition,
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=_ser({":status": status, ":at": iso(now), **placeholders}),
        )
    except store.client.exceptions.ConditionalCheckFailedException:
        return False
    return True


def add_issue_counter(store: Store, issue: str, counter: str) -> bool:
    """Add one to ``ISSUE#<issue>/META`` ``counts.<counter>``. False when the issue has no counts map."""
    try:
        store.client.update_item(
            TableName=store.table_name,
            Key=_ser({"pk": f"ISSUE#{issue}", "sk": "META"}),
            UpdateExpression="SET counts.#counter = if_not_exists(counts.#counter, :zero) + :one",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeNames={"#counter": counter},
            ExpressionAttributeValues=_ser({":zero": 0, ":one": 1}),
        )
    except store.client.exceptions.ConditionalCheckFailedException:
        return False
    except store.client.exceptions.ClientError as error:
        if error.response["Error"]["Code"] == "ValidationException":
            return False
        raise
    return True


def put_event(store: Store, *, message_id: str, event_type: str, hid: str, issue: str, list_id: str, detail: str, now: float) -> None:
    """One row of the recent event log: no address, only the pseudonymous subscriber id, and gone in 90 days."""
    item = {
        "pk": "EVENTS",
        "sk": f"{iso(now)}#{message_id}#{event_type}",
        "type": event_type,
        "hid": hid,
        "issue": issue or None,
        "list": list_id or None,
        "detail": detail or None,
        "expiresAt": int(now) + EVENT_RETENTION_SECONDS,
    }
    store.client.put_item(TableName=store.table_name, Item=_ser(item))
