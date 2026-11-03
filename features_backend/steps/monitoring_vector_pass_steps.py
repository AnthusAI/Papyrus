"""The router's daily vector pass (features_backend/monitoring-vector-pass.feature). The index, the embeddings and the backends are fakes."""
from __future__ import annotations

import os
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
    context.vector = SimpleNamespace(policy={}, watermark=tv.Watermark(), rows=[], pending=[], threads=[], pass_=tv.Pass(), out_of_time=lambda: False, result=None, line=None, order=[], table=None)
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


@given('a pending Reference with id "{identifier}" changed at "{stamp}"')
def step_pending_reference(context, identifier, stamp):
    state(context).pending.append({**tv.accepted(0, stamp), "id": identifier, "lineageId": f"lineage-{identifier}", "curationStatus": "pending"})


STAMPS = {1: "2026-10-30T10:00:00Z", 2: "2026-10-30T11:00:00Z", 3: "2026-10-30T12:00:00Z", 4: "2026-10-31T10:00:00Z"}


def position(identifier):
    number = int(identifier.removeprefix("ref-"))
    return f"{STAMPS[number]}#{identifier}"


def actual_position(context, identifier):
    row = next(row for row in state(context).rows if row["id"] == identifier)
    return f"{row['curationStatusUpdatedAt']}#{identifier}"


@given("a publication with an index and no saved place")
def step_no_place(context):
    reset(context)


@given('a publication whose saved place for accepted References runs from "{low}" to "{high}"')
def step_saved_place(context, low, high):
    import json

    reset(context)
    state(context).watermark = tv.Watermark(json.dumps({"v": 2, "done": [], "accepted": {"high": position(high), "low": position(low)}, "pending": {"high": None, "low": None}}))


@given('a Reference "{identifier}" accepted at "{stamp}" has arrived')
def step_arrived(context, identifier, stamp):
    state(context).rows.append(tv.accepted(int(identifier.removeprefix("ref-")), stamp))


@given('an editor voted on "{identifier}"')
def step_voted(context, identifier):
    state(context).rows = [{**row, "curationActorKind": "human"} if row["id"] == identifier else row for row in state(context).rows]


@when('an editor voted on "{identifier}"')
def step_voted_when(context, identifier):
    step_voted(context, identifier)


@given('a conversation is anchored on "{identifier}"')
def step_conversation(context, identifier):
    state(context).threads.append({"id": f"thread-{identifier}", "primaryAnchorKey": f"reference#lineage-{identifier.removeprefix('ref-')}"})


def time_for(context, suggestions):
    ticks = iter([False] * (1 + suggestions))   # one look by the index sync, then one before each suggestion; then the time is gone
    state(context).out_of_time = lambda: next(ticks, True)


@given("the time lasts for the index sync and {count:d} suggestion")
def step_time_one(context, count):
    time_for(context, count)


@given("the time lasts for the index sync and {count:d} suggestions")
def step_time_many(context, count):
    time_for(context, count)


@when("the vector pass runs")
def step_run_pass(context):
    current = state(context)
    if current.pass_.order:
        current.pass_ = tv.Pass()   # a second pass of the same scenario starts a fresh record of its steps
    current.result = tv.run_pass(tv.AcceptedClient(current.rows, current.pending, current.threads), current.pass_, current.watermark, policy=current.policy, out_of_time=current.out_of_time)


@then("the index is synced for the {count:d} References accepted after the watermark before any suggestion is made")
def step_synced_for(context, count):
    current = state(context)
    assert current.pass_.order[0] == "index" and len(current.pass_.options.reference_ids) == count, (current.pass_.order, current.pass_.options)


@then("suggestions are made for those {count:d} References, the older first")
def step_suggested(context, count):
    current = state(context)
    assert current.pass_.order == ["index", *[f"suggest:{identifier}" for identifier in ("ref-2", "ref-3")][:count]], current.pass_.order


@then("suggestions are made for {identifiers} only")
def step_suggested_only(context, identifiers):
    import re

    wanted = re.findall(r'"([^"]+)"', identifiers)
    assert state(context).pass_.order == ["index", *[f"suggest:{identifier}" for identifier in wanted]], state(context).pass_.order


@then('suggestions are made in the order {identifiers}')
def step_suggested_order(context, identifiers):
    import re

    wanted = re.findall(r'"([^"]+)"', identifiers)
    assert state(context).pass_.order == ["index", *[f"suggest:{identifier}" for identifier in wanted]], state(context).pass_.order


