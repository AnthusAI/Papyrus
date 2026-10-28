from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_web as tw  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore  # noqa: E402
from papyrus_content.monitoring_candidates import record_candidate  # noqa: E402
from papyrus_content.monitoring_router import CyclotronClient, RouterStore, run_router, validate_router_config  # noqa: E402
from papyrus_content.monitoring_web_publications import SHARED_CYCLOTRON, WEB_PUBLICATIONS, monitor_config, router_config  # noqa: E402

NOW, DAY, QUERY = tw.NOW, tw.DAY, "ai agents"


@given("a web monitor for anth-us with one approved query last searched fourteen days ago")
def step_busy_monitor(context):
    context.table_, context.tavily = tw.web_table(), tw.FakeTavily()
    tw.set_high_water(context.table_, QUERY, NOW - 14 * DAY)


@given("Tavily holds seventy matching articles over those fourteen days")
def step_seventy(context):
    context.tavily.articles = [tw.article(n, tw.day(-(n % 14))) for n in range(70)]


@when("the web monitor collects")
def step_collect(context):
    context.result = tw.collect(context.table_, context.tavily, now=getattr(context, "now", NOW))


@then("all seventy articles are recorded")
def step_all_seventy(context):
    assert context.result["new"] == 70 == len(tw.discs(context.table_))


@then("the monitor asked Tavily for narrower date ranges until no range filled a page")
def step_narrower(context):
    assert len(context.tavily.calls) > 1 and all(c["start_date"] <= c["end_date"] for c in context.tavily.calls)


@given("a web monitor for anth-us whose query completed a pass on 21 October")
def step_completed(context):
    context.table_, context.tavily = tw.web_table(), tw.FakeTavily(tw.article(1, tw.day(-1)))
    tw.collect(context.table_, context.tavily, now=NOW)
    context.tavily.calls.clear()


@when("the web monitor collects five days later")
def step_five_days(context):
    context.now = NOW + 5 * DAY
    step_collect(context)


@then("it asks Tavily for results from the day before 21 October up to the new day")
def step_window(context):
    call = context.tavily.calls[0]
    assert call["start_date"] == tw.day(-1) and call["end_date"] == tw.day(0, NOW + 5 * DAY)


@then("the query's high-water mark moves to the start of that pass")
def step_mark(context):
    assert tw.queries_of(context.table_)[QUERY]["highWater"] == NOW + 5 * DAY


@given("a web monitor for anth-us with one approved query, one unapproved query and one paused query")
def step_three_queries(context):
    context.table_, context.tavily = tw.web_table("approved"), tw.FakeTavily()
    tw.add_queries(context.table_, tw.MONITOR, "unapproved", approved_by=None)
    tw.add_queries(context.table_, tw.MONITOR, "paused", status="paused")


@then("Tavily was asked only the approved query")
def step_only_approved(context):
    assert [c["query"] for c in context.tavily.calls] == ["approved"]


@given("a web monitor for anth-us whose approved query already found one story")
def step_found_one(context):
    context.table_, context.tavily = tw.web_table(), tw.FakeTavily(tw.article(1, tw.day(-1)))
    tw.collect(context.table_, context.tavily, now=NOW)


@given("Tavily now returns that story and a new one")
def step_now_two(context):
    context.tavily.articles.append(tw.article(2, tw.day(-1)))


@then("the query's run records two results, one new, one duplicate and its credits")
def step_run(context):
    run = max(tw.rows(context.table_, "QRUN#"), key=lambda r: r["startedAt"])
    assert (run["resultsReturned"], run["newCount"], run["duplicateCount"], run["credits"]) == (2, 1, 1, 1)


@given("a web monitor for anth-us with one approved query")
def step_monitor(context):
    context.table_, context.tavily = tw.web_table(), tw.FakeTavily()


@given("the Hacker News monitor already found https://example.org/story-1")
def step_hn_found(context):
    record_candidate(DynamoStore(context.table_), url="https://example.org/story-1", title="Alpha", published_at=None, monitor_id="hn",
                     source_type="hn-rss", group="hn", source_id="101", found_at="2026-10-20T00:00:00Z", run_id="r0", collected=True)


