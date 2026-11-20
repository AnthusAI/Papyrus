"""Continuation: a unit of work longer than one run (PPY-c023ab, slice A6 of docs/design/always-on-agents-architecture.md).

A run is a short wake-up and the runner has fifteen minutes. A procedure that cannot finish its unit saves its progress on the records it is changing
(a new draft version, a step's evidence), ends `acted`, and names when the next run should start in its output (`run_next_wake_at`, a UTC instant).
Before the run's record is written the runner sets one follow-up timer for that time. Its wake key is `<owner>|<subject>|<root run id>|c<n>`: the chain's
first run is the root, `n` counts the continuations, and two chains about one subject never share a key. The next run re-reads the records and carries on:
progress never lives in a model's transcript. Each continuation is its own run record with its own cost.

Two hard limits stop a chain that would never end:

* `MAXIMUM_CONTINUATIONS` is how many continuations one chain may have. A run that asks for one more ends `failed` with `continuation_limit_reached`.
* The budget is the policy gate's: a continuation carries its chain's trigger, including `paid`, so it is decided like any paid wake and starts nothing
  once the site's budget is reached.

A run that asks for a continuation that cannot be set (no timer service, or the service refuses) ends `failed` with `continuation_not_scheduled`: it never
looks finished while its work is not. A procedure that neither finishes nor saves progress fails or times out like any other run.
"""
from __future__ import annotations

from typing import Any

from . import follow_up_timers, run_outcomes, wake_keys

NEXT_WAKE_KEY = "run_next_wake_at"
CONTINUATION_KIND = "continuation"
MAXIMUM_CONTINUATIONS = 8
LIMIT_REACHED, NOT_SCHEDULED, INVALID_CONTINUATION = "continuation_limit_reached", "continuation_not_scheduled", "invalid_continuation"
ENTRY_RECORD_KIND = "continuation"


class ContinuationError(ValueError):
    """A continuation that cannot be set, with the reason code the run records."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def requested_time(output: Any) -> str | None:
    """The time the procedure asked for its next run, or None when it did not ask. A time that is not a UTC instant is refused, not repaired."""
    if not isinstance(output, dict) or output.get(NEXT_WAKE_KEY) is None:
        return None
    value = output[NEXT_WAKE_KEY]
    try:
        follow_up_timers.parse_utc(value)
    except follow_up_timers.FollowUpError as invalid:
        raise ContinuationError(INVALID_CONTINUATION, f"{NEXT_WAKE_KEY} must be a UTC instant such as 2026-11-17T09:00:00Z, not {value!r}") from invalid
    return str(value)


def next_request(request: dict[str, Any], run_id: str, due_at: str) -> dict[str, Any]:
    """The runner's request for the chain's next run: this request's procedure, site and input, the same trigger (so the same gate decides it), and its own key."""
    trigger = dict(request.get("trigger") or {})
    number = int(trigger.get("continuation") or 0) + 1
    if number > MAXIMUM_CONTINUATIONS:
        raise ContinuationError(LIMIT_REACHED, f"this chain has already continued {MAXIMUM_CONTINUATIONS} times; a unit of work that needs more is stopped, not extended")
    root = str(trigger.get("continuationRoot") or run_id)
    subject = run_outcomes.run_subject(trigger)["subjectId"] or root
    owner = wake_keys.owner(trigger.get("automationId"), request["procedureKey"])
    following = {name: value for name, value in request.items() if name != "wakeKey"}
    following["wakeKey"] = wake_keys.change_key(owner, subject, root, f"c{number}")
    following["trigger"] = {**trigger, "kind": CONTINUATION_KIND, "continuation": number, "continuationRoot": root, "dueAt": due_at,
                            "summary": f"Continuing {request['procedureKey']} (part {number + 1}) from {due_at}"[:500]}
    return following
