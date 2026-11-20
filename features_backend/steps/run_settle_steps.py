"""Settling an interrupted run (features_backend/agents/run-settle.feature)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from behave import given, then, when

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "procedures" / "newsroom" / "tests"))
import test_procedure_runner as tpr  # noqa: E402
from papyrus_content import model_attachments, procedure_runner as pr, run_outcomes, run_attention  # noqa: E402
from papyrus_content.agent_policy import PersonStart  # noqa: E402


class SettlingBackend(tpr.NewsroomClient):
    def __init__(self):
        super().__init__()
        self.records, self.refuse_updates = {}, False

    def graphql(self, query, variables):
        if "startNewsroomProcedureRun" in query:
            run_id = "run-for-" + variables["wakeKey"]
            if run_id in self.records:
                return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": True, "runId": run_id, "runStatus": self.records[run_id]["runStatus"]})}
            self.records[run_id] = {"id": run_id, "runStatus": "started", "wakeKey": variables["wakeKey"]}
            return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": False, "runId": run_id, "procedureVersionId": "version-1"})}
        if "updateProcedureRun" in query and self.refuse_updates:
            raise RuntimeError("the backend refused the write")
        result = super().graphql(query, variables)
        if "updateProcedureRun" in query:
            self.records[variables["input"]["id"]].update(variables["input"])
        return result

    def get_record(self, model, record_id):
        assert model == "ProcedureRun"
        return self.records.get(record_id)


def ordinal(text):
    return int(re.match(r"\d+", text).group())


@given('a site backend that keeps run records for the procedure "{key}"')
def backend(context, key):
    context.client, context.procedure_key, context.executed, context.result, context.failure = SettlingBackend(), key, [], None, None
    context.trigger_extra = {}
    original = model_attachments.download_attachment_buffer
    model_attachments.download_attachment_buffer = lambda client, entry, **_: entry["body"]
    context.add_cleanup(setattr, model_attachments, "download_attachment_buffer", original)


@given('the wake "{key}" has a run record that was started and never finished')
def died(context, key):
    context.wake_key = key
    run_id = "run-for-" + key
    context.client.records[run_id] = {"id": run_id, "runStatus": "started", "wakeKey": key, "startedAt": "2026-11-20T09:00:00Z"}


@given("the wake says its procedure is safe to repeat")
def safe(context):
    context.trigger_extra = {"safeToRepeat": True}


@given("the wake says its procedure is not marked safe to repeat")
def unsafe(context):
    context.trigger_extra = {"safeToRepeat": False}


@given("the wake says nothing about repeating its procedure")
def silent(context):
    context.trigger_extra = {}


@given("the site backend refuses to record the outcome")
def refuses(context):
    context.client.refuse_updates = True


def deliver(context, receive_count):
    request = {**tpr.REQUEST, "procedureKey": context.procedure_key, "wakeKey": context.wake_key,
               "trigger": {"kind": "event", "automationId": "settler", "summary": "settler woke", **context.trigger_extra}}

    def execute(*args, **kwargs):
        context.executed.append(context.wake_key)
        return {"success": True, "output": {"title": "x"}, "seconds": 1}

    context.result = pr.run_procedure_request(request, policy=PersonStart(), client=context.client, execute=execute, seconds_available=900,
                                              environment={}, receive_count=receive_count)


@given("the queue has delivered that wake for the {nth} time")
@when("the queue delivers that wake for the {nth} time")
@when("the queue delivers that wake for the {nth} time again")
def delivered(context, nth):
    deliver(context, ordinal(nth))


@when("the queue delivers that wake for the {nth} time and settling crashes")
def delivered_and_crashes(context, nth):
    try:
        deliver(context, ordinal(nth))
    except RuntimeError as error:
        context.failure = error


def record(context):
    return context.client.records["run-for-" + context.wake_key]


@then('the run record is completed with the outcome "{outcome}" on attempt {attempt:d}')
def completed_on_attempt(context, outcome, attempt):
    stored = record(context)
    assert (stored["runStatus"], stored["outcome"], stored["attempt"]) == ("completed", outcome, attempt), stored


@then('the run record is failed with the outcome "{outcome}" and the reason "{reason}"')
def failed_with_reason(context, outcome, reason):
    stored = record(context)
    assert (stored["runStatus"], stored["outcome"], stored["outcomeReason"]) == ("failed", outcome, reason), stored


@then("the run is on the list of runs that need a person")
def needs_a_person(context):
    stored = record(context)
    assert stored["attentionKey"] == run_attention.attention_key() and stored["dueAt"] == stored["finishedAt"], stored
    assert run_attention.needs_attention(stored)


@then("the delivery is reported as a duplicate of the first run")
def duplicate(context):
    assert context.result["duplicate"] is True and context.result["runStatus"] == pr.DUPLICATE, context.result


@then("the run record is still started")
def still_started(context):
    assert record(context)["runStatus"] == "started" and not record(context).get("outcome"), record(context)


@then("the delivery fails, so the message stays on the queue")
def fails(context):
    assert isinstance(context.failure, RuntimeError) and context.result is None


@then("the wake queue moves a message to its dead-letter queue after {count:d} deliveries")
def dead_letter(context, count):
    source = (REPO / "amplify" / "agents" / "wake-queue.ts").read_text()
    assert re.search(rf"WAKE_MAXIMUM_RECEIVES\s*=\s*{count};", source)
    assert "maxReceiveCount: WAKE_MAXIMUM_RECEIVES" in source
