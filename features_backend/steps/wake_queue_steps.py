from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from unittest import mock

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import automation_fixture as fx  # noqa: E402
import test_automation_run_now as run_now_tests  # noqa: E402
import test_procedure_runner as tpr  # noqa: E402
import test_story_triggers as stage_tests  # noqa: E402
from papyrus_content import agent_wakes, automations, graphql_authoring, model_attachments, procedure_runner as pr, wake_keys  # noqa: E402
from papyrus_content.agent_policy import PersonStart  # noqa: E402
from papyrus_content.automations import MonitoringReader, MonitoringWriter  # noqa: E402

MAXIMUM_RECEIVES = 2   # amplify/agents/wake-queue.ts: a wake is delivered at most twice, then the dead-letter queue takes it


class Message:
    def __init__(self, number, body, group, dedupe):
        self.id, self.body, self.group, self.dedupe, self.receives, self.held = f"message-{number}", body, group, dedupe, 0, False


class FakeQueue:
    """The rules of an SQS FIFO queue that Papyrus relies on: only the first message of a group can be received, and not while another of its
    group is held; a repeated deduplication id inside the window is dropped; a message received more than twice moves to the dead-letter queue."""

    def __init__(self):
        self.messages, self.dead_letters, self.window, self.sent = [], [], set(), 0

    def send(self, body, group, dedupe):
        self.sent += 1
        if dedupe in self.window:
            return
        self.window.add(dedupe)
        self.messages.append(Message(self.sent, body, group, dedupe))

    def receive(self):
        seen = set()
        for message in list(self.messages):
            if message.group in seen:
                continue
            seen.add(message.group)
            if message.held:
                continue
            if message.receives >= MAXIMUM_RECEIVES:
                self.messages.remove(message)
                self.dead_letters.append(message)
                seen.discard(message.group)
                continue
            message.receives, message.held = message.receives + 1, True
            return message
        return None

    def delete(self, message):
        self.messages.remove(message)

    def release(self, message):
        message.held = False


class FakeSqs:
    def __init__(self):
        self.queues, self.sends = {}, []

    def get_queue_url(self, QueueName):
        if QueueName not in self.queues:
            raise LookupError("AWS.SimpleQueueService.NonExistentQueue")
        return {"QueueUrl": f"https://sqs.example.test/000000000000/{QueueName}"}

    def send_message(self, QueueUrl, MessageBody, MessageGroupId, MessageDeduplicationId):
        self.sends.append(QueueUrl)
        self.queues[QueueUrl.rsplit("/", 1)[1]].send(MessageBody, MessageGroupId, MessageDeduplicationId)


class SiteBackend(tpr.NewsroomClient):
    """The site's API as the start mutation behaves: the run's id comes from the wake key, and a second create is answered as a duplicate."""

    def __init__(self):
        super().__init__()
        self.records = {}

    def graphql(self, query, variables):
        if "startNewsroomProcedureRun" in query:
            if variables["procedureKey"] == "newsroom.missing":
                raise RuntimeError("no such procedure")
            run_id = "run-for-" + variables["wakeKey"]
            if run_id in self.records:
                return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": True, "runId": run_id, "runStatus": "started"})}
            self.records[run_id] = {"id": run_id, "runStatus": "started", "wakeKey": variables["wakeKey"]}
            return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": False, "runId": run_id, "procedureVersionId": "version-1"})}
        result = super().graphql(query, variables)
        if "updateProcedureRun" in query:
            self.records[variables["input"]["id"]].update(variables["input"])
        return result

    def get_record(self, model, record_id):   # the runner reads a duplicate wake's record: it may be waiting for the budget cycle (spend_stop.py)
        assert model == "ProcedureRun", model
        return self.records.get(record_id)


class Lambda:
    def get_remaining_time_in_millis(self):
        return 900_000


class FakeBoto3:
    class _Ssm:
        def get_parameter(self, **_):
            return {"Parameter": {"Value": "test-key"}}

    def client(self, name):
        return self._Ssm() if name == "ssm" else object()

    def resource(self, name):
        raise AssertionError("the monitoring table is not part of these scenarios")


