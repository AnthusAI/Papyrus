import json
from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import automation_fixture as fx  # noqa: E402
from fake_client import FakeAuthoringClient  # noqa: E402
from papyrus_content import automation_view  # noqa: E402
from papyrus_content import automations as au  # noqa: E402


def overview_for(context, groups, endpoint=None):
    context.refused = False
    result = automation_view.handle(
        {"identity": {"groups": groups}, "arguments": {}},
        env={"PAPYRUS_GRAPHQL_ENDPOINT": endpoint or fx.SITE_ENDPOINT},
        reader_factory=lambda: context.reader, client_factory=lambda: context.client, now=1_792_756_800.0)
    if result.get("error") == "forbidden":
        context.refused = True
    context.overview = result


def automation(context):
    return context.overview["automations"][0]


def run_for(context, source_id):
    found = [run for run in automation(context)["runs"] if run["sourceId"] == source_id]
    assert found, f"no run for {source_id}: {[run['sourceId'] for run in automation(context)['runs']]}"
    return found[0]


@given("a site backend with no automations")
def empty_backend(context):
    context.client = FakeAuthoringClient({})
    context.reader = au.MonitoringReader(fx.FakeMonitoringTable())


@given("a site backend with the TTAB automation")
def ttab_backend(context):
    context.client = fx.site_client()
    context.reader = au.MonitoringReader(fx.FakeMonitoringTable([]))


@given("a site backend with the TTAB automation and its recorded runs")
def ttab_backend_with_runs(context):
    context.client = fx.site_client()
    context.reader = au.MonitoringReader(fx.FakeMonitoringTable([]))


@given("the TTAB monitor's trigger rows")
def trigger_rows(context):
    context.reader = au.MonitoringReader(fx.FakeMonitoringTable())


@given('the TTAB monitor\'s router starts "{procedure}" with the same input')
def router_same(context, procedure):
    context.reader = au.MonitoringReader(fx.FakeMonitoringTable([fx.router_config(procedure=procedure)]))


@given('the TTAB monitor\'s router starts "{procedure}" with a different input')
def router_different(context, procedure):
    context.reader = au.MonitoringReader(
        fx.FakeMonitoringTable([fx.router_config(procedure=procedure, input_template={"proceeding": "{sourceId}"})]))


@given("monitoring is not connected to the site's account")
def not_connected(context):
    context.reader = None


@when('an operator creates the automation "{automation_id}" for monitor "{monitor}" delivering to "{publication}" running "{procedure}"')
def create_monitor(context, automation_id, monitor, publication, procedure):
    context.created = au.create_automation(context.client, {
        "id": automation_id, "title": "Analyze new TTAB rulings",
        "trigger": {"kind": "monitor", "config": {"monitorId": monitor, "publicationId": publication}},
        "procedureKey": procedure, "inputTemplate": fx.TEMPLATE}, actor="operator")
    context.automation_id = automation_id


@when('an operator creates a "{kind}" automation "{automation_id}" running "{procedure}"')
def create_other_kind(context, kind, automation_id, procedure):
    context.created = au.create_automation(context.client, {
        "id": automation_id, "title": "Weekly digest", "trigger": {"kind": kind, "config": {"cron": "0 9 * * 1"}},
        "procedureKey": procedure}, actor="operator")
    context.automation_id = automation_id
    context.reader = au.MonitoringReader(fx.FakeMonitoringTable())


@when('an operator creates a monitor automation whose input uses the placeholder "{placeholder}"')
def create_invalid(context, placeholder):
    context.error = None
    try:
        au.create_automation(context.client, {
            "id": "bad", "title": "Bad", "trigger": {"kind": "monitor", "config": {"monitorId": "ttab", "publicationId": "distinctive"}},
            "procedureKey": fx.PROCEDURE, "inputTemplate": {"proceeding": placeholder}}, actor="operator")
    except au.AutomationError as error:
        context.error = str(error)


