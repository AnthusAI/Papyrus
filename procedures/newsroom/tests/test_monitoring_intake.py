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
        self.updates = []

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


    def update_record(self, model, row):
        assert model == "Reference"
        self.updates.append(deepcopy(row))
        next(r for r in self.references if r["id"] == row["id"]).update(row)


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
    assert len(client.writes) == 1 and client.references[0] == before and client.updates == []
    assert all(r["modelName"] not in {"Reference", "Message", "SemanticRelation"} for r in saved)   # Messages come only from people
    assert client.references[0]["discoveredByMonitorId"] == "hn"


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


def test_a_delivery_records_its_monitor_and_details_on_the_reference_and_writes_no_message(tmp_path):
    import json

    client, saved, sink, item, p = setup(tmp_path)
    plain = sink(item, p)
    assert "provenanceMessageId" not in plain
    created = client.references[0]
    assert created["discoveredByMonitorId"] == "hn" and created["discoveryDetails"] is None and "discoveryRule" not in created
    assert not [r for r in saved if r["modelName"] in {"Message", "SemanticRelation"}]

    details = {"modelId": "org/tuned", "author": "org", "createdAt": "2026-10-14T08:00:00Z", "license": "apache-2.0", "likes": 3, "downloads": 10, "baseModels": [{"modelId": "org/base", "relation": "finetune"}]}
    model = SourceItem("org--tuned", "org/tuned: text-to-speech model", "https://huggingface.co/org/tuned", "https://huggingface.co/org/tuned", "2026-10-14T08:00:00Z", details=details)
    saved.clear()
    sink(model, {**p, "sourceId": model.source_id, "sourceItemUrl": model.source_item_url, "fingerprint": model.fingerprint})
    stored = client.references[-1]
    assert stored["discoveredByMonitorId"] == "hn" and json.loads(stored["discoveryDetails"]) == details
    assert not [r for r in saved if r["modelName"] in {"Message", "SemanticRelation"}]


def test_a_rule_monitors_delivery_records_its_rule_on_the_reference(tmp_path):
    import json

    client, saved, sink, item, p = setup(tmp_path)
    sink(item, {**p, "machineDecision": {"system": "direct", "rule": {"minLikes": 5}}})
    assert json.loads(client.references[0]["discoveryRule"]) == {"system": "direct", "rule": {"minLikes": 5}}


def test_a_reused_reference_without_a_monitor_gets_one_and_never_loses_its_first(tmp_path):
    client, saved, sink, item, p = setup(tmp_path)
    client.references.append({"id": "reference-earlier-v1", "lineageId": "reference-earlier", "versionNumber": 1,
                              "corpusId": "knowledge-corpus-publication", "versionState": "current",
                              "sourceUri": item.canonical_url, "curationStatus": "accepted"})
    sink(item, p)
    assert client.updates and client.updates[0]["discoveredByMonitorId"] == "hn" and "curationStatus" not in client.updates[0]
    assert client.writes == []
    client.references[0]["discoveredByMonitorId"] = "other"
    client.updates.clear()
    sink(item, p)
    assert client.updates == []
