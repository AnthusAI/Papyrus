import json

import pytest

from papyrus_content.agent_gate import run_context
from papyrus_content.agent_policy.resolve import PolicyState

STATE = PolicyState(3, {"schemaVersion": 1, "site": {}, "agents": {"rate": {"rung": "observe"}}})


def test_the_context_round_trips_through_the_environment():
    environment = run_context.to_environment("run-1", "rate", STATE, 1_800_000_000.5)
    run = run_context.from_environment(environment)
    assert (run.run_id, run.responsibility, run.policy, run.deadline) == ("run-1", "rate", STATE, 1_800_000_000.5)


def test_a_process_an_agent_did_not_start_has_no_context():
    assert run_context.from_environment({}) is None


def test_a_context_nobody_wrote_is_an_error_not_a_missing_one():
    with pytest.raises(ValueError):
        run_context.from_environment({run_context.ENVIRONMENT_KEY: json.dumps({"runId": "run-1"})})
    with pytest.raises(ValueError):
        run_context.from_environment({run_context.ENVIRONMENT_KEY: "not json"})
