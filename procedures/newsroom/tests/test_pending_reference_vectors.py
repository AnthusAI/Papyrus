"""Pending References are indexed as context only (src/papyrus_knowledge_query/vector_index.py, monitoring_vectors.py, reference_suggestions.py;
features_backend/pending-reference-vectors.feature). Fakes only; no AWS or OpenAI."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content import monitoring_vectors as vectors  # noqa: E402
from papyrus_content.reference_suggestions import suggest_for  # noqa: E402
from papyrus_knowledge_query import vector_index  # noqa: E402
from papyrus_knowledge_query.services import KnowledgeQueryServices  # noqa: E402
from test_reference_suggestions import FakeVectorProvider  # noqa: E402
from procedures.newsroom.tests.test_reference_links import FakeClient  # noqa: E402

BODY = "The extracted article body talks about retrieval and ranking at some length. " * 12
SUMMARY = "A study of how small retrieval models rank news items for readers, with the failure cases it found."


class FakeGraph:
    def graphql(self, query, variables):
        return {"listModelAttachmentsByOwnerRoleAndSortKey": {"items": [], "nextToken": None}}

    def list_reference_attachments(self, reference):
        return [{"role": "extracted_text", "storagePath": "s/x.txt"}, {"role": "curation", "metadata": json.dumps({"summary": {"text": SUMMARY}})}]


class FakeCorpus:
    def read_text(self, path):
        return BODY


class FakeIndex:
    """Holds vectors by key with their data and metadata, as the S3 Vectors index does."""

    def __init__(self, deny_delete=False):
        self.stored: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.puts: list[dict] = []
        self.deny_delete = deny_delete

    def list_vectors(self, arn):
        return [{"key": key, "metadata": dict(vector["metadata"])} for key, vector in self.stored.items()]

    def embed_and_put(self, arn, candidates):
        for candidate in candidates:
            self.stored[candidate["key"]] = {"data": {"float32": [1.0, 0.0]}, "metadata": dict(candidate["metadata"])}
        return len(candidates)

    def delete(self, arn, keys):
        if self.deny_delete:
            error = Exception("denied")
            error.response = {"Error": {"Code": "AccessDeniedException"}}
            raise error
        self.deleted.extend(keys)
        for key in keys:
            self.stored.pop(key, None)

    def get(self, arn, keys):
        return [{"key": key, "data": self.stored[key]["data"], "metadata": dict(self.stored[key]["metadata"])} for key in keys if key in self.stored]

    def put(self, arn, vectors_):
        for vector in vectors_:
            self.puts.append(vector)
            self.stored[vector["key"]] = {"data": vector["data"], "metadata": dict(vector["metadata"])}


def reference(name, status, version="current"):
    return {"id": f"id-{name}", "lineageId": f"lin-{name}", "corpusId": "c", "title": f"Title {name}", "sourceUri": f"https://example.org/{name}",
            "curationStatus": status, "curationStatusKey": f"c#{status}", "versionState": version}


def sync(references, index, **options):
    services = KnowledgeQueryServices(graph=FakeGraph(), corpus_text=FakeCorpus())
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
            services, vector_index.VectorIndexOptions(action="sync", include_ontology_vectors=False, include_concept_cards=False, **options))


def kinds(index, lineage):
    return sorted(v["metadata"]["vectorKind"] for v in index.stored.values() if v["metadata"].get("referenceLineageId") == f"lin-{lineage}")


def status_of(index, lineage):
    return {v["metadata"]["curationStatus"] for v in index.stored.values() if v["metadata"].get("referenceLineageId") == f"lin-{lineage}"}


def test_status_is_read_from_the_field_or_the_key_suffix():
    assert vector_index.reference_curation_status({"curationStatus": "pending"}) == "pending"
    assert vector_index.reference_curation_status({"curationStatusKey": "corpus#accepted"}) == "accepted"
    assert vector_index.reference_curation_status({}) == ""


def test_a_pending_reference_gets_its_summary_vector_marked_pending_and_no_passages():
    index = FakeIndex()
    stats = sync([reference("p", "pending"), reference("a", "accepted")], index)
    assert kinds(index, "p") == ["reference_summary"] and status_of(index, "p") == {"pending"}
    assert "reference_passage" in kinds(index, "a") and status_of(index, "a") == {"accepted"}
    assert stats["pendingReferences"] == 1 and stats["acceptedReferences"] == 1


def test_rejected_archived_and_superseded_references_are_not_indexed():
    index = FakeIndex()
    sync([reference("r", "rejected"), reference("x", "archived"), reference("o", "pending", version="superseded"), reference("n", "")], index)
    assert index.stored == {}


def test_a_pending_reference_accepted_later_is_marked_accepted_and_gets_its_passages_without_a_new_summary_embedding():
    index = FakeIndex()
    sync([reference("p", "pending")], index)
    key = vector_index.reference_summary_vector_key("lin-p")
    first_data = index.stored[key]["data"]
    stats = sync([reference("p", "accepted")], index)
    assert status_of(index, "p") == {"accepted"} and "reference_passage" in kinds(index, "p")
    assert stats["vectorsStatusRefreshed"] == 1 and index.stored[key]["data"] == first_data
    assert index.stored[key]["metadata"]["curationStatusKey"] == "c#accepted"


def test_a_reference_rejected_after_it_was_indexed_loses_every_vector():
    index = FakeIndex()
    sync([reference("a", "accepted"), reference("p", "pending")], index)
    stats = sync([reference("a", "rejected"), reference("p", "rejected")], index)
    assert index.stored == {} and stats["vectorsDeletedForStatus"] > 0


def test_an_accepted_reference_sent_back_to_pending_keeps_its_summary_and_loses_its_passages():
    index = FakeIndex()
    sync([reference("a", "accepted")], index)
    sync([reference("a", "pending")], index)
    assert kinds(index, "a") == ["reference_summary"] and status_of(index, "a") == {"pending"}


def test_a_reference_the_graph_does_not_list_is_left_alone_and_a_dry_run_changes_nothing():
    index = FakeIndex()
    sync([reference("a", "accepted"), reference("p", "pending")], index)
    before = json.dumps(index.stored, sort_keys=True)
    sync([], index)
    assert json.dumps(index.stored, sort_keys=True) == before
    stats = sync([reference("a", "rejected"), reference("p", "accepted")], index, dry_run=True)
    assert json.dumps(index.stored, sort_keys=True) == before
    assert stats["vectorsToDeleteForStatus"] > 0 and stats["vectorsToRefreshStatus"] == 1 and index.deleted == []


def test_vectors_written_before_the_status_field_existed_are_refreshed_once_with_no_embedding():
    index = FakeIndex()
    sync([reference("a", "accepted")], index)
    for vector in index.stored.values():
        vector["metadata"].pop("curationStatus")
    stats = sync([reference("a", "accepted")], index)
    assert status_of(index, "a") == {"accepted"} and stats["embeddingRequests"] == 0
    assert sync([reference("a", "accepted")], index)["vectorsStatusRefreshed"] == 0


def test_without_permission_to_delete_the_vectors_are_marked_excluded_instead():
    index = FakeIndex(deny_delete=True)
    sync([reference("a", "accepted")], index)
    stats = sync([reference("a", "rejected")], index)
    assert status_of(index, "a") == {"rejected"} and stats["vectorsMarkedExcluded"] > 0 and stats["vectorsDeletedForStatus"] == 0
    assert any("DeleteVectors" in warning for warning in stats["warnings"])


def test_the_audit_reports_the_stale_vectors_and_changes_nothing():
    index = FakeIndex()
    sync([reference("a", "accepted")], index)
    services = KnowledgeQueryServices(graph=FakeGraph(), corpus_text=FakeCorpus())
    with mock.patch.dict("os.environ", {"PAPYRUS_S3_VECTOR_INDEX_ARN": "arn:fake"}), \
            mock.patch.object(vector_index, "_list_references", return_value=[reference("a", "rejected")]), \
            mock.patch.object(vector_index, "_list_note_messages", return_value=[]), \
            mock.patch.object(vector_index, "_prepare_note_messages", return_value=[]), \
            mock.patch.object(vector_index, "_list_index_vectors", side_effect=index.list_vectors):
        stats = vector_index.index_reference_passages(services, vector_index.VectorIndexOptions(action="audit"))
    assert stats["vectorsToDeleteForStatus"] > 0 and index.deleted == []


# --- the router pass ------------------------------------------------------------------------------------------------------------------------


class ByStatusClient:
    def __init__(self, accepted, pending):
        self.by_status = {"accepted": accepted, "pending": pending}
        self.asked = []

    def list_by_index(self, index_name, key_value, *, limit=100):
        self.asked.append(key_value)
        return list(self.by_status.get(key_value.rsplit("#", 1)[1], []))


def row(number, status, at):
    return {"id": f"ref-{number}", "lineageId": f"lineage-{number}", "versionState": "current", "curationStatus": status, "curationStatusUpdatedAt": at}


def test_the_router_picks_up_accepted_and_pending_references_after_the_watermark_new_arrivals_first_then_pending_then_accepted_newest_first():
    client = ByStatusClient([row(1, "accepted", "2026-10-30T10:00:00Z")], [row(2, "pending", "2026-10-29T10:00:00Z"), row(3, "pending", "2026-10-25T10:00:00Z")])
    found = vectors.references_since(client, {"corpusId": "c"}, "2026-10-26T00:00:00Z")
    assert [r["id"] for r in found] == ["ref-2", "ref-1"]   # both are new arrivals; the pending tier comes before the accepted one
    assert client.asked == ["c#accepted", "c#pending"]
    assert [r["id"] for r in vectors.references_since(client, {"corpusId": "c"}, None)] == ["ref-2", "ref-3", "ref-1"]   # no saved place: pending (what editors triage) newest first, then the accepted with no human signal


def test_a_pending_reference_accepted_since_the_last_pass_comes_round_again_as_accepted():
    client = ByStatusClient([row(2, "accepted", "2026-10-31T10:00:00Z")], [])
    assert [r["id"] for r in vectors.references_since(client, {"corpusId": "c"}, "2026-10-30T00:00:00Z")] == ["ref-2"]


def test_the_pass_syncs_and_suggests_for_pending_references_and_counts_them():
    client = ByStatusClient([row(1, "accepted", "2026-10-30T10:00:00Z")], [row(2, "pending", "2026-10-31T10:00:00Z")])
    seen = {}
    suggested = []

    def indexer(services, options):
        seen["ids"] = options.reference_ids
        return {"vectorsWritten": 2, "conceptCardsToWrite": 0, "embeddingInputCharacters": 10}

    def suggester(client_, provider, reference_id, **options):
        suggested.append(reference_id)
        return {"skipped": None, "references": [], "concepts": []}

    written = []
    with mock.patch.object(vectors, "s3vectors_client_missing_reason", lambda region_name=None: None):
        result = vectors.run_vector_pass(
            client, {"publicationId": "p", "corpusId": "c", "appsyncEndpoint": "e"}, {"vectorIndexArn": "arn:x", "storageBucketName": "b", "suggestions": {"enabled": True}},
            now=__import__("datetime").datetime(2026, 11, 2), out_of_time=lambda: False, maximum_cost_usd=1.0, embedding_key="k", read_watermark=lambda: None,
            write_watermark=written.append, services_for=lambda p, b: "services", indexer=indexer, suggester=suggester, provider_for=lambda arn: "provider",
            calibration_loader=lambda c: None)
    assert sorted(seen["ids"]) == ["ref-1", "ref-2"] and suggested == ["ref-2", "ref-1"]   # the pending one is newer and in the earlier tier
    assert result["newlyAccepted"] == 1 and result["newlyPending"] == 1 and len(written) == 1


# --- suggestions for a pending Reference ----------------------------------------------------------------------------------------------------


def test_a_pending_reference_gets_suggestions_from_its_own_vector_and_is_never_a_neighbour():
    client = FakeClient()
    provider = FakeVectorProvider()
    provider.add_reference("reference-p", 0.0, status="pending")
    provider.add_reference("reference-q", 0.05, status="pending")
    provider.add_reference("reference-a", 0.1, status="accepted")
    provider.add_reference("reference-z", 1.4, status="accepted")
    for lineage in ("reference-p", "reference-q", "reference-z"):
        client.tables["Reference"][f"{lineage}-v1"] = {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "corpusId": "corpus-1"}
    client.tables["Reference"]["reference-p-v1"]["curationStatus"] = "pending"
    result = suggest_for(client, provider, "reference-p", now="2026-11-01T12:00:00Z")
    assert result["skipped"] is None
    assert [entry["lineageId"] for entry in result["references"]] == ["reference-a"]
    assert all({"curationStatus": {"$eq": "accepted"}} in query["$and"] for query in provider.queries if "$and" in query)


def test_a_reference_with_no_vector_is_still_skipped_with_the_reason():
    client = FakeClient()
    client.tables["Reference"] = {"reference-m": {"id": "reference-m", "lineageId": "reference-m", "corpusId": "corpus-1", "curationStatus": "pending"}}
    assert "no reference_summary vector" in suggest_for(client, FakeVectorProvider(), "reference-m")["skipped"]
