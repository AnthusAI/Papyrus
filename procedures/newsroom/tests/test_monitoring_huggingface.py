"""Hugging Face Hub monitor: the model source, collection and dedupe, windowed backfill, and rule-based routing.

Every Hub response here is a recorded one (fixtures/huggingface); nothing touches the network.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from papyrus_content import monitoring_huggingface as hf
from papyrus_content import monitoring_intake, monitoring_router as mr
from papyrus_content.monitoring_backfill import backfill_collection
from papyrus_content.monitoring_cloud import DynamoStore, _validate_config, run_collection
from papyrus_content.monitoring_router import RouterStore, run_router, validate_request, validate_router_config

from test_monitoring_router import ENDPOINT, Delivery, FakeTable

FIXTURES = Path(__file__).parent / "fixtures" / "huggingface"
NOW = datetime(2026, 10, 25, 13, 0, tzinfo=timezone.utc).timestamp()
DAY = 86400
BASE = "https://huggingface.co/api/models"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


TTS, NVIDIA, LIKED = fixture("text-to-speech-newest.json"), fixture("nvidia-newest.json"), fixture("text-generation-most-liked.json")
CONFIG = {"pk": "MONITOR#huggingface", "sk": "CONFIG", "sourceType": "huggingface-models", "sourceUrl": BASE,
          "intervalSeconds": DAY, "limit": 300, "enabled": True, "pipelineTags": ["text-to-speech"],
          "authors": ["hexgrad"], "minLikes": 1, "lookbackDays": 7, "pageSize": 6, "pagesPerQuery": 4}


class Hub:
    """Replays recorded rows as the Hub would serve them: filtered per query, paged by a cursor in the URL."""

    def __init__(self, rows_by_query):
        self.rows_by_query, self.requests = rows_by_query, []

    def __call__(self, url):
        self.requests.append(url)
        from urllib.parse import parse_qs, urlsplit
        params = parse_qs(urlsplit(url).query)
        key = next((f"{name}:{params[name][0]}" for name in ("author", "search", "pipeline_tag") if name in params), "all")
        key += f":{params['sort'][0]}"
        rows, start, size = self.rows_by_query.get(key, []), int(params.get("cursor", ["0"])[0]), int(params["limit"][0])
        nxt = f"{url.split('&cursor=')[0]}&cursor={start + size}" if start + size < len(rows) else None
        return json.dumps(rows[start:start + size]).encode(), nxt


def tts_hub(**more):
    return Hub({"pipeline_tag:text-to-speech:createdAt": TTS, "author:hexgrad:createdAt": [], **more})


def run(table, hub, now=NOW, monitor="huggingface"):
    return run_collection(DynamoStore(table), monitor, fetch=hub, now=now)


def configured():
    table = FakeTable()
    table.put_item(deepcopy(CONFIG))
    return table


# --- one model ---------------------------------------------------------------------------------------

def details_of(rows, model_id):
    return next(d for d in hf.parse_hf_models(json.dumps(rows).encode()) if d["modelId"] == model_id)


def test_a_model_carries_the_fields_the_knowledge_map_needs():
    d = details_of(LIKED, "meta-llama/Llama-3.1-8B-Instruct")

    assert d["author"] == "meta-llama" and d["pipelineTag"] == "text-generation" and d["libraryName"] == "transformers"
    assert d["createdAt"] == "2024-07-18T08:56:00.000Z" and d["lastModified"] and len(d["sha"]) == 40
    assert d["license"] == "llama3.1" and d["likes"] == 8597 and d["downloads"] > 0
    assert "text-generation" in d["tags"]
    assert "extra_gated_prompt" not in json.dumps(d)         # model card text is never kept
    item = hf.hf_item(d)
    assert item.canonical_url == "https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct" and item.source_id == "meta-llama--Llama-3_1-8B-Instruct-" + item.source_id[-8:]
    assert item.title == "meta-llama/Llama-3.1-8B-Instruct: text-generation model" and item.published_at == d["createdAt"]


def test_base_models_become_relation_ready_pairs_from_tags_and_the_card():
    llama = details_of(LIKED, "meta-llama/Llama-3.1-8B-Instruct")
    quantized = details_of(TTS, "mradermacher/Lure-TTS-0.6B-GGUF")
    finetune = details_of(TTS, "anyantudre/moore-tts-kokoro")
    original = details_of(TTS, "pythainlp/MakHamTTS")

    # the typed tag wins over the bare tag the Hub adds beside it; a card value the tags do not name is `declared`
    assert llama["baseModels"] == [{"modelId": "meta-llama/Llama-3.1-8B", "relation": "finetune"},
                                   {"modelId": "meta-llama/Meta-Llama-3.1-8B", "relation": "declared"}]
    assert quantized["baseModels"] == [{"modelId": "Tesslate/Lure-TTS-0.6B", "relation": "quantized"}]
    assert finetune["baseModels"] == [{"modelId": "hexgrad/Kokoro-82M", "relation": "finetune"}]
    assert original["baseModels"] == []


def test_a_card_base_model_list_and_junk_values():
    row = {"id": "a/b", "createdAt": "2026-10-01T00:00:00.000Z", "tags": [], "sha": "x" * 40,
           "cardData": {"base_model": ["org/one", "https://evil.example/x", "org/one", 7]}}

    assert hf.parse_hf_models(json.dumps([row]).encode())[0]["baseModels"] == [{"modelId": "org/one", "relation": "declared"}]


@pytest.mark.parametrize("model_id, expected", [
    ("org/name", "org--name"),
    ("gpt2", "gpt2"),
    ("org/name.v1", None),                       # a dot is not allowed in a source id: hashed
    ("o/" + "n" * 90, None)])                    # too long: hashed
def test_source_ids_are_key_safe_and_stable(model_id, expected):
    source_id = hf.hf_source_id(model_id)

    assert hf.SOURCE_ID.match(source_id) and source_id == hf.hf_source_id(model_id)
    assert (source_id == expected) if expected else source_id[-9] == "-"
    assert hf.hf_source_id("org/name_v1") != hf.hf_source_id("org/name.v1")


@pytest.mark.parametrize("body", [b"<html>nope</html>", json.dumps({"error": "Invalid sort"}).encode()])
def test_error_pages_are_refused(body):
    with pytest.raises(ValueError):
        hf.parse_hf_models(body)


def test_rows_that_are_not_models_are_skipped():
    rows = [{"id": "../etc/passwd", "createdAt": "2026-10-01T00:00:00Z"}, {"id": "ok/model"}, {"id": "ok/model", "createdAt": "2026-10-01T00:00:00Z"}]

    assert [d["modelId"] for d in hf.parse_hf_models(json.dumps(rows).encode())] == ["ok/model"]


# --- the acceptance rule -----------------------------------------------------------------------------

def test_the_rule_is_filters_then_watchlist_or_thresholds():
    popular = {"author": "someone", "pipelineTag": "text-generation", "likes": 40, "downloads": 5}
    quiet = {"author": "someone", "pipelineTag": "text-generation", "likes": 1, "downloads": 5000}
    org = {"author": "Qwen", "pipelineTag": "text-generation", "likes": 0, "downloads": 0}
    rule = {"pipelineTags": ["text-generation"], "authors": ["qwen"], "minLikes": 10, "minDownloads": 10000}

    assert hf.hf_accepts(popular, rule) and hf.hf_accepts(org, rule) and not hf.hf_accepts(quiet, rule)
    assert hf.hf_accepts(quiet, {**rule, "minDownloads": 1000})
    assert not hf.hf_accepts({**popular, "pipelineTag": "text-to-speech"}, rule)
    assert hf.hf_accepts(quiet, {"pipelineTags": ["text-generation"]})        # no thresholds: every match


# --- repackaged models are excluded ------------------------------------------------------------------

REPACK_RULE = {"excludeTags": ["gguf", "mlx"], "excludeBaseRelations": ["quantized", "merge"],
               "excludeIdPatterns": ["-(q|iq)[0-9]", "abliterat"]}


def test_exclusions_name_the_first_reason_and_default_to_nothing():
    quant = {"modelId": "x/Model-GGUF", "tags": ["GGUF"], "baseModels": [{"modelId": "a/b", "relation": "quantized"}]}
    assert hf.hf_exclusion(quant, REPACK_RULE) == "tag"                                    # tags are case-insensitive
    assert hf.hf_exclusion({**quant, "tags": []}, REPACK_RULE) == "baseRelation"
    assert hf.hf_exclusion({"modelId": "x/Llama-Q4_K", "tags": []}, {"excludeIdPatterns": ["-(q|iq)[0-9]"]}) == "idPattern"
    assert hf.hf_exclusion({"modelId": "x/Llama-ABLITERATED"}, REPACK_RULE) == "idPattern"   # patterns are case-insensitive
    finetune = {"modelId": "x/Model", "tags": ["text-generation"], "baseModels": [{"modelId": "a/b", "relation": "finetune"}]}
    assert hf.hf_exclusion(finetune, REPACK_RULE) is None                                  # finetunes are kept unless listed
    assert hf.hf_exclusion(quant, {}) is None and hf.hf_accepts(quant, {})                 # no config, no change
    assert not hf.hf_accepts(quant, REPACK_RULE) and hf.hf_accepts(finetune, REPACK_RULE)


@pytest.mark.parametrize("change, message", [
    ({"excludeTags": "gguf"}, "excludeTags"),
    ({"excludeTags": ["GGUF Q4"]}, "excludeTags"),
    ({"excludeBaseRelations": ["copy"]}, "excludeBaseRelations"),
    ({"excludeIdPatterns": ["(unclosed"]}, "regular expression"),
    ({"excludeIdPatterns": [""]}, "excludeIdPatterns"),
    ({"excludeIdPatterns": ["x"] * 2 + [str(n) for n in range(60)]}, "at most")])
def test_exclusion_config_is_validated(change, message):
    with pytest.raises(ValueError, match=message):
        hf.validate_rule(change)


def test_collection_skips_repackaged_models_and_counts_them_per_reason():
    table = FakeTable()
    table.put_item({**CONFIG, "minLikes": 0, "authors": [], "excludeTags": ["gguf", "mlx"],
                    "excludeIdPatterns": ["OMNIVOICE"]})

    result = run(table, tts_hub())

    kept = sorted(d["details"]["modelId"] for d in table.by_prefix("DISC#"))
    assert result["new"] == 5 and len(kept) == 5 and not any("GGUF" in m or "MLX" in m.upper() for m in kept)
    assert result["read"]["skipped"] == {"tag": 5, "idPattern": 2}                          # in the RUN# receipt
    assert not any("omnivoice" in m for m in kept)


def test_skipped_models_are_counted_once_and_by_base_relation():
    table = FakeTable()
    table.put_item({**CONFIG, "minLikes": 0, "authors": [], "excludeBaseRelations": ["quantized"]})

    result = run(table, tts_hub())

    assert result["new"] == 9 and result["read"]["skipped"] == {"baseRelation": 3}


def test_an_unconfigured_monitor_has_no_skip_counts():
    table = FakeTable()
    table.put_item({**CONFIG, "minLikes": 0, "authors": []})

    result = run(table, tts_hub())

    assert result["new"] == 12 and "skipped" not in result["read"]


def test_backfill_applies_the_same_exclusions():
    table = backfill_config(excludeIdPatterns=["deepseek"])

    result, lines = backfill(table, liked_hub(), apply=True)

    assert result["counts"] == {"new": 1} and result["skipped"] == {"idPattern": 1}
    assert [r["details"]["modelId"] for r in table.by_prefix("DISC#")] == ["meta-llama/Llama-3.1-8B-Instruct"]
    assert "skipped as repackaged: idPattern=1" in lines[-1]


def test_the_router_rule_excludes_repackaged_models_too():
    table, delivery = collected(), Delivery()
    table.put_item(router_config(rule={"excludeTags": ["gguf", "mlx"]}))

    result = route(table, delivery)

    assert result["counts"]["delivered"] == 7 and result["counts"]["routed"] == 12
    finals = [row["final"]["reason"] for row in table.by_prefix("ROUTE#") if row.get("final")]
    assert finals == ["excluded by the monitor's rule"] * 5


@pytest.mark.parametrize("change, message", [
    ({"sourceUrl": "https://news.ycombinator.com/rss"}, "huggingface.co"),
    ({"sourceUrl": "https://huggingface.co/api/datasets"}, "api/models"),
    ({"sourceUrl": "https://huggingface.co/api/models?sort=likes"}, "sourceUrl"),
    ({"pipelineTags": [], "authors": []}, "at least one of"),
    ({"pipelineTags": ["Text Generation"]}, "pipelineTags"),
    ({"authors": ["../x"]}, "authors"),
    ({"minLikes": -1}, "minLikes"),
    ({"minLikes": "5"}, "minLikes"),
    ({"sort": "random"}, "sort"),
    ({"lookbackDays": 0}, "lookbackDays"),
    ({"pageSize": 5000}, "pageSize"),
    ({"limit": 5000}, "limit")])
def test_config_is_validated_for_its_own_source(change, message):
    with pytest.raises(ValueError, match=message):
        _validate_config({**CONFIG, **change})


def test_a_valid_config_fills_in_the_defaults():
    config = _validate_config({"sourceType": "huggingface-models", "sourceUrl": BASE, "intervalSeconds": DAY, "limit": 300,
                               "authors": ["Qwen"]})

    assert config["sort"] == "createdAt" and config["lookbackDays"] == 7 and config["pageSize"] == 200
    assert config["pagesPerQuery"] == 10 and config["search"] == [] and config["maxItems"] == 300


# --- the Hub requests --------------------------------------------------------------------------------

def test_a_list_request_names_its_filters_sort_page_size_and_fields():
    url = hf.list_url(BASE, {"sort": "createdAt", "pipeline_tag": "text-to-speech", "author": "nvidia"}, 200)

    assert url.startswith(BASE + "?limit=200&direction=-1&sort=createdAt&author=nvidia&pipeline_tag=text-to-speech")
    assert "expand=cardData" in url and "expand=sha" in url and "expand=createdAt" in url


@pytest.mark.parametrize("url", ["http://huggingface.co/api/models", "https://evil.example/api/models",
                                 "https://huggingface.co.evil.example/api/models", "https://huggingface.co/api/datasets",
                                 "https://user:pw" + chr(64) + "huggingface.co/api/models"])
def test_only_hub_model_urls_are_ever_fetched(url):
    with pytest.raises(ValueError):
        hf.check_hub_url(url)


def test_the_default_fetch_sends_a_descriptive_user_agent_and_follows_the_link_cursor(monkeypatch):
    seen = {}

    class Response:
        headers = {"Link": f'<{BASE}?limit=2&cursor=abc>; rel="next"'}

        def read(self, n):
            return b"[]"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout):
        seen.update(agent=request.get_header("User-agent"), url=request.full_url)
        return Response()

    monkeypatch.setattr(hf, "urlopen", urlopen)
    monkeypatch.setattr(hf.time, "sleep", lambda s: None)

    body, nxt = hf.fetch_hf_page(BASE + "?limit=2")

    assert seen["agent"].startswith("Papyrus-Monitor/") and "github.com/AnthusAI/Papyrus" in seen["agent"]
    assert (body, nxt) == (b"[]", f"{BASE}?limit=2&cursor=abc")


def test_a_cursor_that_leaves_the_hub_is_refused(monkeypatch):
    class Response:
        headers = {"Link": '<https://evil.example/api/models?cursor=1>; rel="next"'}

        def read(self, n):
            return b"[]"

        __enter__ = lambda self: self
        __exit__ = lambda self, *exc: False

    monkeypatch.setattr(hf, "urlopen", lambda request, timeout: Response())
    monkeypatch.setattr(hf.time, "sleep", lambda s: None)

    with pytest.raises(ValueError):
        hf.fetch_hf_page(BASE + "?limit=2")


# --- collection --------------------------------------------------------------------------------------

def test_collection_pages_every_query_and_keeps_models_that_pass_the_rule():
    table, hub = configured(), tts_hub()

    result = run(table, hub)

    # twelve recorded models, six per page; only mradermacher/Lure-TTS-0.6B-GGUF has the one like the rule asks for
    assert result["status"] == "complete" and result["new"] == 1 and result["itemCount"] == 1
    assert result["read"]["requests"] == 3                       # hexgrad (1 empty page) + two text-to-speech pages
    assert sum("pipeline_tag=text-to-speech" in url for url in hub.requests) == 2
    (disc,) = table.by_prefix("DISC#mradermacher--Lure-TTS-0_6B-GGUF-")
    assert disc["routing"] == "collected" and disc["gsi1pk"] == "ROUTING#huggingface#collected"
    assert disc["sourceType"] == "huggingface-models" and disc["canonicalUrl"] == "https://huggingface.co/mradermacher/Lure-TTS-0.6B-GGUF"
    assert disc["details"]["baseModels"] == [{"modelId": "Tesslate/Lure-TTS-0.6B", "relation": "quantized"}]
    assert disc["details"]["likes"] == 1 and disc["sourcePublishedAt"] == disc["details"]["createdAt"]


def test_a_watchlisted_author_is_kept_whatever_its_signals():
    table = configured()
    table.put_item({**CONFIG, "authors": ["nvidia"], "pipelineTags": ["robotics"]})
    hub = Hub({"author:nvidia:createdAt": NVIDIA, "pipeline_tag:robotics:createdAt": []})

    result = run(table, hub, now=datetime(2026, 10, 26, tzinfo=timezone.utc).timestamp())

    assert result["new"] == 2                       # the two robotics models; the one with no pipeline tag fails the tag filter
    assert {row["details"]["author"] for row in table.by_prefix("DISC#")} == {"nvidia"}
    assert any(row["details"]["likes"] == 0 for row in table.by_prefix("DISC#"))


def test_a_model_found_by_two_queries_is_stored_once():
    table = configured()
    table.put_item({**CONFIG, "authors": ["anyantudre"], "minLikes": 0})
    hub = tts_hub(**{"author:anyantudre:createdAt": [r for r in TTS if r["author"] == "anyantudre"]})

    result = run(table, hub)

    assert len(table.by_prefix("DISC#anyantudre--moore-tts-kokoro#")) == 1 and result["new"] == 12


def test_a_second_run_dedupes_on_the_models_revision():
    table, hub = configured(), tts_hub()
    run(table, hub)

    same = run(table, hub, now=NOW + DAY)
    assert same["unchanged"] == 1 and same["new"] == 0 and same["revised"] == 0

    liked_more = deepcopy(TTS)
    liked_more[5]["likes"] = 30                        # a signal moved; the model did not change
    assert run(table, tts_hub(**{"pipeline_tag:text-to-speech:createdAt": liked_more}), now=NOW + 2 * DAY)["unchanged"] == 1

    edited = deepcopy(TTS)
    edited[5]["sha"] = "f" * 40                        # a new commit on the model
    revised = run(table, tts_hub(**{"pipeline_tag:text-to-speech:createdAt": edited}), now=NOW + 3 * DAY)
    assert revised["revised"] == 1
    assert [r["sk"][-6:] for r in table.by_prefix("DISC#mradermacher--Lure-TTS-0_6B-GGUF-")] == ["000001", "000002"]
    assert table.by_prefix("DISC#mradermacher--Lure-TTS-0_6B-GGUF-")[1]["details"]["sha"] == "f" * 40


def test_the_window_drops_models_created_before_it():
    table = configured()
    table.put_item({**CONFIG, "minLikes": 0})
    hub = tts_hub()

    result = run(table, hub, now=datetime(2026, 11, 20, tzinfo=timezone.utc).timestamp())

    assert result["itemCount"] == 0 and len(hub.requests) == 2      # paging stops at the first page that ends inside the window


def test_newest_first_queries_stop_paging_once_past_the_window():
    table = configured()
    table.put_item({**CONFIG, "authors": [], "minLikes": 0, "pageSize": 2, "pagesPerQuery": 50, "lookbackDays": 1})
    hub = tts_hub()

    # the window starts at 2026-10-25T10:00Z: the third page of two ends before it, so a fourth is never asked for
    result = run(table, hub, now=datetime(2026, 10, 26, 10, tzinfo=timezone.utc).timestamp())

    assert len(hub.requests) == 3 and result["itemCount"] == 5


def test_one_failing_query_does_not_hide_the_others():
    table = configured()

    def fetch(url):
        if "author=hexgrad" in url:
            raise OSError("connection reset")
        return tts_hub()(url)

    result = run_collection(DynamoStore(table), "huggingface", fetch=fetch, now=NOW)

    assert result["status"] == "partial" and result["new"] == 1 and result["errors"][0]["query"] == "author:hexgrad"


def test_all_queries_failing_fails_the_run():
    table = configured()

    def fetch(url):
        raise OSError("hub down")

    result = run_collection(DynamoStore(table), "huggingface", fetch=fetch, now=NOW)

    assert result["status"] == "failed" and "hub down" in result["errors"][0]["message"]


def test_a_rate_limit_stops_the_read_and_the_receipt_says_so():
    table = configured()

    def fetch(url):
        raise hf.RateLimited("slow down")

    result = run_collection(DynamoStore(table), "huggingface", fetch=fetch, now=NOW)

    assert result["read"]["stoppedBy"] == "rate_limited" and result["itemCount"] == 0
    assert table.by_prefix("RUN#")[0]["read"]["stoppedBy"] == "rate_limited"
    assert any("stopped early" in e["message"] for e in result["errors"])


def test_the_item_cap_keeps_the_newest_models():
    table = configured()
    table.put_item({**CONFIG, "minLikes": 0, "limit": 3})

    result = run(table, tts_hub())

    assert result["itemCount"] == 3
    assert [r["details"]["modelId"] for r in table.by_prefix("DISC#")] and max(r["sourcePublishedAt"] for r in table.by_prefix("DISC#")) == TTS[0]["createdAt"]


def test_other_sources_discoveries_are_unchanged():
    table = FakeTable()
    table.put_item({"pk": "MONITOR#hn", "sk": "CONFIG", "sourceUrl": "https://news.ycombinator.com/rss", "intervalSeconds": 900, "limit": 30})
    feed = b"<rss><channel><item><title>A</title><link>https://example.org/a</link><comments>https://news.ycombinator.com/item?id=1</comments></item></channel></rss>"
    run_collection(DynamoStore(table), "hn", fetch=lambda url: feed, now=NOW)

    (disc,) = table.by_prefix("DISC#")
    assert "details" not in disc and "sourceType" not in disc


# --- backfill ----------------------------------------------------------------------------------------

def backfill_config(**more):
    table = FakeTable()
    table.put_item({**CONFIG, "authors": [], "pipelineTags": ["text-generation"], "minLikes": 5000, "pageSize": 2, **more})
    return table


def liked_hub():
    return Hub({"pipeline_tag:text-generation:likes": LIKED})


def backfill(table, hub, since="2024-06-01T00:00:00Z", **kwargs):
    lines = []
    result = backfill_collection(DynamoStore(table), "huggingface", datetime.fromisoformat(since.replace("Z", "+00:00")),
                                 fetch=hub, now=NOW, emit=lines.append, **kwargs)
    return result, lines


def test_backfill_pages_by_likes_until_the_minimum_and_keeps_only_the_window():
    table, hub = backfill_config(), liked_hub()

    result, _ = backfill(table, hub, apply=True)

    assert result["status"] == "complete" and result["counts"] == {"new": 2}
    assert sorted(r["details"]["modelId"] for r in table.by_prefix("DISC#")) == ["deepseek-ai/DeepSeek-R1", "meta-llama/Llama-3.1-8B-Instruct"]
    assert "sort=likes" in hub.requests[0] and len(hub.requests) == 2    # stops at the page whose last row is under 5000 likes


def test_backfill_since_is_the_start_of_the_window_and_until_the_end():
    table = backfill_config()

    result, _ = backfill(table, liked_hub(), since="2025-01-01T00:00:00Z", apply=True)
    assert [r["details"]["modelId"] for r in table.by_prefix("DISC#")] == ["deepseek-ai/DeepSeek-R1"] and result["counts"] == {"new": 1}

    other = backfill_config()
    backfill(other, liked_hub(), since="2024-06-01T00:00:00Z", until=datetime(2025, 1, 1, tzinfo=timezone.utc), apply=True)
    assert [r["details"]["modelId"] for r in other.by_prefix("DISC#")] == ["meta-llama/Llama-3.1-8B-Instruct"]


def test_backfill_is_idempotent_through_the_item_dedupe():
    table = backfill_config()
    backfill(table, liked_hub(), apply=True)
    discoveries = len(table.by_prefix("DISC#"))

    finished, _ = backfill(table, liked_hub(), apply=True)          # the checkpoint says every query is done
    assert finished["status"] == "complete" and finished["requests"] == 0

    for key in [k for k in table.items if k[1].startswith("BACKFILL#")]:
        del table.items[key]                                         # as if the checkpoint were lost
    again, _ = backfill(table, liked_hub(), apply=True)

    assert again["counts"] == {"unchanged": 2} and len(table.by_prefix("DISC#")) == discoveries


def test_backfill_next_to_the_live_collector_does_not_duplicate_a_model():
    table = configured()
    run(table, tts_hub())
    live = len(table.by_prefix("DISC#"))
    table.put_item({**CONFIG, "minLikes": 1, "pageSize": 6})
    hub = Hub({"pipeline_tag:text-to-speech:likes": sorted(TTS, key=lambda r: -r["likes"]), "author:hexgrad:createdAt": []})

    result, _ = backfill(table, hub, since="2026-09-01T00:00:00Z", apply=True)

    assert result["counts"] == {"unchanged": 1} and len(table.by_prefix("DISC#")) == live


def test_a_dry_run_counts_and_writes_nothing():
    table = backfill_config()

    result, lines = backfill(table, liked_hub())

    assert result["applied"] is False and result["counts"] == {"would add": 2}
    assert not table.by_prefix("DISC#") and not table.by_prefix("ITEM#") and not table.by_prefix("BACKFILL#")
    assert any("DRY RUN" in line for line in lines)


def test_backfill_pauses_at_its_request_bound_and_resumes_from_the_checkpoint():
    table = backfill_config()

    first, lines = backfill(table, liked_hub(), apply=True, max_requests=1)

    assert first["status"] == "paused" and first["stoppedBy"] == "request_ceiling" and first["requests"] == 1
    assert any("run the same command again" in line for line in lines)
    checkpoint = table.by_prefix("BACKFILL#")[0]
    assert checkpoint["queries"]["tag:text-generation:likes"]["next"] and not checkpoint["queries"]["tag:text-generation:likes"]["done"]
    assert "LOCK" not in {k[1] for k in table.items}

    hub = liked_hub()
    second, _ = backfill(table, hub, apply=True, max_requests=10, fetch=None) if False else (None, None)
    hub = liked_hub()
    second, _ = backfill(table, hub, apply=True)
    assert second["status"] == "complete"
    assert hub.requests[0].endswith("cursor=2")          # continued from the stored cursor, not from the top
    assert len(table.by_prefix("DISC#")) == 2


def test_backfill_pauses_on_a_rate_limit_and_keeps_what_it_loaded():
    table = backfill_config()
    calls = []

    def fetch(url):
        calls.append(url)
        if len(calls) == 2:
            raise hf.RateLimited("slow down")
        return liked_hub()(url)

    result, _ = backfill(table, fetch, apply=True)

    assert result["status"] == "paused" and result["stoppedBy"] == "rate_limited"
    assert len(table.by_prefix("DISC#")) == 2 and table.by_prefix("BACKFILL#")      # the first page was kept


def test_backfill_by_creation_date_for_authors_and_search():
    table = FakeTable()
    table.put_item({**CONFIG, "pipelineTags": [], "authors": ["nvidia"], "search": [], "minLikes": None, "pageSize": 2,
                    "minDownloads": None})
    hub = Hub({"author:nvidia:createdAt": NVIDIA})

    result, _ = backfill(table, hub, since="2026-10-01T00:00:00Z", apply=True)

    assert result["status"] == "complete" and result["counts"] == {"new": 3} and len(hub.requests) == 2


def test_backfill_refuses_other_sources_and_naive_times():
    table = FakeTable()
    table.put_item({"pk": "MONITOR#hn", "sk": "CONFIG", "sourceUrl": "https://news.ycombinator.com/rss", "intervalSeconds": 900, "limit": 30})
    with pytest.raises(ValueError, match="huggingface-models"):
        backfill_collection(DynamoStore(table), "hn", datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="timezone"):
        backfill_collection(DynamoStore(backfill_config()), "huggingface", datetime(2026, 1, 1))


def test_the_cli_exposes_backfill(monkeypatch):
    from papyrus_content import monitoring_backfill, monitoring_commands
    seen = {}
    monkeypatch.setattr(monitoring_backfill, "collection_command", lambda args: seen.update(vars(args)) or 0)

    code = monitoring_commands.command(["backfill", "--monitor", "huggingface", "--since", "2025-10-25T00:00:00Z", "--max-pages", "7"])

    assert code == 0 and seen["monitor"] == "huggingface" and seen["max_pages"] == 7 and seen["apply"] is False


# --- routing -----------------------------------------------------------------------------------------

DIRECT_PUBLICATION = {"publicationId": "shipped", "site": "shipped.anth.us", "appsyncEndpoint": ENDPOINT}


def router_config(mode="live", **overrides):
    return {"pk": "MONITOR#huggingface", "sk": "CONFIG#router", "mode": mode, "decisions": "direct",
            "publications": [DIRECT_PUBLICATION], **overrides}


def collected(**config):
    table = FakeTable()
    table.put_item({**CONFIG, "minLikes": 0, "authors": [], **config})
    run(table, tts_hub())
    return table


def route(table, delivery, now=NOW + 3600):
    return run_router(RouterStore(table), "huggingface", now=now, cyclotron=None, deliver=delivery, appsync=lambda endpoint: object(),
                      context_receipt=lambda client, publication: {"contextHash": "h", "reason": None})


def test_the_router_accepts_a_rule_only_with_direct_decisions():
    config = validate_router_config(router_config(rule={"minLikes": 1, "authors": ["hexgrad"]}))
    assert config["rule"] == {"pipelineTags": [], "authors": ["hexgrad"], "minLikes": 1}
    kept = validate_router_config(router_config(rule={"excludeTags": ["gguf"], "excludeIdPatterns": ["exl[23]"]}))["rule"]
    assert kept["excludeTags"] == ["gguf"] and kept["excludeIdPatterns"] == ["exl[23]"] and "excludeBaseRelations" not in kept
    assert validate_router_config(router_config())["rule"] is None
    with pytest.raises(ValueError, match="minLikes"):
        validate_router_config(router_config(rule={"minLikes": "many"}))
    with pytest.raises(ValueError, match="direct"):
        validate_router_config({**router_config(rule={"minLikes": 1}), "decisions": "cyclotron",
                                "cyclotron": {"endpoint": "https://o01d28uizl.execute-api.us-east-1.amazonaws.com", "accountId": "a",
                                              "bindingRevision": "1"}})


def test_a_rule_routes_the_models_that_pass_to_the_publication_and_finishes_the_rest():
    table, delivery = collected(), Delivery()
    table.put_item(router_config(rule={"minLikes": 1}))

    result = route(table, delivery)

    assert result["counts"]["routed"] == 12 and result["counts"]["delivered"] == 1
    assert [call[:2] for call in delivery.calls] == [("shipped", "mradermacher--Lure-TTS-0_6B-GGUF-" + delivery.calls[0][1][-8:])]
    finals = {row["sourceId"]: row.get("final") for row in table.by_prefix("ROUTE#")}
    assert sum(1 for f in finals.values() if f and f["reason"] == "excluded by the monitor's rule") == 11
    assert all("gsi1pk" not in row for row in table.by_prefix("DISC#"))        # nothing left waiting
    assert route(table, delivery, now=NOW + 7200)["counts"]["examined"] == 0


def test_a_rule_dry_run_records_who_would_be_delivered():
    table, delivery = collected(), Delivery()
    table.put_item(router_config(mode="dry-run", rule={"minLikes": 1}))

    route(table, delivery)

    wants = [row["dryRun"]["requests"]["shipped"]["wouldDeliver"] for row in table.by_prefix("ROUTE#")]
    assert sorted(wants) == [False] * 11 + [True] and delivery.calls == []


def test_without_a_rule_every_collected_model_is_delivered():
    table, delivery = collected(), Delivery()
    table.put_item(router_config())

    assert route(table, delivery)["counts"]["delivered"] == 12


def test_a_cyclotron_decision_request_for_a_model_names_its_source():
    config = validate_router_config({
        "mode": "dry-run", "publications": [DIRECT_PUBLICATION],
        "cyclotron": {"endpoint": "https://o01d28uizl.execute-api.us-east-1.amazonaws.com", "accountId": "acct-1", "runId": "run-1",
                      "bindingRevision": "1"}})
    table = collected()
    disc = DynamoStore._clean(table.by_prefix("DISC#mradermacher--Lure-TTS-0_6B-GGUF-")[0]) if table.by_prefix("DISC#mradermacher") else DynamoStore._clean(table.by_prefix("DISC#")[0])

    built = mr.build_decide_request(config, config["publications"][0], disc)

    values = built["body"]["payload"]["item"]["values"]
    assert values["source"] == "huggingface" and built["body"]["payload"]["item"]["id"].startswith("huggingface-")
    validate_request(built["body"])
    with pytest.raises(ValueError):
        validate_request({**built["body"], "payload": {**built["body"]["payload"], "item": {
            "id": "huggingface-x", "values": {**values, "source": "myspace"}}}})


def test_delivery_carries_the_models_structured_fields_into_the_provenance(monkeypatch):
    captured, real_intake = {}, monitoring_intake.ReferenceIntake

    class RecordingIntake:
        def __init__(self, client, monitor, *, auth_mode):
            captured["monitor"] = monitor

        def __call__(self, item, provenance):
            captured.update(item=item, provenance=provenance)
            return {"referenceId": "reference-1", "referenceLineageId": "reference", "provenanceMessageId": "m"}

    monkeypatch.setattr(monitoring_intake, "ReferenceIntake", RecordingIntake)
    table = collected()
    disc = DynamoStore._clean(table.by_prefix("DISC#mradermacher--Lure")[0])
    config = validate_router_config(router_config(rule={"minLikes": 1}))

    mr.deliver_reference(object(), config["publications"][0], disc,
                         {"decisionId": "direct-huggingface-x-000001", "output": "huggingface-direct", "label": "include"}, config)

    assert captured["monitor"].source_name == "Hugging Face Hub" and captured["item"].details["license"] == "apache-2.0"
    assert captured["provenance"]["details"]["baseModels"] == [{"modelId": "Tesslate/Lure-TTS-0.6B", "relation": "quantized"}]
    assert captured["provenance"]["machineDecision"]["rule"] == {"pipelineTags": [], "authors": [], "minLikes": 1}
    note = real_intake._machine_decision_note(captured["provenance"])
    assert "at least 1 likes" in note
    detail = real_intake._details_note(captured["item"])
    assert detail == " Text-to-speech; license apache-2.0; 1 likes; built on Tesslate/Lure-TTS-0.6B."


# --- infrastructure ----------------------------------------------------------------------------------

def test_template_collects_and_routes_the_huggingface_monitor_and_grants_shipped():
    from test_monitoring_cloud import template as _fixture  # noqa: F401
    import yaml
    text = (Path(__file__).resolve().parents[3] / "infra" / "monitoring" / "papyrus-monitoring.yaml").read_text()

    class Loader(yaml.SafeLoader):
        pass
    Loader.add_multi_constructor("!", lambda loader, suffix, node: (suffix, loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode)
                                                                      else loader.construct_sequence(node, deep=True) if isinstance(node, yaml.SequenceNode)
                                                                      else loader.construct_mapping(node, deep=True)))
    template = yaml.load(text, Loader=Loader)["Resources"]
    collect, route_schedule = template["HuggingFaceCollectSchedule"]["Properties"], template["HuggingFaceRouteSchedule"]["Properties"]

    assert collect["Target"]["Input"] == '{"monitorId":"huggingface"}' and route_schedule["Target"]["Input"] == '{"monitorId":"huggingface"}'
    assert collect["ScheduleExpression"] == "rate(6 hours)" and route_schedule["ScheduleExpression"] == "cron(17 * * * ? *)"
    assert "DeadLetterConfig" in collect["Target"] and "DeadLetterConfig" in route_schedule["Target"]
    assert "ShippedApiId" in json.dumps(template["RouterShippedIntakePolicy"]["Properties"]["PolicyDocument"])
