"""The spend brake: what the procedure runner asks before it starts a run, so spending is stopped before it happens and not only counted after it.

A run is refused, and recorded as ``nothing`` with a reason code, when

* ``halted``: a halt row is set for every site or for this site (``spend_ledger.set_halt``), the kill switch;
* ``budget_reached``: what the site's cycle already holds in the ledger is at or over the site's budget (``site.budget`` in the agent policy; a site that has none
  gets ``DEFAULT_BUDGET_USD`` for the month, so no site is unlimited). Only a paid run reads the budget: a run whose registered definition says ``paid: false``
  is free work and starts at the budget. A paid wake at the budget is not lost: the stop names the next cycle start, and the runner records the wake
  as waiting until then (spend_stop.py, PPY-9376f8);
* ``spend_unreadable``: the ledger could not be read, because a brake that opens when it cannot see is no brake.

The check is made before the run, so a run that starts under the budget may end over it: the budget is a ceiling on starting, and the overshoot is at most the
runs that were already in flight.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from . import spend_ledger

HALTED, BUDGET_REACHED, SPEND_UNREADABLE = "halted", "budget_reached", "spend_unreadable"
DEFAULT_BUDGET_USD = Decimal("10")   # Ryan 2026-11-22: a site with no budget gets $10 a month
DEFAULT_PERIOD = "month"
DEFAULT_BUDGET_VARIABLE = "PROCEDURE_RUNNER_DEFAULT_BUDGET_USD"


@dataclass(frozen=True)
class Stop:
    reason_code: str
    reason: str
    period: str | None = None           # budget_reached only: the budget period, the start of the cycle that is spent, and when the next one starts
    cycle_start: date | None = None
    due_at: str | None = None


def default_budget_usd(environ: dict[str, str] | None = None) -> Decimal:
    raw = (environ if environ is not None else os.environ).get(DEFAULT_BUDGET_VARIABLE, "").strip()
    try:
        value = Decimal(raw) if raw else DEFAULT_BUDGET_USD
    except ArithmeticError:
        return DEFAULT_BUDGET_USD
    return value if value >= 0 else DEFAULT_BUDGET_USD


class SpendBrake:
    def __init__(self, table: Any, *, default_budget: Decimal | None = None, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.table, self.clock = table, clock
        self.default_budget = default_budget_usd() if default_budget is None else default_budget

    def stop_for(self, request: dict, decision: Any) -> Stop | None:
        tenant_id = request.get("tenantId") or None
        if self.table is None:
            return Stop(SPEND_UNREADABLE, "The spend ledger is not configured for this runner, so no run starts: a run is not started without a way to count and limit its cost.")
        try:
            halt = spend_ledger.halt_reason(self.table, tenant_id)
            if halt:
                return Stop(HALTED, f"Runs are halted: {halt}")
            if not tenant_id:
                return None
            if getattr(decision, "paid", None) is False:
                return None   # free work: the budget limits only what is paid
            budget = self._budget_of(decision)
            period, moment = budget["period"], self.clock()
            start = spend_ledger.cycle_start(period, moment)
            held = spend_ledger.spent_in(self.table, tenant_id=tenant_id, scope="ai", start=start)
        except Exception as error:
            return Stop(SPEND_UNREADABLE, f"The spend ledger could not be read ({type(error).__name__}), so no run starts.")
        if held.usd >= budget["amountUsd"]:
            partial = " (and some model calls had no price, so the total is at least this)" if held.partial else ""
            due_at = f"{spend_ledger.next_cycle_start(period, moment).isoformat()}T00:00:00Z"
            return Stop(BUDGET_REACHED, f"The site's budget for this {period} is reached: ${held.usd:.2f} spent of ${budget['amountUsd']:.2f}{partial}. "
                                         f"Paid work waits until the next {period} starts ({due_at}); raising the budget (papyrus agents set-budget) runs it now.",
                        period=period, cycle_start=start, due_at=due_at)
        return None

    def _budget_of(self, decision: Any) -> dict[str, Any]:
        state = getattr(decision, "state", None)
        site = (state.document.get("site") or {}) if state is not None else {}
        budget = site.get("budget") or {}
        return {"amountUsd": Decimal(str(budget["amountUsd"])) if "amountUsd" in budget else self.default_budget, "period": budget.get("period", DEFAULT_PERIOD)}
