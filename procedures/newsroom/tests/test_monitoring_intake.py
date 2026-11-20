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


def _archived_match(client, item, *, status="archived", by):
    client.references.append({"id": "reference-stub-v1", "lineageId": "reference-stub", "versionNumber": 1, "corpusId": "knowledge-corpus-publication",
                              "versionState": "current", "sourceUri": item.canonical_url, "curationStatus": status,
                              "curationStatusKey": f"knowledge-corpus-publication#{status}", "curationStatusUpdatedBy": by,
                              "createdAt": "2026-10-01T00:00:00Z", "feedStateKey": None, "reviewedFeedKey": "references#reviewed"})
    return deepcopy(client.references[0])


def test_a_stub_the_machine_archived_returns_to_pending_with_its_feed_keys_when_a_monitor_finds_the_paper(tmp_path):
    from papyrus_content.reference_citation_stubs import RETIRED_BY
    client, _, sink, item, p = setup(tmp_path)
    _archived_match(client, item, by=RETIRED_BY)
    receipt = sink(item, p)
    row = client.references[0]
    assert receipt["referenceId"] == "reference-stub-v1" and receipt["referenceRestored"] is True and client.writes == []
    assert row["curationStatus"] == "pending" and row["curationStatusKey"] == "knowledge-corpus-publication#pending"
    assert row["feedStateKey"] == "knowledge-corpus-publication#unrated" and row["reviewedFeedKey"] is None
    assert row["discoveredByMonitorId"] == "hn"


@pytest.mark.parametrize("status, by", [("rejected", "papyrus-retire-citation-stubs"), ("archived", "an editor"), ("rejected", "an editor"),
                                        ("accepted", "papyrus-retire-citation-stubs")])
def test_a_rejected_or_human_archived_match_is_not_restored(tmp_path, status, by):
    client, _, sink, item, p = setup(tmp_path)
    before = _archived_match(client, item, status=status, by=by)
    receipt = sink(item, p)
    row = client.references[0]
    assert "referenceRestored" not in receipt
    assert {key: row[key] for key in before} == before   # curation fields exactly as they were


