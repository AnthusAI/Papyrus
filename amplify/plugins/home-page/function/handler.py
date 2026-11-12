"""homePageTrigger: turns changes to the Reference table (and, when threads are on, to the Message table) into one debounced run of the ``home-page-snapshot`` projection task.

The Reference table's DynamoDB stream invokes this function with batches of records. A record that changes none of the public fields
is ignored, and so is one that can change no page: a Reference that is neither accepted nor predicted (so it cannot be recommended) before
and after the change. Every other record adds the id of its Reference to a list in the shared projection lock table (a changed Message
raises a counter beside it). The first change in a quiet period claims a debounce slot (a conditional write in the same table) and creates
a one-off EventBridge Scheduler schedule at the end of the window that invokes content-actions with the snapshot task; the task reads
the list and reads again only those rows. Later changes inside the window find the slot taken and only extend the list. A batch that
holds a changed Message claims the thread slot instead, whose window is a few seconds, and that run also takes whatever Reference ids are listed. A window with
more changes than one item can list (a mass import) raises a flag instead, and that run reads the whole corpus once.

This file imports nothing but the standard library and boto3: the Lambda bundles do not ship ``papyrus_content`` here.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from typing import Any, Mapping

#: ``predictedAcceptProbability`` is the prediction itself: its first write is what makes a pending Reference appear, so it is watched on its own (the sort key moves with it, but the number is the fact).
#: ``starRating`` is printed on an accepted Reference's tile and orders every page, so a rating change on its own (the old and new image differ in nothing else)
#: must reach the pages. Who rated and when are private and not watched.
CHANGE_FIELDS = ("curationStatus", "feedStateKey", "predictionSortKey", "predictedAcceptProbability", "versionState", "title", "curationSectionId", "starRating", "medium", "thumbnailPath")
MESSAGE_CHANGE_FIELDS = ("status", "content", "editedAt", "deletedAt")
PUBLIC_MESSAGE_KIND = "comment"
CHANGING_EVENTS = ("INSERT", "MODIFY")
REMOVE_EVENT = "REMOVE"
DEBOUNCE_KEY_PREFIX = "home-page-debounce#"
#: A changed Message has a slot of its own and a short window (``homePage.freshness.threadDebounceSeconds``): a forum post must not wait for the Reference window.
THREAD_DEBOUNCE_KEY_PREFIX = "home-page-debounce-thread#"
SCHEDULE_PREFIX = "papyrus-home-page-snapshot-"
DIRTY_KEY_PREFIX = "home-page-dirty#"
FULL_KEY_PREFIX = "home-page-full#"
#: A DynamoDB item holds 400 KB and an id is under 200 bytes, so a list of 2,000 ids always fits; more than that is a mass import and is read in full.
DIRTY_LIMIT = 2000
ACCEPTED = "accepted"
NOT_RECOMMENDABLE = ("rejected", "archived")
HOUR_SECONDS = 3600
CONDITION_FAILED = "ConditionalCheckFailedException"
SCHEDULE_CONFLICT = "ConflictException"
SCOPE_CHARACTERS = 8


def error_code(error: Exception) -> str:
    response = getattr(error, "response", None) or {}
    return str(response.get("Error", {}).get("Code") or type(error).__name__)


def has_prediction(image: Mapping[str, Any]) -> bool:
    """True when the row holds a real prediction: a finite number in ``predictedAcceptProbability``.

    This mirrors ``papyrus_content.home_page.export.stored_prediction``, the rule the snapshot publishes by (this file cannot import that package; a test in
    ``home_page/export_test.py`` runs both over the same rows). ``predictionDecidedAt`` is written together with the number and is not the test, and
    ``predictionSortKey`` is no evidence at all: every Reference gets one at creation (``0.500000#...`` when unpredicted).
    """
    value = (image.get("predictedAcceptProbability") or {}).get("N")
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def can_show(image: Mapping[str, Any]) -> bool:
    """True for a Reference a page can show: an accepted one, or a pending one the Cyclotron has predicted. A pending one nobody has predicted is on no page, so a change to it schedules nothing until its first prediction arrives (that write is the change that makes it appear)."""
    status = (image.get("curationStatus") or {}).get("S")
    if status == ACCEPTED:
        return True
    if not status or status in NOT_RECOMMENDABLE:
        return False
    return has_prediction(image)


def record_change(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """What the record changes for a public page: ``{"id": <Reference id>}`` or ``{"message": True}``; ``None`` when it changes nothing a page shows."""
    event_name = record.get("eventName")
    images = record.get("dynamodb") or {}
    old_image = images.get("OldImage") or {}
    new_image = images.get("NewImage") or {}
    if event_name == REMOVE_EVENT:
        if "messageKind" in old_image:
            return {"message": True}
        return {"id": reference_id(record)} if can_show(old_image) else None
    if event_name not in CHANGING_EVENTS:
        return None
    if "messageKind" in new_image:
        return {"message": True} if message_changed(old_image, new_image) else None
    if not (can_show(old_image) or can_show(new_image)):
        return None
    if event_name == "MODIFY" and not any(old_image.get(field) != new_image.get(field) for field in CHANGE_FIELDS):
        return None
    return {"id": reference_id(record)}


def reference_id(record: Mapping[str, Any]) -> str | None:
    keys = (record.get("dynamodb") or {}).get("Keys") or {}
    return (keys.get("id") or {}).get("S")


def record_changed(record: Mapping[str, Any]) -> bool:
    """True when the record inserts, removes or changes one of the fields a public page shows or ranks by, on a Reference a page can show."""
    return record_change(record) is not None


def message_changed(old_image: Mapping[str, Any], new_image: Mapping[str, Any]) -> bool:
    """True for a comment that is new or whose status, content, edit time or deletion time differs.

    A Message stream that carries only the new image (the console responder's) has no old image to compare, so every write of a comment counts.
    """
    if (new_image.get("messageKind") or {}).get("S") != PUBLIC_MESSAGE_KIND:
        return False
    if not old_image:
        return True
    return any(old_image.get(field) != new_image.get(field) for field in MESSAGE_CHANGE_FIELDS)


def scope_of(function_arn: str) -> str:
    """A short stable name for this site's backend, from the snapshot function it schedules, so sites that share an account never share a slot."""
    function_name = function_arn.rsplit(":", 1)[-1]
    return hashlib.sha256(function_name.encode("utf-8")).hexdigest()[:SCOPE_CHARACTERS]


def debounce_key(scope: str, key_prefix: str = DEBOUNCE_KEY_PREFIX) -> str:
    return f"{key_prefix}{scope}"


def dirty_key(scope: str) -> str:
    return f"{DIRTY_KEY_PREFIX}{scope}"


def full_key(scope: str) -> str:
    return f"{FULL_KEY_PREFIX}{scope}"


def record_changes(dynamodb_client: Any, table: str, scope: str, ids: set[str], messages: int) -> None:
    """Writes what changed where the task will read it: the ids into a set, the Messages into a counter, and a flag when the set would not fit.

    This runs before the schedule is created, so a run never starts without the list that explains it. The task takes out exactly what it read.
    """
    if messages:
        dynamodb_client.update_item(
            TableName=table,
            Key={"publication": {"S": dirty_key(scope)}},
            UpdateExpression="ADD messageSeq :count",
            ExpressionAttributeValues={":count": {"N": str(messages)}},
        )
    if not ids:
        return
    try:
        result = dynamodb_client.update_item(
            TableName=table,
            Key={"publication": {"S": dirty_key(scope)}},
            UpdateExpression="ADD ids :ids",
            ExpressionAttributeValues={":ids": {"SS": sorted(ids)}},
            ReturnValues="UPDATED_NEW",
        )
        listed = len(((result.get("Attributes") or {}).get("ids") or {}).get("SS") or [])
    except Exception as error:
        if error_code(error) != "ValidationException":
            raise
        listed = DIRTY_LIMIT + 1  # the item is full
    if listed > DIRTY_LIMIT:
        dynamodb_client.update_item(
            TableName=table,
            Key={"publication": {"S": full_key(scope)}},
            UpdateExpression="ADD seq :one",
            ExpressionAttributeValues={":one": {"N": "1"}},
        )


def schedule_name(scope: str, locked_until: int) -> str:
    return f"{SCHEDULE_PREFIX}{scope}-{locked_until}"


def claim_slot(
    dynamodb_client: Any, table: str, scope: str, now_seconds: float, debounce_seconds: int, key_prefix: str = DEBOUNCE_KEY_PREFIX
) -> int | None:
    """Opens a debounce window and returns when it closes, or ``None`` when a window is already open."""
    locked_until = int(now_seconds) + debounce_seconds
    try:
        dynamodb_client.put_item(
            TableName=table,
            Item={
                "publication": {"S": debounce_key(scope, key_prefix)},
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


def release_slot(dynamodb_client: Any, table: str, scope: str, locked_until: int, key_prefix: str = DEBOUNCE_KEY_PREFIX) -> None:
    """Reopens the window this call opened, so the next change can schedule the run that failed to schedule."""
    try:
        dynamodb_client.delete_item(
            TableName=table,
            Key={"publication": {"S": debounce_key(scope, key_prefix)}},
            ConditionExpression="lockedUntil = :until",
            ExpressionAttributeValues={":until": {"N": str(locked_until)}},
        )
    except Exception as error:
        if error_code(error) != CONDITION_FAILED:
            raise


def snapshot_task(scope: str) -> dict[str, Any]:
    """The task the schedule invokes: incremental, and told which items hold this site's changes and state."""
    return {"projectionTask": {"task": "home-page-snapshot", "incremental": True, "scope": scope}}


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
            "Input": json.dumps(snapshot_task(scope)),
            "RetryPolicy": {"MaximumRetryAttempts": 0},
        },
    )


def schedule_for_changes(
    dynamodb_client: Any, scheduler_client: Any, environment: Mapping[str, str], now_seconds: float, *, messages: bool = False
) -> dict[str, Any]:
    """Claims the slot and schedules the run. A failure releases the slot, then raises so the stream retries the batch.

    ``messages`` is true when the batch holds a changed Message: it takes the thread slot and its short window (a site without
    ``PAPYRUS_HOME_PAGE_THREAD_DEBOUNCE_SECONDS`` keeps the one window for both)."""
    function_arn = environment["PAPYRUS_HOME_PAGE_SNAPSHOT_FUNCTION_ARN"]
    role_arn = environment["PAPYRUS_HOME_PAGE_SCHEDULER_ROLE_ARN"]
    table = environment["PAPYRUS_PROJECTION_LOCK_TABLE"]
    debounce_seconds = int(environment["PAPYRUS_HOME_PAGE_DEBOUNCE_SECONDS"])
    key_prefix = DEBOUNCE_KEY_PREFIX
    thread_seconds = (environment.get("PAPYRUS_HOME_PAGE_THREAD_DEBOUNCE_SECONDS") or "").strip()
    if messages and thread_seconds:
        debounce_seconds, key_prefix = int(thread_seconds), THREAD_DEBOUNCE_KEY_PREFIX
    scope = scope_of(function_arn)
    locked_until = claim_slot(dynamodb_client, table, scope, now_seconds, debounce_seconds, key_prefix)
    if locked_until is None:
        return {"scheduled": False, "reason": "window open"}
    try:
        create_snapshot_schedule(scheduler_client, scope, locked_until, function_arn, role_arn)
    except Exception as error:
        if error_code(error) == SCHEDULE_CONFLICT:
            return {"scheduled": False, "reason": "already scheduled", "runAt": locked_until}
        print(json.dumps({"homePageScheduleFailed": error_code(error)}))
        release_slot(dynamodb_client, table, scope, locked_until, key_prefix)
        raise
    return {"scheduled": True, "runAt": locked_until}


def handler(event: Mapping[str, Any], context: Any = None, *, dynamodb_client: Any = None, scheduler_client: Any = None, now_seconds: float | None = None) -> dict[str, Any]:
    records = event.get("Records") or []
    changes = [change for change in (record_change(record) for record in records) if change is not None]
    if not changes:
        return {"records": len(records), "changed": 0, "scheduled": False}
    if dynamodb_client is None or scheduler_client is None:
        import boto3

        dynamodb_client = dynamodb_client or boto3.client("dynamodb")
        scheduler_client = scheduler_client or boto3.client("scheduler")
    ids = {change["id"] for change in changes if change.get("id")}
    scope = scope_of(os.environ["PAPYRUS_HOME_PAGE_SNAPSHOT_FUNCTION_ARN"])
    messages = sum(1 for change in changes if change.get("message"))
    record_changes(dynamodb_client, os.environ["PAPYRUS_PROJECTION_LOCK_TABLE"], scope, ids, messages)
    result = schedule_for_changes(dynamodb_client, scheduler_client, os.environ, time.time() if now_seconds is None else now_seconds, messages=messages > 0)
    return {"records": len(records), "changed": len(changes), **result}
