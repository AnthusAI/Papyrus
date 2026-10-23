import contextlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import automation_fixture as fx  # noqa: E402
from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content import automation_view, automations as au, procedure_runner as pr  # noqa: E402
from test_automation_gate import AUTOMATION, PROCEDURE, SiteClient, automation as automation_row, sweep, trigger_rows  # noqa: E402
from test_monitoring_ttab import NOW  # noqa: E402
from test_procedure_runner import NewsroomClient, triggered_table  # noqa: E402
from test_automation_run_now import ACCOUNT, INPUT, NOW as RUN_NOW, WritableTable, lambda_event  # noqa: E402

import pytest  # noqa: E402


def recent(offset):
    return datetime.fromtimestamp(NOW + offset, timezone.utc).isoformat().replace("+00:00", "Z")


@given("the TTAB monitor delivers two new decisions to Distinctive Mark with a procedure trigger")
def background(context):
    context.monitor_table, context.records, context.started, context.counts = triggered_table(), [], [], None
    context.client, context.reader = fx.site_client(), au.MonitoringReader(fx.FakeMonitoringTable())
    context.run_table, context.invoked = WritableTable(), []


@given("the site has no automation record")
def no_record(context):
    context.site = SiteClient([])


@given("the router cannot read the site's automation records")
def unreadable(context):
    context.site = SiteClient(error=PermissionError("not authorized to call listAutomations"))


@given("the site has an automation for a different procedure")
def other_procedure(context):
    context.site = SiteClient([automation_row(procedureKey="some.other.procedure")])


def with_limits(context, **limits):
    context.limits = {"timeoutSeconds": 840, "maxConcurrent": 5, **limits}
    context.site = SiteClient([automation_row(limits=context.limits)])
    context.client = fx.site_client(fx.automation_row(limits=json.dumps(context.limits)))
    context.run_table = WritableTable()


@given("the site has the TTAB automation, disabled")
def disabled(context):
    context.site = SiteClient([automation_row(enabled=False)])
    context.client = fx.site_client(fx.automation_row(enabled=False))
    context.run_table = WritableTable()


@given("the site has the TTAB automation")
def enabled(context):
    with_limits(context)


@given("the site has the TTAB automation with a timeout of {seconds:d} seconds and room for {count:d} at a time")
def with_timeout(context, seconds, count):
    with_limits(context, timeoutSeconds=seconds, maxConcurrent=count)


@given("the site has the TTAB automation with room for {count:d} at a time")
def with_room(context, count):
    with_limits(context, maxConcurrent=count)


@given("the site has the TTAB automation with a budget of {cents:d} cents per run")
def with_budget(context, cents):
    with_limits(context, budgetUsdPerRun=cents / 100)


@given("a run started by hand is still running")
def manual_running(context):
    row = {"pk": "MONITOR#ttab", "sk": f"MANUAL#distinctive.ttab#{recent(30)}", "status": "running", "startedAt": recent(30),
           "automationId": "distinctive.ttab"}
    context.monitor_table.put_item(row)
    context.run_table.put_item(fx.manual_row(stamp=RUN_NOW.replace("09:00:00.000000", "08:59:00.000000"), status="running"))


@given("a trigger row from an hour ago still says started")
def stale_row(context):
    context.monitor_table.put_item({"pk": "MONITOR#ttab", "sk": f"TRIGGER#distinctive#{PROCEDURE}#stale", "status": "started", "startedAt": recent(-3600)})


@given("a trigger row that completed a minute ago")
def done_row(context):
    context.monitor_table.put_item({"pk": "MONITOR#ttab", "sk": f"TRIGGER#distinctive#{PROCEDURE}#done", "status": "completed", "startedAt": recent(-60)})


@when("the router sweeps")
def router_sweeps(context):
    context.result, context.started = sweep(context.monitor_table, context.site)
    context.counts = context.result["counts"]