def patch(context, target, name, value):
    patcher = mock.patch.object(target, name, value)
    patcher.start()
    context.add_cleanup(patcher.stop)


def patch_dict(context, mapping, values):
    patcher = mock.patch.dict(mapping, values)
    patcher.start()
    context.add_cleanup(patcher.stop)


def open_site(context, site, *, with_queue=True):
    context.sqs, context.backend, context.site = FakeSqs(), SiteBackend(), site
    context.queue = FakeQueue()
    if with_queue:
        context.sqs.queues[agent_wakes.queue_name(site)] = context.queue
    context.executed, context.dies, context.taken, context.error, context.answer = [], False, None, None, None
    context.deleted, context.invoked_directly = [], []

    def execute(workdir, source_path, inputs, **_):
        context.executed.append(inputs)
        return {"success": True, "output": {"title": "x"}, "seconds": 1}

    def policy_for(request, client, s3):
        if context.dies:
            context.dies = False
            raise RuntimeError("the runner died")
        return PersonStart()

    patch(context, model_attachments, "download_attachment_buffer", lambda client, entry, **_: entry["body"])
    patch(context, graphql_authoring, "PapyrusGraphQLAuthoringClient", lambda *a, **k: context.backend)
    patch(context, pr, "execute_in_child", execute)
    patch(context, pr, "policy_for", policy_for)
    patch(context, pr, "SpendBrake", lambda table: type("SpendBrakeWithRoom", (), {"stop_for": lambda self, request, decision: None})())
    context.boto3 = FakeBoto3()
    patch_dict(context, sys.modules, {"boto3": context.boto3})
    patch_dict(context, os.environ, {})
    os.environ.pop("TRIGGER_TABLE_NAME", None)   # no monitoring table: the trigger rows are not part of these scenarios
    context.sender = agent_wakes.wake_sender(context.sqs)


@given('the site "{site}" with its wake queue and the runner that consumes it')
def background(context, site):
    open_site(context, site)


@given('a site "{site}" whose wake queue does not exist')
def no_queue(context, site):
    open_site(context, site, with_queue=False)


def route(context):
    if getattr(context, "monitor_table", None) is None:
        context.monitor_table = tpr.triggered_table()
    router_result = tpr.run_router(tpr.RouterStore(context.monitor_table), "ttab", now=tpr.NOW + 60, cyclotron=None, deliver=tpr.Delivery(),
                                   appsync=lambda endpoint: object(), start_procedure=context.sender,
                                   context_receipt=lambda client, publication: {"contextHash": "h", "reason": None})
    context.router_result = router_result
    return router_result


@when("a monitor delivers two new decisions and the router puts their wakes on the queue")
def deliver_two(context):
    route(context)


@when("the monitor delivers the same decisions again")
def deliver_again(context):
    context.before = len(context.queue.messages) + len(context.queue.dead_letters) + len(context.deleted)
    context.router_second = tpr.run_router(tpr.RouterStore(context.monitor_table), "ttab", now=tpr.NOW + 120, cyclotron=None, deliver=tpr.Delivery(),
                                           appsync=lambda endpoint: object(), start_procedure=context.sender,
                                           context_receipt=lambda client, publication: {"contextHash": "h", "reason": None})


def event_for(message):
    return {"Records": [{"eventSource": "aws:sqs", "messageId": message.id, "body": message.body}]}


def run_and_settle(context, message):
    """The runner runs the held message. Returning deletes it; raising leaves it on the queue, hidden until its visibility timeout ends."""
    context.taken, context.error, context.answer = message, None, None
    try:
        context.answer = pr.handler(event_for(message), Lambda())
        context.queue.delete(message)
        context.deleted.append(message)
    except Exception as error:
        context.error = error
        context.queue.release(message)
    context.history = getattr(context, "history", []) + [(message, context.answer, context.error)]


def take(context):
    message = context.queue.receive()
    context.taken, context.error, context.answer = message, None, None
    if message is not None:
        run_and_settle(context, message)


@when("the runner takes the message")
@when("the runner takes the message once more")
def runner_takes(context):
    take(context)
    assert context.taken is not None, "the queue gave the runner nothing"


