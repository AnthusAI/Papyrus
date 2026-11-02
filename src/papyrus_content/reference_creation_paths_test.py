"""Every way of creating a Reference puts it in the References feed (docs/reference-feed-indexes.md).

The feed reads References only through ``feedStateKey`` + ``predictionSortKey`` / ``feedArrivalAt``. A current Reference that has none of
them is invisible there, so every writer must set all three, whatever the source of the Reference. Each path below runs offline against an
in-memory backend (no AWS, no network, no model) in two corpora and asserts what it stored.

Paths that cannot run offline are listed in ``NOT_RUNNABLE_OFFLINE``; they are covered by their own tests or named in the docs.
"""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path
from typing import Any, Callable
from unittest import mock

import pytest

from .monitoring import Monitor, SourceItem
from .reference_feed_keys import FEED_KEY_FIELDS

CORPUS_KEYS = ("alpha-site", "beta-site")   # synthetic: corpus ids are knowledge-corpus-<key>
NOW = "2026-11-02T12:00:00Z"
ARRIVED = "2026-11-02T12:00:00.000Z"

NOT_RUNNABLE_OFFLINE = {
    "amplify/functions/category-action/handler.ts moveReferenceCorpus": "TypeScript Lambda; sets referenceFeedKeys (lib/reference-feed-keys.ts), whose vectors scripts/test-reference-feed-keys.ts shares with this module",
    "console 'Paste a URL' (priming request)": "creates a Cyclotron priming example, never a Reference (src/papyrus_content/relevance_sweep.py _apply_priming_requests)",
    "console 'Import a file' (priming curation)": "builds a candidate with catalog.reference_record for the Cyclotron; nothing is persisted as a Reference (src/papyrus_content/priming_curation.py)",
    "email submission end to end": "needs the inbound mailbox and an enrichment run; its Reference comes from catalog.build_reference_catalog_registration_records, run below with the email options",
}


class Memory:
    """A publication's tables, recording every write. Implements the client calls the Reference writers use."""

    endpoint = "https://example.org/graphql"
    tenant_id = None

    def __init__(self, corpus_id: str):
        self.corpus_id = corpus_id
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}

    def list_records(self, model: str) -> list[dict[str, Any]]:
        if model == "KnowledgeCorpus":
            return [{"id": self.corpus_id, "role": "canonical", "name": "Publication"}]
        return [copy.deepcopy(row) for (name, _), row in self.rows.items() if name == model]

    def get_record(self, model: str, record_id: str) -> dict[str, Any] | None:
        row = self.rows.get((model, record_id))
        return copy.deepcopy(row) if row else None

    def get_records_by_id(self, model: str, ids: list[str]) -> dict[str, dict[str, Any]]:
        return {record_id: self.get_record(model, record_id) for record_id in ids if self.get_record(model, record_id)}

    def create_record(self, model: str, row: dict[str, Any]) -> dict[str, Any]:
        if (model, row["id"]) in self.rows:
            raise RuntimeError("ConditionalCheckFailedException")
        self.rows[(model, row["id"])] = copy.deepcopy(row)
        return row

    def update_record(self, model: str, row: dict[str, Any]) -> dict[str, Any]:
        self.rows[(model, row["id"])].update(copy.deepcopy(row))
        return row

    def upsert(self, model: str, row: dict[str, Any]) -> str:
        existed = (model, row["id"]) in self.rows
        self.rows.setdefault((model, row["id"]), {}).update(copy.deepcopy(row))
        return "updated" if existed else "created"

    def references(self) -> list[dict[str, Any]]:
        return [row for (model, _), row in self.rows.items() if model == "Reference"]


def corpus_of(key: str) -> tuple[str, dict[str, Any]]:
    return f"knowledge-corpus-{key}", {"key": key, "name": key}


def assert_in_the_unrated_feed(reference: dict[str, Any], corpus_id: str, *, id_suffix: str | None = None) -> None:
    assert reference["corpusId"] == corpus_id, reference
    assert reference["feedStateKey"] == f"{corpus_id}#unrated", {key: reference.get(key) for key in FEED_KEY_FIELDS}
    assert reference["feedArrivalAt"], reference
    assert reference["predictionSortKey"] == f"0.500000#{reference['feedArrivalAt']}#{reference['id']}", reference["predictionSortKey"]
    assert reference["feedArrivalAt"].endswith("Z") and "." in reference["feedArrivalAt"]


