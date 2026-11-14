from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_router as tr  # noqa: E402


@given("the router holds decisions")
def step_hold(context):
    context.sent_before_hold = len(context.cyclotron.posts())
    context.table_.items[("MONITOR#hn", "CONFIG#router")]["holdDecisions"] = True


@then("no decision request was sent after the hold")
def step_no_decide(context):
    after = context.cyclotron.posts()[context.sent_before_hold:]
    assert after and all(c[2]["operation"] == "feedback" for c in after), after


@given("a live router with a collected story that holds decisions")
def step_collected(context):
    context.table_ = tr.collected_table(tr.ONE_FEED)
    context.store, context.cyclotron = tr.setup_router(context.table_, holdDecisions=True)


@when("the held router runs")
def step_run(context):
    context.result = tr.go(context.table_, context.store, context.cyclotron)


@then("no decision request was sent by the held router")
def step_none(context):
    assert context.cyclotron.posts() == []


@then("the receipt says decisions were held")
def step_receipt(context):
    assert context.result["stoppedBy"] == "decisions_held"


@given("a live router with three collected stories and a combined decision endpoint")
def step_three_combined(context):
    context.table_ = tr.collected_table(tr.FEED)
    context.store, context.cyclotron = tr.setup_router(context.table_)
    context.cyclotron.combined_enabled = True


@given("a live router with three collected stories and no combined endpoint")
def step_three_plain(context):
    context.table_ = tr.collected_table(tr.FEED)
    context.store, context.cyclotron = tr.setup_router(context.table_)


@when("the router runs as a canary allowed one decision")
def step_canary_one(context):
    context.result = tr.go(context.table_, context.store, context.cyclotron, max_decisions=1)


@when("the router runs as a canary allowed two decisions")
def step_canary_two(context):
    context.result = tr.go(context.table_, context.store, context.cyclotron, max_decisions=2)


@when("the router runs as a canary allowed one decision with the hold overridden")
def step_canary_override(context):
    context.result = tr.go(context.table_, context.store, context.cyclotron, max_decisions=1, hold_override=True)


@when("the router runs normally")
def step_normal(context):
    context.result = tr.go(context.table_, context.store, context.cyclotron)


def sent_count(context):
    return len(context.cyclotron.posts()) + len([c for c in context.cyclotron.combined_calls if c[0] == "POST" and context.cyclotron.combined_enabled])


@then("exactly one decision request was sent")
def step_exactly_one(context):
    assert sent_count(context) == 1


@then("exactly two decision requests were sent")
def step_exactly_two(context):
    assert sent_count(context) == 2


@then("nine decision requests were sent")
def step_nine(context):
    assert sent_count(context) == 9


@then("the receipt says the run stopped by max decisions")
def step_max_receipt(context):
    receipt = [v for k, v in context.table_.items.items() if k[1].startswith("ROUTERUN#")][0]
    assert context.result["stoppedBy"] == receipt["stoppedBy"] == "max_decisions"


@then("the run was not stopped by max decisions")
def step_not_max(context):
    assert context.result["stoppedBy"] != "max_decisions"


@then("the result names the posted request and job")
def step_posted(context):
    assert len(context.result["posted"]) == 1
    assert all(context.result["posted"][0][key] for key in ("requestId", "jobId", "sourceId"))


@then("the stored configuration still holds decisions")
def step_config_holds(context):
    assert context.table_.items[("MONITOR#hn", "CONFIG#router")]["holdDecisions"] is True


@then("a later normal run posts nothing and says decisions were held")
def step_later(context):
    before = sent_count(context)
    assert tr.go(context.table_, context.store, context.cyclotron, now=3000)["stoppedBy"] == "decisions_held"
    assert sent_count(context) == before
