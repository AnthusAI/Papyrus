import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

import test_monitoring_vectors as tv  # noqa: E402
from test_monitor_stories import world  # noqa: E402
from papyrus_content.ideas.monitor_stories import collect_monitored_items  # noqa: E402
from ideas_fixtures import NOW  # noqa: E402


def make_site(context, count, mark):
    rows, client = world(count)
    oldest = rows[-1]
    mark(oldest, client)
    context.site = SimpleNamespace(rows=rows, client=client, oldest=oldest, items=None, counts=None, listed=[])


@given("a site with {count:d} accepted monitored References, the oldest of which an editor voted on")
def step_voted(context, count):
    make_site(context, count, lambda row, client: row.update(curationActorKind="human"))


@given("a site with {count:d} accepted monitored References, the oldest of which an editor tagged with a concept")
def step_tagged(context, count):
    def tag(row, client):
        client.tags = [{"id": "tag-1", "relationState": "current", "predicate": "related_to", "subjectKind": "reference", "subjectLineageId": row["lineageId"], "objectKind": "semanticNode",
                        "objectLineageId": "semantic-node-editor_concept--x", "metadata": '{"provenance": "human"}'}]
    make_site(context, count, tag)


def stopping_after(reads):
    counter = {"calls": 0}

    def out_of_time():
        counter["calls"] += 1
        return counter["calls"] > reads

    return out_of_time


def priority_of(site):
    from papyrus_content.monitoring_vectors import signal_lineages

    original = site.client.list_by_index

    def with_tags(index, key, **kwargs):
        return getattr(site.client, "tags", []) if key == "reference-links" else original(index, key, **kwargs)

    site.client.list_by_index = with_tags
    try:
        return signal_lineages(site.client)
    finally:
        site.client.list_by_index = original


@when("the time stops the reading after {reads:d} References")
def step_stop(context, reads):
    site = context.site
    priority = priority_of(site)
    site.items, site.counts = collect_monitored_items(site.client, site="example-site", now=NOW, workers=2, out_of_time=stopping_after(reads), priority_lineages=priority, count_pending=False)


@then("the voted Reference was read and is a candidate")
def step_voted_candidate(context):
    assert context.site.oldest["id"] in [item.reference_id for item in context.site.items], [item.reference_id for item in context.site.items]


@then("the tagged Reference was read and is a candidate")
def step_tagged_candidate(context):
    assert context.site.oldest["id"] in [item.reference_id for item in context.site.items], [item.reference_id for item in context.site.items]


@when("the candidates are collected without counting the pending References")
def step_no_count(context):
    site = context.site
    original = site.client.list_by_index

    def spy(index, key, **kwargs):
        site.listed.append(key)
        return original(index, key, **kwargs)

    site.client.list_by_index = spy
    site.items, site.counts = collect_monitored_items(site.client, site="example-site", now=NOW, count_pending=False)


@then("the pending References were not listed and there are {count:d} candidate Reference read")
def step_not_listed(context, count):
    site = context.site
    assert not [key for key in site.listed if key.endswith("#pending")], site.listed
    assert len(site.items) == count, len(site.items)


# --- the index walk ---------------------------------------------------------------------------------------------------------------------------


@given('an index that holds the summary vectors of the accepted Reference "one" and of "three", which was pending when it was indexed')
def step_index(context):
    from papyrus_knowledge_query.vector_index import reference_summary_vector_key

    def summary(lineage, status):
        return {"key": reference_summary_vector_key(lineage), "metadata": {"vectorKind": "reference_summary", "lineageId": lineage, "curationStatus": status}}

    context.walk = SimpleNamespace(vectors=[summary("lineage-one", "accepted"), summary("lineage-three", "pending")], prepared=[], stats=None)


@when('the router\'s index sync walks the Reference "one", "two" and "three"')
def step_walk(context):
    from papyrus_knowledge_query import vector_index
    from papyrus_knowledge_query.services import KnowledgeQueryServices

    walk = context.walk
    references = [{"id": f"ref-{name}", "lineageId": f"lineage-{name}", "versionState": "current", "curationStatus": "accepted"} for name in ("one", "two", "three")]

    def prepare(services, reference, options):
        walk.prepared.append(reference["lineageId"].removeprefix("lineage-"))
        return {"referenceId": reference["id"], "status": "no_text", "candidates": [], "warnings": [], "failures": []}

    with mock.patch.dict("os.environ", {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:fake"}), \
            mock.patch.object(vector_index, "_list_references", return_value=references), mock.patch.object(vector_index, "_list_note_messages", return_value=[]), \
            mock.patch.object(vector_index, "_prepare_note_messages", return_value=[]), mock.patch.object(vector_index, "_list_index_vectors", return_value=walk.vectors), \
            mock.patch.object(vector_index, "_prepare_reference_for_indexing", side_effect=prepare), mock.patch.object(vector_index, "_prepare_concept_card_vectors", return_value=[]), \
            mock.patch.object(vector_index, "_apply_status_reconciliation"):
        services = KnowledgeQueryServices(graph=mock.Mock(), corpus_text=object())
        walk.stats = vector_index.index_reference_passages(services, vector_index.VectorIndexOptions(
            action="sync", worker_count=1, include_ontology_vectors=False, include_concept_cards=False, skip_indexed=True))


@then('only "two" and "three" are prepared')
def step_prepared(context):
    assert sorted(context.walk.prepared) == ["three", "two"], context.walk.prepared


@then("the sync counts {count:d} Reference skipped because it was indexed")
def step_skipped(context, count):
    assert context.walk.stats["referencesSkippedIndexed"] == count, context.walk.stats


# --- the run ----------------------------------------------------------------------------------------------------------------------------------


@given("the signal reading's share of the time is already spent")
def step_signals_spent(context):
    options = dict(getattr(context.vector, "drafter_options", None) or {})
    options["signal_out_of_time"] = lambda: True
    context.vector.drafter_options = options


@then("the log line says how many seconds the vector pass, the signal reading, the drafting and the reading of candidates took")
def step_timings(context):
    timings = context.vector.line["timings"]
    for key in ("vectorsSeconds", "signalsSeconds", "draftingSeconds", "collectSeconds"):
        assert isinstance(timings.get(key), (int, float)), timings


@then("the vector pass is over below {vectors:d} seconds left, the signal reading below {signals:d} and drafting below {drafting:d}")
def step_thresholds(context, vectors, signals, drafting):
    seen = context.vector.seen
    remaining = context.vector.remaining

    def state(left):
        remaining[0] = left
        return (seen["vector_out_of_time"](), seen["signal_out_of_time"](), seen["out_of_time"]())

    assert state(vectors + 2) == (False, False, False)
    assert state(vectors - 2) == (True, False, False)
    assert state(signals - 2) == (True, True, False)
    assert state(drafting - 2) == (True, True, True)
