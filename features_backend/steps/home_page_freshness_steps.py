from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

HANDLER_PATH = REPO_ROOT / "amplify" / "plugins" / "home-page" / "function" / "handler.py"
PLUGIN_TEST = REPO_ROOT / "scripts" / "test-home-page-plugin.ts"
START = 1_800_000_000
KEYS = {"id": {"S": "reference-1-v1"}}
ACCEPTED_RECORD = {"eventName": "MODIFY", "dynamodb": {"Keys": KEYS, "OldImage": {"curationStatus": {"S": "pending"}}, "NewImage": {"curationStatus": {"S": "accepted"}}}}
PRIVATE_RECORD = {
    "eventName": "MODIFY",
    "dynamodb": {"Keys": KEYS, "OldImage": {"curationStatus": {"S": "accepted"}, "curationStatusReason": {"S": "a"}}, "NewImage": {"curationStatus": {"S": "accepted"}, "curationStatusReason": {"S": "b"}}},
}


def load_handler():
    specification = importlib.util.spec_from_file_location("home_page_trigger_handler_steps", HANDLER_PATH)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class StepError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class LockTable:
    def __init__(self) -> None:
        self.items: dict[str, int] = {}
        self.claims = 0
        self.ids: dict[str, set[str]] = {}
        self.counters: dict[tuple[str, str], int] = {}

    def put_item(self, *, TableName, Item, ConditionExpression, ExpressionAttributeValues):
        key = Item["publication"]["S"]
        if key in self.items and self.items[key] > int(ExpressionAttributeValues[":now"]["N"]):
            raise StepError("ConditionalCheckFailedException")
        self.claims += 1
        self.items[key] = int(Item["lockedUntil"]["N"])

    def update_item(self, *, TableName, Key, UpdateExpression, ExpressionAttributeValues, ReturnValues=None):
        key = Key["publication"]["S"]
        if UpdateExpression == "ADD ids :ids":
            held = self.ids.setdefault(key, set())
            held |= set(ExpressionAttributeValues[":ids"]["SS"])
            return {"Attributes": {"ids": {"SS": sorted(held)}}}
        attribute = UpdateExpression.removeprefix("ADD ").split(" ")[0]
        self.counters[(key, attribute)] = self.counters.get((key, attribute), 0) + int(next(iter(ExpressionAttributeValues.values()))["N"])
        return {}

    def delete_item(self, *, TableName, Key, ConditionExpression, ExpressionAttributeValues):
        key = Key["publication"]["S"]
        if self.items.get(key) != int(ExpressionAttributeValues[":until"]["N"]):
            raise StepError("ConditionalCheckFailedException")
        del self.items[key]


class Scheduler:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail = False

    def create_schedule(self, **arguments):
        if self.fail:
            raise StepError("InternalServerException")
        self.calls.append(arguments)


class Site:
    def __init__(self, handler, lock_table: LockTable, scheduler: Scheduler, function_name: str, window: int, thread_window: int | None = None) -> None:
        self.handler = handler
        self.lock_table = lock_table
        self.scheduler = scheduler
        self.environment = {
            "PAPYRUS_HOME_PAGE_SNAPSHOT_FUNCTION_ARN": f"arn:aws:lambda:us-east-1:123456789012:function:{function_name}",
            "PAPYRUS_HOME_PAGE_SCHEDULER_ROLE_ARN": "arn:aws:iam::123456789012:role/scheduler",
            "PAPYRUS_HOME_PAGE_DEBOUNCE_SECONDS": str(window),
            "PAPYRUS_PROJECTION_LOCK_TABLE": "papyrus-projection-locks",
        }
        if thread_window is not None:
            self.environment["PAPYRUS_HOME_PAGE_THREAD_DEBOUNCE_SECONDS"] = str(thread_window)

    def receive(self, records: list[dict], seconds_after_start: float):
        previous = dict(os.environ)
        os.environ.update(self.environment)
        try:
            return self.handler.handler({"Records": records}, None, dynamodb_client=self.lock_table, scheduler_client=self.scheduler, now_seconds=START + seconds_after_start)
        finally:
            os.environ.clear()
            os.environ.update(previous)


@given("a trigger function with a {window:d} second debounce window")
def trigger_with_window(context, window: int) -> None:
    context.window = window
    context.site = Site(load_handler(), LockTable(), Scheduler(), "content-actions-a", window)


