"""The deliver side of X: the pause, the budget and the one worker that sends an X Delivery (PPY-efd06c).

``SpendControl`` is what the old announcement pipeline knew about guards, kept as it was and moved off the old row shape: the pause, the account connection, the budget against the cycle's
spend (``spend.SpendLedger``, ``budget.py``), and the rule that a pause the budget caused ends by itself when there is room again while a pause a person made never does.

``XRunner`` hands one due X Delivery to its account's single worker (``attempts.AccountWorker``) and does what only the deliver side may:

* **X is off until the owner turns it on.** The runner refuses to send unless the site's mode is ``on``. A dry run is finished when the Delivery is made and never reaches it.
* **A correction deletes the old post first.** A Delivery that supersedes another is sent only after the post it replaces has been taken down (``withdrawals.Withdrawals.delete_superseded``,
  safe to repeat), so the account never carries both. The deletion cost is written on the old Delivery.
* **The guards are Caducus's, asked before every post.** A pause or the budget refuses the attempt (``guard.SpendGuard``); the attempt closes ``refused`` and the Delivery waits. A refusal
  for the budget also pauses announcements, with the reason, and tells the editors; ``resume_blocked`` puts a Delivery back to ready when the guard lifts.
* **An account that needs connecting again, or a site with no budget or billing day, sends nothing** and says so in words; no attempt is opened.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from . import budget as budget_module
from .attempts import AccountWorker, NotReleasable
from .deliveries import Deliveries
from .records import BLOCKED, BUDGET_REACHED_CODE, PAUSED_CODE, RELEASE, RecordError, now_iso
from .rules import OFF, ON, PAUSE_BUDGET, SYSTEM, post_price, view
from .settings import spacing_minutes
from .spend import SpendLedger
from .withdrawals import Withdrawals
from .x_channel import CHANNEL, XChannel

BUDGET_PAUSE_REASON = "Budget reached for this cycle"
#: The blocked Deliveries ``resume_blocked`` puts back: those a pause or the budget stopped.
GUARD_CODES = (PAUSED_CODE, BUDGET_REACHED_CODE)


class NotSendable(RecordError):
    """X is not ready to send: the site's mode is not on, the account needs connecting, or the budget is not set. ``code`` is the short form."""

    def __init__(self, code: str, words: str):
        super().__init__(words)
        self.code = code


