"""Automation records (PPY-9ff95b step 1): the record rules, the router link, the joined run history, the Lambda boundary and the CLI."""
import json

import pytest

import automation_fixture as fx
from fake_client import FakeAuthoringClient
from papyrus_content import automation_view, automations as au
from papyrus_content.automations import AutomationError, MonitoringReader

MONITOR = {"kind": "monitor", "config": {"monitorId": "ttab", "publicationId": "distinctive"}}
FIELDS = {"id": "distinctive.ttab", "title": "Analyze new TTAB rulings", "trigger": MONITOR, "procedureKey": fx.PROCEDURE,
          "inputTemplate": fx.TEMPLATE}


def reader(table=None):
    return MonitoringReader(table or fx.FakeMonitoringTable())


def record(**changes):
    return au.read_record(fx.automation_row(**changes))


# --- the record rules ------------------------------------------------------------------------------------


def test_a_monitor_automation_is_valid_and_defaults_are_filled_in():
    built = au.build_record(FIELDS, actor="a", now="2026-10-23T00:00:00Z")
    assert built["enabled"] is True and built["limits"] == {"timeoutSeconds": 840, "maxConcurrent": 1}
    assert built["trigger"] == MONITOR and built["createdBy"] == "a" and built["updatedAt"] == "2026-10-23T00:00:00Z"


@pytest.mark.parametrize("kind", ["schedule", "event", "manual"])
def test_the_other_kinds_are_stored_and_marked_not_yet_supported(kind):
    built = au.build_record({**FIELDS, "trigger": {"kind": kind, "config": {"anything": 1}}, "inputTemplate": {"x": "{whatever}"}}, actor="a")
    shown = au.read_record(au.stored_payload(built))
    assert shown["supported"] is False and shown["supportNote"] == "not yet supported"
    assert au.router_link(shown, None)["state"] == "not_applicable"


@pytest.mark.parametrize("change, message", [
    ({"id": "Bad Id"}, "id must be"),
    ({"title": " "}, "title is required"),
    ({"procedureKey": "Not A Key"}, "procedureKey must be"),
    ({"trigger": {"kind": "cron", "config": {}}}, "trigger kind must be one of"),
    ({"trigger": {"kind": "monitor", "config": {"publicationId": "distinctive"}}}, "config.monitorId"),
    ({"trigger": {"kind": "monitor", "config": {"monitorId": "ttab"}}}, "config.publicationId"),
    ({"trigger": "monitor"}, "trigger must be an object"),
    ({"inputTemplate": {"proceeding": "{nope}"}}, "unknown placeholder"),
    ({"inputTemplate": {"Bad-Name": "x"}}, "valid procedure input name"),
    ({"inputTemplate": ["x"]}, "inputTemplate must be an object"),
    ({"limits": {"timeoutSeconds": 0}}, "limits.timeoutSeconds"),
    ({"limits": {"timeoutSeconds": 9999}}, "limits.timeoutSeconds"),
    ({"limits": {"maxConcurrent": "many"}}, "limits.maxConcurrent"),
    ({"limits": {"budgetUsdPerRun": -1}}, "budgetUsdPerRun"),
    ({"limits": {"surprise": 1}}, "unknown limit"),
    ({"enabled": "maybe"}, "enabled must be true or false"),
])
def test_invalid_records_are_refused_with_a_reason(change, message):
    with pytest.raises(AutomationError, match=message):
        au.build_record({**FIELDS, **change}, actor="a")


def test_the_input_placeholders_are_the_routers_own():
    from papyrus_content.monitoring_router import TRIGGER_PLACEHOLDERS
    template = {f"p{i}": "{" + name + "}" for i, name in enumerate(sorted(TRIGGER_PLACEHOLDERS))}
    assert au.build_record({**FIELDS, "inputTemplate": template}, actor="a")["inputTemplate"] == template


