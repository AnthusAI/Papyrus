"""The scheduled send of a Delivery, through the runner (features_backend/announcements/delivery-scheduled-send.feature, PPY-e2829f).

The site: its Delivery records with the words in memory, its schedule group and wake queue (schedule_fakes), Caducus's x channel with its guard (announcements.fakes), and the
runner over the site backend and agent policy of runner_reads_policy_steps. Each wake the timers put on the queue is handed to the runner as the queue would hand it; the runner's
gate decides, and the procedure it starts is the deliver_due step over these fakes. No network.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests", Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import agent_wakes, follow_up_timers as fu, procedure_runner as pr  # noqa: E402
from papyrus_content.agent_definitions import schedules  # noqa: E402
from papyrus_content.announcements import budget, edit_handlers, review_handlers  # noqa: E402
from papyrus_content.announcements.deliver_due import DeliverServices, deliver_due_run  # noqa: E402
from papyrus_content.announcements.deliveries import Deliveries, Plan  # noqa: E402
from papyrus_content.announcements.delivery_timers import PROCEDURE_KEY, DeliveryTimers  # noqa: E402
from papyrus_content.announcements.fakes import FakeFunctions, FakeX, StoryRecordsBackend  # noqa: E402
from papyrus_content.announcements.guard import SpendGuard  # noqa: E402
from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles  # noqa: E402
from papyrus_content.announcements.spend import SpendLedger  # noqa: E402
from papyrus_content.announcements.withdrawals import Withdrawals  # noqa: E402
from papyrus_content.announcements.x_channel import XChannel  # noqa: E402
from papyrus_content.announcements.x_runner import SpendControl, XRunner  # noqa: E402
from papyrus_content.images.handlers import Caller, execute  # noqa: E402
from papyrus_content.spend_ledger_test import FakeLedgerTable  # noqa: E402
from schedule_fakes import ACCOUNT, ENDPOINT, REGION, TimerScheduler, WakeQueue, utc  # noqa: E402

SITE, ANNOUNCEMENT = "mom", "announcement-1"
TENANT, BUCKET = "alpha", "site-bucket"   # the tenant and bucket of runner_reads_policy_steps, where the runner reads the site's agent policy
NOW = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)
WORDS = "A look at whether a system can keep a secret from itself.\n\nhttps://machines.example/s"
PRICES = {"createPost": 0.015, "createPostWithUrl": 0.2, "deletePost": 0.01, "readPost": 0.005, "asOf": "2026-11-12"}


class _Account:
    key = "CHANNELACCT#x#mom"


class _Price:
    def __init__(self, amount):
        self.amount = amount


def words(text: str) -> str:
    return text.replace("\\n", "\n")


def delivery(context) -> dict:
    return context.deliveries.get(context.delivery_id)


def x_runner(context) -> XRunner:
    channel = XChannel(context.x, budget_wait_until=lambda: budget.next_cycle_start(budget.cycle_start(NOW, 1), 1).isoformat() + "T00:00:00Z")
    return XRunner(context.deliveries, Withdrawals(context.deliveries, None, removers=lambda row: channel), channel, context.control)


def door(context) -> dict:
    """The announcements write door's handlers as the image service builds them, holding the site's timers."""
    original = edit_handlers._publication
    edit_handlers._publication = review_handlers._publication = lambda client: SITE   # the publication's key is read from the site's own record, which these specs do not build
    context.add_cleanup(setattr, edit_handlers, "_publication", original)
    context.add_cleanup(setattr, review_handlers, "_publication", original)
    return review_handlers.door_write_handlers(context.records, context.files, context.timers)


# --- the site ---------------------------------------------------------------------------------------------------------------------------------------


@given('X announcements are On for the account "{account}" with a budget of ${amount}')
def x_is_on(context, account, amount):
    context.records = StoryRecordsBackend()
    context.files = MemoryDeliveryFiles(context.records)
    context.functions = FakeFunctions(lambda: NOW.timestamp())
    context.functions.connected = {"connection": "connected", "accountId": account, "handle": f"@{account}_test"}
    context.functions.save({"mode": "on", "rules": {"minStars": 5, "storyTypes": ["article"]}, "budget": float(amount), "billingCycleDay": 1, "prices": PRICES,
                            "labelConfirmed": True}, "connected")
    context.ledger = SpendLedger(FakeLedgerTable(), "site")
    context.control = SpendControl(settings=context.functions, connection=context.functions.status, ledger=context.ledger, now=lambda: NOW)
    context.guard = SpendGuard(context.ledger, context.functions, lambda: NOW)
    context.x = FakeX()
    context.x.guard = context.guard


@given("the site's Deliveries set follow-up timers")
def deliveries_with_timers(context):
    names = schedules.names_for(SITE)
    context.queue = WakeQueue()
    context.scheduler = TimerScheduler(names.group, context.queue)
    base = {"appsyncEndpoint": ENDPOINT, "publicationId": SITE, "procedureKey": PROCEDURE_KEY, "tenantId": TENANT, "siteBucket": BUCKET}
    context.timers = DeliveryTimers(fu.FollowUpTimers.for_site(SITE, account=ACCOUNT, region=REGION, client=context.scheduler), base)
    context.deliveries = Deliveries(context.records, context.files, context.timers)
    context.run_ids = []


def draft(context, approval, drafted, lock, release):
    plan = Plan(channel="x", account_id="mom", approval=approval, approval_policy="publication default", text=WORDS, lock_at=lock, release_at=release)
    context.delivery_id = context.deliveries.create(ANNOUNCEMENT, plan, release_at=release, by="announce", now=drafted)["id"]


@given('an X Delivery drafted at "{drafted}" under "{approval}" review, released and locked at "{release}"')
def drafted_same_time(context, drafted, approval, release):
    draft(context, approval, drafted, release, release)


@given('an X Delivery drafted at "{drafted}" under "{approval}" review, locked at "{lock}" and released at "{release}"')
def drafted_with_lead(context, drafted, approval, lock, release):
    draft(context, approval, drafted, lock, release)


@given("the owner paused announcements")
def owner_paused(context):
    context.functions.manual_pause(True, "ryan")


@given("${amount} is already spent on X this cycle")
def already_spent(context, amount):
    context.guard.charged(_Account(), _Price(amount))


# --- people before the lock ---------------------------------------------------------------------------------------------------------------------------


def through_door(context, name, arguments, who):
    context.envelope = execute(name, arguments, Caller(kind="person", subject=who, is_admin=False), door(context))
    assert context.envelope["ok"], context.envelope


@when('the person "{who}" saves the words "{text}" over version {number:d} through the announcements write door at "{moment}"')
def person_edits(context, who, text, number, moment):
    original = edit_handlers.draft

    def at_moment(*args, **kwargs):   # the door's clock reads the moment of the scenario
        return original(*args, **{**kwargs, "now": moment})

    edit_handlers.EDIT_HANDLERS["announcements_draft"] = at_moment
    context.add_cleanup(edit_handlers.EDIT_HANDLERS.__setitem__, "announcements_draft", original)
    through_door(context, "announcements_draft", {"delivery": context.delivery_id, "replaces": number, "text": words(text)}, who)


@when('the person "{who}" changes the Delivery\'s review to "{approval}" through the announcements write door at "{moment}"')
def person_changes_review(context, who, approval, moment):
    through_door(context, "announcements_delivery_review_set", {"delivery": context.delivery_id, "approval": approval}, who)


@when('the person "{who}" releases the Delivery through the announcements write door at "{moment}"')
def person_releases(context, who, moment):
    through_door(context, "announcements_release", {"delivery": context.delivery_id}, who)


@when('the person "{who}" withdraws the Delivery at "{moment}"')
def person_withdraws(context, who, moment):
    door(context)   # the publication's key, as the door reads it
    # Withdrawing is the signed-in lane's, not the write door's: it holds no timers, so the Delivery's entry stays and its wake finds nothing to wait for.
    review_handlers.withdraw(context.records, {"delivery": context.delivery_id}, Caller(kind="person", subject=who, is_admin=False), None, files=context.files)


@when('the Delivery\'s release moves to "{release}" before the wake runs')
def release_moves(context, release):
    context.deliveries.move_release(delivery(context), release, by="ada", now="2026-11-22T09:59:00Z")


# --- time and the runner ------------------------------------------------------------------------------------------------------------------------------


def run_wake(context, body: str, moment: str) -> None:
    """Hand one wake to the runner as the queue does; the procedure the gate starts is the deliver_due step over this site."""
    request = agent_wakes.request_from_event({"Records": [{"eventSource": agent_wakes.SQS_SOURCE, "body": body}]})
    services = DeliverServices(context.deliveries, send_x=x_runner(context).send_due)

    def run(workdir, source_path, inputs, **_):
        context.executed.append(request["wakeKey"])
        return {"success": True, "output": deliver_due_run(services, inputs["deliveryId"], inputs["dueAt"], now=moment), "seconds": 1}

    policy = pr.policy_for(request, context.client, lambda: context.s3)
    context.result = pr.run_procedure_request(request, policy=policy, client=context.client, execute=run, seconds_available=900, environment={})
    context.run_ids.append(context.result["runId"])


@when('the time "{moment}" arrives and each wake reaches the runner')
def time_arrives(context, moment):
    context.scheduler.fire_until(utc(moment))
    while (message := context.queue.receive()) is not None:
        run_wake(context, message.body, moment)
        context.queue.delete(message)


@given('its timer fired at "{moment}" and the wake waits on the queue')
def timer_fired(context, moment):
    context.scheduler.fire_until(utc(moment))
    assert len(context.queue.messages) == 1


@when('the wake on the queue reaches the runner at "{moment}"')
def queued_wake_runs(context, moment):
    message = context.queue.receive()
    run_wake(context, message.body, moment)
    context.queue.delete(message)


@when("the hygiene agent sends the Delivery's wake again with its timer's key")
def resent(context):
    request = context.timers.wake_request(delivery(context))
    assert request["wakeKey"] == fu.follow_up_key("deliver", context.delivery_id, delivery(context)["dueAt"])
    run_wake(context, agent_wakes.message_body(request), "2026-11-22T12:00:00Z")


@when("Caducus runs its x queue and the deliver side reads what it recorded")
def caducus_runs(context):
    for event in list(context.x.events):
        if context.x.deliveries[event]["status"] == "queued":
            context.x.deliver(event)
    x_runner(context).settle(context.delivery_id, now="2026-11-22T10:01:00Z")


# --- what came of it ----------------------------------------------------------------------------------------------------------------------------------


def last_run(context) -> dict:
    return context.client.records[context.run_ids[-1]]


@then('the deliver run was acted with the reason "{reason}" and names no responsibility and no rung')
def run_acted(context, reason):
    stored = last_run(context)
    assert (stored["outcome"], stored["outcomeReason"]) == ("acted", reason), stored
    assert not any(stored.get(key) for key in ("responsibility", "rung", "policyVersion", "automationId")), stored


@then('the deliver run asked a person with the reason "{reason}"')
def run_asked(context, reason):
    stored = last_run(context)
    assert (stored["outcome"], stored["outcomeReason"]) == ("asked", reason), stored


@then('the deliver run says nothing to do with the reason "{reason}"')
def run_nothing(context, reason):
    stored = last_run(context)
    assert (stored["outcome"], stored["outcomeReason"]) == ("nothing", reason), stored


@then('the Delivery\'s timer is set for "{moment}"')
def one_entry(context, moment):
    (entry,) = context.scheduler.entries.values()
    assert TimerScheduler.at_of(entry) == utc(moment), entry["ScheduleExpression"]


@then("the Delivery has no timer")
def no_entry(context):
    assert context.scheduler.entries == {}, list(context.scheduler.entries.values())


@then('the Delivery was approved by the policy at "{moment}" and locked with version {number:d}')
def approved_by_policy(context, moment, number):
    row = delivery(context)
    assert (row["approvedBy"], row["approvedAt"], row["lockedAt"], int(row["lockedVersion"])) == ("system", moment, moment, number), row


@then("Caducus was handed the drafted words")
def handed_drafted(context):
    assert [event["text"] for event in context.x.events.values()] == [WORDS], context.x.events


@then('Caducus was handed the words "{text}"')
def handed_words(context, text):
    assert [event["text"] for event in context.x.events.values()] == [words(text)], context.x.events


@then("Caducus was handed nothing")
def handed_nothing(context):
    assert context.x.events == {}, context.x.events


@then('the Delivery is "{state}"')
def delivery_state(context, state):
    assert delivery(context)["state"] == state, delivery(context)


@then('the Delivery is still due at "{moment}"')
def still_due(context, moment):
    row = delivery(context)
    assert row["dueAt"] == moment and row["state"] == "ready" and not row.get("lockedAt"), row


@then("exactly one flag is open for the Delivery")
def one_flag(context):
    flags = [row for row in context.records.rows("ReviewRequest") if row.get("mode") == "flag" and json.loads(row["subject"])["id"] == context.delivery_id]
    assert len(context.records.rows("ReviewRequest")) == 1 and len(flags) == 1, context.records.rows("ReviewRequest")


@then('the Delivery is blocked with the reason "{reason}"')
def blocked(context, reason):
    row = delivery(context)
    assert (row["state"], row.get("blockedReason")) == ("blocked", reason), row


@then("nothing was posted to X")
def nothing_posted(context):
    assert all(entry["status"] != "sent" for entry in context.x.deliveries.values()), context.x.deliveries


@then("announcements are paused because the budget was reached")
def paused_for_budget(context):
    settings = context.control.current()
    assert settings["paused"] and settings["pauseKind"] == "budget", settings
