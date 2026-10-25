from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_huggingface as th  # noqa: E402
from papyrus_content import monitoring_huggingface as hf  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, _validate_config  # noqa: E402

DAY = 86400
LURE = "DISC#mradermacher--Lure-TTS-0_6B-GGUF-"


def collect(context, offset=0, hub=None):
    context.result = th.run(context.table_, hub or context.hub, now=th.NOW + offset)


@given("a Hugging Face monitor for text-to-speech models that need at least {likes:d} like")
def step_monitor(context, likes):
    context.table_ = th.FakeTable()
    context.table_.put_item({**th.CONFIG, "minLikes": likes})
    context.hub = th.tts_hub()


@given("a Hugging Face monitor for text-to-speech models that need no minimum")
def step_monitor_open(context):
    context.table_ = th.FakeTable()
    context.table_.put_item({**th.CONFIG, "minLikes": 0, "authors": []})
    context.hub = th.tts_hub()


@given("the Hub lists twelve new text-to-speech models and one of them has a like")
def step_tts(context):
    assert len(th.TTS) == 12 and sum(1 for row in th.TTS if row["likes"]) == 1


@given("a Hugging Face monitor that watches the organisation nvidia for robotics models")
def step_nvidia_monitor(context):
    context.table_ = th.FakeTable()
    context.table_.put_item({**th.CONFIG, "authors": ["nvidia"], "pipelineTags": ["robotics"], "minLikes": 100})
    context.hub = th.Hub({"author:nvidia:createdAt": th.NVIDIA, "pipeline_tag:robotics:createdAt": []})


@given("the Hub lists three new nvidia models, two of them robotics")
def step_nvidia(context):
    assert [row.get("pipeline_tag") for row in th.NVIDIA] == [None, "robotics", "robotics"]


@given("the Hugging Face monitor has collected")
def step_collected(context):
    collect(context)


@when("the Hugging Face monitor collects")
def step_collect(context):
    collect(context, offset=DAY if context.table_.by_prefix("RUN#") else 0)


@when("the Hugging Face monitor collects a day later and only that model's likes have changed")
def step_likes(context):
    rows = deepcopy(th.TTS)
    next(r for r in rows if r["likes"])["likes"] = 40
    collect(context, DAY, th.tts_hub(**{"pipeline_tag:text-to-speech:createdAt": rows}))


@when("the Hugging Face monitor collects another day later and the model has a new commit")
def step_commit(context):
    rows = deepcopy(th.TTS)
    next(r for r in rows if r["likes"])["sha"] = "f" * 40
    collect(context, 2 * DAY, th.tts_hub(**{"pipeline_tag:text-to-speech:createdAt": rows}))


@then("one discovery is recorded, for the model that has the like")
def step_one(context):
    rows = context.table_.by_prefix("DISC#")
    assert context.result["new"] == 1 and len(rows) == 1 and rows[0]["details"]["modelId"] == "mradermacher/Lure-TTS-0.6B-GGUF"


@then("that discovery carries the model id, author, release date, pipeline tag, license, tags, library, likes, downloads and canonical URL")
def step_fields(context):
    disc = context.table_.by_prefix(LURE)[0]
    details = disc["details"]
    for key in ("modelId", "author", "createdAt", "pipelineTag", "license", "tags", "libraryName", "likes", "downloads", "lastModified", "sha"):
        assert details.get(key) not in (None, [], ""), key
    assert details["license"] == "apache-2.0" and details["pipelineTag"] == "text-to-speech" and details["libraryName"] == "transformers"
    assert disc["canonicalUrl"] == "https://huggingface.co/mradermacher/Lure-TTS-0.6B-GGUF"
    assert disc["sourcePublishedAt"] == details["createdAt"]


@then("that discovery waits for the router and records that it came from Hugging Face")
def step_waits(context):
    disc = context.table_.by_prefix(LURE)[0]
    assert disc["routing"] == "collected" and disc["sourceType"] == "huggingface-models"


@then("both robotics models are collected although neither has a like")
def step_both(context):
    rows = context.table_.by_prefix("DISC#")
    assert context.result["new"] == 2 and {r["details"]["pipelineTag"] for r in rows} == {"robotics"}
    assert all(r["details"]["likes"] < 100 for r in rows)


@then("the model with no pipeline tag is left out")
def step_left_out(context):
    assert not any(r["details"]["modelId"] == "nvidia/InternVideo2-CLIP-anomaly-detection" for r in context.table_.by_prefix("DISC#"))


@then("the model is reported unchanged and has one discovery")
def step_unchanged(context):
    assert context.result["unchanged"] == 1 and context.result["revised"] == 0 and len(context.table_.by_prefix(LURE)) == 1


@then("the model has a second discovery revision that carries the new commit")
def step_second(context):
    rows = context.table_.by_prefix(LURE)
    assert context.result["revised"] == 1 and [r["revision"] for r in rows] == [1, 2] and rows[1]["details"]["sha"] == "f" * 40


# --- backfill ---

@given("a Hugging Face monitor for text-generation models that need at least {likes:d} likes")
def step_backfill_monitor(context, likes):
    context.table_ = th.backfill_config(minLikes=likes)
    context.hub = th.liked_hub()
    context.lines = []


@given("the Hub lists the most-liked text-generation models")
def step_liked(context):
    assert [r["likes"] for r in th.LIKED] == sorted((r["likes"] for r in th.LIKED), reverse=True)


def run_backfill(context, since, **kwargs):
    context.backfill, context.lines = th.backfill(context.table_, kwargs.pop("hub", context.hub), since=since, apply=True, **kwargs)


@when("the operator backfills models created since the middle of 2024")
def step_backfill(context):
    run_backfill(context, "2024-06-01T00:00:00Z")


