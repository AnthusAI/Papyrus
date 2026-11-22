"""At the budget, paid work waits and says so (PPY-9376f8, slice G2 of docs/design/always-on-agents-architecture.md).

The spend brake (spend_brake.py) answers, before a run, whether the site's cycle total is at its budget. For a paid wake at the budget this module makes
the stop a wait with a reason and a time, never a loss:

* **Hold.** The wake's run record becomes ``waiting`` with ``waitingFor: budget cycle``, ``dueAt`` at the next cycle start, and the wake itself (the runner's
  request) on the record, because the run record is the wake ledger. One follow-up timer per site and cycle (follow_up_timers.py) is due at that start; its
  message is the latest wake that waited. One flag per cycle tells the admins: a ReviewRequest whose id names the cycle, so raising it again changes nothing.
* **Release.** The site's waiting runs are read from the run status index (``runStatus`` ``waiting``, oldest request first) and each wake is put on the
  queue again, marked as released, in that order. Its run record is the one it already has: the runner finds it waiting and runs it under its own key.
  The cycle's timer releases them when the cycle turns; raising the budget (``papyrus agents set-budget``) releases them at once.
* **Resume.** A released wake re-checks everything when it arrives: the policy, the halt and the budget. Under the budget it runs; at the budget it waits
  again, for the next cycle. Wakes of one agent and scope share a message group, so a wake sent twice runs once: the second finds its record no longer waiting.

Free work (a definition with ``paid: false``) never reads the budget. Reading, editing and serving never pass through the runner, so nothing here stops them.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from . import run_outcomes
from .tenancy import rows_for_tenant

WAITING = "waiting"
WAITING_FOR = "budget cycle"
RELEASED_FROM, RELEASED_AT = "releasedFrom", "releasedAt"   # the trigger fields of a released wake
TIMER_RECORD_KIND = "budget-cycle"
WAITING_INDEX = "procedureRunsWaiting"
RUN_MODEL = "ProcedureRun"
FLAG_RAISED_BY = "AI budget"
MAX_SUMMARY_CHARACTERS = 500

UPDATE_WAITING_RUN_MUTATION = """
  mutation UpdateWaitingProcedureRun($input: UpdateProcedureRunInput!) {
    updateProcedureRun(input: $input) { id runStatus waitingFor dueAt }
  }
"""


def is_waiting(run: Mapping[str, Any] | None) -> bool:
    """The run record of a wake that waits for the budget cycle. Only the spend stop writes a run as ``waiting``."""
    return bool(run) and run.get("runStatus") == WAITING


def is_released(request: Mapping[str, Any]) -> bool:
    trigger = request.get("trigger") if isinstance(request.get("trigger"), dict) else {}
    return trigger.get(RELEASED_FROM) == WAITING_FOR


def original_wake(request: Mapping[str, Any]) -> dict[str, Any]:
    """The wake as it first arrived: without the marks a release or the cycle's timer added to its trigger."""
    trigger = {name: value for name, value in (request.get("trigger") or {}).items() if name not in (RELEASED_FROM, RELEASED_AT, "waitingFor", "dueAt")}
    return {**dict(request), "trigger": trigger}


def flag_id(period: str, cycle_start: Any) -> str:
    return f"rr-budget-{period}-{cycle_start.isoformat()}"


def timer_record_id(tenant_id: str, due_at: str) -> str:
    return f"{tenant_id}|{due_at}"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _update(client, fields: dict[str, Any]) -> None:
    client.graphql(UPDATE_WAITING_RUN_MUTATION, {"input": fields})


def clear_wait(client, run_id: str) -> None:
    """The waiting record goes back to ``started`` as its wake runs (or is skipped by the policy): no reason, no due time and no wake left on it, so a run
    that dies from here is settled like any other (run_settle.py) and is never run again because it still looked waiting."""
    _update(client, {"id": run_id, "runStatus": "started", "waitingFor": None, "dueAt": None, "wake": None})


def raise_cycle_flag(client, stop: Any) -> dict[str, Any]:
    """The one flag of this cycle: raised by the first wake that waits, and returned unchanged to every later one."""
    from .review_requests import raise_review

    return raise_review(
        client, subject={"type": "batch", "id": f"budget-{stop.period}-{stop.cycle_start.isoformat()}"}, mode="flag", raised_by=FLAG_RAISED_BY,
        reason=f"{stop.reason} Free checks, reading, editing and serving continue.",
        ask=f"Nothing is lost: the waiting agent work runs at {stop.due_at}, in the order it arrived. To run it now, raise the budget with "
            "papyrus agents set-budget (admins only).",
        request_id=flag_id(stop.period, stop.cycle_start))


def waiting_runs(client, tenant_id: str | None) -> list[dict[str, Any]]:
    """The site's runs that wait for the budget cycle, oldest request first: one query of the run status index, never a list of the table."""
    rows = rows_for_tenant(RUN_MODEL, tenant_id, client.list_by_index(WAITING_INDEX, WAITING))
    waiting = [row for row in rows if row.get("waitingFor") == WAITING_FOR]
    return sorted(waiting, key=lambda row: (str(row.get("requestedAt") or ""), str(row.get("id") or "")))


