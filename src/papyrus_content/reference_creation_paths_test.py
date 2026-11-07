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
    "console 'Paste a URL' (Add dialog)": "calls intakePendingReferences, the console intake mutation run below; its accept and stars are the Newsroom's reviewReferenceCuration and setReferenceStars (scripts/test-add-reference.ts)",
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

    def list_by_index(self, index_name: str, key_value: str, *, limit: int = 100, sort_eq: str | None = None) -> list[dict[str, Any]]:
        from papyrus_content.reference_reads_testing import list_by_index_from_records
        return list_by_index_from_records(self.list_records, index_name, key_value, sort_eq)

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

PAPER = "https://example.org/paper"
VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def through_the_catalog(key: str, actor: str | None, *, note: str | None = None, address: str = PAPER) -> dict[str, Any]:
    """`papyrus references import` / assignments registration / email submission / priming: the catalog registration plan, applied."""
    from .catalog import build_reference_catalog_registration_records
    from .records import apply_record_changes, build_record_changes

    corpus_id, corpus = corpus_of(key)
    client = Memory(corpus_id)
    catalog = {"schema_version": 1, "generated_at": NOW, "items": [
        {"item_id": "item-1", "title": "A paper", "source_uri": address, "media_type": "text/html",
        "ingestion_rationale": "Because."}]}
    options = {"corpusConfig": corpus, "corpusId": corpus_id, "status": "pending", "importedAt": NOW, "note": note,
               **({"actor": actor} if actor else {})}
    plan = build_reference_catalog_registration_records(catalog, options)
    with mock.patch("papyrus_content.records.upload_attachment_body"):
        apply_record_changes(client, build_record_changes(client, plan["records"]))
    (reference,) = client.references()
    return reference


def through_the_cli_import(key: str, address: str = PAPER) -> dict[str, Any]:
    return through_the_catalog(key, None, address=address)


def through_an_email_submission(key: str, address: str = PAPER) -> dict[str, Any]:
    return through_the_catalog(key, "sender@example.org", note="Registered from inbound email submission message-1", address=address)


def through_a_named_import(key: str, address: str = PAPER) -> dict[str, Any]:
    return through_the_catalog(key, "cursor:example-import", address=address)


def through_chat_reference_create(key: str, address: str = "https://example.org/from-chat") -> dict[str, Any]:
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
            {"url": address, "title": "From chat", "corpusKey": key, "apply": True, "enrich": False})
    assert result["applied"] is True, result
    (reference,) = client.references()
    return reference


def through_the_console_intake_mutation(key: str, address: str = "https://example.org/pasted") -> dict[str, Any]:
    """The Lambda behind the console and the email hand-off: `intakePendingReferences` -> reference_intake.find_or_create_source_reference."""
    from .reference_intake import find_or_create_source_reference

    corpus_id, _ = corpus_of(key)
    client = Memory(corpus_id)
    with mock.patch("papyrus_content.reference_intake._provenance"), mock.patch("papyrus_content.reference_images.attach_preview"):
        find_or_create_source_reference(client, [], publication=key, corpus_id=corpus_id, actor="user:editor",
                                        item={"source_uri": address, "title": "Pasted", "media_type": "text/html"})
    (reference,) = client.references()
    return reference


def through_a_monitor_delivery(key: str, address: str = "https://example.org/monitored") -> dict[str, Any]:
    """The monitoring router's ReferenceIntake (versionCreatedBy `papyrus-monitoring-worker`)."""
    from .monitoring_intake import ReferenceIntake

    corpus_id, _ = corpus_of(key)
    client = Memory(corpus_id)
    monitor = Monitor("example-monitor", key, corpus_id, client.endpoint, Path(tempfile.gettempdir()) / "unused-monitor-state")
    item = SourceItem("123", "A source", address, "https://news.example.org/item?id=123", None)
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


