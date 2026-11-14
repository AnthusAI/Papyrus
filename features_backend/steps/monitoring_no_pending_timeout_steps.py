from behave import given, then, when

from papyrus_content import monitoring_router as mr
import test_monitoring_router as tr  # noqa: F401  (path set by monitoring_post_then_collect_steps)
from monitoring_post_then_collect_steps import route_run


def finalize(context, number, reason):
    route = context.table_.items[("MONITOR#hn", f"ROUTE#{number}#000001")]
    route["final"] = {"routing": "error", "reason": reason, "at": "2026-10-27T00:00:00Z"}
    mr.set_routing(context.store, "hn", context.table_.items[("MONITOR#hn", f"DISC#{number}#000001")], "error", None)


@given("an earlier age limit finalized the first story as an error with its job still recorded")
def step_stale(context):
    finalize(context, 101, mr.STALE_FINAL_REASON)


@given("the second story was finalized as an error for another reason")
def step_other(context):
    finalize(context, 102, "lab does not know the job posted for this story (404 after a re-post)")


@when("the collector runs a month later while the lab is still working")
def step_month(context):
    route_run(context, now=2000 + 30 * 86400, task="collect")


@when("the lab has answered and the collector runs a day later")
def step_day_later(context):
    context.cyclotron.polls_needed = 0
    route_run(context, now=2000 + 31 * 86400, task="collect")


@when("the reopen-stale-finals task runs")
def step_reopen(context):
    route_run(context, now=2100, task="reopen-stale-finals")


@then("no story has a final outcome")
def step_no_final(context):
    assert not [k for k, v in context.table_.items.items() if k[1].startswith("ROUTE#") and v.get("final")]


@then("the task reports one story reopened")
def step_one(context):
    assert context.result["reopened"] == 1


@then("the task reports no story reopened")
def step_none(context):
    assert context.result["reopened"] == 0


@then("the first story is waiting for the router again with its job kept")
def step_waiting_again(context):
    route = context.table_.items[("MONITOR#hn", "ROUTE#101#000001")]
    disc = context.table_.items[("MONITOR#hn", "DISC#101#000001")]
    assert "final" not in route and route["combinedJob"]["jobId"]
    assert disc["routing"] == "collected" and disc["gsi1pk"] == "ROUTING#hn#collected"


@then("the second story is still finalized as an error")
def step_second(context):
    assert context.table_.items[("MONITOR#hn", "ROUTE#102#000001")]["final"]["routing"] == "error"
    assert "gsi1pk" not in context.table_.items[("MONITOR#hn", "DISC#102#000001")]