class CountingClient(Client):
    """The table behind AppSync's 100-row pages: every listing of the Reference table costs a request per page."""

    def __init__(self, existing: int):
        super().__init__()
        self.requests = 0
        self.references = [{"id": f"reference-held-{n}-v1", "lineageId": f"reference-held-{n}", "versionNumber": 1, "versionState": "current",
                            "corpusId": "knowledge-corpus-publication", "sourceUri": f"https://example.org/held/{n}", "curationStatus": "pending"}
                           for n in range(existing)]

    def list_records(self, model):
        if model == "Reference":
            self.requests += max(1, -(-len(self.references) // 100))
        return super().list_records(model)


def deliveries(client, listing, count, tmp_path):
    from papyrus_content.monitoring_intake import ReferenceListing  # noqa: F401 - the listing under test

    monitor = Monitor("hn", "publication", "knowledge-corpus-publication", client.endpoint, tmp_path / "state")
    receipts = []
    for number in range(count):
        item = SourceItem(f"new-{number}", f"A new source {number}", f"https://example.org/new/{number}", f"https://news.ycombinator.com/item?id={number}", None)
        provenance = {**monitor.binding, "sourceId": item.source_id, "sourceItemUrl": item.source_item_url, "fingerprint": item.fingerprint,
                      "observedAt": "2026-11-04T00:00:00Z", "revision": 1}
        receipts.append(ReferenceIntake(client, monitor, auth_mode="iam", persist=lambda rows: None, listing=listing)(item, provenance))
    return receipts


@pytest.mark.parametrize("existing", [200, 5000])
def test_a_run_of_deliveries_reads_the_reference_table_once_not_once_per_delivery(tmp_path, existing):
    from papyrus_content.monitoring_intake import ReferenceListing

    each, shared = CountingClient(existing), CountingClient(existing)
    deliveries(each, None, 30, tmp_path)
    receipts = deliveries(shared, ReferenceListing(shared), 30, tmp_path)
    pages = -(-existing // 100)
    assert each.requests == sum(-(-(existing + n) // 100) for n in range(30)), "without a shared listing every delivery reads the whole table"
    assert shared.requests == pages, "a shared listing reads it once"
    print(f"\nINTAKE REQUESTS references={existing} deliveries=30 per_delivery_scan={each.requests} shared_listing={shared.requests}")  # noqa: T201
    assert len({r["referenceId"] for r in receipts}) == 30 and len(shared.writes) == 30


def test_a_delivery_sees_the_reference_an_earlier_delivery_of_the_run_created(tmp_path):
    from papyrus_content.monitoring_intake import ReferenceListing

    client = CountingClient(5)
    listing = ReferenceListing(client)
    monitor = Monitor("hn", "publication", "knowledge-corpus-publication", client.endpoint, tmp_path / "state")
    item = SourceItem("1", "Same source", "https://example.org/same", "https://news.ycombinator.com/item?id=1", None)
    other = SourceItem("2", "Same source", "https://example.org/same", "https://news.ycombinator.com/item?id=2", None)
    receipts = []
    for delivered in (item, other):
        provenance = {**monitor.binding, "sourceId": delivered.source_id, "sourceItemUrl": delivered.source_item_url, "fingerprint": delivered.fingerprint,
                      "observedAt": "2026-11-04T00:00:00Z", "revision": 1}
        receipts.append(ReferenceIntake(client, monitor, auth_mode="iam", persist=lambda rows: None, listing=listing)(delivered, provenance))
    assert receipts[0]["referenceId"] == receipts[1]["referenceId"] and receipts[1]["referenceReused"] is True
    assert len(client.writes) == 1 and client.requests == 1


def test_listing_for_gives_one_listing_per_client():
    from papyrus_content.monitoring_intake import listing_for

    client = Client()
    assert listing_for(client) is listing_for(client) and listing_for(Client()) is not listing_for(client)


class TenantClient(Client):
    def __init__(self, tenant_id):
        super().__init__()
        self.tenant_id = tenant_id


def tenant_intake(client, tenant_id, tmp_path):
    saved = []
    monitor = Monitor("hn", "publication", "knowledge-corpus-publication", client.endpoint, tmp_path / "state")
    return monitor, saved, ReferenceIntake(client, monitor, auth_mode="iam", persist=lambda rows: saved.extend(rows), tenant_id=tenant_id)


def test_a_tenant_publication_is_delivered_through_its_own_tenant_client(tmp_path):
    client = TenantClient("machines-on-machines")
    monitor, saved, sink = tenant_intake(client, "machines-on-machines", tmp_path)
    item = SourceItem("123", "A source", "https://example.org/paper", "https://news.ycombinator.com/item?id=123", None)
    receipt = sink(item, {**monitor.binding, "sourceId": "123", "sourceItemUrl": item.source_item_url,
                          "fingerprint": item.fingerprint, "observedAt": "2026-11-07T00:00:00Z", "revision": 1})
    assert receipt["referenceReused"] is False and len(client.writes) == 1
    assert "tenantId" not in client.references[0]   # Reference is not a tenant model: nothing tenant-shaped is written


@pytest.mark.parametrize("client_tenant, publication_tenant", [
    ("another-tenant", "machines-on-machines"),   # a tenant that differs from the publication's
    ("machines-on-machines", None),               # a tenant client for a publication that names none
    (None, "machines-on-machines"),               # a plain client for a tenant publication
])
def test_a_tenant_that_does_not_match_the_publications_is_refused_before_mutation(tmp_path, client_tenant, publication_tenant):
    client = TenantClient(client_tenant)
    monitor = Monitor("hn", "publication", "knowledge-corpus-publication", client.endpoint, tmp_path / "state")
    with pytest.raises(ValueError, match="endpoint/tenant binding"):
        ReferenceIntake(client, monitor, auth_mode="iam", tenant_id=publication_tenant)
    assert client.writes == []


def test_a_tenant_publication_is_still_refused_on_another_endpoint(tmp_path):
    client = TenantClient("machines-on-machines")
    monitor = Monitor("hn", "publication", "knowledge-corpus-publication", "https://other.org/graphql", tmp_path / "state")
    with pytest.raises(ValueError, match="endpoint/tenant binding"):
        ReferenceIntake(client, monitor, auth_mode="iam", tenant_id="machines-on-machines")
