"""Web-search monitors: query records, QueryRuns, Tavily paged by date window, per-query high-water marks, shared candidates
with provenance, dedupe across sources, per-publication routing config."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from papyrus_content.monitoring_candidates import candidate_key, record_candidate
from papyrus_content.monitoring_cloud import DynamoStore, _validate_config, run_collection, run_web_collections
from papyrus_content.monitoring_paging import RateLimited
from papyrus_content.monitoring_router import CyclotronClient, RouterStore, run_router, validate_router_config
from papyrus_content.monitoring_web import (TAVILY_PAGE_LIMIT, arxiv_paper_id, canonical_url, parse_results, query_record, searchable,
                                           with_paper_titles)
from papyrus_content.monitoring_web_publications import (SHARED_CYCLOTRON, WEB_PUBLICATIONS, monitor_config, monitor_id,
                                                         router_config)

from test_monitoring_router import FakeCyclotron, FakeTable, router_config as hn_router_config

DAY = 86400
NOW = 1792540800   # 2026-10-21T00:00:00Z
MONITOR = "web-anth-us"
APPROVER = "Ryan (review delegated to Claude, 2026-10-28)"


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


def add_queries(table, monitor, *texts, approved_by=APPROVER, **fields):
    for text in texts:
        record = query_record(monitor, text, f"why {text}", origin="drafted", created_by="gpt-6-luna",
                              now_iso="2026-10-20T00:00:00Z", approved_by=approved_by)
        table.put_item({**record, **fields})


def web_table(*queries, monitor=MONITOR, **extra):
    table = FakeTable()
    config = monitor_config("anth-us", enabled=True)
    table.put_item({**config, "pk": f"MONITOR#{monitor}", **extra})
    add_queries(table, monitor, *(queries or ("ai agents",)))
    return table


def rows(table, prefix, monitor=MONITOR):
    return [v for k, v in sorted(table.items.items()) if k[0] == f"MONITOR#{monitor}" and k[1].startswith(prefix)]


def discs(table, monitor=MONITOR):
    return rows(table, "DISC#", monitor)


def queries_of(table, monitor=MONITOR):
    return {r["text"]: r for r in rows(table, "QUERY#", monitor)}


def collect(table, tavily, now=NOW, monitor=MONITOR, **kwargs):
    return run_collection(DynamoStore(table), monitor, fetch=tavily, now=now, **kwargs)


def state(table, monitor=MONITOR):
    return DynamoStore(table).get_state(monitor)


def set_high_water(table, text, when, monitor=MONITOR):
    record = queries_of(table, monitor)[text]
    table.put_item({**record, "highWater": when})


def candidate(table, url):
    key = candidate_key(url)
    return table.items.get((key["pk"], key["sk"]))


# --- the source -----------------------------------------------------------------------------------------------------------

def test_results_become_items_with_canonical_urls_snippet_date_and_the_query_that_found_them():
    (item,) = parse_results("ai agents", [{"url": "https://Example.org/a?utm_source=x&id=1", "title": " A   story ",
                                           "content": "About   agents", "score": 0.91234567, "published_date": "2026-10-20"}], "q1")

    assert item.canonical_url == "https://example.org/a?id=1" and item.title == "A story"
    assert item.published_at == "2026-10-20T00:00:00Z" and item.source_id.startswith("w")
    assert item.details == {"query": "ai agents", "queryId": "q1", "snippet": "About agents", "tavilyScoreBp": 9123}


def test_an_arxiv_result_takes_the_papers_own_title_from_arxiv():
    items = parse_results("ai evaluation", [{"url": "https://arxiv.org/html/2610.35725v1", "title": "1 Introduction"},
                                            {"url": "https://example.org/a", "title": "A story"}])
    asked = []

    def lookup(ids):
        asked.append(ids)
        return {"2610.35725": "The Watchtower Imperative: Lifespan-Calibrated Evaluation for Frontier AI"}

    titled = with_paper_titles(items, lookup)
    assert [i.title for i in titled] == ["The Watchtower Imperative: Lifespan-Calibrated Evaluation for Frontier AI", "A story"]
    assert asked == [["2610.35725"]], "one request for the page's arXiv papers"
    assert titled[0].fingerprint != items[0].fingerprint, "the fingerprint follows the stored title"
    assert [i.title for i in with_paper_titles(items, lambda ids: {})] == ["1 Introduction", "A story"], "arXiv down: the title stands"
    assert arxiv_paper_id("https://arxiv.org/abs/1706.03762v7") == "1706.03762" and arxiv_paper_id("https://example.org/abs/1") is None


def test_results_without_a_usable_url_or_title_and_repeats_are_dropped():
    rows_ = [{"url": "ftp://x/y", "title": "t"}, {"url": "https://a.org/1", "title": ""}, "junk",
             {"url": "https://a.org/2", "title": "Two"}, {"url": "https://a.org/2?utm_campaign=z", "title": "Two again"}]

    assert [i.title for i in parse_results("q", rows_)] == ["Two"]


def test_config_validation():
    base = monitor_config("anth-us", enabled=True)
    assert _validate_config(base)["topic"] == "news" and "queries" not in _validate_config(base)
    assert _validate_config({k: v for k, v in base.items() if k not in ("sourceUrl", "intervalSeconds")})["intervalSeconds"] == 3600
    assert _validate_config(base)["candidateGroup"] == "shared"
    for bad in ({"topic": "videos"}, {"startDate": "last week"}, {"candidateGroup": " "}):
        with pytest.raises(ValueError):
            _validate_config({**base, **bad})


def test_domain_filters_are_validated_as_bare_domains():
    base = monitor_config("distinctive", enabled=True)
    assert _validate_config({**base, "excludeDomains": ["Facebook.com", "facebook.com", "x.com"]})["excludeDomains"] == ["facebook.com", "x.com"]
    for bad in ("facebook.com", ["https://facebook.com/page"], ["facebook"], [""]):
        with pytest.raises(ValueError):
            _validate_config({**base, "excludeDomains": bad})
    with pytest.raises(ValueError):
        query_record(MONITOR, "q", "r", origin="editor", created_by="x", now_iso="2026-10-20T00:00:00Z", exclude_domains=["a/b.com"])


def test_a_querys_domain_filters_and_the_monitors_are_sent_with_the_search():
    table = web_table("ai agents", "open models", excludeDomains=["facebook.com"])
    narrow = queries_of(table)["ai agents"]
    table.put_item({**narrow, "excludeDomains": ["linkedin.com", "facebook.com"], "includeDomains": ["law360.com"]})
    tavily = FakeTavily(article(1, day(-1), "ai agents"), article(2, day(-1), "open models"))

    collect(table, tavily)

    asked = {c["query"]: c for c in tavily.calls}
    assert asked["ai agents"]["exclude_domains"] == ["facebook.com", "linkedin.com"]
    assert asked["ai agents"]["include_domains"] == ["law360.com"]
    assert asked["open models"]["exclude_domains"] == ["facebook.com"] and "include_domains" not in asked["open models"]


def test_a_query_without_domain_filters_sends_none():
    tavily = FakeTavily(article(1, day(-1)))
    collect(web_table(), tavily)
    assert all("exclude_domains" not in c and "include_domains" not in c for c in tavily.calls)


# --- provider chain ----------------------------------------------------------------------------------------------------------

def _chain(**http_by_name):
    from test_web_search import FakeHttp, make
    from papyrus_content.web_search import OpenAIProvider, PerplexityProvider, SearchChain, TavilyProvider
    classes = {"tavily": TavilyProvider, "openai": OpenAIProvider, "perplexity": PerplexityProvider}
    return SearchChain(list(http_by_name), providers={name: make(classes[name], http, **{f"{name.upper()}_API_KEY": "k"})
                                                     for name, http in http_by_name.items()}), {n: h for n, h in http_by_name.items()}


def test_the_monitors_own_chain_is_validated_and_stored():
    base = monitor_config("distinctive", enabled=True)
    assert _validate_config({**base, "searchProviders": "openai, tavily"})["searchProviders"] == ["openai", "tavily"]
    assert _validate_config({**base, "searchProviders": ["perplexity"]})["searchProviders"] == ["perplexity"]
    assert _validate_config(base)["searchProviders"] == []
    for bad in ("openai,bogus", ["nope"], 5):
        with pytest.raises((ValueError, TypeError)):
            _validate_config({**base, "searchProviders": bad})


def test_an_exhausted_tavily_plan_falls_back_and_the_query_run_records_who_answered_and_why():
    from test_web_search import FakeHttp
    from papyrus_content.web_search import HttpStatusError
    from papyrus_content.monitoring_web import search_fetch
    tavily = FakeHttp(*[HttpStatusError(432, "{}")] * 5)
    perplexity = FakeHttp(*[{"results": [{"url": "https://example.org/story-1", "title": "Story 1", "snippet": "S", "date": day(-1)}]}] * 5)
    chain, _ = _chain(tavily=tavily, perplexity=perplexity)
    table = web_table()

    result = collect(table, search_fetch({}, chain))

    assert result["new"] == 1 and not result.get("errors")
    (run,) = rows(table, "QRUN#")
    assert run["providers"] == {"perplexity": run["requests"]} and run["skipped"] == ["tavily: plan exhausted (432)"]


def test_a_provider_that_cannot_bound_dates_is_asked_once_not_split_into_days():
    from test_web_search import FakeHttp
    from papyrus_content.monitoring_web import search_fetch
    rows_ = [{"url": f"https://example.org/s-{n}", "title": f"S{n}", "snippet": ""} for n in range(25)]
    openai = FakeHttp(*[{"output": [{"action": {"sources": [{"url": r["url"]} for r in rows_]}}]}] * 20)
    chain, _ = _chain(openai=openai)
    table = web_table()
    table.put_item({**queries_of(table)["ai agents"], "highWater": NOW - 14 * DAY})

    result = collect(table, search_fetch({}, chain))

    assert len(openai.calls) == 1 and result["new"] == 20   # one request, the monitor's own page of twenty


def test_all_providers_rate_limited_waits_as_a_single_provider_does():
    from test_web_search import FakeHttp
    from papyrus_content.web_search import HttpStatusError
    from papyrus_content.monitoring_web import search_fetch
    limited = HttpStatusError(429, "", {"Retry-After": "30"})
    chain, _ = _chain(tavily=FakeHttp(limited, limited))
    with pytest.raises(RateLimited) as caught:
        search_fetch({}, chain)({"query": "q", "max_results": 20})
    assert caught.value.retry_after == 30.0


def test_all_providers_failing_names_each_failure_in_the_run_error():
    from test_web_search import FakeHttp
    from papyrus_content.web_search import HttpStatusError
    from papyrus_content.monitoring_web import search_fetch
    chain, _ = _chain(tavily=FakeHttp(HttpStatusError(432)), openai=FakeHttp(HttpStatusError(401)))
    with pytest.raises(ValueError, match=r"tavily: plan exhausted \(432\); openai: authentication failed \(401\)"):
        search_fetch({}, chain)({"query": "q", "max_results": 20})


# --- query records ---------------------------------------------------------------------------------------------------------

def test_a_query_record_has_a_stable_id_origin_creator_approval_status_and_history():
    record = query_record("web-anth-us", "  ai   agents ", "finds agent work", origin="drafted", created_by="gpt-6-luna",
                          now_iso="2026-10-28T00:00:00Z", approved_by=APPROVER)

    assert record["id"] == query_record("web-anth-us", "ai agents", "other", origin="editor", created_by="x", now_iso="y")["id"]
    assert (record["text"], record["origin"], record["createdBy"], record["status"]) == ("ai agents", "drafted", "gpt-6-luna", "active")
    assert record["approvedBy"] == APPROVER and record["approvedAt"] == "2026-10-28T00:00:00Z"
    assert record["history"][0]["change"] == "created" and record["sk"] == f"QUERY#{record['id']}"
    with pytest.raises(ValueError):
        query_record("web-anth-us", "x", "r", origin="robot", created_by="x", now_iso="y")


def test_only_approved_active_queries_are_searched():
    table = web_table("approved")
    add_queries(table, MONITOR, "unapproved", approved_by=None)
    add_queries(table, MONITOR, "paused", status="paused")
    add_queries(table, MONITOR, "retired", status="retired")
    tavily = FakeTavily()

    collect(table, tavily)

    assert [c["query"] for c in tavily.calls] == ["approved"]
    assert not searchable(queries_of(table)["unapproved"]) and not searchable(queries_of(table)["retired"])


# --- paging through everything Tavily returns -----------------------------------------------------------------------------

def test_a_full_page_splits_the_date_window_until_every_result_is_read():
    # Tavily answers at most 20 per request and has no offset: 70 results over 14 days can only be read by narrowing the dates.
    tavily = FakeTavily(*[article(n, day(-(n % 14))) for n in range(70)])
    table = web_table()
    set_high_water(table, "ai agents", NOW - 14 * DAY)

    result = collect(table, tavily)

    assert result["status"] == "complete" and result["new"] == 70 == len(discs(table))
    assert len(tavily.calls) > 1 and all(c["max_results"] == TAVILY_PAGE_LIMIT for c in tavily.calls)
    assert all(c["start_date"] <= c["end_date"] for c in tavily.calls)


def test_every_query_is_searched_and_each_result_records_the_query_that_found_it():
    tavily = FakeTavily(article(1, day(-1), "ai agents"), article(2, day(-1), "open models"))
    table = web_table("ai agents", "open models")

    collect(table, tavily)

    found = sorted((d["title"], d["details"]["query"]) for d in discs(table))
    assert found == [("Story 1", "ai agents"), ("Story 2", "open models")]
    disc = next(d for d in discs(table) if d["title"] == "Story 1")
    assert disc["canonicalUrl"] == "https://example.org/story-1" and disc["details"]["snippet"] == "Snippet 1"
    assert disc["details"]["queryId"] == queries_of(table)["ai agents"]["id"]
    assert disc["sourcePublishedAt"] == day(-1) + "T00:00:00Z" and disc["sourceType"] == "web-search"
    assert disc["routing"] == "collected" and disc["monitorId"] == MONITOR


def test_a_saturated_single_day_is_accepted_not_split_forever():
    tavily = FakeTavily(*[article(n, day(-1)) for n in range(30)])
    table = web_table()
    set_high_water(table, "ai agents", NOW - 2 * DAY)

    result = collect(table, tavily)

    assert result["status"] == "complete" and result["new"] == TAVILY_PAGE_LIMIT


def test_a_rate_limit_is_waited_out_for_its_retry_after():
    tavily = FakeTavily(article(1, day(-1)))
    tavily.fail = [RateLimited("slow down", 7.0)]
    slept = []

    result = collect(web_table(), tavily, sleep=slept.append)

    assert slept == [7.0] and result["new"] == 1 and result["status"] == "complete"


def test_a_pass_that_runs_out_of_time_resumes_where_it_stopped_without_moving_the_high_water_mark():
    tavily = FakeTavily(*[article(n, day(-(n % 14))) for n in range(70)])
    table = web_table()
    set_high_water(table, "ai agents", NOW - 14 * DAY)
    ticks = iter(range(0, 1000))

    first = collect(table, tavily, budget_seconds=3, clock=lambda: float(next(ticks)))

    assert first["status"] == "partial" and "stopped early" in first["errors"][-1]["message"]
    assert state(table)["resume"]["web"] and state(table)["nextDueAt"] == NOW
    assert queries_of(table)["ai agents"]["highWater"] == NOW - 14 * DAY
    asked = len(tavily.calls)
    second = collect(table, tavily, now=NOW + 60)
    assert second["status"] == "complete" and len(discs(table)) == 70 and len(tavily.calls) > asked
    assert queries_of(table)["ai agents"]["highWater"] == NOW and "resume" not in state(table)


def test_a_query_added_during_a_resumed_pass_is_not_marked_as_searched():
    tavily = FakeTavily(*[article(n, day(-(n % 14))) for n in range(70)])
    table = web_table()
    set_high_water(table, "ai agents", NOW - 14 * DAY)
    ticks = iter(range(0, 1000))
    collect(table, tavily, budget_seconds=3, clock=lambda: float(next(ticks)))
    add_queries(table, MONITOR, "added later")

    collect(table, tavily, now=NOW + 60)

    assert "highWater" not in queries_of(table)["added later"]


# --- recency from each query's high-water mark ---------------------------------------------------------------------------

def test_a_new_query_without_a_mark_or_start_date_asks_tavily_with_no_date_filter():
    tavily = FakeTavily(article(1, day(-1)))

    collect(web_table(), tavily)

    assert len(tavily.calls) == 1 and "start_date" not in tavily.calls[0] and tavily.calls[0]["topic"] == "news"


def test_the_first_pass_starts_at_the_configured_start_date():
    tavily = FakeTavily(article(1, day(-1)))
    table = web_table(startDate="2026-10-01")

    collect(table, tavily)

    assert tavily.calls[0]["start_date"] == "2026-10-01" and tavily.calls[0]["end_date"] == day(0)


def test_later_passes_search_from_each_querys_last_complete_pass_never_a_fixed_window():
    tavily = FakeTavily(article(1, day(-1)))
    table = web_table()
    collect(table, tavily, now=NOW)
    assert queries_of(table)["ai agents"]["highWater"] == NOW

    later = NOW + 5 * DAY
    tavily.calls.clear()
    collect(table, tavily, now=later)

    assert tavily.calls[0]["start_date"] == day(-1, NOW) and tavily.calls[0]["end_date"] == day(0, later)
    assert queries_of(table)["ai agents"]["highWater"] == later


def test_a_failed_pass_leaves_the_mark_where_it_was():
    tavily = FakeTavily(article(1, day(-1)))
    table = web_table()
    collect(table, tavily, now=NOW)
    tavily.fail = [ValueError("Tavily search failed: HTTP 500")]

    result = collect(table, tavily, now=NOW + 2 * DAY)

    assert result["status"] == "failed" and queries_of(table)["ai agents"]["highWater"] == NOW


# --- QueryRun records ----------------------------------------------------------------------------------------------------

def test_each_query_of_a_pass_gets_a_query_run_with_its_counts_credits_and_parameters():
    tavily = FakeTavily(article(1, day(-1)), article(2, day(-1)), article(3, day(-1), "open models"))
    table = web_table("ai agents", "open models")
    collect(table, tavily)
    tavily.calls.clear()
    tavily.articles.append(article(4, day(-1)))

    result = collect(table, tavily, now=NOW + 2 * DAY)

    runs = {r["queryId"]: r for r in rows(table, "QRUN#")}
    first = runs[queries_of(table)["ai agents"]["id"]]
    assert first["runId"] == result["runId"] and first["monitorId"] == MONITOR
    assert (first["resultsReturned"], first["newCount"], first["duplicateCount"], first["credits"]) == (3, 1, 2, 1)
    assert first["params"]["topic"] == "news" and first["params"]["windows"] and first["requests"] == 1
    assert len(rows(table, "QRUN#")) == 4   # two passes, two queries each


def test_credits_follow_the_provider_usage_when_it_reports_it():
    table = web_table()

    def fetch(payload):
        return {"results": [], "usage": {"credits": 2}}

    collect(table, fetch)

    assert rows(table, "QRUN#")[0]["credits"] == 2


# --- shared candidates, provenance and dedupe -------------------------------------------------------------------------------

def test_a_found_story_is_a_candidate_with_provenance_naming_the_monitor_query_run_and_score():
    table = web_table()
    result = collect(table, FakeTavily(article(1, day(-1))))

    cand = candidate(table, "https://example.org/story-1")

    assert cand["canonicalUrl"] == "https://example.org/story-1" and cand["title"] == "Story 1"
    (entry,) = cand["provenance"]
    assert entry["monitorId"] == MONITOR and entry["runId"] == result["runId"] and entry["tavilyScoreBp"] == 5000
    assert entry["queryId"] == queries_of(table)["ai agents"]["id"] and entry["publishedDate"] == day(-1) + "T00:00:00Z"
    assert cand["collectedBy"][0]["monitorId"] == MONITOR and cand["collectedBy"][0]["sourceType"] == "web-search"


def test_a_url_this_monitor_already_collected_is_not_collected_again_and_gains_provenance():
    tavily = FakeTavily(article(1, day(-1)))
    table = web_table()
    collect(table, tavily, now=NOW)

    again = collect(table, tavily, now=NOW + 2 * DAY)

    assert again["new"] == 0 and again["unchanged"] >= 1 and len(discs(table)) == 1
    assert len(candidate(table, "https://example.org/story-1")["provenance"]) == 2


def test_a_story_another_source_already_found_is_not_collected_as_new_but_is_noted_on_its_candidate():
    table = web_table()
    store = DynamoStore(table)
    record_candidate(store, url="https://example.org/story-1?utm_source=hn", title="Alpha", published_at=None, monitor_id="hn",
                     source_type="hn-rss", group="hn", source_id="101", found_at="2026-10-20T00:00:00Z", run_id="r0", collected=True)

    result = collect(table, FakeTavily(article(1, day(-1)), article(2, day(-1))))

    assert [d["title"] for d in discs(table)] == ["Story 2"] and result["new"] == 1
    cand = candidate(table, "https://example.org/story-1")
    assert [p["monitorId"] for p in cand["provenance"]] == ["hn", MONITOR] and [c["monitorId"] for c in cand["collectedBy"]] == ["hn"]


def test_collecting_through_the_hn_collector_makes_the_candidate_web_monitors_see():
    table = web_table()
    table.put_item({"pk": "MONITOR#hn", "sk": "CONFIG", "sourceUrl": "https://news.ycombinator.com/rss", "intervalSeconds": 900, "enabled": True})
    feed = (b"<rss><channel><item><title>Alpha</title><link>https://example.org/story-1?utm_source=x</link>"
            b"<comments>https://news.ycombinator.com/item?id=101</comments></item></channel></rss>")
    run_collection(DynamoStore(table), "hn", fetch=lambda url: feed, now=NOW)

    collect(table, FakeTavily(article(1, day(-1)), article(2, day(-1))))

    assert [d["title"] for d in discs(table)] == ["Story 2"]


def test_an_email_submitted_link_is_a_candidate_web_monitors_skip():
    from papyrus_content.email_submission_intake import _note_candidate

    table = web_table()
    _note_candidate(DynamoStore(table), "p-apyr-us-email",
                    {"canonicalUrl": "https://example.org/story-1", "title": "From email", "sourceId": "s1",
                     "observedAt": "2026-10-20T00:00:00Z", "runId": "receipt-1"})

    collect(table, FakeTavily(article(1, day(-1)), article(2, day(-1))))

    assert [d["title"] for d in discs(table)] == ["Story 2"]


def test_web_monitors_of_the_shared_group_find_a_story_once_and_distinctive_keeps_its_own():
    table = web_table()
    table.put_item(monitor_config("shipped", enabled=True))
    add_queries(table, "web-shipped", "ai agents")
    table.put_item(monitor_config("distinctive", enabled=True))
    add_queries(table, "web-distinctive", "ai agents")
    tavily = FakeTavily(article(1, day(-1)))

    collect(table, tavily, monitor="web-shipped")
    collect(table, tavily)
    collect(table, tavily, monitor="web-distinctive")

    assert len(discs(table, "web-shipped")) == 1 and discs(table) == [] and len(discs(table, "web-distinctive")) == 1
    cand = candidate(table, "https://example.org/story-1")
    assert [c["monitorId"] for c in cand["collectedBy"]] == ["web-shipped", "web-distinctive"]
    assert [p["monitorId"] for p in cand["provenance"]] == ["web-shipped", MONITOR, "web-distinctive"]


# --- one scheduled invocation for every web monitor ------------------------------------------------------------------------

def test_one_invocation_collects_every_due_web_monitor_longest_overdue_first_and_skips_the_rest():
    table = FakeTable()
    for publication in ("anth-us", "shipped", "pilobol-us"):
        table.put_item(monitor_config(publication, enabled=True))
        add_queries(table, monitor_id(publication), "ai agents")
    table.put_item(monitor_config("data-parade", enabled=False))
    table.put_item({"pk": "MONITOR#hn", "sk": "CONFIG", "sourceUrl": "https://news.ycombinator.com/rss", "intervalSeconds": 900})
    store = DynamoStore(table)
    store.put_state("web-shipped", {"pk": "MONITOR#web-shipped", "sk": "STATE", "nextDueAt": NOW - 5000})
    store.put_state("web-pilobol-us", {"pk": "MONITOR#web-pilobol-us", "sk": "STATE", "nextDueAt": NOW + 10 * DAY})

    results = run_web_collections(store, ["web-anth-us", "web-shipped", "web-pilobol-us", "web-data-parade", "hn", "web-missing"],
                                  now=NOW, fetch=FakeTavily(article(1, day(-1))))

    assert [r["monitorId"] for r in results] == ["web-anth-us", "web-shipped"]   # never run (due since 0) is the longest overdue
    assert all(r["status"] == "complete" for r in results)


# --- per-publication routing config ----------------------------------------------------------------------------------------

def hn_router():
    config = hn_router_config()
    config["publications"] += [{"publicationId": p, "site": f"{p}.example", "appsyncEndpoint": config["publications"][0]["appsyncEndpoint"]}
                               for p in ("data-parade", "pilobol-us", "shipped")]
    return config


@pytest.mark.parametrize("publication", SHARED_CYCLOTRON)
def test_each_shared_cyclotron_monitor_routes_to_all_six_publications_with_the_hn_cyclotron_block(publication):
    hn = hn_router()
    config = router_config(publication, hn)

    parsed = validate_router_config(config)
    assert config["pk"] == f"MONITOR#{monitor_id(publication)}" and config["sk"] == "CONFIG#router"
    assert [p["publicationId"] for p in parsed["publications"]] == list(SHARED_CYCLOTRON)   # one combined request decides all six
    assert parsed["cyclotron"]["runId"] == hn["cyclotron"]["runId"] and parsed["cyclotron"]["endpoint"] == hn["cyclotron"]["endpoint"]
    assert config["cyclotron"] == hn["cyclotron"] and config["holdDecisions"] is True and parsed["mode"] == "live"
    assert monitor_config(publication)["candidateGroup"] == "shared"


def test_distinctive_has_no_cyclotron_and_holds_every_decision():
    config = router_config("distinctive", hn_router())

    parsed = validate_router_config(config)

    assert "cyclotron" not in config and parsed["cyclotron"] is None and parsed["decisions"] == "hold" and parsed["holdDecisions"] is True
    assert [p["publicationId"] for p in parsed["publications"]] == ["distinctive"]
    assert "candidateGroup" not in monitor_config("distinctive")


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


def test_a_released_shared_router_decides_the_find_for_all_six_publications_in_one_request():
    table = web_table()
    collect(table, FakeTavily(article(1, day(-1))))
    config = {**router_config("anth-us", hn_router()), "holdDecisions": False}
    table.put_item(config)
    lab = FakeCyclotron()
    lab.combined_enabled = True
    client = CyclotronClient(validate_router_config(config), sign=lambda m, u, b: {}, http=lab.http, sleep=lambda s: None, clock=lambda: 0)

    run_router(RouterStore(table), MONITOR, now=NOW + 10, cyclotron=client, deliver=lambda *a: {"referenceId": "r", "referenceLineageId": "r",
               "referenceVersion": 1}, appsync=lambda endpoint: object(),
               context_receipt=lambda c, p: {"contextHash": None, "reason": "test"})

    (post,) = [c for c in lab.combined_calls if c[0] == "POST"]
    assert sorted(post[2]["payload"]["bindings"]) == sorted(SHARED_CYCLOTRON)


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

def drafted(n):
    return json.dumps([{"query": f"query {i}", "rationale": f"because {i}"} for i in range(n)])


def test_queries_are_drafted_from_mission_policy_and_criteria_and_retried_once_when_the_model_misbehaves(tmp_path):
    from papyrus_content import monitoring_web_queries as wq

    (tmp_path / "anth-us-relevance.json").write_text(json.dumps({"question": "Should this source become a reference?"}))
    answers = iter(["not json", drafted(9)])
    prompts = []

    def ask(message):
        prompts.append(message)
        return next(answers)

    pack = {"entries": [{"scope": "publication", "kind": "mission", "text": "Show the work."},
                        {"scope": "publication", "kind": "policy", "text": "Cite primary sources."}], "contextHash": "h"}
    publications = wq.router_publications(hn_router())

    proposal = wq.propose("anth-us", publications, ask, criteria_dir=tmp_path, client_factory=lambda endpoint: object(),
                          resolve=lambda client, **kw: pack)

    assert proposal["queries"][0] == {"text": "query 0", "rationale": "because 0"} and len(proposal["queries"]) == 9
    assert proposal["monitorId"] == "web-anth-us"
    assert proposal["basedOn"] == {"mission": True, "policy": True, "criteria": True, "contextHash": "h"}
    assert len(prompts) == 2 and "Show the work." in prompts[1] and "Should this source become a reference?" in prompts[1]


@pytest.mark.parametrize("answer", [drafted(1), drafted(16), json.dumps({"a": 1}), json.dumps(["bare string"])])
def test_a_proposal_outside_eight_to_fifteen_queries_is_refused(answer):
    from papyrus_content import monitoring_web_queries as wq

    with pytest.raises(ValueError):
        wq.parse_queries(answer)


def test_without_local_criteria_the_proposal_says_so(tmp_path):
    from papyrus_content import monitoring_web_queries as wq

    assert wq.criteria_text("distinctive", tmp_path) is None
