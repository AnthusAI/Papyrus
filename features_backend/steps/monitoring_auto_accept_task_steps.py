import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_router as tr  # noqa: E402
from papyrus_content import monitoring_router as mr  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, run_collection  # noqa: E402


@given("a router with three publications")
def step_given(context):
    context.table_ = tr.FakeTable()
    context.table_.put_item(tr.COLLECTOR_CONFIG)
    run_collection(DynamoStore(context.table_), "hn", fetch=lambda url: tr.FEED, now=1000)
    context.store, context.cyclotron = tr.setup_router(context.table_)
    config = context.table_.items[("MONITOR#hn", "CONFIG#router")]
    context.publications = [p["publicationId"] for p in config["publications"]]
    assert len(context.publications) == 3
    context.passes = []
    context.started = []
    original = mr.run_auto_accept
    context.add_cleanup(setattr, mr, "run_auto_accept", original)   # the fake lives for this scenario only

    def fake(client, publication, policy, **kwargs):
        context.passes.append(publication["publicationId"])
        return {"publicationId": publication["publicationId"], "status": "ran", "accepted": 0}

    mr.run_auto_accept = fake


@given("automatic acceptance is switched off for the second publication")
def step_off(context):
    context.table_.items[("MONITOR#hn", "CONFIG#router")]["publications"][1]["autoAccept"] = {"enabled": False}


@given("the second publication's auto-accept run is in progress")
def step_in_progress(context):
    assert context.store.acquire_router_lock("hn", "other", now=1000, sk=f"LOCK#auto-accept#{context.publications[1]}")


def run(context, **kwargs):
    out = io.StringIO()
    with redirect_stdout(out):
        context.result = mr.run_router(context.store, "hn", now=1010, cyclotron=object(), appsync=lambda e: object(), deliver=tr.Delivery(),
                                       time_left=lambda: 600, fan_out=context.started.append, **kwargs)


@when("the router runs a routing pass")
def step_route(context):
    run(context, task="route")


@when("the router runs the auto-accept task without naming a publication")
def step_fan_out(context):
    run(context, task="auto-accept")


@when("the router runs the auto-accept task for the second publication")
def step_second(context):
    run(context, task="auto-accept", publication_id=context.publications[1])


@when("the router runs the auto-accept task for a publication the monitor does not list")
def step_unknown(context):
    run(context, task="auto-accept", publication_id="nowhere")


@then("no publication had an automatic acceptance pass in that run")
def step_none(context):
    assert context.passes == [] and context.result["autoAccept"] == {}


@then("it started one run for each of the three publications")
def step_started_all(context):
    assert context.started == context.publications and context.result["status"] == "fanned-out"
    assert context.passes == []


@then("it took no lock and wrote no receipt")
def step_no_lock(context):
    assert not [key for key in context.table_.items if key[1].startswith(("LOCK#", "ROUTERUN#"))]


@then("it started runs for the first and third publications only")
def step_started_two(context):
    assert context.started == [context.publications[0], context.publications[2]]


@then("only the second publication had an automatic acceptance pass")
def step_only_second(context):
    assert context.passes == [context.publications[1]] and list(context.result["autoAccept"]) == [context.publications[1]]


@then("the run is refused as an unknown publication and does nothing")
def step_refused(context):
    assert context.result["status"] == "error" and "nowhere" in context.result["reason"] and context.passes == []


@then("that run reports that it is locked")
def step_locked(context):
    assert context.result["status"] == "locked" and context.passes == []


@then("the routing lock is free")
def step_routing_free(context):
    assert context.store.acquire_router_lock("hn", "route", now=1010)


@then("the first publication's auto-accept lock is free")
def step_first_free(context):
    assert context.store.acquire_router_lock("hn", "first", now=1010, sk=f"LOCK#auto-accept#{context.publications[0]}")


@then("the stack has an hourly auto-accept schedule for the hn monitor and one for the web-distinctive monitor")
def step_schedules(context):
    resources = tr._template()["Resources"]
    inputs = {name: json.loads(resources[name]["Properties"]["Target"]["Input"]) for name in ("AutoAcceptSchedule", "DistinctiveAutoAcceptSchedule")}
    assert inputs == {"AutoAcceptSchedule": {"task": "auto-accept", "monitorId": "hn"},
                      "DistinctiveAutoAcceptSchedule": {"task": "auto-accept", "monitorId": "web-distinctive"}}
    assert all(resources[name]["Properties"]["ScheduleExpression"].endswith("* * ? *)") for name in inputs)   # minute N, every hour


@then("neither schedule retries a failed run")
def step_no_retry(context):
    resources = tr._template()["Resources"]
    for name in ("AutoAcceptSchedule", "DistinctiveAutoAcceptSchedule"):
        assert resources[name]["Properties"]["Target"]["RetryPolicy"]["MaximumRetryAttempts"] == 0
