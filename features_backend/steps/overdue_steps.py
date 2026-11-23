"""Overdue (features_backend/agents/overdue.feature): Deliveries in a records backend that reads only indexes, their follow-up timers on a fake scheduler and queue, the runner's
once-only create on the site backend, and Today's own text. No network."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import agent_wakes, follow_up_timers as fu, overdue, today  # noqa: E402
from papyrus_content.agent_definitions import schedules  # noqa: E402
from papyrus_content.announcements import records  # noqa: E402
from papyrus_content.announcements.deliveries import Deliveries  # noqa: E402
from papyrus_content.announcements.delivery_timers import DeliveryTimers  # noqa: E402
from papyrus_content.announcements.records_fakes import RecordsBackend  # noqa: E402
from papyrus_content.review_deadline_timers import PROCEDURE_KEY as REVIEW_DEADLINE_PROCEDURE, ReviewDeadlineTimers  # noqa: E402
from schedule_fakes import ACCOUNT, ENDPOINT, REGION, Backend, TimerScheduler, WakeQueue  # noqa: E402

SITE = "shipped"


class SiteClient(RecordsBackend):
    """The records backend plus the reads Today makes that this feature does not care about: no runs, no agents, no Stories scheduled to publish."""

    tenant_id = None

    def list_by_index(self, index, key, **options):
        if index in ("procedureRunsByStatus", "procedureRunsByAttention"):
            return []
        return super().list_by_index(index, key, **options)

    def list_schedule(self, state, start=None, end=None):
        return []

    def list_tenant_rows(self, model, fields, **_):
        return []


def instant(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def put(context, name, due_at, waiting_for="release"):
    row = {"id": name, "channel": "email", "accountId": "site", "state": "ready", "generation": 1, "releaseAt": due_at, "waitingFor": waiting_for}
    row = records.with_due(row) if due_at else {key: value for key, value in row.items() if key != "releaseAt"}
    context.client.records.setdefault("Delivery", {})[name] = row
    if row.get("dueAt"):
        context.delivery_timers.sync(row)


@given('a site whose clock reads "{moment}"')
def clock(context, moment):
    context.now = instant(moment)
    context.client = SiteClient()
    context.sent, context.checks, context.answers = [], [], []


@given("the site's follow-up timers for its Deliveries")
def timers(context):
    names = schedules.names_for(SITE)
    context.queue = WakeQueue()
    context.fake_scheduler = TimerScheduler(names.group, context.queue)
    follow_ups = fu.FollowUpTimers.for_site(SITE, account=ACCOUNT, region=REGION, client=context.fake_scheduler)
    base = {"appsyncEndpoint": ENDPOINT, "procedureKey": "newsroom.deliver", "publicationId": SITE}
    context.delivery_timers = DeliveryTimers(follow_ups, base)
    context.review_deadline_timers = ReviewDeadlineTimers(follow_ups, {**base, "procedureKey": REVIEW_DEADLINE_PROCEDURE})
    context.backend = Backend()


@given('the Delivery "{name}" waits for its release at "{due_at}" and its timer fired into a queue that lost it')
@when('the Delivery "{name}" waits for its release at "{due_at}" and its timer fired into a queue that lost it')
def lost(context, name, due_at):
    put(context, name, due_at)
    context.fake_scheduler.fire_until(instant(due_at))
    context.queue.messages.clear()   # the queue lost it: nothing will ever deliver it


@given('the Delivery "{name}" waits for its release at "{due_at}" and its timer has fired')
def fired(context, name, due_at):
    put(context, name, due_at)
    context.fake_scheduler.fire_until(instant(due_at))


@given('the Delivery "{name}" waits for nothing')
@when('the Delivery "{name}" runs late and waits for nothing')
def nothing(context, name):
    put(context, name, None)
    context.delivery_timers.sync(context.client.records["Delivery"][name])


def sender(context):
    def send(request):
        context.sent.append(request)
        context.queue.send(agent_wakes.message_body(request), agent_wakes.group_id(agent_wakes.wake_of(request)))
    return send


@when("an editor opens Today")
def open_today(context):
    context.client.reads.clear()
    context.overview = today.today_overview(context.client, day="2026-11-19", time_zone="UTC", now=context.now)
    context.today_lines = today.render(context.overview)


@given("the hygiene agent's daily wake checks what is overdue")
@when("the hygiene agent's daily wake checks what is overdue")
@when("the hygiene agent's daily wake checks what is overdue again after the queue forgot the first message")
def check(context):
    context.queue.window.clear()   # the queue's deduplication window passed
    context.queue.messages.clear()
    context.checks.append(overdue.recover(context.client, deliveries=Deliveries(context.client), wake_request=context.delivery_timers.wake_request,
                                          review_deadline_wake_request=context.review_deadline_timers.wake_request, send=sender(context), now=context.now))


@then('Today lists the Delivery "{name}" as Overdue, in words with a mark')
def listed(context, name):
    (entry,) = [entry for entry in context.overview["overdue"] if entry["id"] == name]
    assert entry["shown"].startswith("⏰ Overdue: Delivery weekly was due 2026-11-19T09:00:00Z") and entry["shown"].endswith("and nothing ran"), entry
    assert any(line.strip().startswith("⏰ Overdue: Delivery weekly was due 9:00 AM") and "nothing ran" in line for line in context.today_lines), context.today_lines


@then("the Overdue lines come before what ran")
def first(context):
    heads = [line for line in context.today_lines if line.startswith(("NEEDS ATTENTION", "WHAT RAN"))]
    assert heads[0] == "NEEDS ATTENTION (1)" and heads[1].startswith("WHAT RAN"), heads


@then("nothing is Overdue")
def none_overdue(context):
    assert context.overview["overdue"] == [] and "NEEDS ATTENTION (0)" in context.today_lines, context.today_lines
    assert not any("Overdue" in line for line in context.today_lines), context.today_lines


@then('Today lists "{first_name}" before "{second}", the oldest due time first')
def ordered(context, first_name, second):
    open_today(context)
    assert [entry["id"] for entry in context.overview["overdue"]] == [first_name, second]


@then('one wake was sent again for the Delivery "{name}"')
def one_sent(context, name):
    assert [request["input"]["deliveryId"] for request in context.sent] == [name], context.sent


@then("its message is the message the Delivery's own timer sends, with the same wake key")
def same_message(context):
    (request,) = context.sent
    (_, target) = context.fake_scheduler.delivered[-1]
    timer_input = target["Input"]
    assert timer_input == agent_wakes.message_body(request), (timer_input, request)
    assert json.loads(timer_input)["wake"]["key"] == request["wakeKey"]


@when("the runner takes the re-sent wake")
def runner_takes(context):
    from papyrus_content.agent_policy import PersonStart
    from papyrus_content import model_attachments, procedure_runner as pr

    original = model_attachments.download_attachment_buffer
    model_attachments.download_attachment_buffer = lambda client, entry, **_: entry["body"]
    context.add_cleanup(lambda: setattr(model_attachments, "download_attachment_buffer", original))

    message = context.queue.messages[-1]
    request = agent_wakes.request_from_event({"Records": [{"eventSource": agent_wakes.SQS_SOURCE, "body": message.body}]})
    context.answers.append(pr.run_procedure_request(request, policy=PersonStart(), client=context.backend, execute=lambda *a, **k: {"success": True, "output": {}, "seconds": 1},
                                                    seconds_available=900, environment={}))


@then('the site has exactly one run record for the Delivery "{name}"')
def one_run(context, name):
    assert len(context.backend.records) == 1, context.backend.records


@then("the second answer says duplicate")
def duplicate(context):
    assert context.answers[0].get("duplicate") is None and context.answers[1].get("duplicate") is True, context.answers
    assert context.answers[1]["runId"] == context.answers[0]["runId"], context.answers


@then('the site has exactly one flag about the Delivery "{name}"')
def one_flag(context, name):
    flags = [row for row in context.client.rows("ReviewRequest") if json.loads(row["subject"])["id"] == name]
    assert len(flags) == 1 and flags[0]["mode"] == "flag", flags


@then('the site has exactly two flags about the Delivery "{name}"')
def two_flags(context, name):
    flags = [row for row in context.client.rows("ReviewRequest") if json.loads(row["subject"])["id"] == name]
    assert len(flags) == 2, flags


@then("the first check raised the flag and the second found it already raised")
def raised_then_existing(context):
    assert [check_[0]["flag"] for check_ in context.checks] == ["raised", "existing"], context.checks


@then("the hygiene agent's daily wake finds nothing to send")
def nothing_to_send(context):
    check(context)
    assert context.checks[-1] == [] and context.sent == [], (context.checks, context.sent)


@then("a record is overdue only after the runner's whole possible length, twice, has passed")
def whole_length(context):
    assert overdue.WAKE_SETTLES_AFTER_SECONDS == (900 + 60) * 2


@then("the limits are the ones the wake queue template sets")
def template(context):
    text = (REPO_ROOT / "amplify" / "agents" / "wake-queue.ts").read_text(encoding="utf-8")
    number = lambda name: int(re.search(rf"export const {name} = (\d+);", text).group(1))  # noqa: E731
    assert (number("RUNNER_TIMEOUT_SECONDS"), number("RUNNER_RECORDING_MARGIN_SECONDS"), number("WAKE_MAXIMUM_RECEIVES")) == (
        overdue.RUNNER_TIMEOUT_SECONDS, overdue.RECORDING_MARGIN_SECONDS, overdue.MAXIMUM_RECEIVES)


@then("every Delivery read was a query on the due index")
def due_only(context):   # one for what is Overdue, one for what is due in the day
    reads = [read for read in context.client.reads if read[0].startswith("deliveries")]
    assert reads and set(reads) == {("deliveriesByDue", "due")}, context.client.reads
