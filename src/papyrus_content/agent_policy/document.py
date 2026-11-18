"""What the agent policy document may hold, and the one validator every write goes through.

::

    {"schemaVersion": 1,
     "site":   {"paused": false, "pausedReason": "...", "quietWindow": {"start": "22:00", "end": "06:00", "timeZone": "America/New_York"},
                "budget": {"amountUsd": 25, "period": "week"}, "tiers": {"editorial": "<model>", "work": "<model>", "bulk": "<model>"}},
     "agents": {"improve": {"rung": "prepare", "paused": false, "loopLimit": 3,
                            "overrides": [{"storyType": "post", "rung": "publish_soft"}]}}}

A responsibility with no entry is at ``off``: a new agent arrives quiet, and a deploy never writes this document. The budget, the quiet
window, the loop limit and the tiers are held here for the tasks that read them; nothing in this package invents a value for them.
"""
from __future__ import annotations

import copy
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re

from papyrus_content.agent_rungs import RUNGS  # noqa: E402  (the ladder; re-exported here for the policy package)

#: The ways an override can narrow a rung, narrowest first: a list is narrower than an Announcement kind, a kind than a channel, a channel than a Story type, a Story type
#: than a section (the publication's own rung is the widest). When two overrides match one call the one whose scope names the earlier dimension (and then more of
#: them) wins; see ``resolve.effective``. Changed by PPY-97c0f2: kind used to rank below channel, which made "roundups hard" lose to "LinkedIn soft".
SCOPE_DIMENSIONS = ("list", "kind", "channel", "storyType", "section")

TIERS = ("editorial", "work", "bulk", "decision")
BUDGET_PERIODS = ("day", "week", "month")
SCHEMA_VERSION = 1

_RESPONSIBILITY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

EMPTY_DOCUMENT: dict[str, Any] = {"schemaVersion": SCHEMA_VERSION, "site": {}, "agents": {}}


class PolicyError(Exception):
    """A refusal. ``code`` is one of ``invalid_input``, ``not_authorized`` (an editor), ``blocked`` (an agent), ``stale_version`` or ``constraint_conflict`` (a rung above the definition's ceiling, or one a hard floor forbids)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _invalid(message: str) -> PolicyError:
    return PolicyError("invalid_input", message)


def _only(value: Any, allowed: set[str], where: str) -> dict:
    if not isinstance(value, dict):
        raise _invalid(f"{where} must be an object.")
    extra = sorted(set(value) - allowed)
    if extra:
        raise _invalid(f"{where} has unknown field(s): {', '.join(extra)}.")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{where} must be a non-empty string.")
    return value


def _flag(entry: dict, where: str) -> None:
    paused = entry.get("paused", False)
    if not isinstance(paused, bool):
        raise _invalid(f"{where}.paused must be true or false.")
    if paused:
        _text(entry.get("pausedReason"), f"{where}.pausedReason (a pause says why)")
    elif "pausedReason" in entry:
        raise _invalid(f"{where}.pausedReason is only held while paused.")


def check_rung(value: Any, where: str) -> str:
    if value not in RUNGS:
        raise _invalid(f"{where} must be one of: {', '.join(RUNGS)}.")
    return value


def scope_of(override: dict) -> dict[str, str]:
    return {dimension: override[dimension] for dimension in SCOPE_DIMENSIONS if dimension in override}


def check_scope(scope: Any, where: str) -> dict[str, str]:
    scope = _only(scope, set(SCOPE_DIMENSIONS), where)
    if not scope:
        raise _invalid(f"{where} must name at least one of: {', '.join(SCOPE_DIMENSIONS)}.")
    return {dimension: _text(value, f"{where}.{dimension}") for dimension, value in scope.items()}


def _quiet_window(value: Any) -> None:
    window = _only(value, {"start", "end", "timeZone"}, "site.quietWindow")
    for field in ("start", "end"):
        if not _CLOCK.match(str(window.get(field, ""))):
            raise _invalid(f"site.quietWindow.{field} must be a time as HH:MM.")
    try:
        ZoneInfo(_text(window.get("timeZone"), "site.quietWindow.timeZone"))
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise _invalid("site.quietWindow.timeZone must be a time zone name such as America/New_York.") from error


def _budget(value: Any) -> None:
    budget = _only(value, {"amountUsd", "period"}, "site.budget")
    amount = budget.get("amountUsd")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0:
        raise _invalid("site.budget.amountUsd must be a number from 0.")
    if budget.get("period") not in BUDGET_PERIODS:
        raise _invalid(f"site.budget.period must be one of: {', '.join(BUDGET_PERIODS)}.")


def validate_site(site: Any) -> None:
    site = _only(site, {"paused", "pausedReason", "quietWindow", "budget", "tiers"}, "site")
    _flag(site, "site")
    if "quietWindow" in site:
        _quiet_window(site["quietWindow"])
    if "budget" in site:
        _budget(site["budget"])
    if "tiers" in site:
        tiers = _only(site["tiers"], set(TIERS), "site.tiers")
        for tier, model in tiers.items():
            _text(model, f"site.tiers.{tier}")


def validate_agent(responsibility: str, entry: Any) -> None:
    where = f"agents.{responsibility}"
    if not _RESPONSIBILITY.match(responsibility):
        raise _invalid(f"{where}: a responsibility is lower-case words joined by underscores.")
    entry = _only(entry, {"rung", "paused", "pausedReason", "loopLimit", "overrides"}, where)
    check_rung(entry.get("rung"), f"{where}.rung")
    _flag(entry, where)
    if "loopLimit" in entry:
        limit = entry["loopLimit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise _invalid(f"{where}.loopLimit must be a whole number from 1.")
    overrides = entry.get("overrides", [])
    if not isinstance(overrides, list):
        raise _invalid(f"{where}.overrides must be a list.")
    seen: list[dict] = []
    for position, override in enumerate(overrides):
        here = f"{where}.overrides[{position}]"
        override = _only(override, {*SCOPE_DIMENSIONS, "rung"}, here)
        check_rung(override.get("rung"), f"{here}.rung")
        scope = check_scope({key: value for key, value in override.items() if key != "rung"}, here)
        if scope in seen:
            raise _invalid(f"{here} repeats a scope another override already names; the scope must be unique.")
        seen.append(scope)


def validate_document(document: Any) -> dict:
    """Return ``document`` when it is a valid policy; raise ``PolicyError`` (``invalid_input``) naming the field when it is not."""
    document = _only(document, {"schemaVersion", "site", "agents"}, "The policy document")
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise _invalid(f"schemaVersion must be {SCHEMA_VERSION}.")
    validate_site(document.get("site", {}))
    agents = document.get("agents", {})
    if not isinstance(agents, dict):
        raise _invalid("agents must be an object keyed by responsibility.")
    for responsibility, entry in agents.items():
        validate_agent(responsibility, entry)
    return document


def fresh() -> dict[str, Any]:
    return copy.deepcopy(EMPTY_DOCUMENT)
