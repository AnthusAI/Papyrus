"""Settling an interrupted run (the behaviour is in features_backend/agents/run-settle.feature)."""
import pytest

from papyrus_content import agent_wakes, run_settle


def run(status="started", outcome=None):
    return {"id": "run-1", "runStatus": status, "outcome": outcome}


@pytest.mark.parametrize("existing_run, receive_count, expected", [
    (run(), 2, True),
    (run(), 1, False),
    (run("completed", "acted"), 2, False),
    (run("failed", "unknown"), 2, False),
    (run(outcome="acted"), 2, False),
    (None, 2, False),
])
def test_only_a_run_still_started_on_the_settling_delivery_died(existing_run, receive_count, expected):
    assert run_settle.first_attempt_died(existing_run, receive_count) is expected


@pytest.mark.parametrize("trigger, expected", [({"safeToRepeat": True}, True), ({"safeToRepeat": False}, False), ({}, False), (None, False), ({"safeToRepeat": "yes"}, False)])
def test_a_procedure_is_repeated_only_when_its_wake_says_so_in_so_many_words(trigger, expected):
    assert run_settle.safe_to_repeat({"trigger": trigger}) is expected


def test_the_receive_count_is_the_queues_own_report():
    assert agent_wakes.receive_count({"Records": [{"attributes": {"ApproximateReceiveCount": "2"}}]}) == 2
    assert agent_wakes.receive_count({"Records": [{}]}) == 1