@when('an operator disables the automation "{automation_id}"')
def disable(context, automation_id):
    context.router_before = json.dumps(sorted(context.reader.table.rows.items()), default=str)
    context.updated = au.update_automation(context.client, automation_id, {"enabled": False}, actor="operator")


@when("an editor opens the automation overview")
def editor_opens(context):
    overview_for(context, ["editor"])


@when("an admin opens the automation overview")
def admin_opens(context):
    overview_for(context, ["admin"])


@when("a reader opens the automation overview")
def reader_opens(context):
    overview_for(context, ["reader"])


@when("an editor of a different site opens the automation overview")
def other_site(context):
    overview_for(context, ["editor"], endpoint=fx.OTHER_ENDPOINT)


@then("the automation is stored enabled with the router's input template")
def stored_enabled(context):
    stored = au.read_record(context.client.tables["Automation"][context.automation_id])
    assert stored["enabled"] is True and stored["inputTemplate"] == fx.TEMPLATE


@then("the automation is a supported monitor automation")
def supported(context):
    assert context.created["supported"] is True and context.created["trigger"]["kind"] == "monitor"


@then("the automation is stored")
def stored(context):
    assert context.automation_id in context.client.tables["Automation"]


@then('the automation is marked "{note}"')
def marked(context, note):
    assert context.created["supported"] is False and context.created["supportNote"] == note


@then("the automation has no run history")
def no_history(context):
    history = au.automation_history(context.created, reader=context.reader, client=context.client)
    assert history["runs"] == [] and history["lastRun"] is None


@then("the creation is refused because of an unknown placeholder")
def refused_placeholder(context):
    assert context.error and "unknown placeholder" in context.error


@then("no automation is stored")
def nothing_stored(context):
    assert context.client.write_calls() == []


@then('the automation\'s router link is "{state}"')
def link_state(context, state):
    assert automation(context)["link"]["state"] == state


@then("the newest run is listed first")
def newest_first(context):
    started = [run["startedAt"] for run in automation(context)["runs"]]
    assert started == sorted(started, reverse=True) and automation(context)["lastRun"] == automation(context)["runs"][0]


@then('the completed run for "{source_id}" took {seconds:d} seconds and created the story "{story}"')
def completed_run(context, source_id, seconds, story):
    run = run_for(context, source_id)
    assert run["status"] == "completed" and run["durationSeconds"] == seconds and run["storyId"] == story


@then('the failed run for "{source_id}" shows the error "{error}"')
def failed_run(context, source_id, error):
    run = run_for(context, source_id)
    assert run["status"] == "failed" and run["error"] == error and run["storyId"] is None


@then('the run for "{source_id}" is started with no run record yet')
def started_run(context, source_id):
    run = run_for(context, source_id)
    assert run["status"] == "started" and run["runId"] is None and run["runRecord"] == "none"


@then('the run for "{source_id}" could not start')
def start_failed(context, source_id):
    assert run_for(context, source_id)["status"] == "startFailed"


@then('the run for "{source_id}" says its run record was not found')
def record_missing(context, source_id):
    assert run_for(context, source_id)["runRecord"] == "missing"


@then("{count:d} items are reported as not started because the Reference already existed")
def skipped(context, count):
    assert automation(context)["skippedAlreadyHadReference"] == count


@then('no listed run has the status "{status}"')
def no_status(context, status):
    assert all(run["status"] != status for run in automation(context)["runs"])


@then("every run reports its cost as unknown")
def cost_unknown(context):
    assert all(run["costUsd"] is None for run in automation(context)["runs"])


@then("the cost note says the cost was not recorded for that run")
def cost_note(context):
    found = [run for run in automation(context)["runs"] if run["runRecord"] == "found"]
    assert found and all(run["costNote"] == "not recorded for this run" for run in found)


@then("the record shows the automation as disabled")
def shows_disabled(context):
    assert context.updated["enabled"] is False


@then("the record says the router starts nothing for a disabled automation")
def router_honours(context):
    assert context.updated["enabledNote"] == "the router starts nothing for a disabled automation"