@given("a trigger function with a {window:d} second debounce window and a {thread_window:d} second thread window")
def trigger_with_thread_window(context, window: int, thread_window: int) -> None:
    context.window = window
    context.site = Site(load_handler(), LockTable(), Scheduler(), "content-actions-a", window, thread_window)


@given("two sites whose trigger functions share one lock table")
def two_sites(context) -> None:
    handler, lock_table = load_handler(), LockTable()
    context.sites = [Site(handler, lock_table, Scheduler(), name, 300) for name in ("content-actions-a", "content-actions-b")]
    context.lock_table = lock_table


@when("a Reference is accepted")
def reference_accepted(context) -> None:
    context.site.receive([ACCEPTED_RECORD], 0)


@when("ten References are accepted over the next {span:d} seconds")
def ten_accepted(context, span: int) -> None:
    for number in range(10):
        context.site.receive([ACCEPTED_RECORD], number * span / 9)


MESSAGE_COMMENT = {"messageKind": {"S": "comment"}, "status": {"S": "active"}, "content": {"S": "Hello"}}


@when("a Message is posted")
def message_posted(context) -> None:
    context.site.receive([{"eventName": "INSERT", "dynamodb": {"NewImage": MESSAGE_COMMENT}}], 0)


@when("another Message is posted {later:d} seconds later")
def message_posted_later(context, later: int) -> None:
    context.site.receive([{"eventName": "INSERT", "dynamodb": {"NewImage": MESSAGE_COMMENT}}], later)


@when("a Message is posted {later:d} seconds later")
def message_posted_at(context, later: int) -> None:
    context.site.receive([{"eventName": "INSERT", "dynamodb": {"NewImage": MESSAGE_COMMENT}}], later)


@when("a Message changes only a private field")
def message_private_change(context) -> None:
    changed = {**MESSAGE_COMMENT, "responseStatus": {"S": "done"}}
    context.site.receive([{"eventName": "MODIFY", "dynamodb": {"OldImage": MESSAGE_COMMENT, "NewImage": changed}}], 0)


@when("a Message is soft-deleted")
def message_soft_deleted(context) -> None:
    deleted = {**MESSAGE_COMMENT, "status": {"S": "deleted"}, "deletedAt": {"S": "2026-10-31T00:00:00.000Z"}}
    context.site.receive([{"eventName": "MODIFY", "dynamodb": {"OldImage": MESSAGE_COMMENT, "NewImage": deleted}}], 0)


def reference_record(identifier: str, old: dict, new: dict, event: str = "MODIFY") -> dict:
    images = {"Keys": {"id": {"S": identifier}}, "NewImage": new}
    if event == "MODIFY":
        images["OldImage"] = old
    return {"eventName": event, "dynamodb": images}


PENDING_IMAGE = {"curationStatus": {"S": "pending"}, "title": {"S": "A"}}
PREDICTION = {"predictionDecidedAt": {"S": "2026-11-04T10:00:00.000Z"}, "predictedAcceptProbability": {"N": "0.9"}, "predictionSortKey": {"S": "0.900000#a#b"}}


@when("a pending Reference is delivered that nobody has predicted")
def pending_delivered(context) -> None:
    context.site.receive([reference_record("reference-new-v1", {}, PENDING_IMAGE, "INSERT")], 0)


@when("the Cyclotron's first prediction is written onto a pending Reference")
def first_prediction(context) -> None:
    context.site.receive([reference_record("reference-new-v1", PENDING_IMAGE, {**PENDING_IMAGE, **PREDICTION})], 0)


THUMBNAIL = {"S": "assets/reference-thumbnails/a4645fd6b3de98f4-bb02a57c6adf.jpg"}


@when("a decision time and a sort key are written onto a pending Reference without a probability")
def decision_time_and_sort_key(context) -> None:
    written = {**PENDING_IMAGE, "predictionDecidedAt": {"S": "2026-11-04T10:00:00.000Z"}, "predictionSortKey": {"S": "0.500000#a#b"}}
    context.site.receive([reference_record("reference-new-v1", PENDING_IMAGE, written)], 0)


@when("the picture of a video is stored on a pending Reference nobody has predicted")
def thumbnail_stored(context) -> None:
    context.site.receive([reference_record("reference-video-v1", PENDING_IMAGE, {**PENDING_IMAGE, "thumbnailPath": THUMBNAIL})], 0)


@when("the Cyclotron's first prediction is written onto that Reference")
def first_prediction_on_video(context) -> None:
    pictured = {**PENDING_IMAGE, "thumbnailPath": THUMBNAIL}
    context.site.receive([reference_record("reference-video-v1", pictured, {**pictured, **PREDICTION})], 0)


