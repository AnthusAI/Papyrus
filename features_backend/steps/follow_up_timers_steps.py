"""Follow-up timers (features_backend/follow-up-timers.feature). A fake EventBridge Scheduler group that fires entries when a time arrives, a fake FIFO wake queue
with content-based deduplication, and a record store; no network. Scheduled publishing's own steps are reused for the last scenario."""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content import agent_wakes, follow_up_timers as fu  # noqa: E402
from papyrus_content.agent_definitions import schedules  # noqa: E402
from papyrus_content.story_schedule import EventBridgeScheduler  # noqa: E402
from schedule_fakes import ACCOUNT, ENDPOINT, REGION, WakeQueue  # noqa: E402

OWNER = "deliver"


class Exceptions:
    ConflictException = type("ConflictException", (Exception,), {})
    ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})


class TimerScheduler:
    """The parts of EventBridge Scheduler a one-shot entry uses: create (a second create of one name conflicts), update, delete, and firing at a time."""

    exceptions = Exceptions

    def __init__(self, group, queue):
        self.group, self.queue, self.entries, self.delivered = group, queue, {}, []

    def create_schedule(self, **entry):
        assert entry["GroupName"] == self.group, f"an entry outside the site's group: {entry['GroupName']}"
        if entry["Name"] in self.entries:
            raise self.exceptions.ConflictException()
        self.entries[entry["Name"]] = copy.deepcopy(entry)

    def update_schedule(self, **entry):
        assert entry["GroupName"] == self.group and entry["Name"] in self.entries
        self.entries[entry["Name"]] = copy.deepcopy(entry)

    def delete_schedule(self, Name, GroupName):  # noqa: N803
        assert GroupName == self.group
        if Name not in self.entries:
            raise self.exceptions.ResourceNotFoundException()
        del self.entries[Name]

    @staticmethod
    def at_of(entry):
        expression = entry["ScheduleExpression"]
        assert expression.startswith("at(") and entry["ScheduleExpressionTimezone"] == "UTC", expression
        return datetime.strptime(expression[3:-1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)

    def fire_until(self, moment):
        for name in sorted(self.entries, key=lambda n: self.at_of(self.entries[n])):
            entry = self.entries[name]
            if self.at_of(entry) <= moment:
                self.deliver(name, entry["Target"])
                if entry["ActionAfterCompletion"] == "DELETE":
                    del self.entries[name]

    def deliver(self, name, target):
        self.delivered.append((name, target))
        self.queue.send(target["Input"], target["SqsParameters"]["MessageGroupId"])


def utc(text):
    return datetime.strptime(text, fu.TIME_FORMAT).replace(tzinfo=timezone.utc)


@given('the site "{site}" with its follow-up timers and its wake queue')
def background(context, site):
    names = schedules.names_for(site)
    context.site_id, context.names, context.rows, context.error = site, names, {}, None
    context.queue = WakeQueue()
    context.fake_scheduler = TimerScheduler(names.group, context.queue)
    context.timers = fu.FollowUpTimers.for_site(site, account=ACCOUNT, region=REGION, client=context.fake_scheduler)
    context.queue_arn = f"arn:aws:sqs:{REGION}:{ACCOUNT}:{names.queue}"


@given('the delivery "{record}" waits for "{waiting_for}" until "{due_at}"')
@when('the delivery "{record}" now waits for "{waiting_for}" until "{due_at}"')
def waits(context, record, waiting_for, due_at):
    context.rows[record] = {"id": record, "dueAt": due_at, "waitingFor": waiting_for}


@when('the delivery "{record}" no longer waits')
def no_longer_waits(context, record):
    context.rows[record] = {"id": record}


@when('the delivery "{record}" is deleted')
def deleted(context, record):
    del context.rows[record]


@given('the site\'s follow-up timer is set for "{record}"')
@when('the site\'s follow-up timer is set for "{record}"')
def timer_set(context, record):
    base = {"appsyncEndpoint": ENDPOINT, "procedureKey": "newsroom.deliver", "publicationId": context.site_id, "input": {"deliveryId": record}}
    row = context.rows.get(record) or {}
    try:
        context.wake_key = context.timers.sync("Delivery", record, row.get("dueAt"), owner=OWNER, base=base, waiting_for=row.get("waitingFor"))
    except fu.FollowUpError as error:
        context.error = error


@given('the time "{moment}" arrives')
@when('the time "{moment}" arrives')
def arrives(context, moment):
    context.fake_scheduler.fire_until(utc(moment))


@when('the scheduler delivers the entry for "{record}" again')
def delivered_again(context, record):
    name = fu.entry_name("Delivery", record)
    target = next(target for delivered, target in reversed(context.fake_scheduler.delivered) if delivered == name)
    context.fake_scheduler.deliver(name, target)


@then("the site's timers hold exactly {count:d} entry")
@then("the site's timers hold exactly {count:d} entries")
def entry_count(context, count):
    assert len(context.fake_scheduler.entries) == count, sorted(context.fake_scheduler.entries)


@then('the entry fires once at "{due_at}" in UTC and is deleted after it runs')
def fires_once(context, due_at):
    (entry,) = context.fake_scheduler.entries.values()
    assert entry["ScheduleExpression"] == "at(" + due_at.rstrip("Z") + ")" and entry["ScheduleExpressionTimezone"] == "UTC", entry
    assert entry["ActionAfterCompletion"] == "DELETE" and entry["FlexibleTimeWindow"] == {"Mode": "OFF"} and entry["State"] == "ENABLED", entry
    assert entry["GroupName"] == context.names.group


@then('the follow-up entry\'s only target is the wake queue of "{site}"')
def only_target(context, site):
    (entry,) = context.fake_scheduler.entries.values()
    target = entry["Target"]
    assert target["Arn"] == context.queue_arn == f"arn:aws:sqs:{REGION}:{ACCOUNT}:{agent_wakes.queue_name(site)}", target
    assert target["RoleArn"].endswith(f":role/{context.names.role}"), target
    assert set(target) == {"Arn", "RoleArn", "Input", "SqsParameters"}, "no other target setting"
    body = json.loads(target["Input"])
    wake = agent_wakes.wake_of({**body["request"], "wakeKey": body["wake"]["key"]})
    assert target["SqsParameters"] == {"MessageGroupId": agent_wakes.group_id(wake)}


@then("the follow-up queue holds {count:d} message")
@then("the follow-up queue holds {count:d} messages")
def queue_count(context, count):
    assert len(context.queue.messages) == count, [m.body for m in context.queue.messages]


def first_wake(context):
    return json.loads(context.queue.messages[0].body)["wake"]


@then('the follow-up message\'s wake key is "{key}"')
def wake_key_is(context, key):
    assert [json.loads(m.body)["wake"]["key"] for m in context.queue.messages][-1] == key


@then('the follow-up message says in words that "{record}" was waiting until "{due_at}" for "{waiting_for}"')
def says_in_words(context, record, due_at, waiting_for):
    assert first_wake(context)["why"] == f"{record} was waiting until {due_at} ({waiting_for})", first_wake(context)


@then("nothing went wrong")
def nothing_wrong(context):
    assert context.error is None


@then('the entry\'s name does not begin with "{prefix}"')
def name_prefix(context, prefix):
    (name,) = context.fake_scheduler.entries
    assert not name.startswith(prefix) and name.startswith(fu.ENTRY_PREFIX) and len(name) <= 64, name


@then("the follow-up is refused because a due time is a UTC instant")
def refused(context):
    assert isinstance(context.error, fu.FollowUpError) and "UTC instant" in str(context.error), context.error


@when("the run reads the record for the wake on the queue")
def run_reads(context):
    body = context.queue.messages[0].body
    request = agent_wakes.request_from_event({"Records": [{"eventSource": "aws:sqs", "body": body}]})
    context.answer = fu.check_wake(request["wakeKey"], context.rows.get(request["input"]["deliveryId"]))


@then('the record still waits for "{due_at}" and the run goes on')
def goes_on(context, due_at):
    assert context.answer["waiting"] is True and context.answer["dueAt"] == due_at, context.answer


@then('the run does nothing and says "{reason}"')
def does_nothing(context, reason):
    assert context.answer["waiting"] is False and reason in context.answer["reason"], context.answer


# --- scheduled publishing through the same helper -------------------------------------------------------------------------------------------------


class RecordingApi:
    exceptions = Exceptions

    def __init__(self):
        self.created, self.updated, self.deleted, self.conflict = [], [], [], False

    def create_schedule(self, **parameters):
        if self.conflict:
            raise self.exceptions.ConflictException()
        self.created.append(parameters)

    def update_schedule(self, **parameters):
        self.updated.append(parameters)

    def delete_schedule(self, **parameters):
        self.deleted.append(parameters)


@then("scheduled publishing makes its timer through the follow-up helper, in the default group, delivering to the content-actions function")
def publishing_uses_helper(context):
    context.api = RecordingApi()
    scheduler = EventBridgeScheduler(function_arn="arn:aws:lambda:us-east-1:1:function:f", role_arn="arn:aws:iam::1:role/r", dead_letter_arn="arn:aws:sqs:us-east-1:1:dlq",
                                     name_prefix="papyrus-pub-test-", client=context.api)
    assert isinstance(scheduler.timers, fu.OneShotSchedules)
    context.scheduler_under_test, context.name = scheduler, scheduler.name_for("item-1")
    scheduler.upsert(context.name, "item-1", "2026-11-13T14:00:00Z")
    parameters = context.api.created[0]
    assert "GroupName" not in parameters, "scheduled publishing stays in the account's default group"
    assert parameters["ScheduleExpression"] == "at(2026-11-13T14:00:00)" and parameters["ActionAfterCompletion"] == "DELETE", parameters
    assert parameters["Target"]["Arn"].endswith(":function:f") and parameters["Target"]["DeadLetterConfig"] == {"Arn": "arn:aws:sqs:us-east-1:1:dlq"}, parameters["Target"]
    assert json.loads(parameters["Target"]["Input"])["projectionTask"]["task"] == "publish-scheduled"


@then("moving or clearing that timer uses the helper's replace and delete")
def publishing_moves_and_clears(context):
    context.api.conflict = True
    context.scheduler_under_test.upsert(context.name, "item-1", "2026-11-13T16:00:00Z")
    assert context.api.updated[0]["ScheduleExpression"] == "at(2026-11-13T16:00:00)" and context.api.updated[0]["Name"] == context.name
    context.scheduler_under_test.delete(context.name)
    assert context.api.deleted == [{"Name": context.name}]