def _wake_of(row: Mapping[str, Any]) -> dict[str, Any] | None:
    wake = row.get("wake")
    if isinstance(wake, str):
        try:
            wake = json.loads(wake)
        except ValueError:
            return None
    return wake if isinstance(wake, dict) and wake.get("wakeKey") else None


def release(client, send: Callable[..., Any], tenant_id: str | None, *, moment: str | None = None) -> dict[str, Any]:
    """Put every waiting wake of the site on its queue again, in the order the wakes arrived, each marked as released. Returns the keys sent and the
    runs that carry no wake to send (which only a run recorded by hand could be)."""
    stamp = moment or _now()
    sent, unreleasable = [], []
    for row in waiting_runs(client, tenant_id):
        wake = _wake_of(row)
        if wake is None:
            unreleasable.append(str(row.get("id")))
            continue
        released = {**wake, "trigger": {**(wake.get("trigger") or {}), RELEASED_FROM: WAITING_FOR, RELEASED_AT: stamp}}
        send(released, deduplication=f"{wake['wakeKey']}|released|{stamp}")
        sent.append(str(wake["wakeKey"]))
    return {"released": sent, "unreleasable": unreleasable, "releasedAt": stamp}


class SpendStop:
    """What the runner does with a paid wake at the budget, and with a waiting wake when it arrives again.

    ``timers(request)`` gives the site's ``FollowUpTimers``; ``send(request, deduplication=...)`` puts a wake on its site's queue (agent_wakes.wake_sender)."""

    def __init__(self, *, timers: Callable[[dict], Any], send: Callable[..., Any], now: Callable[[], str] = _now) -> None:
        self.timers, self.send, self.now = timers, send, now

    is_waiting = staticmethod(is_waiting)
    clear_wait = staticmethod(clear_wait)

    def settle(self, client, run_id: str, request: dict, decision: Any, stop: Any, *, waiting: bool) -> dict[str, Any] | None:
        """After the policy said start: the result to return when this wake waits or released the waiting wakes, or None when the runner goes on (it
        runs, or the brake's other stops skip it as before)."""
        if stop is not None and stop.due_at:
            return self.hold(client, run_id, request, decision, stop)
        if not waiting:
            return None
        if stop is None and not is_released(request):
            return self.release_all(client, run_id, request)
        clear_wait(client, run_id)
        return None

    def hold(self, client, run_id: str, request: dict, decision: Any, stop: Any) -> dict[str, Any]:
        """The wake waits for the next cycle: its record says so (and keeps the wake), the cycle's timer is set, and the cycle's one flag is raised.
        Written in that order, so a failure part way leaves a waiting record that the queue's second delivery holds again."""
        wake, trigger = original_wake(request), request.get("trigger") or {}
        _update(client, {
            "id": run_id, "runStatus": WAITING, "outcome": None, "outcomeReason": None, "automationId": trigger.get("automationId"),
            **run_outcomes.run_subject(trigger), **decision.run_fields(), "resultSummary": stop.reason[:MAX_SUMMARY_CHARACTERS],
            "waitingFor": WAITING_FOR, "dueAt": stop.due_at, "wake": json.dumps(wake, sort_keys=True, default=str)})
        timer_wake = {**wake, "trigger": {**wake["trigger"], "waitingFor": WAITING_FOR, "dueAt": stop.due_at}}
        self.timers(request).wake_again_at(TIMER_RECORD_KIND, timer_record_id(str(request.get("tenantId")), stop.due_at), timer_wake, due_at=stop.due_at)
        flag = raise_cycle_flag(client, stop)
        print(json.dumps({"spendStop": "waiting", "tenantId": request.get("tenantId"), "runId": run_id, "wakeKey": request.get("wakeKey"), "dueAt": stop.due_at}))
        return {"runId": run_id, "procedureKey": request["procedureKey"], "wakeKey": request["wakeKey"], "waiting": True, "runStatus": WAITING,
                "outcome": None, "outcomeReason": None, "waitingFor": WAITING_FOR, "dueAt": stop.due_at, "reason": stop.reason, "flag": flag.get("id"),
                **decision.run_fields(), "responsibility": decision.responsibility, "error": None}

    def release_all(self, client, run_id: str, request: dict) -> dict[str, Any]:
        """The cycle's timer brought this wake and the budget allows paid work again: every waiting wake of the site, this one included, goes on the queue
        in the order they arrived. This delivery runs nothing; its released copy runs in its turn."""
        released = release(client, self.send, request.get("tenantId"), moment=self.now())
        return {"runId": run_id, "procedureKey": request["procedureKey"], "wakeKey": request["wakeKey"], "released": True, "runStatus": WAITING,
                "outcome": None, "outcomeReason": None, **released, "error": None}


def runner_timers(context: Any) -> Callable[[dict], Any]:
    """The site's follow-up timers for a request, with the account and partition taken from the runner's own function ARN."""
    def timers(request: dict) -> Any:
        from .follow_up_timers import FollowUpTimers

        arn_parts = context.invoked_function_arn.split(":")
        return FollowUpTimers.for_site(request["publicationId"], account=arn_parts[4], region=arn_parts[3], partition=arn_parts[1])

    return timers
