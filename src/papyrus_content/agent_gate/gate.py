"""The one gate every agent write passes through (design: docs/design/always-on-agents-architecture.md section 5.4).

``decide`` is a pure function of the operation table, the site's agent policy and who is asking, so the answer to one call is the same everywhere
the table is used (the CLI, the MCP tools and the newsroom). It answers one of three words:

* ``allowed``: it happens.
* ``blocked``: this agent may not, at any rung or now. Either the table says no agent ever may (change policy, budget or accounts), or the agent is
  ``off`` or paused, or the operation is not in the table (the gate fails closed).
* ``human_required``: a person must do it or approve it: the table needs a higher rung than the policy gives this responsibility here, or the table
  says only a person may and names ``human_required`` as the answer. The engine raises one review request and the run ends ``asked``.

A person's own action is never limited by an agent's rung: the gate answers ``allowed`` without reading the policy. What a person may do is
the door's permission check, not this gate. The rung an operation needs is ``Operation.agent_rung``, the only place it is written; raising a
site's rung in the policy document allows the same call with no code change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from papyrus_content.agent_policy.resolve import PolicyState, decide_start, effective
from papyrus_content.agent_rungs import RUNGS
from papyrus_content.images.operations import operation as operation_named

ALLOWED, BLOCKED, HUMAN_REQUIRED = "allowed", "blocked", "human_required"
ANSWERS = (ALLOWED, BLOCKED, HUMAN_REQUIRED)


@dataclass(frozen=True)
class GateAnswer:
    answer: str
    operation: str
    actor_kind: str
    reason: str
    responsibility: str | None = None
    rung: str | None = None            # the rung the policy gives this responsibility for this call; None for a person
    needed_rung: str | None = None     # the lowest rung the operation table allows an agent to call it at; None when none does
    policy_version: int | None = None

    @property
    def allowed(self) -> bool:
        return self.answer == ALLOWED

    def as_record(self) -> dict[str, Any]:
        """The answer as it is written on the run record."""
        return {key: value for key, value in {
            "answer": self.answer, "operation": self.operation, "actorKind": self.actor_kind, "reason": self.reason, "responsibility": self.responsibility,
            "rung": self.rung, "neededRung": self.needed_rung, "policyVersion": self.policy_version}.items() if value is not None}


def decide(policy: PolicyState | None, actor_kind: str, operation: str, responsibility: str | None = None,
           context: Mapping[str, str] | None = None) -> GateAnswer:
    """Answer one call. ``policy`` is the site's agent policy as read once for the run; an agent's call needs it and a person's does not."""
    if actor_kind != "agent":
        return GateAnswer(ALLOWED, operation, actor_kind, "A person's own action is not limited by an agent's rung.")
    found = operation_named(operation)
    if found is None:
        return GateAnswer(BLOCKED, operation, actor_kind, f"{operation} is not in the operation table, so no agent may call it.", responsibility)
    if not found.agent_allowed:
        words = "only a person may do it" if found.agent_refusal == HUMAN_REQUIRED else "no agent may ever do it"
        return GateAnswer(found.agent_refusal, operation, actor_kind, f"{operation}: {words}, at every rung.", responsibility)
    if policy is None or not responsibility:
        return GateAnswer(BLOCKED, operation, actor_kind, f"{operation} was asked without the run's policy and responsibility, so the gate cannot say what rung applies.",
                          responsibility, needed_rung=found.agent_rung)
    start = decide_start(policy, responsibility, context)
    if not start.start:
        return GateAnswer(BLOCKED, operation, actor_kind, str(start.reason), responsibility, start.rung, found.agent_rung, start.policy_version)
    rung = effective(policy, responsibility, context).rung
    if RUNGS.index(rung) < RUNGS.index(found.agent_rung):
        return GateAnswer(HUMAN_REQUIRED, operation, actor_kind,
                          f"{operation} needs the rung {found.agent_rung}; {responsibility} is at {rung}, so a person must do it or approve it.",
                          responsibility, rung, found.agent_rung, policy.version)
    return GateAnswer(ALLOWED, operation, actor_kind, f"{responsibility} is at {rung}, which allows {operation} from {found.agent_rung}.",
                      responsibility, rung, found.agent_rung, policy.version)


class GateRun:
    """One agent run's side of the gate: the policy read once, every answer kept for the run record, and the one review request a ``human_required`` raises."""

    def __init__(self, policy: PolicyState, responsibility: str, run_id: str, context: Mapping[str, str] | None = None):
        self.policy, self.responsibility, self.run_id, self.context = policy, responsibility, run_id, dict(context or {})
        self.answers: list[GateAnswer] = []

    def ask(self, operation: str, context: Mapping[str, str] | None = None) -> GateAnswer:
        answer = decide(self.policy, "agent", operation, self.responsibility, {**self.context, **(context or {})})
        self.answers.append(answer)
        return answer

    @property
    def review_request(self) -> dict[str, Any] | None:
        """The one review request this run raises, naming each operation a person must do or approve; None when nothing needs a person."""
        needed = [answer for answer in self.answers if answer.answer == HUMAN_REQUIRED]
        if not needed:
            return None
        first = needed[0]
        return {"kind": "agent_gate", "runId": self.run_id, "responsibility": self.responsibility, "policyVersion": self.policy.version,
                "operations": [answer.operation for answer in needed], "reason": first.reason}

    def outcome(self) -> dict[str, str] | None:
        """What the run's output declares when the gate asked for a person: the run ends ``asked`` (run_outcomes.py). None otherwise."""
        return {"run_outcome": "asked", "run_outcome_reason": "human_required"} if self.review_request else None

    def record(self) -> dict[str, Any]:
        """What the run record carries: the policy version, and every gate answer in the order they were given."""
        return {"policyVersion": self.policy.version, "gate": [answer.as_record() for answer in self.answers]}
