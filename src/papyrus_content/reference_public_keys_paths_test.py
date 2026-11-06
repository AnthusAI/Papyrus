"""The public keys and the card copies on every path that writes a Reference (docs/plans/public-blocks-from-indexes.md, PPY-7f1e54).

A row is in the public index only when it can be public: accepted, or pending with a stored prediction of 0.5 or more. Every writer that changes a vote, a
prediction or a version keeps the keys right; a row that cannot be public carries no key at all (never an explicit null on a new row). Offline: the same
in-memory backend ``reference_creation_paths_test`` uses.
"""
from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from .reference_creation_paths_test import ARRIVED, CORPUS_KEYS, NOW, PAPER, PATHS, Memory, VoteClient, corpus_of

PUBLIC_FIELDS = {"publicFeedKey", "publicOrderKey"}
CARD_FIELD_NAMES = {"cardImage", "cardSummary", "cardSiteName", "cardPageTitle"}


@pytest.mark.parametrize("key", CORPUS_KEYS)
@pytest.mark.parametrize("path", sorted(PATHS))
def test_a_new_pending_reference_nobody_predicted_carries_no_public_key_and_no_card_copy(path, key):
    reference = PATHS[path](key)
    assert not (PUBLIC_FIELDS | CARD_FIELD_NAMES) & set(reference), {name: reference.get(name) for name in PUBLIC_FIELDS | CARD_FIELD_NAMES}


def test_an_import_that_creates_an_accepted_reference_is_public_from_the_start_and_sorts_after_every_scored_one():
    from .catalog import build_reference_catalog_registration_records

    corpus_id, corpus = corpus_of("alpha-site")
    plan = build_reference_catalog_registration_records(
        {"items": [{"item_id": "item-1", "title": "T", "source_uri": "https://example.org/t", "ingestion_rationale": "Because."}]},
        {"corpusConfig": corpus, "corpusId": corpus_id, "status": "accepted", "importedAt": NOW})
    (reference,) = [record["expected"] for record in plan["records"] if record["modelName"] == "Reference"]
    assert reference["publicFeedKey"] == f"{corpus_id}#accepted"
    assert reference["publicOrderKey"] == f"n#{reference['feedArrivalAt']}#{reference['id']}"


def test_the_router_recording_a_prediction_brings_a_pending_reference_into_the_index_at_half_or_more():
    from .monitoring_router import record_original_prediction

    corpus_id, _ = corpus_of("alpha-site")
    fresh = {"lineageId": "reference-p", "corpusId": corpus_id, "versionState": "current", "curationStatus": "pending", "createdAt": NOW, "feedStateKey": f"{corpus_id}#unrated"}
    client = VoteClient(corpus_id, {"id": "reference-p-v1", **fresh})
    publication = {"positiveLabel": "include"}
    record_original_prediction(client, publication, {"label": "include", "confidence": 0.9, "decidedAt": NOW}, "reference-p-v1", {"observedAt": NOW})
    row = client.get_record("Reference", "reference-p-v1")
    assert row["publicFeedKey"] == f"{corpus_id}#recommended#2026-11-02"
    assert row["publicOrderKey"] == f"p0.900000#{ARRIVED}#reference-p-v1"
    low = VoteClient(corpus_id, {"id": "reference-q-v1", **fresh})
    record_original_prediction(low, publication, {"label": "exclude", "confidence": 0.9, "decidedAt": NOW}, "reference-q-v1", {"observedAt": NOW})
    assert not PUBLIC_FIELDS & set(low.get_record("Reference", "reference-q-v1")), "a prediction below one half leaves the row out of the index, with no null written"


def public_row(corpus_id: str, **extra: Any) -> dict[str, Any]:
    return {"id": "reference-v-v1", "lineageId": "reference-v", "corpusId": corpus_id, "versionState": "current", "curationStatus": "pending",
            "sourceUri": PAPER, "feedStateKey": f"{corpus_id}#unrated", "createdAt": NOW, "feedArrivalAt": ARRIVED, "predictedAcceptProbability": 0.8,
            "publicFeedKey": f"{corpus_id}#recommended#2026-11-02", "publicOrderKey": f"p0.800000#{ARRIVED}#reference-v-v1", **extra}


@pytest.mark.parametrize("action,partition", [("accept", "{c}#accepted"), ("reject", None), ("reopen", "{c}#recommended#2026-11-02"), ("archive", None)])
def test_a_vote_through_chat_moves_the_reference_between_the_public_partitions(action, partition):
    from papyrus_newsroom.reference_actions import review_reference_curation

    corpus_id, _ = corpus_of("alpha-site")
    calls: list[tuple[str, dict[str, Any]]] = []

    def graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        calls.append((query, variables))
        if "getReference" in query:
            return {"getReference": {"id": "reference-1", "lineageId": "reference-1", "corpusId": corpus_id, "versionState": "current", "curationStatus": "pending",
                                     "newsroomFeedKey": "references", "createdAt": NOW, "feedArrivalAt": ARRIVED, "predictedAcceptProbability": 0.8,
                                     "publicFeedKey": f"{corpus_id}#recommended#2026-11-02", "publicOrderKey": f"p0.800000#{ARRIVED}#reference-1"}}
        return {"updateReference": {"id": "reference-1"}}

    review_reference_curation(graphql, reference_id="reference-1", action=action, reason_code="out_of_scope" if action == "reject" else "")
    (update,) = [variables for query, variables in calls if "updateReference" in query]
    assert update["input"]["publicFeedKey"] == (partition.format(c=corpus_id) if partition else None)
    assert update["input"]["publicOrderKey"] == (f"p0.800000#{ARRIVED}#reference-1" if partition else None)


