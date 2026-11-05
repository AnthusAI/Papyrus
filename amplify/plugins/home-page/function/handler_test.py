from __future__ import annotations

import importlib.util
import json
import sys
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
    """The lock table as the trigger sees it: the debounce slot, the set of changed ids, the Message counter and the full-read flag."""

    def __init__(self, item_limit: int | None = None) -> None:
        self.items: dict[str, int] = {}
        self.puts = 0
        self.updates: list[dict] = []
        self.ids: dict[str, set[str]] = {}
        self.counters: dict[tuple[str, str], int] = {}
        self.item_limit = item_limit

    def put_item(self, *, TableName, Item, ConditionExpression, ExpressionAttributeValues):
        self.puts += 1
        key = Item["publication"]["S"]
        now = int(ExpressionAttributeValues[":now"]["N"])
        if key in self.items and self.items[key] > now:
            raise ClientError("ConditionalCheckFailedException")
        self.items[key] = int(Item["lockedUntil"]["N"])

    def update_item(self, *, TableName, Key, UpdateExpression, ExpressionAttributeValues, ReturnValues=None):
        key = Key["publication"]["S"]
        self.updates.append({"key": key, "expression": UpdateExpression})
        if UpdateExpression == "ADD ids :ids":
            held = self.ids.setdefault(key, set())
            if self.item_limit is not None and len(held | set(ExpressionAttributeValues[":ids"]["SS"])) > self.item_limit:
                raise ClientError("ValidationException")
            held |= set(ExpressionAttributeValues[":ids"]["SS"])
            return {"Attributes": {"ids": {"SS": sorted(held)}}}
        attribute = UpdateExpression.removeprefix("ADD ").split(" ")[0]
        amount = int(next(iter(ExpressionAttributeValues.values()))["N"])
        self.counters[(key, attribute)] = self.counters.get((key, attribute), 0) + amount
        return {}

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


def typed(attributes: dict | None) -> dict:
    """Plain values as DynamoDB stream images carry them: strings as S, and a value that is already typed (a dict) as it is."""
    return {name: value if isinstance(value, dict) else {"S": value} for name, value in (attributes or {}).items()}


def record(event_name="MODIFY", old=None, new=None, identifier="reference-1-v1"):
    images = {"Keys": {"id": {"S": identifier}}}
    if old is not None:
        images["OldImage"] = typed(old)
    if new is not None:
        images["NewImage"] = typed(new)
    return {"eventName": event_name, "dynamodb": images}


PREDICTED = {"predictionDecidedAt": "2026-11-04T10:00:00.000Z", "predictedAcceptProbability": {"N": "0.9"}}
PENDING = {"curationStatus": "pending", "title": "A"}
PENDING_PREDICTED = {**PENDING, **PREDICTED}
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
    old, new = ("pending", "accepted") if field == "curationStatus" else ({"N": "0.7"}, {"N": "0.8"}) if field == "predictedAcceptProbability" else ("a", "b")
    assert handler_module.record_changed(record(old={**PENDING_PREDICTED, field: old}, new={**PENDING_PREDICTED, field: new}))


def test_an_edit_to_a_private_field_is_not_a_change():
    assert not handler_module.record_changed(record(old={**ACCEPTED, "curationStatusReason": "x"}, new={**ACCEPTED, "curationStatusReason": "y"}))


def test_rating_changing_or_clearing_a_rating_is_a_change_but_who_rated_and_when_is_not():
    assert handler_module.record_changed(record(old=ACCEPTED, new={**ACCEPTED, "starRating": {"N": "5"}}))
    assert handler_module.record_changed(record(old={**ACCEPTED, "starRating": {"N": "5"}}, new={**ACCEPTED, "starRating": {"N": "2"}}))
    assert handler_module.record_changed(record(old={**ACCEPTED, "starRating": {"N": "5"}}, new=ACCEPTED)), "clearing a rating changes the order"
    rated = {**ACCEPTED, "starRating": {"N": "5"}, "starRatedBy": {"S": "a"}, "starRatedAt": {"S": "t1"}}
    assert not handler_module.record_changed(record(old=rated, new={**rated, "starRatedBy": {"S": "b"}, "starRatedAt": {"S": "t2"}}))


def test_insert_and_remove_of_a_reference_a_page_can_show_are_changes_and_other_events_are_not():
    assert handler_module.record_changed(record("INSERT", new=ACCEPTED))
    assert handler_module.record_changed(record("INSERT", new=PENDING_PREDICTED))
    assert handler_module.record_changed(record("REMOVE", old=ACCEPTED))
    assert not handler_module.record_changed({"eventName": "OTHER", "dynamodb": {}})


