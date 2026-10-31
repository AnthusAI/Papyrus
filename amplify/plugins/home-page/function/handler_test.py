from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("home_page_trigger_handler", Path(__file__).with_name("handler.py"))
handler_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handler_module)

FUNCTION_ARN = "arn:aws:lambda:us-east-1:123456789012:function:content-actions-site-a"
ENVIRONMENT = {
    "PAPYRUS_HOME_PAGE_SNAPSHOT_FUNCTION_ARN": FUNCTION_ARN,
    "PAPYRUS_HOME_PAGE_SCHEDULER_ROLE_ARN": "arn:aws:iam::123456789012:role/scheduler",
    "PAPYRUS_HOME_PAGE_DEBOUNCE_SECONDS": "300",
    "PAPYRUS_PROJECTION_LOCK_TABLE": "papyrus-projection-locks",
}
NOW = 1_800_000_000


class ClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeDynamo:
    def __init__(self) -> None:
        self.items: dict[str, int] = {}
        self.puts = 0

    def put_item(self, *, TableName, Item, ConditionExpression, ExpressionAttributeValues):
        self.puts += 1
        key = Item["publication"]["S"]
        now = int(ExpressionAttributeValues[":now"]["N"])
        if key in self.items and self.items[key] > now:
            raise ClientError("ConditionalCheckFailedException")
        self.items[key] = int(Item["lockedUntil"]["N"])

    def delete_item(self, *, TableName, Key, ConditionExpression, ExpressionAttributeValues):
        key = Key["publication"]["S"]
        if self.items.get(key) != int(ExpressionAttributeValues[":until"]["N"]):
            raise ClientError("ConditionalCheckFailedException")
        del self.items[key]


class FakeScheduler:
    def __init__(self, failure: str | None = None) -> None:
        self.calls: list[dict] = []
        self.failure = failure

    def create_schedule(self, **arguments):
        if self.failure:
            raise ClientError(self.failure)
        self.calls.append(arguments)


def record(event_name="MODIFY", old=None, new=None):
    images = {}
    if old is not None:
        images["OldImage"] = {key: {"S": value} for key, value in old.items()}
    if new is not None:
        images["NewImage"] = {key: {"S": value} for key, value in new.items()}
    return {"eventName": event_name, "dynamodb": images}


PENDING = {"curationStatus": "pending", "title": "A"}
ACCEPTED = {"curationStatus": "accepted", "title": "A"}


def run(records, dynamo=None, scheduler=None, now=NOW, monkeypatch=None):
    dynamo = dynamo or FakeDynamo()
    scheduler = scheduler or FakeScheduler()
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    result = handler_module.handler({"Records": records}, None, dynamodb_client=dynamo, scheduler_client=scheduler, now_seconds=now)
    return result, dynamo, scheduler


def test_a_status_change_is_a_change():
    assert handler_module.record_changed(record(old=PENDING, new=ACCEPTED))


@pytest.mark.parametrize("field", handler_module.CHANGE_FIELDS)
def test_each_public_field_is_a_change(field):
    assert handler_module.record_changed(record(old={field: "a"}, new={field: "b"}))


def test_an_edit_to_a_private_field_is_not_a_change():
    assert not handler_module.record_changed(record(old={**ACCEPTED, "curationStatusReason": "x"}, new={**ACCEPTED, "curationStatusReason": "y"}))


def test_insert_and_remove_are_changes_and_other_events_are_not():
    assert handler_module.record_changed(record("INSERT", new=PENDING))
    assert handler_module.record_changed(record("REMOVE", old=PENDING))
    assert not handler_module.record_changed({"eventName": "OTHER", "dynamodb": {}})


def test_a_change_schedules_one_run_at_the_end_of_the_window(monkeypatch):
    result, dynamo, scheduler = run([record(old=PENDING, new=ACCEPTED)], monkeypatch=monkeypatch)
    assert result["scheduled"] is True and result["runAt"] == NOW + 300
    [call] = scheduler.calls
    assert call["Name"].startswith("papyrus-home-page-snapshot-") and call["Name"].endswith(f"-{NOW + 300}")
    assert call["ActionAfterCompletion"] == "DELETE" and call["FlexibleTimeWindow"] == {"Mode": "OFF"}
    assert call["Target"]["Input"] == '{"projectionTask": {"task": "home-page-snapshot"}}'
    assert call["Target"]["RetryPolicy"] == {"MaximumRetryAttempts": 0}
    assert call["ScheduleExpression"].startswith("at(2027-01-15T")