# --- the paths -------------------------------------------------------------------------------------------------------------------------

def through_the_catalog(key: str, actor: str | None, *, note: str | None = None) -> dict[str, Any]:
    """`papyrus references import` / assignments registration / email submission / priming: the catalog registration plan, applied."""
    from .catalog import build_reference_catalog_registration_records
    from .records import apply_record_changes, build_record_changes

    corpus_id, corpus = corpus_of(key)
    client = Memory(corpus_id)
    catalog = {"schema_version": 1, "generated_at": NOW, "items": [
        {"item_id": "item-1", "title": "A paper", "source_uri": "https://example.org/paper", "media_type": "text/html",
        "ingestion_rationale": "Because."}]}
    options = {"corpusConfig": corpus, "corpusId": corpus_id, "status": "pending", "importedAt": NOW, "note": note,
               **({"actor": actor} if actor else {})}
    plan = build_reference_catalog_registration_records(catalog, options)
    with mock.patch("papyrus_content.records.upload_attachment_body"):
        apply_record_changes(client, build_record_changes(client, plan["records"]))
    (reference,) = client.references()
    return reference


def through_the_cli_import(key: str) -> dict[str, Any]:
    return through_the_catalog(key, None)


def through_an_email_submission(key: str) -> dict[str, Any]:
    return through_the_catalog(key, "sender@example.org", note="Registered from inbound email submission message-1")


def through_a_named_import(key: str) -> dict[str, Any]:
    return through_the_catalog(key, "cursor:example-import")


def through_chat_reference_create(key: str) -> dict[str, Any]:
    """Slack / console chat Tactus `Reference.create{ url = ..., apply = true }` (papyrus_newsroom.newsroom.papyrus_reference_create)."""
    import papyrus_newsroom.newsroom as newsroom

    corpus_id, corpus = corpus_of(key)
    client = Memory(corpus_id)
    with mock.patch.object(newsroom, "_load_steering_config", return_value={"publication": {"name": "Example"}, "corpora": [corpus]}), \
            mock.patch.object(newsroom, "_resolve_corpus", return_value=corpus), \
            mock.patch("papyrus_content.graphql_authoring.PapyrusGraphQLAuthoringClient", return_value=client), \
            mock.patch("papyrus_content.steering.resolve_classifier_for_corpus", return_value="classifier-1"), \
            mock.patch("papyrus_content.records.upload_attachment_body"), \
            mock.patch("papyrus_content.newsroom_summary.update_newsroom_summary_after_reference_registration"):
        result = newsroom.papyrus_reference_create(
            {"url": "https://example.org/from-chat", "title": "From chat", "corpusKey": key, "apply": True, "enrich": False})
    assert result["applied"] is True, result
    (reference,) = client.references()
    return reference


def through_the_console_intake_mutation(key: str) -> dict[str, Any]:
    """The Lambda behind the console and the email hand-off: `intakePendingReferences` -> reference_intake.find_or_create_source_reference."""
    from .reference_intake import find_or_create_source_reference

    corpus_id, _ = corpus_of(key)
    client = Memory(corpus_id)
    with mock.patch("papyrus_content.reference_intake._provenance"), mock.patch("papyrus_content.reference_images.attach_preview"):
        find_or_create_source_reference(client, [], publication=key, corpus_id=corpus_id, actor="user:editor",
                                        item={"source_uri": "https://example.org/pasted", "title": "Pasted", "media_type": "text/html"})
    (reference,) = client.references()
    return reference


def through_a_monitor_delivery(key: str) -> dict[str, Any]:
    """The monitoring router's ReferenceIntake (versionCreatedBy `papyrus-monitoring-worker`)."""
    from .monitoring_intake import ReferenceIntake

    corpus_id, _ = corpus_of(key)
    client = Memory(corpus_id)
    monitor = Monitor("example-monitor", key, corpus_id, client.endpoint, Path(tempfile.gettempdir()) / "unused-monitor-state")
    item = SourceItem("123", "A source", "https://example.org/monitored", "https://news.example.org/item?id=123", None)
    provenance = {**monitor.binding, "sourceId": "123", "sourceItemUrl": item.source_item_url, "fingerprint": item.fingerprint,
                  "observedAt": NOW, "revision": 1}
    with mock.patch("papyrus_content.monitoring_intake.apply_record_changes"):
        ReferenceIntake(client, monitor, auth_mode="iam")(item, provenance)
    (reference,) = client.references()
    return reference