@then("{count:d} suggestions are left")
def step_left_many(context, count):
    assert state(context).result["suggestionsRemaining"] == count, state(context).result


@then("{count:d} suggestion is left")
def step_left_one(context, count):
    assert state(context).result["suggestionsRemaining"] == count, state(context).result


@then("no suggestions are left")
def step_left_none(context):
    assert state(context).result["suggestionsRemaining"] == 0, state(context).result


@then('the saved place for accepted References runs from "{low}" to "{high}"')
def step_place(context, low, high):
    import json

    place = json.loads(state(context).watermark.value)["accepted"]
    assert (place["low"], place["high"]) == (actual_position(context, low), actual_position(context, high)), place


@then('the saved place for accepted References runs from nothing older to "{high}"')
def step_place_new(context, high):
    import json

    place = json.loads(state(context).watermark.value)["accepted"]
    assert place["high"] == actual_position(context, high) and place["low"] == "", place


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


@given("the vector pass's share of the time is already spent")
def step_share_spent(context):
    state(context).drafter_options = {"vector_out_of_time": lambda: True}


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
        current.result, current.line, _ = tv.run_task(store, client, current.order, patches, accepted_rows=current.rows, drafter_options=getattr(current, 'drafter_options', None))
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


@then("the steps ran in the order index sync, drafting, index sync, suggestions")
def step_order_after(context):
    assert state(context).order == ["index", "drafting", "index", "suggest"], state(context).order


@then("the log line says {count:d} suggestions written and no suggestions left")
def step_log_written_none_left(context, count):
    line = state(context).line
    assert line["suggestionsWritten"] == count and not line.get("suggestionsRemaining"), line


@then("the log line shows no raised curation flag")
def step_no_flag_line(context):
    assert state(context).line["curationFlag"] != "raised", state(context).line


@given("the router has {seconds:d} seconds left when a publication starts")
def step_budget_given(context, seconds):
    reset(context)
    state(context).seconds = seconds


@when("the router runs its daily monitor stories with a fake drafter")
def step_budget_run(context):
    from _pytest.monkeypatch import MonkeyPatch

    from test_monitor_stories import StoryModel

    current = state(context)
    remaining = [current.seconds]
    seen = {}

    def drafter(client, publication, **options):
        seen.update(options)
        return {"publicationId": publication["publicationId"], "status": "complete", "stoppedBy": None, "drafted": 0}

    patches = MonkeyPatch()
    try:
        patches.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
        _, store = tv.router_with(dict(tv.tms.SINGLE_ITEM_ONLY))
        _, client = world(1)
        endpoints = {tv.tr.ENDPOINT.replace("abc123", "api0"): client}
        tv.run_router(store, "hn", now=tv.NOW.timestamp(), task="monitor-stories", appsync=lambda endpoint: endpoints[endpoint], deliver=tv.tr.Delivery(),
                      time_left=lambda: remaining[0], story_transport=StoryModel(), story_drafter=drafter)
    finally:
        patches.undo()
    current.seen, current.remaining = seen, remaining
    current.checks = lambda left: (remaining.__setitem__(0, left), seen["out_of_time"](), seen["vector_out_of_time"]())[1:]


@then("drafting is out of time at {drafting:d} seconds left and the vector pass at {vectors:d} seconds left")
def step_budget_then(context, drafting, vectors):
    check = state(context).checks
    assert check(vectors + 1) == (False, False)   # plenty of time: neither is over
    assert check(vectors - 1) == (False, True)   # between the two limits only the vector pass is over: the drafting still has its half
    assert check(drafting - 1) == (True, True)   # below the drafting limit both are over


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
    import json

    assert json.loads(row["watermark"])["accepted"]["high"] == "2026-10-30T10:00:00Z#ref-1", row


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


@given("a batch of texts to embed with one empty text, one whitespace-only text and one longer than the input limit")
def step_embed_batch(context):
    from papyrus_knowledge_query import vector_index

    context.embed = SimpleNamespace(candidates=[{"key": "a", "text": "hello", "metadata": {}}, {"key": "b", "text": ""}, {"key": "c", "text": "  \n"},
                                                {"key": "d", "text": "x" * (vector_index.EMBEDDING_MAX_INPUT_BYTES + 500), "metadata": {}}],
                                    sent=[], stats={"vectorsWritten": 0, "embeddingRequests": 0, "embeddingInputCharacters": 0})


