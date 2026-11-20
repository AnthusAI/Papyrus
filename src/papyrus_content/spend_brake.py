"""The spend brake: what the procedure runner asks before it starts a run, so spending is stopped before it happens and not only counted after it.

A run is refused, and recorded as ``nothing`` with a reason code, when

* ``halted``: a halt row is set for every site or for this site (``spend_ledger.set_halt``), the kill switch;
* ``budget_reached``: what the site's cycle already holds in the ledger is at or over the site's budget (``site.budget`` in the agent policy; a site that has none
  gets ``DEFAULT_BUDGET_USD`` for the month, so no site is unlimited);
* ``spend_unreadable``: the ledger could not be read, because a brake that opens when it cannot see is no brake.

The check is made before the run, so a run that starts under the budget may end over it: the budget is a ceiling on starting, and the overshoot is at most the
runs that were already in flight.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from . import spend_ledger

HALTED, BUDGET_REACHED, SPEND_UNREADABLE = "halted", "budget_reached", "spend_unreadable"
DEFAULT_BUDGET_USD = Decimal("100")
DEFAULT_PERIOD = "month"
DEFAULT_BUDGET_VARIABLE = "PROCEDURE_RUNNER_DEFAULT_BUDGET_USD"


@dataclass(frozen=True)
class Stop:
    reason_code: str
    reason: str


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
            budget = self._budget_of(decision)
            period = budget["period"]
            held = spend_ledger.spent(self.table, tenant_id=tenant_id, scope="ai", period=period, moment=self.clock())
        except Exception as error:
            return Stop(SPEND_UNREADABLE, f"The spend ledger could not be read ({type(error).__name__}), so no run starts.")
        if held.usd >= budget["amountUsd"]:
            partial = " (and some model calls had no price, so the total is at least this)" if held.partial else ""
            return Stop(BUDGET_REACHED, f"The site's budget for this {period} is reached: ${held.usd:.2f} spent of ${budget['amountUsd']:.2f}{partial}. "
                                         "Raise it in the agent policy or lift the halt, and the next wake runs.")
        return None

    def _budget_of(self, decision: Any) -> dict[str, Any]:
        state = getattr(decision, "state", None)
        site = (state.document.get("site") or {}) if state is not None else {}
        budget = site.get("budget") or {}
        return {"amountUsd": Decimal(str(budget["amountUsd"])) if "amountUsd" in budget else self.default_budget, "period": budget.get("period", DEFAULT_PERIOD)}