@when("the runner takes and finishes every message")
def takes_all(context):
    while context.queue.messages:
        take(context)
        if context.taken is None or context.error:
            break


@when("the runner takes each message in turn")
def takes_in_turn(context):
    for _ in range(2):
        take(context)
        assert context.taken is not None and context.error is None, context.error


@when("the runner receives the first message and is still running it")
def receives_first(context):
    context.running = context.queue.receive()
    assert context.running is not None and context.running.held


@when("the runner finishes that run and the message is deleted")
def finishes_first(context):
    run_and_settle(context, context.running)
    assert context.error is None and context.running in context.deleted, context.error


@when("the queue delivers the message again and the runner is alive")
def delivered_again(context):
    take(context)


@then("the queue holds {count:d} message")
@then("the queue holds {count:d} messages")
@then("the queue holds {count:d} messages, one wake for each decision")
def holds(context, count):
    assert len(context.queue.messages) == count, [m.body for m in context.queue.messages]


@then("each message names the agent, the subject and the reason in words")
def names_wake(context):
    for message in context.queue.messages:
        wake = json.loads(message.body)["wake"]
        assert set(wake) == {"key", "agent", "subject", "why", "scope"} and all(wake.values()), wake
        assert wake["agent"] == "procedure:distinctive.ttab.ruling-analysis" and wake["subject"].startswith("reference-"), wake
        assert wake["why"].startswith("Started by monitor ttab for "), wake
        assert wake_keys.checked(wake["key"]) == wake["key"]


@then("the site has 1 run record, made from the wake key")
def one_record(context):
    assert len(context.backend.records) == 1, context.backend.records
    (record,) = context.backend.records.values()
    assert record["id"] == "run-for-" + record["wakeKey"] and record["runStatus"] == "completed", record


@then("the procedure ran twice, one run after the other")
def ran_twice(context):
    assert len(context.executed) == 2, context.executed


@then("the message is deleted")
def is_deleted(context):
    assert context.error is None, context.error
    assert context.taken in context.deleted and context.taken not in context.queue.messages


@then("the message is not deleted")
def not_deleted(context):
    assert context.taken is not None and context.taken in context.queue.messages and context.error is not None


@given("two wakes from one agent about the same story")
def same_group(context):
    owner = wake_keys.owner("distinctive.copywriter", "distinctive.newsroom.copywriter")
    for version in ("version-1", "version-2"):
        request = {**tpr.REQUEST, "wakeKey": wake_keys.change_key(owner, "story-1", version, "story.stage_entered"), "publicationId": context.site,
                   "trigger": {"kind": "event", "summary": f"Story story-1 entered copywriting at {version}"}}
        context.sender(request)


@then("the two messages are in the same group")
def same_groups(context):
    first, second = context.queue.messages
    assert first.group == second.group and first.dedupe != second.dedupe


@then("the two messages are in different groups")
def different_groups(context):
    first, second = context.queue.messages
    assert first.group != second.group


@then("the queue gives the runner no other message while it holds the first")
def blocked(context):
    assert context.queue.receive() is None


@then("the runner takes the second message")
def takes_second(context):
    take(context)
    assert context.taken is not None and context.error is None, context.error


@then("the queue gives the runner the second message while it holds the first")
def parallel(context):
    second = context.queue.receive()
    assert second is not None and second.held and context.running.held and second is not context.running


def one_wake_request(context):
    return {**tpr.REQUEST, "wakeKey": "distinctive.ttab|manual|request-1", "publicationId": context.site,
            "trigger": {"kind": "manual", "summary": "Started by a person with Run now"}}


@when("the same wake is put on the queue twice inside the window")
def twice_inside(context):
    request = one_wake_request(context)
    context.sender(request)
    context.sender(request)


@when("the same wake is put on the queue twice, the second after the window")
def twice_after(context):
    request = one_wake_request(context)
    context.sender(request)
    context.queue.window.clear()   # five minutes later
    context.sender(request)


@then("both messages carry the same deduplication id, made from the wake key")
def same_dedupe(context):
    assert context.sqs.sends and len(context.queue.messages) == 1
    assert context.queue.messages[0].dedupe == agent_wakes.digest("distinctive.ttab|manual|request-1")