def test_a_new_pending_reference_changes_no_page():
    """A monitor delivers dozens of pending References an hour: nobody has predicted one yet, so none can be recommended, and none runs the snapshot."""
    assert not handler_module.record_changed(record("INSERT", new=PENDING))
    assert not handler_module.record_changed(record("INSERT", new={**PENDING, "predictionDecidedAt": {"NULL": True}}))


def test_only_a_stored_probability_is_a_prediction_not_a_decision_time_nor_a_sort_key():
    """Ryan, 2026-11-05: an unpredicted Reference is not 50% and shows nothing. Every Reference has a ``predictionSortKey`` from creation (``0.500000#...``)."""
    sort_key_only = {**PENDING, "predictionSortKey": {"S": "0.500000#2026-11-04T18:49:50.761Z#reference-a-v1"}}
    assert not handler_module.can_show(typed(sort_key_only))
    assert not handler_module.can_show(typed({**sort_key_only, "predictionDecidedAt": {"S": "2026-11-04T10:00:00.000Z"}}))
    assert not handler_module.can_show(typed({**PENDING, "predictedAcceptProbability": {"NULL": True}}))
    assert not handler_module.can_show(typed({**PENDING, "predictedAcceptProbability": {"S": "0.9"}}))
    assert handler_module.can_show(typed({**PENDING, "predictedAcceptProbability": {"N": "0.5"}})), "a prediction of exactly 0.5 is still a prediction"
    assert handler_module.can_show(typed({**PENDING, "predictedAcceptProbability": {"N": "0"}})), "so is a certain reject"
    assert not handler_module.record_changed(record(old=PENDING, new={**sort_key_only, "predictionDecidedAt": {"S": "t"}}))


def test_the_picture_of_a_video_on_an_unpredicted_pending_reference_changes_no_page_until_the_first_prediction():
    """It is on no page, so its picture has nothing to update; when the first prediction arrives the run reads the row, picture included."""
    picture = {"thumbnailPath": {"S": "assets/reference-thumbnails/a.jpg"}}
    assert not handler_module.record_changed(record(old=PENDING, new={**PENDING, **picture}))
    assert handler_module.record_changed(record(old={**PENDING, **picture}, new={**PENDING, **picture, **PREDICTED}))


def test_the_first_prediction_of_a_pending_reference_is_a_change_because_it_may_be_recommended():
    assert handler_module.record_changed(record(old=PENDING, new={**PENDING, **PREDICTED, "predictionSortKey": "0.900000#a#b"}))


def test_a_machine_field_written_on_a_reference_that_cannot_show_changes_no_page():
    assert not handler_module.record_changed(record(old=PENDING, new={**PENDING, "title": "Retitled by the intake"}))
    assert not handler_module.record_changed(record(old=PENDING, new={**PENDING, "starRating": {"N": "5"}})), "an unpredicted pending Reference is not on any page, rated or not"
    assert not handler_module.record_changed(record(old={**PENDING, "curationStatus": "rejected"}, new={**PENDING, "curationStatus": "archived"}))


def test_a_predicted_pending_reference_that_is_retitled_rated_or_rejected_is_a_change():
    assert handler_module.record_changed(record(old=PENDING_PREDICTED, new={**PENDING_PREDICTED, "title": "B"}))
    assert handler_module.record_changed(record(old=PENDING_PREDICTED, new={**PENDING_PREDICTED, "starRating": {"N": "4"}}))
    assert handler_module.record_changed(record(old=PENDING_PREDICTED, new={**PENDING_PREDICTED, "curationStatus": "rejected"})), "it leaves the recommended list"


def test_a_machine_field_on_a_page_reference_is_not_a_change():
    assert not handler_module.record_changed(record(old=ACCEPTED, new={**ACCEPTED, "discoveryDetails": "{}", "updatedAt": "t"}))


def test_a_change_schedules_one_run_at_the_end_of_the_window(monkeypatch):
    result, dynamo, scheduler = run([record(old=PENDING, new=ACCEPTED)], monkeypatch=monkeypatch)
    assert result["scheduled"] is True and result["runAt"] == NOW + 300
    [call] = scheduler.calls
    assert call["Name"].startswith("papyrus-home-page-snapshot-") and call["Name"].endswith(f"-{NOW + 300}")
    assert call["ActionAfterCompletion"] == "DELETE" and call["FlexibleTimeWindow"] == {"Mode": "OFF"}
    assert json.loads(call["Target"]["Input"]) == {"projectionTask": {"task": "home-page-snapshot", "incremental": True, "scope": handler_module.scope_of(FUNCTION_ARN)}}
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
    result, dynamo, scheduler = run([record(old=ACCEPTED, new={**ACCEPTED, "note": "x"}), record("INSERT", new=PENDING)], monkeypatch=monkeypatch)
    assert result["scheduled"] is False and dynamo.puts == 0 and not dynamo.updates and not scheduler.calls


