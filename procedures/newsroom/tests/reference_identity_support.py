"""Synthetic publication and entry paths shared by the identity tests and the Gherkin steps. No network, no model, no AWS."""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

from papyrus_content.monitoring import Monitor, SourceItem
from papyrus_content.reference_creation_paths_test import Memory, corpus_of

NOW = "2026-11-02T12:00:00Z"
FIRST_CORPUS = "alpha-site"
SECOND_CORPUS = "beta-site"
HELD_ARXIV_ADDRESS = "https://arxiv.org/abs/2401.01234v2"
OTHER_ARXIV_ADDRESS = "https://arxiv.org/pdf/2401.01234v3"


class RecordingMemory(Memory):
    """The synthetic backend, counting every write so a test can prove a path wrote nothing."""

    def __init__(self, corpus_id: str):
        super().__init__(corpus_id)
        self.writes: list[tuple[str, str]] = []

    def create_record(self, model, row):
        self.writes.append(("create", model))
        return super().create_record(model, row)

    def update_record(self, model, row):
        self.writes.append(("update", model))
        return super().update_record(model, row)

    def upsert(self, model, row):
        self.writes.append(("upsert", model))
        return super().upsert(model, row)


def held_reference(address: str, *, corpus: str = FIRST_CORPUS, status: str = "accepted", number: int = 1, title: str = "A held paper") -> dict[str, Any]:
    corpus_id, _ = corpus_of(corpus)
    return {"id": f"reference-held-{number}-v1", "lineageId": f"reference-held-{number}", "versionNumber": 1, "versionState": "current",
            "corpusId": corpus_id, "sourceUri": address, "title": title, "curationStatus": status, "createdAt": f"2026-10-0{number}T00:00:00Z",
            "externalItemId": f"item-held-{number}"}


def publication_holding(address: str, *, corpus: str = FIRST_CORPUS, held_in: str | None = None, status: str = "accepted") -> RecordingMemory:
    """A publication whose canonical corpus is ``corpus`` and which already holds ``address`` in ``held_in`` (default: the same corpus)."""
    corpus_id, _ = corpus_of(corpus)
    client = RecordingMemory(corpus_id)
    row = held_reference(address, corpus=held_in or corpus, status=status)
    client.rows[("Reference", row["id"])] = row
    return client


def references_of(client: Memory) -> list[dict[str, Any]]:
    return client.references()


def through_monitor_delivery(client: RecordingMemory, address: str, *, corpus: str = FIRST_CORPUS) -> dict[str, Any]:
    from papyrus_content.monitoring_intake import ReferenceIntake

    corpus_id, _ = corpus_of(corpus)
    monitor = Monitor("example-monitor", corpus, corpus_id, client.endpoint, Path(tempfile.gettempdir()) / "unused-monitor-state")
    item = SourceItem("123", "A source", address, "https://news.example.org/item?id=123", None)
    provenance = {**monitor.binding, "sourceId": "123", "sourceItemUrl": item.source_item_url, "fingerprint": item.fingerprint,
                  "observedAt": NOW, "revision": 1}
    with mock.patch("papyrus_content.monitoring_intake.apply_record_changes"):
        return ReferenceIntake(client, monitor, auth_mode="iam")(item, provenance)


def through_editor_intake(client: RecordingMemory, address: str, *, corpus: str = FIRST_CORPUS) -> dict[str, Any]:
    from papyrus_content.reference_intake import find_or_create_source_reference

    corpus_id, _ = corpus_of(corpus)
    with mock.patch("papyrus_content.reference_intake._provenance"), mock.patch("papyrus_content.reference_images.attach_preview"):
        return find_or_create_source_reference(client, client.list_records("Reference"), publication=corpus, corpus_id=corpus_id, actor="user:editor",
                                               item={"source_uri": address, "title": "Pasted", "media_type": "text/html"})