@then('the second message answered "duplicate" and both messages are deleted')
def second_duplicate(context):
    assert [answer.get("runStatus") for _, answer, _ in context.history] == ["completed", "duplicate"] and len(context.deleted) == 2


@given("a wake on the queue")
def a_wake(context):
    context.sender(one_wake_request(context))


@given("the runner dies before it has made the run record")
def dies(context):
    context.dies = True


@then("no run record exists and the message is not deleted")
def no_record(context):
    assert context.backend.records == {} and context.error is not None and context.taken in context.queue.messages


@given("a wake on the queue for a procedure the site does not have")
def missing_procedure(context):
    context.sender({**one_wake_request(context), "procedureKey": "newsroom.missing"})


@then("the next delivery moves the message to the dead-letter queue")
def to_dead_letters(context):
    assert context.queue.receive() is None
    assert len(context.queue.dead_letters) == 1 and context.queue.messages == []


@then("the dead-letter queue holds {count:d} message")
@then("the dead-letter queue holds {count:d} messages")
def dead_letters(context, count):
    assert len(context.queue.dead_letters) == count


@given("a message on the queue that is not a wake")
def not_a_wake(context):
    context.queue.send("this is not json", agent_wakes.digest("x"), agent_wakes.digest("y"))


@given("a message whose wake says another agent than its key does")
def lying_wake(context):
    body = json.loads(agent_wakes.message_body(one_wake_request(context)))
    body["wake"]["agent"] = "someone.else"
    context.queue.send(json.dumps(body), agent_wakes.digest("a"), agent_wakes.digest("b"))


@then("the runner refuses it and makes no run record")
def refuses(context):
    assert isinstance(context.error, agent_wakes.WakeError) and context.backend.records == {}, context.error


@then("the queue is empty")
def empty(context):
    assert context.queue.messages == [] and len(context.deleted) == 2


@given("an automation with a router publication for the site")
def automation_for_site(context):
    context.run_now_table = run_now_tests.WritableTable()


@when("an editor runs it now")
def run_it_now(context):
    context.invoke = mock.Mock(side_effect=AssertionError("a function was invoked directly"))
    patch(context, context.boto3, "client", lambda name: context.invoke)
    automations.run_now(automations.read_record(fx.automation_row()), reader=MonitoringReader(context.run_now_table),
                        writer=MonitoringWriter(context.run_now_table), invoke=context.sender, actor="an editor", now=run_now_tests.NOW,
                        supplied_input=run_now_tests.INPUT)


@then("the message's reason says the editor ran it now")
def says_run_now(context):
    (message,) = context.queue.messages
    assert "Run now" in json.loads(message.body)["wake"]["why"]


@then("no function was invoked directly")
def no_direct_invoke(context):
    context.invoke.assert_not_called()


@given("a story-stage automation for the site")
def stage_automation(context):
    context.world = stage_tests.World(stage="copywriting")
    context.world.invoked = []


@when("a story enters the stage")
def story_enters(context):
    context.invoke = mock.Mock(side_effect=AssertionError("a function was invoked directly"))
    patch(context, context.boto3, "client", lambda name: context.invoke)
    stage_tests.st.deliver_stage_entered(context.world.client, story=stage_tests.LINEAGE, reader=MonitoringReader(context.world.table),
                                         writer=MonitoringWriter(context.world.table), invoke=context.sender, now=stage_tests.NOW)


@then("the router counts {count:d} failed starts")
def failed_starts(context, count):
    assert context.router_result["counts"]["procedureStartFailed"] == count and context.router_result["counts"]["proceduresStarted"] == 0


@then("nothing started the runner another way")
def nothing_else(context):
    assert context.executed == [] and context.sqs.sends == []


@then("the ruling analysis ran once for each decision")
def ran_for_each(context):
    assert len(context.executed) == 2 and len({run["proceeding"] for run in context.executed}) == 2, context.executed
    assert len(context.deleted) == 2 and len(context.backend.records) == 2


@then("the queue holds no new message")
def no_new_message(context):
    assert context.queue.messages == [] and len(context.deleted) == 2 and context.router_second["counts"]["proceduresStarted"] == 0
