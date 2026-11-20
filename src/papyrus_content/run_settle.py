"""Settling an interrupted run: Outcome unknown is a state, not a guess (PPY-2d2e55, slice A3).

The wake queue gives the runner a message at most twice by design: once to run it and once to settle it. The queue's second delivery means the first
attempt did not finish, because a message is hidden for the whole run and only becomes visible again when the attempt died. On that second delivery the
runner reads the wake's run record. A record still `started` with no outcome is a run that died.

* The agent's definition says `safeToRepeat` (every write it makes is keyed): the run is run once more under the same key and ends with its own outcome.
* The definition does not say so, or the wake carries no definition: the run is recorded `unknown` and joins the attention list, which is the one flag a
  person sees on Today, and the message is deleted. Nothing is run twice for one wake.
* A third delivery can only mean that settling itself crashed: the queue moves the message to the dead-letter queue and its alarm fires.

No timeout and no retry count decides anything here; the receipt count is the queue's own report of which delivery this is.
"""
from __future__ import annotations

from typing import Any, Callable

from . import run_outcomes
from .cloud_procedures import update_cloud_procedure_run_record

RUN_MODEL = "ProcedureRun"
STARTED = "started"
SETTLING_RECEIPT = 2
REPEAT_ATTEMPT = 2
INTERRUPTED = "interrupted"
INTERRUPTED_SUMMARY = (
    "The first attempt started and recorded no result. This procedure is not marked safe to repeat, so it was not run again; "
    "whatever it wrote before it stopped is unchecked."
)
MAX_SUMMARY_CHARACTERS = 500


def first_attempt_died(existing_run: dict[str, Any] | None, receive_count: int) -> bool:
    return receive_count >= SETTLING_RECEIPT and bool(existing_run) and existing_run.get("runStatus") == STARTED and not existing_run.get("outcome")


def safe_to_repeat(request: dict[str, Any]) -> bool:
    trigger = request.get("trigger") if isinstance(request.get("trigger"), dict) else {}
    return trigger.get("safeToRepeat") is True


def record_unknown(client, run_id: str, existing_run: dict[str, Any], request: dict[str, Any], *, now: Callable[[], str]) -> dict[str, Any]:
    stamp, trigger = now(), request.get("trigger") or {}
    update_cloud_procedure_run_record(client, {
        "id": run_id, "runStatus": "failed", "outcome": "unknown", "outcomeReason": INTERRUPTED,
        "automationId": trigger.get("automationId"), **run_outcomes.run_subject(trigger),
        "startedAt": existing_run.get("startedAt") or stamp, "finishedAt": stamp, "errorSummary": INTERRUPTED_SUMMARY[:MAX_SUMMARY_CHARACTERS],
        "error": {"message": INTERRUPTED_SUMMARY}, "attempt": 1})
    return {"runId": run_id, "procedureKey": request["procedureKey"], "wakeKey": request["wakeKey"], "settled": True,
            "runStatus": "failed", "outcome": "unknown", "outcomeReason": INTERRUPTED, "error": INTERRUPTED_SUMMARY}
