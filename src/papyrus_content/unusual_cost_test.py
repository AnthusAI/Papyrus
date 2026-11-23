from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from papyrus_content import spend_ledger, unusual_cost
from papyrus_content.agent_policy.document import PolicyError, validate_agent
from papyrus_content.spend_ledger_test import FakeLedgerTable

MOMENT = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)


class Reviews:
    """The site API as far as raising a review request uses it."""

    def __init__(self):
        self.reviews = {}

    def get_record(self, model, record_id):
        assert model == "ReviewRequest"
        return self.reviews.get(record_id)

    def create_record(self, model, record):
        self.reviews[record["id"]] = dict(record)
        return record


def history_of(costs):
    logs = [spend_ledger.log_micro_usd(Decimal(str(cost))) for cost in costs]
    return spend_ledger.CostHistory(len(logs), sum(logs, Decimal(0)), sum((log * log for log in logs), Decimal(0)))


def spend(cost, *, responsibility="rate", unpriced=0, per_run=None):
    return {"tenantId": "alpha", "responsibility": responsibility, "period": "week", "costUsd": cost, "calls": 2, "unpricedCalls": unpriced,
            "budgetUsdPerRun": per_run}


@pytest.mark.parametrize("degrees, expected", [(1, 318.309), (2, 22.327), (10, 4.144), (30, 3.385), (1000, 3.098)])
def test_the_t_quantile_matches_the_published_table(degrees, expected):
    assert unusual_cost.student_t_upper_quantile(0.001, degrees) == pytest.approx(expected, abs=0.001)


def test_too_little_history_is_never_judged():
    for costs in ([], [0.01]):
        judgement = unusual_cost.judge(history_of(costs), 5.0)
        assert not judgement.judged and not judgement.unusual and judgement.bound_usd is None


def test_a_history_with_no_spread_is_not_judged():
    judgement = unusual_cost.judge(history_of([0.02] * 8), 5.0)
    assert not judgement.judged and "cost the same" in judgement.reason


def test_the_bound_widens_when_the_history_is_short():
    spread = [0.010, 0.012, 0.014]
    short = unusual_cost.judge(history_of(spread), 0.02)
    long = unusual_cost.judge(history_of(spread * 10), 0.02)
    assert short.bound_usd > long.bound_usd and not short.unusual and long.unusual


def test_a_run_is_flagged_once_and_joins_the_history_once():
    table, client = FakeLedgerTable(), Reviews()
    for number, cost in enumerate([0.010, 0.011, 0.012, 0.013, 0.014, 0.012]):
        spend_ledger.record_run(table, tenant_id="alpha", responsibility="rate", run_id=f"r{number}", period="week", cost_usd=cost, calls=1,
                                unpriced_calls=0, moment=MOMENT, add_to_history=True)
    result = {"runId": "run|with:odd chars", "spend": spend(0.5)}
    first = unusual_cost.watch_run(table, client, result, moment=MOMENT, emit=lambda line: None)
    second = unusual_cost.watch_run(table, client, result, moment=MOMENT, emit=lambda line: None)
    assert first["unusual"] and first["counted"] and not second["counted"]
    assert list(client.reviews) == [unusual_cost.flag_id("run|with:odd chars")]
    assert spend_ledger.cost_history(table, tenant_id="alpha", responsibility="rate").runs == 7


def test_a_partly_priced_run_is_not_judged_and_stays_out_of_the_history_but_is_counted():
    table, client = FakeLedgerTable(), Reviews()
    decided = unusual_cost.watch_run(table, client, {"runId": "r1", "spend": spend(0.02, unpriced=1)}, moment=MOMENT, emit=lambda line: None)
    assert not decided["judged"] and "no price" in decided["reason"] and decided["counted"]
    assert spend_ledger.cost_history(table, tenant_id="alpha", responsibility="rate").runs == 0
    assert spend_ledger.spent(table, tenant_id="alpha", scope="ai", period="week", moment=MOMENT).partial


def test_a_partly_priced_run_over_the_per_run_budget_is_flagged_as_at_least_that():
    table, client = FakeLedgerTable(), Reviews()
    decided = unusual_cost.watch_run(table, client, {"runId": "r1", "spend": spend(0.30, unpriced=1, per_run=0.25)}, moment=MOMENT, emit=lambda line: None)
    (flag,) = client.reviews.values()
    assert decided["overBudget"] and "(at least: 1 call had no price)" in flag["reason"] and "over the owner's budget of $0.2500 per run" in flag["reason"]


def test_a_run_no_agent_made_has_no_history_to_judge():
    table = FakeLedgerTable()
    decided = unusual_cost.watch_run(table, Reviews(), {"runId": "r1", "spend": spend(0.02, responsibility=None)}, moment=MOMENT, emit=lambda line: None)
    assert not decided["judged"] and "no agent" in decided["reason"]


def test_a_run_with_no_model_call_is_not_watched():
    assert unusual_cost.watch_run(FakeLedgerTable(), Reviews(), {"runId": "r1", "spend": None}) is None


def test_the_history_takes_only_fully_priced_runs_above_zero():
    with pytest.raises(spend_ledger.SpendError):
        spend_ledger.record_run(FakeLedgerTable(), tenant_id="alpha", responsibility="rate", run_id="r", period="week", cost_usd=0, calls=1,
                                unpriced_calls=0, moment=MOMENT, add_to_history=True)


def test_the_per_run_budget_is_a_positive_number_of_dollars_in_the_policy():
    validate_agent("rate", {"rung": "propose", "budgetUsdPerRun": 0.25})
    for value in (0, -1, "1", True):
        with pytest.raises(PolicyError, match="budgetUsdPerRun"):
            validate_agent("rate", {"rung": "propose", "budgetUsdPerRun": value})
