from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content import review_requests as rr  # noqa: E402

T0 = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


def request(context):
    return rr.get_review(context.client, context.request_id, now=context.clock.now)


@given("a site with no review requests")
def empty_site(context):
    context.client, context.clock, context.request_id, context.waited = FakeAuthoringClient(), Clock(), None, None
    context.proceeded = False


def raise_review(context, mode, procedure, reason, days=None):
    created = rr.raise_review(context.client, subject={"type": "story", "id": "story-1"}, mode=mode, reason=reason,
                              raised_by=procedure, deadline_days=days, now=context.clock.now)
    context.request_id = created["id"]


@when('the procedure "{procedure}" raises a flag on story "{story}" saying "{reason}"')
def raise_flag(context, procedure, story, reason):
    raise_review(context, "flag", procedure, reason)


@when('the procedure "{procedure}" raises a soft review on story "{story}" with a deadline in {days:d} days')
def raise_soft(context, procedure, story, days):
    raise_review(context, "soft_review", procedure, "Please review", days)


@when('the procedure "{procedure}" raises a hard gate on story "{story}" saying "{reason}"')
def raise_hard(context, procedure, story, reason):
    raise_review(context, "hard_gate", procedure, reason)


@when("the procedure waits for the review")
def wait_flag(context):
    context.waited = rr.wait_for_review(context.client, context.request_id, sleep=lambda s: (_ for _ in ()).throw(AssertionError("slept")),
                                        clock=context.clock)


@when("the procedure waits for the review until nobody has answered")
def wait_soft(context):
    context.waited = rr.wait_for_review(context.client, context.request_id, poll_seconds=3600, sleep=context.clock.sleep, clock=context.clock)
    context.proceeded = context.waited["outcome"] == "proceeded_without_review"


@when("a year goes by with nobody answering")
def a_year(context):
    try:
        rr.wait_for_review(context.client, context.request_id, poll_seconds=86_400, max_wait_seconds=365 * 86_400,
                           sleep=context.clock.sleep, clock=context.clock)
        context.proceeded = True
    except rr.ReviewStillOpen:
        context.proceeded = False


@when("the editor answers with approve")
def answer_approve(context):
    context.answered = rr.answer_review(context.client, context.request_id, decision="approve", by="editor", roles=["editor"], now=context.clock.now)


@when('the editor answers with feedback "{text}" and the steer "{steer}"')
def answer_feedback(context, text, steer):
    context.answered = rr.answer_review(context.client, context.request_id, decision="feedback", feedback=text, steer=steer,
                                        by="editor", roles=["editor"], now=context.clock.now)


@then("the wait returns at once and the request is still open")
def returned_open(context):
    assert context.waited["state"] == "open"


@then("the request has no deadline")
def no_deadline(context):
    assert request(context)["deadline"] is None


@then("the process proceeds")
def proceeds(context):
    assert context.proceeded


@then("the process has not proceeded")
def not_proceeded(context):
    assert context.proceeded is False


@then('the request is timed out with the note "{note}"')
def timed_out(context, note):
    current = request(context)
    assert current["state"] == "timed_out" and current["history"][-1]["note"] == note


@then("the request is still open")
def still_open(context):
    assert request(context)["state"] == "open"


@then("the request can no longer be answered")
def not_answerable(context):
    try:
        rr.answer_review(context.client, context.request_id, decision="approve", by="editor", now=context.clock.now)
    except rr.ReviewError:
        return
    raise AssertionError("a timed-out request accepted an answer")


@then('the outcome is "{outcome}"')
def outcome_is(context, outcome):
    assert context.answered["outcome"] == outcome, context.answered["outcome"]


@then('the feedback "{text}" is returned to the procedure')
def feedback_returned(context, text):
    assert rr.get_review(context.client, context.request_id, sweep=False)["answer"]["feedback"] == text


@then("a reader who tries to answer is refused because only editors and admins can answer")
def reader_refused(context):
    try:
        rr.answer_review(context.client, context.request_id, decision="approve", by="reader", roles=["reader"], now=context.clock.now)
    except rr.ReviewError as error:
        assert "only editors and admins" in str(error)
        return
    raise AssertionError("a reader answered")


