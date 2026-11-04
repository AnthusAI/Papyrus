"""The router's daily vector pass (features_backend/monitoring-vector-pass.feature). The index, the embeddings and the backends are fakes; the call counts are real."""
from __future__ import annotations

import json
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

REASON_NO_ARN = "no vectorIndexArn in the publication's monitorStories"


def sites(context):
    if not hasattr(context, "sites"):
        context.sites = []
        context.policy = {}
        context.results = []
    return context.sites


def up_to_date(size):
    site = tv.Site([tv.row(n, n) for n in range(1, size + 1)], place=tv.quiet_place(size))
    site.fill_index()
    return site


@given("a site of {size:d} References that are all indexed, with the pass up to date")
def step_up_to_date(context, size):
    sites(context).append(up_to_date(size))


@given("{count:d} References on each were voted on or starred")
def step_voted_each(context, count):
    for site in context.sites:
        size = len(site.feed.references)
        for n in (3, 5, 7)[:count]:
            site.feed.references[f"ref-{n}"]["updatedAt"] = tv.stamp(size + n)


@given("{count:d} new References have arrived")
def step_new(context, count):
    site = context.sites[0]
    size = len(site.feed.references)
    for n in range(size + 1, size + count + 1):
        site.feed.references[f"ref-{n}"] = tv.row(n, n)
    context.new_lineages = [f"lineage-{n}" for n in range(size + 1, size + count + 1)]


@given("an editor starred a Reference")
def step_starred(context):
    context.sites[0].feed.references["ref-1"].update(updatedAt=tv.stamp(10), starRating=5)


@when("the vector pass runs")
def step_run(context):
    sites(context)
    site = context.sites[0]
    options = {"policy": context.policy}
    if getattr(context, "out_of_time", None):
        options["out_of_time"] = context.out_of_time
    if site.watermark.value is None:
        context.full_calls = []

        def full(services, config):
            context.full_calls.append({"explanations": config.include_link_explanations, "notes": config.include_notes, "skip_indexed": config.skip_indexed})
            site.feed.references["ref-9"] = tv.row(9, 50)   # changed while the sync ran: after the saved place
            return {"vectorsWritten": 3, "conceptCardsToWrite": 0, "embeddingInputCharacters": 0}

        options["full_indexer"] = full
    context.result = site.run(**options)


@when("the vector pass runs on both")
def step_run_both(context):
    context.results = [site.run() for site in context.sites]


@then("the pass made {count:d} requests to the API, none to the vector index and none for text")
def step_quiet_calls(context, count):
    site = context.sites[0]
    assert site.graphql_calls() == count and site.vector_calls() == 0 and site.corpus.reads == 0, (site.graphql_calls(), site.index.calls)


@then("the pass reports {count:d} changed References")
def step_changed(context, count):
    assert context.result["changedReferences"] == count, context.result


@then("no saved place is written")
def step_no_place(context):
    assert context.sites[0].watermark.writes == []


@then("each pass made {count:d} requests to the API: 2 reads of the change feeds and 3 reads of attachments")
def step_each_calls(context, count):
    assert [site.graphql_calls() for site in context.sites] == [count, count], [site.graphql_calls() for site in context.sites]


@then("each pass made the same number of requests to the vector index and embedded nothing")
def step_each_vectors(context):
    assert context.sites[0].vector_calls() == context.sites[1].vector_calls() and all(site.index.embedded == [] for site in context.sites)


@then("the {count:d} new References have a summary vector and each was announced once")
def step_new_announced(context, count):
    site = context.sites[0]
    announced = sorted(entry["referenceLineageId"] for entry in site.heard)
    assert announced == sorted(context.new_lineages), announced
    from papyrus_knowledge_query import vector_index

    assert all(vector_index.reference_summary_vector_key(lineage) in site.index.stored for lineage in context.new_lineages)


@then("nothing is announced again")
def step_not_again(context):
    assert len(context.sites[0].heard) == len(context.new_lineages)


@then("nothing was embedded and nothing was announced")
def step_nothing(context):
    assert context.sites[0].index.embedded == [] and context.sites[0].heard == []


