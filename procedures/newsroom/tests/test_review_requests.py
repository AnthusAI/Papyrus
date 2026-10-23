"""Human review points (PPY-ab6a50): the three modes, the deadline, answers, steering read-back, waiting, the batch hook, recipients."""
from datetime import datetime, timedelta, timezone

import pytest

from fake_client import FakeAuthoringClient
from papyrus_content import review_requests as rr
from papyrus_content.review_requests import ReviewError, ReviewStillOpen

T0 = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
STORY = {"type": "story", "id": "story-1"}


def raise_(client, mode="soft_review", **changes):
    arguments = dict(subject=STORY, mode=mode, reason="Check this", raised_by="procedure:ideas", now=T0)
    arguments.update(changes)
    return rr.raise_review(client, **arguments)


class Clock:
    """A clock that `sleep` moves, so a wait that would take days takes no time."""

    def __init__(self, start=T0):
        self.now = start

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


# --- raising ---------------------------------------------------------------------------------------------------


def test_a_soft_review_gets_the_default_seven_day_deadline_and_a_history_entry():
    request = raise_(FakeAuthoringClient())
    assert request["state"] == "open" and request["deadline"] == "2026-10-30T12:00:00Z"
    assert request["history"][0]["event"] == "raised" and request["outcome"] == "waiting"


def test_a_flag_and_a_hard_gate_take_no_deadline_and_a_soft_review_needs_a_positive_one():
    client = FakeAuthoringClient()
    assert raise_(client, "flag")["deadline"] is None and raise_(client, "hard_gate")["deadline"] is None
    with pytest.raises(ReviewError, match="no deadline"):
        raise_(client, "hard_gate", deadline_days=3)
    with pytest.raises(ReviewError, match="more than zero"):
        raise_(client, "soft_review", deadline_days=0)


@pytest.mark.parametrize("changes,message", [
    ({"mode": "maybe"}, "mode must be"), ({"reason": " "}, "reason is required"),
    ({"subject": {"type": "story"}}, "subject.id"), ({"request_id": "Bad Id"}, "id must be"),
    ({"links": [{"label": "x"}]}, "needs a url"),
])
def test_invalid_requests_are_refused_with_a_reason(changes, message):
    with pytest.raises(ReviewError, match=message):
        raise_(FakeAuthoringClient(), **changes)


def test_raising_with_the_same_id_twice_returns_the_first_request():
    client = FakeAuthoringClient()
    first = raise_(client, request_id="rr-same")
    second = raise_(client, request_id="rr-same", reason="Different")
    assert second["reason"] == first["reason"] and len(client.list_records("ReviewRequest")) == 1


# --- the deadline: check on read ----------------------------------------------------------------------------------


def test_a_soft_review_past_its_deadline_is_timed_out_and_records_proceeded_without_review():
    client = FakeAuthoringClient()
    request = raise_(client)
    assert rr.expire_due(client, now=T0 + timedelta(days=6)) == []
    assert rr.expire_due(client, now=T0 + timedelta(days=7)) == [request["id"]]
    stored = rr.get_review(client, request["id"], now=T0 + timedelta(days=8))
    assert stored["state"] == "timed_out" and stored["outcome"] == "proceeded_without_review"
    assert stored["history"][-1]["note"] == "proceeded without review" and stored["history"][-1]["by"] == "system"
    assert rr.expire_due(client, now=T0 + timedelta(days=9)) == [], "idempotent"


def test_listing_sweeps_and_a_late_answer_is_refused_with_the_reason():
    client = FakeAuthoringClient()
    request = raise_(client)
    listed = rr.list_reviews(client, now=T0 + timedelta(days=8))
    assert listed[0]["state"] == "timed_out"
    with pytest.raises(ReviewError, match="proceeded without review"):
        rr.answer_review(client, request["id"], decision="approve", by="ed", now=T0 + timedelta(days=8))


def test_a_flag_and_a_hard_gate_never_time_out():
    client = FakeAuthoringClient()
    raise_(client, "flag"), raise_(client, "hard_gate")
    assert rr.expire_due(client, now=T0 + timedelta(days=3650)) == []
    assert {request["state"] for request in rr.list_reviews(client, now=T0 + timedelta(days=3650))} == {"open"}


# --- answers -----------------------------------------------------------------------------------------------------------


def test_approve_reject_and_feedback_are_recorded_with_who_and_when():
    client = FakeAuthoringClient()
    ids = {name: raise_(client)["id"] for name in ("a", "r", "f")}
    approved = rr.answer_review(client, ids["a"], decision="approve", by="ed", now=T0)
    rejected = rr.answer_review(client, ids["r"], decision="reject", by="ed", feedback="Off topic", now=T0)
    feedback = rr.answer_review(client, ids["f"], decision="feedback", by="ed", feedback="More on pricing", steer="adjust", now=T0)
    assert approved["outcome"] == "approved" and rejected["outcome"] == "rejected" and feedback["outcome"] == "feedback"
    assert feedback["answer"] == {"decision": "feedback", "feedback": "More on pricing", "steer": "adjust", "by": "ed", "at": "2026-10-23T12:00:00Z"}
    assert [entry["event"] for entry in feedback["history"]] == ["raised", "answered"]