def through_a_grobid_cited_reference(key: str) -> dict[str, Any]:
    """A Reference auto-created from a citation in an extracted paper."""
    from .reference_url_text import _resolve_or_build_cited_reference_record

    corpus_id, _ = corpus_of(key)
    built = _resolve_or_build_cited_reference_record(
        citation={"title": "A cited paper", "doi": "10.1000/example", "year": 2024, "authors": ["A. Author"]},
        corpus_id=corpus_id, existing_lookup={}, now=NOW)
    assert built["isNew"] is True
    return built["record"]


def through_accession_replacement(key: str) -> dict[str, Any]:
    """Accession that replaces a Reference with a new lineage (`create-uuid-replacement`), and the plain next-version accession."""
    from .accession import new_reference_for_accession_replacement

    corpus_id, _ = corpus_of(key)
    old = {"id": "reference-old-v1", "lineageId": "reference-old", "corpusId": corpus_id, "curationStatus": "pending",
           "versionState": "current", "createdAt": NOW, "metadata": "{}"}
    accession = {"biblicusItemId": "item-new", "storagePath": "corpus/item-new.pdf", "mediaType": "application/pdf",
                 "byteSize": 3, "sha256": "abc"}
    return new_reference_for_accession_replacement(old, corpus_id, "import-run-1", accession, "accession", NOW)


def through_accession_next_version(key: str) -> dict[str, Any]:
    from .accession import next_reference_version_for_accession

    corpus_id, _ = corpus_of(key)
    old = {"id": "reference-old-v1", "lineageId": "reference-old", "corpusId": corpus_id, "curationStatus": "pending",
           "versionState": "current", "createdAt": NOW, "metadata": "{}"}   # a Reference created before the keys existed
    accession = {"storagePath": "corpus/item.pdf", "mediaType": "application/pdf", "byteSize": 3, "sha256": "abc"}
    return next_reference_version_for_accession(old, "import-run-1", accession, "accession", NOW)


PATHS: dict[str, Callable[[str], dict[str, Any]]] = {
    "papyrus references import (CLI)": through_the_cli_import,
    "email submission": through_an_email_submission,
    "monitor delivery": through_a_monitor_delivery,
    "named import (cursor:...)": through_a_named_import,
    "Slack / console chat Reference.create": through_chat_reference_create,
    "console intake mutation (intakePendingReferences)": through_the_console_intake_mutation,
    "GROBID cited reference": through_a_grobid_cited_reference,
    "accession replacement": through_accession_replacement,
    "accession next version": through_accession_next_version,
}


@pytest.mark.parametrize("key", CORPUS_KEYS)
@pytest.mark.parametrize("path", sorted(PATHS))
def test_every_way_of_creating_a_reference_puts_it_in_the_unrated_feed(path, key):
    reference = PATHS[path](key)
    assert_in_the_unrated_feed(reference, f"knowledge-corpus-{key}")


@pytest.mark.parametrize("key", CORPUS_KEYS)
def test_a_monitor_delivery_arrives_when_the_monitor_observed_it(key):
    reference = through_a_monitor_delivery(key)
    assert reference["versionCreatedBy"] == "papyrus-monitoring-worker"
    assert reference["feedArrivalAt"] == ARRIVED   # when the monitor observed it, not when the engine ran


def test_an_import_that_creates_an_accepted_reference_is_in_the_rated_feed():
    from .catalog import build_reference_catalog_registration_records

    corpus_id, corpus = corpus_of("alpha-site")
    plan = build_reference_catalog_registration_records(
        {"items": [{"item_id": "item-1", "title": "T", "source_uri": "https://example.org/t", "ingestion_rationale": "Because."}]},
        {"corpusConfig": corpus, "corpusId": corpus_id, "status": "accepted", "importedAt": NOW})
    (reference,) = [record["expected"] for record in plan["records"] if record["modelName"] == "Reference"]
    assert reference["feedStateKey"] == f"{corpus_id}#rated"


