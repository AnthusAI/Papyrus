"""The preview gate's statistics and wording (preview_gate.py). Synthetic data only."""

from __future__ import annotations

import math

import pytest

from .preview_gate import (
    APPROVED,
    HELD,
    MAX_REQUEST_TEXT,
    REJECTED,
    TOTAL,
    WRITTEN,
    Decision,
    compare,
    decide,
    describe,
    fingerprint_of,
    log10_tail,
    predictive,
    record,
    request_id,
    request_status,
    series_of,
    settle,
)


def plan(**kinds):
    """A sync plan with ``n`` pages to create for each entity kind given."""
    pages = [
        {"action": "create", "section": "wiki", "slug": f"{kind}-{n}", "kind": "entity", "entityKind": kind, "title": f"Title {kind} {n}"}
        for kind, count in kinds.items()
        for n in range(count)
    ]
    return {"counts": {}, "pages": pages}


def runs(*counts_by_run):
    return [series_of(plan(**counts)) for counts in counts_by_run]


def test_a_plans_series_count_what_it_would_write_by_kind_and_leave_unchanged_pages_out():
    sync = plan(maker=2, tool=1)
    sync["pages"].append({"action": "unchanged", "section": "wiki", "slug": "x", "kind": "entity", "entityKind": "maker", "title": "X"})
    sync["pages"].append({"action": "update", "section": "wiki", "slug": "y", "kind": "entity", "entityKind": "tool", "title": "Y"})
    assert series_of(sync) == {
        "entity/maker:create": 2, "entity/tool:create": 1, "entity/tool:update": 1, TOTAL: 4,
    }
    assert series_of(plan()) == {}


def test_the_fingerprint_is_the_same_for_the_same_plan_in_any_order_and_differs_for_another():
    first = plan(maker=3, tool=2)
    shuffled = {**first, "pages": list(reversed(first["pages"]))}
    assert fingerprint_of(first) == fingerprint_of(shuffled)
    assert fingerprint_of(first) != fingerprint_of(plan(maker=3, tool=3))


def test_the_tail_matches_the_exact_poisson_tail_when_the_variance_is_no_more_than_the_mean():
    mean, count = 20.0, 40
    exact = sum(math.exp(k * math.log(mean) - mean - math.lgamma(k + 1)) for k in range(count, 400))
    assert log10_tail(count, mean, mean) == pytest.approx(math.log10(exact), abs=0.01)


def test_a_count_at_or_below_the_mean_is_never_extreme():
    assert log10_tail(10, 12.0, 30.0) == 0.0


def test_a_wider_spread_makes_the_same_count_less_surprising():
    assert log10_tail(60, 20.0, 400.0) > log10_tail(60, 20.0, 20.0)


def test_the_prediction_learns_its_spread_from_the_history_and_never_goes_below_a_poisson():
    mean, variance = predictive([20, 20, 20, 20])
    assert mean == pytest.approx(20.125) and variance == pytest.approx(mean * 1.25)
    swinging_mean, swinging_variance = predictive([0, 40, 0, 40])
    assert swinging_variance > 10 * variance
    assert predictive([0, 0, 0, 0])[0] == pytest.approx(0.125)  # a series never seen still has a small rate


def test_a_steady_run_proceeds_and_a_run_many_times_larger_is_held_naming_the_series():
    steady = runs(*[{"maker": count} for count in (20, 25, 18, 22, 21, 19, 24, 20)])
    assert compare(series_of(plan(maker=26)), steady).action == "proceed"
    surge = compare(series_of(plan(maker=400)), steady)
    assert surge.hold and surge.reason == "differs_from_history" and "entity/maker:create" in {finding.series for finding in surge.findings}


def test_the_same_count_is_normal_for_a_site_that_swings_and_a_surge_for_one_that_does_not():
    swinging = runs(*[{"maker": count} for count in (5, 60, 10, 80, 15, 55)])
    steady = runs(*[{"maker": 20}] * 6)
    assert compare(series_of(plan(maker=70)), swinging).action == "proceed"
    assert compare(series_of(plan(maker=70)), steady).hold


def test_a_kind_that_appears_in_numbers_is_held_even_when_the_site_often_writes_pages():
    history = runs(*[{"maker": 20}] * 10)
    decision = compare(series_of(plan(maker=20, personauthor=1346)), history)
    assert decision.hold and any(finding.series == "entity/personauthor:create" for finding in decision.findings)


