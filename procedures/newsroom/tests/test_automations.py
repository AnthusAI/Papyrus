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
    assert built["enabled"] is True and built["limits"] == {"timeoutSeconds": 840}   # no maxConcurrent: no limit, as before
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
    assert json.loads(stored["inputTemplate"]) == fx.TEMPLATE and json.loads(stored["limits"]) == {"timeoutSeconds": 840}
    assert created["trigger"] == MONITOR and created["enabled"] is True
    with pytest.raises(AutomationError, match="already exists"):
        au.create_automation(client, FIELDS, actor="a")
    assert [c for c in client.write_calls()] == [("create", "Automation", "distinctive.ttab")]


def test_update_changes_only_what_is_set_and_keeps_creation():
    client = FakeAuthoringClient({"Automation": [fx.automation_row()]})
    updated = au.update_automation(client, "distinctive.ttab", {"enabled": "false", "limits": {"budgetUsdPerRun": 2.5}},
                                   actor="b", now="2026-10-24T00:00:00Z")
    assert updated["enabled"] is False and updated["title"] == "Analyze new TTAB rulings"
    assert updated["limits"] == {"timeoutSeconds": 840, "budgetUsdPerRun": 2.5}
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
    assert shown["enabledNote"] == "the router starts nothing for a disabled automation"
    assert "enforced when a run starts" in shown["limitsNote"] and "budget is advisory" in shown["limitsNote"]
    assert shown["supported"] is True and shown["supportNote"] is None


def test_run_now_is_offered_only_for_an_enabled_monitor_automation_and_says_when_input_is_needed():
    assert record()["runNow"] == {"available": True, "reason": None, "needsInput": True, "inputNames": ["opinion_url", "proceeding"]}
    literal = au.read_record(fx.automation_row(inputTemplate=json.dumps({"corpus": "knowledge-corpus-example"})))
    assert literal["runNow"]["needsInput"] is False
    assert au.read_record(fx.automation_row(enabled=False))["runNow"]["reason"] == "disabled"
    schedule = au.read_record(fx.automation_row(trigger=json.dumps({"kind": "schedule", "config": {}})))
    assert schedule["runNow"] == {"available": False, "reason": "not yet supported", "needsInput": False, "inputNames": []}


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


def test_a_run_without_a_recorded_cost_says_so():
    run = next(run for run in history()["runs"] if run["sourceId"] == "97752244-EXA_26")
    assert run["costUsd"] is None and run["costNote"] == "not recorded for this run" and run["usage"] is None
    assert run["overBudget"] is False
    assert history()["runs"][0]["costNote"] == "no run record, so no cost"   # started, with no run record yet


def costed_client(cost, usage, *, run_id="run-1"):
    client = fx.site_client()
    client.tables["ProcedureRun"][run_id].update(costUsd=cost, usage=json.dumps(usage) if usage is not None else None)
    return client


def test_the_recorded_cost_and_usage_are_shown_with_the_run():
    run = next(run for run in history(client=costed_client(0.0123, fx.usage_summary()))["runs"] if run["runId"] == "run-1")
    assert run["costUsd"] == 0.0123 and run["costNote"] == "estimated from the model usage reported by the run"
    assert run["usage"] == {"calls": 3, "promptTokens": 50000, "completionTokens": 4000, "models": {"gpt-6-luna": 3},
                            "complete": True, "unpricedModels": []}
    assert run["overBudget"] is False and run["budgetUsd"] is None


def test_a_partly_priced_run_says_which_model_has_no_price():
    run = next(run for run in history(client=costed_client(0.01, fx.usage_summary(complete=False, unpricedModels=["mystery"])))["runs"]
               if run["runId"] == "run-1")
    assert run["costUsd"] == 0.01 and "partly" in run["costNote"] and "mystery" in run["costNote"]


def test_usage_with_no_priced_model_has_no_cost_and_says_why():
    run = next(run for run in history(client=costed_client(None, fx.usage_summary(complete=False, unpricedModels=["mystery"])))["runs"]
               if run["runId"] == "run-1")
    assert run["costUsd"] is None and "no model in it has a price: mystery" in run["costNote"]


def test_the_advisory_budget_is_compared_with_the_recorded_cost_and_flagged():
    shown = au.read_record(fx.automation_row(limits=json.dumps({"timeoutSeconds": 840, "maxConcurrent": 1, "budgetUsdPerRun": 0.05})))
    result = au.automation_history(shown, reader=reader(), client=costed_client(0.08, fx.usage_summary()))
    over = next(run for run in result["runs"] if run["runId"] == "run-1")
    assert over["overBudget"] is True and over["budgetUsd"] == 0.05
    within = au.automation_history(shown, reader=reader(), client=costed_client(0.05, fx.usage_summary()))
    assert next(run for run in within["runs"] if run["runId"] == "run-1")["overBudget"] is False   # at the budget is not over it
    assert next(run for run in result["runs"] if run["runId"] == "run-2")["overBudget"] is False   # no cost, nothing to flag