@given("Tavily returns that story, with tracking parameters, and a new one")
def step_returns_both(context):
    first = tw.article(1, tw.day(-1))
    first["url"] += "?utm_source=newsletter"
    context.tavily.articles = [first, tw.article(2, tw.day(-1))]


@then("only the new story is recorded")
def step_only_new(context):
    assert [d["title"] for d in tw.discs(context.table_)] == ["Story 2"]


@then("the shared candidate for the first story lists both finds in its provenance")
def step_provenance(context):
    cand = tw.candidate(context.table_, "https://example.org/story-1")
    assert [p["monitorId"] for p in cand["provenance"]] == ["hn", tw.MONITOR]


@given("a web monitor for shipped that already collected https://example.org/story-1")
def step_shipped_found(context):
    context.table_.put_item(monitor_config("shipped", enabled=True))
    tw.add_queries(context.table_, "web-shipped", QUERY)
    tw.collect(context.table_, tw.FakeTavily(tw.article(1, tw.day(-1))), monitor="web-shipped")


@given("Tavily returns that story")
def step_returns_story(context):
    context.tavily.articles = [tw.article(1, tw.day(-1))]


@then("the story is not recorded again for anth-us")
def step_not_again(context):
    assert len(tw.discs(context.table_, "web-shipped")) == 1 and tw.discs(context.table_) == []


@given("the hn router config lists all the shared publications")
def step_hn_router(context):
    context.hn = tw.hn_router()


@when("the web monitors' router configs are built")
def step_build_configs(context):
    context.configs = {p: router_config(p, context.hn) for p in WEB_PUBLICATIONS}


@then("each shared monitor lists all six publications")
def step_all_six(context):
    for publication in SHARED_CYCLOTRON:
        assert [p["publicationId"] for p in context.configs[publication]["publications"]] == list(SHARED_CYCLOTRON)


@then("each reuses the hn router's Cyclotron block")
def step_cyclotron(context):
    for publication in SHARED_CYCLOTRON:
        assert context.configs[publication]["cyclotron"] == context.hn["cyclotron"]
        validate_router_config(context.configs[publication])


@then("each holds decisions")
def step_holds(context):
    assert all(config["holdDecisions"] is True for config in context.configs.values())


@then("the Distinctive Mark config has no Cyclotron block and still validates")
def step_distinctive(context):
    config = context.configs["distinctive"]
    assert "cyclotron" not in config and validate_router_config(config)["decisions"] == "hold"


@then("a router run for it collects and enriches but decides nothing")
def step_distinctive_run(context):
    table = tw.web_table(monitor="web-distinctive")
    tw.collect(table, tw.FakeTavily(tw.article(1, tw.day(-1))), monitor="web-distinctive")
    table.put_item(context.configs["distinctive"])
    result = run_router(RouterStore(table), "web-distinctive", now=NOW + 10, deliver=lambda *a: None, appsync=lambda e: object(),
                        context_receipt=lambda c, p: {"contextHash": None, "reason": "test"})
    assert result["status"] == "complete" and [d["routing"] for d in tw.discs(table, "web-distinctive")] == ["collected"]


@given("a web monitor for anth-us that collected a story")
def step_collected(context):
    context.table_ = tw.web_table()
    tw.collect(context.table_, tw.FakeTavily(tw.article(1, tw.day(-1))))


@given("its router config holds decisions")
def step_router_holds(context):
    context.router_cfg = router_config("anth-us", tw.hn_router())
    context.table_.put_item(context.router_cfg)
    context.lab = tw.FakeCyclotron()


@when("the web router runs")
def step_router_runs(context):
    client = CyclotronClient(validate_router_config(context.router_cfg), sign=lambda m, u, b: {}, http=context.lab.http,
                             sleep=lambda s: None, clock=lambda: 0)
    context.result = run_router(RouterStore(context.table_), tw.MONITOR, now=NOW + 10, cyclotron=client, deliver=lambda *a: None,
                                appsync=lambda e: object(), context_receipt=lambda c, p: {"contextHash": None, "reason": "test"})


@then("no decision request was sent to the Cyclotron")
def step_no_posts(context):
    assert context.lab.posts() == [] and context.result["stoppedBy"] == "decisions_held"


@then("the story is still waiting to be decided")
def step_waiting(context):
    assert [d["routing"] for d in tw.discs(context.table_)] == ["collected"]