@then("both procedures start")
def both_start(context):
    assert len(context.started) == 2 and context.counts["proceduresStarted"] == 2


@then("only the run started in this sweep counts against the limit")
def only_new_run_counts(context):
    # Nothing old is in flight, so the first start finds room for 1; the second is refused by the run just started.
    assert len(context.started) == 1 and context.counts["procedureRefused"] == 1


@then("one procedure starts")
def one_starts(context):
    assert len(context.started) == 1 and context.counts["proceduresStarted"] == 1


@then("no procedure starts")
def none_start(context):
    assert context.started == [] and context.counts["proceduresStarted"] == 0


@then("the requests carry no timeout and no automation id")
def plain_requests(context):
    assert all("timeoutSeconds" not in request and "automationId" not in request["trigger"] for request in context.started)


@then("the requests carry a timeout of {seconds:d} seconds and the automation id")
def timeout_and_id(context, seconds):
    assert all(request["timeoutSeconds"] == seconds and request["trigger"]["automationId"] == "distinctive.ttab" for request in context.started)


@then("the requests carry a timeout of {seconds:d} seconds")
def timeout_only(context, seconds):
    assert {request["timeoutSeconds"] for request in context.started} == {seconds}


@then("the trigger rows say started")
def rows_started(context):
    assert {row["status"] for row in trigger_rows(context.monitor_table)} == {"started"}


@then("each trigger row says skipped because the automation is disabled")
def rows_skipped(context):
    rows = trigger_rows(context.monitor_table)
    assert {row["status"] for row in rows} == {"skipped"} and {row["reason"] for row in rows} == {"automation disabled"}


@then("both decisions were still delivered")
def delivered(context):
    assert context.counts["delivered"] == 2 and context.counts["routed"] == 2


@then("one trigger row says refused because the automation is at its limit of {count:d} at a time")
def one_refused(context, count):
    refused = [row for row in trigger_rows(context.monitor_table) if row["status"] == "refused"]
    assert len(refused) == 1 and f"at most {count} at a time" in refused[0]["reason"]


@then("both trigger rows say refused")
def both_refused(context):
    assert [row["status"] for row in trigger_rows(context.monitor_table)] == ["refused", "refused"]


# --- cost ---------------------------------------------------------------------------------------------------------------------

CALL = {"agent": "analyst", "model": "gpt-6-luna", "provider": "openai", "promptTokens": 100_000, "completionTokens": 10_000, "cachedTokens": 0}


def record_run(context, client, calls):
    context.newsroom = client
    context.outcome = pr.run_procedure_request(
        {"appsyncEndpoint": "https://abc123.appsync-api.us-east-1.amazonaws.com/graphql", "procedureKey": PROCEDURE,
         "input": {"proceeding": "1", "opinion_url": "https://x/a.pdf"}},
        client=client, execute=lambda *a, **k: {"success": True, "output": {"title": "x"}, "seconds": 3, "usage": calls},
        seconds_available=900, environment={})


@given("a procedure run that made two GPT-6 Luna calls")
def two_calls(context):
    context.calls, context.newsroom = [CALL, {**CALL, "promptTokens": 50_000, "completionTokens": 0}], NewsroomClient()


@given("a procedure run that made one call to a model with no price")
def unpriced_call(context):
    context.calls, context.newsroom = [{**CALL, "model": "mystery-1"}], NewsroomClient()


@given("a site backend that refuses the usage fields")
def old_backend(context):
    class OldBackend(NewsroomClient):
        def graphql(self, query, variables):
            if "updateProcedureRun" in query and "usage" in variables["input"]:
                raise RuntimeError("Validation error: field 'usage' is not defined")
            return super().graphql(query, variables)
    context.newsroom = OldBackend()
    context.calls = [CALL]


@when("the runner records the run")
def runner_records(context):
    from test_procedure_runner import attachment_bodies  # noqa: F401  (the attachments are served in memory)
    from papyrus_content import model_attachments
    original = model_attachments.download_attachment_buffer
    model_attachments.download_attachment_buffer = lambda client, entry, **_: entry["body"]
    try:
        record_run(context, context.newsroom, context.calls)
    finally:
        model_attachments.download_attachment_buffer = original


