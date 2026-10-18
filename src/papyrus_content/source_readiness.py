from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE_READINESS_STATES = {
    "URL_ONLY": "url_only",
    "ACCESSIONED": "accessioned",
    "EXTRACTABLE": "extractable",
    "EXTRACTED": "extracted",
    "BLOCKED": "blocked",
}

SOURCE_TEXT_STATES = {
    "TEXT_READY": "text_ready",
    "SNAPSHOT_EXTRACTED": "snapshot_extracted",
    "MISSING_TEXT": "missing_text",
    "NOT_APPLICABLE": "not_applicable",
}

REFERENCE_PROCESSING_STATUS = {
    "CREATED": "created",
    "PROCESSABLE": "processable",
    "PROCESSED": "processed",
    "BLOCKED": "blocked",
}

EXTRACTABLE_MEDIA_TYPES = {
    "application/pdf",
    "text/html",
    "text/markdown",
    "text/plain",
    "application/xhtml+xml",
    "application/json",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "video/mp4",
    "video/webm",
    "video/youtube",
}


@dataclass
class ExtractionIndex:
    item_ids: set[str]
    text_by_item_id: dict[str, dict[str, Any]]
    text_by_storage_path: dict[str, dict[str, Any]]
    snapshot_ids: list[str]


def has_corpus_storage_path(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("corpora/")


def is_extractable_media_type(media_type: str | None) -> bool:
    if not media_type:
        return True
    normalized = str(media_type).split(";", 1)[0].strip().lower()
    return normalized in EXTRACTABLE_MEDIA_TYPES or normalized.startswith("text/") or normalized.startswith("audio/")


def source_storage_path_for_reference(reference: dict[str, Any], attachments: list[dict[str, Any]]) -> str | None:
    if has_corpus_storage_path(reference.get("storagePath")):
        return reference["storagePath"]
    for attachment in attachments:
        if attachment.get("referenceLineageId") != reference.get("lineageId"):
            continue
        if attachment.get("role") == "source" and has_corpus_storage_path(attachment.get("storagePath")):
            return attachment["storagePath"]
    return None


def source_media_type_for_reference(reference: dict[str, Any], attachments: list[dict[str, Any]]) -> str | None:
    if reference.get("mediaType"):
        return reference["mediaType"]
    for attachment in attachments:
        if attachment.get("referenceLineageId") != reference.get("lineageId"):
            continue
        if attachment.get("role") == "source" and attachment.get("mediaType"):
            return attachment["mediaType"]
    return None


def text_storage_path_for_reference(reference: dict[str, Any], attachments: list[dict[str, Any]]) -> str | None:
    attachment = select_extracted_text_attachment(reference, attachments)
    return attachment.get("storagePath") if attachment else None


def select_reference_attachment_by_role(
    reference: dict[str, Any],
    attachments: list[dict[str, Any]],
    *,
    role: str,
) -> dict[str, Any] | None:
    candidates = [
        attachment
        for attachment in attachments
        if attachment.get("referenceLineageId") == reference.get("lineageId")
        and attachment.get("role") == role
        and has_corpus_storage_path(attachment.get("storagePath"))
    ]
    candidates.sort(
        key=lambda entry: (
            str(entry.get("importedAt") or ""),
            str(entry.get("id") or ""),
        ),
        reverse=True,
    )
    return candidates[0] if candidates else None


def select_extracted_text_attachment(reference: dict[str, Any], attachments: list[dict[str, Any]]) -> dict[str, Any] | None:
    return select_reference_attachment_by_role(
        reference,
        attachments,
        role="extracted_text",
    )


def select_extracted_text_raw_attachment(reference: dict[str, Any], attachments: list[dict[str, Any]]) -> dict[str, Any] | None:
    return select_reference_attachment_by_role(
        reference,
        attachments,
        role="extracted_text_raw",
    )


def is_biblicus_extraction_snapshot_text_path(storage_path: str | None, item_id: str | None = None) -> bool:
    if not has_corpus_storage_path(storage_path):
        return False
    normalized = str(storage_path).replace("\\", "/")
    suffix = f"/{item_id}.txt" if item_id else ".txt"
    return "/extracted/pipeline/" in normalized and "/text/" in normalized and normalized.endswith(suffix)


def build_extraction_index(corpus_path: str | None) -> ExtractionIndex:
    item_ids: set[str] = set()
    text_by_item_id: dict[str, dict[str, Any]] = {}
    text_by_storage_path: dict[str, dict[str, Any]] = {}
    snapshot_ids: list[str] = []
    if not corpus_path:
        return ExtractionIndex(item_ids, text_by_item_id, text_by_storage_path, snapshot_ids)
    from biblicus.constants import PIPELINE_EXTRACTOR_ID
    from biblicus.corpus import Corpus

    root = Path(corpus_path).resolve()
    corpus = Corpus.open(root)
    extracted_root = corpus.extraction_snapshots_dir / PIPELINE_EXTRACTOR_ID
    if not extracted_root.exists():
        return ExtractionIndex(item_ids, text_by_item_id, text_by_storage_path, snapshot_ids)

    snapshots: list[dict[str, Any]] = []
    for snapshot_dir in extracted_root.iterdir():
        if not snapshot_dir.is_dir():
            continue
        entry = _extraction_snapshot_entry(root, extracted_root, snapshot_dir.name)
        if entry:
            snapshots.append(entry)
    snapshots.sort(key=lambda entry: (str(entry.get("createdAt") or ""), str(entry.get("snapshotId") or "")))

    for snapshot in snapshots:
        snapshot_ids.append(snapshot["snapshotId"])
        for item in snapshot.get("items") or []:
            item_id = item.get("itemId")
            storage_path = item.get("storagePath")
            if not item_id or not storage_path:
                continue
            item_ids.add(item_id)
            text_by_item_id[item_id] = item
            text_by_storage_path[storage_path] = item
    return ExtractionIndex(item_ids, text_by_item_id, text_by_storage_path, snapshot_ids)


def reference_source_readiness(
    reference: dict[str, Any],
    attachments: list[dict[str, Any]] | None = None,
    extraction_index: ExtractionIndex | None = None,
) -> dict[str, Any]:
    attachments = attachments or []
    storage_path = source_storage_path_for_reference(reference, attachments)
    text_storage_path = text_storage_path_for_reference(reference, attachments)
    media_type = source_media_type_for_reference(reference, attachments)
    has_source_uri = bool(reference.get("sourceUri"))
    has_extraction_snapshot = bool(
        reference.get("externalItemId")
        and extraction_index
        and reference["externalItemId"] in extraction_index.item_ids
    )
    text_attachment_exists = bool(text_storage_path)
    text_attachment_is_snapshot = bool(
        text_storage_path
        and is_biblicus_extraction_snapshot_text_path(text_storage_path, reference.get("externalItemId"))
    )
    text_attachment_present = (
        not text_storage_path
        or not extraction_index
        or not text_attachment_is_snapshot
        or text_storage_path in extraction_index.text_by_storage_path
    )
    extracted = text_attachment_exists and text_attachment_present
    extractable = is_extractable_media_type(media_type)
    if extracted:
        text_state = SOURCE_TEXT_STATES["TEXT_READY"]
    elif has_extraction_snapshot:
        text_state = SOURCE_TEXT_STATES["SNAPSHOT_EXTRACTED"]
    elif storage_path and extractable:
        text_state = SOURCE_TEXT_STATES["MISSING_TEXT"]
    else:
        text_state = SOURCE_TEXT_STATES["NOT_APPLICABLE"]

    if extracted:
        state = SOURCE_READINESS_STATES["EXTRACTED"]
        reason = "extracted_text_attachment_found"
    elif storage_path and extractable:
        state = SOURCE_READINESS_STATES["EXTRACTABLE"]
        reason = "snapshot_extracted_missing_attachment" if has_extraction_snapshot else "corpus_source_available"
    elif storage_path:
        state = SOURCE_READINESS_STATES["ACCESSIONED"]
        reason = "unsupported_or_unknown_extractor"
    elif has_source_uri:
        state = SOURCE_READINESS_STATES["URL_ONLY"]
        reason = "missing_corpus_storage_path"
    else:
        state = SOURCE_READINESS_STATES["BLOCKED"]
        reason = "missing_source_material"

    processing_status = reference_processing_status_for_readiness(state)
    return {
        "state": state,
        "processingStatus": processing_status,
        "reason": reason,
        "storagePath": storage_path,
        "textStoragePath": text_storage_path,
        "mediaType": media_type,
        "extracted": extracted,
        "extractable": extractable,
        "hasExtractionSnapshot": has_extraction_snapshot,
        "textState": text_state,
    }


def reference_processing_status_for_readiness(readiness_state: str | None) -> str:
    normalized = str(readiness_state or "").strip().lower()
    if normalized == SOURCE_READINESS_STATES["URL_ONLY"]:
        return REFERENCE_PROCESSING_STATUS["CREATED"]
    if normalized in {SOURCE_READINESS_STATES["ACCESSIONED"], SOURCE_READINESS_STATES["EXTRACTABLE"]}:
        return REFERENCE_PROCESSING_STATUS["PROCESSABLE"]
    if normalized == SOURCE_READINESS_STATES["EXTRACTED"]:
        return REFERENCE_PROCESSING_STATUS["PROCESSED"]
    return REFERENCE_PROCESSING_STATUS["BLOCKED"]


def build_reference_source_status_rows(
    *,
    references: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    corpus_id: str,
    curation_status: str = "all",
    extraction_index: ExtractionIndex | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for reference in references:
        if corpus_id and reference.get("corpusId") != corpus_id:
            continue
        if reference.get("versionState") != "current":
            continue
        if curation_status != "all" and reference.get("curationStatus") != curation_status:
            continue
        readiness = reference_source_readiness(reference, attachments, extraction_index)
        rows.append(
            {
                "reference": reference,
                "readiness": readiness,
                "state": readiness["state"],
                "processingStatus": readiness["processingStatus"],
                "reason": readiness["reason"],
            }
        )
    rows.sort(
        key=lambda row: (
            str(row["state"]),
            str(row["reference"].get("curationStatus") or ""),
            str(row["reference"].get("externalItemId") or row["reference"].get("id") or ""),
        )
    )
    return rows


def _extraction_snapshot_entry(root: Path, extracted_root: Path, snapshot_id: str) -> dict[str, Any] | None:
    snapshot_dir = extracted_root / snapshot_id
    manifest_path = snapshot_dir / "manifest.json"
    manifest = _read_json_if_exists(manifest_path)
    configuration = (manifest or {}).get("configuration") or {}
    created_at = (manifest or {}).get("created_at")
    items: list[dict[str, Any]] = []
    if isinstance((manifest or {}).get("items"), list):
        for item in manifest["items"]:
            if item.get("status") != "extracted" or not item.get("final_text_relpath"):
                continue
            local_path = snapshot_dir.joinpath(*str(item["final_text_relpath"]).split("/"))
            if not local_path.exists():
                continue
            storage_path = _corpus_storage_path(root, local_path)
            if not storage_path:
                continue
            items.append(
                {
                    "itemId": item.get("item_id"),
                    "snapshotId": snapshot_id,
                    "localPath": str(local_path),
                    "storagePath": storage_path,
                    "createdAt": created_at,
                }
            )
    else:
        text_dir = snapshot_dir / "text"
        if not text_dir.exists():
            return None
        for filename in text_dir.iterdir():
            if not filename.name.endswith(".txt"):
                continue
            storage_path = _corpus_storage_path(root, filename)
            if not storage_path:
                continue
            items.append(
                {
                    "itemId": filename.name[:-4],
                    "snapshotId": snapshot_id,
                    "localPath": str(filename),
                    "storagePath": storage_path,
                    "createdAt": created_at,
                }
            )
    return {"snapshotId": snapshot_id, "createdAt": created_at, "items": items, "configuration": configuration}


def _corpus_storage_path(root: Path, local_path: Path) -> str | None:
    try:
        relative = local_path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    relative_text = relative.as_posix()
    corpus_name = root.name
    if relative_text.startswith("corpora/"):
        return relative_text
    return f"corpora/{corpus_name}/{relative_text}"


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