def test_the_ids_of_the_changed_references_are_listed_for_the_run(monkeypatch):
    scope = handler_module.scope_of(FUNCTION_ARN)
    records = [record(old=PENDING, new=ACCEPTED, identifier="reference-a-v1"), record(old=PENDING, new=ACCEPTED, identifier="reference-b-v1"), record("INSERT", new=PENDING, identifier="reference-c-v1")]
    _, dynamo, _ = run(records, monkeypatch=monkeypatch)
    assert dynamo.ids == {handler_module.dirty_key(scope): {"reference-a-v1", "reference-b-v1"}}
    run([record(old=PENDING, new=ACCEPTED, identifier="reference-d-v1")], dynamo, now=NOW + 5, monkeypatch=monkeypatch)
    assert dynamo.ids[handler_module.dirty_key(scope)] == {"reference-a-v1", "reference-b-v1", "reference-d-v1"}, "later changes in the window extend the list"


def test_a_removed_reference_that_could_show_is_listed(monkeypatch):
    _, dynamo, _ = run([record("REMOVE", old=ACCEPTED, identifier="reference-gone-v1")], monkeypatch=monkeypatch)
    assert dynamo.ids[handler_module.dirty_key(handler_module.scope_of(FUNCTION_ARN))] == {"reference-gone-v1"}


def test_a_window_with_more_changes_than_the_list_can_hold_asks_for_a_full_read(monkeypatch):
    scope = handler_module.scope_of(FUNCTION_ARN)
    many = [record(old=PENDING, new=ACCEPTED, identifier=f"reference-{index}-v1") for index in range(handler_module.DIRTY_LIMIT + 1)]
    _, dynamo, _ = run(many, monkeypatch=monkeypatch)
    assert dynamo.counters == {(handler_module.full_key(scope), "seq"): 1}


def test_an_item_that_is_full_asks_for_a_full_read_instead_of_losing_the_change(monkeypatch):
    scope = handler_module.scope_of(FUNCTION_ARN)
    dynamo = FakeDynamo(item_limit=1)
    run([record(old=PENDING, new=ACCEPTED, identifier="a"), record(old=PENDING, new=ACCEPTED, identifier="b")], dynamo, monkeypatch=monkeypatch)
    assert dynamo.counters == {(handler_module.full_key(scope), "seq"): 1}


def test_the_names_of_the_items_are_the_names_the_task_reads():
    """The trigger carries no papyrus_content, so the two sides spell the item names separately; this keeps them the same."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
    from papyrus_content.home_page import runtime, state_store

    assert handler_module.scope_of(FUNCTION_ARN) == runtime.scope_of(FUNCTION_ARN.rsplit(":", 1)[-1])
    assert handler_module.dirty_key("abc") == state_store.dirty_key("abc") and handler_module.full_key("abc") == state_store.full_key("abc")


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


def test_a_changed_message_raises_a_counter_and_lists_no_id(monkeypatch):
    scope = handler_module.scope_of(FUNCTION_ARN)
    _, dynamo, _ = run([message_record("INSERT", None, COMMENT)], monkeypatch=monkeypatch)
    assert dynamo.counters == {(handler_module.dirty_key(scope), "messageSeq"): 1} and dynamo.ids == {}


def test_a_posted_message_schedules_one_snapshot_for_the_end_of_the_window(monkeypatch):
    first, dynamo, scheduler = run([message_record("INSERT", None, COMMENT)], monkeypatch=monkeypatch)
    second, _, _ = run([message_record("INSERT", None, COMMENT)], dynamo, scheduler, NOW + 100, monkeypatch)
    assert first["scheduled"] is True and second["scheduled"] is False
    assert len(scheduler.calls) == 1 and scheduler.calls[0]["Name"].endswith(f"-{NOW + 300}")


def test_writing_the_public_blocks_attributes_alone_changes_no_page():
    """The five attributes of the public index (PPY-7f1e54) are copies of facts this function already watches, or of the preview. The backfill writes them to every
    public row, so a write of them alone must not schedule a snapshot (it would be one run per backfill, for nothing)."""
    written = {"publicFeedKey": "c#accepted", "publicOrderKey": "p0.800000#2026-11-02T12:00:00.000Z#r", "cardImage": "https://img.example.org/a.jpg",
               "cardSummary": "A summary.", "cardSiteName": "Example", "cardPageTitle": "A title"}
    assert not handler_module.record_changed(record(old=ACCEPTED, new={**ACCEPTED, **written}))
    assert not handler_module.record_changed(record(old=PENDING_PREDICTED, new={**PENDING_PREDICTED, **written}))
    assert not set(written) & set(handler_module.CHANGE_FIELDS)
