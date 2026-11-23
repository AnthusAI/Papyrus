"""Unusual cost is flagged from the agent's own history, and never stopped (PPY-eef85d, slice G3 of docs/design/always-on-agents-architecture.md).

Ryan's ruling: an unusually costly run flags a person and is never stopped. "Unusual" is learned, not set: each finished run is judged against every earlier
fully priced run of the same agent on the same site, as the spend ledger keeps them (``spend_ledger.CostHistory``: how many runs, and the sum and the sum of
squares of the natural logarithm of each run's cost).

**The statistic.** The cost of an agent's runs is a product of many factors (the size of the input, how many calls, how long the answers), so it is skewed
to the right and its logarithm is close to normal; the history is summarised by the mean and the standard deviation of the log costs. A run is unusual when
its log cost is above the one-sided upper prediction bound for one more run from that history, at a tail probability of one in a thousand::

    bound = mean + t(1 - 1/1000, n - 1) * standard deviation * sqrt(1 + 1/n)

where ``n`` is the number of earlier runs and ``t`` is Student's t quantile. A run from the same history lands above the bound one time in a thousand, and the
bound widens by itself when the history is short, so a young agent is not flagged for ordinary variation. Two earlier runs are the fewest that have a spread
at all; with fewer, or when every earlier run cost the same, the judgement says that the history is too short to judge and raises nothing: it never guesses.

**The owner's per-run budget.** ``agents.<responsibility>.budgetUsdPerRun`` in the agent policy is the owner's own figure. A run over it is flagged too, and is
not stopped either. A run that is unusual and over the budget raises one flag that says both.

**One flag a run.** The flag is a ReviewRequest (mode ``flag``) whose id comes from the run id, so a redelivered wake finds the flag and raises no other. It is
raised before the run is added to the ledger: a failure in between leaves the wake on the queue, and its next delivery judges against the same history and finds
the same flag.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from . import spend_ledger

TAIL_PROBABILITY = 0.001   # "far outside the distribution": one run in a thousand from the same history lands above the bound
FEWEST_EARLIER_RUNS = 2   # a standard deviation needs two values
SPREAD_BELOW_STORED_PRECISION = 2 * float(spend_ledger.LOGARITHM_PLACES)   # a variance smaller than this is rounding in the stored sums: the earlier runs cost the same
FLAG_RAISED_BY = "AI cost"
FLAG_SUBJECT_TYPE = "automation_run"


@dataclass(frozen=True)
class CostJudgement:
    """What the history says about one run's cost. ``judged`` is False when there was nothing to judge against, and ``reason`` then says why in words."""
    judged: bool
    unusual: bool
    cost_usd: float
    earlier_runs: int
    typical_usd: float | None = None   # the geometric mean of the earlier runs' costs
    bound_usd: float | None = None   # the cost above which one run in a thousand from the same history lands
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"judged": self.judged, "unusual": self.unusual, "costUsd": self.cost_usd, "earlierRuns": self.earlier_runs, "typicalUsd": self.typical_usd,
                "boundUsd": self.bound_usd, "reason": self.reason}


def _continued_fraction_for_incomplete_beta(a: float, b: float, x: float) -> float:
    """Lentz's evaluation of the continued fraction of the regularized incomplete beta function (Numerical Recipes, betacf)."""
    tiny, converged = 1e-300, 3e-16
    c, d = 1.0, 1.0 - (a + b) * x / (a + 1.0)
    d = 1.0 / (d if abs(d) > tiny else tiny)
    fraction = d
    for m in range(1, 10_000):
        step = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        d = 1.0 + step * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + step / c
        c = c if abs(c) > tiny else tiny
        fraction *= d * c
        step = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + step * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + step / c
        c = c if abs(c) > tiny else tiny
        change = d * c
        fraction *= change
        if abs(change - 1.0) < converged:
            return fraction
    raise ArithmeticError("The incomplete beta function did not converge.")


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _continued_fraction_for_incomplete_beta(a, b, x) / a
    return 1.0 - front * _continued_fraction_for_incomplete_beta(b, a, 1.0 - x) / b


def student_t_upper_tail(t: float, degrees_of_freedom: int) -> float:
    """P(T > t) for Student's t with the given degrees of freedom, for t of zero or more."""
    return 0.5 * regularized_incomplete_beta(degrees_of_freedom / 2.0, 0.5, degrees_of_freedom / (degrees_of_freedom + t * t))


def student_t_upper_quantile(tail_probability: float, degrees_of_freedom: int) -> float:
    """The t whose upper tail is ``tail_probability`` (below one half), found by bisection on the tail."""
    low, high = 0.0, 1.0
    while student_t_upper_tail(high, degrees_of_freedom) > tail_probability:
        low, high = high, high * 2.0
    for _ in range(200):
        middle = (low + high) / 2.0
        if student_t_upper_tail(middle, degrees_of_freedom) > tail_probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _dollars(micro_logarithm: float) -> float:
    return math.exp(micro_logarithm) / float(spend_ledger.MICRO)