def test_only_editors_and_admins_answer_and_an_answer_is_final():
    client = FakeAuthoringClient()
    request_id = raise_(client)["id"]
    with pytest.raises(ReviewError, match="only editors and admins"):
        rr.answer_review(client, request_id, decision="approve", by="reader", roles=["reader"], now=T0)
    rr.answer_review(client, request_id, decision="approve", by="ed", roles=["editor"], now=T0)
    with pytest.raises(ReviewError, match="answered"):
        rr.answer_review(client, request_id, decision="reject", by="ed", now=T0)


@pytest.mark.parametrize("arguments,message", [
    ({"decision": "later"}, "decision must be"), ({"decision": "feedback"}, "needs some text"),
    ({"decision": "feedback", "feedback": "x", "steer": "sideways"}, "steer must be"),
])
def test_bad_answers_are_refused(arguments, message):
    client = FakeAuthoringClient()
    with pytest.raises(ReviewError, match=message):
        rr.answer_review(client, raise_(client)["id"], by="ed", now=T0, **arguments)


def test_a_withdrawn_request_cannot_be_answered():
    client = FakeAuthoringClient()
    request_id = raise_(client)["id"]
    assert rr.withdraw_review(client, request_id, by="procedure", now=T0)["outcome"] == "withdrawn"
    with pytest.raises(ReviewError, match="withdrawn"):
        rr.answer_review(client, request_id, decision="approve", by="ed", now=T0)


# --- waiting: what a process does ----------------------------------------------------------------------------------------


def test_a_flag_never_blocks():
    client = FakeAuthoringClient()
    request = rr.review_gate(client, subject=STORY, mode="flag", reason="FYI", raised_by="p", sleep=lambda s: pytest.fail("slept"))
    assert request["state"] == "open" and request["outcome"] == "waiting"


def test_a_soft_review_waits_then_proceeds_without_review_at_the_deadline():
    client, clock = FakeAuthoringClient(), Clock()
    request = raise_(client)
    result = rr.wait_for_review(client, request["id"], poll_seconds=3600, sleep=clock.sleep, clock=clock)
    assert result["outcome"] == "proceeded_without_review" and result["state"] == "timed_out"
    assert clock.now >= T0 + timedelta(days=7), "it waited until the deadline"


def test_a_soft_review_answered_before_its_deadline_returns_the_answer():
    client, clock = FakeAuthoringClient(), Clock()
    request = raise_(client)
    calls = []

    def sleep(seconds):
        calls.append(seconds)
        rr.answer_review(client, request["id"], decision="feedback", feedback="Shorter", by="ed", now=clock.now)
        clock.sleep(seconds)

    result = rr.wait_for_review(client, request["id"], poll_seconds=60, sleep=sleep, clock=clock)
    assert result["outcome"] == "feedback" and result["answer"]["feedback"] == "Shorter" and len(calls) == 1


def test_a_hard_gate_blocks_indefinitely_and_never_proceeds_without_review():
    client, clock = FakeAuthoringClient(), Clock()
    request = raise_(client, "hard_gate")
    with pytest.raises(ReviewStillOpen) as stopped:
        rr.wait_for_review(client, request["id"], poll_seconds=86_400, max_wait_seconds=365 * 86_400, sleep=clock.sleep, clock=clock)
    assert stopped.value.request["state"] == "open"
    assert rr.get_review(client, request["id"], now=clock.now)["state"] == "open", "a year later it is still waiting"


def test_a_hard_gate_continues_only_on_an_explicit_answer():
    client, clock = FakeAuthoringClient(), Clock()
    request = raise_(client, "hard_gate")

    def sleep(seconds):
        rr.answer_review(client, request["id"], decision="approve", by="ed", now=clock.now)

    assert rr.wait_for_review(client, request["id"], sleep=sleep, clock=clock)["outcome"] == "approved"


# --- steering read back ------------------------------------------------------------------------------------------------------


def test_steering_is_read_back_by_whoever_raised_the_request_and_marked_applied_once():
    client = FakeAuthoringClient()
    mine, other = raise_(client, raised_by="idea-pipeline")["id"], raise_(client, raised_by="other")["id"]
    plain = raise_(client, raised_by="idea-pipeline")["id"]
    rr.answer_review(client, mine, decision="feedback", feedback="Fewer listicles", steer="not_this_kind", by="ed", now=T0)
    rr.answer_review(client, other, decision="feedback", feedback="Not for you", by="ed", now=T0)
    rr.answer_review(client, plain, decision="approve", by="ed", now=T0)
    found = rr.steering_for(client, raised_by="idea-pipeline")
    assert [(entry["requestId"], entry["feedback"], entry["steer"]) for entry in found] == [(mine, "Fewer listicles", "not_this_kind")]
    applied = rr.mark_applied(client, mine, run_id="run-42", by="idea-pipeline", now=T0)
    assert applied["appliedIn"]["runId"] == "run-42" and applied["history"][-1]["event"] == "applied"
    assert rr.steering_for(client, raised_by="idea-pipeline") == []
    assert len(rr.steering_for(client, raised_by="idea-pipeline", include_applied=True)) == 1


