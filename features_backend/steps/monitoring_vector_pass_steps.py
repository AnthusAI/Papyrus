"""The router's daily vector pass (features_backend/monitoring-vector-pass.feature). The index, the embeddings and the backends are fakes."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

import test_monitoring_vectors as tv  # noqa: E402
from test_monitor_stories import world  # noqa: E402

REASON_NO_ARN = "no vectorIndexArn in the publication's monitorStories"


def state(context):
    return context.vector


def reset(context):
    context.vector = SimpleNamespace(policy={}, watermark=tv.Watermark(), rows=[], pass_=tv.Pass(), out_of_time=lambda: False, result=None, line=None, order=[], table=None)
    tv.vectors.s3vectors_client_missing_reason = lambda region_name=None: None


@given('a publication with an index whose watermark is "{watermark}"')
def step_index_with_watermark(context, watermark):
    reset(context)
    state(context).watermark = tv.Watermark(watermark)


@given("a publication with no index recorded")
def step_no_index(context):
    reset(context)
    state(context).policy = {"vectorIndexArn": None}


@given("suggestions are off for the publication")
def step_suggestions_off(context):
    state(context).policy = {**state(context).policy, "suggestions": {"enabled": False}}


@given("the sync embeds {millions:d} million characters")
def step_embeds(context, millions):
    state(context).pass_ = tv.Pass(characters=millions * 1_000_000)


@given("the run is out of time")
def step_out_of_time(context):
    state(context).out_of_time = lambda: True


@given("References accepted at {times}")
def step_references_accepted(context, times):
    stamps = [part.strip().strip('"') for part in times.replace(" and ", ",").split(",") if part.strip()]
    state(context).rows = [tv.accepted(number, stamp) for number, stamp in enumerate(stamps, start=1)]


@when("the vector pass runs")
def step_run_pass(context):
    current = state(context)
    current.result = tv.run_pass(tv.AcceptedClient(current.rows), current.pass_, current.watermark, policy=current.policy, out_of_time=current.out_of_time)


@then("the index is synced for the {count:d} References accepted after the watermark before any suggestion is made")
def step_synced_for(context, count):
    current = state(context)
    assert current.pass_.order[0] == "index" and len(current.pass_.options.reference_ids) == count, (current.pass_.order, current.pass_.options)


@then("suggestions are made for those {count:d} References, the older first")
def step_suggested(context, count):
    current = state(context)
    assert current.pass_.order == ["index", *[f"suggest:{identifier}" for identifier in ("ref-2", "ref-3")][:count]], current.pass_.order


@then('the watermark is now "{value}"')
def step_watermark(context, value):
    assert state(context).watermark.value == value, state(context).watermark.value


@then("the index is synced for the concept cards only")
def step_cards_only(context):
    options = state(context).pass_.options
    assert options.skip_references and options.include_concept_cards and options.reference_ids == (), options


@then("no suggestion is made")
def step_no_suggestion(context):
    assert not [step for step in state(context).pass_.order if step.startswith("suggest")], state(context).pass_.order


@then("nothing is indexed and no suggestion is made")
def step_nothing(context):
    assert state(context).pass_.order == [], state(context).pass_.order


@then("the reason says there is no vectorIndexArn in the publication's monitorStories")
def step_reason_no_arn(context):
    assert state(context).result["suggestionsSkippedReason"] == REASON_NO_ARN, state(context).result


@then("the reason says suggestions are off")
def step_reason_off(context):
    assert state(context).result["suggestionsSkippedReason"] == "suggestions are off in the publication's monitorStories", state(context).result


@then("no watermark is written")
def step_no_watermark(context):
    assert state(context).watermark.writes == [], state(context).watermark.writes


@then("the pass was stopped by {reason}")
def step_stopped_by(context, reason):
    assert state(context).result["stoppedBy"] == reason, state(context).result


@given('a router publication whose entry names an index and a storage bucket')
def step_router_with_index(context):
    reset(context)
    context.vector.policy = {**tv.tms.SINGLE_ITEM_ONLY, "vectorIndexArn": tv.ARN, "storageBucketName": tv.BUCKET}


@given("a router publication whose entry names no index")
def step_router_without_index(context):
    reset(context)
    context.vector.policy = dict(tv.tms.SINGLE_ITEM_ONLY)


@given('2 accepted References that the "hn" monitor delivered, one accepted since the last pass')
def step_router_references(context):
    context.vector.rows = [tv.accepted(1, "2026-10-30T10:00:00Z")]


def run_router_task(context):
    from _pytest.monkeypatch import MonkeyPatch

    from fake_idea_store import FakeIdeaStore
    from test_idea_items import FakeGate

    current = state(context)
    patches = MonkeyPatch()
    try:
        patches.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
        patches.setattr("papyrus_content.ideas.items.ItemStore", lambda client, **options: FakeIdeaStore(client, gate=options.get("gate")))
        patches.setattr("papyrus_content.ideas.gate.HumanusGate.for_client", classmethod(lambda cls, client, **options: FakeGate()))
        table, store = tv.router_with(current.policy)
        _, client = world(2)
        current.table = table
        current.result, current.line, _ = tv.run_task(store, client, current.order, patches, accepted_rows=current.rows)
    finally:
        patches.undo()


@when("the router runs its daily monitor stories with the vector pass")
def step_router_runs_with_pass(context):
    run_router_task(context)


@when("the router runs its daily monitor stories without an index")
def step_router_runs(context):
    from _pytest.monkeypatch import MonkeyPatch

    from fake_idea_store import FakeIdeaStore
    from test_idea_items import FakeGate
    from test_monitor_stories import StoryModel

    current = state(context)
    patches = MonkeyPatch()
    try:
        patches.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
        patches.setattr("papyrus_content.ideas.items.ItemStore", lambda client, **options: FakeIdeaStore(client, gate=options.get("gate")))
        patches.setattr("papyrus_content.ideas.gate.HumanusGate.for_client", classmethod(lambda cls, client, **options: FakeGate()))
        table, store = tv.router_with(current.policy)
        _, client = world(2)
        current.table = table
        current.result, lines = tv.tms.run_task(store, {tv.tms.PUBLICATION: client}, StoryModel())
        current.line = lines[tv.tms.PUBLICATION]
    finally:
        patches.undo()


@then("the steps ran in the order index sync, suggestions, drafting")
def step_order(context):
    assert state(context).order == ["index", "suggest", "drafting"], state(context).order


@then("the log line says {indexed:d} vectors indexed, {cards:d} concept cards written, {suggestions:d} suggestions written and no suggestions reason")
def step_log_counts(context, indexed, cards, suggestions):
    line = state(context).line
    assert (line["indexed"], line["conceptCardsWritten"], line["suggestionsWritten"], line["suggestionsSkippedReason"]) == (indexed, cards, suggestions, None), line


@then("the router's table holds the watermark of the publication")
def step_table_watermark(context):
    row = state(context).table.get_item({"pk": "MONITOR#hn", "sk": tv.vectors.watermark_sort_key(tv.tms.PUBLICATION)})["Item"]
    assert row["watermark"] == "2026-10-30T10:00:00Z", row


@then("2 ideas are drafted")
def step_two_drafted(context):
    assert state(context).line["drafted"] == 2, state(context).line


@then("the log line says {indexed:d} vectors indexed, {cards:d} concept cards written, {suggestions:d} suggestions written and the reason that there is no vectorIndexArn")
def step_log_no_arn(context, indexed, cards, suggestions):
    line = state(context).line
    assert (line["indexed"], line["conceptCardsWritten"], line["suggestionsWritten"]) == (indexed, cards, suggestions), line
    assert line["suggestionsSkippedReason"] == REASON_NO_ARN, line


@given('the example router configuration and the amplify_outputs.json of "{publication}"')
def step_seed_inputs(context, publication):
    import json

    context.seed = SimpleNamespace(
        config=json.loads((REPO_ROOT / "docs" / "monitoring-router-config.example.json").read_text()), publication=publication, outputs=tv.amplify_outputs(), filled=None)


@when("the vector settings are filled from the outputs")
def step_seed_fill(context):
    seed = tv.seed_module()
    context.seed.filled = seed.fill_vector_settings(context.seed.config, {context.seed.publication: context.seed.outputs})
    context.seed.module = seed


@then('the "{publication}" entry carries the index address and the storage bucket from its outputs')
def step_seed_entry(context, publication):
    entry = next(item for item in context.seed.filled["publications"] if item["publicationId"] == publication)
    assert entry["monitorStories"]["vectorIndexArn"] == tv.ARN and entry["monitorStories"]["storageBucketName"] == tv.BUCKET, entry


@then("the other entries are unchanged")
def step_seed_others(context):
    before = {item["publicationId"]: item for item in context.seed.config["publications"]}
    for item in context.seed.filled["publications"]:
        if item["publicationId"] != context.seed.publication:
            assert item == before[item["publicationId"]], item


@then("outputs without an index address are refused")
def step_seed_refused(context):
    try:
        context.seed.module.fill_vector_settings(context.seed.config, {context.seed.publication: {"storage": {"bucket_name": tv.BUCKET}}})
    except ValueError as error:
        assert "s3VectorIndexArn" in str(error)
    else:
        raise AssertionError("outputs without an index were accepted")


@given("the router package modules computed from this repository")
def step_package_modules(context):
    build = tv.load_build()
    context.package = SimpleNamespace(build=build, modules=build.router_modules(), files=build.knowledge_query_files())


@then("they include the vector pass, the suggestions and the calibration")
def step_package_modules_include(context):
    assert {"monitoring_vectors", "reference_suggestions", "suggestion_calibration"} <= set(context.package.modules), context.package.modules


@then("the knowledge-query package files are added to the package without its command line")
def step_package_files(context):
    names = set(context.package.files)
    assert "papyrus_knowledge_query/vector_index.py" in names and "papyrus_knowledge_query/cli.py" not in names, names
