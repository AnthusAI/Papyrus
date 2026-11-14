from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_router as tr  # noqa: E402
from papyrus_content.monitoring_router import run_router, validate_router_config  # noqa: E402

PAUSE = ("MONITOR#hn", "STATE#labBackoff")


def client(context):
    context.clock = tr.Clocked()
    context.paced = tr.paced_client(context.table_, context.cyclotron, context.clock)
    return context.paced


def lab_gets_now(context):
    return len(tr.lab_gets(context.cyclotron))


@when("the router makes eight lab calls in a row")
def step_eight(context):
    lab = client(context)
    for _ in range(3):
        lab.post_combined({"payload": {"bindings": ["anth-us"], "item": {"id": "x"}}})
    for _ in range(5):
        try:
            lab.poll_combined("cjob-0", wait=False)
        except Exception:
            pass


@then("no two calls left less than a quarter of a second apart")
def step_gaps(context):
    arrivals = context.clock.arrivals
    assert len(arrivals) == 8 and min(b - a for a, b in zip(arrivals, arrivals[1:])) >= 0.25


@then("no second of the clock saw more than four calls")
def step_second(context):
    arrivals = context.clock.arrivals
    assert all(sum(1 for t in arrivals if s <= t < s + 1) <= 4 for s in arrivals)


@given('the gateway answers "Too Many Requests" twice and then the lab recovers')
def step_bare(context):
    context.cyclotron.polls_needed = 0
    context.cyclotron.combined_poll_queue = [(429, {"message": "Too Many Requests"})] * 2


@when("the collector asks the lab about the jobs through the paced client")
def step_collect(context):
    lab = client(context)
    context.result = run_router(context.store, "hn", now=3000, cyclotron=lab, appsync=lambda e: object(),
                                deliver=context.delivery, context_receipt=lambda c, p: {}, task="collect")


@then("the same calls were repeated after waiting about a second each time")
def step_repeated(context):
    assert context.paced.throttled == 2 and context.clock.t >= 2.0


@then("the monitor is not paused and the stories are delivered")
def step_not_paused(context):
    assert PAUSE not in context.table_.items and context.paced.rate_limited is None
    assert set(tr.routing_of(context.table_).values()) == {"routed"}


@given("the lab answers 503 and asks the router to wait forty-five seconds")
def step_503(context):
    context.cyclotron.combined_poll_override = (503, {"retryAfter": 45})


@then("the monitor records that the lab is paused for forty-five seconds")
def step_paused(context):
    assert context.table_.items[PAUSE]["until"] == 3045


@given("the monitor still carries a pause caused by a 429 with no Retry-After")
def step_old(context):
    context.table_.put_item({"pk": "MONITOR#hn", "sk": "STATE#labBackoff", "until": 9000, "strikes": 4,
                             "status": 429, "retryAfter": None})
    context.gets_seen = lab_gets_now(context)


@then("the lab was called and the old pause row is gone")
def step_cleared(context):
    assert lab_gets_now(context) > context.gets_seen and PAUSE not in context.table_.items
