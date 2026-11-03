"""Steps for monitoring-web-search-spend.feature and monitoring-run-at.feature: they drive `run_collection` with the fakes of
procedures/newsroom/tests/test_monitoring_web.py (a fake Tavily, a fake DynamoDB table, scripted provider HTTP)."""
import contextlib
import io
import json
from pathlib import Path
import re
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_web as tw  # noqa: E402
from papyrus_content.monitoring_cloud import _validate_config, next_run_at  # noqa: E402
from papyrus_content.monitoring_web import search_fetch  # noqa: E402
from papyrus_content.web_search import (HttpStatusError, PerplexityProvider, SearchChain, TavilyProvider,  # noqa: E402
                                        chain_names)
from test_web_search import FakeHttp, make  # noqa: E402

NOW, DAY, QUERY = tw.NOW, tw.DAY, "ai agents"
KEYS = tw.payload_keys


def tick_clock():
    ticks = iter(range(0, 100000))
    return lambda: float(next(ticks))


def collect_logged(context, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        context.result = tw.collect(context.table_, context.tavily, **kwargs)
    context.log_lines = [json.loads(line) for line in out.getvalue().splitlines() if line.startswith("{")]


def failing_lines(context):
    return [l for l in context.log_lines if l.get("monitor") == "search_provider_failing"]


# --- never paying twice ------------------------------------------------------------------------------------------------------

@given("a web monitor with one approved query whose last complete pass ended today")
def step_ended_today(context):
    context.table_, context.tavily = tw.web_table(), tw.FakeTavily()
    tw.set_high_water(context.table_, QUERY, NOW)


@given("the provider holds sixty matching articles from the last two days")
def step_sixty(context):
    context.tavily.articles = [tw.article(n, tw.day(-(n % 2))) for n in range(60)]


@then("the query is asked for the two days, and a full page splits them into one day each")
def step_two_days_split(context):
    first = context.tavily.calls[0]
    assert (first["start_date"], first["end_date"]) == (tw.day(-1), tw.day(0)) and len(context.tavily.calls) == 2
    assert (context.tavily.calls[1]["start_date"], context.tavily.calls[1]["end_date"]) == (tw.day(-2), tw.day(-1))


@then("the later day is not asked, because the one search for the two days already covered it")
def step_later_day_skipped(context):
    assert not any((c["start_date"], c["end_date"]) == (tw.day(-1), tw.day(0)) for c in context.tavily.calls[1:])


@then("no query and pair of dates is asked more than once in the pass")
def step_unique(context):
    keys = KEYS(context.tavily)
    assert len(keys) == len(set(keys))


ARTICLES = [tw.article(n, tw.day(-(n % 14))) for n in range(70)]


def two_query_table():
    table = tw.web_table(QUERY, "open models")
    tw.set_high_water(table, QUERY, NOW - 14 * DAY)
    return table


@given("a web monitor with two approved queries and seventy matching articles over fourteen days")
def step_two_queries(context):
    context.table_, context.tavily = two_query_table(), tw.FakeTavily(*ARTICLES)


@given("the first run stops on its time budget with its pass unfinished")
def step_first_run_stops(context):
    context.first = tw.collect(context.table_, context.tavily, budget_seconds=3, clock=tick_clock())
    assert context.first["status"] == "partial" and tw.state(context.table_)["resume"]


@when("the next five minute wake runs the monitor again until the pass is complete")
def step_wakes(context):
    context.runs = 1
    while tw.state(context.table_).get("resume"):
        context.result = tw.collect(context.table_, context.tavily, now=NOW + 300 * context.runs)
        context.runs += 1


@then("the searches asked across all the runs are exactly the searches one uninterrupted run would have asked")
def step_same_searches(context):
    whole = tw.FakeTavily(*ARTICLES)
    tw.collect(two_query_table(), whole)
    assert context.runs > 1 and sorted(KEYS(context.tavily)) == sorted(KEYS(whole))


@then("none of them was asked twice")
def step_none_twice(context):
    step_unique(context)


@given("a web monitor whose run receives a page of results and is then out of time before it can write them")
def step_page_unwritten(context):
    context.table_ = tw.web_table()
    tw.set_high_water(context.table_, QUERY, NOW - DAY)
    context.tavily = tw.FakeTavily(*[tw.article(n, tw.day(-1)) for n in range(5)])
    tavily = context.tavily
    context.first = tw.collect(context.table_, tavily, budget_seconds=3, clock=lambda: 1000.0 if tavily.calls else 0.0)
    assert context.first["status"] == "partial" and not tw.discs(context.table_)
    context.cursor = tw.state(context.table_)["resume"]["web"][0]


@when("the pass resumes on the next wake")
def step_resume(context):
    context.asked_before = len(context.tavily.calls)
    context.result = tw.collect(context.table_, context.tavily, now=NOW + 60)


@then("the resume point holds the paid page of results")
def step_holds_page(context):
    assert context.asked_before == 1 and len(context.cursor["page"]) == 5


@then("the next run records those articles without asking the provider again")
def step_reads_page(context):
    assert context.result["status"] == "complete" and len(tw.discs(context.table_)) == 5 and len(context.tavily.calls) == 1


@then("the stored page keeps its scores as whole numbers because the table takes no decimals")
def step_whole_scores(context):
    from papyrus_content.monitoring_web import storable_row
    row = storable_row(tw.article(1, tw.day(-1)))
    assert row["scoreBp"] == 5000 and isinstance(row["scoreBp"], int) and "score" not in row


@given("a web monitor whose pass takes two runs")
def step_two_runs(context):
    context.table_, context.tavily = two_query_table(), tw.FakeTavily(*ARTICLES)
    context.first = tw.collect(context.table_, context.tavily, budget_seconds=3, clock=tick_clock())


@when("both runs finish")
def step_both(context):
    context.second = tw.collect(context.table_, context.tavily, now=NOW + 300)
    assert context.second["status"] == "complete"


@then("each run line and receipt names the searches that run paid for, by provider, and the failures each provider answered")
def step_run_lines(context):
    receipts = tw.rows(context.table_, "RUN#")
    for result, receipt in zip((context.first, context.second), receipts):
        assert receipt["searches"] == result["searches"]
        run = result["searches"]["run"]
        assert run["requests"] > 0 and set(run) == {"requests", "providers", "failures"}


@then("the second run's receipt also names the total for the whole pass, which equals every search asked since the pass began")
def step_pass_total(context):
    assert context.second["searches"]["pass"]["requests"] == len(context.tavily.calls)
    assert context.first["searches"]["run"]["requests"] + context.second["searches"]["run"]["requests"] == len(context.tavily.calls)


def chain_of(first_error, second):
    tavily, other = FakeHttp(*[first_error] * 20), second
    chain = SearchChain(["tavily", "perplexity"], remember_refusals=True,
                        providers={"tavily": make(TavilyProvider, tavily, TAVILY_API_KEY="k"),
                                   "perplexity": make(PerplexityProvider, other, PERPLEXITY_API_KEY="k")})
    return chain, tavily, other


@given('a web monitor whose first provider answers "plan exhausted" and whose second provider answers')
def step_plan_exhausted(context):
    answer = {"results": [{"url": "https://example.org/story-1", "title": "S", "snippet": "S", "date": tw.day(-1)}]}
    chain, context.first_http, context.second_http = chain_of(HttpStatusError(432, "{}"), FakeHttp(*[answer] * 20))
    context.table_, context.tavily = tw.web_table(QUERY, "open models", "agents news"), search_fetch({}, chain)


@when("the web monitor collects three queries")
def step_three_queries(context):
    collect_logged(context)


@then("the first provider is asked once and passed over for the rest of the run")
def step_first_once(context):
    assert len(context.first_http.calls) == 1


@then("the second provider answers all three")
def step_second_three(context):
    assert len(context.second_http.calls) == 3 and context.result["searches"]["run"]["providers"] == {"perplexity": 3}


@then('the run logs one "search_provider_failing" line naming the first provider, "plan_exhausted" and the status')
def step_log_line(context):
    assert failing_lines(context) == [{"monitor": "search_provider_failing", "monitorId": tw.MONITOR, "provider": "tavily",
                                       "kind": "plan_exhausted", "status": 432}]


def template():
    import yaml

    class Loader(yaml.SafeLoader):
        pass
    Loader.add_multi_constructor("!", lambda loader, suffix, node: None)
    return yaml.load((Path(__file__).resolve().parents[2] / "infra/monitoring/papyrus-monitoring.yaml").read_text(), Loader)


@then('the template\'s metric filter counts that line and "papyrus-monitoring-search-provider-failing" alarms on it')
def step_alarm(context):
    resources = template()["Resources"]
    assert resources["SearchProviderFailingMetricFilter"]["Properties"]["FilterPattern"] == '{ $.monitor = "search_provider_failing" }'
    assert resources["SearchProviderFailingAlarm"]["Properties"]["AlarmName"] == "papyrus-monitoring-search-provider-failing"


@given("a web monitor whose first provider is out of plan and whose second provider refuses its key")
def step_all_refused(context):
    chain, context.first_http, context.second_http = chain_of(HttpStatusError(432, "{}"), FakeHttp(*[HttpStatusError(401, "{}")] * 20))
    context.table_, context.tavily = tw.web_table(QUERY, "open models"), search_fetch({}, chain)


@when("the web monitor collects with its log captured")
def step_collect_captured(context):
    collect_logged(context)


@then("each provider is asked once and the run fails")
def step_each_once(context):
    assert len(context.first_http.calls) == len(context.second_http.calls) == 1 and context.result["status"] == "failed"


@then("the monitor is not due again until its interval or its fixed time of day, not at the next five minute wake")
def step_not_due(context):
    assert tw.state(context.table_)["nextDueAt"] == NOW + 3600 and "resume" not in tw.state(context.table_)
    again = tw.collect(context.table_, context.tavily, now=NOW + 300)
    assert again["status"] == "not_due"


@then("both refusals are logged for the alarm")
def step_both_logged(context):
    assert {(l["provider"], l["kind"]) for l in failing_lines(context)} == {("tavily", "plan_exhausted"), ("perplexity", "auth")}


@given('the "WebSearchProviders" stack parameter holds an ordered list of providers')
def step_parameter(context):
    context.parameter = template()["Parameters"]["WebSearchProviders"]


@when('it is set to "tavily,perplexity"')
def step_set_parameter(context):
    assert re.match(context.parameter["AllowedPattern"], "tavily,perplexity")
    context.environ = {"WEB_SEARCH_PROVIDERS": "tavily,perplexity"}


@then("the collector's WEB_SEARCH_PROVIDERS names only those two, in that order")
def step_two_providers(context):
    variables = template()["Resources"]["CollectorFunction"]["Properties"]["Environment"]["Variables"]
    assert "WEB_SEARCH_PROVIDERS" in variables and chain_names(None, context.environ) == ["tavily", "perplexity"]


@then("no monitor config sets its own searchProviders, so OpenAI is no longer asked")
def step_no_own_chain(context):
    from papyrus_content.monitoring_web_publications import WEB_PUBLICATIONS, monitor_config
    for publication in WEB_PUBLICATIONS:
        assert _validate_config(monitor_config(publication, enabled=True))["searchProviders"] == []
    assert "openai" not in SearchChain(environ=context.environ).names


# --- a fixed time of day -----------------------------------------------------------------------------------------------------

I = tw.instant


def run_pass_at(context, text, **kwargs):
    context.table_ = getattr(context, "table_", None) or tw.run_at_table()
    context.tavily = getattr(context, "tavily", None) or tw.FakeTavily()
    context.when = I(text)
    context.result = tw.collect(context.table_, context.tavily, now=context.when, **kwargs)


def due(context):
    return tw.state(context.table_)["nextDueAt"]


@given("a monitor with runAt 02:00 in America/New_York")
def step_run_at_monitor(context):
    context.table_, context.tavily = tw.run_at_table(), tw.FakeTavily()


@when("a pass finishes at 02:03 on the 28th")
def step_pass_0203(context):
    run_pass_at(context, "2026-10-28 02:03")


@then("the monitor is next due at 02:00 on the 29th, not at 02:03")
def step_due_29(context):
    assert context.result["status"] == "complete" and due(context) == I("2026-10-29 02:00")


@then("a pass finishing at 01:30 would be next due at 02:00 the same morning")
def step_0130(context):
    assert next_run_at(tw.RUN_AT, I("2026-10-28 01:30")) == I("2026-10-28 02:00")


@when("a pass finishes at 02:07 on 31 October 2026, the day before the clocks go back")
def step_fall_back(context):
    run_pass_at(context, "2026-10-31 02:07")


@then("the monitor is next due at 02:00 on 1 November, twenty five hours later")
def step_due_nov1(context):
    assert due(context) == I("2026-11-01 02:00") and due(context) - I("2026-10-31 02:00") == 25 * 3600


@then("after that pass it is next due at 02:00 on 2 November")
def step_due_nov2(context):
    tw.collect(context.table_, context.tavily, now=I("2026-11-01 02:07"))
    assert due(context) == I("2026-11-02 02:00")


@when("a pass finishes on 7 March 2026, the day before the clocks go forward")
def step_spring(context):
    run_pass_at(context, "2026-03-07 02:07")


@then("the monitor is next due at 03:00 Eastern on the 8th, which is 07:00 UTC, because 02:00 does not exist that day")
def step_gap(context):
    from datetime import datetime, timezone
    assert datetime.fromtimestamp(due(context), timezone.utc).isoformat() == "2026-03-08T07:00:00+00:00"


@then("the day after it is due at 02:00 again")
def step_after_gap(context):
    tw.collect(context.table_, context.tavily, now=due(context) + 180)
    assert due(context) == I("2026-03-09 02:00")


@given("a monitor with runAt 02:00 whose next due time is 02:00")
def step_due_0200(context):
    context.table_, context.tavily = tw.run_at_table(), tw.FakeTavily()
    tw.DynamoStore(context.table_).put_state(tw.MONITOR, {"pk": f"MONITOR#{tw.MONITOR}", "sk": "STATE",
                                                          "nextDueAt": I("2026-10-29 02:00")})


@when("the schedule wakes it thirty seconds before 02:00 and it finishes")
def step_early(context):
    context.result = tw.collect(context.table_, context.tavily, now=I("2026-10-29 01:59") + 30)


@then("it is next due at 02:00 the following day, not at 02:00 that morning")
def step_following_day(context):
    assert context.result["status"] == "complete" and due(context) == I("2026-10-30 02:00")


@given("a monitor with runAt 02:00 whose pass starts at 02:03 and runs out of time")
def step_stops(context):
    context.tavily = tw.FakeTavily(*[tw.article(n, tw.day(-(n % 14), I("2026-10-28 02:03"))) for n in range(70)])
    context.table_ = tw.run_at_table()
    context.when = I("2026-10-28 02:03")
    tw.set_high_water(context.table_, QUERY, context.when - 14 * DAY)
    context.first = tw.collect(context.table_, context.tavily, now=context.when, budget_seconds=3, clock=tick_clock())
    assert context.first["status"] == "partial"


@then("it is due at once, and the five minute wake continues the pass at 02:08")
def step_due_now(context):
    assert due(context) == context.when
    context.asked = len(context.tavily.calls)
    context.second_at = context.when + 300
    assert tw.state(context.table_)["resume"]


@then("the continued pass asks no search the first run already asked")
def step_continue_no_repeat(context):
    context.result = tw.collect(context.table_, context.tavily, now=context.second_at)
    assert len(context.tavily.calls) > context.asked
    step_unique(context)


@when("the continued pass finishes")
def step_continued(context):
    assert context.result["status"] == "complete"


@then("the monitor is next due at 02:00 the following day")
def step_next_day(context):
    assert due(context) == I("2026-10-29 02:00")


@given("a monitor config whose runAt has an hour of 25, an unknown time zone, an extra field or is not an object")
def step_bad_configs(context):
    context.bad = [{"time": "25:00", "timeZone": "America/New_York"}, {"time": "02:00", "timeZone": "Mars/Base"},
                   {"time": "02:00", "timeZone": "America/New_York", "extra": 1}, "02:00"]


@when("the config is validated")
def step_validate(context):
    base = tw.monitor_config("anth-us", enabled=True)
    context.refused = 0
    for bad in context.bad:
        try:
            _validate_config({**base, "runAt": bad})
        except ValueError:
            context.refused += 1
    context.plain = _validate_config(base)


@then("it is refused, and a config without runAt behaves as before, due an interval after each pass")
def step_refused(context):
    assert context.refused == len(context.bad) and "runAt" not in context.plain
    table = tw.web_table()
    tw.collect(table, tw.FakeTavily(), now=NOW)
    assert tw.state(table)["nextDueAt"] == NOW + 3600
