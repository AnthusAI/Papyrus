"""Automations step 2 (PPY-112007): the monitoring router honours the Automation record before it starts a procedure.

The rules, from papyrus_content/automation_gate.py: no record or an unreadable one starts exactly as before; a
disabled automation starts nothing and records "skipped"; maxConcurrent refuses with a recorded reason; the record's
timeout travels with the request."""
import json

import pytest

from papyrus_content import automation_gate as gate
from papyrus_content.monitoring_router import Router, RouterStore, run_router

from test_monitoring_router import Delivery
from test_monitoring_ttab import NOW
from test_procedure_runner import TRIGGER, triggered_table

PROCEDURE = TRIGGER["procedureKey"]
AUTOMATION = {"id": "distinctive.ttab", "enabled": True,
              "trigger": json.dumps({"kind": "monitor", "config": {"monitorId": "ttab", "publicationId": "distinctive"}}),
              "procedureKey": PROCEDURE, "inputTemplate": json.dumps(TRIGGER["input"]),
              "limits": json.dumps({"timeoutSeconds": 840, "maxConcurrent": 5})}


def automation(**changes):
    row = {**AUTOMATION, **changes}
    return {key: (json.dumps(value) if key in ("limits", "trigger") and isinstance(value, dict) else value) for key, value in row.items()}


class SiteClient:
    """The site's AppSync client as the router sees it: it can list Automation records, or fail to."""

    def __init__(self, rows=None, error=None):
        self.rows, self.error, self.reads = rows or [], error, 0

    def list_records(self, model):
        assert model == "Automation"
        self.reads += 1
        if self.error:
            raise self.error
        return self.rows


def sweep(table, client, *, now=NOW + 60, started=None):
    started = [] if started is None else started
    result = run_router(RouterStore(table), "ttab", now=now, cyclotron=None, deliver=Delivery(), appsync=lambda endpoint: client,
                        start_procedure=started.append, context_receipt=lambda c, p: {"contextHash": "h", "reason": None})
    return result, started


def trigger_rows(table):
    return table.by_prefix("TRIGGER#")


# --- no record, or one that cannot be read: exactly as before ---------------------------------------------------------------


def baseline():
    result, started = sweep(triggered_table(), object())   # an AppSync client with no Automation support at all: today's behaviour
    return result["counts"], started


@pytest.mark.parametrize("client", [
    SiteClient([]),                                                  # no record at all
    SiteClient(error=PermissionError("not authorized to call listAutomations")),   # the router's role may not read it (not deployed yet)
    SiteClient(error=TimeoutError("AppSync timed out")),
    SiteClient([automation(procedureKey="some.other.procedure")]),    # a record for another procedure
    SiteClient([automation(trigger={"kind": "monitor", "config": {"monitorId": "hn", "publicationId": "distinctive"}})]),
    SiteClient([automation(trigger={"kind": "monitor", "config": {"monitorId": "ttab", "publicationId": "elsewhere"}})]),
    SiteClient([automation(trigger={"kind": "schedule", "config": {}})]),
    SiteClient([automation(trigger="{not json")]),                    # a record the router cannot read is no record
    SiteClient([{"id": "broken"}]),
    object(),                                                          # a client without the call
])
def test_with_no_usable_record_the_router_starts_exactly_as_it_always_did(client):
    expected_counts, expected = baseline()
    result, started = sweep(triggered_table(), client)
    assert started == expected and result["counts"] == expected_counts
    assert all("timeoutSeconds" not in request and "automationId" not in request["trigger"] for request in started)


def test_the_requests_and_rows_with_no_record_are_byte_for_byte_those_of_the_router_without_the_feature():
    table_a, table_b = triggered_table(), triggered_table()
    _, plain = sweep(table_a, object())
    _, with_empty_site = sweep(table_b, SiteClient([]))
    assert plain == with_empty_site
    without_run_id = lambda rows: [{key: value for key, value in row.items() if key != "routerRunId"} for row in rows]   # a fresh uuid per sweep
    assert without_run_id(trigger_rows(table_a)) == without_run_id(trigger_rows(table_b))
    assert {row["status"] for row in trigger_rows(table_a)} == {"started"} and all("automationId" not in row for row in trigger_rows(table_a))


