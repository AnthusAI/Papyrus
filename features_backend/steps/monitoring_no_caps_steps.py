import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_paging as tp  # noqa: E402
import test_monitoring_router as tr  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, run_collection  # noqa: E402
from papyrus_content.monitoring_paging import RateLimited  # noqa: E402

PUBLICATION = "threat-intelligence"
PENDING = (409, {"detail": "publication criteria are pending"})
DAY = 86400


# --- parked items -----------------------------------------------------------

def collect_stories(context, count):
    context.table_ = tr.collected_table(tr.many_stories(count))
    context.table_.page_size = 7          # DynamoDB answers a page at a time
    context.store, context.cyclotron = tr.setup_router(context.table_)
    context.cyclotron.post_override[PUBLICATION] = PENDING
    context.delivery = tr.Delivery()
    context.stories = count
    tr.go(context.table_, context.store, context.cyclotron, now=2000, deliver=context.delivery)


@given("a router for a publication whose classifier is not ready")
def step_router(context):
    context.pending_router = True


@given("forty stories were collected while it waited")
def step_forty(context):
    collect_stories(context, 40)


@given("three stories were collected while it waited")
def step_three(context):
    collect_stories(context, 3)


@then("all forty stories are parked, each in a row of its own")
def step_parked(context):
    rows = tr.parked(context.table_, PUBLICATION)
    assert len(rows) == 40
    assert not any("items" in v for k, v in context.table_.items.items() if k[1].startswith("PARK#"))


@when("the classifier becomes ready and the router runs again")
def step_ready(context):
    context.cyclotron.post_override.clear()
    extra = "<item><title>S</title><link>https://example.org/s</link><comments>https://news.ycombinator.com/item?id=2000</comments></item>".encode()
    run_collection(DynamoStore(context.table_), "hn", fetch=lambda url: tr.many_stories(40).replace(b"</channel>", extra + b"</channel>"), now=7000)
    for n in range(12):
        tr.go(context.table_, context.store, context.cyclotron, now=8000 + 900 * n, deliver=context.delivery)


@then("every one of the forty stories is decided for that publication")
def step_decided(context):
    expected = {str(n) for n in range(1000, 1040)} | {"2000"}
    assert expected == {call[1] for call in context.delivery.calls if call[0] == PUBLICATION}


@then("the publication's park is removed")
def step_park_removed(context):
    assert ("MONITOR#hn", "PARK#" + PUBLICATION) not in context.table_.items and not tr.parked(context.table_, PUBLICATION)


@given("the publication's park is stored the old way, with its three items in one list")
def step_old_park(context):
    for key in [k for k in context.table_.items if k[1].startswith(f"PARK#{PUBLICATION}#")]:
        del context.table_.items[key]
    context.table_.items[("MONITOR#hn", "PARK#" + PUBLICATION)]["items"] = [{"sourceId": str(n), "revision": 1} for n in (1000, 1001, 1002)]


@when("the router runs again")
def step_run_again(context):
    tr.go(context.table_, context.store, context.cyclotron, now=2300, deliver=context.delivery)


@then("the park header no longer carries a list")
def step_header(context):
    assert "items" not in context.table_.items[("MONITOR#hn", "PARK#" + PUBLICATION)]


@then("the three items are parked in rows of their own")
def step_three_rows(context):
    assert [row["sourceId"] for row in tr.parked(context.table_, PUBLICATION)] == ["1000", "1001", "1002"]


# --- collector passes ---------------------------------------------------------

def ttab(context, count, cost=0, **config):
    context.clock = tp.Clock(cost=cost)
    context.rows = tp.decisions(count)
    context.server = tp.ReadingRoom(context.rows, clock=context.clock if cost else None)
    context.table_ = tp.ttab_table(**config)


def collect(context, now=tp.NOW, fresh_clock=False):
    clock = tp.Clock() if fresh_clock else context.clock
    printed = io.StringIO()
    with redirect_stdout(printed):
        context.result = tp.collect(context.table_, context.server, now=now, clock=clock, sleep=clock.sleep)
    context.log = [json.loads(line) for line in printed.getvalue().splitlines()]


@given("a TTAB monitor and a Reading Room that holds two hundred and fifty new decisions")
def step_250(context):
    ttab(context, 250)


@when("the monitor collects")
def step_collects(context):
    collect(context)


@then("all two hundred and fifty decisions are recorded")
def step_all_250(context):
    assert context.result["new"] == 250 and len(context.table_.by_prefix("DISC#")) == 250


@then("the monitor asked for every page until the search ran out")
def step_every_page(context):
    assert [call[0] for call in context.server.calls] == [0, 100, 200, 250]


@given("a TTAB monitor that has collected two hundred and fifty decisions")
def step_collected(context):
    ttab(context, 250)
    collect(context)


@given("the Reading Room has thirty newer decisions")
def step_newer(context):
    newer = [tp.decision(f"/legal-proceeding/{91000000 + n}/decision/EXA_{n}.pdf", 91000000 + n, f"Newer {n}", "Refusal Affirmed",
                         issued=1792000000000 - n * 1000, kind="EXA") for n in range(30)]
    context.server = tp.ReadingRoom(newer + context.rows)


@when("the monitor collects a day later")
def step_next_day(context):
    collect(context, now=tp.NOW + DAY)


@then("only the thirty newer decisions are recorded")
def step_thirty(context):
    assert context.result["new"] == 30 and len(context.table_.by_prefix("DISC#")) == 280


@then("the monitor asked for one page")
def step_one_page(context):
    assert len(context.server.calls) == 1


@given("a TTAB monitor and a Reading Room that holds four hundred and fifty new decisions, each page taking thirty seconds")
def step_450(context):
    ttab(context, 450, cost=30)


@then("the pass stops early with three hundred decisions, says it ran out of time, and is due again at once")
def step_stopped(context):
    assert context.result["new"] == 300 and context.result["read"]["stoppedBy"] == "time_budget"
    state = context.table_.items[("MONITOR#ttab", "STATE")]
    assert state["resume"] == {"recent": [300]} and state["nextDueAt"] == int(tp.NOW)


@when("the monitor collects at its next scheduled tick")
def step_tick(context):
    context.server.calls.clear()
    collect(context, now=tp.NOW + 900, fresh_clock=True)


@then("the remaining hundred and fifty decisions are recorded and the monitor has nothing left to resume")
def step_rest(context):
    assert context.result["new"] == 150 and len(context.table_.by_prefix("DISC#")) == 450
    assert "resume" not in context.table_.items[("MONITOR#ttab", "STATE")]


@given("a TTAB monitor and a Reading Room that holds one hundred and fifty new decisions")
def step_150(context):
    ttab(context, 150)


@given("the Reading Room answers its second request with a rate limit and asks for twenty-five seconds")
def step_limited(context):
    context.server.fail = {2: RateLimited("slow down", retry_after=25)}


@then("the monitor waited twenty-five seconds and recorded all one hundred and fifty decisions")
def step_waited(context):
    assert context.clock.slept == [25] and context.result["new"] == 150 and context.result["status"] == "complete"


@given("a stored monitor config that still says limit 1, maxItems 1 and pagesPerQuery 1")
def step_retired(context):
    ttab(context, 5, limit=1, maxItems=1, pagesPerQuery=1)


@then("every item the source has is recorded")
def step_every_item(context):
    assert context.result["new"] == 5


@then("one log line names the ignored fields")
def step_log(context):
    assert context.log == [{"monitor": "ignored_retired_config", "fields": ["limit", "maxItems", "pagesPerQuery"]}]
