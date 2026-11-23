"""Wake now on an Overdue record (features_backend/agents/overdue-wake-now.feature): the site of overdue.feature (its records backend, its fake scheduler and the
runner's once-only create), with the site's follow-up timers built from the names the site's functions carry, and a wake queue that deduplicates by the
deduplication id the real sender gives it (the wake key). The newsroom's door is the Automation page function (`automation_view.handle`, `agentWake`); the
command line is the operation table's adapter (`papyrus agents wake-overdue`) on the operator's lane. No network."""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

from behave import given, step, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import agent_poke_in_handlers, agent_wakes, follow_up_timers as fu, overdue, review_requests as rr, today, user_auth_mode  # noqa: E402
from papyrus_content.agent_definitions import schedules  # noqa: E402
from papyrus_content.announcements.delivery_timers import DeliveryTimers  # noqa: E402
from papyrus_content.appsync_event import amplify_function_event, user_pool_identity  # noqa: E402
from papyrus_content.automation_view import handle as automation_function  # noqa: E402
from papyrus_content.images import cli as images_cli  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.review_deadline_timers import ReviewDeadlineTimers  # noqa: E402
from schedule_fakes import ACCOUNT, ENDPOINT, REGION, Backend, Message, TimerScheduler, WakeQueue  # noqa: E402

