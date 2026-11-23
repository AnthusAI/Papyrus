"""Monitor stories under the spend ledger, the site's budget and the unusual-cost flag (features_backend/monitoring/monitor-stories-spend.feature, PPY-45c2ef).

The router, the queue, the site and the model are the queue scenarios' own (monitoring_stories_queue_steps.py): the same Background builds them, with one fake
ledger table, one site policy and one clock for every run of a scenario."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

from behave import given, then, when

from monitor_stories_spend_fixture import TENANT  # noqa: E402  (the queue steps put the tests directory on the path)
from papyrus_content import spend_ledger, unusual_cost  # noqa: E402
from papyrus_content.ideas import story_plan  # noqa: E402
from papyrus_content.ideas.review import RAISED_BY as CURATION_RAISED_BY  # noqa: E402
from papyrus_content.monitor_stories_spend import DRAFTING_RESPONSIBILITY, INDEX_RESPONSIBILITY, site_policy_from_bucket  # noqa: E402
from papyrus_content.monitoring_vectors import EMPTY_RESULT  # noqa: E402


def held(context):
    return context.queue


def month_of(context):
    return spend_ledger.spent(held(context).ledger, tenant_id=TENANT, scope="ai", period="month", moment=held(context).clock[0])


def agent_month(context, agent):
    return spend_ledger.spent(held(context).ledger, tenant_id=TENANT, scope=f"ai:{agent}", period="month", moment=held(context).clock[0])


def done_rows(context):
    state = held(context)
    plan_id = state.sqs.sent[0]["body"]["planId"]
    return state.store.query_prefix("hn", story_plan.done_prefix(state.publication, plan_id))


def reviews(context):
    return held(context).client.reviews


@given("every model call reports {tokens:d} input tokens")
def step_costly_calls(context, tokens):
    held(context).model.usage = {"input_tokens": tokens, "output_tokens": 400, "input_tokens_details": {"cached_tokens": 0}}


@given('the "{agent}" agent\'s last {count:d} runs on the site cost between {low} and {high} cents each')
def step_history(context, agent, count, low, high):
    low, high = Decimal(low), Decimal(high)
    for number in range(count):
        cents = low + (high - low) * number / max(count - 1, 1)
        spend_ledger.record_run(held(context).ledger, tenant_id=TENANT, responsibility=agent, run_id=f"earlier-{number}", period="month", cost_usd=cents / 100,
                                calls=1, unpriced_calls=0, moment=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(hours=number), add_to_history=True)


@given("the site has spent its budget of {amount:d} dollars for this month")
@when("the site has spent its budget of {amount:d} dollars for this month")
def step_budget_spent(context, amount):
    state = held(context)
    spend_ledger.record_run(state.ledger, tenant_id=TENANT, responsibility=None, run_id="other-paid-work", period="month", cost_usd=Decimal(amount), calls=1,
                            unpriced_calls=0, moment=state.clock[0])


@given('runs are halted for the site because "{reason}"')
def step_halted(context, reason):
    spend_ledger.set_halt(held(context).ledger, tenant_id=TENANT, reason=reason, by="ada", moment=held(context).clock[0])


@given("a vector pass that makes {requests:d} embedding requests costing {dollars} dollars")
def step_vector_pass(context, requests, dollars):
    def vector_pass(client, publication, policy, **options):
        return {**EMPTY_RESULT, "timings": {"passSeconds": 0.1}, "indexed": 2, "costUsd": float(dollars), "embeddingRequests": requests}

    patch = mock.patch("papyrus_content.monitoring_vectors.run_vector_pass", vector_pass)
    patch.start()
    context.add_cleanup(patch.stop)


class NoBucketReads:
    """An S3 client that fails the scenario if the site's bucket is read: the router entry does not say which bucket it is."""

    def get_object(self, **request):
        raise AssertionError(f"the site's bucket was read: {request}")


@given("the router reads each publication's site and policy from its router entry, as the Lambda does")
def step_lambda_site_policy(context):
    held(context).spend.site_policy = site_policy_from_bucket(NoBucketReads())


@when("the month turns and the router plans its daily monitor stories")
def step_month_turns(context):
    state = held(context)
    state.clock[0] = datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc)
    context.execute_steps("When the router plans its daily monitor stories the next day")


@when("the story worker takes every step of that plan off the queue")
def step_work_second_plan(context):
    from monitoring_stories_queue_steps import work

    state = held(context)
    work(state, state.next_sqs.sent)


