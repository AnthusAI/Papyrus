"""Continuation requests (the behaviour is in features_backend/agents/run-continuation.feature)."""
import pytest

from papyrus_content import run_continuation as continuation, wake_keys

REQUEST = {"procedureKey": "papyrus.example.long", "wakeKey": "translator|story-1|7|stage_entered", "input": {"story": "story-1"}, "publicationId": "site",
           "trigger": {"kind": "event", "automationId": "translator", "summary": "woke", "paid": True, "story": "story-1", "version": "7"}}


def test_the_first_continuation_is_keyed_by_its_chains_root_run_and_keeps_the_trigger():
    following = continuation.next_request(REQUEST, "run-1", "2026-11-21T09:00:00Z")
    assert following["wakeKey"] == "translator|story-1|run-1|c1" and wake_keys.checked(following["wakeKey"])
    assert following["trigger"]["paid"] is True and following["trigger"]["continuation"] == 1 and following["trigger"]["continuationRoot"] == "run-1"
    assert following["input"] == REQUEST["input"]


def test_a_later_continuation_counts_up_in_the_same_chain():
    second = continuation.next_request({**REQUEST, "trigger": {**REQUEST["trigger"], "continuation": 1, "continuationRoot": "run-1"}}, "run-2", "2026-11-22T09:00:00Z")
    assert second["wakeKey"] == "translator|story-1|run-1|c2"


def test_the_chain_stops_at_the_limit():
    at_limit = {**REQUEST, "trigger": {**REQUEST["trigger"], "continuation": continuation.MAXIMUM_CONTINUATIONS, "continuationRoot": "run-1"}}
    with pytest.raises(continuation.ContinuationError) as stopped:
        continuation.next_request(at_limit, "run-9", "2026-11-22T09:00:00Z")
    assert stopped.value.reason == continuation.LIMIT_REACHED


@pytest.mark.parametrize("output, expected", [({}, None), ({continuation.NEXT_WAKE_KEY: None}, None), ({continuation.NEXT_WAKE_KEY: "2026-11-21T09:00:00Z"}, "2026-11-21T09:00:00Z"), ("text", None)])
def test_the_requested_time_is_read_from_the_output(output, expected):
    assert continuation.requested_time(output) == expected


def test_a_time_that_is_not_a_utc_instant_is_refused():
    with pytest.raises(continuation.ContinuationError) as refused:
        continuation.requested_time({continuation.NEXT_WAKE_KEY: "tomorrow"})
    assert refused.value.reason == continuation.INVALID_CONTINUATION