@when("an unpredicted pending Reference is retitled and rated")
def unpredicted_edited(context) -> None:
    context.site.receive([reference_record("reference-new-v1", PENDING_IMAGE, {**PENDING_IMAGE, "title": {"S": "B"}, "starRating": {"N": "5"}})], 0)


@when("ten changes arrive for three different References")
def ten_changes_three_references(context) -> None:
    for number in range(10):
        context.site.receive([reference_record(f"reference-{number % 3}-v1", PENDING_IMAGE, {"curationStatus": {"S": "accepted"}, "title": {"S": f"T{number}"}})], number)


@when("{count:d} References are accepted in one batch")
def many_accepted(context, count: int) -> None:
    context.site.receive([reference_record(f"reference-{number}-v1", PENDING_IMAGE, {"curationStatus": {"S": "accepted"}, "title": {"S": "A"}}) for number in range(count)], 0)


@then("the run's list holds exactly those {count:d} Reference ids")
def list_holds(context, count: int) -> None:
    [listed] = context.site.lock_table.ids.values()
    assert listed == {f"reference-{number}-v1" for number in range(count)}, listed


@then("the full-read flag is raised once")
def full_read_flag(context) -> None:
    flags = {key: value for key, value in context.site.lock_table.counters.items() if key[0].startswith("home-page-full#")}
    assert list(flags.values()) == [1], context.site.lock_table.counters


@when("another Reference is accepted {later:d} seconds later")
def accepted_later(context, later: int) -> None:
    context.site.receive([ACCEPTED_RECORD], later)


@when("a Reference changes only a private field")
def private_change(context) -> None:
    context.site.receive([PRIVATE_RECORD], 0)


@when("a Reference is rated")
def reference_rated(context) -> None:
    context.site.receive([{"eventName": "MODIFY", "dynamodb": {"Keys": KEYS, "OldImage": {"curationStatus": {"S": "accepted"}}, "NewImage": {"curationStatus": {"S": "accepted"}, "starRating": {"N": "5"}}}}], 0)


@when("an accepted Reference changes from {before:d} stars to {after:d} and nothing else")
def stars_changed(context, before: int, after: int) -> None:
    accepted = {"curationStatus": {"S": "accepted"}, "starRatedBy": {"S": "a"}, "starRatedAt": {"S": "t1"}}
    context.site.receive([{"eventName": "MODIFY", "dynamodb": {"Keys": KEYS, "OldImage": {**accepted, "starRating": {"N": str(before)}}, "NewImage": {**accepted, "starRating": {"N": str(after)}}}}], 0)


@when("a Reference changes only who rated it")
def rater_changed(context) -> None:
    rated = {"curationStatus": {"S": "accepted"}, "starRating": {"N": "5"}}
    context.site.receive([{"eventName": "MODIFY", "dynamodb": {"Keys": KEYS, "OldImage": {**rated, "starRatedBy": {"S": "a"}, "starRatedAt": {"S": "t1"}}, "NewImage": {**rated, "starRatedBy": {"S": "b"}, "starRatedAt": {"S": "t2"}}}}], 0)


@when("a Reference is accepted and creating the schedule fails")
def accepted_and_failing(context) -> None:
    context.site.scheduler.fail = True
    try:
        context.site.receive([ACCEPTED_RECORD], 0)
    except StepError:
        context.raised = True
    context.site.scheduler.fail = False


@when("another Reference is accepted")
def another_accepted(context) -> None:
    context.site.receive([ACCEPTED_RECORD], 1)


@when("a Reference is accepted on each site")
def accepted_on_each(context) -> None:
    for site in context.sites:
        site.receive([ACCEPTED_RECORD], 0)


@then("one home-page snapshot run is scheduled for {seconds:d} seconds later")
def one_run_scheduled(context, seconds: int) -> None:
    calls = context.site.scheduler.calls
    assert len(calls) == 1, f"{len(calls)} schedules: {[call['Name'] for call in calls]}"
    assert calls[0]["Name"].endswith(f"-{START + seconds}"), calls[0]["Name"]
    context.schedule = calls[0]


@then("a home-page snapshot run is scheduled for {seconds:d} seconds after the start")
def a_run_scheduled_at(context, seconds: int) -> None:
    names = [call["Name"] for call in context.site.scheduler.calls]
    assert any(name.endswith(f"-{START + seconds}") for name in names), names


