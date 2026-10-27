"""Monitor-delivered References as data for the Knowledge Map (``knowledge.monitorSources``, docs/knowledge-cloud-run.md).

A monitor (docs/monitoring-cloud.md) delivers pending ``Reference`` rows: a Hugging Face Hub model, say. Such a row is a
**monitor record**. It counts in the weekly Knowledge Map (entities and their weekly trends; not the topic model's clusters) and is never a page: it is
not a published item, the wiki sync makes no page for an entity only records mention, and the projection never sees it.
Notable records are promoted by a person to normal items (``papyrus references promote``).

``load_monitor_records`` reads the records of a publication from the backend once (the weekly run's ``corpus-sync``
stage) and ``write_records`` keeps them in a JSON file; every later command reads that file (``--monitor-records``), so
the dating, the counts and the entities of one run agree and no later stage scans the backend again.

* A record is dated by the source's own date (``createdAt`` of the model), so a 12-month backfill gives real weekly history.
* Rejected References are left out; any other curation state counts.
* The Hub's structured fields ride in the ``details`` of the relation that links the provenance Message to the Reference
  (``monitoring_intake.py``), so reading a record is one indexed query, not a download.
* Entities and relations of a record come from its structured fields, deterministically (``monitor_import.py``).
* A **routed** record (source ``routed``) is any other Reference a monitor delivered to the site (its provenance relation names the
  ``monitorId``, e.g. ``hn``). It has no structured fields: its title is matched against the entities already accepted on the map.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..categories_steering import semantic_state_key
from ..ids import deterministic_uuid
from ..reference_policy import normalize_policy_token
from .model import KIND_MONITOR_RECORD, PublishedItem
from .parallel import map_with_clients
from .weeks import iso_timestamp, parse_day

SOURCE_HUGGINGFACE = "huggingface"
SOURCE_ROUTED = "routed"  # the source name in ``monitorSources`` for any monitor's routed References (Hacker News, later RSS, arXiv); a record's own ``source`` is its monitor id
SOURCES = (SOURCE_HUGGINGFACE, SOURCE_ROUTED)
HUB_HOST = "huggingface.co"
PROVENANCE = {SOURCE_HUGGINGFACE: "from the Hugging Face Hub"}
RATIONALE_PREDICATE = "ingestion_rationale"
SCHEMA_VERSION = 1
EXCLUDED_STATES = frozenset({"rejected", "reject", "declined", "decline", "discarded"})
GENERIC_LICENCES = frozenset({"other", "unknown"})
SUMMARY_LIMIT = 300
MARKER = "papyrus_record_id:"


@dataclass(frozen=True)
class MonitorRecord:
    reference_id: str
    lineage_id: str
    source: str
    url: str
    title: str
    created_at: str
    details: dict[str, Any]
    state: str = "pending"

    @property
    def model_id(self) -> str:
        return str(self.details.get("modelId") or self.title)

    @property
    def provenance(self) -> str:
        return provenance_of(self.source)

    @property
    def routed(self) -> bool:
        """A record some monitor routed to the site (``routed`` source), as opposed to a Hub model with structured fields."""
        return self.source != SOURCE_HUGGINGFACE

    @property
    def text(self) -> str:
        """The free text of a routed record that entities are matched in: its title and, when the source stored one, its summary or excerpt."""
        return " ".join(part for part in (self.title, str(self.details.get("summary") or ""), str(self.details.get("excerpt") or "")) if part)

    def to_dict(self) -> dict[str, Any]:
        return {
            "referenceId": self.reference_id, "lineageId": self.lineage_id, "source": self.source, "url": self.url,
            "title": self.title, "createdAt": self.created_at, "state": self.state, "details": self.details,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "MonitorRecord":
        return cls(
            reference_id=str(raw["referenceId"]), lineage_id=str(raw["lineageId"]), source=str(raw["source"]), url=str(raw["url"]),
            title=str(raw["title"]), created_at=str(raw["createdAt"]), details=dict(raw.get("details") or {}), state=str(raw.get("state") or "pending"),
        )


def provenance_of(source: str) -> str:
    """Where a record is from, in words: the Hub, or the monitor that routed it (``from the hn monitor``)."""
    return PROVENANCE.get(source) or f"routed from the {source} monitor"


def parse_sources(value: Any) -> tuple[str, ...]:
    """``huggingface`` or a comma separated list of sources; anything not supported is refused."""
    names = [part.strip().lower() for part in str(value or "").split(",") if part.strip()]
    unknown = [name for name in names if name not in SOURCES]
    if unknown:
        raise ValueError(f"Unsupported monitor source {unknown[0]!r}; supported: {', '.join(SOURCES)}.")
    return tuple(dict.fromkeys(names))


def biblicus_record_id(reference_id: str) -> str:
    """The Biblicus id of a record's corpus document: the same UUID on every export."""
    return deterministic_uuid(f"papyrus-record:{reference_id}")


