"""homePageTrigger: turns changes to the Reference table into one debounced run of the ``home-page-snapshot`` projection task.

The Reference table's DynamoDB stream invokes this function with batches of records. A record that changes none of the public fields
is ignored. The first change in a quiet period claims a debounce slot (a conditional write in the shared projection lock table) and
creates a one-off EventBridge Scheduler schedule at the end of the window that invokes content-actions with the snapshot task. Later
changes inside the window find the slot taken and do nothing, because the run at the end of the window reads them all.

This file imports nothing but the standard library and boto3: the Lambda bundles do not ship ``papyrus_content`` here.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Mapping

CHANGE_FIELDS = ("curationStatus", "feedStateKey", "predictionSortKey", "versionState", "title", "curationSectionId")
CHANGING_EVENTS = ("INSERT", "MODIFY")
REMOVE_EVENT = "REMOVE"
DEBOUNCE_KEY_PREFIX = "home-page-debounce#"
SCHEDULE_PREFIX = "papyrus-home-page-snapshot-"
SNAPSHOT_TASK = {"projectionTask": {"task": "home-page-snapshot"}}
HOUR_SECONDS = 3600
CONDITION_FAILED = "ConditionalCheckFailedException"
SCHEDULE_CONFLICT = "ConflictException"
SCOPE_CHARACTERS = 8


def error_code(error: Exception) -> str:
    response = getattr(error, "response", None) or {}
    return str(response.get("Error", {}).get("Code") or type(error).__name__)


def record_changed(record: Mapping[str, Any]) -> bool:
    """True when the record inserts, removes or changes one of the fields a public page shows or ranks by."""
    event_name = record.get("eventName")
    if event_name == REMOVE_EVENT:
        return True
    if event_name not in CHANGING_EVENTS:
        return False
    images = record.get("dynamodb") or {}
    old_image = images.get("OldImage") or {}
    new_image = images.get("NewImage") or {}
    return any(old_image.get(field) != new_image.get(field) for field in CHANGE_FIELDS)


def scope_of(function_arn: str) -> str:
    """A short stable name for this site's backend, from the snapshot function it schedules, so sites that share an account never share a slot."""
    function_name = function_arn.rsplit(":", 1)[-1]
    return hashlib.sha256(function_name.encode("utf-8")).hexdigest()[:SCOPE_CHARACTERS]


def debounce_key(scope: str) -> str:
    return f"{DEBOUNCE_KEY_PREFIX}{scope}"


def schedule_name(scope: str, locked_until: int) -> str:
    return f"{SCHEDULE_PREFIX}{scope}-{locked_until}"


def claim_slot(dynamodb_client: Any, table: str, scope: str, now_seconds: float, debounce_seconds: int) -> int | None:
    """Opens a debounce window and returns when it closes, or ``None`` when a window is already open."""
    locked_until = int(now_seconds) + debounce_seconds
    try:
        dynamodb_client.put_item(
            TableName=table,
            Item={
                "publication": {"S": debounce_key(scope)},
                "lockedUntil": {"N": str(locked_until)},
                "expiresAt": {"N": str(locked_until + debounce_seconds + HOUR_SECONDS)},
            },
            ConditionExpression="attribute_not_exists(publication) OR lockedUntil <= :now",
            ExpressionAttributeValues={":now": {"N": str(int(now_seconds))}},
        )
    except Exception as error:
        if error_code(error) == CONDITION_FAILED:
            return None
        raise
    return locked_until


def release_slot(dynamodb_client: Any, table: str, scope: str, locked_until: int) -> None:
    """Reopens the window this call opened, so the next change can schedule the run that failed to schedule."""
    try:
        dynamodb_client.delete_item(
            TableName=table,
            Key={"publication": {"S": debounce_key(scope)}},
            ConditionExpression="lockedUntil = :until",
            ExpressionAttributeValues={":until": {"N": str(locked_until)}},
        )
    except Exception as error:
        if error_code(error) != CONDITION_FAILED:
            raise


def create_snapshot_schedule(scheduler_client: Any, scope: str, locked_until: int, function_arn: str, role_arn: str) -> None:
    scheduler_client.create_schedule(
        Name=schedule_name(scope, locked_until),
        ScheduleExpression="at(" + time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(locked_until)) + ")",
        ScheduleExpressionTimezone="UTC",
        FlexibleTimeWindow={"Mode": "OFF"},
        ActionAfterCompletion="DELETE",
        Target={
            "Arn": function_arn,
            "RoleArn": role_arn,
            "Input": json.dumps(SNAPSHOT_TASK),
            "RetryPolicy": {"MaximumRetryAttempts": 0},
        },
    )


def schedule_for_changes(
    dynamodb_client: Any, scheduler_client: Any, environment: Mapping[str, str], now_seconds: float
) -> dict[str, Any]:
    """Claims the slot and schedules the run. A failure releases the slot, then raises so the stream retries the batch."""
    function_arn = environment["PAPYRUS_HOME_PAGE_SNAPSHOT_FUNCTION_ARN"]
    role_arn = environment["PAPYRUS_HOME_PAGE_SCHEDULER_ROLE_ARN"]
    table = environment["PAPYRUS_PROJECTION_LOCK_TABLE"]
    debounce_seconds = int(environment["PAPYRUS_HOME_PAGE_DEBOUNCE_SECONDS"])
    scope = scope_of(function_arn)
    locked_until = claim_slot(dynamodb_client, table, scope, now_seconds, debounce_seconds)
    if locked_until is None:
        return {"scheduled": False, "reason": "window open"}
    try:
        create_snapshot_schedule(scheduler_client, scope, locked_until, function_arn, role_arn)
    except Exception as error:
        if error_code(error) == SCHEDULE_CONFLICT:
            return {"scheduled": False, "reason": "already scheduled", "runAt": locked_until}
        print(json.dumps({"homePageScheduleFailed": error_code(error)}))
        release_slot(dynamodb_client, table, scope, locked_until)
        raise
    return {"scheduled": True, "runAt": locked_until}


def handler(event: Mapping[str, Any], context: Any = None, *, dynamodb_client: Any = None, scheduler_client: Any = None, now_seconds: float | None = None) -> dict[str, Any]:
    records = event.get("Records") or []
    changed = sum(1 for record in records if record_changed(record))
    if changed == 0:
        return {"records": len(records), "changed": 0, "scheduled": False}
    if dynamodb_client is None or scheduler_client is None:
        import boto3

        dynamodb_client = dynamodb_client or boto3.client("dynamodb")
        scheduler_client = scheduler_client or boto3.client("scheduler")
    result = schedule_for_changes(dynamodb_client, scheduler_client, os.environ, time.time() if now_seconds is None else now_seconds)
    return {"records": len(records), "changed": changed, **result}
