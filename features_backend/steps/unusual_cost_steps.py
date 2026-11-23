"""An unusually costly run is flagged from the agent's own history, and never stopped (features_backend/agents/unusual-cost.feature).

The site, its policy, its ledger and the runner's clock come from the spend stop's steps (spend_stop_steps.py): the same Background sentences build them."""
from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS = REPO_ROOT / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_procedure_runner as tpr  # noqa: E402
from papyrus_content import agent_wakes, procedure_runner as pr, spend_ledger, unusual_cost  # noqa: E402
from papyrus_content.agent_definitions import cli as agents_cli  # noqa: E402
from papyrus_content.agent_policy import PolicyGate  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.spend_brake import SpendBrake  # noqa: E402

TENANT, BUCKET, AGENT = "alpha", "site-bucket", "rate"
PEOPLE = {"admin": Caller(kind="person", subject="ada", is_admin=True), "agent": Caller(kind="agent", subject="rating-agent")}
TOKENS_PER_CENT = 100_000   # gpt-6-luna input is $0.10 a million tokens below 272,000 in one call
TOKENS_PER_CALL = 200_000


def utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def calls_costing(cents: Decimal) -> list[dict]:
    """Model calls whose estimated cost is ``cents``, each small enough to stay on the model's first price tier."""
    tokens, calls = int(cents * TOKENS_PER_CENT), []
    while tokens > 0:
        calls.append({"agent": "rater", "model": "gpt-6-luna", "provider": "openai", "promptTokens": min(tokens, TOKENS_PER_CALL), "completionTokens": 0, "cachedTokens": 0})
        tokens -= TOKENS_PER_CALL
    return calls


def wake_request(key):
    return {**tpr.REQUEST, "procedureKey": "papyrus.rate", "wakeKey": key, "tenantId": TENANT, "siteBucket": BUCKET, "publicationId": "alpha",
            "input": {}, "trigger": {"kind": "schedule", "automationId": AGENT, "summary": f"Scheduled run of {AGENT}", "serialBy": "agent"}}


def cost_flags(context):
    return {request_id: flag for request_id, flag in context.client.reviews.items() if request_id.startswith("rr-run-cost-")}


def history(context):
    return spend_ledger.cost_history(context.ledger, tenant_id=TENANT, responsibility=AGENT)


@given('the "{agent}" agent\'s last {count:d} runs cost between {low} and {high} cents each')
@given('the "{agent}" agent\'s last {count:d} run cost {low} cents')
def earlier_runs(context, agent, count, low, high=None):
    low, high = Decimal(low), Decimal(high if high is not None else low)
    for number in range(count):
        cents = low + (high - low) * number / max(count - 1, 1)
        spend_ledger.record_run(context.ledger, tenant_id=TENANT, responsibility=agent, run_id=f"earlier-{number}", period="week", cost_usd=cents / 100,
                                calls=1, unpriced_calls=0, moment=utc("2026-10-01T12:00:00Z") + timedelta(hours=number), add_to_history=True)


def per_run_budget(context, who, agent, dollars, reason):
    argv = ["--agent", agent, "--per-run", dollars, "--reason", reason, "--apply"]
    out = io.StringIO()
    context.exit_code = agents_cli.set_budget_command(argv, out, client_factory=lambda: context.client, policy_factory=lambda client: context.policy,
                                                      caller_factory=lambda client, caller: PEOPLE[who])
    context.envelope = json.loads(out.getvalue())


@given('an admin sets the "{agent}" agent\'s budget per run to {dollars} dollars because "{reason}" and applies it')
def admin_sets_per_run_budget(context, agent, dollars, reason):
    per_run_budget(context, "admin", agent, dollars, reason)
    assert context.exit_code == 0, context.envelope
    assert context.policy.read(TENANT).document["agents"][agent]["budgetUsdPerRun"] == float(dollars)


@when('an agent sets the "{agent}" agent\'s budget per run to {dollars} dollars because "{reason}" and applies it')
def agent_sets_per_run_budget(context, agent, dollars, reason):
    per_run_budget(context, "agent", agent, dollars, reason)


