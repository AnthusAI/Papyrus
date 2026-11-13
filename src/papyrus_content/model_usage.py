"""Model calls a procedure's Python tools make themselves, reported to the run that made them (PPY-843a7c).

Tactus reports every call its agents make; a tool that calls a model from Python (the translation procedure's translate, judge and refine
calls) reports each call here, in the same shape (``agent``, ``model``, ``provider``, ``promptTokens``, ``completionTokens``, ``cachedTokens``).
``procedure_runner_child`` adds them to the run's usage, so the run's estimated cost (``model_cost``) counts every call, whoever made it.
"""
from __future__ import annotations

from typing import Any

_CALLS: list[dict[str, Any]] = []


def record(call: dict[str, Any]) -> None:
    _CALLS.append(dict(call))


def drain() -> list[dict[str, Any]]:
    """Every call recorded since the last drain, in order; the list is then empty."""
    calls = list(_CALLS)
    _CALLS.clear()
    return calls
