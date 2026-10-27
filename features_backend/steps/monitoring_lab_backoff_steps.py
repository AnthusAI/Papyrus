from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_router as tr  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, run_collection  # noqa: E402
from papyrus_content.monitoring_router import RouterStore  # noqa: E402

PAUSE = ("MONITOR#hn", "STATE#labBackoff")


def collect(context, now):
    return tr.run_with(context.table_, context.store, context.cyclotron, now=now, deliver=context.delivery, task="collect")


def lab_calls(context):
    return len(context.cyclotron.combined_calls) + len(context.cyclotron.calls)


def job_row(context):
    return context.table_.items[("MONITOR#hn", "ROUTE#101#000001")]["combinedJob"]


@given("a router with three stories whose lab jobs are still running")
def step_router(context):
    context.table_ = tr.FakeTable()
    context.table_.put_item(tr.COLLECTOR_CONFIG)
    context.table_.put_item(tr.router_config())
    context.store, context.cyclotron, context.delivery = RouterStore(context.table_), tr.FakeCyclotron(), tr.Delivery()
    context.cyclotron.combined_enabled = True
    run_collection(DynamoStore(context.table_), "hn", fetch=lambda url: tr.FEED, now=1000)
    context.cyclotron.polls_needed = 10_000
    tr.run_with(context.table_, context.store, context.cyclotron, now=2000, deliver=context.delivery)
    context.gets_before = len(tr.lab_gets(context.cyclotron))


@given("the lab answers 429 and asks the router to wait ninety seconds")
def step_429(context):
    context.cyclotron.combined_poll_override = (429, {"retryAfter": 90})


@given("the lab answers 503 without a Retry-After")
def step_503(context):
    context.cyclotron.combined_poll_override = (503, {})


@when("the collector asks the lab about the jobs")
def step_collector(context):
    context.result = collect(context, 3000)
    context.calls_after_first = lab_calls(context)


@when("the collector and the route task run thirty seconds later")
def step_paused(context):
    context.paused = [tr.run_with(context.table_, context.store, context.cyclotron, now=3030, deliver=context.delivery, task=task)
                      for task in ("collect", "route")]


@when("the lab has recovered and the collector asks after the pause")
def step_recovered(context):
    context.cyclotron.combined_poll_override = None
    context.cyclotron.polls_needed = 0
    context.result = collect(context, 3091)


@when("the collector is refused three times in a row, each time after the pause")
def step_three(context):
    now, context.waits = 3000, []
    for _ in range(3):
        collect(context, now)
        until = int(context.table_.items[PAUSE]["until"])
        context.waits.append(until - now)
        now = until + 1


@when("the collector asks and then asks again before the job's wait is over")
def step_twice(context):
    collect(context, 3000)
    context.after_first = len(tr.lab_gets(context.cyclotron))
    collect(context, 3010)


@when("the collector asks again after the wait")
def step_after_wait(context):
    collect(context, 3031)


@then("the monitor records that the lab is paused for ninety seconds")
def step_recorded(context):
    assert context.table_.items[PAUSE]["until"] == 3090 and context.result["stoppedBy"] == "http_429"


@then("both stopped because of the lab backoff and the lab received no call")
def step_stopped(context):
    assert [r["stoppedBy"] for r in context.paused] == ["lab_backoff", "lab_backoff"]
    assert lab_calls(context) == context.calls_after_first


@then("the stories are delivered and the pause is cleared")
def step_delivered(context):
    assert set(tr.routing_of(context.table_).values()) == {"routed"} and PAUSE not in context.table_.items


@then("the pauses were sixty, one hundred and twenty and two hundred and forty seconds")
def step_waits(context):
    assert context.waits == [60, 120, 240]


@then("the lab was asked about each job once and not again inside its wait")
def step_once(context):
    assert context.after_first - context.gets_before == 3
    assert len(tr.lab_gets(context.cyclotron)) == context.after_first
    assert job_row(context)["nextPollAt"] == 3030


@then("each job's next wait is twice as long")
def step_double(context):
    assert job_row(context)["nextPollAt"] == 3031 + 60 and job_row(context)["pollBackoffs"] == 2


@then("the collector asked the lab about only the oldest job")
def step_oldest(context):
    asked = tr.lab_gets(context.cyclotron)[context.gets_before:]
    jobs = [context.table_.items[("MONITOR#hn", f"ROUTE#{n}#000001")]["combinedJob"] for n in (101, 102, 103)]
    assert len(asked) == 1 and asked[0][1].endswith(min(jobs, key=lambda j: (j["postedAt"], j["jobId"]))["jobId"])


@then("all three stories still have their jobs recorded")
def step_recorded_jobs(context):
    for n in (101, 102, 103):
        assert context.table_.items[("MONITOR#hn", f"ROUTE#{n}#000001")]["combinedJob"]["jobId"]
