"""Which rung applies, and whether a run may start (PPY-51ea61).

Pure functions over a ``PolicyState``; they read nothing and write nothing, so a run's start and its record are one decision.

* An unnamed responsibility is at ``off``. A new agent is quiet until a person names it.
* The agent's own entry gives its rung; an override that matches the call replaces it. The narrowest matching override wins:
  the one that names the earliest dimension of ``SCOPE_DIMENSIONS`` (list, then channel, kind, story type, section) the other
  does not, so a scope that adds a dimension to another's is narrower than it. Two overrides cannot share a scope (the validator
  refuses it), so the answer never depends on the order they are written in.
* A pause, on the site or on the agent, starts nothing and says why. ``off`` starts nothing. Nothing is queued for later:
  a tick that was skipped is gone, so resuming never replays it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .document import RUNGS, SCOPE_DIMENSIONS, scope_of


@dataclass(frozen=True)
class PolicyState:
    """A document and the version it is. Version 0 is a site that has never saved one: every agent is at ``off``."""
    version: int
    document: dict[str, Any]


@dataclass(frozen=True)
class Effective:
    responsibility: str
    rung: str
    source: str                      # "default" (not named), "agent" (the agent's own rung) or "override"
    override: dict | None
    policy_version: int


@dataclass(frozen=True)
class StartDecision:
    start: bool
    rung: str
    policy_version: int
    source: str
    reason: str | None = None       # why nothing starts; None when it does

    def run_fields(self) -> dict[str, Any]:
        """What the run record carries, started or skipped: the version of the policy and the rung it ran under."""
        return {"policyVersion": self.policy_version, "rung": self.rung}


def _rank(scope: Mapping[str, str]) -> tuple[bool, ...]:
    return tuple(dimension in scope for dimension in SCOPE_DIMENSIONS)


def effective(state: PolicyState, responsibility: str, context: Mapping[str, str] | None = None) -> Effective:
    context = context or {}
    entry = state.document.get("agents", {}).get(responsibility)
    if entry is None:
        return Effective(responsibility, RUNGS[0], "default", None, state.version)
    matching = [o for o in entry.get("overrides", []) if all(context.get(dimension) == value for dimension, value in scope_of(o).items())]
    if matching:
        winner = max(matching, key=lambda override: _rank(scope_of(override)))
        return Effective(responsibility, winner["rung"], "override", winner, state.version)
    return Effective(responsibility, entry["rung"], "agent", None, state.version)


def decide_start(state: PolicyState, responsibility: str, context: Mapping[str, str] | None = None) -> StartDecision:
    """May a run of ``responsibility`` start on this wake? Always answers, and the answer names the policy version and rung."""
    found = effective(state, responsibility, context)
    site, entry = state.document.get("site", {}), state.document.get("agents", {}).get(responsibility, {})
    if site.get("paused"):
        reason = f"The site is paused: {site['pausedReason']}"
    elif entry.get("paused"):
        reason = f"{responsibility} is paused: {entry['pausedReason']}"
    elif found.rung == "off":
        reason = f"{responsibility} is off"
    else:
        reason = None
    return StartDecision(reason is None, found.rung, found.policy_version, found.source, reason)