def test_ten_accepts_in_one_window_schedule_one_run(monkeypatch):
    dynamo, scheduler = FakeDynamo(), FakeScheduler()
    for offset in range(10):
        run([record(old=PENDING, new=ACCEPTED)], dynamo, scheduler, now=NOW + offset * 20, monkeypatch=monkeypatch)
    assert len(scheduler.calls) == 1


def test_a_change_after_the_window_schedules_the_next_run(monkeypatch):
    dynamo, scheduler = FakeDynamo(), FakeScheduler()
    run([record(old=PENDING, new=ACCEPTED)], dynamo, scheduler, now=NOW, monkeypatch=monkeypatch)
    run([record(old=PENDING, new=ACCEPTED)], dynamo, scheduler, now=NOW + 301, monkeypatch=monkeypatch)
    assert len(scheduler.calls) == 2


def test_a_batch_with_nothing_changed_touches_nothing(monkeypatch):
    result, dynamo, scheduler = run([record(old=ACCEPTED, new={**ACCEPTED, "note": "x"})], monkeypatch=monkeypatch)
    assert result["scheduled"] is False and dynamo.puts == 0 and not scheduler.calls


def test_a_failed_schedule_releases_the_slot_and_raises(monkeypatch):
    dynamo = FakeDynamo()
    with pytest.raises(ClientError):
        run([record(old=PENDING, new=ACCEPTED)], dynamo, FakeScheduler("InternalServerException"), monkeypatch=monkeypatch)
    assert dynamo.items == {}
    _, _, scheduler = run([record(old=PENDING, new=ACCEPTED)], dynamo, monkeypatch=monkeypatch)
    assert len(scheduler.calls) == 1


def test_a_schedule_conflict_is_ignored_and_keeps_the_slot(monkeypatch):
    result, dynamo, _ = run([record(old=PENDING, new=ACCEPTED)], scheduler=FakeScheduler("ConflictException"), monkeypatch=monkeypatch)
    assert result["scheduled"] is False and len(dynamo.items) == 1


def test_two_sites_in_one_account_never_share_a_slot_or_a_schedule_name():
    other = "arn:aws:lambda:us-east-1:123456789012:function:content-actions-site-b"
    assert handler_module.scope_of(FUNCTION_ARN) != handler_module.scope_of(other)
    assert handler_module.schedule_name(handler_module.scope_of(FUNCTION_ARN), 5) != handler_module.schedule_name(handler_module.scope_of(other), 5)


def message_record(event_name: str, old: dict | None, new: dict) -> dict:
    images = {"NewImage": new}
    if old is not None:
        images["OldImage"] = old
    return {"eventName": event_name, "dynamodb": images}


COMMENT = {"messageKind": {"S": "comment"}, "status": {"S": "active"}, "content": {"S": "Hello"}}


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (message_record("INSERT", None, COMMENT), True),
        (message_record("MODIFY", None, {**COMMENT, "status": {"S": "deleted"}, "deletedAt": {"S": "2026-10-31T00:00:00Z"}}), True),
        (message_record("MODIFY", COMMENT, {**COMMENT, "status": {"S": "deleted"}}), True),
        (message_record("MODIFY", COMMENT, {**COMMENT, "content": {"S": "Edited"}, "editedAt": {"S": "2026-10-31T00:00:00Z"}}), True),
        (message_record("MODIFY", COMMENT, {**COMMENT, "responseStatus": {"S": "done"}}), False),
        (message_record("INSERT", None, {**COMMENT, "messageKind": {"S": "system"}}), False),
    ],
)
def test_message_records_change_only_when_a_public_field_does(record, expected):
    assert handler_module.record_changed(record) is expected


def test_a_posted_message_schedules_one_snapshot_for_the_end_of_the_window(monkeypatch):
    first, dynamo, scheduler = run([message_record("INSERT", None, COMMENT)], monkeypatch=monkeypatch)
    second, _, _ = run([message_record("INSERT", None, COMMENT)], dynamo, scheduler, NOW + 100, monkeypatch)
    assert first["scheduled"] is True and second["scheduled"] is False
    assert len(scheduler.calls) == 1 and scheduler.calls[0]["Name"].endswith(f"-{NOW + 300}")
