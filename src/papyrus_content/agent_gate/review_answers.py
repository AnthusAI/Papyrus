"""A person's answer to the review request a run's gate raised, read by the run it wakes (PPY-ecf852, slice F4 of docs/design/always-on-agents-architecture.md).

When a run ends ``asked`` (``run_end.py``), its review request names the run (subject ``automation_run``) and the agent (``raisedBy agent:<responsibility>``).
Nothing waits for the answer: the run has ended. A person's answer is a change, and the ReviewRequest change feed wakes the agent that asked and no other
(``change_feeds.py``). The wake carries the request's id, not its words, so the runner reads the request again, and the run that asked, and this module says
what the answer means for the run it woke:

* approved: the procedure runs again and re-reads the records. The operations the person approved (the ones the asking run's gate said a person must do or
  approve) are allowed for this run only; the gate records each as allowed with the request that approved it, so no second request is raised.
* rejected: nothing runs. The run ends ``nothing`` with the reason ``review_rejected`` and the person's words as its summary.
* feedback: the procedure runs with the answer in its input (``review``) and nothing is approved. If it still needs a person, it asks again, on its own run.
* already used: the request's ``appliedIn`` names a run, so nothing runs and the run ends ``nothing`` with ``answer_already_applied``. An answer continues the
  work once.

The run that used an answer, by running with it or by stopping for it, is written on the request as ``appliedIn``. A request nobody answers is one open row that
wakes nobody, so it holds up only the work it is about.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from papyrus_content import review_requests

from .gate import HUMAN_REQUIRED

REVIEW_ANSWERED_EVENT = "reviewrequest.answered"
REVIEW_INPUT_KEY = "review"
RUN_MODEL = "ProcedureRun"
APPROVED, REJECTED, FEEDBACK = "approved", "rejected", "feedback"
REVIEW_REJECTED, ANSWER_ALREADY_APPLIED, ANSWER_UNREADABLE = "review_rejected", "answer_already_applied", "answer_unreadable"


class AnswerUnreadable(ValueError):
    """The wake says a review request was answered, and the request, its answer or the run that asked cannot be read as such."""


@dataclass(frozen=True)
class ReviewAnswer:
    request_id: str
    outcome: str                              # approved, rejected or feedback (review_requests.outcome_of)
    feedback: str | None
    steer: str | None
    answered_by: str | None
    asking_run_id: str | None                 # the run whose gate raised the request; None for a request about something else
    approved_operations: tuple[str, ...]      # what this run may do because the person approved it; empty unless approved
    applied_in: Mapping[str, Any] | None      # the run that already used the answer, if one did

    @property
    def continues_the_work(self) -> bool:
        """Whether the procedure runs for this answer: not when the answer was already used, and not when it was a rejection."""
        return not self.applied_in and self.outcome != REJECTED

    @property
    def approvals(self) -> dict[str, str]:
        """Each approved operation and the request that approved it, as the gate takes them."""
        return {operation: self.request_id for operation in self.approved_operations}

    def as_input(self) -> dict[str, Any]:
        """What the procedure is given under ``review``: the decision and the person's own words, never a summary of them."""
        return {"requestId": self.request_id, "decision": self.outcome, "feedback": self.feedback, "steer": self.steer, "answeredBy": self.answered_by,
                "askingRun": self.asking_run_id, "approvedOperations": list(self.approved_operations)}

    def stop_reason(self) -> tuple[str, str]:
        """The reason code and the words of a run that stops for this answer instead of running."""
        if self.applied_in:
            return ANSWER_ALREADY_APPLIED, f"The answer to review request {self.request_id} was already used by run {self.applied_in.get('runId')}."
        words = f": {self.feedback}" if self.feedback else ""
        return REVIEW_REJECTED, f"Rejected by {self.answered_by or 'a person'} in review request {self.request_id}{words}"


def is_answer_wake(request: Mapping[str, Any]) -> bool:
    trigger = request.get("trigger")
    return isinstance(trigger, dict) and trigger.get("event") == REVIEW_ANSWERED_EVENT


def _parsed(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value) if value else None
        except json.JSONDecodeError as error:
            raise AnswerUnreadable(f"a stored value is not JSON: {error}") from error
    return value


def operations_a_person_was_asked_for(client, run_id: str) -> tuple[str, ...]:
    """The operations the asking run's gate said a person must do or approve, from the gate's answers on its run record."""
    run = client.get_record(RUN_MODEL, run_id)
    if not run:
        raise AnswerUnreadable(f"the run {run_id} that asked has no run record")
    output = _parsed(run.get("output")) or {}
    gate = output.get("gate") if isinstance(output, dict) else None
    answers = gate.get("gate") if isinstance(gate, dict) else None
    if not isinstance(answers, list):
        raise AnswerUnreadable(f"the run {run_id} that asked has no gate answers on its record")
    return tuple(str(answer["operation"]) for answer in answers if isinstance(answer, dict) and answer.get("answer") == HUMAN_REQUIRED)


def answer_of(client, request: Mapping[str, Any]) -> ReviewAnswer | None:
    """The answer this wake is about, read from the records; None when the wake is not an answer to a review request."""
    if not is_answer_wake(request):
        return None
    request_id = (request.get("input") or {}).get("version")   # the ReviewRequest feed puts the request's id where a record's version goes
    if not isinstance(request_id, str) or not request_id:
        raise AnswerUnreadable("the wake names no review request")
    try:
        review = review_requests.get_review(client, request_id)
    except review_requests.ReviewError as error:
        raise AnswerUnreadable(str(error)) from error
    answer = review["answer"] or {}
    if review["state"] != "answered" or review["outcome"] not in (APPROVED, REJECTED, FEEDBACK):
        raise AnswerUnreadable(f"review request {request_id} is {review['state']}, not answered")
    subject = review["subject"] or {}
    asking_run_id = str(subject["id"]) if subject.get("type") == "automation_run" and subject.get("id") else None
    approved = operations_a_person_was_asked_for(client, asking_run_id) if review["outcome"] == APPROVED and asking_run_id else ()
    return ReviewAnswer(request_id, review["outcome"], answer.get("feedback"), answer.get("steer"), answer.get("by"), asking_run_id, approved, review["appliedIn"])


def record_used(client, answer: ReviewAnswer, run_id: str, responsibility: str) -> None:
    """Write on the request the run that used the answer (``appliedIn``). A request already applied keeps the run it names."""
    review_requests.mark_applied(client, answer.request_id, run_id=run_id, by=f"agent:{responsibility}")