@when("the runner records a run that made model calls")
def runner_records_calls(context):
    runner_records(context)


@then("the run stores its model usage per call")
def stores_usage(context):
    usage = json.loads(context.newsroom.updates[0]["usage"])
    assert usage["calls"] == 2 and usage["perCall"] == context.calls and usage["models"] == {"gpt-6-luna": 2}


@then("the run stores an estimated cost from the price table")
def stores_cost(context):
    assert context.newsroom.updates[0]["costUsd"] == pytest.approx(0.015 + 0.005)


@then("the run stores its model usage with the unpriced model named")
def stores_unpriced(context):
    usage = json.loads(context.newsroom.updates[0]["usage"])
    assert usage["unpricedModels"] == ["mystery-1"] and usage["complete"] is False


@then("the run stores no cost")
def stores_no_cost(context):
    assert context.newsroom.updates[0]["costUsd"] is None


@then("the run is recorded as completed without its usage")
def recorded_without(context):
    assert context.outcome["runStatus"] == "completed" and context.outcome["costRecorded"] is False
    assert context.newsroom.updates[0]["runStatus"] == "completed" and "usage" not in context.newsroom.updates[0]


@given("a completed run that cost 8 cents and one that cost 2 cents")
def costed_runs(context):
    context.client.tables["ProcedureRun"]["run-1"].update(costUsd=0.08, usage=json.dumps(fx.usage_summary()))
    context.client.tables["ProcedureRun"]["run-2"].update(costUsd=0.02, usage=json.dumps(fx.usage_summary()))
    context.reader = au.MonitoringReader(fx.FakeMonitoringTable())


def overview(context, identity, account=ACCOUNT):
    context.refused = False
    result = automation_view.handle({"info": {"fieldName": "automationOverview"}, "identity": identity, "arguments": {}},
                                    env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.SITE_ENDPOINT}, reader_factory=lambda: context.reader,
                                    client_factory=lambda: context.client, now=1_792_756_800.0, account_id=account)
    context.refused = result.get("error") == "forbidden"
    context.overview = result


def runs_by_id(context):
    return {run["runId"]: run for run in context.overview["automations"][0]["runs"]}


@then("the 8 cent run is flagged as over budget")
def over(context):
    assert runs_by_id(context)["run-1"]["overBudget"] is True and runs_by_id(context)["run-1"]["costUsd"] == 0.08


@then("the 2 cent run is not flagged")
def not_over(context):
    assert runs_by_id(context)["run-2"]["overBudget"] is False


@given("someone ran the procedure by hand outside the automation")
def outside(context):
    assert "run-outside" in context.client.tables["ProcedureRun"]


@then("the run started outside the automation is listed apart from the automation's own runs")
def listed_apart(context):
    only = context.overview["automations"][0]
    assert [run["runId"] for run in only["outsideRuns"]] == ["run-outside"]
    assert "run-outside" not in [run["runId"] for run in only["runs"]]


# --- run now --------------------------------------------------------------------------------------------------------------------


def operator_runs(context, supplied, dry_run=False):
    context.error, context.result = None, None
    try:
        context.result = au.run_now(au.read_record(context.client.tables["Automation"]["distinctive.ttab"]),
                                    reader=au.MonitoringReader(context.run_table), writer=au.MonitoringWriter(context.run_table),
                                    invoke=context.invoked.append, actor="ryan@example.test", supplied_input=supplied, now=RUN_NOW,
                                    dry_run=dry_run)
    except au.AutomationError as error:
        context.error = str(error)


@when("an operator runs the automation now with an input")
def run_with_input(context):
    operator_runs(context, INPUT)


@when("an operator runs the automation now without an input")
def run_without_input(context):
    operator_runs(context, None)


