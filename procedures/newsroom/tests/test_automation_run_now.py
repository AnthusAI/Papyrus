"""Automations step 2 (PPY-112007): Run now from the library, the console's Lambda and the command line, and the operator read."""
import json

import pytest

import automation_fixture as fx
from papyrus_content import automation_view, automations as au
from papyrus_content.automations import AutomationError, MonitoringReader, MonitoringWriter

NOW = "2026-10-24T09:00:00.000000Z"
INPUT = {"proceeding": "97752299", "opinion_url": "https://example.test/a.pdf"}


class WritableTable(fx.FakeMonitoringTable):
    """The fake monitoring table with the one write Run now makes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.puts = []

    def put_item(self, Item):
        self.puts.append(dict(Item))
        self.rows[(Item["pk"], Item["sk"])] = dict(Item)


def automation(**changes):
    return au.read_record(fx.automation_row(**changes))


def start(table=None, record=None, invoked=None, **kwargs):
    table = table if table is not None else WritableTable()
    invoked = invoked if invoked is not None else []
    kwargs.setdefault("supplied_input", INPUT)
    return au.run_now(record or automation(), reader=MonitoringReader(table), writer=MonitoringWriter(table),
                      invoke=invoked.append, actor="ryan@example.test", now=NOW, **kwargs), table, invoked


# --- Run now ----------------------------------------------------------------------------------------------


def test_run_now_writes_a_linking_row_then_starts_the_runner_with_the_automations_limits():
    result, table, invoked = start()
    key = f"MANUAL#distinctive.ttab#{NOW}"
    assert result["started"] is True and result["key"] == key and result["timeoutSeconds"] == 840
    (row,) = table.puts
    assert (row["pk"], row["sk"]) == ("MONITOR#ttab", key) and row["status"] == "starting"
    assert row["automationId"] == "distinctive.ttab" and row["requestedBy"] == "ryan@example.test" and row["procedureKey"] == fx.PROCEDURE
    (request,) = invoked
    assert request["procedureKey"] == fx.PROCEDURE and request["input"] == INPUT and request["timeoutSeconds"] == 840
    assert request["appsyncEndpoint"] == fx.SITE_ENDPOINT and request["openaiKeyParameter"].endswith("OPENAI_API_KEY")
    assert request["actorLabel"] == "ryan@example.test (run now)"
    assert request["trigger"] == {"kind": "manual", "automationId": "distinctive.ttab", "monitorId": "ttab", "pk": "MONITOR#ttab", "sk": key,
                                  "title": f"{fx.PROCEDURE}: run now by ryan@example.test",
                                  "summary": "Started by ryan@example.test with Run now on automation distinctive.ttab"}


def test_the_row_run_now_writes_is_the_one_the_history_joins():
    _, table, _ = start()
    table.rows[("MONITOR#ttab", f"MANUAL#distinctive.ttab#{NOW}")].update(runId="run-1", status="running")
    history = au.automation_history(automation(), reader=MonitoringReader(table), client=fx.site_client())
    manual = next(run for run in history["runs"] if run["origin"] == "manual")
    assert manual["requestedBy"] == "ryan@example.test" and manual["runId"] == "run-1" and manual["storyId"] == "story-lineage-1"
    assert '"request"' not in json.dumps(history) and not any(marker in json.dumps(history) for marker in fx.SECRET_MARKERS)   # the stored request is never returned


def test_the_timeout_in_the_record_goes_with_the_request_and_is_capped():
    short = automation(limits=json.dumps({"timeoutSeconds": 120, "maxConcurrent": 1}))
    assert start(record=short)[0]["timeoutSeconds"] == 120
    long = automation(limits=json.dumps({"timeoutSeconds": 5000, "maxConcurrent": 1}))
    assert start(record=long)[0]["timeoutSeconds"] == 840


def test_dry_run_checks_everything_and_writes_and_starts_nothing():
    result, table, invoked = start(dry_run=True)
    assert result["started"] is False and result["dryRun"] is True and result["input"] == INPUT
    assert table.puts == [] and invoked == []


@pytest.mark.parametrize("changes, message", [
    ({"enabled": False}, "is disabled"),
    ({"trigger": json.dumps({"kind": "schedule", "config": {}})}, "only monitor automations"),
])
def test_run_now_is_refused_for_a_disabled_or_unsupported_automation(changes, message):
    table, invoked = WritableTable(), []
    with pytest.raises(AutomationError, match=message):
        start(table=table, invoked=invoked, record=automation(**changes))
    assert table.puts == [] and invoked == []


def test_run_now_is_refused_at_maxconcurrent_with_the_reason_and_writes_nothing():
    busy = WritableTable(fx.rows() + [fx.manual_row(stamp="2026-10-24T08:59:00.000000Z", status="running")])
    invoked = []
    with pytest.raises(AutomationError, match="1 running, at most 1 at a time"):
        start(table=busy, invoked=invoked)
    assert busy.puts == [] and invoked == []


def test_a_trigger_row_in_flight_also_counts_against_the_limit():
    busy = WritableTable(fx.rows() + [fx.trigger_row("97752260-EXA_26", "starting", started="2026-10-24T08:58:00Z")])
    with pytest.raises(AutomationError, match="at most 1 at a time"):
        start(table=busy)


def test_a_run_whose_outcome_was_never_recorded_stops_counting_after_its_timeout_and_grace():
    stale = WritableTable(fx.rows() + [fx.trigger_row("97752261-EXA_26", "started", started="2026-10-24T08:00:00Z")])   # an hour ago
    result, _, _ = start(table=stale)
    assert result["started"] is True


def test_a_higher_limit_allows_another_run_beside_the_one_in_flight():
    busy = WritableTable(fx.rows() + [fx.manual_row(stamp="2026-10-24T08:59:00.000000Z", status="running")])
    two = automation(limits=json.dumps({"timeoutSeconds": 840, "maxConcurrent": 2}))
    assert start(table=busy, record=two)[0]["started"] is True


def test_the_router_must_deliver_to_this_sites_publication():
    for config, message in ((fx.router_config(publication="elsewhere"), "does not deliver to this automation's publication"),
                            (None, "does not deliver")):
        table = WritableTable([config] if config else [])
        with pytest.raises(AutomationError, match=message):
            start(table=table)
    with pytest.raises(AutomationError, match="belongs to another site"):
        start(site_endpoint=fx.OTHER_ENDPOINT)
    assert start(site_endpoint=fx.SITE_ENDPOINT)[0]["started"] is True


def test_the_router_publication_needs_a_key_parameter_and_the_monitoring_table_must_be_connected():
    config = fx.router_config()
    config["publications"][0]["openaiKeyParameter"] = ""
    with pytest.raises(AutomationError, match="openaiKeyParameter"):
        start(table=WritableTable([config]))
    with pytest.raises(AutomationError, match="needs the monitoring table"):
        au.run_now(automation(), reader=None, writer=None, invoke=lambda r: None, actor="a", supplied_input=INPUT)


def test_a_runner_that_cannot_be_started_is_recorded_and_reported():
    table = WritableTable()

    def unavailable(request):
        raise RuntimeError("AccessDenied: arn:aws:lambda:secret")
    with pytest.raises(AutomationError, match=r"could not be started \(RuntimeError\)") as raised:
        au.run_now(automation(), reader=MonitoringReader(table), writer=MonitoringWriter(table), invoke=unavailable,
                   actor="a", supplied_input=INPUT, now=NOW)
    assert "secret" not in str(raised.value)
    assert [row["status"] for row in table.puts] == ["starting", "startFailed"] and table.puts[-1]["error"] == "RuntimeError"


# --- the input of a manual run -----------------------------------------------------------------------------


def test_a_template_with_item_placeholders_needs_the_input_for_this_run():
    with pytest.raises(AutomationError, match="give the input for this run"):
        start(supplied_input=None)


def test_a_template_without_placeholders_is_the_default_input():
    literal = automation(inputTemplate=json.dumps({"corpus": "knowledge-corpus-example"}))
    result, _, invoked = start(record=literal, supplied_input=None)
    assert result["input"] == {"corpus": "knowledge-corpus-example"} and invoked[0]["input"] == {"corpus": "knowledge-corpus-example"}


@pytest.mark.parametrize("bad, message", [(["x"], "JSON object"), ("text", "JSON object"), ({"Bad-Name": 1}, "valid procedure input name")])
def test_a_bad_input_is_refused_before_anything_is_written(bad, message):
    table = WritableTable()
    with pytest.raises(AutomationError, match=message):
        start(table=table, supplied_input=bad)
    assert table.puts == []


# --- the console's Lambda ----------------------------------------------------------------------------------

ACCOUNT = "712236451410"
ENV = {"PAPYRUS_GRAPHQL_ENDPOINT": fx.SITE_ENDPOINT}


def lambda_event(field, *, groups=("editor",), arguments=None, identity=None):
    return {"info": {"fieldName": field}, "identity": identity or {"groups": list(groups), "claims": {"email": "ed@example.test"}},
            "arguments": arguments or {}}


def call(field, **kwargs):
    table, invoked = kwargs.pop("table", None) or WritableTable(), kwargs.pop("invoked", [])
    result = automation_view.handle(lambda_event(field, **kwargs), env=ENV, client_factory=lambda: fx.site_client(),
                                    reader_factory=lambda: MonitoringReader(table), table_factory=lambda: table,
                                    invoker=invoked.append, now=1_792_832_400.0, account_id=ACCOUNT)
    return result, table, invoked


@pytest.mark.parametrize("group", ["editor", "admin"])
def test_editors_and_admins_run_an_automation_from_the_console(group):
    result, table, invoked = call("runAutomation", groups=(group,), arguments={"automationId": "distinctive.ttab", "input": json.dumps(INPUT)})
    assert result["state"] == "started" and result["requestedBy"] == "ed@example.test"
    assert invoked[0]["input"] == INPUT and invoked[0]["actorLabel"] == "ed@example.test (run now)"
    assert len(table.puts) == 1 and table.puts[0]["requestedBy"] == "ed@example.test"


@pytest.mark.parametrize("groups", [("reader",), ()])
def test_others_cannot_run_an_automation(groups):
    result, table, invoked = call("runAutomation", groups=groups, arguments={"automationId": "distinctive.ttab", "input": json.dumps(INPUT)})
    assert result == {"error": "forbidden"} and table.puts == [] and invoked == []


def test_an_operator_iam_role_cannot_run_an_automation():
    operator = {"accountId": ACCOUNT, "userArn": f"arn:aws:sts::{ACCOUNT}:assumed-role/operator/ryan"}
    result, table, invoked = call("runAutomation", identity=operator, arguments={"automationId": "distinctive.ttab", "input": json.dumps(INPUT)})
    assert result == {"error": "forbidden"} and table.puts == [] and invoked == []


def test_the_console_reports_a_refusal_in_words_and_a_failure_as_a_state():
    refused, table, invoked = call("runAutomation", arguments={"automationId": "distinctive.ttab"})
    assert refused["state"] == "refused" and "give the input for this run" in refused["reason"] and table.puts == []
    missing, *_ = call("runAutomation", arguments={"automationId": "nope", "input": "{}"})
    assert missing == {"state": "refused", "reason": "automation nope does not exist."}
    malformed, *_ = call("runAutomation", arguments={"automationId": "distinctive.ttab", "input": "{not json"})
    assert malformed == {"state": "refused", "reason": "the input must be a JSON object."}
    assert call("runAutomation", arguments={})[0] == {"error": "bad_request"}

    def boom():
        raise RuntimeError("secret detail")
    broken = automation_view.handle(lambda_event("runAutomation", arguments={"automationId": "distinctive.ttab", "input": json.dumps(INPUT)}),
                                    env=ENV, client_factory=boom)
    assert broken == {"state": "unavailable"}


def test_run_now_from_a_site_that_is_not_the_routers_publication_is_refused():
    table = WritableTable()
    result = automation_view.handle(lambda_event("runAutomation", arguments={"automationId": "distinctive.ttab", "input": json.dumps(INPUT)}),
                                    env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.OTHER_ENDPOINT}, client_factory=lambda: fx.site_client(),
                                    table_factory=lambda: table, invoker=lambda request: None)
    assert result["state"] == "refused" and "another site" in result["reason"] and table.puts == []


# --- the operator read -------------------------------------------------------------------------------------


def operator(**changes):
    return {"accountId": ACCOUNT, "userArn": f"arn:aws:sts::{ACCOUNT}:assumed-role/operator/ryan", "username": "AROA:ryan", **changes}


def test_an_operators_iam_role_in_this_account_reads_the_overview():
    result, *_ = call("automationOverview", identity=operator())
    assert result["state"] == "ready" and len(result["automations"][0]["runs"]) == 5


@pytest.mark.parametrize("identity", [
    operator(accountId="999999999999"),                       # a role in another account
    operator(cognitoIdentityId="us-east-1:abc"),              # a Cognito identity-pool user, signed in or not
    operator(sub="user-sub"),
    {"accountId": ACCOUNT},                                   # no principal ARN
    {"sourceIp": ["1.2.3.4"]},
    None,
])
def test_no_other_caller_reads_the_overview(identity):
    event = lambda_event("automationOverview", identity=identity or {})
    event["identity"] = identity
    assert automation_view.handle(event, env=ENV, client_factory=lambda: fx.site_client(), reader_factory=lambda: MonitoringReader(WritableTable()),
                                  account_id=ACCOUNT) == {"error": "forbidden"}


def test_the_operator_read_fails_closed_when_the_functions_own_account_is_unknown():
    event = lambda_event("automationOverview", identity=operator())
    assert automation_view.handle(event, env=ENV, client_factory=lambda: fx.site_client(), account_id=None) == {"error": "forbidden"}


def test_the_lambda_entry_point_passes_its_own_account():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "amplify/functions/automation-view/handler.py"
    spec = importlib.util.spec_from_file_location("automation_view_handler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Context:
        invoked_function_arn = f"arn:aws:lambda:us-east-1:{ACCOUNT}:function:papyrus-automation-view"
    assert module._account(Context()) == ACCOUNT and module._account(None) is None


# --- the command line --------------------------------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch, capsys):
    state = {"client": fx.site_client(), "table": WritableTable(), "invoked": []}
    import papyrus_content.graphql_authoring as ga
    monkeypatch.setattr(ga, "create_authoring_client", lambda *a, **k: (state["client"], {}))
    monkeypatch.setattr(au, "monitoring_table_from_environment", lambda env=None: state["table"])
    monkeypatch.setattr(au, "lambda_invoker", lambda name=None: state["invoked"].append)
    monkeypatch.setenv("PAPYRUS_ACTOR_LABEL", "ryan-cli")
    monkeypatch.setattr(au, "_now", lambda: NOW)

    def run(*flags):
        capsys.readouterr()
        au.run_command("run", list(flags))
        return capsys.readouterr().out
    run.state = state
    return run


def test_the_command_runs_the_automation_with_the_given_input(cli):
    out = cli("--id", "distinctive.ttab", "--input", json.dumps(INPUT))
    assert "started" in out and "distinctive.ttab" in out
    assert cli.state["invoked"][0]["input"] == INPUT and cli.state["invoked"][0]["actorLabel"] == "ryan-cli (run now)"
    assert cli.state["table"].puts[0]["requestedBy"] == "ryan-cli"


def test_the_command_dry_run_starts_nothing(cli):
    out = cli("--id", "distinctive.ttab", "--input", json.dumps(INPUT), "--dry-run")
    assert "dry run, nothing started" in out and cli.state["invoked"] == [] and cli.state["table"].puts == []


def test_the_command_as_json(cli):
    data = json.loads(cli("--id", "distinctive.ttab", "--input", json.dumps(INPUT), "--json"))
    assert data["ok"] is True and data["started"] is True and data["timeoutSeconds"] == 840


def test_the_command_refuses_without_an_id_for_a_missing_automation_and_for_bad_json(cli):
    with pytest.raises(AutomationError, match="needs --id"):
        cli()
    with pytest.raises(AutomationError, match="does not exist"):
        cli("--id", "nope")
    with pytest.raises(AutomationError, match="must be JSON"):
        cli("--id", "distinctive.ttab", "--input", "{nope")
    with pytest.raises(AutomationError, match="give the input for this run"):
        cli("--id", "distinctive.ttab")
    assert cli.state["invoked"] == []


def test_the_command_without_the_monitoring_table_says_so(cli):
    cli.state["table"] = None
    with pytest.raises(AutomationError, match="needs the monitoring table"):
        cli("--id", "distinctive.ttab", "--input", json.dumps(INPUT))