@when('the paid wake "{key}" arrives and its run costs {cents} cents')
def costly_run(context, key, cents):
    request = agent_wakes.request_from_event({"Records": [{"eventSource": "aws:sqs", "body": agent_wakes.message_body(wake_request(key))}]})

    def execute(*args, **kwargs):
        context.executed.append(request["wakeKey"])
        return {"success": True, "output": {"title": "rated"}, "seconds": 1, "usage": calls_costing(Decimal(cents))}

    brake = SpendBrake(context.ledger, default_budget=Decimal("100"), clock=lambda: utc(context.clock))
    gate = PolicyGate(context.client, policy=context.policy, tenant_id=TENANT)
    context.result = pr.run_procedure_request(request, client=context.client, policy=gate, execute=execute, seconds_available=900, environment={},
                                              spend_brake=brake)
    assert round(context.result["costUsd"] * 100, 6) == float(cents), context.result
    context.cost_lines = []
    context.judgement = pr.unusual_cost.watch_run(context.ledger, context.client, context.result, moment=utc(context.clock), emit=context.cost_lines.append)


@when("the same run's spend is recorded again, as a redelivered wake would")
def recorded_again(context):
    context.second_judgement = unusual_cost.watch_run(context.ledger, context.client, context.result, moment=utc(context.clock), emit=context.cost_lines.append)


@then("the cost of that run was judged against {count:d} earlier runs and is not unusual")
def judged_usual(context, count):
    judgement = context.judgement
    assert judgement["judged"] and not judgement["unusual"] and judgement["earlierRuns"] == count, judgement
    assert judgement["typicalUsd"] < judgement["costUsd"] < judgement["boundUsd"], judgement
    assert json.loads(context.cost_lines[-1])["unusualCost"] == "judged", context.cost_lines


@then('the cost of that run was not judged, because "{reason}"')
def not_judged(context, reason):
    judgement = context.judgement
    assert not judgement["judged"] and not judgement["unusual"] and reason in judgement["reason"], judgement
    assert judgement["boundUsd"] is None, judgement   # no bound is made up from too little history
    assert json.loads(context.cost_lines[-1])["unusualCost"] == "not judged", context.cost_lines


@then("the admins were sent no cost flag")
def no_cost_flag(context):
    assert not cost_flags(context), cost_flags(context)
    assert context.judgement["flag"] is None, context.judgement


@then('the admins have exactly one cost flag, for the run of "{key}"')
def one_cost_flag(context, key):
    flags = cost_flags(context)
    run_id = "run-for-" + key
    assert list(flags) == [unusual_cost.flag_id(run_id)], flags
    flag = flags[unusual_cost.flag_id(run_id)]
    assert flag["mode"] == "flag" and flag["state"] == "open" and json.loads(flag["subject"]) == {"type": "automation_run", "id": run_id}, flag
    context.flag = flag


@then('the flag says the run cost "{cost}" against "{earlier}", with what such a run typically costs and the cost passed one time in 1,000')
def flag_figures(context, cost, earlier):
    reason, judgement = context.flag["reason"], context.judgement
    assert judgement["unusual"] and judgement["costUsd"] > judgement["boundUsd"], judgement
    for figure in (f"cost {cost}", earlier, f"${judgement['typicalUsd']:.4f} typically", f"more than ${judgement['boundUsd']:.4f} only one time in 1,000"):
        assert figure in reason, (figure, reason)


@then('the flag says the run is over the owner\'s budget of "{budget}" per run')
def flag_over_budget(context, budget):
    assert f"over the owner's budget of {budget} per run" in context.flag["reason"], context.flag["reason"]
    assert context.judgement["overBudget"] and not context.judgement["unusual"], context.judgement


@then("the flag says the run was not stopped")
def flag_not_stopped(context):
    assert "The run was not stopped." in context.flag["reason"] and "Nothing waits on this flag" in context.flag["ask"], context.flag
    assert context.result["runStatus"] == "completed" and not context.result.get("waiting"), context.result


@then('the "{agent}" agent\'s history holds {count:d} runs')
def history_holds(context, agent, count):
    assert spend_ledger.cost_history(context.ledger, tenant_id=TENANT, responsibility=agent).runs == count


@then("the site's ledger counted that run once")
def counted_once(context):
    assert context.judgement["counted"] is True and context.second_judgement["counted"] is False, (context.judgement, context.second_judgement)
    spent = spend_ledger.spent(context.ledger, tenant_id=TENANT, scope="ai", period="week", moment=utc(context.clock))
    assert spent.usd == Decimal("0.4"), spent


@then('the agent policy holds no budget per run for the "{agent}" agent')
def no_per_run_budget(context, agent):
    assert "budgetUsdPerRun" not in (context.policy.read(TENANT).document["agents"].get(agent) or {})