def test_create_stores_json_fields_as_strings_and_refuses_a_duplicate():
    client = FakeAuthoringClient({})
    created = au.create_automation(client, FIELDS, actor="a", now="2026-10-23T00:00:00Z")
    stored = client.tables["Automation"]["distinctive.ttab"]
    assert isinstance(stored["trigger"], str) and json.loads(stored["trigger"]) == MONITOR
    assert json.loads(stored["inputTemplate"]) == fx.TEMPLATE and json.loads(stored["limits"])["maxConcurrent"] == 1
    assert created["trigger"] == MONITOR and created["enabled"] is True
    with pytest.raises(AutomationError, match="already exists"):
        au.create_automation(client, FIELDS, actor="a")
    assert [c for c in client.write_calls()] == [("create", "Automation", "distinctive.ttab")]


def test_update_changes_only_what_is_set_and_keeps_creation():
    client = FakeAuthoringClient({"Automation": [fx.automation_row()]})
    updated = au.update_automation(client, "distinctive.ttab", {"enabled": "false", "limits": {"budgetUsdPerRun": 2.5}},
                                   actor="b", now="2026-10-24T00:00:00Z")
    assert updated["enabled"] is False and updated["title"] == "Analyze new TTAB rulings"
    assert updated["limits"] == {"timeoutSeconds": 840, "maxConcurrent": 1, "budgetUsdPerRun": 2.5}
    assert updated["createdBy"] == "tester" and updated["createdAt"] == "2026-10-23T07:00:00Z"
    assert updated["updatedBy"] == "b" and updated["updatedAt"] == "2026-10-24T00:00:00Z"
    assert json.loads(client.tables["Automation"]["distinctive.ttab"]["inputTemplate"]) == fx.TEMPLATE


def test_update_refuses_a_missing_record_and_an_id_change():
    client = FakeAuthoringClient({"Automation": [fx.automation_row()]})
    with pytest.raises(AutomationError, match="does not exist"):
        au.update_automation(client, "nope", {"title": "x"}, actor="a")
    with pytest.raises(AutomationError, match="cannot change"):
        au.update_automation(client, "distinctive.ttab", {"id": "other"}, actor="a")
    assert client.write_calls() == []


def test_a_record_says_what_enabled_and_limits_do():
    shown = record()
    assert shown["enabledNote"] == "display only until the router honours it"
    assert shown["limitsNote"].startswith("recorded only")
    assert shown["supported"] is True and shown["supportNote"] is None


# --- the router link --------------------------------------------------------------------------------------


@pytest.mark.parametrize("router, state", [
    (fx.router_config(), "linked"),
    (fx.router_config(input_template={"proceeding": "{sourceId}"}), "input_differs"),
    (fx.router_config(procedure="other.procedure"), "trigger_not_found"),
    (fx.router_config(with_trigger=False), "trigger_not_found"),
    (fx.router_config(publication="elsewhere"), "publication_not_in_router"),
    (None, "router_not_found"),
])
def test_the_link_compares_the_record_with_the_routers_own_trigger(router, state):
    assert au.router_link(record(), router)["state"] == state


def test_the_link_reports_the_routers_mode_and_enabled_flag():
    link = au.router_link(record(), {**fx.router_config(), "enabled": False})
    assert link["routerMode"] == "live" and link["routerEnabled"] is False


# --- run history ------------------------------------------------------------------------------------------


def history(**kwargs):
    return au.automation_history(record(), reader=kwargs.pop("reader", reader()), client=kwargs.pop("client", fx.site_client()), **kwargs)


def test_history_joins_trigger_rows_with_their_procedure_runs_newest_first():
    result = history()
    assert [run["sourceId"] for run in result["runs"]] == [
        "97752246-EXA_26", "97752247-EXA_26", "97752245-EXA_26", "97752244-EXA_26", "97752248-EXA_26"]
    done = next(run for run in result["runs"] if run["sourceId"] == "97752244-EXA_26")
    assert done["status"] == "completed" and done["runId"] == "run-1" and done["durationSeconds"] == 185.0
    assert (done["storyId"], done["storyVersionId"], done["storyTitle"]) == ("story-lineage-1", "story-v2", "Board refuses registration")
    assert done["referenceId"] == "ref-97752244-EXA_26" and done["runRecord"] == "found"
    assert result["lastRun"]["sourceId"] == "97752246-EXA_26"
    assert result["link"]["state"] == "linked" and result["notice"] is None


