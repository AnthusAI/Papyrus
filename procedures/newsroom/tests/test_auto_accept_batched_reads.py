"""Auto-accept reads the relations of 25 References per request, so a pass costs a fixed number of requests plus one per 25 References
(features_backend/batched-reads.feature), and decides exactly what the one-Reference-at-a-time pass decided."""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from papyrus_content import request_meter
from papyrus_content.auto_accept import run_auto_accept, verdict_of
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient

from fake_appsync import FakeAppSync

ENDPOINT = "https://example.appsync-api.us-east-1.amazonaws.com/graphql"
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
POLICY = {"enabled": True, "precision": 0.9, "latencyQuantile": 0.5}
PUBLICATION = {"publicationId": "pub", "corpusId": "corpus", "positiveLabel": "include"}


@pytest.fixture(autouse=True)
def iam_lane(monkeypatch):
    monkeypatch.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")


def relation(lineage: str, confidence: float) -> dict:
    return {"id": f"rel-{lineage}", "predicate": "relevance_decision_is", "relationState": "current", "confidence": confidence,
            "objectLineageId": "semantic-node-relevance-include-v1", "createdAt": "2026-11-01T00:00:00Z",
            "metadata": '{"positiveLabel": "include"}'}


def backend_with(votes: int, pending: int) -> FakeAppSync:
    voted = [{"id": f"v{n}", "lineageId": f"lv{n}", "versionState": "current", "curationStatus": "accepted",
              "curationStatusUpdatedBy": "user:editor", "createdAt": "2026-11-01T00:00:00Z", "curationStatusUpdatedAt": "2026-11-01T06:00:00Z"} for n in range(votes)]
    waiting = [{"id": f"p{n}", "lineageId": f"lp{n}", "versionState": "current", "curationStatus": "pending",
                "curationStatusUpdatedBy": "worker", "createdAt": "2026-11-02T00:00:00Z"} for n in range(pending)]
    relations = {f"reference#lv{n}#current": [relation(f"lv{n}", 0.95)] for n in range(votes)}
    relations |= {f"reference#lp{n}#current": [relation(f"lp{n}", 0.97)] for n in range(pending)}
    return FakeAppSync(indexes={"listReferencesByCurationStatusKeyAndUpdatedAt": {"corpus#accepted": voted, "corpus#rejected": [], "corpus#pending": waiting},
                                "listSemanticRelationsBySubjectState": relations})


def pass_requests(votes: int, pending: int) -> tuple[int, dict]:
    backend = backend_with(votes, pending)
    client = PapyrusGraphQLAuthoringClient(endpoint=ENDPOINT, header_factory=lambda body: {}, site_tenant=False)
    client._open_connection = lambda: backend  # type: ignore[method-assign]
    request_meter.reset_for_tests()
    with request_meter.run("test:auto-accept", emit="log"):
        result = run_auto_accept(client, PUBLICATION, POLICY, now=NOW, dry_run=True)
    return len(backend.requests), result


def expected_requests(votes: int, pending: int) -> int:
    pages = lambda rows: max(1, math.ceil(rows / 100))   # the fake backend pages index reads by 100, as AppSync does
    index_reads = pages(votes) + pages(0) + pages(pending)   # accepted, rejected, pending
    return index_reads + math.ceil(votes / 25) + math.ceil(pending / 25)


def test_a_pass_costs_one_request_per_25_references_not_one_per_reference():
    small, small_result = pass_requests(votes=60, pending=10)
    large, large_result = pass_requests(votes=600, pending=100)
    assert small == expected_requests(60, 10)
    assert large == expected_requests(600, 100)
    assert large < (600 + 100) / 10   # the per-Reference loop made 700 requests for the relations alone
    assert small_result["status"] == "dry-run" and small_result["votes"] == 60 and small_result["candidates"] == 10
    assert large_result["votes"] == 600 and large_result["candidates"] == 100


def test_the_verdict_from_batched_relations_is_the_verdict_of_the_per_reference_read():
    class Client:
        def list_semantic_relations_by_subject_state(self, key):
            return [relation("lx", 0.93)]
    from papyrus_content.auto_accept import verdict_from_relations
    assert verdict_of(Client(), {"lineageId": "lx"}, "include") == verdict_from_relations([relation("lx", 0.93)], "include")
