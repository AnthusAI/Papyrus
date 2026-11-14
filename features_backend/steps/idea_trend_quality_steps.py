"""Cited Trends picks news, not volume: signal selection and the published trending order (features_backend/idea-trend-quality.feature)."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from ideas_fixtures import FakeTrendModel, selection_snapshot  # noqa: E402
from papyrus_content.ideas import trends  # noqa: E402
from papyrus_content.knowledge_snapshot import builder_test  # noqa: E402
from papyrus_content.knowledge_snapshot.builder import INDEX_FILE, build_files  # noqa: E402
from papyrus_content.knowledge_snapshot.trends import TrendConfig  # noqa: E402

KEYS = {"MIT": "licence--mit", "text-generation": "task--text-generation", "Hugging Face": "platform--hugging-face", "NVIDIA": "maker--nvidia", "emonHasan01": "maker--emonhasan01"}


def selection(context) -> dict:
    return trends.select_entities(context.quality_snapshot, getattr(context, "trend_config", None))


@given("the knowledge snapshot of a week in which a licence, a task and a platform carry the biggest counts")
def step_week(context):
    context.quality_snapshot = selection_snapshot()
    context.trend_snapshot = context.quality_snapshot
    context.trend_config = None


@given("NVIDIA released four models with {likes:d} likes between them")
def step_nvidia(context, likes):
    assert likes == 640  # four models of 160 likes each, in the fixture


@given("an individual account released five small models with {likes:d} likes between them")
def step_individual(context, likes):
    assert likes == 30  # five models of 6 likes each, in the fixture


@given("the individual's three models have {downloads:d} downloads each and {likes:d} likes between them")
def step_downloads(context, downloads, likes):
    rows = [
        {"title": f"emonHasan01/m{n}", "url": "https://huggingface.co/x", "publishedAt": "2026-10-14T08:00:00Z", "summary": f"m is a model. {n} likes, {downloads} downloads."}
        for n in range(3)
    ]
    assert sum(range(3)) == likes  # 0 + 1 + 2 likes
    context.quality_snapshot = selection_snapshot({"maker--emonhasan01": {"relatedItems": [], "relatedRecords": rows}})


@given('the maker "{name}" is on the watchlist')
def step_watchlist(context, name):
    context.trend_config = TrendConfig(watchlist=frozenset({name.lower()}))


@given("the operator lowers the likes threshold to {likes:d}")
def step_threshold(context, likes):
    context.trend_config = TrendConfig.from_mapping({"minimum_likes": likes, "minimum_downloads": 1000})


@when("the operator reads which entities become signals")
def step_read_selection(context):
    context.quality_selection = selection(context)


@then('the licence "MIT", the task "text-generation" and the platform "Hugging Face" are not anchors')
def step_not_anchors(context):
    anchors = {row["key"] for row in context.quality_selection["anchors"]}
    assert not anchors & {KEYS["MIT"], KEYS["text-generation"], KEYS["Hugging Face"]}, anchors


@then('"{name}" is an anchor, notable for {models:d} models and {likes:d} likes')
def step_anchor_for_numbers(context, name, models, likes):
    row = next(row for row in context.quality_selection["anchors"] if row["key"] == KEYS[name])
    assert row["notability"].startswith(f"{models} model(s), {likes} likes"), row


@then('"{name}" is an anchor, notable because it is watchlisted')
def step_anchor_watchlisted(context, name):
    row = next(row for row in context.quality_selection["anchors"] if row["key"] == KEYS[name])
    assert row["notability"] == "watchlisted", row


@then('"{name}" is an anchor')
def step_anchor(context, name):
    assert KEYS[name] in {row["key"] for row in context.quality_selection["anchors"]}


@then('"{name}" is not an anchor')
def step_not_anchor(context, name):
    assert KEYS[name] not in {row["key"] for row in context.quality_selection["anchors"]}


@then('the run record lists "{name}" as passed over because the maker is below the notability bar, with {models:d} models and {likes:d} likes')
def step_passed_over(context, name, models, likes):
    model = FakeTrendModel([])
    run = trends.draft_trends(
        snapshot={**context.quality_snapshot, "source": "test"}, site="shipped", context={"sections": [{"title": "Analysis"}], "stories": []},
        json_store=None, transport=model, dry_run=True, config=context.trend_config,
    )
    [row] = [row for row in run["selection"]["excluded"] if row["key"] == KEYS[name]]
    assert "below the notability bar" in row["reason"] and f"{models} model(s), {likes} likes" in row["reason"], row


@then('the task "text-generation" and the licence "MIT" are signals with the role context')
def step_context_roles(context):
    roles = {signal["targetId"]: signal["role"] for signal in context.trend_signals}
    assert roles[KEYS["text-generation"]] == "context" and roles[KEYS["MIT"]] == "context", roles


@then("the model sees them marked as context")
def step_model_sees_context(context):
    view = trends.build_input(context.trend_snapshot, context.trend_signals, {"sections": [{"title": "Analysis"}], "stories": []}, 3)["signals"]
    assert {entry["name"] for entry in view if entry.get("role") == "context"} == {"text-generation", "MIT"}


@then("the prompt forbids a headline about a context signal")
def step_prompt(context):
    assert '"role": "context"' in trends.SYSTEM_PROMPT and "never make it the subject of the headline" in trends.SYSTEM_PROMPT


@given("a snapshot build in which a licence and a task rose with the corpus while a maker gained share")
def step_build(context):
    context.quality_data = builder_test._corpus(
        {"mit": ("licence", 60, 40), "text generation": ("task", 80, 55), "nvidia": ("maker", 6, 1), "steady": ("maker", 9, 8)}
    )


@when("the snapshot is built")
def step_built(context):
    context.quality_index = build_files(context.quality_data, builder_test.OPTIONS)[INDEX_FILE]


@then("the trending list holds the maker and neither the licence nor the task")
def step_trending(context):
    assert context.quality_index["trending"] == ["maker--nvidia"], context.quality_index["trending"]
