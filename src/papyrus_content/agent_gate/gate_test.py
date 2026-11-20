import pytest

from papyrus_content.agent_gate import ALLOWED, BLOCKED, HUMAN_REQUIRED, GateRun, decide
from papyrus_content.agent_policy import PolicyState
from papyrus_content.agent_rungs import RUNGS
from papyrus_content.images.operations import OPERATIONS


def policy(rung, **entry):
    return PolicyState(3, {"schemaVersion": 1, "site": {}, "agents": {"illustrate": {"rung": rung, **entry}}})


def test_every_agent_operation_is_allowed_from_exactly_its_rung_up():
    for item in OPERATIONS:
        if not item.agent_allowed:
            continue
        for rung in RUNGS[1:]:
            expected = ALLOWED if RUNGS.index(rung) >= RUNGS.index(item.agent_rung) else HUMAN_REQUIRED
            assert decide(policy(rung), "agent", item.name, "illustrate").answer == expected, (item.name, rung)


def test_person_only_operations_answer_what_the_table_says_at_every_rung():
    for item in OPERATIONS:
        if item.agent_allowed:
            continue
        for rung in RUNGS:
            assert decide(policy(rung), "agent", item.name, "illustrate").answer == item.agent_refusal


def test_a_person_is_never_gated_and_needs_no_policy():
    assert decide(None, "person", "announcements_settings_set").answer == ALLOWED


def test_a_pause_blocks_and_says_why():
    answer = decide(policy("publish_auto", paused=True, pausedReason="Checking a bad run"), "agent", "image_apply", "illustrate")
    assert answer.answer == BLOCKED and "Checking a bad run" in answer.reason


def test_an_agent_call_without_a_policy_or_responsibility_is_blocked():
    assert decide(None, "agent", "image_apply", "illustrate").answer == BLOCKED
    assert decide(policy("draft"), "agent", "image_apply").answer == BLOCKED


def test_the_run_keeps_one_review_request_and_every_answer():
    run = GateRun(policy("propose"), "illustrate", "run-9")
    run.ask("image_search"), run.ask("image_apply"), run.ask("image_discard")
    assert run.review_request["operations"] == ["image_apply", "image_discard"]
    assert [entry["answer"] for entry in run.record()["gate"]] == [ALLOWED, HUMAN_REQUIRED, HUMAN_REQUIRED]
    assert run.record()["policyVersion"] == 3