@then("the router's configuration and the trigger rows are unchanged")
def router_unchanged(context):
    assert json.dumps(sorted(context.reader.table.rows.items()), default=str) == context.router_before


@then('the overview lists the automation "{title}"')
def lists(context, title):
    assert automation(context)["title"] == title


@then("the automation has no run history because it belongs to another publication")
def other_publication(context):
    assert automation(context)["runs"] == [] and automation(context)["notice"] == "other_publication"


@then("the trigger rows of the other publication are never returned")
def never_other(context):
    assert "99999999-OTH_26" not in json.dumps(context.overview)


@then("the automation says run history cannot be shown")
def cannot_show(context):
    assert automation(context)["notice"] == "monitoring_not_configured" and automation(context)["runs"] == []


@then("the overview contains no endpoint or secret parameter name")
def no_secrets(context):
    blob = json.dumps(context.overview)
    for marker in fx.SECRET_MARKERS:
        assert marker not in blob


# --- the command line ---

def run_cli(context, line):
    import contextlib
    import io
    import papyrus_content.graphql_authoring as graphql_authoring
    words = line.split()
    assert words[0] == "automations"
    original_client, original_reader = graphql_authoring.create_authoring_client, au.monitoring_reader_from_environment
    graphql_authoring.create_authoring_client = lambda *a, **k: (context.client, {})
    au.monitoring_reader_from_environment = lambda env=None: context.reader
    out, context.cli_error = io.StringIO(), None
    try:
        with contextlib.redirect_stdout(out):
            au.run_command(words[1], words[2:])
    except au.AutomationError as error:
        context.cli_error = str(error)
    finally:
        graphql_authoring.create_authoring_client, au.monitoring_reader_from_environment = original_client, original_reader
    context.cli_output = out.getvalue()


@when('an operator runs "{line}"')
def operator_runs(context, line):
    run_cli(context, line)


@then('the output has one line for "{automation_id}" showing monitor, the procedure, enabled and the last run status')
def list_line(context, automation_id):
    fields = context.cli_output.strip().split("\t")
    assert fields[:5] == ["automations", automation_id, "monitor", fx.PROCEDURE, "enabled"] and len(fields) == 6, fields


@then("the output says the router starts nothing for a disabled automation")
def output_enabled(context):
    assert "the router starts nothing for a disabled automation" in context.cli_output


@then("the output says the limits are enforced when a run starts")
def output_limits(context):
    assert "enforced when a run starts" in context.cli_output


@then('the output lists the run for "{source_id}" with its run id and story')
def output_run(context, source_id):
    line = next(line for line in context.cli_output.splitlines() if source_id in line)
    assert "run-1" in line and "story-lineage-1" in line


@then("the output reports {count:d} items not started because the Reference already existed")
def output_skipped(context, count):
    assert f"{count} item(s) not started because the Reference already existed" in context.cli_output


@then("the output says the cost is unknown for runs without a recorded cost")
def output_cost(context):
    assert "cost unknown" in context.cli_output


@then("the command is refused because it needs the monitoring table")
def refused_needs_table(context):
    assert context.cli_error and "needs the monitoring table" in context.cli_error


@then("the output says it was a dry run")
def output_dry(context):
    assert "dry run, nothing written" in context.cli_output


@then('the automation "{automation_id}" is disabled with a budget of {dollars:d} dollars per run')
def updated(context, automation_id, dollars):
    stored = au.read_record(context.client.tables["Automation"][automation_id])
    assert stored["enabled"] is False and stored["limits"]["budgetUsdPerRun"] == dollars


@then("its trigger and input template are unchanged")
def unchanged(context):
    stored = au.read_record(context.client.tables["Automation"]["distinctive.ttab"])
    assert stored["trigger"]["config"] == {"monitorId": "ttab", "publicationId": "distinctive"} and stored["inputTemplate"] == fx.TEMPLATE