def test_a_failure_while_counting_runs_starts_as_before():
    table = triggered_table()
    store = RouterStore(table)

    def broken(monitor_id, prefix):
        raise RuntimeError("Query denied")
    store.query_prefix = broken
    started = []
    result = run_router(store, "ttab", now=NOW + 60, cyclotron=None, deliver=Delivery(), appsync=lambda e: SiteClient([automation()]),
                        start_procedure=started.append, context_receipt=lambda c, p: {"contextHash": "h", "reason": None})
    assert result["counts"]["proceduresStarted"] == 2 and all("timeoutSeconds" not in request for request in started)


# --- enabled ----------------------------------------------------------------------------------------------------------------


def test_a_disabled_automation_starts_nothing_and_records_skipped_with_the_reason():
    table, client = triggered_table(), SiteClient([automation(enabled=False)])
    result, started = sweep(table, client)
    assert started == []
    assert result["counts"]["procedureSkipped"] == 2 and result["counts"]["proceduresStarted"] == 0
    assert result["counts"]["delivered"] == 2 and result["counts"]["routed"] == 2   # the delivery is not affected
    rows = trigger_rows(table)
    assert {row["status"] for row in rows} == {"skipped"} and {row["reason"] for row in rows} == {"automation disabled"}
    assert {row["automationId"] for row in rows} == {"distinctive.ttab"} and all("startedAt" not in row for row in rows)


def test_a_skipped_item_is_not_started_later_by_the_same_trigger():
    table = triggered_table()
    sweep(table, SiteClient([automation(enabled=False)]))
    router = Router(RouterStore(table), __import__("papyrus_content.monitoring_router", fromlist=["x"]).validate_router_config(
        table.items[("MONITOR#ttab", "CONFIG#router")]), monitor_id="ttab", now=NOW + 120, run_id="again", cyclotron=None,
        appsync=lambda e: SiteClient([automation(enabled=True)]), start_procedure=lambda request: None)
    from papyrus_content.monitoring_cloud import DynamoStore
    disc = DynamoStore._clean(table.by_prefix("DISC#97752244-EXA_26#")[0])
    router.start_procedures(router.publications["distinctive"], disc, {"referenceId": "reference-again"})
    assert router.counts["proceduresStarted"] == 0 and router.counts["procedureSkipped"] == 0   # the row exists: exactly once
    assert {row["status"] for row in trigger_rows(table)} == {"skipped"}


def test_an_enabled_automation_starts_and_its_timeout_and_id_go_with_the_request():
    table = triggered_table()
    result, started = sweep(table, SiteClient([automation(limits={"timeoutSeconds": 300, "maxConcurrent": 5})]))
    assert result["counts"]["proceduresStarted"] == 2 and len(started) == 2
    assert all(request["timeoutSeconds"] == 300 and request["trigger"]["automationId"] == "distinctive.ttab" for request in started)
    assert {row["automationId"] for row in trigger_rows(table)} == {"distinctive.ttab"}


def test_the_timeout_defaults_to_the_runners_limit_and_is_capped_there():
    _, started = sweep(triggered_table(), SiteClient([automation(limits={"maxConcurrent": 5})]))
    assert {request["timeoutSeconds"] for request in started} == {840}
    _, started = sweep(triggered_table(), SiteClient([automation(limits={"timeoutSeconds": 99999, "maxConcurrent": 5})]))
    assert {request["timeoutSeconds"] for request in started} == {840}


def test_the_record_is_read_once_per_publication_and_not_when_the_reference_already_existed():
    client = SiteClient([automation()])
    sweep(triggered_table(), client)
    assert client.reads == 1
    reused = SiteClient([automation()])

    class ReusingDelivery(Delivery):
        def __call__(self, *args):
            return {**super().__call__(*args), "referenceReused": True}
    run_router(RouterStore(triggered_table()), "ttab", now=NOW + 60, cyclotron=None, deliver=ReusingDelivery(), appsync=lambda e: reused,
               start_procedure=lambda request: None, context_receipt=lambda c, p: {"contextHash": "h", "reason": None})
    assert reused.reads == 0


# --- maxConcurrent -----------------------------------------------------------------------------------------------------------