def test_a_backend_without_the_cost_fields_still_reads_the_run():
    class OldBackend(FakeAuthoringClient):
        def get_record_with_fields(self, *_):
            raise RuntimeError("Validation error: Field 'usage' in type 'ProcedureRun' is undefined")
    client = OldBackend({"ProcedureRun": fx.site_client().tables["ProcedureRun"].values()})
    run = next(run for run in history(client=client)["runs"] if run["runId"] == "run-1")
    assert run["runRecord"] == "found" and run["status"] == "completed" and run["costUsd"] is None


def test_the_procedures_other_runs_are_listed_apart_under_started_outside():
    result = history()
    assert [run["runId"] for run in result["outsideRuns"]] == ["run-outside"]   # run-1 and run-2 belong to trigger rows
    outside = result["outsideRuns"][0]
    assert outside["requestedBy"] == "papyrus-cli" and outside["status"] == "completed" and outside["durationSeconds"] == 120.0
    assert "run-outside" not in [run["runId"] for run in result["runs"]]


def test_outside_runs_exclude_every_run_a_row_links_even_beyond_the_listed_limit():
    result = history(limit=1)
    assert len(result["runs"]) == 1
    assert [run["runId"] for run in result["outsideRuns"]] == ["run-outside"]


def test_outside_runs_that_cannot_be_read_do_not_break_the_history():
    class Broken(FakeAuthoringClient):
        def recent_procedure_runs(self, *_):
            raise RuntimeError("AccessDenied")
    client = Broken({"ProcedureRun": fx.site_client().tables["ProcedureRun"].values()})
    result = history(client=client)
    assert result["outsideRuns"] == [] and result["outsideNotice"] == "outside_unavailable" and len(result["runs"]) == 5


def test_a_skipped_and_a_refused_start_are_listed_with_their_reason():
    skipped = fx.trigger_row("97752250-EXA_26", "skipped", started="2026-10-24T01:00:00Z")
    skipped.update(reason="automation disabled", automationId="distinctive.ttab")
    refused = fx.trigger_row("97752251-EXA_26", "refused", started="2026-10-24T02:00:00Z")
    refused.update(reason="automation at its limit: 1 running, at most 1 at a time")
    result = history(reader=reader(fx.FakeMonitoringTable(fx.rows() + [skipped, refused])))
    by_source = {run["sourceId"]: run for run in result["runs"]}
    assert by_source["97752250-EXA_26"]["status"] == "skipped" and by_source["97752250-EXA_26"]["reason"] == "automation disabled"
    assert by_source["97752251-EXA_26"]["status"] == "refused" and "at most 1 at a time" in by_source["97752251-EXA_26"]["reason"]
    assert by_source["97752251-EXA_26"]["error"] is None and by_source["97752251-EXA_26"]["runRecord"] == "none"
    assert result["skippedAlreadyHadReference"] == 2   # a skipped or refused start is a run to read, not "already had a Reference"


def test_a_run_now_row_joins_its_run_and_names_who_started_it():
    table = fx.FakeMonitoringTable(fx.rows() + [fx.manual_row(run_id="run-1", status="running", stamp="2026-10-24T09:00:00Z")])
    result = history(reader=reader(table))
    manual = result["runs"][0]
    assert manual["origin"] == "manual" and manual["requestedBy"] == "ryan@example.test" and manual["sourceId"] is None
    assert manual["runId"] == "run-1" and manual["runRecord"] == "found" and manual["storyId"] == "story-lineage-1"
    assert "run-1" not in [run["runId"] for run in result["outsideRuns"]]
    other = fx.manual_row(automation_id="another.automation", run_id="run-2")
    assert len(history(reader=reader(fx.FakeMonitoringTable(fx.rows() + [other])))["runs"]) == 5   # another automation's rows stay out


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
    assert [run["runId"] for run in result["automations"][0]["outsideRuns"]] == ["run-outside"]


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
    assert "the router starts nothing for a disabled automation" in out and "linked" in out and "enforced when a run starts" in out


def test_runs_prints_the_history_the_cost_and_the_runs_started_outside(cli):
    cli.state["client"].tables["ProcedureRun"]["run-1"].update(costUsd=0.0123, usage=json.dumps(fx.usage_summary()))
    out = cli("runs", "--id", "distinctive.ttab")
    assert "97752244-EXA_26" in out and "story-lineage-1" in out and "run-1" in out
    assert "2 item(s) not started because the Reference already existed" in out
    assert "$0.0123" in out and "cost unknown" in out
    assert "cost\t$0.0123 total across 1 run with a recorded cost (1 of 5 listed runs; an estimate)" in out
    assert "Started outside this automation:" in out and "outside\t2026-10-22T10:00:00Z\tcompleted" in out and "papyrus-cli" in out


def test_runs_flags_a_run_over_its_advisory_budget(cli):
    cli.state["client"].tables["Automation"]["distinctive.ttab"]["limits"] = json.dumps({"timeoutSeconds": 840, "maxConcurrent": 1, "budgetUsdPerRun": 0.01})
    cli.state["client"].tables["ProcedureRun"]["run-1"].update(costUsd=0.0123, usage=json.dumps(fx.usage_summary()))
    assert "$0.0123 OVER BUDGET" in cli("runs", "--id", "distinctive.ttab")


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


