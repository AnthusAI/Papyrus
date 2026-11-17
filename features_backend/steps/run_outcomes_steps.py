import json
import sys
from pathlib import Path

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import automation_fixture as fx  # noqa: E402
import test_automations as ta  # noqa: E402
import test_procedure_runner as tpr  # noqa: E402
from papyrus_content.agent_policy import PersonStart
from papyrus_content import automations as au, model_attachments, procedure_runner as pr  # noqa: E402


def declare(context, outcome=None, reason=None):
    output = {"title": "Board affirms"}
    if outcome is not None:
        output["run_outcome"] = outcome
    if reason is not None:
        output["run_outcome_reason"] = reason
    context.execution = {"success": True, "output": output, "seconds": 3}


@given("a procedure that finishes and returns a title")
def finishes(context):
    declare(context)


@given('a procedure that looks at a feed and returns run_outcome "nothing" with run_outcome_reason "{reason}"')
def nothing(context, reason):
    declare(context, "nothing", reason)


@given('a procedure that returns run_outcome "nothing" with no run_outcome_reason')
def nothing_no_reason(context):
    declare(context, "nothing")


@given('a procedure that raises a review request and returns run_outcome "asked" with run_outcome_reason "{reason}"')
def asked(context, reason):
    declare(context, "asked", reason)


@given('a procedure that returns run_outcome "{outcome}" with run_outcome_reason "{reason}"')
def declares(context, outcome, reason):
    declare(context, outcome, reason)


@given("a procedure that stops with an error")
def stops(context):
    context.execution = {"success": False, "error": "RuntimeError: the opinion could not be read", "seconds": 2, "logTail": "trace"}


@given("a procedure that runs past its deadline")
def deadline(context):
    context.execution = {"success": False, "error": "timed out after 840 s", "seconds": 840}


@given('a story-stage automation started a procedure for the story "{story}" at version "{version}"')
def stage_started(context, story, version):
    declare(context)
    context.trigger = {"kind": "event", "event": "story.stage_entered", "automationId": "distinctive.ruling.fact-check",
                       "story": story, "stage": "reporting", "version": version}


@when("the runner runs it")
def runner_runs(context):
    original = model_attachments.download_attachment_buffer
    model_attachments.download_attachment_buffer = lambda client, entry, **_: entry["body"]
    context.client = tpr.NewsroomClient()
    request = {**tpr.REQUEST, "trigger": getattr(context, "trigger", None)}
    try:
        context.result = pr.run_procedure_request(request, policy=PersonStart(), client=context.client, execute=lambda *a, **k: context.execution,
                                                  seconds_available=900, environment={})
    finally:
        model_attachments.download_attachment_buffer = original
    context.update = context.client.updates[0]


@then('the run is recorded as {status} with the outcome "{outcome}"')
def recorded(context, status, outcome):
    assert (context.update["runStatus"], context.update["outcome"]) == (status, outcome), context.update


@then('the run result carries the outcome "{outcome}"')
def result_outcome(context, outcome):
    assert context.result["outcome"] == outcome


@then('the outcome reason is "{reason}"')
def reason_is(context, reason):
    assert context.update["outcomeReason"] == reason, context.update


@then("no error is recorded on the run")
def no_error(context):
    assert context.update["error"] is None and context.update["errorSummary"] is None


@then("the run's error says a nothing-to-do outcome needs a reason")
def error_says(context):
    assert "nothing-to-do outcome needs a reason" in context.update["errorSummary"]


@then("the error is kept on the run")
def error_kept(context):
    assert "could not be read" in context.update["errorSummary"] and context.update["error"] is not None


@then('the run records the automation id and the subject "{kind}" "{subject}" at version "{version}"')
def subject(context, kind, subject, version):
    u = context.update
    assert (u["automationId"], u["subjectKind"], u["subjectId"], u["subjectVersion"]) == (
        "distinctive.ruling.fact-check", kind, subject, version), u


@then("the run records no subject")
def no_subject(context):
    u = context.update
    assert (u["subjectKind"], u["subjectId"], u["subjectVersion"]) == (None, None, None), u


class Rows:
    def __init__(self):
        self.items = {("MONITOR#ttab", "MANUAL#a#1"): {"status": "running"}}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues, **_):
        item = self.items[(Key["pk"], Key["sk"])]
        for assignment in UpdateExpression.removeprefix("SET ").split(", "):
            name, value = assignment.split(" = ")
            item[ExpressionAttributeNames.get(name, name)] = ExpressionAttributeValues[value]


TRIGGER_KEY = {"pk": "MONITOR#ttab", "sk": "MANUAL#a#1"}


@given('a trigger row for a run that found nothing to do for the reason "{reason}"')
def trigger_nothing(context, reason):
    context.trigger_table = Rows()
    context.trigger_result = {"runStatus": "completed", "runId": "run-1", "outcome": "nothing", "outcomeReason": reason, "error": None}


@given("a trigger row for a request the runner refused")
def trigger_refused(context):
    context.trigger_table = Rows()
    context.trigger_result = {"runStatus": "notRunnable", "runId": None, "outcome": "failed", "outcomeReason": "not_runnable", "error": "x"}


@when("the runner records the trigger row")
def record_row(context):
    pr.record_trigger_outcome(context.trigger_table, TRIGGER_KEY, context.trigger_result)


@then('the trigger row says the outcome is "{outcome}" with the reason "{reason}"')
def row_says(context, outcome, reason):
    row = context.trigger_table.items[("MONITOR#ttab", "MANUAL#a#1")]
    assert (row["outcome"], row["outcomeReason"]) == (outcome, reason), row


def world(context, run):
    context.client = fx.site_client(fx.automation_row())
    context.client.tables["ProcedureRun"]["run-1"] = run
    context.reader = ta.reader(fx.FakeMonitoringTable([fx.router_config(), fx.trigger_row("97752244-EXA_26", run["runStatus"], run_id="run-1")]))


def finished_run(**fields):
    run = fx.procedure_run("run-1", "completed", started="2026-10-23T08:00:00Z", finished="2026-10-23T08:03:00Z", output={"title": "x"})
    run.update(fields)
    return run


@given('a finished run recorded with the outcome "{outcome}"')
def with_outcome(context, outcome):
    world(context, finished_run(outcome=outcome))


@given('a finished run that found nothing to do for the reason "{reason}"')
def with_reason(context, reason):
    world(context, finished_run(outcome="nothing", outcomeReason=reason))


@given("a finished run recorded before outcomes existed")
def before(context):
    world(context, finished_run())
    context.before = dict(context.client.tables["ProcedureRun"]["run-1"])


@given("a run that is still running")
def running(context):
    world(context, fx.procedure_run("run-1", "running", started="2026-10-23T08:00:00Z", finished=None))


@when("an operator reads the run list")
def reads(context):
    history = au.automation_history(ta.record(), reader=context.reader, client=context.client)
    context.shown = [run["outcomeShown"] for run in history["runs"] if run["runId"] == "run-1"]


@then('the run is shown as "{shown}"')
def shown(context, shown):
    assert context.shown == [shown], context.shown


@then("the stored run still has no outcome")
def not_rewritten(context):
    assert context.client.tables["ProcedureRun"]["run-1"] == context.before


@then('the output has a run line containing "{text}"')
def run_line(context, text):
    assert any(line.startswith("run\t") and text in line for line in context.cli_output.splitlines()), context.cli_output