@given("a pending Reference that is indexed")
def step_pending_indexed(context):
    site = tv.Site([tv.row(1, 1, "pending")], place=tv.saved_place(1))
    site.fill_index()
    from papyrus_knowledge_query import vector_index

    context.key = vector_index.reference_summary_vector_key("lineage-1")
    context.data = site.index.stored[context.key]["data"]
    sites(context).append(site)


@given("an editor accepted it")
def step_accepted(context):
    context.sites[0].feed.references["ref-1"].update(**tv.row(1, 5, "accepted"))


@then("its summary vector is marked accepted with the same vector data, its passages are written and nothing was announced")
def step_marked(context):
    site = context.sites[0]
    assert site.index.stored[context.key]["metadata"]["curationStatus"] == "accepted" and site.index.stored[context.key]["data"] == context.data
    assert any(v["metadata"].get("vectorKind") == "reference_passage" for v in site.index.stored.values()) and site.heard == []


@given("an accepted Reference that is indexed and another that is not rejected")
def step_two(context):
    site = tv.Site([tv.row(1, 1), tv.row(2, 2)], place=tv.saved_place(2))
    site.fill_index()
    sites(context).append(site)


@given("an editor rejected the first")
def step_rejected(context):
    context.sites[0].feed.references["ref-1"].update(**tv.row(1, 5, "rejected"))


@then("the first has no vector, the other keeps its vectors and the index was not listed")
def step_deleted(context):
    site = context.sites[0]
    owners = {v["metadata"].get("referenceLineageId") for v in site.index.stored.values()}
    assert owners == {"lineage-2"} and site.index.count("list_vectors") == 0


@given("a pending Reference whose summary vector was made from its summary alone")
def step_summary_only(context):
    site = tv.Site([tv.row(1, 1, "pending")], place=tv.saved_place(1))
    context.texts = {"value": "First summary of the piece, long enough to be a summary of the piece on its own."}

    def attachments(reference):
        site.graph.attachment_reads += 1
        return [{"role": "curation", "metadata": json.dumps({"summary": {"text": context.texts["value"]}})}]

    site.graph.list_reference_attachments = attachments
    sites(context).append(site)


@when("the summary is rewritten and the vector pass runs")
def step_rewritten(context):
    context.texts["value"] = "A different summary of the piece, written later and also long enough to stand as a summary."
    context.sites[0].feed.references["ref-1"]["updatedAt"] = tv.stamp(9)
    context.sites[0].run()


@then("the Reference was announced twice with two different hashes")
def step_twice(context):
    heard = context.sites[0].heard
    assert len(heard) == 2 and heard[0]["contentHash"] != heard[1]["contentHash"] and {e["referenceLineageId"] for e in heard} == {"lineage-1"}, heard


@given("a site with {count:d} References and no saved place")
def step_no_place_site(context, count):
    sites(context).append(tv.Site([tv.row(n, n) for n in range(1, count + 1)], place=None))


@then("the full sync ran once with link explanations and notes left out")
def step_full_sync(context):
    assert context.full_calls == [{"explanations": False, "notes": False, "skip_indexed": True}], context.full_calls


@then("the saved place is the newest change read before the sync began")
def step_place_before(context):
    assert json.loads(context.sites[0].watermark.value)["since"] == tv.stamp(3)


@given("a site with {count:d} References changed since the saved place, read 2 to a page")
def step_paged(context, count):
    from papyrus_content import monitoring_vectors

    monitoring_vectors.PAGE_SIZE = 2
    context.clock = {"pages": 0}
    original = monitoring_vectors.read_changed_page

    def counting(*arguments):
        context.clock["pages"] += 1
        return original(*arguments)

    monitoring_vectors.read_changed_page = counting
    context.restore = lambda: (setattr(monitoring_vectors, "PAGE_SIZE", 1000), setattr(monitoring_vectors, "read_changed_page", original))
    sites(context).append(tv.Site([tv.row(n, n) for n in range(1, count + 1)], place=tv.saved_place(0), page_size=2))


@given("the time runs out while the second page is being indexed")
def step_time(context):
    context.out_of_time = lambda: context.clock["pages"] >= 2


@when("the vector pass runs with time to spare")
def step_spare(context):
    context.clock["pages"] = -99
    context.result = context.sites[0].run()
    context.restore()


@then("the saved place is the end of the first page")
def step_first_page(context):
    assert json.loads(context.sites[0].watermark.value)["since"] == tv.stamp(2) and context.result["stoppedBy"] == "time"


