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