def through_accession_replacement(key: str, address: str = PAPER) -> dict[str, Any]:
    """Accession that replaces a Reference with a new lineage (`create-uuid-replacement`), and the plain next-version accession."""
    from .accession import new_reference_for_accession_replacement

    corpus_id, _ = corpus_of(key)
    old = {"id": "reference-old-v1", "lineageId": "reference-old", "corpusId": corpus_id, "curationStatus": "pending",
           "versionState": "current", "createdAt": NOW, "metadata": "{}", "sourceUri": address}
    accession = {"biblicusItemId": "item-new", "storagePath": "corpus/item-new.pdf", "mediaType": "application/pdf",
                 "byteSize": 3, "sha256": "abc"}
    return new_reference_for_accession_replacement(old, corpus_id, "import-run-1", accession, "accession", NOW)


def through_accession_next_version(key: str, address: str = PAPER) -> dict[str, Any]:
    from .accession import next_reference_version_for_accession

    corpus_id, _ = corpus_of(key)
    old = {"id": "reference-old-v1", "lineageId": "reference-old", "corpusId": corpus_id, "curationStatus": "pending",
           "versionState": "current", "createdAt": NOW, "metadata": "{}", "sourceUri": address}   # a Reference created before the keys existed
    accession = {"storagePath": "corpus/item.pdf", "mediaType": "application/pdf", "byteSize": 3, "sha256": "abc"}
    return next_reference_version_for_accession(old, "import-run-1", accession, "accession", NOW)


