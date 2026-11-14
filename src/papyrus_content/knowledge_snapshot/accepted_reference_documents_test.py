from __future__ import annotations

import json
from pathlib import Path

import pytest

from ..model_attachments import model_attachment_id
from ..reference_curation_store import BODY_ROLE, CARD_SORT_KEY, TEXT_SORT_KEY, card_id
from . import commands, reference_documents
from .commands_test import HUB_CORPUS, client, routed_story, run, with_published_rows  # noqa: F401
from .reference_documents import biblicus_reference_id, read_documents_file
from .reference_documents_test import front_matter_of, reference

TEXTS: dict[str, str] = {}


def attach_text(client, name: str, text: str | None, *, sort_key: str = TEXT_SORT_KEY, with_path: bool = True) -> None:
    attachment_id = model_attachment_id("reference", f"reference-{name}", BODY_ROLE, sort_key)
    client.rows.setdefault("ModelAttachment", {})[attachment_id] = {
        "id": attachment_id, "ownerKind": "reference", "ownerId": f"reference-{name}", "sortKey": sort_key,
        "storagePath": f"newsroom/payloads/reference/reference-{name}/metadata/{sort_key}.md" if with_path else None,
        "sha256": f"sha-{name}-{sort_key}-{len(text or '')}",
    }
    TEXTS[attachment_id] = text if text is not None else ""


@pytest.fixture
def accepted_corpus(client, monkeypatch):
    TEXTS.clear()
    with_published_rows(client)
    reference(client, "paper", published="2026-09-10T09:00:00Z")
    reference(client, "delivered", discoveredByMonitorId="hn", published="2026-10-10T09:00:00Z")
    reference(client, "textless")
    reference(client, "blank")
    reference(client, "broken")
    reference(client, "waiting", status="pending")
    reference(client, "refused", status="rejected")
    reference(client, "elsewhere", corpus="knowledge-corpus-other")
    reference(client, "superseded", state="superseded")
    for name in ("paper", "waiting", "refused", "elsewhere", "superseded"):
        attach_text(client, name, f"Body of {name}. Acme released Tern 3.")
    attach_text(client, "delivered", "Delivered by a monitor and accepted. Acme released Tern 3.")
    attach_text(client, "blank", "  \n")
    attach_text(client, "broken", "never read")
    client.rows["ModelAttachment"][model_attachment_id("reference", "reference-textless", BODY_ROLE, TEXT_SORT_KEY)] = {
        "id": model_attachment_id("reference", "reference-textless", BODY_ROLE, TEXT_SORT_KEY), "storagePath": None, "sha256": "",
    }
    broken_id = model_attachment_id("reference", "reference-broken", BODY_ROLE, TEXT_SORT_KEY)
    reads: list[str] = []

    def download(_client, attachment):
        reads.append(attachment["id"])
        if attachment["id"] == broken_id and TEXTS.get("broken-fails"):
            raise RuntimeError("storage said no")
        return TEXTS[attachment["id"]].encode("utf-8")

    monkeypatch.setattr(reference_documents, "download_attachment_buffer", download)
    client.reads = reads
    return client


def export(tmp_path, *flags):
    out = tmp_path / "raw"
    documents = tmp_path / "run" / "reference-documents.json"
    run(commands.knowledge_corpus_export, "--out", str(out), "--corpus-key", "shipped", "--reference-documents-accepted", "--reference-documents-out", str(documents), *flags)
    return out, documents


def test_every_accepted_reference_is_a_document_whatever_monitor_delivered_it_and_pending_and_rejected_ones_never_are(accepted_corpus, tmp_path):
    out, documents = export(tmp_path)
    assert sorted(path.name for path in out.glob("ref-*.md")) == ["ref-reference-broken.md", "ref-reference-delivered.md", "ref-reference-paper.md"]
    assert [d.reference_id for d in read_documents_file(documents)] == ["reference-broken", "reference-delivered", "reference-paper"]
    meta, body = front_matter_of(out / "ref-reference-delivered.md")
    assert meta["biblicus"] == {"id": biblicus_reference_id("reference-delivered")} and meta["papyrus_reference_id"] == "reference-delivered"
    assert body == "# Paper delivered\n\nDelivered by a monitor and accepted. Acme released Tern 3.\n"


