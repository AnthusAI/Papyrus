import json

import pytest

from papyrus_content import review_requests
from papyrus_content.agent_gate import ALLOWED, BLOCKED, HUMAN_REQUIRED, GateRun, review_answers
from papyrus_content.agent_policy import PolicyState

ASKING_RUN = "procedure-run-wake-0123456789abcdef0123456789abcdef"


class Records:
    def __init__(self):
        self.rows = {}

    def get_record(self, model, record_id):
        return self.rows.get(model, {}).get(record_id)

    def create_record(self, model, row):
        self.rows.setdefault(model, {})[row["id"]] = dict(row)

    def update_record(self, model, changes):
        self.rows[model][changes["id"]].update({key: value for key, value in changes.items() if value is not None})


def asked(records, *, operations=("image_apply",), decision="approve", feedback=None):
    records.create_record("ProcedureRun", {"id": ASKING_RUN, "output": json.dumps({"gate": {"policyVersion": 1, "gate": [
        {"answer": HUMAN_REQUIRED, "operation": name} for name in operations] + [{"answer": ALLOWED, "operation": "items_read"}]}})})
    filed = review_requests.raise_review(records, subject={"type": "automation_run", "id": ASKING_RUN}, mode="hard_gate", reason="needs a person",
                                         raised_by="agent:illustrate", request_id="gate-1")
    review_requests.answer_review(records, filed["id"], decision=decision, by="ada", feedback=feedback)
    return filed["id"]


def wake(request_id="gate-1", event=review_answers.REVIEW_ANSWERED_EVENT):
    return {"input": {"subject": {"kind": "automation_run", "id": ASKING_RUN}, "version": request_id, "change": "answered"}, "trigger": {"event": event}}


def test_a_wake_that_is_not_an_answer_has_no_answer():
    assert review_answers.answer_of(Records(), wake(event="story.stage_entered")) is None


def test_an_approval_allows_what_the_asking_run_was_refused_and_nothing_else():
    records = Records()
    asked(records, operations=("image_apply", "items_write"))
    answer = review_answers.answer_of(records, wake())
    assert answer.continues_the_work and answer.approved_operations == ("image_apply", "items_write")
    assert answer.approvals == {"image_apply": "gate-1", "items_write": "gate-1"}
    assert answer.as_input()["askingRun"] == ASKING_RUN and answer.as_input()["decision"] == "approved"


def test_a_rejection_stops_with_the_persons_words():
    records = Records()
    asked(records, decision="reject", feedback="Not this picture")
    answer = review_answers.answer_of(records, wake())
    assert not answer.continues_the_work and answer.approved_operations == ()
    assert answer.stop_reason() == (review_answers.REVIEW_REJECTED, "Rejected by ada in review request gate-1: Not this picture")


def test_feedback_approves_nothing_and_continues():
    records = Records()
    asked(records, decision="feedback", feedback="Crop it")
    answer = review_answers.answer_of(records, wake())
    assert answer.continues_the_work and answer.approved_operations == () and answer.feedback == "Crop it"


def test_an_answer_already_used_stops_and_names_the_run_that_used_it():
    records = Records()
    asked(records)
    review_requests.mark_applied(records, "gate-1", run_id="run-7", by="agent:illustrate")
    answer = review_answers.answer_of(records, wake())
    assert not answer.continues_the_work
    assert answer.stop_reason() == (review_answers.ANSWER_ALREADY_APPLIED, "The answer to review request gate-1 was already used by run run-7.")


def test_an_approval_whose_asking_run_has_no_record_is_unreadable():
    records = Records()
    asked(records)
    del records.rows["ProcedureRun"][ASKING_RUN]
    with pytest.raises(review_answers.AnswerUnreadable, match="has no run record"):
        review_answers.answer_of(records, wake())


def test_a_wake_for_a_request_that_does_not_exist_is_unreadable():
    with pytest.raises(review_answers.AnswerUnreadable, match="does not exist"):
        review_answers.answer_of(Records(), wake("gate-missing"))


def test_an_approval_never_lifts_a_blocked_operation():
    state = PolicyState(1, {"schemaVersion": 1, "site": {}, "agents": {"illustrate": {"rung": "propose"}}})
    gate_run = GateRun(state, "illustrate", "run-2", approvals={"image_apply": "gate-1", "announcements_settings_set": "gate-1"})
    assert gate_run.ask("image_apply").answer == ALLOWED and gate_run.answers[0].approved_in == "gate-1"
    assert gate_run.ask("announcements_settings_set").answer == BLOCKED
    assert gate_run.review_request is None