def judge(history: spend_ledger.CostHistory, cost_usd: float) -> CostJudgement:
    """Judge one fully priced run's cost against the agent's earlier runs."""
    runs = history.runs
    if runs < FEWEST_EARLIER_RUNS:
        return CostJudgement(False, False, cost_usd, runs, reason=(
            f"The agent has {runs} earlier priced run{'' if runs == 1 else 's'}; at least {FEWEST_EARLIER_RUNS} are needed to tell whether a cost is unusual, "
            "so this run's cost was not judged."))
    total, squares = float(history.sumLogMicroUsd), float(history.sumSquaredLogMicroUsd)
    mean = total / runs
    variance = (squares - total * total / runs) / (runs - 1)
    typical = _dollars(mean)
    if variance <= SPREAD_BELOW_STORED_PRECISION:
        return CostJudgement(False, False, cost_usd, runs, typical_usd=typical, reason=(
            f"All {runs} earlier priced runs of the agent cost the same (${typical:.4f}), so their spread is not known yet and this run's cost was not judged."))
    log_bound = mean + student_t_upper_quantile(TAIL_PROBABILITY, runs - 1) * math.sqrt(variance) * math.sqrt(1.0 + 1.0 / runs)
    bound = _dollars(log_bound)
    unusual = float(spend_ledger.log_micro_usd(cost_usd)) > log_bound
    return CostJudgement(True, unusual, cost_usd, runs, typical_usd=typical, bound_usd=bound, reason=(
        f"${cost_usd:.4f} against {runs} earlier runs, typically ${typical:.4f}; a run from that history costs more than ${bound:.4f} one time in "
        f"{round(1 / TAIL_PROBABILITY):,}."))


def flag_id(run_id: str) -> str:
    """The run's one cost flag. A run id may hold characters a review request id may not, so the id is a digest of it."""
    return f"rr-run-cost-{hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:24]}"


def _flag_reason(spend: Mapping[str, Any], run_id: str, judgement: CostJudgement, budget_usd_per_run: float | None) -> str:
    agent = spend.get("responsibility") or "an agent"
    partial = f" (at least: {spend['unpricedCalls']} call{'' if spend['unpricedCalls'] == 1 else 's'} had no price)" if spend.get("unpricedCalls") else ""
    findings = []
    if judgement.unusual:
        findings.append(f"far above the agent's own history: {judgement.earlier_runs} earlier runs cost ${judgement.typical_usd:.4f} typically, and a run from "
                        f"that history costs more than ${judgement.bound_usd:.4f} only one time in {round(1 / TAIL_PROBABILITY):,}")
    if budget_usd_per_run is not None and judgement.cost_usd > budget_usd_per_run:
        findings.append(f"over the owner's budget of ${budget_usd_per_run:.4f} per run")
    return f"Run {run_id} of {agent} cost ${judgement.cost_usd:.4f}{partial}: {'; and '.join(findings)}. The run was not stopped."


def raise_cost_flag(client: Any, spend: Mapping[str, Any], run_id: str, judgement: CostJudgement, budget_usd_per_run: float | None) -> dict[str, Any]:
    from .review_requests import raise_review

    return raise_review(
        client, subject={"type": FLAG_SUBJECT_TYPE, "id": run_id}, mode="flag", raised_by=FLAG_RAISED_BY,
        reason=_flag_reason(spend, run_id, judgement, budget_usd_per_run),
        ask="Look at what the run did and whether the cost was worth it. Nothing waits on this flag. An admin sets the agent's per-run budget with "
            "papyrus agents set-budget --agent.",
        request_id=flag_id(run_id))


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    return float(value) if value > 0 else None


def watch_run(table: Any, client: Any, result: Mapping[str, Any], *, moment: datetime | None = None, emit: Any = print) -> dict[str, Any] | None:
    """Judge a finished run's cost, flag it when it is unusual or over the owner's per-run budget, and add it to the spend ledger (and, when it is fully priced,
    to its agent's history), once. Returns what was decided, or None for a run that made no model call."""
    spend = result.get("spend")
    if table is None or not spend:
        return None
    run_id, responsibility = str(result["runId"]), spend.get("responsibility")
    cost_usd = float(spend.get("costUsd") or 0)
    fully_priced = bool(responsibility) and not spend.get("unpricedCalls") and cost_usd > 0
    if fully_priced:
        judgement = judge(spend_ledger.cost_history(table, tenant_id=spend["tenantId"], responsibility=responsibility), cost_usd)
    else:
        judgement = CostJudgement(False, False, cost_usd, 0, reason=(
            "The run was made by no agent, so it has no history to be judged against." if not responsibility else
            "Some of the run's calls had no price, so its cost is not known and was not judged." if spend.get("unpricedCalls") else
            "The run cost nothing that has a price, so there was nothing to judge."))
    budget_usd_per_run = _positive_number(spend.get("budgetUsdPerRun"))
    over_budget = budget_usd_per_run is not None and cost_usd > budget_usd_per_run
    flag = raise_cost_flag(client, spend, run_id, judgement, budget_usd_per_run) if judgement.unusual or over_budget else None
    counted = spend_ledger.record_run(table, tenant_id=spend["tenantId"], responsibility=responsibility, run_id=run_id, period=spend["period"],
                                      cost_usd=spend.get("costUsd"), calls=spend["calls"], unpriced_calls=spend.get("unpricedCalls", 0),
                                      moment=moment or datetime.now(timezone.utc), add_to_history=fully_priced)
    decided = {"runId": run_id, "responsibility": responsibility, "counted": counted, **judgement.as_dict(), "budgetUsdPerRun": budget_usd_per_run,
               "overBudget": over_budget, "flag": flag.get("id") if flag else None}
    emit(json.dumps({"unusualCost": "flagged" if flag else "judged" if judgement.judged else "not judged", "tenantId": spend.get("tenantId"), **decided}, default=str))
    return decided