def test_the_chat_asks_for_what_the_public_keys_are_made_from():
    from papyrus_newsroom.reference_actions import GET_REFERENCE_QUERY

    for name in ("predictedAcceptProbability", "feedArrivalAt", "createdAt", "publicFeedKey", "publicOrderKey"):
        assert name in GET_REFERENCE_QUERY.split(), name


def test_a_vote_through_chat_on_a_row_that_is_not_public_names_no_public_field():
    from papyrus_newsroom.reference_actions import review_reference_curation

    corpus_id, _ = corpus_of("alpha-site")
    calls: list[tuple[str, dict[str, Any]]] = []

    def graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        calls.append((query, variables))
        if "getReference" in query:
            return {"getReference": {"id": "reference-1", "lineageId": "reference-1", "corpusId": corpus_id, "versionState": "current", "curationStatus": "pending",
                                     "newsroomFeedKey": "references", "createdAt": NOW}}
        return {"updateReference": {"id": "reference-1"}}

    review_reference_curation(graphql, reference_id="reference-1", action="reject", reason_code="out_of_scope")
    (update,) = [variables for query, variables in calls if "updateReference" in query]
    assert not PUBLIC_FIELDS & set(update["input"])


def test_the_cyclotron_accepting_or_rejecting_moves_the_public_keys():
    from .auto_accept import accept_reference_automatically
    from .auto_reject import reject_reference_automatically

    corpus_id, _ = corpus_of("alpha-site")
    accepted = VoteClient(corpus_id, public_row(corpus_id))
    assert accept_reference_automatically(accepted, {"id": "reference-v-v1"}, reason="Confident.", evidence={}, now=NOW)
    row = accepted.get_record("Reference", "reference-v-v1")
    assert (row["publicFeedKey"], row["publicOrderKey"]) == (f"{corpus_id}#accepted", f"p0.800000#{ARRIVED}#reference-v-v1")
    rejected = VoteClient(corpus_id, public_row(corpus_id))
    assert reject_reference_automatically(rejected, {"id": "reference-v-v1"}, cyclotron_id="relevance", probability=0.99, proof_id="proof-1", decision_id="d1", now=NOW)
    row = rejected.get_record("Reference", "reference-v-v1")
    assert (row["publicFeedKey"], row["publicOrderKey"]) == (None, None)


def test_the_cyclotron_voting_on_a_row_that_is_not_public_names_no_public_field():
    from .auto_reject import reject_reference_automatically

    corpus_id, _ = corpus_of("alpha-site")
    row = public_row(corpus_id, predictedAcceptProbability=0.2)
    row.pop("publicFeedKey")
    row.pop("publicOrderKey")
    client = VoteClient(corpus_id, row)
    assert reject_reference_automatically(client, {"id": "reference-v-v1"}, cyclotron_id="relevance", probability=0.99, proof_id="proof-1", decision_id="d1", now=NOW)
    assert not PUBLIC_FIELDS & set(client.get_record("Reference", "reference-v-v1"))


def test_retiring_a_citation_stub_takes_it_out_of_the_public_index_and_restoring_it_puts_it_back():
    from .reference_citation_stubs import restored_fields, retired_fields

    corpus_id, _ = corpus_of("alpha-site")
    stub = public_row(corpus_id)
    retired = retired_fields(stub, now=NOW)
    assert retired["publicFeedKey"] is None and retired["publicOrderKey"] is None
    restored = restored_fields({**stub, **retired, "curationStatus": "archived"}, now=NOW)
    assert restored["publicFeedKey"] == f"{corpus_id}#recommended#2026-11-02"
    plain = public_row(corpus_id, predictedAcceptProbability=0.1)
    plain.pop("publicFeedKey")
    plain.pop("publicOrderKey")
    assert not PUBLIC_FIELDS & set(retired_fields(plain, now=NOW))


def test_a_new_version_is_keyed_with_its_own_id_carries_the_card_copies_and_the_old_version_leaves_the_index():
    from .catalog import build_reference_catalog_registration_records
    from .records import apply_record_changes, build_record_changes

    corpus_id, corpus = corpus_of("alpha-site")
    client = Memory(corpus_id)
    catalog = {"items": [{"item_id": "item-1", "title": "First", "source_uri": PAPER, "ingestion_rationale": "Because."}]}

    def register(title: str, at: str) -> None:
        catalog["items"][0]["title"] = title
        plan = build_reference_catalog_registration_records(catalog, {"corpusConfig": corpus, "corpusId": corpus_id, "status": "accepted", "importedAt": at})
        with mock.patch("papyrus_content.records.upload_attachment_body"):
            apply_record_changes(client, build_record_changes(client, plan["records"]))

    register("First", "2026-11-01T00:00:00Z")
    (first,) = client.references()
    first.update(predictedAcceptProbability=0.9, predictionDecidedAt="2026-11-01T01:00:00.000Z", cardImage="https://img.example.org/a.jpg", cardSummary="A summary.", cardSiteName="Example", cardPageTitle="A title")
    register("Retitled", "2026-11-02T00:00:00Z")
    versions = {row["versionNumber"]: row for row in client.references()}
    assert versions[1]["versionState"] == "superseded" and versions[1]["publicFeedKey"] is None and versions[1]["publicOrderKey"] is None
    second = versions[2]
    assert second["publicFeedKey"] == f"{corpus_id}#accepted"
    assert second["publicOrderKey"] == f"p0.900000#2026-11-01T00:00:00.000Z#{second['id']}", "the sort key carries the new version's id and the arrival the first version had"
    assert (second["cardImage"], second["cardSummary"], second["cardSiteName"], second["cardPageTitle"]) == ("https://img.example.org/a.jpg", "A summary.", "Example", "A title")