@then("the site's spend this month holds the model calls and the cost of the {count:d} drafted steps, each counted once")
def step_counted_once(context, count):
    rows = [row for row in done_rows(context) if row.get("status") == "drafted"]
    assert len(rows) == count, rows
    calls = sum(int(row["spend"]["calls"]) for row in rows)
    micro = sum(spend_ledger.micro_usd(row["spend"]["costUsd"]) for row in rows)
    site, agent = month_of(context), agent_month(context, DRAFTING_RESPONSIBILITY)
    assert calls > 0 and (site.calls, site.microUsd) == (calls, micro) == (agent.calls, agent.microUsd), (site, agent, calls, micro)


@then('the "{agent}" agent\'s cost history holds {count:d} runs')
def step_history_holds(context, agent, count):
    assert spend_ledger.cost_history(held(context).ledger, tenant_id=TENANT, responsibility=agent).runs == count


@then('the "{agent}" agent\'s spend this month is more than {dollars} dollars')
def step_spend_above(context, agent, dollars):
    spent = agent_month(context, agent)
    assert spent.usd > Decimal(dollars) and not spent.partial, spent


@then("the admins have exactly one cost flag, and it says the run was not stopped")
def step_one_cost_flag(context):
    flags = [request for request in reviews(context).values() if request["id"].startswith("rr-run-cost-")]
    assert len(flags) == 1, flags
    [flag] = flags
    assert flag["mode"] == "flag" and flag["raisedBy"] == unusual_cost.FLAG_RAISED_BY and "The run was not stopped." in flag["reason"], flag
    assert DRAFTING_RESPONSIBILITY in flag["reason"] and "far above the agent's own history" in flag["reason"], flag["reason"]


@then("nothing is on the story queue and the model is not asked")
def step_nothing_queued(context):
    state = held(context)
    later_plan = getattr(state, "next_sqs", None)
    assert not state.sqs.sent and not (later_plan and later_plan.sent), (state.sqs.sent, later_plan and later_plan.sent)
    assert not state.model.requests and not state.client.filed, (len(state.model.requests), len(state.client.filed))


@then('the log line for "{publication}" says it waits for the budget cycle until "{due_at}"')
def step_waits_line(context, publication, due_at):
    lines = held(context).lines
    assert lines and all(line["status"] == "waiting" and line["reasonCode"] == "budget_reached" and line["dueAt"] == due_at for line in lines), lines
    assert "Paid work waits until the next month starts" in lines[-1]["reason"], lines[-1]["reason"]


@then('the admins have exactly one budget flag, for the month that started on "{start}"')
def step_one_budget_flag(context, start):
    flags = [request for request in reviews(context).values() if request["id"].startswith("rr-budget-")]
    assert [flag["id"] for flag in flags] == [f"rr-budget-month-{start}"], flags


@then("every step logs that it waits for the budget cycle")
def step_steps_wait(context):
    steps = [line for line in held(context).logs if "monitorStoriesStep" in line]
    assert steps and all(line["monitorStoriesStep"] == "waiting" and line["reasonCode"] == "budget_reached" for line in steps), steps


@then('the worker logs that the plan finished with {drafted:d} drafted and {count:d} steps held back by "{reason}"')
def step_finished_held_back(context, drafted, count, reason):
    [finished] = [line for line in held(context).logs if line.get("monitorStories") == "finished"]
    assert (finished["drafted"], finished["heldBackSteps"], finished["heldBackBy"], finished["failedSteps"]) == (drafted, count, reason, 0), finished


@then("no curation flag is raised")
def step_no_curation_flag(context):
    assert not [request for request in reviews(context).values() if request.get("raisedBy") == CURATION_RAISED_BY and request.get("mode") == "flag"], reviews(context)


@then('the log line for "{publication}" says monitor stories did not start because "{code}"')
def step_not_started(context, publication, code):
    line = held(context).lines[-1]
    assert line["status"] == "not_started" and line["reasonCode"] == code, line


@then('the log line for "{publication}" names the missing "{first}" and "{second}" as why monitor stories did not start, with the code "{code}"')
def step_not_started_naming(context, publication, code, first, second):
    line = held(context).lines[-1]
    assert line["status"] == "not_started" and line["reasonCode"] == code and first in line["reason"] and second in line["reason"], line


@then('the "{agent}" agent\'s spend this month is {calls:d} calls and {dollars} dollars')
def step_agent_spend_exact(context, agent, calls, dollars):
    spent = agent_month(context, agent)
    assert (spent.calls, spent.microUsd) == (calls, spend_ledger.micro_usd(dollars)), spent


@then("the site's spend this month includes the vector pass")
def step_site_includes_index(context):
    assert month_of(context).microUsd >= agent_month(context, INDEX_RESPONSIBILITY).microUsd > 0
