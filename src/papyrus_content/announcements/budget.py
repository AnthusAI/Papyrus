"""The budget: what an account may spend on X in one billing cycle, and what it has spent.

The owner enters the budget and the day of the month the X billing cycle starts, plus X's price list with the date it was copied (X returns no price with a
request, and the list changes). Nothing here is a number: every amount comes from the site's settings.

The ledger is one counter row per account and cycle (``AnnouncementSpend``, id ``<accountId>#<cycle start>``), raised once for every charge Caducus records on a
delivery (its ``Guard.charged`` call) with the price used. The same Guard refuses a post that would pass the budget (``Guard.refusal``), and the announcement
pipeline asks the same question before it hands a Story to Caducus. Charges are applied one at a time (the ``x`` queue has one consumer), so a check followed by
a charge cannot race another post.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from .rules import money, post_price

def _clamped(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def cycle_start(now: datetime, day: int) -> date:
    """The first day of the billing cycle that contains ``now`` (UTC), for a cycle that starts on ``day`` of the month (a short month starts on its last day)."""
    today = now.astimezone(timezone.utc).date()
    this_month = _clamped(today.year, today.month, day)
    if today >= this_month:
        return this_month
    year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return _clamped(year, month, day)


def next_cycle_start(start: date, day: int) -> date:
    year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return _clamped(year, month, day)


def money_sum(*values: Any) -> Decimal:
    return sum((money(value) or Decimal(0) for value in values), Decimal(0))


def spend_id(account_id: str, start: date) -> str:
    return f"{account_id}#{start.isoformat()}"


@dataclass(frozen=True)
class Standing:
    spent: Decimal
    budget: Decimal
    cycle_start: date
    cycle_end: date  # the first day of the next cycle

    def would_pass(self, amount: Decimal) -> bool:
        return self.spent + amount > self.budget

    def sentence(self) -> str:
        return f"${self.spent:.2f} spent of ${self.budget:.2f} this cycle"


def standing(settings: Mapping[str, Any], spent_so_far: Any, now: datetime) -> Standing:
    budget = money(settings.get("budget"))
    if budget is None or settings.get("billingCycleDay") is None:
        raise ValueError("The site has no budget or billing cycle day.")
    start = cycle_start(now, int(settings["billingCycleDay"]))
    return Standing(money_sum(spent_so_far), budget, start, next_cycle_start(start, int(settings["billingCycleDay"])))


def suggestion(eligible_count: int, window_days: int, settings: Mapping[str, Any]) -> dict[str, Any]:
    """From the site's own pace: how many Stories met the rules over ``window_days``, and what that costs per 30 days at the link price.

    Reported as a pace, never applied as a limit. Zero eligible Stories gives zero posts."""
    per_month = Decimal(eligible_count) * Decimal(30) / Decimal(window_days)
    amount = per_month * post_price(settings)
    return {"eligibleCount": eligible_count, "windowDays": window_days, "postsPerMonth": float(per_month), "dollarsPerMonth": float(amount),
            "sentence": f"At your pace, about {round(per_month)} posts and ${amount:.2f} per month"}
