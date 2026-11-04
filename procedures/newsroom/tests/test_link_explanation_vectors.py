"""An editor's explanation of an accepted link is in the vector index and found by the internal knowledge query, never by a public reader
(src/papyrus_knowledge_query/vector_index.py, services.py, engine.py; features_backend/link-explanation-vectors.feature). Fakes only; no AWS or OpenAI."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content import monitoring_vectors as vectors  # noqa: E402
from papyrus_knowledge_query import vector_index  # noqa: E402
from papyrus_knowledge_query.engine import run_knowledge_query  # noqa: E402
from papyrus_knowledge_query.services import KnowledgeQueryServices, S3VectorsProvider, explanations_allowed  # noqa: E402
from test_pending_reference_vectors import FakeCorpus, FakeIndex, reference  # noqa: E402

NOTE = "Both papers measure the same failure from opposite ends: one on the benchmark, one in production."


def link(name, first, second, note=NOTE, state="current", decision="accepted", provenance="human", kind="reference.link", object_kind="reference", predicate="related_to"):
    metadata = {"kind": kind, "provenance": provenance, "decision": decision, "decidedBy": "an editor", "decidedAt": "2026-11-01T10:00:00Z", "note": note}
    return {"id": f"rel-{name}", "relationState": state, "predicate": predicate, "subjectKind": "reference", "subjectId": f"id-{first}",
            "subjectLineageId": f"lin-{first}", "objectKind": object_kind, "objectId": f"id-{second}", "objectLineageId": f"lin-{second}" if object_kind == "reference" else second,
            "updatedAt": "2026-11-01T10:00:00Z", "metadata": json.dumps(metadata)}


class Graph:
    def __init__(self, relations, nodes=()):
        self.relations, self.nodes, self.fail = list(relations), list(nodes), False

    def graphql(self, query, variables):
        if self.fail:
            raise RuntimeError("AppSync is down")
        if "ListLinkRelations" in query:
            return {"listSemanticRelationsByNewsroomFeedAndCreatedAt": {"items": self.relations, "nextToken": None}}
        if "ListSemanticNodes" in query:
            return {"listSemanticNodes": {"items": self.nodes, "nextToken": None}}
        return {"listModelAttachmentsByOwnerRoleAndSortKey": {"items": [], "nextToken": None}}

    def list_reference_attachments(self, reference):
        return []


NODE = {"id": "node-1-v1", "lineageId": "node-1", "versionState": "current", "nodeKey": "topic:evals", "nodeKind": "topic", "displayName": "Evaluation", "status": "accepted"}


def sync(graph, references, index, **options):
    services = KnowledgeQueryServices(graph=graph, corpus_text=FakeCorpus())
    with mock.patch.dict("os.environ", {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:fake"}), \
            mock.patch.object(vector_index, "_list_references", return_value=references), \
            mock.patch.object(vector_index, "_list_note_messages", return_value=[]), \
            mock.patch.object(vector_index, "_prepare_note_messages", return_value=[]), \
            mock.patch.object(vector_index, "_list_index_vectors", side_effect=index.list_vectors), \
            mock.patch.object(vector_index, "_embed_and_put_vectors", side_effect=index.embed_and_put), \
            mock.patch.object(vector_index, "_delete_vectors", side_effect=index.delete), \
            mock.patch.object(vector_index, "_get_vectors", side_effect=index.get), \
            mock.patch.object(vector_index, "_put_vectors", side_effect=index.put):
        return vector_index.index_reference_passages(
            services, vector_index.VectorIndexOptions(action="sync", include_ontology_vectors=False, include_concept_cards=False, skip_references=True, **options))


def explanation_vectors(index):
    return {key: value for key, value in index.stored.items() if key.startswith("link_explanation-")}


def two_accepted():
    return [reference("a", "accepted"), reference("b", "accepted")]


def test_an_accepted_explained_link_is_one_vector_naming_both_ends_and_the_explanation():
    index = FakeIndex()
    stats = sync(Graph([link("ab", "a", "b")]), two_accepted(), index)
    [(key, stored)] = explanation_vectors(index).items()
    assert key == "link_explanation-rel-ab" and stats["linkExplanationsToWrite"] == 1
    metadata = stored["metadata"]
    assert metadata["vectorKind"] == "link_explanation" and metadata["relationId"] == "rel-ab" and metadata["predicate"] == "related_to"
    assert (metadata["subjectLineageId"], metadata["objectLineageId"]) == ("lin-a", "lin-b")
    assert metadata["decidedBy"] == "an editor" and metadata["audience"] == "editor" and metadata["curationStatus"] == "accepted"
    assert "Title a" in metadata["text"] and "Title b" in metadata["text"] and NOTE in metadata["text"]


def test_a_concept_tag_with_an_explanation_is_indexed_with_the_concept_name():
    index = FakeIndex()
    tag = link("ac", "a", "node-1", kind="reference.concept", object_kind="semanticNode")
    tag["objectKind"] = "semanticNode"
    sync(Graph([tag], [NODE]), two_accepted(), index)
    [stored] = explanation_vectors(index).values()
    assert "Evaluation" in stored["metadata"]["text"] and stored["metadata"]["objectKind"] == "semanticNode"


@pytest.mark.parametrize("row", [
    link("x", "a", "b", note=""),
    link("x", "a", "b", note="   "),
    link("x", "a", "b", state="suggested", decision=None, provenance="suggested"),
    link("x", "a", "b", state="rejected", decision="rejected"),
    link("x", "a", "b", kind="item.concept"),
    link("x", "a", "b", provenance="suggested", decision=None),
])
def test_only_accepted_person_made_links_with_a_note_are_indexed(row):
    index = FakeIndex()
    sync(Graph([row]), two_accepted(), index)
    assert explanation_vectors(index) == {}


def test_a_link_a_person_made_with_no_decision_recorded_yet_counts_as_accepted():
    index = FakeIndex()
    sync(Graph([link("ab", "a", "b", decision=None)]), two_accepted(), index)
    assert len(explanation_vectors(index)) == 1


def test_a_link_to_a_reference_that_is_not_accepted_is_not_indexed():
    index = FakeIndex()
    sync(Graph([link("ab", "a", "b")]), [reference("a", "accepted"), reference("b", "pending")], index)
    assert explanation_vectors(index) == {}


def test_an_unchanged_explanation_is_not_embedded_again_and_an_edited_one_is():
    index, graph = FakeIndex(), Graph([link("ab", "a", "b")])
    sync(graph, two_accepted(), index)
    second = sync(graph, two_accepted(), index)
    assert second["linkExplanationsToWrite"] == 0 and second["linkExplanationsSkippedUnchanged"] == 1 and second["vectorsWritten"] == 0
    graph.relations = [link("ab", "a", "b", note="Corrected: they disagree on what counts as a failure.")]
    third = sync(graph, two_accepted(), index)
    assert third["linkExplanationsToWrite"] == 1
    assert "Corrected" in explanation_vectors(index)["link_explanation-rel-ab"]["metadata"]["text"]


@pytest.mark.parametrize("later", [
    link("ab", "a", "b", state="rejected", decision="rejected"),
    link("ab", "a", "b", note=""),
])
def test_a_link_later_rejected_or_with_its_note_cleared_loses_its_vector(later):
    index, graph = FakeIndex(), Graph([link("ab", "a", "b")])
    sync(graph, two_accepted(), index)
    graph.relations = [later]
    stats = sync(graph, two_accepted(), index)
    assert explanation_vectors(index) == {} and stats["linkExplanationsRemoved"] == 1


def test_where_the_router_may_not_delete_the_vector_is_marked_withdrawn_and_the_search_filter_excludes_it():
    index, graph = FakeIndex(deny_delete=True), Graph([link("ab", "a", "b")])
    sync(graph, two_accepted(), index)
    graph.relations = [link("ab", "a", "b", state="rejected", decision="rejected")]
    stats = sync(graph, two_accepted(), index)
    [stored] = explanation_vectors(index).values()
    assert stored["metadata"]["curationStatus"] == "withdrawn" and stored["data"] == {"float32": [1.0, 0.0]} and stats["linkExplanationsWithdrawn"] == 1
    assert any("DeleteVectors was denied" in warning for warning in stats["warnings"])
    assert query({}, [stored["metadata"]]) == []
    again = sync(graph, two_accepted(), index)   # a second pass does not re-mark what is already marked
    assert again["linkExplanationsWithdrawn"] == 0
    graph.relations = [link("ab", "a", "b")]   # accepted again: the vector comes back
    sync(graph, two_accepted(), index)
    assert explanation_vectors(index)["link_explanation-rel-ab"]["metadata"]["curationStatus"] == "accepted"


def test_a_link_read_that_fails_deletes_nothing_and_does_not_fail_the_sync():
    index, graph = FakeIndex(), Graph([link("ab", "a", "b")])
    sync(graph, two_accepted(), index)
    graph.fail = True
    stats = sync(graph, two_accepted(), index)
    assert len(explanation_vectors(index)) == 1 and any("link explanations were not synced" in warning for warning in stats["warnings"])


def test_a_dry_run_and_the_switch_change_nothing():
    index = FakeIndex()
    sync(Graph([link("ab", "a", "b")]), two_accepted(), index, dry_run=True)
    sync(Graph([link("ab", "a", "b")]), two_accepted(), index, include_link_explanations=False)
    assert index.stored == {}


def test_the_routers_daily_pass_leaves_link_explanations_to_the_by_hand_sync():
    seen = {}

    def indexer(services, options):
        seen["explanations"] = options.include_link_explanations
        return {"vectorsWritten": 0, "conceptCardsToWrite": 0, "embeddingInputCharacters": 0}

    with mock.patch.object(vectors, "s3vectors_client_missing_reason", lambda region_name=None: None):
        vectors.run_vector_pass(
            mock.Mock(graphql=lambda *a, **k: {}), {"publicationId": "p", "corpusId": "c", "appsyncEndpoint": "e"},
            {"vectorIndexArn": "arn:x", "storageBucketName": "b", "suggestions": {"enabled": False}}, now=__import__("datetime").datetime(2026, 11, 2),
            out_of_time=lambda: False, maximum_cost_usd=1.0, embedding_key="k", read_watermark=lambda: None, write_watermark=lambda v: None,
            services_for=lambda p, b: "services", full_indexer=indexer)
    assert seen == {"explanations": False}   # no changed-since index on links: they are indexed by the command-line sync (docs/monitoring-cloud.md)


# --- audience and filters ------------------------------------------------------------------------------------------------------------------


def test_the_metadata_filter_passes_explanations_deliberately_and_keeps_public_requests_from_them():
    provider = S3VectorsProvider(vector_index_arn="arn:x")
    exclusion = {"vectorKind": {"$ne": "link_explanation"}}
    for scope in ({}, {"curationStatus": "accepted"}, {"audience": "editor", "corpusId": "c"}):
        clauses = (provider._metadata_filter(scope) or {}).get("$and") or [provider._metadata_filter(scope)]
        assert exclusion not in clauses   # accepted-status explanation vectors satisfy both the accepted-only and the accepted-or-absent clause
    for scope in ({"audience": "public"}, {"audience": "reader"}, {"audience": "PUBLIC", "curationStatus": "accepted", "corpusId": "c"}):
        assert exclusion in provider._metadata_filter(scope)["$and"]
    assert explanations_allowed({}) and explanations_allowed({"audience": "editor"}) and not explanations_allowed({"audience": "public"})


def returned(metadata_list):
    client = mock.Mock()
    client.query_vectors.return_value = {"vectors": [{"key": f"k{i}", "distance": 0.1, "metadata": m} for i, m in enumerate(metadata_list)]}
    return client


def query(scope, metadata_list):
    provider = S3VectorsProvider(vector_index_arn="arn:x")
    with mock.patch.dict("sys.modules", {"boto3": mock.Mock(client=mock.Mock(return_value=returned(metadata_list)))}):
        return provider._query_vectors([0.1], scope, 10)


EXPLANATION_METADATA = {"kind": "semanticRelation", "vectorKind": "link_explanation", "id": "rel-ab", "curationStatus": "accepted", "audience": "editor"}


def test_the_post_filter_drops_an_explanation_for_a_public_request_even_when_the_index_returns_one():
    assert [m["id"] for m in query({"audience": "public"}, [EXPLANATION_METADATA, {"kind": "reference", "id": "a", "curationStatus": "accepted"}])] == ["a"]
    assert [m["id"] for m in query({}, [EXPLANATION_METADATA])] == ["rel-ab"]
    assert [m["id"] for m in query({"audience": "editor"}, [EXPLANATION_METADATA])] == ["rel-ab"]


def test_broad_search_asks_for_explanations_as_their_own_kind_and_never_for_a_public_request():
    provider = S3VectorsProvider(vector_index_arn="arn:x")
    seen = []
    provider._query_vectors = lambda vector, scope, limit, vector_kind=None: seen.append(vector_kind) or []
    with mock.patch.object(provider, "_embed", return_value=[0.1]):
        provider.search("q", {"rankingDiversity": "broad"}, 5)
        assert "link_explanation" in seen
        seen.clear()
        provider.search("q", {"rankingDiversity": "broad", "audience": "public"}, 5)
        assert "link_explanation" not in seen


def test_suggestions_and_idea_pack_neighbours_filter_by_kind_so_they_never_pick_explanations_up():
    from papyrus_content import reference_suggestions
    from papyrus_content.ideas import context_packs
    assert "link_explanation" not in reference_suggestions.CONCEPT_VECTOR_KINDS
    assert reference_suggestions.REFERENCE_SUMMARY_VECTOR_KIND == context_packs.REFERENCE_SUMMARY_VECTOR_KIND == "reference_summary"


# --- the query engine ------------------------------------------------------------------------------------------------------------------------


class Search:
    name = "explanations"

    def search(self, query, scope, limit):
        return [{"rank": 1, "distance": 0.05, "kind": "semanticRelation", "id": "rel-ab", "lineageId": "rel-ab", "title": "Title a / Title b",
                 "metadata": {**EXPLANATION_METADATA, "lineageId": "rel-ab", "relationId": "rel-ab", "relationKind": "reference.link", "predicate": "related_to",
                              "subjectKind": "reference", "subjectLineageId": "lin-a", "objectKind": "reference", "objectLineageId": "lin-b",
                              "subjectTitle": "Title a", "objectTitle": "Title b", "decidedBy": "an editor", "explanation": NOTE,
                              "text": f"Editor's explanation of a link between two items.\nExplanation: {NOTE}"}}]


class Graph2:
    name = "g"

    def resolve_anchor(self, anchor):
        return {"kind": anchor["kind"], "id": anchor["id"], "lineageId": anchor["lineageId"], "title": f"Title {anchor['lineageId'][4:]}",
                "curationStatus": "accepted", "sourceUri": f"https://example.org/{anchor['lineageId']}"}

    def expand_anchor(self, anchor, scope):
        return {"objects": [], "relations": [], "warnings": []}


def ask(scope=None):
    request = {"semanticQuery": "why do these two papers belong together", "output": {"format": "both", "maxTokens": 600, "maxPassageTokens": 120}}
    if scope is not None:
        request["scope"] = scope
    return run_knowledge_query(request, KnowledgeQueryServices(graph=Graph2(), semantic=Search()))


def test_the_internal_query_returns_the_explanation_attributed_to_the_editor_and_linking_both_references():
    result = ask()
    [found] = result["structured"]["linkExplanations"]
    assert found["attribution"].startswith("Editor's explanation") and found["explanation"] == NOTE and found["audience"] == "editor"
    assert [end["lineageId"] for end in found["ends"]] == ["lin-a", "lin-b"]
    assert all(end["objectUri"].startswith("papyrus://reference/") for end in found["ends"])
    passages = [p for p in result["structured"]["evidencePassages"] if p.get("selectionReason") == "link_explanation"]
    assert passages and passages[0]["text"].startswith("Editor's explanation") and NOTE in passages[0]["text"]
    assert "Editor's explanation" in result["context"]["text"] and NOTE in result["context"]["text"]


def test_a_public_request_gets_no_explanation_even_if_the_provider_returned_one():
    result = ask({"audience": "public"})
    assert result["structured"]["linkExplanations"] == []
    assert NOTE not in json.dumps(result)