@then("one home-page snapshot run is scheduled for {seconds:d} seconds after that")
def one_run_scheduled_after_retry(context, seconds: int) -> None:
    calls = context.site.scheduler.calls
    assert len(calls) == 1, [call["Name"] for call in calls]
    assert calls[0]["Name"].endswith(f"-{START + 1 + seconds}"), calls[0]["Name"]


@then("{count:d} home-page snapshot runs are scheduled")
def runs_scheduled(context, count: int) -> None:
    assert len(context.site.scheduler.calls) == count, [call["Name"] for call in context.site.scheduler.calls]


@then("the schedule runs the home-page-snapshot task once and deletes itself afterwards")
def schedule_shape(context) -> None:
    call = context.schedule
    assert call["Name"].startswith("papyrus-home-page-snapshot-")
    task = json.loads(call["Target"]["Input"])["projectionTask"]
    assert task["task"] == "home-page-snapshot" and task["incremental"] is True and task["scope"]
    assert call["Target"]["RetryPolicy"] == {"MaximumRetryAttempts": 0}
    assert call["ActionAfterCompletion"] == "DELETE"
    assert call["FlexibleTimeWindow"] == {"Mode": "OFF"}


@then("no home-page snapshot run is scheduled")
def nothing_scheduled(context) -> None:
    assert context.site.scheduler.calls == []


@then("no debounce slot is claimed")
def nothing_claimed(context) -> None:
    assert context.site.lock_table.claims == 0 and context.site.lock_table.items == {}


@then("the debounce slot is open again")
def slot_open(context) -> None:
    assert context.raised, "the failure should reach the stream so the batch is retried"
    assert context.site.lock_table.items == {}


@then("each site has its own home-page snapshot run scheduled")
def each_site_scheduled(context) -> None:
    for site in context.sites:
        assert len(site.scheduler.calls) == 1
    assert len(context.lock_table.items) == 2


def plugin_behaviours(context, *names: str) -> None:
    for name in names:
        result = subprocess.run(
            ["node", "--import", "tsx", str(PLUGIN_TEST), name], cwd=REPO_ROOT, capture_output=True, text=True, timeout=240
        )
        assert result.returncode == 0, f"{name} failed:\n{result.stdout}\n{result.stderr}"
    context.plugin_behaviours = names


@when("a site asks for the home-page plugin without naming a purge setting")
def default_purge(context) -> None:
    plugin_behaviours(context, "the_defaults_are_justified_and_configurable", "purge_is_off_unless_the_site_turns_it_on")


@when("a site synthesizes its backend without the home-page plugin")
def synth_without(context) -> None:
    plugin_behaviours(context, "a_site_that_does_not_ask_for_the_plugin_synthesizes_no_new_resource", "the_plugin_is_opt_in_by_name")


@when("a site synthesizes its backend with the home-page plugin")
def synth_with(context) -> None:
    plugin_behaviours(context, "the_plugin_adds_the_stream_the_trigger_the_scheduler_and_nothing_else", "plain_cloudformation_tables_are_found_by_name_too")


@when("a site synthesizes its backend with the home-page plugin and threads enabled")
def synth_threads(context) -> None:
    plugin_behaviours(context, "threads_enabled_adds_the_message_stream_to_the_same_trigger", "an_existing_message_stream_is_reused_and_never_replaced")


@when("a site asks for the home-page plugin with an interval of 6 hours")
def synth_interval(context) -> None:
    plugin_behaviours(context, "an_interval_adds_one_rule_that_runs_the_snapshot_task")


@when("a site asks for the home-page plugin without a publication or without a homePage setting")
def synth_refused(context) -> None:
    plugin_behaviours(context, "the_plugin_needs_a_publication", "a_site_with_the_plugin_but_no_home_page_setting_is_refused")


@then("purge is off and the debounce window is 300 seconds")
@then("no stack changes, no stack is added and no output is added")
@then("the Reference table is left as it was")
@then("the Reference table streams old and new images to one trigger function")
@then("the trigger function may create only schedules named for the home-page snapshot and pass only the scheduler role")
@then("the debounce window reaches the trigger function")
@then("the Message table feeds the same trigger function through its own filter")
@then("a Message stream that already exists is reused and not replaced")
@then("one rule runs the home-page-snapshot task every 6 hours without retries")
@then("a site that sets no interval gets no rule")
@then("the backend refuses to synthesize and says what is missing")
def plugin_behaviour_held(context) -> None:
    assert context.plugin_behaviours
