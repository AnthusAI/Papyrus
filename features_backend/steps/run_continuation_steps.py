"""Continuation of a unit of work across runs (features_backend/agents/run-continuation.feature)."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_procedure_runner as tpr  # noqa: E402
from papyrus_content import model_attachments, procedure_runner as pr, run_continuation  # noqa: E402
from papyrus_content.agent_policy import PersonStart  # noqa: E402

ROOT_RUN = "run-root"


class ContinuationBackend(tpr.NewsroomClient):
    def __init__(self):
        super().__init__()
        self.records = {}

    def graphql(self, query, variables):
        result = super().graphql(query, variables)
        if "updateProcedureRun" in query:
            self.records[variables["input"]["id"]] = variables["input"]
        return result


@given('a site backend with a published procedure for continuation "{key}"')
def backend(context, key):
    context.client, context.procedure_key = ContinuationBackend(), key
    context.timers, context.timer_refuses, context.has_timer_service, context.chain = [], False, True, 0
    original = model_attachments.download_attachment_buffer
    model_attachments.download_attachment_buffer = lambda client, entry, **_: entry["body"]
    context.add_cleanup(setattr, model_attachments, "download_attachment_buffer", original)


@given('the run is itself continuation {number:d} of the chain that began with run "{root}"')
def in_chain(context, number, root):
    context.chain, context.chain_root = number, root


@given("the timer service refuses the timer")
def refuses(context):
    context.timer_refuses = True


@given("the runner has no timer service")
def no_service(context):
    context.has_timer_service = False


def run_with_output(context, output):
    trigger = {"kind": "event", "automationId": "translator", "summary": "translator woke", "paid": True, "story": "story-1", "version": "7"}
    wake_key = "translator|story-1|7|stage_entered"
    if context.chain:
        trigger = {**trigger, "kind": "continuation", "continuation": context.chain, "continuationRoot": context.chain_root}
        wake_key = f"translator|story-1|{context.chain_root}|c{context.chain}"
    request = {**tpr.REQUEST, "procedureKey": context.procedure_key, "wakeKey": wake_key, "trigger": trigger}

    def schedule(following, due_at, run_id):
        if context.timer_refuses:
            raise RuntimeError("the scheduler refused")
        context.timers.append({"request": following, "dueAt": due_at, "runId": run_id})

    context.request = request
    context.result = pr.run_procedure_request(
        request, policy=PersonStart(), client=context.client, seconds_available=900, environment={},
        execute=lambda *args, **kwargs: {"success": True, "output": output, "seconds": 1},
        schedule_continuation=schedule if context.has_timer_service else None)


@when('the procedure finishes part of its work and asks for its next run at "{when}"')
def partial(context, when):
    run_with_output(context, {"title": "x", run_continuation.NEXT_WAKE_KEY: when})


@when("the procedure finishes all of its work")
def complete(context):
    run_with_output(context, {"title": "x"})


def record(context):
    (stored,) = context.client.records.values()
    return stored


@then('the continuation run record is completed with the outcome "{outcome}"')
def completed(context, outcome):
    stored = record(context)
    assert (stored["runStatus"], stored["outcome"]) == ("completed", outcome), stored


@then('the continuation run record is failed with the outcome "{outcome}" and the reason "{reason}"')
def failed(context, outcome, reason):
    stored = record(context)
    assert (stored["runStatus"], stored["outcome"], stored["outcomeReason"]) == ("failed", outcome, reason), stored


@then('one timer is set for "{when}" whose wake key ends in "{suffix}"')
def timer_set(context, when, suffix):
    (timer,) = context.timers
    assert timer["dueAt"] == when and timer["request"]["wakeKey"].endswith(suffix), timer


@then("no timer is set")
def no_timer(context):
    assert context.timers == []


@then("the timer's wake is the same procedure with the same input and the same trigger, marked as a continuation {number:d}")
def same_wake(context, number):
    (timer,) = context.timers
    following, original = timer["request"], context.request
    assert following["procedureKey"] == original["procedureKey"] and following["input"] == original["input"], following
    trigger = following["trigger"]
    assert trigger["kind"] == "continuation" and trigger["continuation"] == number and trigger["paid"] is True, trigger
    assert trigger["automationId"] == original["trigger"]["automationId"] and trigger["story"] == "story-1", trigger


@then('the wake key names the chain\'s first run "{root}"')
def names_root(context, root):
    (timer,) = context.timers
    assert timer["request"]["wakeKey"].split("|")[2] == root, timer
