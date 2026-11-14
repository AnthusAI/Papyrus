from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from . import commands
from .commands_test import HUB_CORPUS, client, routed_story, run, snapshot_to, with_published_rows  # noqa: F401
from .reference_documents import ReferenceText, biblicus_reference_id, export_reference_documents, load_reference_documents, read_documents_file


def reference(client, name: str, *, status="accepted", corpus=HUB_CORPUS, state="current", published="2026-09-10T00:00:00Z", **extra) -> None:
    row = {
        "id": f"reference-{name}", "lineageId": f"lineage-{name}", "versionState": state, "corpusId": corpus, "curationStatus": status,
        "sourceUri": f"https://example.org/{name}.pdf", "title": f"Paper {name}", **extra,
    }
    if published:
        row["sourcePublishedAt"] = published
    client.rows.setdefault("Reference", {})[row["id"]] = row


class FakeStore:
    def __init__(self, texts: dict[str, tuple[str, str]]) -> None:
        self.texts = texts  # reference id -> (etag, text)
        self.reads: list[str] = []

    def list_texts(self):
        return {name: ReferenceText(f"corpora/k/extracted/markitdown/raw/{name}/extracted_text_raw.md", etag) for name, (etag, _) in self.texts.items()}

    def read(self, text):
        name = text.key.split("/")[-2]
        self.reads.append(name)
        return self.texts[name][1]


def front_matter_of(path: Path) -> tuple[dict, str]:
    head, _, body = path.read_text(encoding="utf-8")[4:].partition("\n---\n")
    return yaml.safe_load(head), body


@pytest.fixture
def corpus(client):
    with_published_rows(client)
    reference(client, "paper", published="2026-09-10T09:00:00Z")
    reference(client, "undated", published=None)
    reference(client, "stub")  # a citation-graph stub: a title and no extracted text
    reference(client, "refused", status="rejected")
    reference(client, "elsewhere", corpus="knowledge-corpus-other")
    reference(client, "old", state="superseded")
    reference(client, "delivered", discoveredByMonitorId="hn")
    return client


def texts_for(*names: str) -> dict[str, tuple[str, str]]:
    return {f"reference-{name}": (f"etag-{name}", f"Body of {name}. Acme builds Tern.") for name in names}


ALL_TEXTS = texts_for("paper", "undated", "refused", "elsewhere", "old", "delivered")


def test_a_reference_with_text_is_a_document_and_a_stub_a_rejected_one_a_monitor_record_and_another_corpus_are_not(corpus):
    documents, left = load_reference_documents(corpus, corpus_id=HUB_CORPUS, texts=FakeStore(ALL_TEXTS).list_texts())
    assert [document.reference_id for document in documents] == ["reference-paper", "reference-undated"]
    assert left == {"stubs": 1, "monitor": 1, "rejected": 1}
    paper, undated = documents
    assert (paper.lineage_id, paper.url, paper.title, paper.published_at) == ("lineage-paper", "https://example.org/paper.pdf", "Paper paper", "2026-09-10T09:00:00Z")
    assert undated.published_at is None


def test_a_document_file_carries_what_biblicus_reads_and_what_the_wiki_cites(corpus, tmp_path):
    documents, _ = load_reference_documents(corpus, corpus_id=HUB_CORPUS, texts=FakeStore(ALL_TEXTS).list_texts())
    files, counts = export_reference_documents(documents, FakeStore(ALL_TEXTS), tmp_path)
    assert counts == {"downloaded": 2, "reused": 0, "empty": 0}
    write_files(tmp_path, files)
    meta, body = front_matter_of(tmp_path / "ref-reference-paper.md")
    assert meta["biblicus"] == {"id": biblicus_reference_id("reference-paper")}
    assert (meta["papyrus_reference_id"], meta["kind"], meta["url"], meta["source_etag"]) == ("reference-paper", "reference-document", "https://example.org/paper.pdf", "etag-paper")
    assert meta["dates"] == {"published_at": "2026-09-10T09:00:00Z"}
    assert body == "# Paper paper\n\nBody of paper. Acme builds Tern.\n"
    undated, _ = front_matter_of(tmp_path / "ref-reference-undated.md")
    assert "dates" not in undated


def write_files(directory: Path, files) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for file in files:
        (directory / file.file).write_text(file.text, encoding="utf-8")


def test_a_text_whose_etag_is_unchanged_is_not_downloaded_again_and_a_changed_one_is(corpus, tmp_path):
    texts = texts_for("paper", "undated")
    documents, _ = load_reference_documents(corpus, corpus_id=HUB_CORPUS, texts=FakeStore(texts).list_texts())
    first = FakeStore(texts)
    write_files(tmp_path, export_reference_documents(documents, first, tmp_path)[0])
    assert sorted(first.reads) == ["reference-paper", "reference-undated"]
    before = (tmp_path / "ref-reference-paper.md").read_text()

    second = FakeStore(texts)
    files, counts = export_reference_documents(documents, second, tmp_path)
    assert second.reads == [] and counts == {"downloaded": 0, "reused": 2, "empty": 0}
    assert [file.text for file in files if file.item_id == "reference-paper"] == [before]

    texts["reference-paper"] = ("etag-new", "A revised paper.")
    documents, _ = load_reference_documents(corpus, corpus_id=HUB_CORPUS, texts=FakeStore(texts).list_texts())
    third = FakeStore(texts)
    files, counts = export_reference_documents(documents, third, tmp_path)
    assert third.reads == ["reference-paper"] and counts["reused"] == 1
    assert "A revised paper." in next(file.text for file in files if file.item_id == "reference-paper")


