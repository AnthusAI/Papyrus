"""Web-search monitors: Tavily paged by date window, high-water-mark recency, dedupe across monitors, per-publication config."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from papyrus_content.monitoring_cloud import DynamoStore, _validate_config, run_collection, run_web_collections
from papyrus_content.monitoring_paging import RateLimited
from papyrus_content.monitoring_router import CyclotronClient, RouterStore, run_router, validate_router_config
from papyrus_content.monitoring_web import TAVILY_PAGE_LIMIT, canonical_url, parse_results, url_hash
from papyrus_content.monitoring_web_publications import (WEB_PUBLICATIONS, monitor_config, monitor_id, router_config)

from test_monitoring_router import FakeCyclotron, FakeTable, router_config as hn_router_config

DAY = 86400
NOW = 1792540800   # 2026-10-21T00:00:00Z
MONITOR = "web-anth-us"


def day(offset: int, base: int = NOW) -> str:
    return (datetime.fromtimestamp(base, timezone.utc) + timedelta(days=offset)).date().isoformat()


def article(n: int, published: str, query: str = "ai agents", host: str = "example.org") -> dict:
    return {"url": f"https://{host}/story-{n}", "title": f"Story {n}", "content": f"Snippet {n}", "score": 0.5,
            "published_date": published, "_query": query}


class FakeTavily:
    """Tavily without the network: filters its corpus by the date window and answers at most max_results, newest first."""

    def __init__(self, *articles):
        self.articles, self.calls, self.fail = list(articles), [], []

    def __call__(self, payload):
        self.calls.append(payload)
        if self.fail:
            raise self.fail.pop(0)
        start, end = payload.get("start_date"), payload.get("end_date")
        rows = [a for a in self.articles if a["_query"] == payload["query"]
                and (not start or start <= a["published_date"][:10] <= end)]
        rows.sort(key=lambda a: a["published_date"], reverse=True)
        return {"results": [{k: v for k, v in a.items() if k != "_query"} for a in rows[:payload["max_results"]]]}


def web_table(*queries, monitor=MONITOR, **extra):
    table = FakeTable()
    table.put_item({**monitor_config("anth-us", queries or ("ai agents",), enabled=True), "pk": f"MONITOR#{monitor}", **extra})
    return table


def discs(table, monitor=MONITOR):
    return [v for k, v in sorted(table.items.items()) if k[0] == f"MONITOR#{monitor}" and k[1].startswith("DISC#")]


def collect(table, tavily, now=NOW, monitor=MONITOR, **kwargs):
    return run_collection(DynamoStore(table), monitor, fetch=tavily, now=now, **kwargs)


def state(table, monitor=MONITOR):
    return DynamoStore(table).get_state(monitor)


# --- the source -----------------------------------------------------------------------------------------------------------

def test_results_become_items_with_canonical_urls_snippet_date_and_the_query_that_found_them():
    (item,) = parse_results("ai agents", [{"url": "https://Example.org/a?utm_source=x&id=1", "title": " A   story ",
                                           "content": "About   agents", "published_date": "2026-10-20"}])

    assert item.canonical_url == "https://example.org/a?id=1" and item.title == "A story"
    assert item.published_at == "2026-10-20T00:00:00Z" and item.source_id.startswith("w")
    assert item.details == {"query": "ai agents", "snippet": "About agents"}


def test_results_without_a_usable_url_or_title_and_repeats_are_dropped():
    rows = [{"url": "ftp://x/y", "title": "t"}, {"url": "https://a.org/1", "title": ""}, "junk",
            {"url": "https://a.org/2", "title": "Two"}, {"url": "https://a.org/2?utm_campaign=z", "title": "Two again"}]

    assert [i.title for i in parse_results("q", rows)] == ["Two"]


def test_config_validation():
    base = monitor_config("anth-us", ["a"], enabled=True)
    assert _validate_config(base)["queries"] == ["a"] and _validate_config(base)["topic"] == "news"
    assert _validate_config({k: v for k, v in base.items() if k not in ("sourceUrl", "intervalSeconds")})["intervalSeconds"] == 3600
    assert _validate_config(monitor_config("anth-us", [], enabled=False))["enabled"] is False
    for bad in ({"queries": []}, {"queries": ["a", "a"]}, {"queries": [""]}, {"topic": "videos"}, {"startDate": "last week"}):
        with pytest.raises(ValueError):
            _validate_config({**base, **bad})


# --- paging through everything Tavily returns -----------------------------------------------------------------------------

def test_a_full_page_splits_the_date_window_until_every_result_is_read():
    # Tavily answers at most 20 per request and has no offset: 70 results over 14 days can only be read by narrowing the dates.
    corpus = [article(n, day(-(n % 14))) for n in range(70)]
    tavily = FakeTavily(*corpus)
    table = web_table()
    DynamoStore(table).put_state(MONITOR, {"pk": f"MONITOR#{MONITOR}", "sk": "STATE", "nextDueAt": 0, "watermark": NOW - 14 * DAY})

    result = collect(table, tavily)

    assert result["status"] == "complete" and result["new"] == 70 == len(discs(table))
    assert len(tavily.calls) > 1 and all(c["max_results"] == TAVILY_PAGE_LIMIT for c in tavily.calls)
    assert all(c["start_date"] <= c["end_date"] for c in tavily.calls)


def test_every_query_is_searched_and_each_result_records_the_query_that_found_it():
    tavily = FakeTavily(article(1, day(-1), "ai agents"), article(2, day(-1), "open models"))
    table = web_table("ai agents", "open models")

    collect(table, tavily)

    assert sorted((d["title"], d["details"]["query"]) for d in discs(table)) == [("Story 1", "ai agents"), ("Story 2", "open models")]
    disc = next(d for d in discs(table) if d["title"] == "Story 1")
    assert disc["canonicalUrl"] == "https://example.org/story-1" and disc["details"]["snippet"] == "Snippet 1"
    assert disc["sourcePublishedAt"] == day(-1) + "T00:00:00Z" and disc["sourceType"] == "web-search"
    assert disc["routing"] == "collected" and disc["monitorId"] == MONITOR


def test_a_saturated_single_day_is_accepted_not_split_forever():
    tavily = FakeTavily(*[article(n, day(-1)) for n in range(30)])
    table = web_table()
    DynamoStore(table).put_state(MONITOR, {"pk": f"MONITOR#{MONITOR}", "sk": "STATE", "nextDueAt": 0, "watermark": NOW - 2 * DAY})

    result = collect(table, tavily)

    assert result["status"] == "complete" and result["new"] == TAVILY_PAGE_LIMIT


def test_a_rate_limit_is_waited_out_for_its_retry_after():
    tavily = FakeTavily(article(1, day(-1)))
    tavily.fail = [RateLimited("slow down", 7.0)]
    slept = []
    table = web_table()

    result = collect(table, tavily, sleep=slept.append)

    assert slept == [7.0] and result["new"] == 1 and result["status"] == "complete"


def test_a_pass_that_runs_out_of_time_resumes_where_it_stopped_without_moving_the_high_water_mark():
    corpus = [article(n, day(-(n % 14))) for n in range(70)]
    tavily = FakeTavily(*corpus)
    table = web_table()
    store = DynamoStore(table)
    store.put_state(MONITOR, {"pk": f"MONITOR#{MONITOR}", "sk": "STATE", "nextDueAt": 0, "watermark": NOW - 14 * DAY})
    ticks = iter(range(0, 1000))

    first = collect(table, tavily, budget_seconds=3, clock=lambda: float(next(ticks)))

    assert first["status"] == "partial" and "stopped early" in first["errors"][-1]["message"]
    saved = state(table)
    assert saved["resume"]["web"] and saved["watermark"] == NOW - 14 * DAY and saved["nextDueAt"] == NOW
    asked = len(tavily.calls)
    second = collect(table, tavily, now=NOW + 60)
    assert second["status"] == "complete" and len(discs(table)) == 70
    assert len(tavily.calls) > asked
    assert state(table)["watermark"] == NOW and "resume" not in state(table)


# --- recency from the high-water mark ---------------------------------------------------------------------------------

def test_the_first_pass_without_a_mark_or_start_date_asks_tavily_with_no_date_filter():
    tavily = FakeTavily(article(1, day(-1)))

    collect(web_table(), tavily)

    assert len(tavily.calls) == 1 and "start_date" not in tavily.calls[0] and tavily.calls[0]["topic"] == "news"


def test_the_first_pass_starts_at_the_configured_start_date():
    tavily = FakeTavily(article(1, day(-1)))
    table = FakeTable()
    table.put_item({**monitor_config("anth-us", ["ai agents"], enabled=True), "pk": f"MONITOR#{MONITOR}", "startDate": "2026-10-01"})

    collect(table, tavily)

    assert tavily.calls[0]["start_date"] == "2026-10-01" and tavily.calls[0]["end_date"] == day(0)


def test_later_passes_search_from_the_last_complete_pass_never_a_fixed_window():
    tavily = FakeTavily(article(1, day(-1)))
    table = web_table()
    collect(table, tavily, now=NOW)
    assert state(table)["watermark"] == NOW

    later = NOW + 5 * DAY
    tavily.calls.clear()
    collect(table, tavily, now=later)

    assert tavily.calls[0]["start_date"] == day(-1, NOW) and tavily.calls[0]["end_date"] == day(0, later)
    assert state(table)["watermark"] == later


def test_a_failed_pass_leaves_the_mark_where_it_was():
    tavily = FakeTavily(article(1, day(-1)))
    table = web_table()
    collect(table, tavily, now=NOW)
    tavily.fail = [ValueError("Tavily search failed: HTTP 500")]

    result = collect(table, tavily, now=NOW + 2 * DAY)

    assert result["status"] == "failed" and state(table)["watermark"] == NOW


# --- dedupe ------------------------------------------------------------------------------------------------------------

def test_a_url_this_monitor_already_collected_is_not_collected_again():
    tavily = FakeTavily(article(1, day(-1)))
    table = web_table()
    collect(table, tavily, now=NOW)

    again = collect(table, tavily, now=NOW + 2 * DAY)

    assert again["new"] == 0 and again["unchanged"] >= 1 and len(discs(table)) == 1


def test_a_story_another_source_already_found_is_not_collected_as_new():
    hn_url = "https://example.org/story-1?utm_source=hn"
    table = web_table()
    DynamoStore(table).put_item("hn", {"pk": f"URL#{url_hash(hn_url)}", "sk": "MON#hn", "monitorId": "hn", "sourceType": "hn-rss",
                                       "sourceId": "101", "canonicalUrl": canonical_url(hn_url)})
    tavily = FakeTavily(article(1, day(-1)), article(2, day(-1)))

    result = collect(table, tavily)

    assert [d["title"] for d in discs(table)] == ["Story 2"] and result["new"] == 1


def test_collecting_through_the_hn_collector_registers_the_url_so_web_monitors_see_it():
    table = web_table()
    table.put_item({"pk": "MONITOR#hn", "sk": "CONFIG", "sourceUrl": "https://news.ycombinator.com/rss", "intervalSeconds": 900, "enabled": True})
    feed = (b"<rss><channel><item><title>Alpha</title><link>https://example.org/story-1?utm_source=x</link>"
            b"<comments>https://news.ycombinator.com/item?id=101</comments></item></channel></rss>")
    run_collection(DynamoStore(table), "hn", fetch=lambda url: feed, now=NOW)

    collect(table, FakeTavily(article(1, day(-1)), article(2, day(-1))))

    assert [d["title"] for d in discs(table)] == ["Story 2"]


def test_two_publications_web_monitors_each_collect_the_same_story_by_default():
    table = web_table()
    table.put_item(monitor_config("shipped", ["ai agents"], enabled=True))
    tavily = FakeTavily(article(1, day(-1)))

    collect(table, tavily, monitor="web-shipped")
    collect(table, tavily)

    assert len(discs(table, "web-shipped")) == 1 and len(discs(table)) == 1


def test_a_web_monitor_can_be_told_to_skip_stories_other_web_monitors_found():
    table = web_table(dedupeAgainstWebMonitors=True)
    table.put_item(monitor_config("shipped", ["ai agents"], enabled=True))
    tavily = FakeTavily(article(1, day(-1)))

    collect(table, tavily, monitor="web-shipped")
    collect(table, tavily)

    assert len(discs(table, "web-shipped")) == 1 and discs(table) == []


# --- one scheduled invocation for every web monitor ------------------------------------------------------------------------

def test_one_invocation_collects_every_due_web_monitor_longest_overdue_first_and_skips_the_rest():
    table = FakeTable()
    for publication in ("anth-us", "shipped", "pilobol-us"):
        table.put_item(monitor_config(publication, ["ai agents"], enabled=True))
    table.put_item(monitor_config("data-parade", ["ai agents"], enabled=False))
    table.put_item({"pk": "MONITOR#hn", "sk": "CONFIG", "sourceUrl": "https://news.ycombinator.com/rss", "intervalSeconds": 900})
    store = DynamoStore(table)
    store.put_state("web-shipped", {"pk": "MONITOR#web-shipped", "sk": "STATE", "nextDueAt": NOW - 5000})
    store.put_state("web-pilobol-us", {"pk": "MONITOR#web-pilobol-us", "sk": "STATE", "nextDueAt": NOW + 10 * DAY})
    tavily = FakeTavily(article(1, day(-1)))

    results = run_web_collections(store, ["web-anth-us", "web-shipped", "web-pilobol-us", "web-data-parade", "hn", "web-missing"],
                                  now=NOW, fetch=tavily)

    assert [r["monitorId"] for r in results] == ["web-anth-us", "web-shipped"]   # never run (due since 0) is the longest overdue
    assert all(r["status"] == "complete" for r in results)


# --- per-publication routing config ----------------------------------------------------------------------------------------

def hn_router():
    config = hn_router_config()
    config["publications"] += [{"publicationId": p, "site": f"{p}.example", "appsyncEndpoint": config["publications"][0]["appsyncEndpoint"]}
                               for p in ("data-parade", "pilobol-us", "shipped")]
    return config


@pytest.mark.parametrize("publication", [p for p in WEB_PUBLICATIONS if p != "distinctive"])
def test_each_shared_cyclotron_publication_gets_its_own_router_config_with_the_hn_cyclotron_block(publication):
    hn = hn_router()
    config = router_config(publication, hn)

    parsed = validate_router_config(config)
    assert config["pk"] == f"MONITOR#{monitor_id(publication)}" and config["sk"] == "CONFIG#router"
    assert [p["publicationId"] for p in parsed["publications"]] == [publication]
    assert parsed["cyclotron"]["runId"] == hn["cyclotron"]["runId"] and parsed["cyclotron"]["endpoint"] == hn["cyclotron"]["endpoint"]
    assert config["cyclotron"] == hn["cyclotron"] and config["holdDecisions"] is True and parsed["mode"] == "live"


def test_distinctive_has_no_cyclotron_and_holds_every_decision():
    config = router_config("distinctive", hn_router())

    parsed = validate_router_config(config)

    assert "cyclotron" not in config and parsed["cyclotron"] is None and parsed["decisions"] == "hold" and parsed["holdDecisions"] is True
    assert [p["publicationId"] for p in parsed["publications"]] == ["distinctive"]


def test_a_publication_missing_from_the_hn_router_is_refused():
    hn = hn_router()
    hn["publications"] = hn["publications"][:1]

    with pytest.raises(ValueError):
        router_config("shipped", hn)


def test_the_distinctive_router_collects_and_never_decides():
    table = web_table(monitor="web-distinctive")
    collect(table, FakeTavily(article(1, day(-1))), monitor="web-distinctive")
    table.put_item(router_config("distinctive", hn_router()))
    posted = []

    result = run_router(RouterStore(table), "web-distinctive", now=NOW + 10, deliver=lambda *a: posted.append(a),
                        appsync=lambda endpoint: object(), context_receipt=lambda c, p: {"contextHash": None, "reason": "test"})

    assert result["status"] == "complete" and posted == []
    assert [d["routing"] for d in discs(table, "web-distinctive")] == ["collected"]


def test_a_cyclotron_bound_web_router_holds_decisions_and_posts_nothing():
    table = web_table()
    collect(table, FakeTavily(article(1, day(-1))))
    config = router_config("anth-us", hn_router())
    table.put_item(config)
    lab = FakeCyclotron()
    client = CyclotronClient(validate_router_config(config), sign=lambda m, u, b: {}, http=lab.http, sleep=lambda s: None, clock=lambda: 0)
    delivered = []

    result = run_router(RouterStore(table), MONITOR, now=NOW + 10, cyclotron=client, deliver=lambda *a: delivered.append(a),
                        appsync=lambda endpoint: object(), context_receipt=lambda c, p: {"contextHash": None, "reason": "test"})

    assert result["stoppedBy"] == "decisions_held" and lab.posts() == [] and delivered == []
    assert [d["routing"] for d in discs(table)] == ["collected"]


def test_the_monitoring_template_schedules_web_collection_and_one_router_per_publication():
    import yaml
    from pathlib import Path

    class Loader(yaml.SafeLoader):
        pass
    Loader.add_multi_constructor("!", lambda loader, suffix, node: None)
    template = yaml.load((Path(__file__).resolve().parents[3] / "infra" / "monitoring" / "papyrus-monitoring.yaml").read_text(), Loader)
    resources = template["Resources"]
    collect_input = json.loads(resources["WebCollectSchedule"]["Properties"]["Target"]["Input"])
    routes = {json.loads(r["Properties"]["Target"]["Input"])["monitorId"] for n, r in resources.items()
              if n.startswith("Web") and n.endswith("RouteSchedule")}

    assert collect_input == {"sourceType": "web-search", "monitorIds": [monitor_id(p) for p in WEB_PUBLICATIONS]}
    assert routes == {monitor_id(p) for p in WEB_PUBLICATIONS}


# --- query drafting ----------------------------------------------------------------------------------------------------------

def test_queries_are_drafted_from_mission_policy_and_criteria_and_retried_once_when_the_model_misbehaves(tmp_path):
    from papyrus_content import monitoring_web_queries as wq

    (tmp_path / "anth-us-relevance.json").write_text(json.dumps({"question": "Should this source become a reference?"}))
    answers = iter(["not json", json.dumps([f"query {n}" for n in range(9)])])
    prompts = []

    def ask(message):
        prompts.append(message)
        return next(answers)

    pack = {"entries": [{"scope": "publication", "kind": "mission", "text": "Show the work."},
                        {"scope": "publication", "kind": "policy", "text": "Cite primary sources."}], "contextHash": "h"}
    publications = wq.router_publications(hn_router())

    proposal = wq.propose("anth-us", publications, ask, criteria_dir=tmp_path, client_factory=lambda endpoint: object(),
                          resolve=lambda client, **kw: pack)

    assert proposal["queries"] == [f"query {n}" for n in range(9)] and proposal["monitorId"] == "web-anth-us"
    assert proposal["basedOn"] == {"mission": True, "policy": True, "criteria": True, "contextHash": "h"}
    assert len(prompts) == 2 and "Show the work." in prompts[1] and "Should this source become a reference?" in prompts[1]


@pytest.mark.parametrize("answer", [json.dumps(["only one"]), json.dumps([f"q{n}" for n in range(16)]), json.dumps({"a": 1})])
def test_a_proposal_outside_eight_to_fifteen_queries_is_refused(answer):
    from papyrus_content import monitoring_web_queries as wq

    with pytest.raises(ValueError):
        wq.parse_queries(answer)


def test_without_local_criteria_the_proposal_says_so(tmp_path):
    from papyrus_content import monitoring_web_queries as wq

    assert wq.criteria_text("distinctive", tmp_path) is None
