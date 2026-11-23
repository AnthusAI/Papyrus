"""How a run ends when it asked the gate about operations (PPY-c630d3, E2 follow-up).

A procedure that must not write without leave names the operations it wants in its output as ``gate_operations`` and does none of them itself. The
runner, which holds the site's policy as read for the run, asks the one gate (``GateRun``) about each, in order, and settles the run here:

* every answer ``allowed``: the output stands and the run ends as the procedure declared (``acted`` unless it says ``nothing``);
* any ``human_required``: this code files the one review request (a hard gate on the run) and the run ends ``asked`` with the reason
  ``human_required``. The word comes from this path, never from the procedure's own ``run_outcome``;
* any ``blocked`` (and none human required): the run ends ``failed`` with the reason ``gate_blocked``, because it asked for what no agent may do.

Every answer, in order, is stored on the run record under ``output.gate`` (``GateRun.record()``), with the id of the review request filed.
A person's own run has no policy and no responsibility, so there is no gate to ask and nothing is settled.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from papyrus_content import review_requests
from papyrus_content.agent_policy.resolve import PolicyState

from .gate import BLOCKED, GateRun

GATE_OPERATIONS_KEY = "gate_operations"
GATE_BLOCKED, REVIEW_REQUEST_FAILED = "gate_blocked", "review_request_failed"


@dataclass(frozen=True)
class GateSettlement:
    declaration: dict[str, str] | None   # run_outcome and run_outcome_reason the gate sets for the run (asked); None when the run's own word stands
    record: dict[str, Any]               # GateRun.record(): the policy version and every answer, plus the review request's id when one was filed
    blocked: list[str]                   # the operations no agent may do that the run asked for
    error: str | None = None             # the review request could not be filed: the run must not end asked


def review_request_id(run_id: str) -> str:
    """One request per run, so a run settled twice files it once: the run id, folded into the characters a request id allows."""
    return ("gate-" + re.sub(r"[^a-z0-9._-]+", "-", run_id.lower()))[:128]


def operations_asked(output: Any) -> list[str]:
    value = output.get(GATE_OPERATIONS_KEY) if isinstance(output, dict) else None
    return [str(name) for name in value] if isinstance(value, list) else []


def settle(client, state: PolicyState, responsibility: str, run_id: str, output: Any, approvals: Mapping[str, str] | None = None) -> GateSettlement | None:
    """Ask the gate about every operation the run named, file the one review request a person is needed for, and say how the run ends.
    ``approvals`` are what a person approved for this run (``review_answers.ReviewAnswer.approvals``). None when the run named no operation."""
    operations = operations_asked(output)
    if not operations:
        return None
    gate_run = GateRun(state, responsibility, run_id, approvals=approvals)
    for name in operations:
        gate_run.ask(name)
    record = gate_run.record()
    blocked = [answer.operation for answer in gate_run.answers if answer.answer == BLOCKED]
    request = gate_run.review_request
    if request is None:
        return GateSettlement(None, record, blocked)
    try:
        filed = review_requests.raise_review(
            client, subject={"type": "automation_run", "id": run_id}, mode="hard_gate", reason=request["reason"],
            ask=f"Approve or do: {', '.join(request['operations'])}", raised_by=f"agent:{responsibility}", request_id=review_request_id(run_id))
    except Exception as error:
        return GateSettlement(None, record, blocked, f"The review request could not be filed: {type(error).__name__}: {error}")
    return GateSettlement(gate_run.outcome(), {**record, "reviewRequestId": filed["id"]}, blocked)