def through_research_intake(client: RecordingMemory, address: str, *, corpus: str = FIRST_CORPUS, dry_run: bool = False) -> dict[str, Any]:
    import papyrus_content.assignments_workflow as workflow

    corpus_id, corpus_config = corpus_of(corpus)
    packet = {"proposedReferences": [{"url": address, "title": "Proposed"}]}
    entries = [{"assignment": {"id": "assignment-1", "title": "Find sources"}, "message": {"id": "message-1", "createdAt": NOW}, "packet": packet}]
    with tempfile.TemporaryDirectory() as root, \
            mock.patch.object(workflow, "PAPYRUS_ROOT", Path(root)), \
            mock.patch.object(workflow, "load_assignment_research_packet_entries", return_value=entries), \
            mock.patch.object(workflow, "intake_corpus", return_value=(corpus_config, None)), \
            mock.patch.object(workflow, "update_newsroom_summary_after_reference_registration"):
        return workflow.intake_research_packet_proposals(client, {"assignment": "assignment-1", "corpus-key": corpus, "url-text": "false",
                                                                  "metadata-from-text": "false", "run-id": "run-1", **({"dry-run": "true"} if dry_run else {})})


def through_chat_create(client: RecordingMemory, address: str, *, corpus: str = FIRST_CORPUS, skip_existing: bool = True) -> dict[str, Any]:
    import papyrus_newsroom.newsroom as newsroom

    _, corpus_config = corpus_of(corpus)
    with mock.patch.object(newsroom, "_load_steering_config", return_value={"publication": {"name": "Example"}, "corpora": [corpus_config]}), \
            mock.patch.object(newsroom, "_resolve_corpus", return_value=corpus_config), \
            mock.patch("papyrus_content.graphql_authoring.PapyrusGraphQLAuthoringClient", return_value=client), \
            mock.patch("papyrus_content.steering.resolve_classifier_for_corpus", return_value="classifier-1"), \
            mock.patch("papyrus_content.records.upload_attachment_body"), \
            mock.patch("papyrus_content.newsroom_summary.update_newsroom_summary_after_reference_registration"):
        return newsroom.papyrus_reference_create({"url": address, "title": "From chat", "corpusKey": corpus, "apply": True, "enrich": False,
                                                  "skipExisting": skip_existing})


def through_catalog_import(client: RecordingMemory, address: str, *, corpus: str = FIRST_CORPUS, skip_existing: bool = True) -> dict[str, Any]:
    import papyrus_content.cli as cli

    corpus_id, corpus_config = corpus_of(corpus)
    catalog = {"schema_version": 1, "generated_at": NOW, "items": [{"item_id": "item-new", "title": "Imported", "source_uri": address,
                                                                     "media_type": "text/html", "ingestion_rationale": "Because."}]}
    with mock.patch.object(cli, "load_json_file", return_value=copy.deepcopy(catalog)), \
            mock.patch.object(cli, "maybe_enrich_reference_catalog_title_subtitle", side_effect=lambda loaded, options, persist=False: loaded), \
            mock.patch("papyrus_content.publication.resolve_catalog_corpus", return_value=(corpus_config, None)):
        return cli.plan_reference_catalog_registration(client, {"catalog": "catalog.json", "status": "pending", "skip-existing": skip_existing})


def through_citation_graph(client: RecordingMemory, address: str, *, corpus: str = FIRST_CORPUS) -> dict[str, Any]:
    from papyrus_content.reference_identity import IdentityIndex
    from papyrus_content.reference_url_text import _resolve_or_build_cited_reference_record

    corpus_id, _ = corpus_of(corpus)
    return _resolve_or_build_cited_reference_record(citation={"title": "A cited paper", "url": address}, corpus_id=corpus_id, existing_lookup={}, now=NOW,
                                                    identity_index=IdentityIndex(client.list_records("Reference")))


def created_references(client: RecordingMemory) -> list[dict[str, Any]]:
    return [row for row in client.references() if not str(row["id"]).startswith("reference-held-")]
