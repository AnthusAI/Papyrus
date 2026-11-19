from __future__ import annotations

from papyrus_content import agent_assignments, change_feeds
from papyrus_content.handoff_records import responsibility_of

ASSIGNMENT = {"id": "handoff-1", "assignmentTypeKey": "responsibility.research", "status": "open", "createdBy": "agent:fact_check", "summary": "Find a source.",
              "itemLineageId": "story-1", "createdAt": "2026-11-19T09:00:00Z", "updatedAt": "2026-11-19T09:00:00Z"}


def names(old, new, event):
    return [(c.change, c.what, c.only_for) for c in change_feeds.changes_of("Assignment", old, new, event)]


def test_a_new_open_request_is_created_and_any_other_kind_is_no_change():
    assert names(None, ASSIGNMENT, "INSERT") == [("created", "created", None)]
    assert names(None, {**ASSIGNMENT, "assignmentTypeKey": "research.candidate"}, "INSERT") == []
    assert names(None, {**ASSIGNMENT, "status": "claimed"}, "INSERT") == []


def test_reopening_a_closed_request_names_the_reopening_and_a_release_is_no_change():
    for closed in ("completed", "canceled", "failed"):
        assert names({**ASSIGNMENT, "status": closed}, {**ASSIGNMENT, "updatedAt": "2026-11-19T11:00:00Z"}, "MODIFY") == [("reopened", "reopened.2026-11-19T11:00:00Z", None)]
    assert names({**ASSIGNMENT, "status": "claimed"}, ASSIGNMENT, "MODIFY") == []


def test_completion_is_addressed_to_the_agent_that_asked_and_to_nobody_for_a_person():
    claimed = {**ASSIGNMENT, "status": "claimed", "assigneeKey": "agent:research"}
    done = {**claimed, "status": "completed", "completedAt": "2026-11-19T10:00:00Z"}
    assert names(claimed, done, "MODIFY") == [("completed", "completed.2026-11-19T10:00:00Z", "fact_check")]
    assert names({**claimed, "createdBy": "ada"}, {**done, "createdBy": "ada"}, "MODIFY") == []
    assert names(claimed, {**claimed, "status": "failed"}, "MODIFY") == []


def test_the_type_names_the_responsibility():
    assert agent_assignments.type_key("research") == "responsibility.research"
    assert responsibility_of(ASSIGNMENT) == "research" and responsibility_of({"assignmentTypeKey": "responsibility."}) is None


def test_the_same_ask_has_the_same_id_and_a_person_s_ask_does_not():
    first = agent_assignments.assignment_id("agent:a", "research", "s", "why")
    assert first == agent_assignments.assignment_id("agent:a", "research", "s", "why") != agent_assignments.assignment_id("agent:a", "research", "s", "other")
    assert agent_assignments.assignment_id("ada", "research", "s", "why", "r1") != agent_assignments.assignment_id("ada", "research", "s", "why", "r2")


def test_only_the_wakes_made_for_the_responsible_agent_are_its_work():
    def request(event):
        return {"trigger": {"event": event}, "input": {"subject": {"kind": "Assignment", "id": "handoff-1"}}}

    assert agent_assignments.assignment_of_request(request("assignment.created")) == "handoff-1"
    assert agent_assignments.assignment_of_request(request("assignment.reopened")) == "handoff-1"
    assert agent_assignments.assignment_of_request(request("assignment.completed")) is None
    assert agent_assignments.assignment_of_request({"trigger": {"event": "assignment.created"}, "input": {}}) is None
