"""Reads for many keys ride in aliased requests, 25 to a request, and return what the one-at-a-time reads return
(features_backend/batched-reads.feature)."""
from __future__ import annotations

import math
from unittest import mock

import pytest

from papyrus_content import request_meter
from papyrus_content.batched_reads import attachments_of_many, current_relations_of_many, references_by_id
from papyrus_content.graphql_authoring import ALIAS_BATCH_SIZE, PapyrusGraphQLAuthoringClient

from fake_appsync import FakeAppSync

ENDPOINT = "https://example.appsync-api.us-east-1.amazonaws.com/graphql"


def make_client(backend: FakeAppSync, tenant_id: str | None = None) -> PapyrusGraphQLAuthoringClient:
    client = PapyrusGraphQLAuthoringClient(endpoint=ENDPOINT, header_factory=lambda body: {}, tenant_id=tenant_id, site_tenant=False)
    client._open_connection = lambda: backend  # type: ignore[method-assign]
    return client


def relation_rows(count: int) -> dict[str, list[dict]]:
    return {f"reference#lin-{n}#current": [{"id": f"rel-{n}", "predicate": "relevance_decision_is", "relationState": "current"}] for n in range(count)}


@pytest.fixture(autouse=True)
def fresh_meter(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    request_meter.reset_for_tests()
    yield
    request_meter.reset_for_tests()


def test_get_many_is_one_request_per_25_ids_and_matches_get_record():
    rows = {f"ref-{n}": {"id": f"ref-{n}", "title": f"t{n}"} for n in range(60)}
    backend = FakeAppSync(gets={"getReference": rows})
    client = make_client(backend)
    ids = [*rows, "missing"]
    many = client.get_many("Reference", ids)
    assert len(backend.requests) == math.ceil(len(ids) / ALIAS_BATCH_SIZE) == 3
    singly = {record_id: row for record_id in ids if (row := client.get_record("Reference", record_id))}
    assert many == singly and "missing" not in many


def test_get_records_by_id_never_reads_the_whole_table_above_100_ids():
    rows = {f"ref-{n}": {"id": f"ref-{n}"} for n in range(240)}
    backend = FakeAppSync(gets={"getReference": rows}, indexes={"listReferences": {"": list(rows.values())}})
    client = make_client(backend)
    found = client.get_records_by_id("Reference", list(rows))
    assert len(found) == 240
    assert len(backend.requests) == math.ceil(240 / ALIAS_BATCH_SIZE)
    assert not any("listReferences" in query for query in backend.requests)


def test_index_many_returns_each_keys_rows_with_a_request_per_25_keys():
    indexes = {"listSemanticRelationsBySubjectState": relation_rows(53)}
    backend = FakeAppSync(indexes=indexes)
    client = make_client(backend)
    keys = list(indexes["listSemanticRelationsBySubjectState"])
    many = client.index_many("semanticRelationsBySubjectState", keys)
    assert len(backend.requests) == 3
    assert many == {key: client.list_by_index("semanticRelationsBySubjectState", key) for key in keys}


def test_index_many_finishes_a_key_with_more_than_one_page():
    key = "reference#lin-0#current"
    indexes = {"listSemanticRelationsBySubjectState": {key: [{"id": f"r{n}"} for n in range(7)], "reference#lin-1#current": [{"id": "x"}]}}
    backend = FakeAppSync(indexes=indexes)
    client = make_client(backend)
    many = client.index_many("semanticRelationsBySubjectState", [key, "reference#lin-1#current"], limit=3)
    assert [row["id"] for row in many[key]] == [f"r{n}" for n in range(7)]
    assert len(backend.requests) == 1 + 2   # the batch, then the key's remaining two pages
    assert [row["id"] for row in many["reference#lin-1#current"]] == ["x"]


def test_a_batch_counts_as_one_request_in_the_meter():
    backend = FakeAppSync(gets={"getReference": {f"r{n}": {"id": f"r{n}"} for n in range(25)}})
    client = make_client(backend)
    with request_meter.run("test:batch", emit="log") as run:
        client.get_many("Reference", [f"r{n}" for n in range(25)])
    assert run.requests == 1 and run.aliases == 25


def test_the_tenant_scope_applies_to_batched_gets():
    other = {"id": "ref-1", "tenantId": "tenant-b"}
    mine = {"id": "ref-2", "tenantId": "tenant-a"}
    backend = FakeAppSync(gets={"getItem": {"ref-1": other, "ref-2": mine}})
    client = make_client(backend, tenant_id="tenant-a")
    with mock.patch.object(client, "_stored_record_id", side_effect=lambda model, record_id: record_id):
        assert client.get_many("Item", ["ref-1", "ref-2"]) == {"ref-2": mine}


def test_helpers_read_the_same_whether_the_client_batches_or_not():
    class OneAtATime:
        def list_semantic_relations_by_subject_state(self, key):
            return relation_rows(3).get(key, [])
        def list_reference_attachments_by_lineage(self, lineage):
            return [{"id": f"a-{lineage}"}]
        def get_record(self, model, record_id):
            return {"id": record_id} if record_id != "gone" else None
    references = [{"id": f"ref-{n}", "lineageId": f"lin-{n}"} for n in range(3)] + [{"id": "no-lineage"}]
    backend = FakeAppSync(indexes={"listSemanticRelationsBySubjectState": relation_rows(3),
                                    "listReferenceAttachmentsByReferenceLineageAndSortKey": {f"lin-{n}": [{"id": f"a-lin-{n}"}] for n in range(3)}},
                          gets={"getReference": {"ref-1": {"id": "ref-1"}}})
    batching, single = make_client(backend), OneAtATime()
    assert current_relations_of_many(batching, references) == current_relations_of_many(single, references)
    assert attachments_of_many(batching, ["lin-0", "lin-1", "lin-2"]) == attachments_of_many(single, ["lin-0", "lin-1", "lin-2"])
    assert references_by_id(batching, ["ref-1", "gone"]) == {"ref-1": {"id": "ref-1"}}
    assert references_by_id(single, ["ref-1", "gone"]) == {"ref-1": {"id": "ref-1"}, }