@then('"{procedure}" reads the steering "{text}"')
def reads_steering(context, procedure, text):
    found = rr.steering_for(context.client, raised_by=procedure)
    assert [entry["feedback"] for entry in found] == [text]


@when('"{procedure}" records that run "{run}" used the steering')
def records_applied(context, procedure, run):
    rr.mark_applied(context.client, context.request_id, run_id=run, by=procedure, now=context.clock.now)


@then('the request shows it was applied in run "{run}"')
def applied_in(context, run):
    assert request(context)["appliedIn"]["runId"] == run


@then('"{procedure}" has no unapplied steering')
def no_unapplied(context, procedure):
    assert rr.steering_for(context.client, raised_by=procedure) == []


@when('the idea pipeline raises a batch review for run "{run}" with {count:d} proposals')
def raise_batch(context, run, count):
    created = rr.raise_batch_review(context.client, raised_by="idea-pipeline", batch_id=run,
                                    idea_ids=[f"idea-{n}" for n in range(count)], now=context.clock.now)
    context.request_id = created["id"]


@when('the idea pipeline raises the batch review for run "{run}" again')
def raise_batch_again(context, run):
    rr.raise_batch_review(context.client, raised_by="idea-pipeline", batch_id=run, idea_ids=["idea-0", "idea-1", "idea-2"],
                          now=context.clock.now)


@then('there is one open soft review "{reason}"')
def one_open_soft(context, reason):
    found = rr.list_reviews(context.client, state="open", now=context.clock.now)
    assert len(found) == 1 and found[0]["mode"] == "soft_review" and found[0]["reason"] == reason


@then("it has no deadline")
def has_no_deadline(context):
    assert request(context)["deadline"] is None


@when('the procedure "{procedure}" raises a soft review on story "{story}" with no deadline')
def raise_soft_open_ended(context, procedure, story):
    raise_review(context, "soft_review", procedure, "Please review")


@when("ten years go by with nobody answering")
def ten_years(context):
    context.clock.now += timedelta(days=3650)
    context.expired = rr.expire_due(context.client, now=context.clock.now)


@then("the request was not timed out")
def not_timed_out(context):
    assert context.expired == [] and request(context)["state"] == "open"


@then("there is still one review request")
def still_one(context):
    assert len(context.client.list_records("ReviewRequest")) == 1


@given('a site whose admin is "{admin}" and whose editor is "{editor}"')
def site_with_users(context, admin, editor):
    context.client = FakeAuthoringClient({"UserRoleAssignment": [
        {"id": "u1", "role": "admin", "status": "active", "email": admin},
        {"id": "u2", "role": "editor", "status": "active", "email": editor}]})
    import os
    os.environ.pop("PAPYRUS_SITE_OWNER_EMAIL", None)


@when("no recipient rule is set and a hard gate is raised")
def no_rule(context):
    context.recipients = rr.resolve_recipients(context.client, mode="hard_gate")


@then("the recipients are the site's admins")
def admins(context):
    assert context.recipients["emails"] == ["admin@example.test"]


@when('an admin sets the hard gate rule to editors plus the extra address "{extra}"')
def set_mode_rule(context, extra):
    rr.set_recipient_rule(context.client, scope="mode", key="hard_gate", roles=["editor"], emails=[extra], by="admin")


@then('the recipients of a hard gate are "{first}" and "{second}"')
def hard_recipients(context, first, second):
    assert rr.resolve_recipients(context.client, mode="hard_gate")["emails"] == sorted([first, second])


@when('an admin sets a rule for the automation "{automation}" to the address "{address}"')
def set_automation_rule(context, automation, address):
    rr.set_recipient_rule(context.client, scope="automation", key=automation, roles=[], emails=[address], by="admin")


@then('the recipients of a hard gate from "{automation}" are "{address}"')
def automation_recipients(context, automation, address):
    assert rr.resolve_recipients(context.client, mode="hard_gate", automation=automation)["emails"] == [address]