@when("the batch is embedded")
def step_embed(context):
    import json
    from unittest import mock

    import test_vector_index_embed as te
    from papyrus_knowledge_query import vector_index

    held = context.embed
    os.environ["OPENAI_API_KEY"] = "sk-secret"
    with mock.patch("urllib.request.urlopen", te.ok_urlopen(held.sent)), mock.patch.object(vector_index, "_put_vectors", lambda arn, vectors: None):
        vector_index._write_pending_vectors(held.stats, "arn", held.candidates)
    del json


@then("the empty and whitespace-only texts are dropped and counted")
def step_dropped(context):
    held = context.embed
    assert held.stats["embeddingInputsEmpty"] == 2 and len(held.sent[0]) == 2


@then("the long text is cut to a safe length and counted")
def step_cut(context):
    from papyrus_knowledge_query import vector_index

    held = context.embed
    assert held.stats["embeddingInputsTruncated"] == 1 and len(held.sent[0][1].encode()) <= vector_index.EMBEDDING_MAX_INPUT_BYTES


@then("a request the endpoint refuses with 400 fails with the endpoint's own message and never the key")
def step_refused(context):
    import io
    import json
    import urllib.error
    from unittest import mock

    from papyrus_knowledge_query import vector_index

    body = json.dumps({"error": {"message": "input is invalid"}}).encode()

    def urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(body))
    with mock.patch("urllib.request.urlopen", urlopen):
        try:
            vector_index._embed(["hello"])
        except RuntimeError as error:
            assert "HTTP 400" in str(error) and "input is invalid" in str(error) and "sk-secret" not in str(error)
        else:
            raise AssertionError("no error")


# --- concepts: authors and the graph's own bookkeeping are not concepts ------------------------------------------------------------------------


CONCEPT_NODES = [
    ("voice cloning", "task", "task--voice-cloning"), ("pitch", "concept", "concept--pitch"), ("Ada Lovelace", "personAuthor", "author.name.adalovelace"),
    ("Coverage: AI", "coverageQuestion", "coverage.ai"), ("General comment", "commentConcept", "comment.general"),
    ("4 star", "qualityRating", "quality.rating.4_star"), ("Include", "relevanceDecision", "relevance.include"),
]


@given("a site whose graph has the concepts \"voice cloning\" (task) and \"pitch\" (concept), an author, a coverage question, a comment concept, a quality rating and a relevance decision")
def step_concept_graph(context):
    nodes = [{"id": f"node-{number}-v1", "lineageId": f"node-{number}", "versionState": "current", "status": "accepted", "displayName": name, "nodeKind": kind, "nodeKey": key}
             for number, (name, kind, key) in enumerate(CONCEPT_NODES)]

    class Graph:
        def graphql(self, query, variables):
            return {"listSemanticNodes": {"items": nodes, "nextToken": None}}

    context.concepts = SimpleNamespace(graph=Graph(), cards=None)


@when("the concept cards are prepared")
def step_prepare_cards(context):
    from papyrus_knowledge_query import vector_index

    context.concepts.cards = vector_index._prepare_concept_card_vectors(context.concepts.graph)


@then('only "voice cloning" and "pitch" have a card')
def step_only_real_cards(context):
    from papyrus_knowledge_query.concept_kinds import is_concept  # noqa: F401

    names = sorted(card["metadata"]["nodeKey"] for card in context.concepts.cards)
    assert names == ["concept--pitch", "task--voice-cloning"], names


@then("a card for an author that was written earlier is not offered as a suggested concept")
def step_old_author_card(context):
    from papyrus_content.reference_suggestions import suggest_for
    from test_reference_suggestions import FakeVectorProvider, build

    client, provider = build()
    provider.entries["concept_card-node-author"] = {"vector": provider.entries["concept_card-node-voice"]["vector"],
                                                    "metadata": {"vectorKind": "concept_card", "lineageId": "node-author", "nodeKind": "personAuthor", "nodeKey": "author.name.adalovelace"}}
    client.tables.setdefault("SemanticNode", {})["node-voice"] = {"id": "node-voice-v1", "lineageId": "node-voice", "versionNumber": 1}
    result = suggest_for(client, provider, "reference-a-v1", corpus_id="corpus-1", now="2026-11-01T12:00:00Z")
    offered = [entry["lineageId"] for entry in result["concepts"]]
    assert "node-author" not in offered, offered
