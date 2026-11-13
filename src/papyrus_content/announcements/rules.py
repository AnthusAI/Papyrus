"""The settings as the announcement pipeline reads them: one flat view over the settings document (``settings.py``) and the X connection (``x_account.py``).

``settings.py`` owns the document and every rule about what may be saved; ``x_account.py`` owns the connection and the tokens. This module only reads them together,
so the engine, the budget and the guard never learn the document's nesting, and never keep a second copy of anything.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .x_account import CONNECTED

OFF, DRY_RUN, ON = "off", "dry_run", "on"
MODE_LABELS = {OFF: "Off", DRY_RUN: "Dry run", ON: "On"}
PAUSE_BUDGET = "budget"
SYSTEM = "system"


class SettingsIncomplete(ValueError):
    """The settings lack something announcing needs (named in the message)."""


def money(value: Any) -> Decimal | None:
    """A non-negative amount of US dollars, or None when ``value`` is not one."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).strip().lstrip("$"))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def view(document: Mapping[str, Any], connection: Mapping[str, Any]) -> dict[str, Any]:
    """The flat view: mode, the bar, Story types, sections, the connected account, budget, cycle day, prices and the pause."""
    rules, pause = document.get("rules") or {}, document.get("pause") or {}
    return {
        "mode": document.get("mode", OFF), "minStars": rules.get("minStars"), "storyTypes": rules.get("storyTypes") or [], "sections": rules.get("sections") or [],
        "accountId": connection.get("accountId"), "accountHandle": connection.get("handle"), "connected": connection.get("connection") == CONNECTED,
        "connectionStatus": connection.get("connection"), "budget": document.get("budget"), "billingCycleDay": document.get("billingCycleDay"),
        "prices": document.get("prices") or {}, "labelConfirmed": bool(document.get("labelConfirmed")),
        "paused": bool(pause.get("paused")), "pausedBy": pause.get("by"), "pausedAt": pause.get("at"), "pauseReason": pause.get("detail"), "pauseKind": pause.get("reason"),
    }


def price(settings: Mapping[str, Any], name: str) -> Decimal:
    value = money((settings.get("prices") or {}).get(name))
    if value is None:
        raise SettingsIncomplete(f"The site has no price for {name}.")
    return value


def post_price(settings: Mapping[str, Any]) -> Decimal:
    """Announcements always carry a link, so a post costs the link price."""
    return price(settings, "createPostWithUrl")
