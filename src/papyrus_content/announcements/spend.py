"""What an account spent on X in one billing cycle: the ``AnnouncementSpend`` counter (PPY-fa165c generalises it into the one ledger later).

One row for each account and cycle, id ``<accountId>#<cycle start date>``, raised once for every charge Caducus records (``guard.SpendGuard.charged``). The budget rules
are in ``budget.py``; this is only the counter. It is the one thing the old X row shape's store held that stays: the Announcement and the Delivery hold everything else.
"""
from __future__ import annotations

from typing import Any

from . import budget as budget_module
from .records import now_iso

SPEND_MODEL = "AnnouncementSpend"


class SpendLedger:
    def __init__(self, client: Any):
        self.client = client

    def spent(self, account_id: str, start: Any) -> Any:
        row = self.client.get_record(SPEND_MODEL, budget_module.spend_id(account_id, start))
        return (row or {}).get("total")

    def add_spend(self, account_id: str, start: Any, amount: Any, *, now: str | None = None) -> str:
        """Raise the cycle's counter by ``amount`` and return the new total. Charges arrive one at a time (see ``budget``)."""
        row_id = budget_module.spend_id(account_id, start)
        row = self.client.get_record(SPEND_MODEL, row_id)
        total = str(budget_module.money_sum((row or {}).get("total"), amount))
        record = {"id": row_id, "accountId": account_id, "cycleStart": start.isoformat(), "total": total, "updatedAt": now or now_iso()}
        (self.client.update_record if row else self.client.create_record)(SPEND_MODEL, record)
        return total