def test_a_failed_run_carries_its_error_and_no_story():
    failed = next(run for run in history()["runs"] if run["sourceId"] == "97752245-EXA_26")
    assert failed["status"] == "failed" and failed["error"] == "the opinion could not be downloaded"
    assert failed["storyId"] is None and failed["durationSeconds"] == 55.0


def test_rows_that_never_reached_a_run_say_so():
    runs = {run["sourceId"]: run for run in history()["runs"]}
    started = runs["97752246-EXA_26"]
    assert started["status"] == "started" and started["runId"] is None and started["runRecord"] == "none"
    assert started["durationSeconds"] is None and started["storyId"] is None
    start_failed = runs["97752247-EXA_26"]
    assert start_failed["status"] == "startFailed" and start_failed["error"] == "ClientError: throttled"
    missing = runs["97752248-EXA_26"]
    assert missing["runId"] == "run-gone" and missing["runRecord"] == "missing" and missing["status"] == "completed"


def test_items_that_already_had_a_reference_are_counted_not_listed():
    result = history()
    assert result["skippedAlreadyHadReference"] == 2
    assert all(run["triggerStatus"] != "notTriggered" for run in result["runs"])


def test_cost_is_unknown_and_says_where_it_would_come_from():
    run = history()["runs"][0]
    assert run["costUsd"] is None and "does not record token use or cost" in run["costNote"]


def test_the_limit_bounds_the_history_and_rows_are_read_across_pages():
    table = fx.FakeMonitoringTable(page_size=2)
    result = history(reader=reader(table), limit=2)
    assert len(result["runs"]) == 2 and table.queries > 1
    assert result["skippedAlreadyHadReference"] == 2


def test_another_publications_rows_never_appear():
    sources = {run["sourceId"] for run in history()["runs"]}
    assert "99999999-OTH_26" not in sources


def test_history_never_returns_the_runner_request_or_endpoints():
    blob = json.dumps(history())
    for marker in fx.SECRET_MARKERS:
        assert marker not in blob


def test_a_failed_run_lookup_is_shown_on_its_row_and_the_rest_still_reads():
    class Flaky(FakeAuthoringClient):
        def get_record(self, model_name, record_id):
            if record_id == "run-1":
                raise RuntimeError("AppSync is down")
            return super().get_record(model_name, record_id)
    client = Flaky({"ProcedureRun": fx.site_client().tables["ProcedureRun"].values()})
    runs = {run["sourceId"]: run for run in history(client=client)["runs"]}
    assert runs["97752244-EXA_26"]["runRecord"] == "unavailable" and runs["97752244-EXA_26"]["status"] == "completed"
    assert runs["97752245-EXA_26"]["runRecord"] == "found"


def test_without_a_monitoring_table_the_history_is_empty_with_a_reason():
    result = au.automation_history(record(), reader=None, client=fx.site_client())
    assert result["runs"] == [] and result["notice"] == "monitoring_not_configured"


def test_an_unsupported_kind_has_no_history():
    shown = au.read_record(fx.automation_row(trigger=json.dumps({"kind": "schedule", "config": {}})))
    result = au.automation_history(shown, reader=reader(), client=fx.site_client())
    assert result["runs"] == [] and result["notice"] == "not yet supported"


def test_a_site_sees_only_its_own_publications_rows():
    own = history(site_endpoint=fx.SITE_ENDPOINT)
    assert len(own["runs"]) == 5
    other = history(site_endpoint=fx.OTHER_ENDPOINT)
    assert other["runs"] == [] and other["notice"] == "other_publication" and other["link"] is None
    unrouted = history(reader=reader(fx.FakeMonitoringTable([fx.router_config(publication="elsewhere")])), site_endpoint=fx.SITE_ENDPOINT)
    assert unrouted["runs"] == [] and unrouted["notice"] == "publication_not_routed"
    assert unrouted["link"]["state"] == "publication_not_in_router"


def test_the_reader_has_no_write_path():
    table = fx.FakeMonitoringTable()
    assert not any(hasattr(table, name) for name in ("put_item", "update_item", "delete_item", "batch_writer"))
    history(reader=reader(table))


# --- the overview -----------------------------------------------------------------------------------------