def test_a_rejection_counts_as_steering_and_an_open_request_cannot_be_applied():
    client = FakeAuthoringClient()
    request_id = raise_(client, raised_by="p")["id"]
    with pytest.raises(ReviewError, match="not answered"):
        rr.mark_applied(client, request_id, run_id="r", by="p")
    rr.answer_review(client, request_id, decision="reject", by="ed", now=T0)
    assert rr.steering_for(client, raised_by="p")[0]["decision"] == "reject"


# --- the idea pipeline hook -------------------------------------------------------------------------------------------------------


def test_one_soft_review_per_synthesis_run_with_the_count_in_the_reason_and_a_seven_day_deadline():
    client = FakeAuthoringClient()
    request = rr.raise_batch_review(client, raised_by="idea-pipeline", batch_id="2026-W43", proposal_ids=["p1", "p2", "p3"], now=T0)
    assert request["reason"] == "3 new story ideas to review" and request["mode"] == "soft_review"
    assert request["deadline"] == "2026-10-30T12:00:00Z" and request["subject"] == {"type": "batch", "id": "2026-W43"}
    assert [link["id"] for link in request["links"]] == ["p1", "p2", "p3"]
    again = rr.raise_batch_review(client, raised_by="idea-pipeline", batch_id="2026-W43", proposal_ids=["p1", "p2", "p3"], now=T0)
    assert again["id"] == request["id"] and len(client.list_records("ReviewRequest")) == 1
    assert rr.raise_batch_review(client, raised_by="i", batch_id="b2", proposal_ids=["p9"], now=T0)["reason"] == "1 new story idea to review"
    with pytest.raises(ReviewError, match="at least one"):
        rr.raise_batch_review(client, raised_by="i", batch_id="b3", proposal_ids=[])


# --- recipients ------------------------------------------------------------------------------------------------------------------------


def users(*pairs):
    return [{"id": f"u{index}", "role": role, "status": status, "email": email} for index, (role, status, email) in enumerate(pairs)]


def test_recipients_default_to_the_site_owner_then_the_admins(monkeypatch):
    monkeypatch.delenv("PAPYRUS_SITE_OWNER_EMAIL", raising=False)
    client = FakeAuthoringClient({"UserRoleAssignment": users(("admin", "active", "admin@example.test"), ("editor", "active", "ed@example.test"),
                                                              ("admin", "revoked", "gone@example.test"))})
    assert rr.resolve_recipients(client, mode="hard_gate")["emails"] == ["admin@example.test"]
    assert rr.resolve_recipients(client, mode="hard_gate", site_owner="owner@example.test") == {
        "emails": ["owner@example.test"], "source": "site_owner", "roles": []}


def test_the_most_specific_rule_wins_and_can_change_without_code():
    client = FakeAuthoringClient({"UserRoleAssignment": users(("admin", "active", "admin@example.test"), ("editor", "active", "ed@example.test"))})
    rr.set_recipient_rule(client, scope="default", key=None, roles=["admin"], emails=[], by="a")
    rr.set_recipient_rule(client, scope="mode", key="hard_gate", roles=["editor"], emails=["extra@example.test"], by="a")
    rr.set_recipient_rule(client, scope="automation", key="ttab", roles=[], emails=["ruling@example.test"], by="a")
    assert rr.resolve_recipients(client, mode="soft_review")["emails"] == ["admin@example.test"]
    assert rr.resolve_recipients(client, mode="hard_gate") == {"emails": ["ed@example.test", "extra@example.test"], "source": "mode hard_gate", "roles": ["editor"]}
    assert rr.resolve_recipients(client, mode="hard_gate", automation="ttab")["emails"] == ["ruling@example.test"]
    rr.set_recipient_rule(client, scope="mode", key="hard_gate", roles=["admin"], emails=[], by="a")
    assert rr.resolve_recipients(client, mode="hard_gate")["emails"] == ["admin@example.test"]


@pytest.mark.parametrize("arguments,message", [
    ({"scope": "everyone"}, "scope must be"), ({"scope": "mode", "key": "loud"}, "mode rule needs"),
    ({"scope": "default", "key": "x"}, "no key"), ({"scope": "automation"}, "automation id"),
    ({"scope": "default", "roles": ["reader"]}, "roles must be"), ({"scope": "default", "emails": ["nope"]}, "not an email"),
])
def test_bad_recipient_rules_are_refused(arguments, message):
    with pytest.raises(ReviewError, match=message):
        rr.set_recipient_rule(FakeAuthoringClient(), **{"key": None, "roles": [], "emails": [], "by": "a", **arguments})
