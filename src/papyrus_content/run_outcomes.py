"""The five outcomes of a finished run, and how a run is shown with its outcome (PPY-f58445, slice A1).

A ProcedureRun keeps two facts apart. `runStatus` is the mechanics (queued, running, completed, failed). `outcome` is what
came of the run, set only when the run finishes:

* `acted`   it did the work (it changed records);
* `nothing` it looked and there was nothing to do; a reason code says why; this is not a failure;
* `asked`   it raised a review request for a person and stopped;
* `failed`  it could not do the work, and nothing half-done is left looking done;
* `unknown` it started and no result was recorded. Only settling an interrupted run sets it (slice A3); nothing here does.

A procedure says `nothing` or `asked` by returning `run_outcome` and `run_outcome_reason` in its output. A procedure that
returns neither did its work. See docs/design/always-on-agents-architecture.md section 3.2.
"""
from __future__ import annotations

import re
from typing import Any

# Outcome -> (mark, words). The mark never carries the meaning alone: the words are always shown with it.
OUTCOME_SHOWN: dict[str, tuple[str, str]] = {
    "acted": ("✓", "Did it"),
    "nothing": ("–", "Nothing to do"),
    "asked": ("?", "Asked"),
    "failed": ("✗", "Failed"),
    "unknown": ("!", "Outcome unknown"),
}
OUTCOMES = tuple(OUTCOME_SHOWN)
# What a procedure may declare for itself. `failed` is the runner's judgement and `unknown` is only ever a settling.
DECLARABLE = ("acted", "nothing", "asked")
OUTCOME_KEY, REASON_KEY = "run_outcome", "run_outcome_reason"
REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

BEFORE_OUTCOMES = "Recorded before outcomes"
NOT_FINISHED = "Not finished yet"
NO_RUN_RECORD = "No run record"
FINISHED_STATUSES = ("completed", "failed")

PROCEDURE_ERROR, TIMED_OUT, INVALID_OUTCOME, NOT_RUNNABLE = "procedure_error", "timed_out", "invalid_outcome", "not_runnable"


class InvalidOutcome(ValueError):
    """A procedure declared an outcome the vocabulary does not allow."""


def declared_outcome(output: Any) -> tuple[str, str | None]:
    """The outcome and reason a finished procedure's output declares. No declaration means it did its work (`acted`).
    Raises InvalidOutcome for a value outside the vocabulary, a `nothing` or `asked` without a reason, or a malformed reason."""
    if not isinstance(output, dict) or (OUTCOME_KEY not in output and REASON_KEY not in output):
        return "acted", None
    outcome, reason = output.get(OUTCOME_KEY, "acted"), output.get(REASON_KEY)
    if outcome not in DECLARABLE:
        raise InvalidOutcome(f"{OUTCOME_KEY} must be one of {', '.join(DECLARABLE)}, not {outcome!r}")
    if reason is not None and not (isinstance(reason, str) and REASON_CODE.match(reason)):
        raise InvalidOutcome(f"{REASON_KEY} must be a short lower-case code such as no_new_filing")
    if outcome in ("nothing", "asked") and reason is None:
        what = "a nothing-to-do outcome" if outcome == "nothing" else "an asked outcome"
        raise InvalidOutcome(f"{what} needs a reason: set {REASON_KEY}")
    return outcome, reason


def finished_outcome(succeeded: bool, output: Any, error: str | None) -> dict[str, Any]:
    """How a finished run ends: runStatus, outcome, outcomeReason and the error text (None unless it failed)."""
    if succeeded:
        try:
            outcome, reason = declared_outcome(output)
            return {"runStatus": "completed", "outcome": outcome, "outcomeReason": reason, "error": None}
        except InvalidOutcome as invalid:
            return {"runStatus": "failed", "outcome": "failed", "outcomeReason": INVALID_OUTCOME, "error": str(invalid)}
    message = str(error or "failed")
    return {"runStatus": "failed", "outcome": "failed", "outcomeReason": TIMED_OUT if message.startswith("timed out") else PROCEDURE_ERROR,
            "error": message}


def run_subject(trigger: dict | None) -> dict[str, str | None]:
    """What a run was started for, from the trigger that started it: a story at a version (a story entering a stage), a Reference
    (a monitor's new item), or nothing (Run now)."""
    trigger = trigger or {}
    if trigger.get("story"):
        return {"subjectKind": "Story", "subjectId": str(trigger["story"]), "subjectVersion": str(trigger["version"]) if trigger.get("version") else None}
    if trigger.get("referenceId"):
        return {"subjectKind": "Reference", "subjectId": str(trigger["referenceId"]), "subjectVersion": None}
    return {"subjectKind": None, "subjectId": None, "subjectVersion": None}


def outcome_text(outcome: str, reason: str | None = None) -> str:
    if outcome not in OUTCOME_SHOWN:
        return f"Unrecognised outcome ({outcome})"
    mark, words = OUTCOME_SHOWN[outcome]
    return f"{mark} {words}" + (f" ({reason})" if reason else "")


def outcome_shown(run: dict | None, row: dict | None = None) -> str:
    """The words and mark for one run in a list. `run` is its ProcedureRun, `row` the trigger row that named it (a run the runner
    refused has an outcome on its row and no run record)."""
    source = run if run is not None else (row or {})
    outcome = source.get("outcome")
    if outcome:
        return outcome_text(str(outcome), source.get("outcomeReason"))
    if run is None:
        return NO_RUN_RECORD
    return BEFORE_OUTCOMES if run.get("runStatus") in FINISHED_STATUSES else NOT_FINISHED