@dataclass
class SpendControl:
    """The settings document's reader and writer (``settings.AnnouncementSettings``), the account connection's status, the spend ledger and a way to tell the editors
    (``notify(kind, facts)``; None tells no one)."""

    settings: Any
    connection: Callable[[], Mapping[str, Any]]
    ledger: SpendLedger
    notify: Callable[[str, Mapping[str, Any]], None] | None = None
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def current(self) -> dict[str, Any]:
        """The settings and the connection as one flat view (``rules.view``)."""
        return view(self.settings.read(), self.connection())

    def standing(self, settings: Mapping[str, Any]) -> budget_module.Standing:
        start = budget_module.cycle_start(self.now(), int(settings["billingCycleDay"]))
        return budget_module.standing(settings, self.ledger.spent(settings["accountId"], start), self.now())

    def lift_budget_pause(self, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        """A pause the budget caused ends by itself when the budget has room again (a new cycle, or the owner raised it). A pause a person made never does."""
        settings = settings or self.current()
        if not (settings["paused"] and settings["pauseKind"] == PAUSE_BUDGET and settings["pausedBy"] == SYSTEM):
            return settings
        if settings["budget"] is None or settings["billingCycleDay"] is None or self.standing(settings).would_pass(post_price(settings)):
            return settings
        self.settings.resume_if(PAUSE_BUDGET)
        return self.current()

    def pause_for_budget(self, story: str = "") -> dict[str, Any]:
        """The budget was reached: announcements pause with the reason, and the editors are told. Pausing again changes nothing the owner can see."""
        settings = self.current()
        if not settings["paused"]:
            self.settings.pause(PAUSE_BUDGET, BUDGET_PAUSE_REASON, SYSTEM, self.now().strftime("%Y-%m-%dT%H:%M:%SZ"))
            self._tell("announcement.budget-reached", story=story, spent=self.standing(self.current()).sentence())
        return self.current()

    def _tell(self, kind: str, **facts: Any) -> None:
        if self.notify is not None:
            self.notify(kind, facts)

    def ready_to_send(self) -> dict[str, Any]:
        """The settings, or why nothing is sent: X is not on, the account needs connecting again, or the budget and the billing day are not set."""
        settings = self.lift_budget_pause()
        if settings["mode"] != ON:
            raise NotSendable("not_on", "Announcements are not turned on for this publication, so nothing is sent to X.")
        if not settings["connected"]:
            words = "The X account needs connecting again" if settings["connectionStatus"] == "needs_reconnecting" else "No X account is connected"
            if settings["connectionStatus"] == "needs_reconnecting":
                self._tell("announcement.account-needs-reconnecting", reason=words)
            raise NotSendable("account_needs_reconnecting", words)
        if settings["budget"] is None or settings["billingCycleDay"] is None:
            raise NotSendable("settings_incomplete", "Enter a budget and the day your X billing cycle starts")
        return settings


class XRunner:
    def __init__(self, deliveries: Deliveries, withdrawals: Withdrawals, channel: XChannel, control: SpendControl, *, by: str = "deliver"):
        self.deliveries, self.withdrawals, self.channel, self.control, self.by = deliveries, withdrawals, channel, control, by

    def send(self, delivery: str, *, now: str | None = None) -> dict[str, Any]:
        """Send one X Delivery through its account's worker. Nothing is sent, and no attempt opens, when X is not ready (``NotSendable``) or the Delivery may not go yet
        (``attempts.NotReleasable``)."""
        now = now or now_iso()
        self.control.ready_to_send()
        row = self.deliveries.get(delivery)
        if row is None or row["channel"] != CHANNEL:
            raise RecordError(f"There is no X Delivery {delivery}.")
        if row.get("supersedes"):
            old = self.deliveries.get(row["supersedes"])
            if old is not None:
                self.withdrawals.delete_superseded(old, by=self.by, now=now)
        worker = AccountWorker(self.deliveries, self.channel, CHANNEL, row["accountId"], spacing_minutes=spacing_minutes(self.control.settings.read(), CHANNEL, row["accountId"]))
        return self._after(worker.send(delivery, by=self.by, now=now))

    def settle(self, delivery: str, *, now: str | None = None) -> dict[str, Any]:
        """Read what Caducus recorded for a Delivery whose attempt had no answer yet, and close the attempt if it says how it ended. Hands nothing over unless Caducus has no
        record of the event at all (it dedupes on the event id)."""
        row = self.deliveries.get(delivery)
        if row is None or row["channel"] != CHANNEL:
            raise RecordError(f"There is no X Delivery {delivery}.")
        worker = AccountWorker(self.deliveries, self.channel, CHANNEL, row["accountId"], spacing_minutes=spacing_minutes(self.control.settings.read(), CHANNEL, row["accountId"]))
        return self._after(worker.settle(delivery, by=self.by, now=now or now_iso()))

    def _after(self, written: dict[str, Any]) -> dict[str, Any]:
        """A refusal for the budget also pauses announcements, with the reason, and tells the editors."""
        if written.get("state") == BLOCKED and written.get("blockedReason") == BUDGET_REACHED_CODE:
            self.control.pause_for_budget()
        return written

    def send_due(self, now: str | None = None) -> list[dict[str, Any]]:
        """Send every X Delivery whose time has come (one read of the sparse due index). One that may not go yet, or that X is not ready for, is left as it is."""
        now = now or now_iso()
        sent = []
        for row in self.deliveries.due(now):
            if row["channel"] != CHANNEL:
                continue
            try:
                sent.append(self.send(row["id"], now=now))
            except (NotReleasable, NotSendable):
                continue
        return sent


def resume_blocked(deliveries: Deliveries, control: SpendControl, *, by: str, now: str | None = None) -> list[dict[str, Any]]:
    """Put back every X Delivery a pause or the budget stopped, now that the guard has lifted: it is ready again and due now, and its next try is the next attempt.

    The account's own Deliveries are read newest first, one page at a time (the account index; nothing lists a table). Resuming clears the pause, and with it the time the pause began, so
    there is no point in the account's history to stop at: the read goes to the end of the account's partition, which holds only that account's Deliveries."""
    now = now or control.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    settings = control.lift_budget_pause()
    if settings["mode"] == OFF or not settings["accountId"] or settings["paused"]:
        return []
    resumed = []
    for row in deliveries.for_account(CHANNEL, settings["accountId"]):
        if row.get("state") == BLOCKED and row.get("blockedReason") in GUARD_CODES:
            back = deliveries.resume(row, by=by, now=now)
            resumed.append(deliveries.wait_until(back, now, RELEASE, by=by, now=now))
    return resumed