@then("the two models inside the window are loaded and the third is not")
def step_window(context):
    assert sorted(r["details"]["modelId"] for r in context.table_.by_prefix("DISC#")) == [
        "deepseek-ai/DeepSeek-R1", "meta-llama/Llama-3.1-8B-Instruct"]


@when("the operator backfills the same window again")
def step_again(context):
    context.before = len(context.table_.by_prefix("DISC#"))
    hub = th.liked_hub()
    run_backfill(context, "2024-06-01T00:00:00Z", hub=hub)
    context.again_requests = len(hub.requests)


@then("nothing is read or written twice")
def step_idempotent(context):
    assert context.again_requests == 0 and len(context.table_.by_prefix("DISC#")) == context.before == 2


@when("the operator backfills with room for only one Hub request")
def step_one_request(context):
    run_backfill(context, "2024-06-01T00:00:00Z", max_requests=1)


@then("the backfill reports that it paused and stored a checkpoint")
def step_paused(context):
    assert context.backfill["status"] == "paused" and context.table_.by_prefix("BACKFILL#")
    assert any("run the same command again" in line for line in context.lines)


@when("the operator backfills the same window again with room to finish")
def step_resume(context):
    context.resume_hub = th.liked_hub()
    run_backfill(context, "2024-06-01T00:00:00Z", hub=context.resume_hub)


@then("the backfill continues from the stored cursor and completes with all models loaded once")
def step_resumed(context):
    assert context.backfill["status"] == "complete" and context.resume_hub.requests[0].endswith("cursor=2")
    assert len(context.table_.by_prefix("DISC#")) == 2


# --- relations ---

@then("a quantized model lists its base model with the relation quantized")
def step_quantized(context):
    disc = context.table_.by_prefix(LURE)[0]
    assert disc["details"]["baseModels"] == [{"modelId": "Tesslate/Lure-TTS-0.6B", "relation": "quantized"}]


@then("a fine-tuned model lists its base model with the relation finetune")
def step_finetune(context):
    disc = context.table_.by_prefix("DISC#anyantudre--moore-tts-kokoro#")[0]
    assert disc["details"]["baseModels"] == [{"modelId": "hexgrad/Kokoro-82M", "relation": "finetune"}]


@then("a model that declares no base lists none")
def step_none(context):
    assert context.table_.by_prefix("DISC#pythainlp--MakHamTTS#")[0]["details"]["baseModels"] == []


# --- routing ---

@given("the router for Shipped delivers by the monitor's rule that a model needs at least {likes:d} like")
def step_router(context, likes):
    context.table_.put_item(th.router_config(rule={"minLikes": likes}))
    context.delivery = th.Delivery()


@when("the router runs")
def step_router_runs(context):
    context.router_result = th.route(context.table_, context.delivery)


@then("the liked model is delivered to Shipped as a pending Reference candidate")
def step_delivered(context):
    assert len(context.delivery.calls) == 1 and context.delivery.calls[0][0] == "shipped"
    assert context.delivery.calls[0][1].startswith("mradermacher--Lure-TTS-0_6B-GGUF-")
    assert context.router_result["counts"]["delivered"] == 1


@then("the other eleven models are finished without delivery and say that the rule excluded them")
def step_excluded(context):
    finals = [row["final"] for row in context.table_.by_prefix("ROUTE#") if row.get("final")]
    assert len(finals) == 11 and {f["reason"] for f in finals} == {"excluded by the monitor's rule"}


@given("the monitor excludes the tags gguf and mlx and the id pattern omnivoice")
def step_exclusions(context):
    config = context.table_.get_item(Key={"pk": "MONITOR#huggingface", "sk": "CONFIG"})["Item"]
    context.table_.put_item({**config, "excludeTags": ["gguf", "mlx"], "excludeIdPatterns": ["omnivoice"]})


@then("the five repackaged and two renamed copies are not stored as discoveries")
def step_not_stored(context):
    stored = [row["details"]["modelId"] for row in context.table_.by_prefix("DISC#")]
    assert not any("GGUF" in m or "MLX" in m.upper() or "omnivoice" in m for m in stored)


@then("the run receipt counts five skipped by tag and two by id pattern")
def step_skip_counts(context):
    assert context.result["read"]["skipped"] == {"tag": 5, "idPattern": 2}


@then("the five other models are collected")
def step_five(context):
    assert context.result["new"] == 5 and len(context.table_.by_prefix("DISC#")) == 5


@given("the router for Shipped excludes the tags gguf and mlx")
def step_router_excludes(context):
    context.table_.put_item(th.router_config(rule={"excludeTags": ["gguf", "mlx"]}))
    context.delivery = th.Delivery()


@then("the seven other models are delivered and the five repackaged ones are finished without delivery")
def step_seven(context):
    assert context.router_result["counts"]["delivered"] == 7
    finals = [row["final"] for row in context.table_.by_prefix("ROUTE#") if row.get("final")]
    assert len(finals) == 5 and {f["reason"] for f in finals} == {"excluded by the monitor's rule"}


@then("a second router run finds nothing waiting")
def step_nothing(context):
    assert th.route(context.table_, context.delivery, now=th.NOW + 7200)["counts"]["examined"] == 0


# --- addresses ---

@then("a monitor source address on another host is refused")
def step_host(context):
    try:
        _validate_config({**th.CONFIG, "sourceUrl": "https://example.org/api/models"})
    except ValueError as error:
        assert "huggingface.co" in str(error)
    else:
        raise AssertionError("an address on another host was accepted")


@then("a next-page cursor that leaves huggingface.co is refused")
def step_cursor(context):
    try:
        hf.check_hub_url("https://evil.example/api/models?cursor=1")
    except ValueError:
        return
    raise AssertionError("a cursor on another host was accepted")