PATHS: dict[str, Callable[..., dict[str, Any]]] = {
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


# --- the medium: every path that has an address records what the address certainly says (src/papyrus_content/reference_medium.py) -----------------

PATHS_WITH_AN_ADDRESS = sorted(path for path in PATHS if path != "GROBID cited reference")   # a citation has a DOI and a title, never an address


@pytest.mark.parametrize("key", CORPUS_KEYS)
@pytest.mark.parametrize("path", PATHS_WITH_AN_ADDRESS)
def test_every_way_of_creating_a_reference_records_a_video_address_as_a_video_in_the_pending_video_list(path, key):
    reference = PATHS[path](key, VIDEO)
    corpus_id = f"knowledge-corpus-{key}"
    # A new video has no captured content yet, so it is in the content-needed list of its status (the transcript worker reads it).
    assert reference["contentNeededKey"] == f"{corpus_id}#video#needs_content#pending", reference
    if path.startswith("accession"):
        assert reference["mediumFeedKey"] == f"{corpus_id}#video#pending"   # carried from the Reference it replaces, re-keyed for its status
        return
    assert reference["medium"] == "video", reference
    assert reference["mediumFeedKey"] == f"{corpus_id}#video#pending", reference
    assert "evidenceLevel" not in reference and "playlistUrl" not in reference


@pytest.mark.parametrize("path", PATHS_WITH_AN_ADDRESS)
def test_an_ordinary_address_gets_no_medium_field_and_no_medium_key(path):
    reference = PATHS[path]("alpha-site")
    assert not {"medium", "mediumFeedKey", "contentNeededKey", "captureReason", "evidenceLevel", "playlistUrl"} & set(reference), {key: reference.get(key) for key in reference if "edium" in key}


def test_a_playlist_address_is_an_aggregation_and_in_no_video_list():
    reference = through_the_cli_import("alpha-site", "https://www.youtube.com/playlist?list=PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom")
    assert reference["evidenceLevel"] == "aggregation"
    assert "medium" not in reference and "mediumFeedKey" not in reference and "contentNeededKey" not in reference


def test_a_watch_address_with_a_list_is_the_video_and_records_the_playlist_separately():
    reference = through_the_cli_import("alpha-site", "https://www.youtube.com/watch?v=JDAPDpbXRXw&list=PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom")
    assert reference["medium"] == "video" and "evidenceLevel" not in reference
    assert reference["playlistUrl"] == "https://www.youtube.com/playlist?list=PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom"
    assert reference["sourceUri"].startswith("https://www.youtube.com/watch?v=JDAPDpbXRXw")


# --- a vote moves a video between the medium lists, and a superseded or archived one leaves them -------------------------------------------------


class VoteClient(Memory):
    def __init__(self, corpus_id: str, row: dict[str, Any]):
        super().__init__(corpus_id)
        self.rows[("Reference", row["id"])] = copy.deepcopy(row)


def a_video(corpus_id: str, **extra: Any) -> dict[str, Any]:
    return {"id": "reference-v-v1", "lineageId": "reference-v", "corpusId": corpus_id, "versionState": "current", "curationStatus": "pending",
            "sourceUri": VIDEO, "medium": "video", "mediumFeedKey": f"{corpus_id}#video#pending", "feedStateKey": f"{corpus_id}#unrated",
            "contentNeededKey": f"{corpus_id}#video#needs_content#pending", **extra}


def test_the_cyclotron_accepting_a_video_moves_it_to_the_accepted_video_list():
    from .auto_accept import accept_reference_automatically

    corpus_id, _ = corpus_of("alpha-site")
    client = VoteClient(corpus_id, a_video(corpus_id))
    assert accept_reference_automatically(client, {"id": "reference-v-v1"}, reason="Confident.", evidence={}, now=NOW)
    voted = client.get_record("Reference", "reference-v-v1")
    assert voted["mediumFeedKey"] == f"{corpus_id}#video#accepted" and voted["contentNeededKey"] == f"{corpus_id}#video#needs_content#accepted"


def test_auto_accepting_an_ordinary_page_names_no_medium_field():
    from .auto_accept import accept_reference_automatically

    corpus_id, _ = corpus_of("alpha-site")
    row = {**a_video(corpus_id), "sourceUri": "https://example.org/a"}
    for key in ("medium", "mediumFeedKey", "contentNeededKey"):
        row.pop(key)
    client = VoteClient(corpus_id, row)
    assert accept_reference_automatically(client, {"id": "reference-v-v1"}, reason="Confident.", evidence={}, now=NOW)
    assert not {"mediumFeedKey", "contentNeededKey"} & set(client.get_record("Reference", "reference-v-v1"))


def test_a_captured_video_voted_on_gains_no_content_key():
    from .auto_accept import accept_reference_automatically

    corpus_id, _ = corpus_of("alpha-site")
    row = a_video(corpus_id, captureState="full")
    row.pop("contentNeededKey")
    client = VoteClient(corpus_id, row)
    assert accept_reference_automatically(client, {"id": "reference-v-v1"}, reason="Confident.", evidence={}, now=NOW)
    assert "contentNeededKey" not in client.get_record("Reference", "reference-v-v1")


@pytest.mark.parametrize("action,status,key", [("accept", "accepted", "{c}#video#accepted"), ("reject", "rejected", "{c}#video#rejected"),
                                               ("reopen", "pending", "{c}#video#pending"), ("archive", "archived", None)])
def test_a_vote_through_chat_moves_a_video_between_the_medium_lists(action, status, key):
    from papyrus_newsroom.reference_actions import review_reference_curation

    corpus_id, _ = corpus_of("alpha-site")
    calls: list[tuple[str, dict[str, Any]]] = []

    def graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        calls.append((query, variables))
        if "getReference" in query:
            return {"getReference": {"id": "reference-1", "lineageId": "reference-1", "corpusId": corpus_id, "versionState": "current",
                                     "curationStatus": "pending", "newsroomFeedKey": "references", "sourceUri": VIDEO,
                                     "contentNeededKey": f"{corpus_id}#video#needs_content#pending"}}
        return {"updateReference": {"id": "reference-1"}}

    review_reference_curation(graphql, reference_id="reference-1", action=action, reason_code="out_of_scope" if action == "reject" else "")
    (update,) = [variables for query, variables in calls if "updateReference" in query]
    assert update["input"]["mediumFeedKey"] == (key.format(c=corpus_id) if key else None)
    assert update["input"]["contentNeededKey"] == (key.format(c=corpus_id).replace("#video#", "#video#needs_content#") if key else None)


def test_a_new_version_of_a_video_keeps_it_in_its_list_and_the_old_version_leaves_it():
    from .catalog import build_reference_catalog_registration_records
    from .records import apply_record_changes, build_record_changes

    corpus_id, corpus = corpus_of("alpha-site")
    client = Memory(corpus_id)
    catalog = {"items": [{"item_id": "item-1", "title": "First", "source_uri": VIDEO, "ingestion_rationale": "Because."}]}

    def register(title: str, at: str) -> None:
        catalog["items"][0]["title"] = title
        plan = build_reference_catalog_registration_records(catalog, {"corpusConfig": corpus, "corpusId": corpus_id, "status": "accepted", "importedAt": at})
        with mock.patch("papyrus_content.records.upload_attachment_body"):
            apply_record_changes(client, build_record_changes(client, plan["records"]))

    register("First", "2026-11-01T00:00:00Z")
    register("Retitled", "2026-11-02T00:00:00Z")
    versions = {row["versionNumber"]: row for row in client.references()}
    assert versions[1]["versionState"] == "superseded" and versions[1]["mediumFeedKey"] is None and versions[1]["contentNeededKey"] is None
    assert versions[2]["mediumFeedKey"] == f"{corpus_id}#video#accepted"
    assert versions[2]["contentNeededKey"] == f"{corpus_id}#video#needs_content#accepted"


def test_a_new_version_of_a_captured_video_stays_out_of_the_content_needed_list():
    from .records import _feed_keys_for_new_version

    corpus_id, _ = corpus_of("alpha-site")
    current = a_video(corpus_id, curationStatus="accepted", captureState="full")
    current.pop("contentNeededKey")
    next_reference = {"id": "reference-v-v2", "lineageId": "reference-v", "corpusId": corpus_id, "versionState": "current", "curationStatus": "accepted",
                      "sourceUri": VIDEO, "medium": "video", "createdAt": NOW}
    keys = _feed_keys_for_new_version(next_reference, current)
    assert keys["captureState"] == "full" and "contentNeededKey" not in keys
    waiting = _feed_keys_for_new_version(next_reference, a_video(corpus_id, curationStatus="accepted"))
    assert waiting["contentNeededKey"] == f"{corpus_id}#video#needs_content#accepted"
    settled = _feed_keys_for_new_version(next_reference, a_video(corpus_id, curationStatus="accepted", captureState="thin", captureReason="no_transcript"))
    assert settled["captureReason"] == "no_transcript" and not settled.get("contentNeededKey")


def test_retiring_a_citation_stub_that_is_a_video_takes_it_out_of_the_video_list():
    from .reference_citation_stubs import restored_fields, retired_fields

    corpus_id, _ = corpus_of("alpha-site")
    stub = a_video(corpus_id)
    retired = retired_fields(stub, now=NOW)
    assert retired["mediumFeedKey"] is None and retired["contentNeededKey"] is None
    assert restored_fields({**stub, **retired, "curationStatus": "archived"}, now=NOW)["mediumFeedKey"] == f"{corpus_id}#video#pending"
    ordinary = {**stub, "sourceUri": "https://example.org/a"}
    for key in ("medium", "mediumFeedKey", "contentNeededKey"):
        ordinary.pop(key)
    assert not {"mediumFeedKey", "contentNeededKey"} & set(retired_fields(ordinary, now=NOW))


def test_the_cyclotron_rejecting_a_video_moves_it_to_the_rejected_video_list():
    from .auto_reject import reject_reference_automatically

    corpus_id, _ = corpus_of("alpha-site")
    client = VoteClient(corpus_id, a_video(corpus_id))
    assert reject_reference_automatically(client, {"id": "reference-v-v1"}, cyclotron_id="relevance", probability=0.99, proof_id="proof-1", decision_id="d1", now=NOW)
    rejected = client.get_record("Reference", "reference-v-v1")
    assert rejected["mediumFeedKey"] == f"{corpus_id}#video#rejected" and rejected["contentNeededKey"] == f"{corpus_id}#video#needs_content#rejected"


# --- a prediction: every route either decides, carries one, or asks for one (src/papyrus_content/reference_prediction_queue.py, PPY-eac36e) ---------
#
# The References page and the public pages show a pending Reference only once the Cyclotron has predicted it. The router's delivery decides its own; an accession
# keeps the prediction of the Reference it replaces; every other path below creates a pending Reference with none, and the code that calls it asks for one.
# `LEFT_WITHOUT_A_REQUEST` names the paths that do not, with the reason, so adding a path forces the question.

DECIDES_ITSELF = {"monitor delivery": "the router decides before it delivers (monitoring_router.deliver_reference)"}
CARRIES_ONE = {"accession replacement": "{**reference} keeps the replaced Reference's prediction", "accession next version": "records.py KEPT_FEED_FIELDS"}
LEFT_WITHOUT_A_REQUEST = {"GROBID cited reference": "a machine placeholder that stub retirement archives; `papyrus references queue-predictions` covers it by hand"}
ASKS_FOR_ONE = {"papyrus references import (CLI)", "email submission", "named import (cursor:...)", "Slack / console chat Reference.create",
                "console intake mutation (intakePendingReferences)"}


def test_every_path_that_creates_a_reference_is_accounted_for_in_the_prediction_rule():
    assert set(PATHS) == ASKS_FOR_ONE | set(DECIDES_ITSELF) | set(CARRIES_ONE) | set(LEFT_WITHOUT_A_REQUEST)


@pytest.mark.parametrize("key", CORPUS_KEYS)
@pytest.mark.parametrize("path", sorted(ASKS_FOR_ONE))
def test_a_reference_created_by_an_asking_path_is_one_a_prediction_is_requested_for(path, key):
    from .reference_prediction_queue import references_for_prediction

    reference = PATHS[path](key)
    (request,) = references_for_prediction([reference])
    assert request["referenceId"] == reference["id"] and request["sourceUri"]


@pytest.mark.parametrize("key", CORPUS_KEYS)
@pytest.mark.parametrize("path", sorted(ASKS_FOR_ONE))
def test_a_reference_created_by_an_asking_path_also_requests_its_enrichment_exactly_once(path, key):
    """The one request row that asks for the prediction also asks for the enrichment that precedes it (`predictFor.enrich`); a retry adds nothing."""
    from procedures.newsroom.tests.test_monitoring_router import ENDPOINT, FakeTable, router_config
    from .monitoring_view import TableViewStore
    from .reference_prediction_queue import queue_reference_predictions, references_for_prediction, wants_enrichment

    table = FakeTable()
    table.put_item(router_config())
    store = TableViewStore(table, "hn")
    endpoint = ENDPOINT.replace("abc123", "api0")
    (request,) = references_for_prediction([PATHS[path](key)])
    first = queue_reference_predictions(store, endpoint=endpoint, references=[request], subject="test")
    again = queue_reference_predictions(store, endpoint=endpoint, references=[request], subject="test")
    rows = [row for row in table.by_prefix("DISC#") if row.get("sourceType") == "reference"]
    assert first["queued"] == 1 and again["queued"] == 0 and len(rows) == 1 and wants_enrichment(rows[0])


@pytest.mark.parametrize("path", sorted(CARRIES_ONE))
def test_an_accession_keeps_the_prediction_it_started_with(path):
    old = {"id": "reference-old-v1", "lineageId": "reference-old", "corpusId": "knowledge-corpus-alpha-site", "curationStatus": "pending", "versionState": "current",
           "createdAt": NOW, "metadata": "{}", "sourceUri": PAPER, "predictedAcceptProbability": 0.8, "predictionDecidedAt": "2026-11-01T00:00:00.000Z"}
    from .accession import new_reference_for_accession_replacement, next_reference_version_for_accession
    if path == "accession replacement":
        accession = {"biblicusItemId": "item-new", "storagePath": "corpus/item-new.pdf", "mediaType": "application/pdf", "byteSize": 3, "sha256": "abc"}
        new = new_reference_for_accession_replacement(old, "knowledge-corpus-alpha-site", "import-run-1", accession, "accession", NOW)
    else:
        accession = {"storagePath": "corpus/item.pdf", "mediaType": "application/pdf", "byteSize": 3, "sha256": "abc"}
        new = next_reference_version_for_accession(old, "import-run-1", accession, "accession", NOW)
    assert new["predictedAcceptProbability"] == 0.8 and new["predictionDecidedAt"] == "2026-11-01T00:00:00.000Z"