def test_at_maxconcurrent_a_new_start_is_refused_with_a_recorded_reason():
    table = triggered_table()
    result, started = sweep(table, SiteClient([automation(limits={"timeoutSeconds": 840, "maxConcurrent": 1})]))
    assert len(started) == 1 and result["counts"]["proceduresStarted"] == 1 and result["counts"]["procedureRefused"] == 1
    assert result["counts"]["delivered"] == 2 and result["counts"]["routed"] == 2
    assert sorted(row["status"] for row in trigger_rows(table)) == ["refused", "started"]
    refused = next(row for row in trigger_rows(table) if row["status"] == "refused")
    assert refused["reason"] == "automation at its limit: 1 running, at most 1 at a time" and refused["automationId"] == "distinctive.ttab"
    assert "runId" not in refused and "startedAt" not in refused


def test_a_limit_of_two_lets_both_start():
    result, started = sweep(triggered_table(), SiteClient([automation(limits={"timeoutSeconds": 840, "maxConcurrent": 2})]))
    assert len(started) == 2 and result["counts"]["procedureRefused"] == 0


def test_a_run_now_row_in_flight_counts_against_the_limit():
    table = triggered_table()
    from datetime import datetime, timezone
    recent = datetime.fromtimestamp(NOW + 30, timezone.utc).isoformat().replace("+00:00", "Z")
    table.put_item({"pk": "MONITOR#ttab", "sk": f"MANUAL#distinctive.ttab#{recent}", "status": "running", "startedAt": recent,
                    "automationId": "distinctive.ttab"})
    result, started = sweep(table, SiteClient([automation(limits={"timeoutSeconds": 840, "maxConcurrent": 1})]))
    assert started == [] and result["counts"]["procedureRefused"] == 2


def test_runs_that_finished_do_not_count():
    table = triggered_table()
    from datetime import datetime, timezone
    recent = datetime.fromtimestamp(NOW + 30, timezone.utc).isoformat().replace("+00:00", "Z")
    for status in ("completed", "failed", "startFailed", "refused", "skipped", "notTriggered", "notRunnable"):
        table.put_item({"pk": "MONITOR#ttab", "sk": f"TRIGGER#distinctive#{PROCEDURE}#old-{status}", "status": status, "startedAt": recent})
    result, started = sweep(table, SiteClient([automation(limits={"timeoutSeconds": 840, "maxConcurrent": 2})]))
    assert len(started) == 2


def test_another_automations_or_procedures_runs_do_not_count():
    table = triggered_table()
    from datetime import datetime, timezone
    recent = datetime.fromtimestamp(NOW + 30, timezone.utc).isoformat().replace("+00:00", "Z")
    table.put_item({"pk": "MONITOR#ttab", "sk": "MANUAL#another.automation#x", "status": "running", "startedAt": recent})
    table.put_item({"pk": "MONITOR#ttab", "sk": "TRIGGER#distinctive#another.procedure#x", "status": "running", "startedAt": recent})
    result, started = sweep(table, SiteClient([automation(limits={"timeoutSeconds": 840, "maxConcurrent": 1})]))
    assert len(started) == 1


# --- the pure rules ----------------------------------------------------------------------------------------------------------


def row(status, started="2026-10-24T09:00:00Z"):
    return {"status": status, "startedAt": started}


def epoch(text):
    return gate._epoch(text)


@pytest.mark.parametrize("status, counts", [("starting", True), ("started", True), ("running", True), ("completed", False),
                                            ("failed", False), ("startFailed", False), ("refused", False), ("skipped", False)])
def test_only_runs_in_flight_count(status, counts):
    assert gate.in_flight_count([row(status)], now=epoch("2026-10-24T09:05:00Z"), window_seconds=960) == (1 if counts else 0)


def test_a_run_older_than_its_timeout_and_grace_no_longer_counts():
    now = epoch("2026-10-24T09:20:00Z")
    assert gate.in_flight_count([row("started")], now=now, window_seconds=840 + gate.GRACE_SECONDS) == 0       # 20 minutes old
    assert gate.in_flight_count([row("started", "2026-10-24T09:10:00Z")], now=now, window_seconds=960) == 1    # 10 minutes old
    assert gate.in_flight_count([row("started", None)], now=now, window_seconds=960) == 1                       # no time: counted, not lost


