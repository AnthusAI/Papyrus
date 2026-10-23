"""`papyrus reviews ...` (PPY-ab6a50): raise, list, show, answer, steering, applied, withdraw and the recipient rules."""
import json

import pytest

from fake_client import FakeAuthoringClient
from papyrus_content import graphql_authoring
from papyrus_content import review_requests as rr


@pytest.fixture
def run(monkeypatch, capsys):
    client = FakeAuthoringClient()
    monkeypatch.setattr(graphql_authoring, "create_authoring_client", lambda: (client,))
    monkeypatch.setenv("PAPYRUS_ACTOR_LABEL", "tester")

    def invoke(command, *flags):
        capsys.readouterr()
        rr.run_command(command, list(flags))
        return capsys.readouterr().out

    invoke.client = client
    return invoke


def test_raise_list_show_answer_and_steering_round_trip(run):
    out = run("raise", "--subject-type", "batch", "--subject-id", "w43", "--mode", "soft_review", "--reason", "3 new story ideas to review",
              "--raised-by", "idea-pipeline", "--deadline-days", "7", "--id", "rr-w43")
    assert out.startswith("reviews\trr-w43\tsoft_review\topen\tbatch:w43\tproceeds ")
    assert "rr-w43" in run("list", "--state", "open")
    assert "ask\t-" in run("show", "--id", "rr-w43")
    answered = run("answer", "--id", "rr-w43", "--decision", "feedback", "--feedback", "Fewer listicles", "--steer", "not_this_kind")
    assert "answered" in answered and "feedback" in answered
    steering = json.loads(run("steering", "--raised-by", "idea-pipeline", "--json"))["result"]
    assert steering[0]["feedback"] == "Fewer listicles" and steering[0]["by"] == "tester"
    run("applied", "--id", "rr-w43", "--run", "run-9")
    assert "applied\trun run-9" in run("show", "--id", "rr-w43")
    assert json.loads(run("steering", "--raised-by", "idea-pipeline", "--json"))["result"] == []


def test_a_hard_gate_raise_with_a_deadline_is_refused_and_withdraw_works(run):
    with pytest.raises(rr.ReviewError, match="no deadline"):
        run("raise", "--subject-type", "story", "--subject-id", "s", "--mode", "hard_gate", "--reason", "r", "--deadline-days", "2")
    run("raise", "--subject-type", "story", "--subject-id", "s", "--mode", "flag", "--reason", "FYI", "--id", "rr-flag")
    assert "withdrawn" in run("withdraw", "--id", "rr-flag", "--note", "no longer applies")


def test_recipient_rules_are_set_and_resolved(run):
    run("recipients", "--set", "--scope", "mode", "--key", "hard_gate", "--roles", "editor", "--emails", "extra@example.test")
    out = json.loads(run("recipients", "--mode", "hard_gate", "--json"))["result"]
    assert out["emails"] == ["extra@example.test"] and out["source"] == "mode hard_gate"


def test_an_unknown_command_is_refused(run):
    with pytest.raises(ValueError, match="Unsupported"):
        run("frobnicate")
