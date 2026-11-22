from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from papyrus_content import spend_ledger, spend_stop
from papyrus_content.agent_policy.run_gate import registered_paid
from papyrus_content.spend_brake import BUDGET_REACHED, HALTED, SpendBrake, Stop
from papyrus_content.spend_brake_test import HaltableTable, decision_with, spend

MOMENT = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)


def test_the_next_cycle_starts_on_the_next_day_monday_or_first_of_the_month():
    assert spend_ledger.next_cycle_start("day", MOMENT) == date(2026, 11, 19)
    assert spend_ledger.next_cycle_start("week", MOMENT) == date(2026, 11, 23)
    assert spend_ledger.next_cycle_start("month", MOMENT) == date(2026, 12, 1)
    assert spend_ledger.next_cycle_start("month", datetime(2026, 12, 31, 23, 0, tzinfo=timezone.utc)) == date(2027, 1, 1)


def test_the_registered_definition_says_whether_a_run_is_paid():
    assert registered_paid({"definition": json.dumps({"paid": False})}) is False
    assert registered_paid({"definition": {"paid": True}}) is True
    assert registered_paid({"definition": None}) is None   # no registered definition: the brake counts it as paid
    assert registered_paid({}) is None


def test_free_work_starts_at_the_budget_and_paid_work_is_told_when_the_next_cycle_starts():
    table = HaltableTable()
    spend(table, 5, period="week")
    brake = SpendBrake(table, default_budget=Decimal("100"), clock=lambda: MOMENT)
    free = SimpleNamespace(**vars(decision_with({"amountUsd": 5, "period": "week"})), paid=False)
    assert brake.stop_for({"tenantId": "alpha"}, free) is None
    stop = brake.stop_for({"tenantId": "alpha"}, decision_with({"amountUsd": 5, "period": "week"}))
    assert (stop.reason_code, stop.period, stop.cycle_start, stop.due_at) == (BUDGET_REACHED, "week", date(2026, 11, 16), "2026-11-23T00:00:00Z")


def test_a_halt_stops_free_work_too():
    table = HaltableTable()
    spend_ledger.set_halt(table, tenant_id="alpha", reason="a loop", by="ryan", moment=MOMENT)
    free = SimpleNamespace(**vars(decision_with()), paid=False)
    assert SpendBrake(table, clock=lambda: MOMENT).stop_for({"tenantId": "alpha"}, free).reason_code == HALTED


class WaitingRuns:
    def __init__(self, rows):
        self.rows, self.updates = rows, []

    def list_by_index(self, index_name, key_value, **_):
        assert (index_name, key_value) == (spend_stop.WAITING_INDEX, spend_stop.WAITING)
        return list(self.rows)

    def graphql(self, query, variables):
        self.updates.append(variables["input"])
        return {}


def waiting_row(run_id, requested_at, *, wake=True, waiting_for=spend_stop.WAITING_FOR):
    key = f"rate|manual|{run_id}"
    return {"id": run_id, "runStatus": "waiting", "waitingFor": waiting_for, "requestedAt": requested_at, "wakeKey": key,
            "wake": json.dumps({"wakeKey": key, "trigger": {"summary": "s"}}) if wake else None}


def test_release_sends_the_waiting_wakes_oldest_first_each_as_its_own_message():
    client = WaitingRuns([waiting_row("b", "2026-11-18T10:00:00Z"), waiting_row("a", "2026-11-18T09:00:00Z"),
                          waiting_row("x", "2026-11-18T08:00:00Z", wake=False), waiting_row("q", "2026-11-18T07:00:00Z", waiting_for="quiet window")])
    sent = []
    result = spend_stop.release(client, lambda request, deduplication=None: sent.append((request, deduplication)), "alpha", moment="2026-11-19T00:00:00Z")
    assert result["released"] == ["rate|manual|a", "rate|manual|b"] and result["unreleasable"] == ["x"]
    assert all(request["trigger"][spend_stop.RELEASED_FROM] == spend_stop.WAITING_FOR for request, _ in sent)
    assert [dedup for _, dedup in sent] == ["rate|manual|a|released|2026-11-19T00:00:00Z", "rate|manual|b|released|2026-11-19T00:00:00Z"]


def test_a_waiting_wake_that_a_halt_stops_is_cleared_so_the_runner_records_it_as_skipped():
    client = WaitingRuns([])
    stopper = spend_stop.SpendStop(timers=lambda request: None, send=lambda *a, **k: None)
    assert stopper.settle(client, "run-1", {}, None, Stop(HALTED, "halted"), waiting=True) is None
    assert client.updates == [{"id": "run-1", "runStatus": "started", "waitingFor": None, "dueAt": None, "wake": None}]


def test_a_wake_that_did_not_wait_is_left_alone_when_nothing_stops_it():
    client = WaitingRuns([])
    stopper = spend_stop.SpendStop(timers=lambda request: None, send=lambda *a, **k: None)
    assert stopper.settle(client, "run-1", {}, None, None, waiting=False) is None and client.updates == []


def test_the_original_wake_is_kept_without_the_marks_of_a_release_or_a_timer():
    request = {"wakeKey": "k", "trigger": {"summary": "s", spend_stop.RELEASED_FROM: spend_stop.WAITING_FOR, spend_stop.RELEASED_AT: "t",
                                           "waitingFor": spend_stop.WAITING_FOR, "dueAt": "d"}}
    assert spend_stop.original_wake(request)["trigger"] == {"summary": "s"}
