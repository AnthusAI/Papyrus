from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_knowledge_query import vector_index  # noqa: E402
from papyrus_knowledge_query.services import KnowledgeQueryServices  # noqa: E402


class FakeGraph:
    def __init__(self, nodes):
        self.nodes = nodes

    def graphql(self, query, variables):
        return {"listSemanticNodes": {"items": self.nodes, "nextToken": None}}

    def list_reference_attachments(self, reference):
        return []


class FakeVectorIndex:
    def __init__(self):
        self.stored = {}
        self.written_last_run = []

    def list_vectors(self, index_arn):
        return [{"key": key, "metadata": metadata} for key, metadata in self.stored.items()]

    def embed_and_put(self, index_arn, candidates):
        self.written_last_run.extend(candidate["key"] for candidate in candidates)
        for candidate in candidates:
            self.stored[candidate["key"]] = candidate["metadata"]
        return len(candidates)


def _node(name, kind, status, description):
    slug = name.lower().replace(" ", "-")
    return {
        "id": f"id-{slug}", "lineageId": f"lineage-{slug}", "versionState": "current", "status": status,
        "nodeKey": f"{kind}--{slug}", "nodeKind": kind, "displayName": name, "description": description, "aliases": [],
    }


def _sync(context):
    context.index.written_last_run = []
    services = KnowledgeQueryServices(graph=FakeGraph(context.nodes), corpus_text=object())
    with mock.patch.dict("os.environ", {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:fake"}), \
            mock.patch.object(vector_index, "_list_references", return_value=[]), \
            mock.patch.object(vector_index, "_list_note_messages", return_value=[]), \
            mock.patch.object(vector_index, "_prepare_note_messages", return_value=[]), \
            mock.patch.object(vector_index, "_prepare_ontology_vectors", return_value=[]), \
            mock.patch.object(vector_index, "_list_index_vectors", side_effect=context.index.list_vectors), \
            mock.patch.object(vector_index, "_embed_and_put_vectors", side_effect=context.index.embed_and_put):
        context.stats = vector_index.index_reference_passages(services, vector_index.VectorIndexOptions(action="sync"))


@given("a vector index with no vectors")
def step_empty_index(context):
    context.index = FakeVectorIndex()


@given('an accepted concept "{accepted}" of kind "{kind}" and a rejected concept "{rejected}" of kind "{rejected_kind}"')
def step_concepts(context, accepted, kind, rejected, rejected_kind):
    context.nodes = [_node(accepted, kind, "accepted", "Cloning a voice from a sample."), _node(rejected, rejected_kind, "rejected", "Nothing.")]


@given("the vector index was synced once")
def step_synced_once(context):
    _sync(context)


@given('the description of "{name}" changes')
def step_description_changes(context, name):
    for node in context.nodes:
        if node["displayName"] == name:
            node["description"] = "A new description."


@when("the vector index is synced")
def step_sync(context):
    _sync(context)


@then("exactly {count:d} concept card is written")
def step_cards_written(context, count):
    assert len(context.index.written_last_run) == count, context.index.written_last_run


@then("no concept card is written")
def step_no_cards(context):
    assert context.index.written_last_run == [], context.index.written_last_run


@then("{count:d} concept card is reported as unchanged")
def step_unchanged(context, count):
    assert context.stats["conceptCardsSkippedUnchanged"] == count, context.stats


@then('the written card has the node key "{node_key}" and the hashtag "{hashtag}"')
def step_card_key(context, node_key, hashtag):
    metadata = next(iter(context.index.stored.values()))
    assert metadata["nodeKey"] == node_key and metadata["hashtag"] == hashtag, metadata


@then('the written card carries the vector kind "{vector_kind}" and the node kind "{node_kind}"')
def step_card_kinds(context, vector_kind, node_kind):
    metadata = next(iter(context.index.stored.values()))
    assert metadata["vectorKind"] == vector_kind and metadata["nodeKind"] == node_kind, metadata
    assert metadata["kind"] == "semanticNode" and metadata["lineageId"], metadata