def test_the_text_is_the_curation_text_and_an_editors_corrected_text_wins(accepted_corpus, tmp_path):
    attach_text(accepted_corpus, "paper", "The editor corrected this.", sort_key="curation-edit-0001-text")
    paper = accepted_corpus.rows["Reference"]["reference-paper"]
    accepted_corpus.rows["ReferenceAttachment"] = {
        card_id(paper): {"id": card_id(paper), "sortKey": CARD_SORT_KEY, "metadata": json.dumps({"kind": "reference-curation", "current": {"textSortKey": "curation-edit-0001-text"}})}
    }
    out, _ = export(tmp_path)
    assert front_matter_of(out / "ref-reference-paper.md")[1] == "# Paper paper\n\nThe editor corrected this.\n"
    assert front_matter_of(out / "ref-reference-delivered.md")[1].startswith("# Paper delivered\n\nDelivered by a monitor")


def test_a_reference_with_no_text_is_listed_by_id_and_reason_and_not_silently_dropped(accepted_corpus, tmp_path, capsys):
    export(tmp_path)
    lines = [line.split("\t") for line in capsys.readouterr().out.splitlines() if "reference-without-text" in line]
    reasons = {line[3]: line[4] for line in lines}
    assert set(reasons) == {"reference-textless", "reference-blank"}
    assert "no curation text attachment" in reasons["reference-textless"] and "empty" in reasons["reference-blank"]


def test_the_report_is_in_the_json_output_and_in_the_documents_file(accepted_corpus, tmp_path, capsys):
    _, documents = export(tmp_path, "--json")
    report = json.loads(capsys.readouterr().out)
    assert {entry["referenceId"] for entry in report["referenceWithoutText"]} == {"reference-textless", "reference-blank"}
    assert report["referenceDocuments"] == 3 and report["referenceLeftStubs"] == 2
    assert {entry["referenceId"] for entry in json.loads(documents.read_text())["withoutText"]} == {"reference-textless", "reference-blank"}


def test_zero_documents_is_an_error_that_removes_nothing(accepted_corpus, tmp_path):
    out, documents = export(tmp_path)
    before = {path.name: path.read_text() for path in out.glob("*.md")}
    for row in accepted_corpus.rows["Reference"].values():
        row["curationStatus"] = "pending"
    with pytest.raises(ValueError, match="found no accepted Reference with a text to read"):
        export(tmp_path)
    assert {path.name: path.read_text() for path in out.glob("*.md")} == before
    assert len(read_documents_file(documents)) == 3


def test_an_accepted_reference_whose_listing_came_back_empty_keeps_its_earlier_file(accepted_corpus, tmp_path):
    out, _ = export(tmp_path)
    del accepted_corpus.rows["ModelAttachment"][model_attachment_id("reference", "reference-paper", BODY_ROLE, TEXT_SORT_KEY)]
    TEXTS["broken-fails"] = "yes"
    export(tmp_path)
    assert (out / "ref-reference-paper.md").exists(), "still accepted: its text is recoverable, so its file stays"
    assert (out / "ref-reference-broken.md").exists()
    accepted_corpus.rows["Reference"]["reference-paper"]["curationStatus"] = "rejected"
    export(tmp_path)
    assert not (out / "ref-reference-paper.md").exists(), "no longer accepted: the file goes"


