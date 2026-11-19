"""The deliver side of X for one site: the runner over the site's real Broadcaster, or a plain refusal when the site has none.

``x_runner`` builds the ``x_runner.XRunner`` for a site from the Broadcaster the site's config provides (``caducus_x.CaducusBroadcaster``, over Caducus's router, delivery log and ``x`` channel).

* A site whose mode is On and that has no Broadcaster raises ``ChannelNotAvailable``: X was turned on and nothing can post, which is said, never papered over. Nothing else stands in for the channel.
* A site that is Off or in a dry run has nothing to send (a dry run never reaches a channel and Off makes no Delivery), so it gets no runner and needs no Broadcaster.

``send_due`` is the announce agent's step after it has decided: every X Delivery whose time has come goes through the runner. A Delivery that may not go yet (its release or lock time, an edit window) is left
for its own timer's wake (``delivery_timers``), and one X is not ready for (``x_runner.NotSendable``) is left as it is.
"""
from __future__ import annotations

from typing import Any

from . import budget as budget_module
from .channel import Broadcaster, ChannelNotAvailable
from .deliveries import Deliveries
from .rules import ON
from .withdrawals import Withdrawals
from .x_channel import XChannel
from .x_runner import SpendControl, XRunner


def x_runner(deliveries: Deliveries, announcements: Any, control: SpendControl, broadcaster: Broadcaster | None, *, by: str = "deliver") -> XRunner | None:
    settings = control.current()
    if broadcaster is None:
        if settings["mode"] == ON:
            raise ChannelNotAvailable("Announcements are turned on, but this site has no Caducus x channel wired (the notifications function's X queue), so nothing can be posted.")
        return None

    def budget_wait_until() -> str | None:
        day = settings.get("billingCycleDay")
        if day is None:
            return None
        return budget_module.next_cycle_start(budget_module.cycle_start(control.now(), int(day)), int(day)).isoformat() + "T00:00:00Z"

    channel = XChannel(broadcaster, budget_wait_until=budget_wait_until)
    return XRunner(deliveries, Withdrawals(deliveries, announcements, removers=lambda row: channel), channel, control, by=by)


def send_due(deliveries: Deliveries, announcements: Any, control: SpendControl, broadcaster: Broadcaster | None, now: str | None = None) -> list[dict[str, Any]]:
    """Send the X Deliveries that are due. Returns each Delivery as written; empty when X is off."""
    runner = x_runner(deliveries, announcements, control, broadcaster)
    return runner.send_due(now) if runner is not None else []
