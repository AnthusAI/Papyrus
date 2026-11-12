"""The pause and the budget as Caducus asks for them: ``Guard.refusal(account, price)`` before every post and ``Guard.charged(account, price)`` after each charge.

Withdrawals are never refused. Structural (duck-typed) so it needs no Caducus import: an account is anything with a ``key`` ``CHANNELACCT#x#<accountId>``, a price
anything with a decimal-string ``amount``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from . import budget as budget_module
from .store import AnnouncementStore, now_iso


def account_id_of(account: Any) -> str:
    return str(account.key).rsplit("#", 1)[-1]


class SpendGuard:
    def __init__(self, store: AnnouncementStore, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.store, self.now = store, now

    def _standing(self, settings: dict[str, Any], account_id: str) -> budget_module.Standing:
        start = budget_module.cycle_start(self.now(), int(settings["billingCycleDay"]))
        return budget_module.standing(settings, self.store.spent(account_id, start), self.now())

    def refusal(self, account: Any, price: Any) -> str | None:
        settings = self.store.settings()
        if settings.get("paused"):
            return "Announcements are paused" + (f": {settings['pauseReason']}" if settings.get("pauseReason") else "")
        if self._standing(settings, account_id_of(account)).would_pass(Decimal(str(price.amount))):
            return "Budget reached for this cycle"
        return None

    def charged(self, account: Any, price: Any) -> None:
        settings = self.store.settings()
        start = budget_module.cycle_start(self.now(), int(settings["billingCycleDay"]))
        self.store.add_spend(account_id_of(account), start, Decimal(str(price.amount)), now=now_iso())
