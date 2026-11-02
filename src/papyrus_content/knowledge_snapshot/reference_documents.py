"""References whose extracted text is a corpus document (``knowledgeRun.referenceDocuments``, docs/knowledge-cloud-run.md).

A site that opts in makes its corpus's own References, the PDFs and pages a person or an importer added, the documents its wiki and
concepts are built from. This is a different, explicit source from the monitor records (``monitor_records.py``): a record is data for counts
and is never a document; a **Reference document** is a Reference that has extracted text, and it is a corpus document like a published item.

* ``corpus export --reference-documents-bucket B`` lists the extracted texts under ``corpora/<corpus key>/extracted/<extractor>/raw/`` once,
  reads the Reference rows of the corpus, and writes ``ref-<reference id>.md`` for each current, not rejected, not monitor-delivered Reference
  that has a non-empty text. A Reference with no text (a citation-graph stub: a title and nothing else) is not a document.
* **Incremental.** The file records the S3 ETag of the text it was made from (``source_etag``). The corpus (with ``raw/papyrus``) is kept in
  the state bucket between runs, so a text whose ETag is unchanged is not downloaded again.
* ``--reference-documents-out FILE`` keeps the documents (id, lineage id, title, address, source date) for the later stages, which read it with
  ``--reference-documents``: ``publish-run`` turns the Biblicus ids back into Reference ids and links extracted entities from the Reference
  (``subjectKind`` ``reference``); the snapshot, the archive and the wiki count the Reference as a dated item that cites its address.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from ..ids import deterministic_uuid
from ..reference_policy import normalize_policy_token
from .corpus_export import REFERENCE_MARKER, ExportedItem
from .model import KIND_REFERENCE_DOCUMENT, PublishedItem
from .monitor_records import EXCLUDED_STATES, discovery_monitor_id
from .weeks import iso_timestamp

MARKER = REFERENCE_MARKER
SCHEMA_VERSION = 1
TEXT_FILE = "extracted_text_raw.md"
DEFAULT_EXTRACTOR = "markitdown"


@dataclass(frozen=True)
class ReferenceText:
    """Where a Reference's extracted text is and which version of it that is."""

    key: str
    etag: str


class TextStore(Protocol):
    def list_texts(self) -> dict[str, ReferenceText]:
        """Reference id to its extracted text."""

    def read(self, text: ReferenceText) -> str: ...


class S3TextStore:
    """The extracted texts of a corpus in the media bucket: ``corpora/<corpus key>/extracted/<extractor>/raw/<reference id>/extracted_text_raw.md``."""

    def __init__(self, bucket: str, corpus_key: str, extractor: str = DEFAULT_EXTRACTOR, client: Any = None) -> None:
        if client is None:
            import boto3  # noqa: PLC0415

            client = boto3.client("s3")
        self.bucket, self.client = bucket, client
        self.prefix = f"corpora/{corpus_key}/extracted/{extractor}/raw/"

    def list_texts(self) -> dict[str, ReferenceText]:
        found: dict[str, ReferenceText] = {}
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self.prefix):
            for entry in page.get("Contents", []):
                reference_id, _, name = entry["Key"][len(self.prefix):].partition("/")
                if reference_id and name == TEXT_FILE:
                    found[reference_id] = ReferenceText(entry["Key"], str(entry.get("ETag") or "").strip('"'))
        return found

    def read(self, text: ReferenceText) -> str:
        return self.client.get_object(Bucket=self.bucket, Key=text.key)["Body"].read().decode("utf-8", errors="replace")


@dataclass(frozen=True)
class ReferenceDocument:
    reference_id: str
    lineage_id: str
    title: str
    url: str
    published_at: str | None
    text: ReferenceText

    def to_dict(self) -> dict[str, Any]:
        return {"referenceId": self.reference_id, "lineageId": self.lineage_id, "title": self.title, "url": self.url, "publishedAt": self.published_at}

    def as_item(self) -> PublishedItem:
        """The document as the snapshot builder counts it: a dated item (a page-bearing source, unlike a monitor record) that cites the Reference's address."""
        return PublishedItem(
            key=self.lineage_id, item_id=self.reference_id, title=self.title, url=self.url or None, published_at=self.published_at,
            kind=KIND_REFERENCE_DOCUMENT, source="reference",
        )


def biblicus_reference_id(reference_id: str) -> str:
    """The Biblicus id of a Reference document: the same UUID on every export."""
    return deterministic_uuid(f"papyrus-reference:{reference_id}")


