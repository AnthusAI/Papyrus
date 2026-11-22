"""Review deadline timers and reads by index (features_backend/stories/review-deadline-timers.feature). The site's schedule group, wake queue and request store
are fakes (review_deadline_fakes); listing every review request fails the scenario. No network."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from behave import given, then, when

STEPS = Path(__file__).resolve().parent
if str(STEPS) not in sys.path:
    sys.path.insert(0, str(STEPS))

from review_deadline_fakes import DeadlineSite, RequestsReadOnlyByIndex  # noqa: E402
from papyrus_content import agent_wakes, follow_up_timers as fu, overdue, publish_gate, review_requests as rr  # noqa: E402
from papyrus_content.announcements.deliveries import Deliveries  # noqa: E402
from papyrus_content.publishing import PublishError  # noqa: E402

RAISED_AT = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)
STORY_VERSION = {"id": "story-1-v3", "lineageId": "story-1", "contentHash": "hash-3", "title": "A story", "versionNumber": 3}


def instant(text: str) -> datetime:
    return datetime.strptime(text, fu.TIME_FORMAT).replace(tzinfo=timezone.utc)


def stored(context) -> dict:
    return context.client.tables["ReviewRequest"][context.request_id]


def raise_one(context, mode: str, raised_by: str, deadline: str | None = None) -> None:
    created = rr.raise_review(context.client, subject={"type": "story", "id": "story-1"}, mode=mode, reason="Please review", raised_by=raised_by,
                              deadline=deadline, now=RAISED_AT, deadline_timers=context.site.timers)
    context.request_id = created["id"]


@given("a site with deadline timers whose review requests can only be read by index or by id")
def site(context):
    context.site = DeadlineSite(RequestsReadOnlyByIndex())
    context.client, context.request_id = context.site.client, None


@when('the procedure "{procedure}" raises a soft review with the deadline "{deadline}"')
def raise_soft(context, procedure, deadline):
    raise_one(context, "soft_review", procedure, deadline)


@when('the procedure "{procedure}" raises a hard gate')
def raise_hard(context, procedure):
    raise_one(context, "hard_gate", procedure)


@when('the procedure "{procedure}" raises a flag')
def raise_flag(context, procedure):
    raise_one(context, "flag", procedure)


@then("the site's timers hold one entry, for that request's deadline")
def one_entry(context):
    (name,) = context.site.entries()
    entry = context.site.scheduler.entries[name]
    assert name == fu.entry_name("ReviewRequest", context.request_id), name
    assert entry["ScheduleExpression"] == f"at({stored(context)['deadline'][:-1]})", entry["ScheduleExpression"]
    request = json.loads(entry["Target"]["Input"])["request"]
    assert request["input"] == {"reviewRequestId": context.request_id, "dueAt": stored(context)["deadline"]} and request["trigger"]["waitingFor"] == "deadline", request


@then("the site's timers hold no entry")
def no_entry(context):
    assert context.site.entries() == [], context.site.entries()


@when('the time "{moment}" arrives with no page open')
def time_arrives(context, moment):
    context.site.advance_to(instant(moment))


@then('the request has no due time and is in the "{state}" partition of the state index')
def in_partition(context, state):
    row = stored(context)
    assert row.get("dueAt") is None, row
    assert [found["id"] for found in rr.rows_in_state(context.client, state)] == [context.request_id]


@when('an editor approves the request on "{moment}" where the site\'s timers are at hand')
def approve_with_timers(context, moment):
    rr.answer_review(context.client, context.request_id, decision="approve", by="editor", roles=["editor"], now=instant(moment), deadline_timers=context.site.timers)


@when('an editor approves the request on "{moment}" from the Notification Center, which has no timers')
def approve_without_timers(context, moment):
    rr.answer_review(context.client, context.request_id, decision="approve", by="editor", roles=["editor"], now=instant(moment))


@when("the procedure withdraws the request where the site's timers are at hand")
def withdraw(context):
    rr.withdraw_review(context.client, context.request_id, by="ideas", now=RAISED_AT, deadline_timers=context.site.timers)


@then("no deadline wake ran")
def no_wake(context):
    assert context.site.wakes == [], context.site.wakes


@then("the deadline wake did nothing because the request waits for nothing now")
def wake_did_nothing(context):
    (wake,) = context.site.wakes
    assert wake["action"] == "nothing" and "waits for nothing now" in wake["reason"], wake


@then('the request is answered with "{decision}"')
def answered(context, decision):
    request = rr.get_review(context.client, context.request_id)
    assert request["state"] == "answered" and request["answer"]["decision"] == decision, request


@then("raising a hard gate with a deadline is refused")
def hard_gate_deadline_refused(context):
    try:
        rr.raise_review(context.client, subject={"type": "story", "id": "story-2"}, mode="hard_gate", reason="Approve", raised_by="ruling",
                        deadline="2026-11-20T09:00:00Z", deadline_timers=context.site.timers)
    except rr.ReviewError as refused:
        assert "has no deadline" in str(refused)
        return
    raise AssertionError("a hard gate took a deadline")


@then("raising a soft review with a deadline but no timers is refused, and nothing is stored")
def refused_without_timers(context):
    try:
        rr.raise_review(context.client, subject={"type": "story", "id": "story-1"}, mode="soft_review", reason="Please review", raised_by="ideas",
                        deadline="2026-11-20T09:00:00Z")
    except rr.ReviewError as refused:
        assert "follow-up timer" in str(refused)
        assert not context.client.tables.get("ReviewRequest"), context.client.tables.get("ReviewRequest")
        return
    raise AssertionError("a soft review with a deadline was raised with no timer")


# --- the publish gate ----------------------------------------------------------------------------------------------------------------------


@given("the site's publish gate requires a person's approval")
def gate_required(context):
    publish_gate.set_publish_approval(context.client, publish_gate.REQUIRED, by="admin", now="2026-11-19T08:00:00Z")


@when('an agent publishes the story "{story}"')
def agent_publishes(context, story):
    context.client.calls.clear()
    try:
        publish_gate.ensure_publish_approval(context.client, STORY_VERSION, approved_by=None, actor="agent:announce")
        context.publish = None
    except PublishError as refused:
        context.publish = refused


@then('publishing is refused and the request "{prefix}" for that version is open')
def refused_and_open(context, prefix):
    assert context.publish is not None and context.publish.code == publish_gate.APPROVAL_REQUIRED, context.publish
    expected = publish_gate.request_prefix(STORY_VERSION) + prefix.removeprefix("rr-publish")
    context.gate_request = expected
    assert rr.get_review(context.client, expected)["state"] == "open"


@when("the publish gate's request is withdrawn")
def gate_withdrawn(context):
    rr.withdraw_review(context.client, context.gate_request, by="publish-gate")


@when("an editor approves the publish gate's latest request")
def gate_approved(context):
    rr.answer_review(context.client, context.gate_request, decision="approve", by="ada", roles=["editor"])


@then("publishing is allowed")
def allowed(context):
    assert context.publish is None, context.publish


@then("the publish gate read its requests by their ids")
def gate_by_id(context):
    reads = [call for call in context.client.calls if call[1] == "ReviewRequest"]
    prefix = publish_gate.request_prefix(STORY_VERSION)
    assert reads and all(kind == "get" for kind, _, _ in reads), reads
    assert [record_id for _, _, record_id in reads] == [prefix, f"{prefix}-2", f"{prefix}-3"], reads


# --- reads by index ----------------------------------------------------------------------------------------------------------------------------


@given("open, answered and withdrawn review requests")
def mixed_requests(context):
    for number, mode in enumerate(("flag", "soft_review", "hard_gate", "soft_review"), 1):
        rr.raise_review(context.client, subject={"type": "story", "id": f"story-{number}"}, mode=mode, reason=f"Request {number}", raised_by="idea-pipeline",
                        request_id=f"rr-{number}", deadline="2026-11-20T09:00:00Z" if number == 4 else None, now=RAISED_AT,
                        deadline_timers=context.site.timers)
    rr.answer_review(context.client, "rr-2", decision="feedback", feedback="Shorter", by="editor", roles=["editor"])
    rr.withdraw_review(context.client, "rr-3", by="idea-pipeline")


@when("the requests are listed by state, listed in every state, read back for steering and their recipients resolved")
def read_everything(context):
    context.client.calls.clear()
    context.open_ids = sorted(request["id"] for request in rr.list_reviews(context.client, state="open"))
    context.every_id = sorted(request["id"] for request in rr.list_reviews(context.client))
    context.steering = rr.steering_for(context.client, raised_by="idea-pipeline")
    context.recipients = rr.resolve_recipients(context.client, mode="hard_gate", site_owner="owner@example.test")


@then("the open list holds only the open requests and the full list holds every request")
def lists_hold(context):
    assert context.open_ids == ["rr-1", "rr-4"], context.open_ids
    assert context.every_id == ["rr-1", "rr-2", "rr-3", "rr-4"], context.every_id
    assert [note["requestId"] for note in context.steering] == ["rr-2"], context.steering
    assert context.recipients["emails"] == ["owner@example.test"], context.recipients


@then("every read of review requests was a query of a state partition or a read by id")
def only_index_reads(context):
    reads = [call for call in context.client.calls if call[1] in ("ReviewRequest", rr.STATE_INDEX)]
    assert reads and all(kind in ("list_by_index", "get") for kind, _, _ in reads), reads
    partitions = {key for kind, _, key in reads if kind == "list_by_index"}
    assert partitions == {rr.review_state_key(state) for state in rr.STATES}, partitions


# --- overdue -------------------------------------------------------------------------------------------------------------------------------------


@when("its deadline timer fires into a queue that lost the wake")
def lost_wake(context):
    context.site.scheduler.fire_until(instant(stored(context)["dueAt"]))
    context.site.queue.messages.clear()


@then('on "{moment}" the request is listed as Overdue, in words with a mark')
def listed_overdue(context, moment):
    (entry,) = overdue.overdue_review_deadlines(context.client, instant(moment))
    assert entry["id"] == context.request_id
    shown = overdue.shown("ReviewRequest", entry)["shown"]
    assert shown == f"⏰ Overdue: ReviewRequest {context.request_id} was due 2026-11-20T09:00:00Z (deadline) and nothing ran", shown


@when('the hygiene agent\'s daily wake recovers what is overdue on "{moment}"')
def recover(context, moment):
    context.sent = []
    context.recovered = overdue.recover(context.client, deliveries=Deliveries(context.client), wake_request=lambda row: {}, send=context.sent.append,
                                        review_deadline_wake_request=context.site.timers.wake_request, now=instant(moment))


@then("the wake sent again has the key the request's own timer used")
def same_key(context):
    (request,) = context.sent
    (name, target) = context.site.scheduler.delivered[-1]
    original = agent_wakes.request_from_event({"Records": [{"eventSource": agent_wakes.SQS_SOURCE, "body": target["Input"]}]})
    assert request["wakeKey"] == original["wakeKey"] == fu.follow_up_key("review-deadline", context.request_id, "2026-11-20T09:00:00Z"), (request, original)
    (entry,) = context.recovered
    assert entry["flag"] == "raised" and rr.get_review(context.client, entry["flagId"])["mode"] == "flag"


@then('running that wake times the request out with the note "{note}"')
def resent_wake_runs(context, note):
    (request,) = context.sent
    outcome = rr.on_deadline_wake(context.client, request["wakeKey"], now=instant("2026-11-20T12:00:00Z"))
    assert outcome["action"] == "timed_out", outcome
    current = rr.get_review(context.client, context.request_id)
    assert current["state"] == "timed_out" and current["history"][-1]["note"] == note


# --- the engine's own follow-ups, through the runner -----------------------------------------------------------------------------------------------


def runner_request(context, request_id: str, *, owner: str | None = None, procedure: str | None = None) -> dict:
    """The request the deadline timer sends (``ReviewDeadlineTimers.wake_request``), with the site's tenant and bucket, as the queue hands it to the runner."""
    from papyrus_content.review_deadline_timers import ReviewDeadlineTimers
    from runner_reads_policy_steps import BUCKET, TENANT
    from schedule_fakes import ENDPOINT

    base = {"appsyncEndpoint": ENDPOINT, "publicationId": "review-site", "procedureKey": procedure or "review_deadline", "tenantId": TENANT, "siteBucket": BUCKET}
    timers = ReviewDeadlineTimers(fu.FollowUpTimers.for_site("review-site", account="123456789012", region="us-east-1", client=object()), base)
    request = timers.wake_request(context.reviews.tables["ReviewRequest"][request_id])
    if owner is not None:
        request["wakeKey"] = fu.follow_up_key(owner, request_id, request["input"]["dueAt"])
    return request