def test_the_overview_lists_automations_with_their_last_run_sorted_by_title():
    second = fx.automation_row(id="a.weekly", title="Weekly digest", trigger=json.dumps({"kind": "schedule", "config": {}}))
    overview = au.automation_overview(fx.site_client(fx.automation_row(), second), reader=reader(), now="2026-10-23T12:00:00Z")
    assert overview["state"] == "ready" and overview["asOf"] == "2026-10-23T12:00:00Z" and overview["monitoring"] == "ready"
    assert [a["title"] for a in overview["automations"]] == ["Analyze new TTAB rulings", "Weekly digest"]
    assert overview["automations"][0]["lastRun"]["status"] == "started"
    assert overview["automations"][1]["supported"] is False and overview["automations"][1]["runs"] == []


def test_the_overview_can_select_one_automation_and_can_be_empty():
    client = fx.site_client(fx.automation_row(), fx.automation_row(id="other", title="Other"))
    assert [a["id"] for a in au.automation_overview(client, reader=reader(), automation_id="other")["automations"]] == ["other"]
    assert au.automation_overview(FakeAuthoringClient({}), reader=reader())["state"] == "empty"


def test_records_still_list_when_the_monitoring_table_cannot_be_read():
    class Broken:
        def get_item(self, **_):
            raise RuntimeError("AccessDenied")
    overview = au.automation_overview(fx.site_client(), reader=MonitoringReader(Broken()))
    only = overview["automations"][0]
    assert only["title"] == "Analyze new TTAB rulings" and only["runs"] == [] and only["notice"] == "monitoring_unavailable"


# --- the Lambda boundary ----------------------------------------------------------------------------------


def handle(groups=("editor",), arguments=None, reader_factory=None, client_factory=None):
    return automation_view.handle(
        {"identity": {"groups": list(groups)}, "arguments": arguments or {}},
        env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.SITE_ENDPOINT}, reader_factory=reader_factory or (lambda: reader()),
        client_factory=client_factory or (lambda: fx.site_client()), now=1_792_756_800.0)


@pytest.mark.parametrize("groups", [("reader",), (), ("guest", "viewer")])
def test_only_editors_and_admins_may_read(groups):
    assert handle(groups) == {"error": "forbidden"}


@pytest.mark.parametrize("group", ["editor", "admin"])
def test_editors_and_admins_read_the_overview_scoped_to_their_site(group):
    result = handle((group,))
    assert result["state"] == "ready" and len(result["automations"][0]["runs"]) == 5
    assert result["asOf"].endswith("Z")


def test_a_site_that_is_not_the_routers_publication_sees_no_runs():
    result = automation_view.handle({"identity": {"groups": ["editor"]}, "arguments": {}},
                                    env={"PAPYRUS_GRAPHQL_ENDPOINT": fx.OTHER_ENDPOINT}, reader_factory=lambda: reader(),
                                    client_factory=lambda: fx.site_client())
    assert result["automations"][0]["runs"] == [] and result["automations"][0]["notice"] == "other_publication"


def test_a_bad_argument_is_refused_and_a_failure_is_a_state_not_a_trace():
    assert handle(arguments={"automationId": 7}) == {"error": "bad_request"}

    def boom():
        raise RuntimeError("secret detail")
    assert handle(client_factory=boom) == {"state": "unavailable"}


def test_without_a_monitoring_table_the_records_still_list():
    result = handle(reader_factory=lambda: None)
    assert result["monitoring"] == "not_configured" and result["automations"][0]["notice"] == "monitoring_not_configured"

    def broken():
        raise RuntimeError("no parameter")
    assert handle(reader_factory=broken)["monitoring"] == "not_configured"


# --- the command line -------------------------------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch, capsys):
    state = {"client": fx.site_client(), "reader": reader()}
    import papyrus_content.graphql_authoring as ga
    monkeypatch.setattr(ga, "create_authoring_client", lambda *a, **k: (state["client"], {}))
    monkeypatch.setattr(au, "monitoring_reader_from_environment", lambda env=None: state["reader"])

    def run(command, *flags):
        capsys.readouterr()
        au.run_command(command, list(flags))
        return capsys.readouterr().out
    run.state = state
    return run