def load_reference_documents(client: Any, *, corpus_id: str, texts: Mapping[str, ReferenceText]) -> tuple[list[ReferenceDocument], dict[str, int]]:
    """The corpus's current References that have extracted text, ordered by id, and what was left out (``stubs``: no text, ``monitor``: a
    monitor delivered it, so it is a record, ``rejected``)."""
    left = {"stubs": 0, "monitor": 0, "rejected": 0}
    documents: list[ReferenceDocument] = []
    for row in client.list_records("Reference"):
        if row.get("corpusId") != corpus_id or row.get("versionState") not in (None, "current"):
            continue
        text = texts.get(str(row.get("id"))) or texts.get(str(row.get("lineageId") or ""))
        if text is None:
            left["stubs"] += 1
        elif discovery_monitor_id(row):
            left["monitor"] += 1  # records are data and never documents (docs/knowledge-cloud-run.md)
        elif normalize_policy_token(row.get("curationStatus")) in EXCLUDED_STATES:
            left["rejected"] += 1
        else:
            url = str(row.get("sourceUri") or "")
            published = None
            try:
                published = iso_timestamp(str(row["sourcePublishedAt"])) if row.get("sourcePublishedAt") else None
            except (TypeError, ValueError):
                published = None
            documents.append(
                ReferenceDocument(str(row["id"]), str(row.get("lineageId") or row["id"]), str(row.get("title") or url or row["id"]).strip(), url, published, text)
            )
    return sorted(documents, key=lambda document: document.reference_id), left


def _front_matter(text: str) -> dict:
    if not text.startswith("---\n"):
        return {}
    head, _, _ = text[4:].partition("\n---\n")
    try:
        meta = yaml.safe_load(head)
    except yaml.YAMLError:
        return {}
    return meta if isinstance(meta, dict) else {}


def render_reference_document(document: ReferenceDocument, body: str) -> ExportedItem:
    meta: dict[str, Any] = {
        "title": document.title,
        "biblicus": {"id": biblicus_reference_id(document.reference_id)},
        "papyrus_reference_id": document.reference_id,
        "kind": KIND_REFERENCE_DOCUMENT,
        "url": document.url,
        "source_etag": document.text.etag,
    }
    if document.published_at:
        meta["dates"] = {"published_at": document.published_at}
        meta["date_provenance"] = {"published_at": "reference-source-published-at"}
    meta = {key: value for key, value in meta.items() if value not in (None, "")}
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000).strip()
    heading = f"# {document.title}\n\n" if document.title and not body.lstrip().startswith("# ") else ""
    return ExportedItem(
        item_id=document.reference_id, biblicus_id=meta["biblicus"]["id"], file=f"ref-{document.reference_id}.md", slug="", url=document.url or None,
        title=document.title, published_at=document.published_at, text=f"---\n{front}\n---\n{heading}{body.strip()}\n",
    )


def export_reference_documents(
    documents: Iterable[ReferenceDocument], store: TextStore, out: Path, *, on_progress: Callable[[int, int], None] | None = None,
) -> tuple[list[ExportedItem], dict[str, int]]:
    """One corpus file per document. A text whose ETag the file in ``out`` already records is read from that file, not downloaded again;
    a text that is empty is not a document."""
    documents = list(documents)
    files: list[ExportedItem] = []
    counts = {"downloaded": 0, "reused": 0, "empty": 0}
    for number, document in enumerate(documents, 1):
        existing = out / f"ref-{document.reference_id}.md"
        body = None
        if existing.exists():
            old = existing.read_text(encoding="utf-8")
            if _front_matter(old).get("source_etag") == document.text.etag and document.text.etag:
                body = old.partition("\n---\n")[2]
                counts["reused"] += 1
        if body is None:
            body = store.read(document.text)
            counts["downloaded"] += 1
        if not body.strip():
            counts["empty"] += 1
            continue
        files.append(render_reference_document(document, _strip_heading(body, document.title)))
        if on_progress is not None and number % 250 == 0:
            on_progress(number, len(documents))
    return files, counts


def _strip_heading(body: str, title: str) -> str:
    """A text read back from an earlier file starts with the heading the export added; the title is added again from the Reference."""
    heading = f"# {title}\n\n"
    return body[len(heading):] if title and body.startswith(heading) else body


def write_documents_file(path: Path, documents: list[ReferenceDocument]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schemaVersion": SCHEMA_VERSION, "referenceDocuments": [d.to_dict() for d in documents]}, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def read_documents_file(path: Path | str) -> list[ReferenceDocument]:
    """The documents the export kept (without their text location: the later stages never read the text)."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return sorted(
            (
                ReferenceDocument(str(e["referenceId"]), str(e["lineageId"]), str(e["title"]), str(e.get("url") or ""), e.get("publishedAt"), ReferenceText("", ""))
                for e in raw["referenceDocuments"]
            ),
            key=lambda document: document.reference_id,
        )
    except OSError as error:
        raise ValueError(f"Cannot read --reference-documents {path}: {error.strerror or error}") from error
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{path} is not a reference documents file: {error}") from error
