from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import spend_ledger  # noqa: E402
from papyrus_content.procedure_runner import record_spend, spend_of  # noqa: E402
from papyrus_content.agent_policy.resolve import PolicyState  # noqa: E402
from papyrus_content.spend_ledger_test import FakeLedgerTable  # noqa: E402

TENANT = "alpha"
MONTHS = {"November": 11}


class _Decision:
    def __init__(self, responsibility, period):
        self.responsibility = responsibility
        self.state = PolicyState(1, {"site": {"budget": {"amountUsd": 25, "period": period}}})


def _moment(text):
    day, month, year = text.split()[-3:]
    return datetime(int(year), MONTHS[month], int(day), 15, 0, tzinfo=timezone.utc)


def _day(text):
    day, month, year = text.split()[-3:]
    return date(int(year), MONTHS[month], int(day))


@given('an empty spend ledger and a site whose budget period is "{period}"')
def empty_ledger(context, period):
    context.table_ledger, context.period, context.added = FakeLedgerTable(), period, []


def _finish(context, run_id, responsibility, moment, calls, unpriced, cost):
    usage = {"calls": calls, "unpricedCalls": unpriced}
    spend = spend_of({"tenantId": TENANT}, _Decision(responsibility, context.period), usage, float(cost))
    context.last_result = {"runId": run_id, "spend": spend}
    context.added.append(spend_ledger.record_run(context.table_ledger, tenant_id=spend["tenantId"], responsibility=spend["responsibility"], run_id=run_id,
                                                 period=spend["period"], cost_usd=spend["costUsd"], calls=spend["calls"],
                                                 unpriced_calls=spend["unpricedCalls"], moment=moment))
    context.moment = moment


@when('the run "{run_id}" of the agent "{agent}" finishes on {when} with {calls:d} priced calls costing {cost} dollars')
def finish_priced(context, run_id, agent, when, calls, cost):
    _finish(context, run_id, agent, _moment(when), calls, 0, cost)


@when('the run "{run_id}" of the agent "{agent}" finishes on {when} with {calls:d} calls, {unpriced:d} of them unpriced, costing {cost} dollars')
def finish_unpriced(context, run_id, agent, when, calls, unpriced, cost):
    _finish(context, run_id, agent, _moment(when), calls, unpriced, cost)


@when("the same wake is delivered again and the run is counted again")
def redelivered(context):
    spend = context.last_result["spend"]
    context.added.append(spend_ledger.record_run(context.table_ledger, tenant_id=spend["tenantId"], responsibility=spend["responsibility"],
                                                 run_id=context.last_result["runId"], period=spend["period"], cost_usd=spend["costUsd"], calls=spend["calls"],
                                                 unpriced_calls=spend["unpricedCalls"], moment=context.moment))


def _held(context, scope, when):
    start = _day(when)
    row = context.table_ledger.get_item(Key={"pk": spend_ledger.partition_key(TENANT, scope, start), "sk": spend_ledger.TOTAL_SORT_KEY}).get("Item") or {}
    return spend_ledger.Spent(int(row.get("microUsd", 0)), int(row.get("calls", 0)), int(row.get("unpricedCalls", 0)))


@then("the site's cycle starting {when} holds {cost} dollars from {calls:d} calls")
def site_holds(context, when, cost, calls):
    held = _held(context, "ai", when)
    assert held.usd == Decimal(cost) and held.calls == calls, held


@then('the agent "{agent}" cycle starting {when} holds {cost} dollars from {calls:d} calls')
def agent_holds(context, agent, when, cost, calls):
    held = _held(context, f"ai:{agent}", when)
    assert held.usd == Decimal(cost) and held.calls == calls, held


@then("the second delivery added nothing")
def second_added_nothing(context):
    assert context.added == [True, False], context.added


@then("the site's total is partial, missing {missing:d} call")
def partial(context, missing):
    held = _held(context, "ai", "Sunday 1 November 2026")
    assert held.partial and held.unpricedCalls == missing, held
