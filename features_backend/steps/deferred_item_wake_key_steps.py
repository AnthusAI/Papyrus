import json
import sys
from pathlib import Path

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_procedure_runner as tpr  # noqa: E402
from papyrus_content.agent_policy import PersonStart  # noqa: E402
from papyrus_content import model_attachments, procedure_runner as pr, wake_keys  # noqa: E402
from test_automation_gate import trigger_rows  # noqa: E402

# The steps that build the monitor, the site's automation and the sweeps are shared with automation-limits-and-run-now.feature.


class SiteBackend(tpr.NewsroomClient):
    """A site backend as the start mutation behaves: the run's id comes from the wake key and a second create is refused."""

    def __init__(self):
        super().__init__()
        self.records = {}

    def graphql(self, query, variables):
        if "startNewsroomProcedureRun" in query:
            run_id = "run-for-" + variables["wakeKey"]
            if run_id in self.records:
                return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": True, "runId": run_id, "runStatus": self.records[run_id]["runStatus"]})}
            self.records[run_id] = {"id": run_id, "runStatus": "started", "wakeKey": variables["wakeKey"]}
            return {"startNewsroomProcedureRun": json.dumps({"ok": True, "duplicate": False, "runId": run_id, "procedureVersionId": "version-1"})}
        return super().graphql(query, variables)


def deferred_rows(context):
    rows = [row for row in trigger_rows(context.monitor_table) if row["status"] == "deferred"]
    return sorted(rows, key=lambda row: row["createdAt"])


def row_key(row):
    """The key a first start of this row's item would have used, written out by hand so the test does not use the code it checks."""
    return f"{row['automationId']}|{row['referenceId']}|unversioned|monitor.new_reference"


def stored(context, row):
    return context.monitor_table.items[(row["pk"], row["sk"])]


def retried(context):
    (request,) = context.started
    (row,) = [r for r in trigger_rows(context.monitor_table) if r["status"] == "started" and r.get("retriedAt")]
    return request, row


@given("the router sweeps and defers two decisions")
def sweeps_and_defers(context):
    from test_automation_gate import sweep
    context.result, context.started = sweep(context.monitor_table, context.site)
    assert len(context.started) == 1 and len(deferred_rows(context)) == 2
    context.original_keys = {row["sk"]: row["request"]["wakeKey"] for row in deferred_rows(context)}


@given("the deferred rows were stored before wake keys, with no key on their requests")
def stored_before(context):
    for row in deferred_rows(context):
        stored(context, row)["request"].pop("wakeKey")


@given("the deferred rows carry a wake key for some other Reference")
def other_key(context):
    for row in deferred_rows(context):
        stored(context, row)["request"]["wakeKey"] = wake_keys.change_key(row["automationId"], "some-other-reference", None, "monitor.new_reference")


@given("the deferred rows have lost their Reference id")
def lost_reference(context):
    for row in deferred_rows(context):
        stored(context, row).pop("referenceId")


@given("the first attempt of the first deferred item already made its run record")
def first_attempt_ran(context):
    context.backend = SiteBackend()
    original = model_attachments.download_attachment_buffer
    model_attachments.download_attachment_buffer = lambda client, entry, **_: entry["body"]
    context.add_cleanup(setattr, model_attachments, "download_attachment_buffer", original)
    context.first_key = row_key(deferred_rows(context)[0])
    first = pr.run_procedure_request({**tpr.REQUEST, "procedureKey": "newsroom.fact-check", "wakeKey": context.first_key}, policy=PersonStart(), client=context.backend,
                                     execute=lambda *args, **kwargs: {"success": True, "output": {"title": "x"}, "seconds": 1},
                                     seconds_available=900, environment={})
    assert not first.get("duplicate") and len(context.backend.records) == 1


@then("1 deferred item starts")
def one_retried(context):
    assert len(context.started) == 1 and context.counts["procedureRetried"] == 1 and context.counts["procedureStartFailed"] == 0, context.counts


@then("its request carries the wake key built from its row")
def key_from_row(context):
    request, row = retried(context)
    assert request["wakeKey"] == row_key(row)
    assert wake_keys.checked(request["wakeKey"]) == request["wakeKey"]


@then("its request carries the same wake key its deferred row was stored with")
def same_as_first(context):
    request, row = retried(context)
    assert request["wakeKey"] == context.original_keys[row["sk"]] == row_key(row)


@then("its row now holds the key it started with")
def row_holds_key(context):
    request, row = retried(context)
    assert row["request"]["wakeKey"] == request["wakeKey"]


@then("that row says started")
def row_started(context):
    request, row = retried(context)
    assert row["status"] == "started" and row["request"]["wakeKey"] == request["wakeKey"]


@then("the other deferred item starts, and no item has started twice")
def other_starts(context):
    assert len(context.started) == 1 and not deferred_rows(context)
    keys = [row["request"]["wakeKey"] for row in trigger_rows(context.monitor_table)]
    assert len(keys) == 3 and len(set(keys)) == 3, keys


@then("the runner reports it as a duplicate of the run that exists")
def duplicate(context):
    (request,) = context.started
    assert request["wakeKey"] == context.first_key
    result = pr.run_procedure_request({**tpr.REQUEST, "procedureKey": "newsroom.fact-check", "wakeKey": request["wakeKey"]}, policy=PersonStart(), client=context.backend,
                                      execute=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ran twice")),
                                      seconds_available=900, environment={})
    assert result["duplicate"] is True and result["runId"] == "run-for-" + context.first_key


@then("the site holds 1 run record for it")
def one_record(context):
    assert len(context.backend.records) == 1


@then("no deferred item starts")
def none_retried(context):
    assert context.started == [] and context.counts["procedureRetried"] == 0


@then("2 rows say startFailed and name the missing Reference id as the reason")
def reported(context):
    rows = [row for row in trigger_rows(context.monitor_table) if row["status"] == "startFailed"]
    assert len(rows) == 2 and all("no wake key" in row["error"] and "referenceId=None" in row["error"] for row in rows), rows


@then("the sweep counts 2 failed starts")
def counted(context):
    assert context.counts["procedureStartFailed"] == 2