@when("an operator runs the automation now with an input as a dry run")
def run_dry(context):
    operator_runs(context, INPUT, dry_run=True)


@then("the runner is started with the automation's procedure, that input and the automation's timeout")
def runner_started(context):
    (request,) = context.invoked
    assert request["procedureKey"] == PROCEDURE and request["input"] == INPUT and request["timeoutSeconds"] == context.limits["timeoutSeconds"]


@then("a row links the run to the automation and says who started it")
def linking_row(context):
    (row,) = context.run_table.puts
    assert row["sk"].startswith("MANUAL#distinctive.ttab#") and row["automationId"] == "distinctive.ttab" and row["requestedBy"] == "ryan@example.test"


@then("the automation's history lists that run as started by hand")
def history_lists(context):
    history = au.automation_history(au.read_record(context.client.tables["Automation"]["distinctive.ttab"]),
                                    reader=au.MonitoringReader(context.run_table), client=context.client)
    manual = [run for run in history["runs"] if run["origin"] == "manual"]
    assert len(manual) == 1 and manual[0]["requestedBy"] == "ryan@example.test"


@then("nothing is started because the input for this run is needed")
def input_needed(context):
    assert context.error and "give the input for this run" in context.error and context.invoked == [] and context.run_table.puts == []


@then("nothing is started because the automation is disabled")
def refused_disabled(context):
    assert context.error and "is disabled" in context.error and context.invoked == []


@then("nothing is started because the automation is at its limit")
def refused_limit(context):
    assert context.error and "at most 1 at a time" in context.error and context.invoked == []


@then("nothing is started and nothing is written")
def dry(context):
    assert context.result["dryRun"] is True and context.invoked == [] and context.run_table.puts == []


def console(context, identity, field="runAutomation"):
    return automation_view.handle(
        {"info": {"fieldName": field}, "identity": identity, "arguments": {"automationId": "distinctive.ttab", "input": json.dumps(INPUT)}},
        env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.SITE_ENDPOINT}, client_factory=lambda: context.client, reader_factory=lambda: context.reader,
        table_factory=lambda: context.run_table, invoker=context.invoked.append, now=1_792_832_400.0, account_id=ACCOUNT)


@when("an editor runs the automation from the console with an input")
def editor_console(context):
    context.console = console(context, {"groups": ["editor"], "claims": {"email": "ed@example.test"}})


@when("a reader runs the automation from the console with an input")
def reader_console(context):
    context.console = console(context, {"groups": ["reader"]})


@when("an operator's IAM role in the same account runs the automation from the console")
def operator_console(context):
    context.console = console(context, {"accountId": ACCOUNT, "userArn": f"arn:aws:sts::{ACCOUNT}:assumed-role/operator/ryan"})


@then("the console says the run started")
def console_started(context):
    assert context.console["state"] == "started" and len(context.invoked) == 1


@then("the console refuses the request")
def console_refused(context):
    assert context.console == {"error": "forbidden"}


@when("an operator's IAM role in the same account reads the overview")
def operator_reads(context):
    overview(context, {"accountId": ACCOUNT, "userArn": f"arn:aws:sts::{ACCOUNT}:assumed-role/operator/ryan"})


@when("an identity-pool user or a role from another account reads the overview")
def others_read(context):
    context.denied = [
        automation_view.handle({"identity": identity, "arguments": {}}, env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.SITE_ENDPOINT},
                               client_factory=lambda: context.client, account_id=ACCOUNT)
        for identity in ({"accountId": ACCOUNT, "userArn": f"arn:aws:sts::{ACCOUNT}:assumed-role/auth/x", "cognitoIdentityId": "us-east-1:abc"},
                         {"accountId": "999999999999", "userArn": "arn:aws:sts::999999999999:assumed-role/other/x"})]


@then("both callers are refused")
def request_refused(context):
    assert context.denied == [{"error": "forbidden"}, {"error": "forbidden"}]
