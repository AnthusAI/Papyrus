"""The announcement settings every site has: mode, pause, rules, budget and the price table.

Stored as one JSON document (the ``AnnouncementSettings`` model, id ``settings``), like the editorial check settings.
Only the ``announcements`` function writes it, so every rule below is enforced on the server. Nothing is announced until
the owner turns the mode on.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .x_account import CONNECTED, AnnouncementError, utc_iso

MODES = ("off", "dry_run", "on")
STORY_TYPES = ("article", "post")
PAUSE_REASONS = ("budget", "disconnected", "manual")
# The site's quality floor: nothing below three stars is public or announced (the 3-star decision, PPY-0e8d66).
QUALITY_FLOOR_STARS = 3
MAX_STARS = 5
# X's price list as read from docs.x.com/x-api/getting-started/pricing on the date below. The owner edits it when X changes it.
DEFAULT_PRICES = {"createPost": 0.015, "createPostWithUrl": 0.2, "deletePost": 0.01, "readPost": 0.005, "asOf": "2026-11-12"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "mode": "off",
    "pause": {"paused": False, "reason": None, "detail": None, "by": None, "at": None},
    "rules": {"minStars": MAX_STARS, "storyTypes": list(STORY_TYPES), "sections": []},
    "budget": None,
    "prices": DEFAULT_PRICES,
    "labelConfirmed": False,
}


def with_defaults(stored: dict[str, Any] | None) -> dict[str, Any]:
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    for key, value in (stored or {}).items():
        settings[key] = value
    return settings


def _fail(code: str, message: str) -> AnnouncementError:
    return AnnouncementError(code, message)


def validate(proposed: dict[str, Any], connection_status: str) -> dict[str, Any]:
    """The owner's choices checked against the rules; returns the settings to store, or raises with a plain sentence."""
    mode = proposed.get("mode")
    if mode not in MODES:
        raise _fail("mode_invalid", "Choose Off, Dry run or On.")
    rules = proposed.get("rules") or {}
    stars = rules.get("minStars")
    if not isinstance(stars, int) or isinstance(stars, bool):
        raise _fail("stars_invalid", "Choose a minimum star rating.")
    if stars < QUALITY_FLOOR_STARS:
        raise _fail("below_quality_floor", f"Announcements can't go below your quality floor of {QUALITY_FLOOR_STARS} stars.")
    if stars > MAX_STARS:
        raise _fail("stars_invalid", f"Star ratings stop at {MAX_STARS}.")
    types = rules.get("storyTypes")
    if not isinstance(types, list) or not types or any(item not in STORY_TYPES for item in types):
        raise _fail("types_invalid", "Choose at least one kind of Story to announce (Articles or Posts). References are never announced.")
    sections = rules.get("sections", [])
    if not isinstance(sections, list) or any(not isinstance(item, str) or not item for item in sections):
        raise _fail("sections_invalid", "Sections must be a list of section names.")
    budget = proposed.get("budget")
    if budget is not None and (isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget < 0):
        raise _fail("budget_invalid", "The budget is an amount of money, zero or more, per X billing cycle.")
    prices = proposed.get("prices") or {}
    for name in ("createPost", "createPostWithUrl", "deletePost", "readPost"):
        price = prices.get(name)
        if isinstance(price, bool) or not isinstance(price, (int, float)) or price < 0:
            raise _fail("price_invalid", "Each price is an amount of money, zero or more.")
    if not isinstance(prices.get("asOf"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", prices["asOf"]):
        raise _fail("price_date_invalid", "Give the date you copied the prices from X, as year-month-day.")
    label = bool(proposed.get("labelConfirmed"))
    if mode in ("dry_run", "on") and connection_status != CONNECTED:
        raise _fail("account_needed", "Connect an X account before choosing Dry run or On.")
    if mode == "on":
        if not label:
            raise _fail("label_unconfirmed", "Confirm that the account shows X's Automated label before turning announcements on.")
        if not budget:
            raise _fail("budget_needed", "Enter a budget per X billing cycle before turning announcements on.")
    return {
        "mode": mode,
        "rules": {"minStars": stars, "storyTypes": list(types), "sections": list(sections)},
        "budget": budget,
        "prices": {name: prices[name] for name in ("createPost", "createPostWithUrl", "deletePost", "readPost", "asOf")},
        "labelConfirmed": label,
    }


class AnnouncementSettings:
    """The settings document plus the pause switch. ``store`` has ``get()`` and ``put(dict)``."""

    def __init__(self, store: Any, clock: Any) -> None:
        self.store = store
        self.clock = clock

    def read(self) -> dict[str, Any]:
        return with_defaults(self.store.get())

    def save(self, proposed: dict[str, Any], connection_status: str) -> dict[str, Any]:
        current = self.read()
        checked = validate({**current, **proposed}, connection_status)
        updated = {**current, **checked}
        self.store.put(updated)
        return updated

    def pause(self, reason: str, detail: str, by: str, at: str) -> None:
        if reason not in PAUSE_REASONS:
            raise _fail("pause_reason_invalid", "A pause has a reason: budget, disconnected or manual.")
        current = self.read()
        self.store.put({**current, "pause": {"paused": True, "reason": reason, "detail": detail, "by": by, "at": at}})

    def resume(self) -> None:
        self.store.put({**self.read(), "pause": copy.deepcopy(DEFAULT_SETTINGS["pause"])})

    def resume_if(self, reason: str) -> None:
        if self.read()["pause"].get("reason") == reason:
            self.resume()

    def manual_pause(self, paused: bool, by: str) -> dict[str, Any]:
        if paused:
            self.pause("manual", "Paused by hand.", by, utc_iso(self.clock()))
        else:
            self.resume()
        return self.read()
