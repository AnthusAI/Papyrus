"""The wake gate's arithmetic and refusals (the behaviour is in features_backend/coalescing-window.feature and agent-loop-guard.feature)."""
from datetime import datetime, timezone

import pytest

from papyrus_content import wake_gate
from papyrus_content.agent_policy import PolicyError, validate_document


class Chain:
    def __init__(self, hops=0):
        self.hops, self.round, self.cleared = hops, 0, 0

    def read(self, subject):
        return {"hops": self.hops, "round": self.round}

    def write(self, subject, hops):
        self.hops = hops

    def reset(self, subject, version):
        self.cleared += 1
        return True


class Timers:
    def __init__(self):
        self.set = []

    def sync(self, kind, record, due_at, *, owner, base, waiting_for):
        self.set.append((kind, record, due_at, owner, base, waiting_for))


def request(*, paid, actor, at="2026-11-18T09:00:00Z", responsibility="improve"):
    return {"wakeKey": "fact-check|story-1|story-1-v2|version_created", "procedureKey": "story.fact_check", "input": {"story": "story-1", "version": "story-1-v2"},
            "trigger": {"kind": "event", "automationId": "fact-check", "story": "story-1", "version": "story-1-v2", "summary": "why", "paid": paid, "actorKind": actor,
                        "at": at, "responsibility": responsibility}}


def gate(document=None, chain=None, reviews=None):
    return wake_gate.WakeGate(policy=lambda: document or {}, timers=Timers(), chain=chain or Chain(), review=lambda **found: (reviews if reviews is not None else []).append(found),
                              clock=lambda: datetime(2026, 11, 18, tzinfo=timezone.utc))


def test_a_free_wake_is_sent_at_once_and_a_paid_one_sets_a_timer_without_the_version():
    sent, free_gate = [], gate()
    assert free_gate.release(request(paid=False, actor="person"), sent.append) == {"status": "sent"} and len(sent) == 1
    outcome = free_gate.release(request(paid=True, actor="person"), sent.append)
    assert outcome["status"] == "waiting" and len(sent) == 1
    [(kind, record, due_at, owner, base, waiting_for)] = free_gate.timers.set
    assert (kind, record, owner, waiting_for, due_at) == ("quiet:fact-check", "story-1", "fact-check", "quiet window", "2026-11-18T09:05:00Z")
    assert "version" not in base["input"] and "version" not in base["trigger"] and "wakeKey" not in base


@pytest.mark.parametrize("actor, seconds", [("person", 300), ("agent", 1800)])
def test_the_starting_windows_are_the_shortest_of_the_ruling(actor, seconds):
    assert gate().window_seconds(actor) == seconds


def test_the_owners_windows_win():
    document = {"site": {"coalescing": {"windowSeconds": 7200, "afterPersonSeconds": 600}}}
    assert (gate(document).window_seconds("agent"), gate(document).window_seconds("person")) == (7200, 600)


def test_an_agent_wake_at_the_limit_is_stopped_once_per_wake_and_raises_the_gate_each_time_for_the_same_request():
    reviews, sent = [], []
    stopped = gate({"agents": {"improve": {"rung": "propose", "loopLimit": 2}}}, Chain(hops=2), reviews)
    assert stopped.release(request(paid=False, actor="agent"), sent.append)["status"] == "stopped"
    assert sent == [] and reviews == [{"story": "story-1", "agent": "fact-check", "hops": 2, "limit": 2, "round": 0}]


def test_a_person_wake_is_never_counted_or_stopped():
    chain = Chain(hops=99)
    assert gate(chain=chain).release(request(paid=False, actor="person"), lambda r: None)["status"] == "sent" and chain.hops == 99


def test_an_agent_wake_that_goes_on_is_counted():
    chain = Chain(hops=1)
    gate(chain=chain).release(request(paid=True, actor="agent"), lambda r: None)
    assert chain.hops == 2


def test_the_limit_starts_at_five():
    assert gate().loop_limit("improve") == wake_gate.DEFAULT_LOOP_LIMIT == 5


@pytest.mark.parametrize("coalescing", [{"windowSeconds": 60}, {"windowSeconds": 90000}, {"windowSeconds": True}, {"afterPersonSeconds": 0},
                                        {"windowSeconds": 1800, "afterPersonSeconds": 3600}, {"minutes": 5}])
def test_a_window_outside_the_ruling_is_refused(coalescing):
    with pytest.raises(PolicyError):
        validate_document({"schemaVersion": 1, "site": {"coalescing": coalescing}, "agents": {}})


def test_a_window_inside_the_ruling_is_kept():
    validate_document({"schemaVersion": 1, "site": {"coalescing": {"windowSeconds": 1800, "afterPersonSeconds": 300}}, "agents": {}})