SITE, TENANT, BUCKET = "shipped", "alpha", "site-bucket"
EDIE = "edie@example.test"
#: The names the site's functions carry for its follow-up timers (amplify/functions/automation-view/wire.ts and image-service/wire.ts).
SITE_FUNCTION_ENVIRONMENT = {"PAPYRUS_AGENT_PUBLICATION_ID": SITE, "PAPYRUS_AWS_ACCOUNT_ID": ACCOUNT, "AWS_REGION": REGION, "PAPYRUS_AGENT_TENANT_ID": TENANT,
                             "PAPYRUS_SITE_BUCKET": BUCKET, "PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT}


class RunRecordsWithSummaries(Backend):
    """The runner's once-only create, keeping the summary each run record starts with."""

    def __init__(self):
        super().__init__()
        self.summaries = {}

    def graphql(self, query, variables):
        if "startNewsroomProcedureRun" in query:
            self.summaries.setdefault("run-for-" + variables["wakeKey"], variables.get("summary"))
        return super().graphql(query, variables)


class SqsDeduplicatingByItsId:
    """The site's FIFO queue as SQS keeps it: a message whose deduplication id it already holds inside its window is dropped. It feeds the queue the runner reads."""

    def __init__(self, queue: WakeQueue):
        self.queue, self.window, self.accepted = queue, set(), []

    def get_queue_url(self, QueueName):
        assert QueueName == agent_wakes.queue_name(SITE), QueueName
        return {"QueueUrl": f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/{QueueName}"}

    def send_message(self, QueueUrl, MessageBody, MessageGroupId, MessageDeduplicationId):
        if MessageDeduplicationId in self.window:
            return {}
        self.window.add(MessageDeduplicationId)
        self.accepted.append(json.loads(MessageBody))
        self.queue.messages.append(Message(MessageBody, MessageGroupId))
        return {}


def sent(context) -> list[dict]:
    """What the person's Wake now put on the queue (the timer's own sends before it are not counted)."""
    return context.sqs.accepted


@given("the site's follow-up timers, named as the site's functions name them")
def site_timers(context):
    names = schedules.names_for(SITE)
    context.queue = WakeQueue()
    context.fake_scheduler = TimerScheduler(names.group, context.queue)
    context.delivery_timers = DeliveryTimers.from_environment(SITE_FUNCTION_ENVIRONMENT, appsync_endpoint=ENDPOINT, client=context.fake_scheduler)
    context.review_deadline_timers = ReviewDeadlineTimers.from_environment(SITE_FUNCTION_ENVIRONMENT, appsync_endpoint=ENDPOINT, client=context.fake_scheduler)
    context.backend = RunRecordsWithSummaries()
    context.sqs = SqsDeduplicatingByItsId(context.queue)
    context.wake_answers = []


@given('the procedure "{procedure}" raised a soft review with the deadline "{deadline}" whose deadline wake was lost')
def soft_review_lost(context, procedure, deadline):
    from datetime import datetime, timezone

    created = rr.raise_review(context.client, subject={"type": "story", "id": "story-1"}, mode="soft_review", reason="Please review", raised_by=procedure,
                              deadline=deadline, now=datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc), deadline_timers=context.review_deadline_timers)
    context.review_id = created["id"]
    context.fake_scheduler.fire_until(datetime.fromisoformat(deadline.replace("Z", "+00:00")))
    context.queue.messages.clear()


def wake_on_today(context, kind: str, record_id: str, reason: str, *, groups=("editor",), email=EDIE):
    event = amplify_function_event("Mutation", "agentWake", {"input": json.dumps({"op": "agents_wake_overdue", "record": kind, "id": record_id, "reason": reason})},
                                   user_pool_identity("edie", list(groups), email=email))
    answer = automation_function(event, env=SITE_FUNCTION_ENVIRONMENT, client_factory=lambda: context.client, invoker=real_sender(context))
    context.wake_answers.append(answer)
    return answer


WAKE_SENDER = agent_wakes.wake_sender


def real_sender(context):
    """The one sender every caller uses (``agent_wakes.wake_sender``), over the fake SQS: the deduplication id is the wake key's digest."""
    return WAKE_SENDER(context.sqs)


def wake_on_command_line(context, kind: str, record_id: str, reason: str, *, actor="person"):
    """`papyrus agents wake-overdue` on the operator's lane, with the operator's environment naming the site as its functions do."""
    out = io.StringIO()
    with mock.patch.object(user_auth_mode, "user_auth_requested", lambda: False), \
            mock.patch.object(agent_poke_in_handlers, "_operator_caller", lambda client, caller: Caller(kind=caller.kind, subject=EDIE)), \
            mock.patch.object(agent_wakes, "wake_sender", lambda sqs=None: real_sender(context)), \
            mock.patch.object(images_cli, "caller_from", lambda environ: Caller(kind=actor)), \
            mock.patch.dict(os.environ, SITE_FUNCTION_ENVIRONMENT), \
            mock.patch.object(context.client, "endpoint", ENDPOINT, create=True):
        images_cli.command(["wake-overdue", "--record", kind, "--id", record_id, "--reason", reason], group="agents",
                           handlers=agent_poke_in_handlers.signed_in_handlers(client_factory=lambda: context.client), environ={}, stdout=out)
    answer = json.loads(out.getvalue())
    if not answer.get("ok"):
        answer = {"ok": False, "error": answer["error"]["code"], "message": answer["error"]["message"]}
    context.wake_answers.append(answer)
    return answer


def with_clock(context, function, *args, **kwargs):
    with mock.patch.object(overdue, "datetime", ClockAt(context.now)):
        return function(context, *args, **kwargs)


class ClockAt:
    """``overdue``'s ``datetime`` with ``now()`` reading the scenario's clock; everything else is the real class."""

    def __init__(self, moment):
        from datetime import datetime

        self._moment, self._real = moment, datetime

    def now(self, tz=None):
        return self._moment.astimezone(tz) if tz else self._moment

    def __getattr__(self, name):
        return getattr(self._real, name)


@step('Edie presses Wake now on the Delivery "{name}" on Today because "{reason}"')
def edie_wakes_on_today(context, name, reason):
    with_clock(context, wake_on_today, "Delivery", name, reason)


@step('Edie presses Wake now on the Delivery "{name}" on the command line because "{reason}"')
def edie_wakes_on_command_line(context, name, reason):
    with_clock(context, wake_on_command_line, "Delivery", name, reason)


@step('Edie presses Wake now on the review request on Today because "{reason}"')
def edie_wakes_review(context, reason):
    with_clock(context, wake_on_today, "ReviewRequest", context.review_id, reason)


@when('once the queue has forgotten the first message, Edie presses Wake now on the Delivery "{name}" on Today because "{reason}"')
def edie_wakes_after_window(context, name, reason):
    context.sqs.window.clear()   # the queue's deduplication window passed
    context.queue.messages.clear()
    with_clock(context, wake_on_today, "Delivery", name, reason)


@when('Rita, a reader, presses Wake now on the Delivery "{name}" because "{reason}"')
def reader_wakes(context, name, reason):
    with_clock(context, wake_on_today, "Delivery", name, reason, groups=("reader",), email="rita@example.test")


@when('an agent asks the command line to wake the Delivery "{name}" now because "{reason}"')
def agent_wakes_overdue(context, name, reason):
    with_clock(context, wake_on_command_line, "Delivery", name, reason, actor="agent")


# --- what happened ---------------------------------------------------------------------------------------------------------------------------------


@then('one wake went on the site\'s queue for the Delivery "{name}"')
def one_wake_for_delivery(context, name):
    assert [request["request"]["input"]["deliveryId"] for request in sent(context)] == [name], sent(context)


@then("it has the wake key the Delivery's own timer used, and the timer's request")
def same_key_as_delivery_timer(context):
    (message,) = sent(context)
    (_, target) = context.fake_scheduler.delivered[-1]
    timer = json.loads(target["Input"])
    assert message["wake"]["key"] == timer["wake"]["key"], (message, timer)
    without_who = lambda body: {**body["request"], "trigger": {k: v for k, v in body["request"]["trigger"].items() if k not in ("summary", "poke")}}  # noqa: E731
    assert without_who(message) == without_who(timer), (message, timer)


@then("it has the wake key the review request's own deadline timer used")
def same_key_as_review_timer(context):
    (message,) = sent(context)
    (_, target) = context.fake_scheduler.delivered[-1]
    assert message["wake"]["key"] == json.loads(target["Input"])["wake"]["key"] == fu.follow_up_key("review-deadline", context.review_id, "2026-11-19T09:00:00Z")


@then("the wake says Edie sent it again because \"{reason}\"")
def wake_says_who(context, reason):
    trigger = sent(context)[-1]["request"]["trigger"]
    assert trigger["poke"]["kind"] == "wake_overdue" and trigger["poke"]["by"] == EDIE and trigger["poke"]["reason"] == reason, trigger
    assert trigger["poke"]["repeats"] == sent(context)[-1]["wake"]["key"]


@then('Wake now answers in words that it was woken now by "{person}" with the same key')
def answer_in_words(context, person):
    answer = context.wake_answers[-1]
    assert answer["ok"] is True, answer
    result = answer["result"]
    assert result["requestedBy"] == person and "with the same key" in result["shown"] and person in result["shown"], result
    assert result["wakeKey"] == sent(context)[-1]["wake"]["key"]


@then("the site's queue holds one wake for it")
def one_message(context):
    assert len(context.queue.messages) == 1 and len(sent(context)) == 1, (context.queue.messages, sent(context))
    assert all(answer["ok"] for answer in context.wake_answers), context.wake_answers


@then('the run record\'s summary says it was woken by "{person}" because "{reason}"')
def run_summary(context, person, reason):
    (summary,) = context.backend.summaries.values()
    assert summary.startswith(f"{person} woke it now ({reason}); this repeats: "), summary


@then('running that wake times the review request out with the note "{note}"')
def review_times_out(context, note):
    (message,) = sent(context)
    outcome = rr.on_deadline_wake(context.client, message["wake"]["key"], now=context.now)
    assert outcome["action"] == "timed_out", outcome
    current = rr.get_review(context.client, context.review_id)
    assert current["state"] == "timed_out" and current["history"][-1]["note"] == note, current


@then('Wake now is refused as "{code}", saying "{words}"')
def refused(context, code, words):
    answer = context.wake_answers[-1]
    assert answer["ok"] is False and answer["error"] == code and words in answer["message"], answer


@then("Wake now put nothing on the site's queue")
def nothing_sent(context):
    assert sent(context) == [], sent(context)


@then('Today\'s Wake now for the Delivery "{name}" can be pressed, and names the command "{command}"')
def today_offers(context, name, command):
    (entry,) = [entry for entry in context.overview["attention"] if entry["kind"] == "overdue" and entry["id"] == name]
    action = entry["action"]
    assert action["kind"] == "wake_now" and action["words"] == "Wake now" and action["available"] is True, action
    assert action["command"] == command, action
    assert any(command in line for line in today.render(context.overview)), today.render(context.overview)


# --- the requests against the real schema ----------------------------------------------------------------------------------------------------------


@when("the Wake now requests are built against a recording site API")
def recorded_requests(context):
    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient

    class RecordingClient(PapyrusGraphQLAuthoringClient):
        def __init__(self):
            super().__init__(endpoint=ENDPOINT, tenant_id=None)
            self.requests = []

        def graphql(self, query, variables=None):
            self.requests.append({"query": query, "variables": variables or {}})
            return {"agentWake": json.dumps({"ok": True, "result": {}}), "getDelivery": None, "getReviewRequest": None}

    client = RecordingClient()
    for kind in overdue.OVERDUE_KINDS:
        try:
            overdue.wake_now(client, kind=kind, record_id="r1", reason="r", by=EDIE, person=True, wake_requests={}, send=lambda request: None)
        except overdue.OverdueWakeError as error:
            assert error.code == "not_found", error
    with mock.patch.object(user_auth_mode, "user_auth_requested", lambda: True):
        agent_poke_in_handlers.wake_overdue_now(client, {"record": "Delivery", "id": "r1", "reason": "r"}, Caller(kind="person"))
    context.poke_requests = client.requests