def test_max_concurrent_can_be_set_and_cleared_from_the_command_line(cli):
    cli("update", "--id", "distinctive.ttab", "--max-concurrent", "3")
    assert au.read_record(cli.state["client"].tables["Automation"]["distinctive.ttab"])["limits"]["maxConcurrent"] == 3
    cli("update", "--id", "distinctive.ttab", "--max-concurrent", "none")
    assert "maxConcurrent" not in au.read_record(cli.state["client"].tables["Automation"]["distinctive.ttab"])["limits"]
    with pytest.raises(AutomationError, match="limits.maxConcurrent"):
        cli("update", "--id", "distinctive.ttab", "--max-concurrent", "0")


def test_the_command_is_registered_under_the_papyrus_cli():
    from papyrus_content import cli as content_cli
    for command in ("list", "show", "runs", "run", "create", "update"):
        assert content_cli.is_ported_command("automations", command)


# --- stage-entry runs, tools used, deleted stories ---------------------------------------------------------

STAGE_ID = "distinctive.ruling.fact-check"
STAGE_TRIGGER = {"kind": "event", "config": {"event": "story.stage_entered", "onStage": "reporting", "nextStage": "copywriting",
                                              "monitorId": "ttab", "publicationId": "distinctive"}}


def stage_row(story, version, *, run_id=None, started="2026-10-24T09:00:00Z", status="completed"):
    return {"pk": fx.PK, "sk": f"STAGE#{STAGE_ID}#{story}#reporting#{version}", "automationId": STAGE_ID, "storyId": story,
            "stage": "reporting", "version": version, "requestedBy": f"automation:{STAGE_ID}", "createdAt": started,
            "startedAt": started, "status": status, "runId": run_id}


def stage_world(usage=None):
    client = fx.site_client(fx.automation_row(id=STAGE_ID, trigger=json.dumps(STAGE_TRIGGER)))
    client.tables["ProcedureRun"]["run-s"] = fx.procedure_run("run-s", "completed", started="2026-10-24T09:00:05Z", finished="2026-10-24T09:02:05Z",
                                                              output={"version": "v-1"}, usage=usage, cost=0.01 if usage and "calls" in usage else None)
    client.tables["Item"] = {"v-1": {"id": "v-1", "lineageId": "story-a", "versionNumber": 1}}
    table = fx.FakeMonitoringTable([fx.router_config(), stage_row("story-a", "v-1", run_id="run-s"),
                                    stage_row("story-gone", "v-9", started="2026-10-24T08:00:00Z")])
    return client, reader(table)


def stage_history(usage=None):
    client, rdr = stage_world(usage)
    row = au.read_record(client.tables["Automation"][STAGE_ID])
    return au.automation_history(row, reader=rdr, client=client)


def test_a_story_stage_automation_lists_the_runs_its_stage_entries_started():
    result = stage_history()
    assert result["notice"] is None and len(result["runs"]) == 2
    first = result["runs"][0]
    assert (first["origin"], first["stage"], first["runId"], first["storyId"], first["status"]) == ("stage", "reporting", "run-s", "story-a", "completed")
    assert first["requestedBy"] == f"automation:{STAGE_ID}"
    assert result["runs"][1]["runRecord"] == "none" and result["runs"][1]["storyId"] == "story-gone"


def test_a_run_whose_story_no_longer_exists_says_so():
    first, second = stage_history()["runs"]
    assert first["storyExists"] is True and second["storyExists"] is False


def test_the_tools_a_run_used_are_listed_by_name_and_count():
    usage = fx.usage_summary(toolsUsed={"papyrus_story_version": 1, "papyrus_fetch_pdf_text": 2})
    first = stage_history(usage)["runs"][0]
    assert first["toolsUsed"] == {"papyrus_story_version": 1, "papyrus_fetch_pdf_text": 2}
    assert first["costUsd"] == 0.01 and "toolsUsed" not in (first["usage"] or {})
    assert stage_history()["runs"][0]["toolsUsed"] is None


def test_a_run_with_tools_but_no_model_call_has_no_cost_and_still_lists_its_tools():
    first = stage_history({"toolsUsed": {"papyrus_story_version": 1}})["runs"][0]
    assert first["toolsUsed"] == {"papyrus_story_version": 1} and first["costUsd"] is None and first["usage"] is None


def test_runs_prints_stage_runs_with_tools_and_marks_deleted_stories(cli):
    client, rdr = stage_world(fx.usage_summary(toolsUsed={"papyrus_fetch_pdf_text": 2, "papyrus_story_version": 1}))
    cli.state.update(client=client, reader=rdr)
    out = cli("runs", "--id", STAGE_ID)
    assert "story entered reporting" in out and "story-a\t" in out
    assert "story-gone (story deleted)" in out and "story-a (story deleted)" not in out
    assert "tools: papyrus_fetch_pdf_text x2, papyrus_story_version x1" in out and "tools: none recorded" in out
    assert "cost\t$0.0100 total across 1 run with a recorded cost (1 of 2 listed runs; an estimate)" in out
