"""features_backend/pending-reference-vectors.feature. Fakes only; the unit tests in procedures/newsroom/tests/test_pending_reference_vectors.py share them."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_pending_reference_vectors as unit  # noqa: E402
from papyrus_content import monitoring_vectors as vectors  # noqa: E402
from papyrus_content.reference_suggestions import suggest_for  # noqa: E402
from papyrus_knowledge_query import vector_index  # noqa: E402
from papyrus_knowledge_query.services import S3VectorsProvider  # noqa: E402
from procedures.newsroom.tests.test_reference_links import FakeClient  # noqa: E402
from test_reference_suggestions import FakeVectorProvider  # noqa: E402


def start(context, references, deny_delete=False):
    context.index = unit.FakeIndex(deny_delete=deny_delete)
    context.references = {reference["lineageId"]: reference for reference in references}
    context.embedded_summary_data = None


def named(name, status, version="current"):
    return unit.reference(name, status, version)


def run_sync(context):
    context.stats = unit.sync(list(context.references.values()), context.index)


def lineage(name):
    return f"lin-{name}"


@given('a site index with the accepted Reference "{first}" and the pending Reference "{second}"')
def step_accepted_and_pending(context, first, second):
    start(context, [named(first, "accepted"), named(second, "pending")])
    run_sync(context)


@given('a site index with the accepted Reference "{name}"')
def step_accepted(context, name):
    start(context, [named(name, "accepted")])
    run_sync(context)


@given('a site index with the pending Reference "{name}"')
def step_pending(context, name):
    start(context, [named(name, "pending")])
    run_sync(context)
    key = vector_index.reference_summary_vector_key(lineage(name))
    context.summary_data = context.index.stored[key]["data"]


@given('a site index with the accepted Reference "{name}" in which deleting vectors is not allowed')
def step_accepted_no_delete(context, name):
    start(context, [named(name, "accepted")], deny_delete=True)
    run_sync(context)


@given('a site index with the rejected Reference "{first}", the archived Reference "{second}" and a superseded version of "{third}"')
def step_not_indexable(context, first, second, third):
    start(context, [named(first, "rejected"), named(second, "archived"), named(third, "pending", version="superseded")])


@when("the index is synced")
def step_sync(context):
    run_sync(context)


@when('"{name}" is accepted and the index is synced')
def step_accept_sync(context, name):
    context.references[lineage(name)] = named(name, "accepted")
    run_sync(context)


@when('"{name}" goes back to pending and the index is synced')
def step_pending_sync(context, name):
    context.references[lineage(name)] = named(name, "pending")
    run_sync(context)


@when("both are rejected and the index is synced")
def step_both_rejected(context):
    context.references = {key: {**reference, "curationStatus": "rejected", "curationStatusKey": "c#rejected"} for key, reference in context.references.items()}
    run_sync(context)


@when('"{name}" is rejected and the index is synced')
def step_rejected_sync(context, name):
    context.references[lineage(name)] = named(name, "rejected")
    run_sync(context)


@then('"{name}" has a summary vector marked pending and no passage vectors')
def step_pending_summary(context, name):
    assert unit.kinds(context.index, name) == ["reference_summary"], unit.kinds(context.index, name)
    assert unit.status_of(context.index, name) == {"pending"}


@then('"{name}" has a summary vector marked accepted and passage vectors')
def step_accepted_summary(context, name):
    assert "reference_summary" in unit.kinds(context.index, name) and "reference_passage" in unit.kinds(context.index, name)
    assert unit.status_of(context.index, name) == {"accepted"}


@then("the index holds no vector for them")
def step_empty(context):
    assert context.index.stored == {}, context.index.stored


@then('the vectors of "{name}" are marked {status}')
def step_marked(context, name, status):
    assert unit.status_of(context.index, name) == {status}, unit.status_of(context.index, name)


@then('"{name}" has passage vectors')
def step_passages(context, name):
    assert "reference_passage" in unit.kinds(context.index, name)


@then("its summary vector was not embedded again")
def step_not_embedded(context):
    key = vector_index.reference_summary_vector_key(lineage("beta"))
    assert context.index.stored[key]["data"] == context.summary_data


@then("the sync records that deleting was denied")
def step_denied(context):
    assert any("DeleteVectors" in warning for warning in context.stats["warnings"]), context.stats["warnings"]


# --- the router pass ----------------------------------------------------------------------------------------------------------------------


@given('a publication whose Reference "{one}" was accepted at "{accepted_at}" and "{two}" is pending since "{pending_at}"')
def step_publication(context, one, accepted_at, pending_at, two):
    context.client = unit.ByStatusClient([unit.row(1, "accepted", accepted_at)], [unit.row(2, "pending", pending_at)])
    context.watermark_writes = []


@when("the router's vector pass runs")
def step_pass(context):
    context.indexed_ids, context.suggested = [], []

    def indexer(services, options):
        context.indexed_ids = list(options.reference_ids)
        return {"vectorsWritten": 2, "conceptCardsToWrite": 0, "embeddingInputCharacters": 10}

    def suggester(client, provider, reference_id, **options):
        context.suggested.append(reference_id)
        return {"skipped": None, "references": [], "concepts": []}

    with mock.patch.object(vectors, "s3vectors_client_missing_reason", lambda region_name=None: None):
        context.result = vectors.run_vector_pass(
            context.client, {"publicationId": "p", "corpusId": "c", "appsyncEndpoint": "e"},
            {"vectorIndexArn": "arn:x", "storageBucketName": "b", "suggestions": {"enabled": True}}, now=datetime(2026, 11, 2), out_of_time=lambda: False,
            maximum_cost_usd=1.0, embedding_key="k", read_watermark=lambda: None, write_watermark=context.watermark_writes.append,
            services_for=lambda p, b: "services", indexer=indexer, suggester=suggester, provider_for=lambda arn: "provider", calibration_loader=lambda c: None)


@then("both References are indexed and suggested for, the pending one first")
def step_both(context):
    assert sorted(context.indexed_ids) == ["ref-1", "ref-2"] and context.suggested == ["ref-2", "ref-1"], (context.indexed_ids, context.suggested)


@then("the pass reports {accepted:d} newly accepted and {pending:d} newly pending Reference")
def step_counts(context, accepted, pending):
    assert (context.result["newlyAccepted"], context.result["newlyPending"]) == (accepted, pending), context.result


@then("the pass saves a place for the pending and the accepted group")
def step_watermark(context):
    import json

    place = json.loads(context.watermark_writes[-1])
    assert place["v"] == 2 and place["pending"]["high"].endswith("#ref-2") and place["accepted"]["high"].endswith("#ref-1"), place


# --- suggestions and search -------------------------------------------------------------------------------------------------------------


@given("a pending Reference \"reference-p\" with a stored vector, another pending Reference close to it and an accepted one a little further")
def step_pending_suggestion(context):
    context.sclient, context.provider = FakeClient(), FakeVectorProvider()
    context.provider.add_reference("reference-p", 0.0, status="pending")
    context.provider.add_reference("reference-q", 0.05, status="pending")
    context.provider.add_reference("reference-a", 0.1, status="accepted")
    for name in ("reference-p", "reference-q"):
        context.sclient.tables["Reference"][f"{name}-v1"] = {"id": f"{name}-v1", "lineageId": name, "versionNumber": 1, "versionState": "current", "corpusId": "corpus-1"}


@when('suggestions are made for "reference-p"')
def step_suggest(context):
    context.suggested_result = suggest_for(context.sclient, context.provider, "reference-p", now="2026-11-01T12:00:00Z")


@then("the accepted Reference is suggested")
def step_accepted_suggested(context):
    assert [entry["lineageId"] for entry in context.suggested_result["references"]] == ["reference-a"], context.suggested_result


@then("the pending Reference is not")
def step_pending_not(context):
    assert "reference-q" not in [entry["lineageId"] for entry in context.suggested_result["references"]]


@given("the knowledge search asks the index for a topic")
def step_search(context):
    context.search_provider = S3VectorsProvider(vector_index_arn="arn:test:index")


@when("the index also returns a pending Reference")
def step_returns_pending(context):
    client = mock.Mock()
    client.query_vectors.return_value = {"vectors": [
        {"key": "a", "distance": 0.1, "metadata": {"kind": "reference", "id": "a", "curationStatus": "accepted"}},
        {"key": "p", "distance": 0.05, "metadata": {"kind": "reference", "id": "p", "curationStatus": "pending"}},
    ]}
    with mock.patch.dict("sys.modules", {"boto3": mock.Mock(client=mock.Mock(return_value=client))}):
        context.matches = context.search_provider._query_vectors([0.1], {}, 10)


@then("the search results leave it out")
def step_leave_out(context):
    assert [match["id"] for match in context.matches] == ["a"], context.matches


@then("the search filter asks for accepted References whatever curation status the request names")
def step_filter(context):
    accepted_or_absent = {"$or": [{"curationStatus": {"$exists": False}}, {"curationStatus": {"$eq": "accepted"}}]}
    for asked in ("pending", "rejected", "all"):
        clauses = context.search_provider._metadata_filter({"curationStatus": asked, "corpusId": "c"})["$and"]
        assert accepted_or_absent in clauses, clauses