def _source_of(row: Mapping[str, Any], sources: tuple[str, ...] = (SOURCE_HUGGINGFACE,)) -> str | None:
    host = (urlparse(str(row.get("sourceUri") or "")).hostname or "").lower()
    if host == HUB_HOST and SOURCE_HUGGINGFACE in sources:
        return SOURCE_HUGGINGFACE
    return SOURCE_ROUTED if SOURCE_ROUTED in sources else None


def _monitor_id(rows: Iterable[Mapping[str, Any]]) -> str:
    """The ``monitorId`` of the newest provenance relation that names one: which monitor routed the Reference ('' when none did)."""
    found: list[tuple[str, str]] = []
    for row in rows:
        if row.get("predicate") != RATIONALE_PREDICATE or row.get("relationState", "current") != "current":
            continue
        metadata = row.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except ValueError:
                continue
        if isinstance(metadata, dict) and metadata.get("monitorId"):
            found.append((str(row.get("importedAt") or row.get("createdAt") or ""), str(metadata["monitorId"])))
    return max(found)[1] if found else ""


def _details_from_relations(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The ``details`` of the newest provenance relation that carries them (a new revision of a model adds another)."""
    found: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        if row.get("predicate") != RATIONALE_PREDICATE or row.get("relationState", "current") != "current":
            continue
        metadata = row.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except ValueError:
                continue
        details = metadata.get("details") if isinstance(metadata, dict) else None
        if isinstance(details, dict):
            found.append((str(row.get("importedAt") or row.get("createdAt") or ""), details))
    return max(found, key=lambda pair: pair[0])[1] if found else {}


def _fallback_details(row: Mapping[str, Any], url: str) -> dict[str, Any]:
    """What the Reference alone says about a Hub model, for one delivered before the details rode on the relation."""
    model_id = urlparse(url).path.strip("/")
    return {"modelId": model_id, "author": model_id.partition("/")[0], "createdAt": str(row.get("sourcePublishedAt") or ""), "baseModels": []}


def load_monitor_records(
    client: Any, *, corpus_id: str, sources: tuple[str, ...], as_of: date, weeks: int | None = None,
    workers: int = 1, client_factory: Any = None,
) -> tuple[list[MonitorRecord], list[str]]:
    """The records of a publication dated up to the end of ``as_of``'s week, newest first, and warnings. All history by default: there is no
    lower bound and no cap on how many. ``weeks`` (optional) limits how far back a record counts, by its source date.
    Each record costs one indexed query (its provenance relation); with ``workers`` above 1 and a ``client_factory`` they run over that many clients."""
    since = as_of - timedelta(weeks=weeks) if weeks is not None else None
    until = as_of + timedelta(days=6)
    warnings: list[str] = []
    chosen: list[tuple[date, Mapping[str, Any], str]] = []
    for row in client.list_records("Reference"):
        source = _source_of(row, sources)
        if source not in sources or row.get("corpusId") != corpus_id or row.get("versionState") not in (None, "current"):
            continue
        if normalize_policy_token(row.get("curationStatus")) in EXCLUDED_STATES:
            continue
        try:
            created = parse_day(str(row.get("sourcePublishedAt")))
        except (TypeError, ValueError):
            continue
        if (since is None or since <= created) and created <= until:
            chosen.append((created, row, source))
    chosen.sort(key=lambda entry: (entry[0], str(entry[1].get("id"))), reverse=True)
    records = []
    read = map_with_clients(chosen, lambda reader, entry: record_of(reader, entry[1], entry[2]), client=client, client_factory=client_factory, workers=workers)
    for (_created, row, _source), (record, missing) in zip(chosen, read):
        if record is None:  # a routed candidate no monitor delivered (no provenance relation names one): not a monitor record
            continue
        if missing:
            warnings.append(f"{row['id']}: no Hub details on its provenance relation; only its title, date and author are used")
        records.append(record)
    return records, warnings


def record_of(client: Any, row: Mapping[str, Any], source: str | None = None) -> tuple[MonitorRecord | None, bool]:
    """The record a delivered Reference is, and whether its provenance relation lacked the Hub details. A routed candidate that no monitor
    delivered (its provenance names no ``monitorId``, or names the Hub monitor, which the ``huggingface`` source owns) is ``None``."""
    source = source or _source_of(row)
    if source is None:
        raise ValueError(f"Reference {row.get('id')} is not a monitor record: its address is not on a supported source.")
    lineage = str(row.get("lineageId") or row["id"])
    url = str(row["sourceUri"])
    relations = client.list_semantic_relations_by_object_state(semantic_state_key("reference", lineage))
    if source == SOURCE_ROUTED:
        monitor = _monitor_id(relations)
        if not monitor or monitor == SOURCE_HUGGINGFACE:
            return None, False
        return (
            MonitorRecord(
                reference_id=str(row["id"]), lineage_id=lineage, source=monitor, url=url, title=str(row.get("title") or url),
                created_at=iso_timestamp(str(row["sourcePublishedAt"])), details=_details_from_relations(relations),
                state=normalize_policy_token(row.get("curationStatus")) or "pending",
            ),
            False,
        )
    details = _details_from_relations(relations)
    missing = not details
    if missing:
        details = _fallback_details(row, url)
    return (
        MonitorRecord(
            reference_id=str(row["id"]), lineage_id=lineage, source=source, url=url,
            title=str(details.get("modelId") or row.get("title") or url), created_at=iso_timestamp(str(row["sourcePublishedAt"])),
            details=details, state=normalize_policy_token(row.get("curationStatus")) or "pending",
        ),
        missing,
    )


def write_records(path: Path, records: list[MonitorRecord], *, as_of: date, sources: tuple[str, ...]) -> None:
    payload = {"schemaVersion": SCHEMA_VERSION, "asOf": as_of.isoformat(), "sources": list(sources), "records": [record.to_dict() for record in records]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def read_records(path: Path | str) -> list[MonitorRecord]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return sorted((MonitorRecord.from_dict(entry) for entry in raw["records"]), key=lambda record: record.reference_id)
    except OSError as error:
        raise ValueError(f"Cannot read --monitor-records {path}: {error.strerror or error}") from error
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{path} is not a monitor records file: {error}") from error


# -- what a record says about itself ---------------------------------------------------------------------------------
def record_summary(record: MonitorRecord) -> str:
    """One line of the record's structured facts: the only text a Cited Trends story may rest on for a record."""
    if record.routed:  # no structured facts: what the monitor delivered is the title (and the summary, when it stored one)
        return f"{record.title} ({record.provenance}, {record.created_at[:10]}).{' ' + str(record.details['summary']) if record.details.get('summary') else ''}"[:SUMMARY_LIMIT]
    details = record.details
    kind = f"{details['pipelineTag']} model" if details.get("pipelineTag") else "model"
    author = f" by {details['author']}" if details.get("author") else ""
    parts = [f"{record.model_id} is a {kind}{author}, released {record.created_at[:10]}."]
    if details.get("license"):
        parts.append(f"License {details['license']}.")
    counts = [f"{details[name]} {name}" for name in ("likes", "downloads") if isinstance(details.get(name), int)]
    if counts:
        parts.append(", ".join(counts).capitalize() + ".")
    bases = [f"{base['modelId']} ({base.get('relation') or 'declared'})" for base in details.get("baseModels") or [] if base.get("modelId")]
    if bases:
        parts.append("Built on " + ", ".join(bases[:3]) + ".")
    return " ".join(parts)[:SUMMARY_LIMIT]


def record_entities(record: MonitorRecord) -> list[tuple[str, str]]:
    """``(kind, name)`` pairs from the structured fields: the model, its maker, its licence and its task. A routed record has none:
    its entities are the ones its text mentions (``monitor_match.py``)."""
    if record.routed:
        return []
    details = record.details
    licence = str(details.get("license") or "").strip()
    pairs = [
        ("model", record.model_id),
        ("maker", str(details.get("author") or "").strip()),
        ("licence", "" if licence.lower() in GENERIC_LICENCES else licence),
        ("task", str(details.get("pipelineTag") or "").strip()),
    ]
    return [(kind, name) for kind, name in pairs if name]


def record_as_item(record: MonitorRecord) -> PublishedItem:
    """The record as the snapshot builder counts it: dated, with the Hub card as its address, kind ``monitor-record``."""
    return PublishedItem(
        key=record.lineage_id, item_id=record.reference_id, title=record.title, url=record.url, published_at=record.created_at,
        kind=KIND_MONITOR_RECORD, summary=record_summary(record), source=record.source,
    )
