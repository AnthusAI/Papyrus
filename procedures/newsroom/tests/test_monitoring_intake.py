from copy import deepcopy

import pytest

from papyrus_content.monitoring import Monitor, SourceItem
from papyrus_content.monitoring_intake import ReferenceIntake


class Client:
    endpoint = "https://example.org/graphql"
    tenant_id = None

    def __init__(self):
        self.references = []
        self.writes = []

    def list_records(self, model):
        if model == "KnowledgeCorpus":
            return [{"id": "knowledge-corpus-publication", "role": "canonical", "name": "Publication"}]
        return deepcopy(self.references)

    def get_record(self, model, identifier):
        return next((r for r in self.references if r["id"] == identifier), None)

    def create_record(self, model, row):
        assert model == "Reference"
        self.writes.append((model, deepcopy(row)))
        self.references.append(deepcopy(row))


def setup(tmp_path):
    client, saved = Client(), []
    monitor = Monitor("hn", "publication", "knowledge-corpus-publication", client.endpoint, tmp_path / "state")
    sink = ReferenceIntake(client, monitor, auth_mode="iam", persist=lambda rows: saved.extend(rows))
    item = SourceItem("123", "A source", "https://example.org/paper", "https://news.ycombinator.com/item?id=123", None)
    p = {**monitor.binding, "sourceId": "123", "sourceItemUrl": item.source_item_url,
         "fingerprint": item.fingerprint, "observedAt": "2026-10-20T00:00:00Z", "revision": 1}
    return client, saved, sink, item, p


def test_registers_pending_and_preserves_accepted_reference_with_more_provenance(tmp_path):
    client, saved, sink, item, p = setup(tmp_path)
    first = sink(item, p)
    assert client.references[0]["curationStatus"] == "pending"
    assert "metadata" not in client.references[0]
    client.references[0]["curationStatus"] = "accepted"
    before = deepcopy(client.references[0])
    other = SourceItem("456", item.title, item.canonical_url, "https://news.ycombinator.com/item?id=456", None)
    again = sink(other, {**p, "sourceId": "456", "sourceItemUrl": other.source_item_url})
    assert first["referenceId"] == again["referenceId"]
    assert len(client.writes) == 1 and client.references[0] == before
    assert len({r["expected"]["id"] for r in saved if r["modelName"] == "Message"}) == 2
    assert all(r["modelName"] != "Reference" for r in saved)
    messages = [r["expected"] for r in saved if r["modelName"] == "Message"]
    assert '"sourceId": "123"' in messages[0]["body"]


def test_editorial_user_intake_never_falls_back_to_raw_model_writes(tmp_path):
    client, _, sink, item, p = setup(tmp_path)
    with pytest.raises(ValueError, match="PR367"):
        ReferenceIntake(client, sink.monitor, auth_mode="user")
    assert client.writes == []


def test_scope_mismatch_is_rejected_before_mutation(tmp_path):
    client, _, sink, item, p = setup(tmp_path)
    for changes in [{"endpoint": "https://other.org/graphql"}, {"corpus_id": "knowledge-corpus-other"}]:
        kwargs = {k: getattr(sink.monitor, k) for k in ["id", "publication", "corpus_id", "endpoint", "state"]}
        with pytest.raises(ValueError):
            ReferenceIntake(client, Monitor(**{**kwargs, **changes}), auth_mode="iam")
    assert client.writes == []


def test_ambiguous_canonical_identity_is_not_overwritten(tmp_path):
    client, _, sink, item, p = setup(tmp_path)
    sink(item, p)
    client.references.append({**client.references[0], "id": "another-v1", "lineageId": "another"})
    with pytest.raises(ValueError, match="Multiple"):
        sink(item, p)
    assert len(client.writes) == 1


def test_mismatched_discovery_identity_is_rejected_before_intake(tmp_path):
    client, _, sink, item, p = setup(tmp_path)
    with pytest.raises(ValueError, match="source item"):
        sink(item, {**p, "sourceId": "wrong"})
    assert client.writes == []


def test_a_reference_stored_under_another_address_of_the_same_document_is_reused(tmp_path):
    client, saved, sink, item, p = setup(tmp_path)
    client.references.append({"id": "reference-earlier-v1", "lineageId": "reference-earlier", "versionNumber": 1,
                              "corpusId": "knowledge-corpus-publication", "versionState": "current",
                              "sourceUri": "https://ttabvue.uspto.gov/ttabvue/ttabvue-91287216-OPP-17.pdf",
                              "curationStatus": "pending"})
    decision = SourceItem("91287216-OPP_17", "Cielo e Terra: Opposition Sustained",
                          "https://ttab-reading-room.uspto.gov/ttab-document/legal-proceeding/91287216/decision/OPP_17.pdf",
                          "https://ttabvue.uspto.gov/ttabvue/v?pno=91287216&pty=OPP", None, "application/pdf",
                          ("https://ttabvue.uspto.gov/ttabvue/ttabvue-91287216-OPP-17.pdf",))
    receipt = sink(decision, {**p, "sourceId": decision.source_id, "sourceItemUrl": decision.source_item_url,
                              "fingerprint": decision.fingerprint})
    assert receipt["referenceId"] == "reference-earlier-v1"
    assert client.writes == []


def test_a_sources_structured_details_ride_on_the_provenance_relation_where_the_knowledge_run_reads_them(tmp_path):
    import json

    client, saved, sink, item, p = setup(tmp_path)
    plain = sink(item, p)
    [relation] = [r["expected"] for r in saved if r["modelName"] == "SemanticRelation"]
    assert "details" not in json.loads(relation["metadata"])  # a source without details writes what it always wrote

    details = {"modelId": "org/tuned", "author": "org", "createdAt": "2026-10-14T08:00:00Z", "license": "apache-2.0", "likes": 3, "downloads": 10, "baseModels": [{"modelId": "org/base", "relation": "finetune"}]}
    model = SourceItem("org--tuned", "org/tuned: text-to-speech model", "https://huggingface.co/org/tuned", "https://huggingface.co/org/tuned", "2026-10-14T08:00:00Z", details=details)
    saved.clear()
    sink(model, {**p, "sourceId": model.source_id, "sourceItemUrl": model.source_item_url, "fingerprint": model.fingerprint})
    [relation] = [r["expected"] for r in saved if r["modelName"] == "SemanticRelation"]
    metadata = json.loads(relation["metadata"])
    assert relation["predicate"] == "ingestion_rationale" and metadata["details"] == details and metadata["sourceId"] == "org--tuned"
    assert plain["referenceId"] != ""