def test_list_shows_one_line_per_automation(cli):
    out = cli("list")
    assert out.strip().split("\t") == ["automations", "distinctive.ttab", "monitor", fx.PROCEDURE, "enabled", "started"]


def test_show_prints_the_record_the_link_and_the_enabled_caveat(cli):
    out = cli("show", "--id", "distinctive.ttab")
    assert "display only until the router honours it" in out and "linked" in out and "recorded only" in out


def test_runs_prints_the_history_and_the_cost_note(cli):
    out = cli("runs", "--id", "distinctive.ttab")
    assert "97752244-EXA_26" in out and "story-lineage-1" in out and "run-1" in out
    assert "2 item(s) not started because the Reference already existed" in out and "does not record token use or cost" in out


def test_runs_as_json_has_the_joined_fields(cli):
    data = json.loads(cli("runs", "--id", "distinctive.ttab", "--json", "--limit", "2"))
    assert data["ok"] is True and len(data["automations"][0]["runs"]) == 2


def test_runs_needs_an_id_and_the_monitoring_table(cli):
    with pytest.raises(AutomationError, match="needs --id"):
        cli("runs")
    cli.state["reader"] = None
    with pytest.raises(AutomationError, match="needs the monitoring table"):
        cli("runs", "--id", "distinctive.ttab")
    assert "monitoring_not_configured" not in cli("list")   # records still list without it


def test_show_of_a_missing_automation_says_so(cli):
    with pytest.raises(AutomationError, match="does not exist"):
        cli("show", "--id", "nope")


def test_create_writes_the_record_and_dry_run_writes_nothing(cli):
    flags = ("--id", "new.one", "--title", "New one", "--monitor", "ttab", "--publication", "distinctive",
             "--procedure", fx.PROCEDURE, "--input", json.dumps(fx.TEMPLATE))
    assert "(dry run, nothing written)" in cli("create", *flags, "--dry-run")
    assert "new.one" not in cli.state["client"].tables["Automation"]
    out = cli("create", *flags)
    assert "created" in out
    stored = au.read_record(cli.state["client"].tables["Automation"]["new.one"])
    assert stored["trigger"] == MONITOR and stored["enabled"] is True and stored["inputTemplate"] == fx.TEMPLATE


def test_create_refuses_an_invalid_input_template(cli):
    with pytest.raises(AutomationError, match="unknown placeholder"):
        cli("create", "--id", "x", "--title", "X", "--monitor", "ttab", "--publication", "distinctive", "--procedure", fx.PROCEDURE,
            "--input", '{"a": "{nonsense}"}')
    with pytest.raises(AutomationError, match="must be JSON"):
        cli("create", "--id", "x", "--title", "X", "--monitor", "ttab", "--publication", "distinctive", "--procedure", fx.PROCEDURE,
            "--input", "not json")


def test_update_sets_enabled_and_limits_and_keeps_the_rest(cli):
    cli("update", "--id", "distinctive.ttab", "--enabled", "false", "--budget-usd", "3", "--timeout-seconds", "600")
    stored = au.read_record(cli.state["client"].tables["Automation"]["distinctive.ttab"])
    assert stored["enabled"] is False and stored["limits"] == {"timeoutSeconds": 600, "maxConcurrent": 1, "budgetUsdPerRun": 3.0}
    assert stored["trigger"] == MONITOR and stored["inputTemplate"] == fx.TEMPLATE


def test_update_can_repoint_the_monitor_and_dry_run_writes_nothing(cli):
    before = dict(cli.state["client"].tables["Automation"]["distinctive.ttab"])
    cli("update", "--id", "distinctive.ttab", "--monitor", "hn", "--dry-run")
    assert cli.state["client"].tables["Automation"]["distinctive.ttab"] == before
    cli("update", "--id", "distinctive.ttab", "--monitor", "hn")
    assert au.read_record(cli.state["client"].tables["Automation"]["distinctive.ttab"])["trigger"]["config"] == {
        "monitorId": "hn", "publicationId": "distinctive"}


def test_the_command_is_registered_under_the_papyrus_cli():
    from papyrus_content import cli as content_cli
    for command in ("list", "show", "runs", "create", "update"):
        assert content_cli.is_ported_command("automations", command)
