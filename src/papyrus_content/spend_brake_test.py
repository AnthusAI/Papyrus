from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from papyrus_content import spend_ledger
from papyrus_content.spend_brake import BUDGET_REACHED, HALTED, SPEND_UNREADABLE, SpendBrake
from papyrus_content.spend_ledger_test import FakeLedgerTable

MOMENT = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)


class HaltableTable(FakeLedgerTable):
    def put_item(self, Item):
        self.rows[(Item["pk"], Item["sk"])] = dict(Item)

    def delete_item(self, Key):
        self.rows.pop((Key["pk"], Key["sk"]), None)


class UnreadableTable(FakeLedgerTable):
    def get_item(self, Key, ConsistentRead=False):
        raise RuntimeError("throttled")


def decision_with(budget=None):
    document = {"site": {"budget": budget} if budget else {}}
    return SimpleNamespace(state=SimpleNamespace(document=document))


def spend(table, usd, tenant="alpha", run="run-1", period="month"):
    spend_ledger.record_run(table, tenant_id=tenant, responsibility=None, run_id=run, period=period, cost_usd=usd, calls=1, unpriced_calls=0, moment=MOMENT)


def brake_over(table):
    return SpendBrake(table, default_budget=Decimal("100"), clock=lambda: MOMENT)


def test_a_site_under_its_budget_may_start_a_run():
    table = HaltableTable()
    spend(table, 4)
    assert brake_over(table).stop_for({"tenantId": "alpha"}, decision_with({"amountUsd": 5, "period": "month"})) is None


def test_a_site_at_its_budget_starts_nothing():
    table = HaltableTable()
    spend(table, 5)
    stop = brake_over(table).stop_for({"tenantId": "alpha"}, decision_with({"amountUsd": 5, "period": "month"}))
    assert stop.reason_code == BUDGET_REACHED and "$5.00 spent of $5.00" in stop.reason


def test_another_sites_spend_does_not_count():
    table = HaltableTable()
    spend(table, 500, tenant="beta")
    assert brake_over(table).stop_for({"tenantId": "alpha"}, decision_with({"amountUsd": 5, "period": "month"})) is None


def test_a_site_with_no_budget_gets_the_default_so_none_is_unlimited():
    table = HaltableTable()
    spend(table, 100)
    assert brake_over(table).stop_for({"tenantId": "alpha"}, decision_with()).reason_code == BUDGET_REACHED


def test_the_budget_is_counted_for_the_cycle_the_policy_names():
    table = HaltableTable()
    spend(table, 6, period="day")
    assert brake_over(table).stop_for({"tenantId": "alpha"}, decision_with({"amountUsd": 5, "period": "day"})).reason_code == BUDGET_REACHED
    later = SpendBrake(table, default_budget=Decimal("100"), clock=lambda: datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc))
    assert later.stop_for({"tenantId": "alpha"}, decision_with({"amountUsd": 5, "period": "day"})) is None


def test_a_halt_for_one_site_stops_only_that_site():
    table = HaltableTable()
    spend_ledger.set_halt(table, tenant_id="alpha", reason="a loop was spending", by="ryan", moment=MOMENT)
    brake = brake_over(table)
    assert brake.stop_for({"tenantId": "alpha"}, decision_with()).reason_code == HALTED
    assert brake.stop_for({"tenantId": "beta"}, decision_with()) is None


def test_a_halt_for_every_site_stops_every_run_and_clearing_it_lets_them_start():
    table = HaltableTable()
    spend_ledger.set_halt(table, tenant_id=None, reason="provider key leaked", by="ryan", moment=MOMENT)
    brake = brake_over(table)
    assert "provider key leaked" in brake.stop_for({"tenantId": "beta"}, decision_with()).reason
    assert brake.stop_for({}, decision_with()).reason_code == HALTED
    spend_ledger.clear_halt(table, tenant_id=None)
    assert brake.stop_for({"tenantId": "beta"}, decision_with()) is None


def test_a_ledger_that_cannot_be_read_starts_nothing():
    assert brake_over(UnreadableTable()).stop_for({"tenantId": "alpha"}, decision_with()).reason_code == SPEND_UNREADABLE


def test_a_runner_with_no_ledger_starts_nothing():
    assert SpendBrake(None).stop_for({"tenantId": "alpha"}, decision_with()).reason_code == SPEND_UNREADABLE


def test_a_halt_says_why_and_who():
    try:
        spend_ledger.set_halt(HaltableTable(), tenant_id=None, reason=" ", by="ryan", moment=MOMENT)
    except spend_ledger.SpendError:
        return
    raise AssertionError("a halt with no reason was accepted")
