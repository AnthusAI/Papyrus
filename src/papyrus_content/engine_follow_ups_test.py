from papyrus_content import follow_up_timers as fu
from papyrus_content.engine_follow_ups import engine_follow_up_of


def wake(owner="review-deadline", procedure="review_deadline", **trigger):
    return {"wakeKey": fu.follow_up_key(owner, "rr-1", "2026-11-20T09:00:00Z"), "procedureKey": procedure,
            "trigger": {"kind": fu.KIND, **trigger}}


def test_only_an_engine_owner_with_its_own_procedure_is_an_engine_follow_up():
    assert engine_follow_up_of(wake()) == "review-deadline"
    assert engine_follow_up_of(wake(owner="deliver")) is None, "not on the engine list"
    assert engine_follow_up_of(wake(procedure="rate_items")) is None, "another procedure"
    assert engine_follow_up_of(wake(automationId="rate")) is None, "an agent's wake"
    assert engine_follow_up_of({**wake(), "trigger": {"kind": "event"}}) is None, "not a follow-up"
    assert engine_follow_up_of({**wake(), "wakeKey": "review-deadline|schedule|2026-11-20"}) is None, "not a follow-up's key"
