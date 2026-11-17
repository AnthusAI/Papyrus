import json
import sys
from pathlib import Path

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_procedure_runner as tpr  # noqa: E402
from papyrus_content.agent_policy import PersonStart
from papyrus_content import model_attachments, procedure_runner as pr, wake_keys  # noqa: E402


class SiteBackend(tpr.NewsroomClient):
    """A site backend as the start mutation behaves: the record's id comes from the wake key and a second create is refused."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.records, self.calls, self.records_at_load = {}, [], []

    def graphql(self, query, variables):
        if "startNewsroomProcedureRun" in query:
            self.calls.append("start")
            run_id = "run-for-" + variables["wakeKey"]
            if run_id in self.records:
                return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": True, "runId": run_id, "runStatus": self.records[run_id]["runStatus"]})}
            self.records[run_id] = {"id": run_id, "runStatus": "started", "wakeKey": variables["wakeKey"]}
            return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": False, "runId": run_id, "procedureVersionId": "version-1"})}
        if "getNewsroomProcedureDefinition" in query:
            self.calls.append("load")
            self.records_at_load.append({run_id: dict(record) for run_id, record in self.records.items()})
        result = super().graphql(query, variables)
        if "updateProcedureRun" in query:
            self.records[variables["input"]["id"]].update(variables["input"])
        return result


def new_backend(context, **kwargs):
    context.client = SiteBackend(**kwargs)
    context.runs, context.executed, context.results = [], [], []


@given('a site with a published procedure "{key}"')
def site(context, key):
    new_backend(context)
    context.procedure_key = key
    original = model_attachments.download_attachment_buffer
    model_attachments.download_attachment_buffer = lambda client, entry, **_: entry["body"]
    context.add_cleanup(setattr, model_attachments, "download_attachment_buffer", original)


@given("the procedure is not published")
def unpublished(context):
    new_backend(context, status="draft")


def deliver(context, key):
    request = {**tpr.REQUEST, "procedureKey": context.procedure_key, "wakeKey": key}

    def execute(*args, **kwargs):
        context.executed.append(key)
        return {"success": True, "output": {"title": "x"}, "seconds": 1}

    result = pr.run_procedure_request(request, policy=PersonStart(), client=context.client, execute=execute, seconds_available=900, environment={})
    context.results.append(result)
    return result


@when('the wake "{key}" is delivered')
def delivered(context, key):
    deliver(context, key)


@when('the wake "{key}" is delivered again')
def delivered_again(context, key):
    deliver(context, key)


@when('the wake "{key}" is delivered and refused')
def delivered_refused(context, key):
    try:
        deliver(context, key)
    except pr.ProcedureNotRunnable as error:
        context.refusal = error


@when('a run is requested with the wake key "{key}"')
def requested(context, key):
    try:
        deliver(context, "" if key == "(none)" else key)
    except pr.ProcedureNotRunnable as error:
        context.refusal = error


@then("the procedure ran {count:d} time")
@then("the procedure ran {count:d} times")
def ran(context, count):
    assert len(context.executed) == count, context.executed


@then("the site holds {count:d} run record")
@then("the site holds {count:d} run records")
def holds(context, count):
    assert len(context.client.records) == count, context.client.records


@then("the second delivery is reported as a duplicate of the first run")
def duplicate(context):
    first, second = context.results
    assert second["duplicate"] is True and second["runStatus"] == pr.DUPLICATE and second["runId"] == first["runId"], second


@then("the first thing the site is asked is to start a run record")
def first_call(context):
    assert context.client.calls[0] == "start", context.client.calls


@then('the run record was made with the status "{status}" and the wake key')
def record_made(context, status):
    record = context.client.records_at_load[0]["run-for-fact-check|story-1|v7|story.stage_entered"]
    assert record["runStatus"] == status and record["wakeKey"] == "fact-check|story-1|v7|story.stage_entered", record


@then("the procedure was loaded after the record existed")
def loaded_after(context):
    assert context.client.records_at_load and context.client.calls.index("load") > context.client.calls.index("start")


@then("the run record says it failed because the procedure was not runnable")
def refused_record(context):
    (record,) = context.client.records.values()
    assert (record["runStatus"], record["outcome"], record["outcomeReason"]) == ("failed", "failed", "not_runnable"), record
    assert context.refusal.run_id == record["id"]


@then("the request is refused for its wake key")
def refused_key(context):
    assert "wake key" in str(context.refusal), context.refusal


@then('the change key for "{owner}", "{subject}", "{version}" and "{what}" is "{key}"')
def change_key(context, owner, subject, version, what, key):
    assert wake_keys.change_key(owner, subject, version, what) == key


@then('the timer key for "{owner}" at "{when}" is "{key}"')
def timer_key(context, owner, when, key):
    assert wake_keys.schedule_key(owner, when) == key


@then('the manual key for "{owner}" and request "{request}" is "{key}"')
def manual_key(context, owner, request, key):
    assert wake_keys.manual_key(owner, request) == key


@then('the change key for a Reference with no versions says "{word}"')
def unversioned(context, word):
    key = wake_keys.change_key("monitor", "reference-1", None, "monitor.new_reference")
    assert key == f"monitor|reference-1|{word}|monitor.new_reference"
    wake_keys.checked(key)


@then("a start that no automation governs is owned by its procedure")
def procedure_owner(context):
    assert wake_keys.owner(None, "newsroom.fact-check") == "procedure:newsroom.fact-check"
    assert wake_keys.owner("fact-check", "newsroom.fact-check") == "fact-check"


@then("a part that contains the separator is refused")
def separator(context):
    try:
        wake_keys.manual_key("rating", "a|b")
    except wake_keys.InvalidWakeKey:
        return
    raise AssertionError("a part with the separator was accepted")