def test_a_new_version_of_a_reference_keeps_its_original_prediction_and_arrival_and_the_old_version_leaves_the_feed():
    from .catalog import build_reference_catalog_registration_records
    from .records import apply_record_changes, build_record_changes

    corpus_id, corpus = corpus_of("alpha-site")
    client = Memory(corpus_id)
    catalog = {"items": [{"item_id": "item-1", "title": "First title", "source_uri": "https://example.org/t", "ingestion_rationale": "Because."}]}

    def register(title: str, at: str) -> None:
        catalog["items"][0]["title"] = title
        plan = build_reference_catalog_registration_records(catalog, {"corpusConfig": corpus, "corpusId": corpus_id, "status": "pending", "importedAt": at})
        with mock.patch("papyrus_content.records.upload_attachment_body"):
            apply_record_changes(client, build_record_changes(client, plan["records"]))

    register("First title", "2026-11-01T00:00:00Z")
    (first,) = client.references()
    first.update(predictedAcceptProbability=0.9, predictionDecidedAt="2026-11-01T01:00:00.000Z",
                 predictionSortKey=f"0.900000#{first['feedArrivalAt']}#{first['id']}")
    register("A changed title", "2026-11-02T00:00:00Z")
    versions = {row["versionNumber"]: row for row in client.references()}
    assert versions[1]["versionState"] == "superseded" and versions[1]["feedStateKey"] is None
    second = versions[2]
    assert second["feedStateKey"] == f"{corpus_id}#unrated"
    assert second["predictedAcceptProbability"] == 0.9 and second["predictionDecidedAt"] == "2026-11-01T01:00:00.000Z"
    assert second["feedArrivalAt"] == "2026-11-01T00:00:00.000Z"
    assert second["predictionSortKey"] == f"0.900000#2026-11-01T00:00:00.000Z#{second['id']}"


def test_a_new_version_of_a_reference_with_no_keys_gets_them():
    from .catalog import build_reference_catalog_registration_records
    from .records import apply_record_changes, build_record_changes

    corpus_id, corpus = corpus_of("beta-site")
    client = Memory(corpus_id)
    catalog = {"items": [{"item_id": "item-1", "title": "First title", "source_uri": "https://example.org/t", "ingestion_rationale": "Because."}]}
    plan = build_reference_catalog_registration_records(catalog, {"corpusConfig": corpus, "corpusId": corpus_id, "status": "pending", "importedAt": NOW})
    with mock.patch("papyrus_content.records.upload_attachment_body"):
        apply_record_changes(client, build_record_changes(client, plan["records"]))
    (old,) = client.references()
    for key in FEED_KEY_FIELDS:
        old.pop(key)   # as it was stored before the feed indexes existed
    catalog["items"][0]["title"] = "A changed title"
    plan = build_reference_catalog_registration_records(catalog, {"corpusConfig": corpus, "corpusId": corpus_id, "status": "pending", "importedAt": "2026-11-03T00:00:00Z"})
    with mock.patch("papyrus_content.records.upload_attachment_body"):
        apply_record_changes(client, build_record_changes(client, plan["records"]))
    current = [row for row in client.references() if row["versionState"] == "current"]
    assert len(current) == 1
    assert_in_the_unrated_feed(current[0], corpus_id)


@pytest.mark.parametrize("action,status,feed", [("accept", "accepted", "rated"), ("reject", "rejected", "rated"),
                                                ("reopen", "pending", "unrated"), ("archive", "archived", None)])
def test_a_vote_through_chat_moves_the_reference_between_the_feeds(action, status, feed):
    from papyrus_newsroom.reference_actions import review_reference_curation

    corpus_id, _ = corpus_of("alpha-site")
    calls: list[tuple[str, dict[str, Any]]] = []

    def graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        calls.append((query, variables))
        if "getReference" in query:
            return {"getReference": {"id": "reference-1", "lineageId": "reference-1", "corpusId": corpus_id, "versionState": "current",
                                     "curationStatus": "pending", "newsroomFeedKey": "references"}}
        return {"updateReference": {"id": "reference-1"}}

    review_reference_curation(graphql, reference_id="reference-1", action=action, reason_code="out_of_scope" if action == "reject" else "")
    (update,) = [variables for query, variables in calls if "updateReference" in query]
    assert update["input"]["curationStatus"] == status
    assert update["input"]["feedStateKey"] == (f"{corpus_id}#{feed}" if feed else None)