def test_the_window_follows_the_automations_own_timeout():
    short = {"id": "a", "enabled": True, "limits": {"timeoutSeconds": 60, "maxConcurrent": 1}}
    now = epoch("2026-10-24T09:10:00Z")
    assert gate.decide(short, [row("started", "2026-10-24T09:05:00Z")], now=now).action == "start"    # 300 s > 60 + 120
    assert gate.decide(short, [row("started", "2026-10-24T09:08:30Z")], now=now).action == "refuse"   # 90 s


def test_decide_returns_the_action_status_and_reason():
    now = epoch("2026-10-24T09:05:00Z")
    assert gate.decide(None, [], now=now) == gate.START_AS_BEFORE and gate.START_AS_BEFORE.status is None
    disabled = gate.decide({"id": "a", "enabled": False, "limits": {}}, [], now=now)
    assert (disabled.action, disabled.status, disabled.reason) == ("skip", "skipped", "automation disabled")
    refused = gate.decide({"id": "a", "enabled": True, "limits": {"maxConcurrent": 1}}, [row("running")], now=now)
    assert (refused.action, refused.status) == ("refuse", "refused") and "1 running, at most 1" in refused.reason
    unlimited = gate.decide({"id": "a", "enabled": True, "limits": {}}, [row("running")] * 9, now=now)
    assert unlimited.action == "start" and unlimited.timeout_seconds == 840


def test_limits_that_are_not_usable_are_ignored_not_errors():
    assert gate.limits_of({"limits": json.dumps({"timeoutSeconds": 0, "maxConcurrent": "many", "budgetUsdPerRun": -1})}) == {}
    assert gate.limits_of({"limits": "{broken"}) == {} and gate.limits_of({}) == {}
    assert gate.limits_of({"limits": {"timeoutSeconds": 30, "maxConcurrent": 2, "budgetUsdPerRun": 0.5}}) == {
        "timeoutSeconds": 30, "maxConcurrent": 2, "budgetUsdPerRun": 0.5}


def test_matching_prefers_the_lowest_id_when_two_records_name_the_same_trigger():
    rows = [automation(id="b.second"), automation(id="a.first", enabled=False)]
    found = gate.matching_automation(rows, monitor_id="ttab", publication_id="distinctive", procedure_key=PROCEDURE)
    assert found["id"] == "a.first" and found["enabled"] is False


def test_a_record_with_enabled_missing_counts_as_enabled_like_the_console_reads_it():
    row_without = {k: v for k, v in automation().items() if k != "enabled"}
    assert gate.matching_automation([row_without], monitor_id="ttab", publication_id="distinctive", procedure_key=PROCEDURE)["enabled"] is True


def test_the_gate_module_stays_light_for_the_routers_zip():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(gate.__file__).read_text())
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any(name.startswith(".") or "papyrus" in name for name in imported), imported   # stdlib only, and not the router


def test_the_routers_zip_carries_the_gate():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "infra/monitoring/build.py"
    spec = importlib.util.spec_from_file_location("monitoring_build", path)
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    assert "automation_gate" in build.router_modules()
    assert "automations" not in build.router_modules()   # the router does not pull in the CLI and console code


def test_the_routers_role_may_read_automation_records_of_distinctive_only_and_update_its_rows():
    from test_monitoring_router import _template
    resources = _template()["Resources"]
    policy = resources["RouterAutomationReadPolicy"]["Properties"]
    assert policy["Roles"] == [("Ref", "RouterRole")]
    (statement,) = policy["PolicyDocument"]["Statement"]
    assert statement["Action"] == "appsync:GraphQL"
    (resource,) = [entry[1] for entry in statement["Resource"]]
    assert resource.endswith("apis/${DistinctiveApiId}/types/Query/fields/listAutomations")   # one read field, one API, no write
    table = next(s for s in resources["RouterRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"] if s["Sid"] == "MonitoringTable")
    assert "dynamodb:UpdateItem" in table["Action"] and "dynamodb:Scan" not in table["Action"]


def test_the_price_table_ships_inside_the_package():
    import importlib.resources
    text = importlib.resources.files("papyrus_content").joinpath("data", "model_prices.json").read_text()
    assert "gpt-6-luna" in json.loads(text)["models"]