@then("the saved place is the newest change and every Reference was announced")
def step_newest(context):
    site = context.sites[0]
    assert json.loads(site.watermark.value)["since"] == tv.stamp(7)
    assert sorted({e["referenceLineageId"] for e in site.heard}) == [f"lineage-{n}" for n in range(1, 8)]


@given("a site with {count:d} Reference and a saved place")
def step_one_site(context, count):
    sites(context).append(tv.Site([tv.row(n, n) for n in range(1, count + 1)], place=tv.saved_place(0)))


@given("the publication has no vector index recorded")
def step_no_index(context):
    context.policy = {"vectorIndexArn": None}


@given("suggestions are off for the publication")
def step_off(context):
    context.policy = {"suggestions": {"enabled": False}}


@then("the reason says there is no vectorIndexArn in the publication's monitorStories")
def step_no_arn(context):
    assert context.result["indexSkippedReason"] == REASON_NO_ARN, context.result


@then("the pass made {count:d} requests to the API")
def step_requests(context, count):
    assert context.sites[0].graphql_calls() == count


@then("the Reference is indexed, nothing is announced and the reason says suggestions are off")
def step_indexed_off(context):
    assert context.result["indexed"] >= 1 and context.sites[0].heard == [] and "off" in context.result["suggestionsSkippedReason"], context.result


@then("the vector pass module has no plan, no owed memory, no suggestion step and no backlog task")
def step_no_plan(context):
    from papyrus_content import monitoring_router, monitoring_vectors

    for name in ("plan_since", "OwedMemory", "_Suggesting", "run_suggest_backlog", "parse_watermark"):
        assert not hasattr(monitoring_vectors, name), name
    assert "suggest-backlog" not in monitoring_router.FAN_OUT_TASKS


@then("the monitoring template has no suggest-backlog schedule")
def step_no_schedule(context):
    text = tv.template_text()
    assert "suggest-backlog" not in text and "SuggestBacklog" not in text


# --- the router run: the vector pass comes first, then the drafting ---------------------------------------------------------------------------


def state(context):
    return context.vector


def reset(context):
    context.vector = SimpleNamespace(policy={}, order=[], result=None, line=None, table=None, drafter_options=None)


@given("a router publication whose entry names an index and a storage bucket")
def step_router_with_index(context):
    reset(context)
    context.vector.policy = {**tv.tms.SINGLE_ITEM_ONLY, "vectorIndexArn": tv.ARN, "storageBucketName": tv.BUCKET}


@given('2 accepted References that the "hn" monitor delivered, one accepted since the last pass')
def step_router_references(context):
    pass   # the fixture world has them


@given("the vector pass's share of the time is already spent")
def step_share_spent(context):
    state(context).drafter_options = {"vector_out_of_time": lambda: True}


@when("the router runs its daily monitor stories with the vector pass")
def step_router_runs_with_pass(context):
    from _pytest.monkeypatch import MonkeyPatch

    from fake_idea_store import FakeIdeaStore
    from test_idea_items import FakeGate
    from test_monitor_stories import world

    current = state(context)
    patches = MonkeyPatch()
    try:
        patches.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
        patches.setattr("papyrus_content.ideas.items.ItemStore", lambda client, **options: FakeIdeaStore(client, gate=options.get("gate")))
        patches.setattr("papyrus_content.ideas.gate.HumanusGate.for_client", classmethod(lambda cls, client, **options: FakeGate()))
        table, store = tv.router_with(current.policy)
        _, client = world(2)
        current.table = table
        current.result, current.line = tv.run_task(store, client, current.order, patches, drafter_options=current.drafter_options)
    finally:
        patches.undo()


@then("2 ideas are drafted")
def step_two_drafted(context):
    assert state(context).line["drafted"] == 2, state(context).line


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

    from test_monitor_stories import StoryModel, world

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
    assert check(vectors + 1) == (False, False)
    assert check(vectors - 1) == (False, True)
    assert check(drafting - 1) == (True, True)


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
    assert {"monitoring_vectors", "reference_suggest_once", "reference_suggestions", "suggestion_calibration"} <= set(context.package.modules), context.package.modules


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


# --- suggestions do not wait for the index: owed and parked References, the failing sync, the time, several workers -----------------------------------
