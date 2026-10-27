from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_router as tr  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, run_collection  # noqa: E402
from papyrus_content.monitoring_router import RouterStore  # noqa: E402

STORIES = (101, 102, 103)


def posts(context):
    return [c for c in context.cyclotron.combined_calls if c[0] == "POST"]


def posted_items(context):
    return sorted(c[2]["payload"]["item"]["id"] for c in posts(context))


def route_run(context, now=2000, task=None):
    context.result = tr.run_with(context.table_, context.store, context.cyclotron, now=now, deliver=context.delivery, task=task)


@given("a router that may take up to three stories per run, with a combined Cyclotron endpoint")
def step_router(context):
    context.table_ = tr.FakeTable()
    context.table_.put_item(tr.COLLECTOR_CONFIG)
    context.table_.put_item(tr.router_config(maxItemsPerRun=3))
    context.store, context.cyclotron, context.delivery = RouterStore(context.table_), tr.FakeCyclotron(), tr.Delivery()
    context.cyclotron.combined_enabled = True


@given("the monitor has collected three stories")
def step_collected(context):
    run_collection(DynamoStore(context.table_), "hn", fetch=lambda url: tr.FEED, now=1000)


@given("the router may take only one story per run")
def step_one_per_run(context):
    context.table_.put_item(tr.router_config(maxItemsPerRun=1))


@given("Cyclotron does not have the combined endpoint")
def step_no_combined(context):
    context.cyclotron.combined_enabled = False


@given("the lab takes longer than the run's collect window to answer")
def step_slow(context):
    context.cyclotron.polls_needed = 10_000


@given("the lab answers each job after a few checks")
def step_few(context):
    context.cyclotron.polls_needed = 3


@given("Cyclotron is busy with another run when the router posts")
def step_busy(context):
    context.cyclotron.combined_post_override = (409, {"code": "run_busy"})


@given("the route task has run once")
def step_ran_once(context):
    route_run(context)


@given("the route run holds the router lock")
def step_route_lock(context):
    assert context.store.acquire_router_lock("hn", "route-run", 2000)


@given("the collector holds the router lock")
def step_collector_lock(context):
    assert context.store.acquire_router_lock("hn", "collector", 2000)


@when("the route task runs")
def step_run(context):
    route_run(context, now=2010)


@when("the lab has answered and the route task runs again")
def step_run_again(context):
    context.cyclotron.polls_needed = 0
    route_run(context, now=2900)


@when("the lab has answered and the collector runs")
def step_collect(context):
    context.cyclotron.polls_needed = 0
    route_run(context, now=2200, task="collect")


@when("the collector runs")
def step_collector(context):
    route_run(context, now=2010, task="collect")


@then("the lab received one decision request for each of the three stories")
@then("the lab still received only one decision request for each of the three stories")
def step_three_posts(context):
    assert posted_items(context) == ["hn-101", "hn-102", "hn-103"]


@then("the run ends with the status awaiting and counts three stories awaiting")
def step_awaiting_three(context):
    assert context.result["status"] == "awaiting" and context.result["stoppedBy"] == "awaiting"
    assert context.result["counts"]["awaiting"] == 3


@then("the run ends with the status awaiting and counts one story awaiting")
def step_awaiting_one(context):
    assert context.result["status"] == "awaiting" and context.result["counts"]["awaiting"] == 1


@then("all three stories are still waiting for the router with their jobs recorded")
def step_waiting(context):
    assert set(tr.routing_of(context.table_).values()) == {"collected"}
    for n in STORIES:
        assert context.table_.items[("MONITOR#hn", f"ROUTE#{n}#000001")]["combinedJob"]["jobId"]


@then("nothing was delivered")
def step_nothing(context):
    assert context.delivery.calls == []


@then("all three stories are routed and delivered to every publication")
def step_all_routed(context):
    assert set(tr.routing_of(context.table_).values()) == {"routed"}
    assert len(context.delivery.calls) == 9


@then("the run ends complete with nothing awaiting")
def step_complete(context):
    assert context.result["status"] == "complete" and context.result["counts"]["awaiting"] == 0


@then("the collector did not examine feedback")
def step_no_feedback(context):
    assert context.result["feedback"] == {"status": "skipped"}


@then("the first story is routed")
def step_first_routed(context):
    assert tr.routing_of(context.table_)["DISC#101#000001"] == "routed"


@then("the other two stories were never sent to the lab")
def step_others_unsent(context):
    assert posted_items(context) == ["hn-101"]
    assert tr.routing_of(context.table_)["DISC#102#000001"] == "collected"
    assert ("MONITOR#hn", "ROUTE#102#000001") not in context.table_.items


@then("the collector reports that the router is locked")
@then("the router reports that it is locked")
def step_locked(context):
    assert context.result["status"] == "locked"


@then("the lab received no requests")
def step_no_requests(context):
    assert context.cyclotron.combined_calls == [] and context.cyclotron.calls == []


@then("the lab received one request for each publication of the first story")
@then("the lab still received only one request for each publication of the first story")
def step_per_publication(context):
    assert sorted(c[1].split("/")[3] for c in context.cyclotron.posts()) == sorted(tr.PUBS)


@then("the run ends stopped because Cyclotron is busy")
def step_stopped(context):
    assert context.result["status"] == "stopped" and context.result["stoppedBy"] == "run_busy"