def start_runner(context, request: dict) -> None:
    from papyrus_content import procedure_runner as pr

    def execute(workdir, source_path, inputs, **_):
        context.executed.append(request["wakeKey"])
        return {"success": True, "output": rr.deadline_run(context.reviews, inputs["reviewRequestId"], inputs["dueAt"], now=instant("2026-11-20T09:00:00Z")), "seconds": 1}

    policy = pr.policy_for(request, context.client, lambda: context.s3)
    context.result = pr.run_procedure_request(request, policy=policy, client=context.client, execute=execute, seconds_available=900, environment={})


@given('the open soft review "{request_id}" waits for its deadline "{deadline}"')
def open_soft_review(context, request_id, deadline):
    deadline_site = DeadlineSite(RequestsReadOnlyByIndex())
    context.reviews = deadline_site.client
    rr.raise_review(context.reviews, subject={"type": "story", "id": "story-1"}, mode="soft_review", reason="Please review", raised_by="ideas",
                    request_id=request_id, deadline=deadline, now=RAISED_AT, deadline_timers=deadline_site.timers)


@when('the deadline timer\'s wake for "{request_id}" reaches the runner')
def deadline_wake_reaches_runner(context, request_id):
    start_runner(context, runner_request(context, request_id))


@when('the deadline timer\'s wake for "{request_id}" reaches the runner naming the procedure "{procedure}"')
def deadline_wake_other_procedure(context, request_id, procedure):
    start_runner(context, runner_request(context, request_id, procedure=procedure))


@when('a follow-up wake for "{request_id}" from the owner "{owner}" reaches the runner')
def other_owner_wake(context, request_id, owner):
    start_runner(context, runner_request(context, request_id, owner=owner))


@then('the run record is acted with the reason "{reason}" and names no responsibility and no rung')
def acted_without_agent(context, reason):
    (stored,) = context.client.records.values()
    assert (stored["outcome"], stored["outcomeReason"]) == ("acted", reason), stored
    assert not any(stored.get(key) for key in ("responsibility", "rung", "policyVersion", "automationId")), stored


@then('the review request "{request_id}" proceeded without review')
def proceeded(context, request_id):
    request = rr.get_review(context.reviews, request_id)
    assert request["state"] == "timed_out" and request["outcome"] == "proceeded_without_review", request


@then('the review request "{request_id}" is still open')
def still_open_request(context, request_id):
    assert rr.get_review(context.reviews, request_id)["state"] == "open"
