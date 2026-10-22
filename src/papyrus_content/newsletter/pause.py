"""The site-wide sending pause: set by the bounce and complaint alarms, cleared by an admin. ``is_paused()`` is for the sender."""

from __future__ import annotations

from typing import Any

from . import records
from .store import Store, iso
from .suppression import default_store


def is_paused(store: Store | None = None) -> bool:
    return bool(records.get_state(store or default_store()).get("paused"))


def pause_site(store: Store, mailer: Any, reason: str, now: float) -> bool:
    """Turn sending off at SES for the site's configuration set and record why. False when it was already paused."""
    state = records.get_state(store)
    if state.get("paused"):
        return False
    mailer.set_sending_enabled(False)
    records.put_state(store, {"paused": True, "reason": reason[:300], "pausedAt": iso(now)})
    return True


def resume_site(store: Store, mailer: Any, now: float) -> None:
    mailer.set_sending_enabled(True)
    records.put_state(store, {"paused": False, "resumedAt": iso(now)})