def test_a_text_with_nothing_in_it_is_not_a_document(corpus, tmp_path):
    texts = {**texts_for("paper"), "reference-undated": ("etag-undated", "   \n")}
    documents, _ = load_reference_documents(corpus, corpus_id=HUB_CORPUS, texts=FakeStore(texts).list_texts())
    files, counts = export_reference_documents(documents, FakeStore(texts), tmp_path)
    assert [file.item_id for file in files] == ["reference-paper"] and counts["empty"] == 1


def export(tmp_path, monkeypatch, store, *flags):
    monkeypatch.setattr(commands, "S3TextStore", lambda bucket, key, extractor: store)
    out = tmp_path / "raw"
    documents = tmp_path / "run" / "reference-documents.json"
    run(
        commands.knowledge_corpus_export, "--out", str(out), "--corpus-key", "shipped", "--reference-documents-bucket", "media",
        "--reference-documents-out", str(documents), *flags,
    )
    return out, documents


def test_the_export_writes_the_documents_beside_the_items_removes_the_ones_that_left_and_keeps_the_list_for_later_stages(corpus, tmp_path, monkeypatch, capsys):
    out, documents = export(tmp_path, monkeypatch, FakeStore(ALL_TEXTS))
    assert sorted(path.name for path in out.glob("ref-*.md")) == ["ref-reference-paper.md", "ref-reference-undated.md"]
    assert len(list(out.glob("item-*.md"))) == 2
    assert "2 reference documents (2 downloaded, 0 unchanged, 1 without text)" in capsys.readouterr().out
    assert [d.reference_id for d in read_documents_file(documents)] == ["reference-paper", "reference-undated"]

    corpus.rows["Reference"]["reference-paper"]["curationStatus"] = "rejected"
    out, _ = export(tmp_path, monkeypatch, FakeStore(ALL_TEXTS))
    assert sorted(path.name for path in out.glob("ref-*.md")) == ["ref-reference-undated.md"]


def test_the_export_without_the_option_writes_no_reference_documents(corpus, tmp_path):
    out = tmp_path / "raw"
    run(commands.knowledge_corpus_export, "--out", str(out))
    assert not list(out.glob("ref-*.md"))


def test_the_option_needs_a_corpus_key(corpus, tmp_path):
    with pytest.raises(ValueError, match="--reference-documents-bucket needs --corpus-key"):
        run(commands.knowledge_corpus_export, "--out", str(tmp_path / "raw"), "--reference-documents-bucket", "media")


def test_records_stay_data_while_references_with_text_are_documents(corpus, tmp_path, monkeypatch):
    routed_story(corpus, "cloning", "Show HN: Voice cloning", "2026-10-14T09:00:00Z")
    out, _ = export(
        tmp_path, monkeypatch, FakeStore(ALL_TEXTS), "--monitor-sources", "routed", "--as-of", "2026-10-19", "--monitor-records-out", str(tmp_path / "run" / "monitor-records.json"),
    )
    assert not list(out.glob("record-*.md"))
    assert sorted(path.name for path in out.glob("ref-*.md")) == ["ref-reference-paper.md", "ref-reference-undated.md"]


def typed_run(tmp_path: Path) -> Path:
    entities = {
        "schema_version": 1,
        "items": [
            {
                "item_id": biblicus_reference_id("reference-paper"),
                "entities": [{"id": "e1", "kind": "model", "text": "Tern 3", "state": "proposed", "span": {"start": 0, "end": 6}, "score": 0.9}],
                "relations": [],
            },
        ],
    }
    path = tmp_path / "entities.json"
    path.write_text(json.dumps(entities))
    return path


def test_an_entity_extracted_from_a_reference_document_is_a_mention_from_that_reference_and_counts_in_the_snapshot_once_accepted(corpus, tmp_path, monkeypatch):
    out, documents = export(tmp_path, monkeypatch, FakeStore(ALL_TEXTS))
    run(commands.knowledge_publish_run, "--apply")
    flags = ("--entities", str(typed_run(tmp_path)), "--reference-documents", str(documents), "--apply")
    run(commands.knowledge_publish_run, *flags)
    mentions = [row for row in corpus.rows["SemanticRelation"].values() if row["subjectKind"] == "reference"]
    assert len(mentions) == 1
    mention = mentions[0]
    assert (mention["subjectId"], mention["subjectLineageId"], mention["predicate"]) == ("reference-paper", "lineage-paper", "mentions")
    metadata = json.loads(mention["metadata"])
    assert (metadata["kind"], metadata["linkSource"], metadata["confirmed"]) == ("knowledge.reference_mention", "extractor", False)
    node = next(row for row in corpus.rows["SemanticNode"].values() if row["displayName"] == "Tern 3")
    assert node["status"] == "generated"

    run(commands.knowledge_publish_run, *flags)  # again: nothing is written twice
    assert len([row for row in corpus.rows["SemanticRelation"].values() if row["subjectKind"] == "reference"]) == 1

    run(commands.knowledge_entities_accept, "--key", node["nodeKey"], "--actor", "ai")
    confirmed = json.loads(corpus.rows["SemanticRelation"][mention["id"]]["metadata"])
    assert confirmed["confirmed"] is True

    site = snapshot_to(tmp_path, monkeypatch, "--entity-href", "/wiki/{slug}/", "--reference-documents", str(documents))
    entity = json.loads((site / "_data/knowledge/entities" / f"{node['nodeKey']}.json").read_text())
    assert [(item["title"], item["url"]) for item in entity["relatedItems"]] == [("Paper paper", "https://example.org/paper.pdf")]
    assert entity["href"] is not None  # a Reference document is a page-bearing source, unlike a monitor record

    plain = snapshot_to(tmp_path / "plain", monkeypatch)
    assert not (plain / "_data/knowledge/entities" / f"{node['nodeKey']}.json").exists()  # without the option the Reference counts for nothing