def test_an_unreadable_text_is_reported_with_its_reason_and_does_not_fail_the_export(accepted_corpus, tmp_path, capsys):
    TEXTS["broken-fails"] = "yes"
    out, _ = export(tmp_path, "--json")
    report = json.loads(capsys.readouterr().out)
    broken = next(entry for entry in report["referenceWithoutText"] if entry["referenceId"] == "reference-broken")
    assert "could not be read" in broken["reason"] and "RuntimeError" in broken["reason"]
    assert not (out / "ref-reference-broken.md").exists()


def test_a_text_that_did_not_change_is_not_downloaded_again(accepted_corpus, tmp_path):
    export(tmp_path)
    accepted_corpus.reads.clear()
    export(tmp_path)
    assert accepted_corpus.reads == [model_attachment_id("reference", "reference-blank", BODY_ROLE, TEXT_SORT_KEY)]  # only the empty one is looked at again


def test_the_option_needs_a_corpus_key_and_does_not_mix_with_the_bucket_selection(accepted_corpus, tmp_path):
    with pytest.raises(ValueError, match="--reference-documents-accepted needs --corpus-key"):
        run(commands.knowledge_corpus_export, "--out", str(tmp_path / "raw"), "--reference-documents-accepted")
    with pytest.raises(ValueError, match="not both"):
        run(commands.knowledge_corpus_export, "--out", str(tmp_path / "raw"), "--corpus-key", "shipped", "--reference-documents-accepted", "--reference-documents-bucket", "media")


def test_the_export_without_the_option_writes_no_reference_documents(accepted_corpus, tmp_path):
    out = tmp_path / "raw"
    run(commands.knowledge_corpus_export, "--out", str(out), "--corpus-key", "shipped")
    assert not list(out.glob("ref-*.md"))


def typed_run(tmp_path: Path, reference_id: str) -> Path:
    entities = {
        "schema_version": 1,
        "items": [
            {
                "item_id": biblicus_reference_id(reference_id),
                "entities": [{"id": "e1", "kind": "model", "text": "Tern 3", "state": "proposed", "span": {"start": 0, "end": 6}, "score": 0.9}],
                "relations": [],
            },
        ],
    }
    path = tmp_path / "entities.json"
    path.write_text(json.dumps(entities))
    return path


def test_an_accepted_monitor_delivered_reference_is_a_document_not_a_record_and_ends_with_a_mention_of_a_concept_extracted_from_it(accepted_corpus, tmp_path):
    routed_story(accepted_corpus, "pending-story", "Show HN: Something pending", "2026-10-14T09:00:00Z")
    records = tmp_path / "run" / "monitor-records.json"
    out, documents = export(tmp_path, "--monitor-sources", "routed", "--as-of", "2026-10-19", "--monitor-records-out", str(records))
    delivered = {entry["referenceId"] for entry in json.loads(records.read_text())["records"]}
    assert "reference-delivered" not in delivered and "reference-pending-story" in delivered, "an accepted Reference is a document; counted as a record too it would hide its entities' pages"

    run(commands.knowledge_publish_run, "--apply")
    flags = ("--entities", str(typed_run(tmp_path, "reference-delivered")), "--reference-documents", str(documents), "--monitor-records", str(records), "--apply")
    run(commands.knowledge_publish_run, *flags)
    node = next(row for row in accepted_corpus.rows["SemanticNode"].values() if row["displayName"] == "Tern 3")
    mentions = [row for row in accepted_corpus.rows["SemanticRelation"].values() if row["objectLineageId"] == node["lineageId"] and row["predicate"] == "mentions"]
    assert [(row["subjectKind"], row["subjectId"], row["subjectLineageId"]) for row in mentions] == [("reference", "reference-delivered", "lineage-delivered")]
    assert json.loads(mentions[0]["metadata"])["kind"] == "knowledge.reference_mention"
    run(commands.knowledge_publish_run, *flags)
    assert len([row for row in accepted_corpus.rows["SemanticRelation"].values() if row["objectLineageId"] == node["lineageId"]]) == 1, "again: nothing is written twice"