def test_the_threshold_is_the_chance_the_newest_run_is_the_biggest_shared_among_the_series_tested():
    history = runs(*[{"maker": 20}] * 9)
    decision = compare(series_of(plan(maker=20, tool=1)), history)
    assert decision.threshold == pytest.approx(1 / (10 * 3))  # 9 earlier runs, three series wrote something (maker, tool, the total)


def test_a_first_run_waits_for_a_person_unless_it_writes_nothing():
    series = series_of(plan(maker=3))
    assert decide(series, "fp", [], set(), set()) == Decision("hold", "first_run")
    assert decide({}, "fp", [], set(), set()).reason == "nothing_to_write" and decide({}, "fp", [], set(), set()).action == "proceed"


def test_a_plan_a_person_accepted_goes_through_and_one_they_rejected_stays_held():
    series = series_of(plan(maker=3))
    assert decide(series, "fp", [], {"fp"}, set()).reason == "approved_plan"
    assert decide(series, "fp", runs({"maker": 3}), set(), {"fp"}) == Decision("hold", "rejected_plan", runs_compared=1)


def test_only_a_persons_accept_counts_as_an_approval():
    assert request_status({"state": "answered", "answer": {"decision": "approve", "by": "person-sub"}}) == "approved"
    assert request_status({"state": "answered", "answer": {"decision": "approve", "by": "agent:editor"}}) == "rejected"
    assert request_status({"state": "answered", "answer": {"decision": "reject", "by": "person-sub"}}) == "rejected"
    assert request_status({"state": "withdrawn"}) == "rejected"
    assert request_status({"state": "open"}) == "open"


def test_settling_marks_answered_requests_in_the_history_and_leaves_open_ones_held():
    entries = [
        {"runId": "a", "fingerprint": "1", "outcome": HELD, "requestId": "r1", "series": {}},
        {"runId": "b", "fingerprint": "2", "outcome": HELD, "requestId": "r2", "series": {}},
        {"runId": "c", "fingerprint": "3", "outcome": HELD, "requestId": "r3", "series": {}},
        {"runId": "d", "fingerprint": "4", "outcome": WRITTEN, "series": {}},
    ]
    states = {"r1": {"state": "answered", "answer": {"decision": "approve", "by": "p"}}, "r2": {"state": "answered", "answer": {"decision": "reject", "by": "p"}}, "r3": {"state": "open"}}
    assert settle(entries, states.__getitem__) is True
    assert [entry["outcome"] for entry in entries] == [APPROVED, REJECTED, HELD, WRITTEN]
    assert settle(entries, states.__getitem__) is False


def test_recording_a_retried_stage_replaces_its_earlier_entry():
    entries = [{"runId": "a", "fingerprint": "1", "outcome": HELD}]
    record(entries, {"runId": "a", "fingerprint": "1", "outcome": WRITTEN})
    assert entries == [{"runId": "a", "fingerprint": "1", "outcome": WRITTEN}]


def test_the_request_a_person_reads_says_nothing_was_written_names_the_kinds_and_samples_titles_within_the_limit():
    many = plan(personauthor=1346, qualityrating=5, maker=3, **{f"kind{n}": 4 for n in range(60)})
    series = series_of(many)
    reason, ask = describe(many, series, Decision("hold", "first_run"), publication="example")
    assert "First knowledge run for example" in reason and "Nothing has been written" in reason
    assert "entity/personauthor:create 1,346" in ask and "Title " in ask and "Accept to let the next run write pages like these" in ask
    assert len(ask) <= MAX_REQUEST_TEXT and len(reason) <= MAX_REQUEST_TEXT


def test_a_held_run_that_differs_from_history_says_what_the_history_predicted():
    history = runs(*[{"maker": 20}] * 6)
    surge = plan(maker=400)
    series = series_of(surge)
    decision = compare(series, history)
    reason, ask = describe(surge, series, decision, publication="example")
    assert "unlike this site's earlier runs" in reason
    assert "entity/maker:create would write 400" in ask and "predict about" in ask


def test_the_request_id_is_stable_for_a_plan_and_a_valid_review_request_id():
    from papyrus_content.review_requests import REQUEST_ID

    assert request_id("Example", "abc123") == "rr-wiki-sync-example-abc123" and REQUEST_ID.match(request_id("Example", "abc123"))
