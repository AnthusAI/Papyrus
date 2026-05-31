from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .assignments import apply_assignment_action, assignment_metadata
from .catalog import semantic_relation_record
from .corpora import build_corpus_sync_plan, run_or_print_corpus_sync_plan
from .graphql_authoring import PapyrusGraphQLAuthoringClient
from .options import normalize_string
from .ids import deterministic_uuid, hash_short, is_uuid_string, knowledge_corpus_id, reference_lineage_id_for, safe_id
from .model_attachments import parse_jsonish
from .records import apply_record_changes, build_record_change_from_current, build_record_changes
from .reference_url_text import _resolve_existing_canonical_uri
from .source_readiness import SOURCE_READINESS_STATES, is_extractable_media_type, reference_source_readiness
from .source_site_plugins import resolve_accessible_pdf_url_for_reference, resolve_source_site_enrichment
from .steering import (
    find_corpus_config,
    load_steering_config,
    require_corpus_config,
    require_steering_config,
    resolve_biblicus_runtime_dir,
    resolve_corpus_local_path,
)


ASSIGNMENT_TYPE_POLICY = {
    "assignmentTypeKey": "reference.corpus-accession",
    "handlerKey": "reference.corpus-accession",
    "executionMode": "queued",
    "claimPolicy": "exclusive",
    "defaultClaimTtlSeconds": 60 * 60,
}


def build_reference_accession_assignment_records(
    rows: list[dict[str, Any]],
    *,
    corpus_config: dict[str, Any],
    corpus_id: str,
    assignments: list[dict[str, Any]],
    actor_label: str,
    now: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        if row["state"] != SOURCE_READINESS_STATES["URL_ONLY"]:
            continue
        reference = row["reference"]
        if active_reference_accession_assignment(assignments, reference, corpus_id):
            continue
        assignment = reference_accession_assignment_record(
            reference,
            row["readiness"],
            corpus_config=corpus_config,
            corpus_id=corpus_id,
            actor_label=actor_label,
            now=now,
        )
        records.extend(
            [
                {"modelName": "Assignment", "expected": assignment},
                {
                    "modelName": "AssignmentEvent",
                    "expected": assignment_created_event_record(assignment, actor_label, now),
                },
                semantic_relation_record(
                    {
                        "predicate": "requests_work_on",
                        "subjectKind": "assignment",
                        "subjectId": assignment["id"],
                        "subjectLineageId": assignment["id"],
                        "subjectVersionNumber": None,
                        "objectKind": "reference",
                        "objectId": reference["id"],
                        "objectLineageId": reference["lineageId"],
                        "objectVersionNumber": reference.get("versionNumber"),
                        "rank": 1,
                        "importedAt": now,
                        "metadata": {
                            "kind": "reference.corpus-accession.requests_work_on",
                            "sourceReadinessBefore": row["readiness"]["state"],
                        },
                    }
                ),
            ]
        )
    return records


def reference_accession_assignment_id(reference: dict[str, Any], corpus_id: str) -> str:
    return f"assignment-reference-corpus-accession-{hash_short([corpus_id, reference['lineageId']])}"


def active_reference_accession_assignment(assignments: list[dict[str, Any]], reference: dict[str, Any], corpus_id: str) -> bool:
    expected_id = reference_accession_assignment_id(reference, corpus_id)
    return any(assignment.get("id") == expected_id for assignment in assignments)


def reference_accession_assignment_record(
    reference: dict[str, Any],
    readiness: dict[str, Any],
    *,
    corpus_config: dict[str, Any],
    corpus_id: str,
    actor_label: str,
    now: str,
) -> dict[str, Any]:
    assignment_type_key = "reference.corpus-accession"
    queue_key = f"{assignment_type_key}#{corpus_id}"
    biblicus_item_id = (
        reference["externalItemId"]
        if is_uuid_string(reference.get("externalItemId"))
        else deterministic_uuid(f"papyrus-reference-accession:{reference['lineageId']}")
    )
    accession_mode = "update-current-lineage" if is_uuid_string(reference.get("externalItemId")) else "create-uuid-replacement"
    return {
        "id": reference_accession_assignment_id(reference, corpus_id),
        "assignmentTypeKey": assignment_type_key,
        "queueKey": queue_key,
        "queueStatusKey": f"{queue_key}#open",
        "status": "open",
        "priority": 60,
        "title": (
            f"Accession source: {reference['title']}"
            if reference.get("title")
            else f"Accession source {reference.get('externalItemId')}"
        ),
        "brief": "Materialize this URL-only reference prospect into the configured Biblicus corpus.",
        "instructions": "Download the source URI into the corpus accession and update Reference source metadata.",
        "corpusId": corpus_id,
        "importRunId": None,
        "createdBy": actor_label,
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "assignments",
        "metadata": json.dumps(
            {
                "kind": "reference.corpus-accession.requested",
                "referenceId": reference["id"],
                "referenceLineageId": reference["lineageId"],
                "sourceUri": reference.get("sourceUri"),
                "corpusKey": corpus_config["key"],
                "corpusId": corpus_id,
                "corpusPath": corpus_config.get("path"),
                "expectedStoragePrefix": f"{str(corpus_config.get('path') or '').rstrip('/')}/imports/",
                "s3Prefix": corpus_config.get("s3Prefix"),
                "accessionMode": accession_mode,
                "biblicusItemId": biblicus_item_id,
                "sourceReadinessBefore": readiness.get("state"),
                "assignmentTypePolicy": ASSIGNMENT_TYPE_POLICY,
            }
        ),
    }


def assignment_created_event_record(assignment: dict[str, Any], actor_label: str, now: str) -> dict[str, Any]:
    return {
        "id": f"assignment-event-{assignment['id']}-created",
        "assignmentId": assignment["id"],
        "assignmentTypeKey": assignment["assignmentTypeKey"],
        "queueKey": assignment["queueKey"],
        "eventType": "created",
        "fromStatus": None,
        "toStatus": assignment["status"],
        "actorLabel": actor_label,
        "note": assignment.get("brief"),
        "createdAt": now,
        "metadata": json.dumps({"kind": f"{assignment['assignmentTypeKey']}.created", "source": "papyrus-cli"}),
    }


def find_reference_for_source_accession(references: list[dict[str, Any]], selector: str) -> dict[str, Any] | None:
    return next(
        (
            reference
            for reference in references
            if reference.get("id") == selector
            or (reference.get("lineageId") == selector and reference.get("versionState") == "current")
            or (reference.get("externalItemId") == selector and reference.get("versionState") == "current")
        ),
        None,
    )


def require_corpus_config_by_id_or_key(
    steering_config: dict[str, Any],
    corpus_id: str,
    corpus_key: str | None,
) -> dict[str, Any]:
    if corpus_key:
        return require_corpus_config(steering_config, corpus_key, "--corpus-key")
    match = next(
        (corpus for corpus in steering_config.get("corpora", []) if knowledge_corpus_id(corpus) == corpus_id),
        None,
    )
    if not match:
        raise ValueError(f"Could not resolve corpus config for {corpus_id}; pass --corpus-key.")
    return match


def execute_reference_accession_assignment(
    client: PapyrusGraphQLAuthoringClient,
    assignment: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    if assignment.get("assignmentTypeKey") != "reference.corpus-accession":
        raise ValueError(
            f"Assignment {assignment['id']} is {assignment.get('assignmentTypeKey')}; expected reference.corpus-accession."
        )
    if assignment.get("status") != "claimed":
        raise ValueError(
            f"Assignment {assignment['id']} must be claimed before execution (current={assignment.get('status')})."
        )
    metadata = resolve_accession_assignment_metadata(client, assignment, options)
    actor_label = options.get("actor") or options.get("assignee-key") or "papyrus-cli"
    run_id = options.get("run-id") or f"reference-accession-{hash_short([assignment['id'], _utc_now()])}"
    run_dir = Path.cwd() / ".papyrus-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "execution-manifest.json"

    reference = client.get_record("Reference", metadata["referenceId"])
    if not reference:
        raise ReferenceAccessionError(f"Reference {metadata['referenceId']} was not found.", kind="missing_reference")
    if not reference.get("sourceUri"):
        raise ReferenceAccessionError(
            f"Reference {reference['id']} has no sourceUri to accession.",
            kind="missing_source_material",
        )

    steering_config = load_steering_config(options.get("config") or metadata.get("steeringConfigPath")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, metadata["corpusKey"], "assignment.metadata.corpusKey")
    corpus_id = knowledge_corpus_id(corpus_config)
    corpus_path = resolve_corpus_local_path(corpus_config, steering_config)
    biblicus_workdir = resolve_biblicus_runtime_dir(options)

    source_material = download_reference_source_material(
        reference,
        biblicus_item_id=metadata["biblicusItemId"],
        run_dir=run_dir,
        download_uri=normalize_string((options or {}).get("download-uri") or (options or {}).get("downloadUri")),
    )
    if not is_extractable_media_type(source_material["mediaType"]):
        raise ReferenceAccessionError(
            f"Unsupported media type for extraction: {source_material['mediaType']}.",
            kind="unsupported_media_type",
        )
    accession = write_reference_source_accession(
        reference=reference,
        source_material=source_material,
        corpus_config=corpus_config,
        corpus_path=corpus_path,
        biblicus_item_id=metadata["biblicusItemId"],
        actor_label=actor_label,
    )
    reindex_result = run_biblicus_reindex_for_accession(corpus_path=corpus_path, biblicus_workdir=biblicus_workdir, run_dir=run_dir)
    s3_sync_result = maybe_sync_accession_to_s3(
        corpus_config=corpus_config,
        corpus_path=corpus_path,
        run_dir=run_dir,
        options=options,
    )
    import_run_id = (
        f"knowledge-import-{safe_id(corpus_id)}-reference-accession-"
        f"{hash_short([reference['lineageId'], accession['sha256']])}"
    )
    records = build_reference_accession_graphql_records(
        reference=reference,
        corpus_id=corpus_id,
        import_run_id=import_run_id,
        accession=accession,
        source_material=source_material,
        metadata=metadata,
        actor_label=actor_label,
    )
    changes = build_record_changes(client, records)
    changes = augment_reference_accession_changes_for_replacement(changes, reference=reference, accession=accession, metadata=metadata)
    apply_record_changes(client, changes)
    manifest = {
        "runId": run_id,
        "assignmentId": assignment["id"],
        "assignmentTypeKey": assignment["assignmentTypeKey"],
        "status": "executed",
        "referenceId": reference["id"],
        "sourceUri": reference.get("sourceUri"),
        "storagePath": accession["storagePath"],
        "reindex": reindex_result,
        "s3Sync": s3_sync_result,
        "importSummary": {
            "importedRecords": sum(1 for change in changes if change.get("action") != "noop"),
            "importRuns": [import_run_id],
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "assignmentId": assignment["id"],
        "runId": run_id,
        "manifestPath": str(manifest_path),
        "storagePath": accession["storagePath"],
        "importSummary": manifest["importSummary"],
    }


def download_reference_source_material(
    reference: dict[str, Any],
    *,
    biblicus_item_id: str,
    run_dir: Path,
    download_uri: str | None = None,
) -> dict[str, Any]:
    download_uri = str(download_uri or "").strip() or source_download_uri_for_reference(reference)
    try:
        buffer, content_type, download_uri = _download_reference_payload(download_uri)
    except ReferenceAccessionError as error:
        if error.kind != "download_failed":
            raise
        fallback = resolve_accessible_pdf_url_for_reference(
            reference,
            source_uri=str(reference.get("sourceUri") or ""),
            failed_uri=download_uri,
        )
        fallback_uri = str(fallback.get("selectedPdfUrl") or "").strip()
        if not fallback_uri or fallback_uri == download_uri:
            raise
        buffer, content_type, download_uri = _download_reference_payload(fallback_uri)
    if not buffer:
        raise ReferenceAccessionError(f"Downloaded source for {reference['id']} was empty.", kind="download_empty")
    filename = reference_accession_filename(
        item_id=biblicus_item_id,
        source_uri=download_uri,
        title=reference.get("title"),
        media_type=content_type,
    )
    download_path = run_dir / filename
    download_path.write_bytes(buffer)
    import hashlib

    return {
        "downloadPath": str(download_path),
        "filename": filename,
        "downloadUri": download_uri,
        "mediaType": content_type,
        "byteSize": len(buffer),
        "sha256": hashlib.sha256(buffer).hexdigest(),
    }


def write_reference_source_accession(
    *,
    reference: dict[str, Any],
    source_material: dict[str, Any],
    corpus_config: dict[str, Any],
    corpus_path: Path,
    biblicus_item_id: str,
    actor_label: str,
) -> dict[str, Any]:
    imports_dir = corpus_path / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    local_path = imports_dir / source_material["filename"]
    shutil.copyfile(source_material["downloadPath"], local_path)
    relpath = local_path.relative_to(corpus_path).as_posix()
    storage_path = f"{str(corpus_config.get('path')).rstrip('/')}/{relpath}"
    sidecar_path = Path(f"{local_path}.biblicus.yml")
    sidecar = {
        "title": reference.get("title"),
        "media_type": source_material["mediaType"],
        "biblicus": {"id": biblicus_item_id, "source": reference.get("sourceUri")},
        "dates": {
            "published_at": reference.get("sourcePublishedAt"),
            "updated_at": reference.get("sourceUpdatedAt"),
            "retrieved_at": reference.get("retrievedAt") or _utc_now(),
        },
        "papyrus": {
            "reference_id": reference["id"],
            "reference_lineage_id": reference["lineageId"],
            "download_uri": source_material["downloadUri"],
            "accessioned_by": actor_label,
            "accessioned_at": _utc_now(),
        },
    }
    sidecar_path.write_text(yaml.safe_dump({key: value for key, value in sidecar.items() if value is not None}, sort_keys=False), encoding="utf-8")
    return {
        "biblicusItemId": biblicus_item_id,
        "localPath": str(local_path),
        "sidecarPath": str(sidecar_path),
        "relpath": relpath,
        "storagePath": storage_path,
        "sourceUri": reference.get("sourceUri"),
        "mediaType": source_material["mediaType"],
        "byteSize": source_material["byteSize"],
        "sha256": source_material["sha256"],
    }


def run_biblicus_reindex_for_accession(*, corpus_path: Path, biblicus_workdir: Path, run_dir: Path) -> dict[str, Any]:
    stdout_log = run_dir / "biblicus-reindex.stdout.log"
    stderr_log = run_dir / "biblicus-reindex.stderr.log"
    uv_path = shutil.which("uv")
    if not uv_path:
        raise ReferenceAccessionError(
            "Biblicus reindex requires the uv executable on PATH.",
            kind="biblicus_reindex_failed",
        )

    resolved_corpus_path = corpus_path.resolve()
    command = [uv_path, "run", "biblicus", "reindex", "--corpus", str(resolved_corpus_path)]
    run_dir.mkdir(parents=True, exist_ok=True)
    with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open("w", encoding="utf-8") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=biblicus_workdir,
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=_biblicus_subprocess_env(),
            start_new_session=True,
        )
        returncode = process.wait()

    if returncode != 0:
        detail = _subprocess_failure_detail(stdout_log, stderr_log)
        raise ReferenceAccessionError(
            (
                f"Biblicus reindex failed for {resolved_corpus_path} "
                f"(exit {_format_subprocess_exit(returncode)}). {detail} "
                f"See {stderr_log} and {stdout_log}."
            ),
            kind="biblicus_reindex_failed",
        )
    return {"label": "biblicus-reindex", "stdoutLogPath": str(stdout_log), "stderrLogPath": str(stderr_log)}


def _biblicus_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    path_entries = [entry for entry in str(env.get("PATH") or "").split(os.pathsep) if entry]
    for extra in ("/opt/homebrew/bin", "/usr/local/bin"):
        if extra not in path_entries:
            path_entries.append(extra)
    env["PATH"] = os.pathsep.join(path_entries)
    return env


def _format_subprocess_exit(returncode: int) -> str:
    if returncode < 0:
        signal_number = -returncode
        signal_name = ""
        try:
            signal_name = signal.Signals(signal_number).name
        except (ValueError, AttributeError):
            signal_name = str(signal_number)
        return f"signal {signal_name}"
    return str(returncode)


def _subprocess_failure_detail(stdout_log: Path, stderr_log: Path, *, max_chars: int = 400) -> str:
    chunks: list[str] = []
    for path in (stderr_log, stdout_log):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            chunks.append(text[-max_chars:])
    if not chunks:
        return "No subprocess output was captured."
    return " ".join(chunk.replace("\n", " ").strip() for chunk in chunks)


def maybe_sync_accession_to_s3(
    *,
    corpus_config: dict[str, Any],
    corpus_path: Path,
    run_dir: Path,
    options: dict[str, Any],
) -> dict[str, Any]:
    if not options.get("sync-s3") and not options.get("sync-s3-apply"):
        return {"skipped": True, "reason": "pass --sync-s3 for dry-run and --sync-s3-apply for actual sync"}
    plan = build_corpus_sync_plan(
        corpus_config,
        direction="to-cloud",
        options={"apply": bool(options.get("sync-s3-apply")), "dry-run": not options.get("sync-s3-apply")},
    )
    run_or_print_corpus_sync_plan(plan, options)
    return {"skipped": not options.get("sync-s3-apply"), "plan": plan}


def build_reference_accession_graphql_records(
    *,
    reference: dict[str, Any],
    corpus_id: str,
    import_run_id: str,
    accession: dict[str, Any],
    source_material: dict[str, Any],
    metadata: dict[str, Any],
    actor_label: str,
) -> list[dict[str, Any]]:
    now = _utc_now()
    replacement_mode = metadata.get("accessionMode") == "create-uuid-replacement"
    next_reference = (
        new_reference_for_accession_replacement(reference, corpus_id, import_run_id, accession, actor_label, now)
        if replacement_mode
        else next_reference_version_for_accession(reference, import_run_id, accession, actor_label, now)
    )
    records: list[dict[str, Any]] = [
        {
            "modelName": "KnowledgeImportRun",
            "expected": {
                "id": import_run_id,
                "corpusId": corpus_id,
                "importKind": "reference-corpus-accession",
                "status": "imported",
                "generatedAt": now,
                "importedAt": now,
                "itemCount": 1,
                "referenceCount": 1,
                "relationCount": 1 if replacement_mode else 0,
            },
        },
        {
            "modelName": "KnowledgeRawPayload",
            "expected": {
                "id": f"knowledge-raw-payload-{safe_id(import_run_id)}-reference-accession",
                "ownerType": "importRun",
                "ownerId": import_run_id,
                "payloadKind": "reference-corpus-accession",
                "importRunId": import_run_id,
                "payload": json.dumps(
                    {
                        "snapshot_kind": "papyrus-reference-corpus-accession",
                        "reference_id": reference["id"],
                        "storage_path": accession["storagePath"],
                        "sha256": accession["sha256"],
                    }
                ),
                "createdAt": now,
                "updatedAt": now,
            },
        },
        {"modelName": "Reference", "expected": next_reference},
        {
            "modelName": "ReferenceAttachment",
            "expected": reference_attachment_for_accession(next_reference, accession, import_run_id, now),
        },
    ]
    if replacement_mode:
        records.append(
            semantic_relation_record(
                {
                    "predicate": "derived_from",
                    "subjectKind": "reference",
                    "subjectId": next_reference["id"],
                    "subjectLineageId": next_reference["lineageId"],
                    "subjectVersionNumber": next_reference.get("versionNumber"),
                    "objectKind": "reference",
                    "objectId": reference["id"],
                    "objectLineageId": reference["lineageId"],
                    "objectVersionNumber": reference.get("versionNumber"),
                    "rank": 1,
                    "importRunId": import_run_id,
                    "importedAt": now,
                    "metadata": {
                        "kind": "reference.corpus-accession.replacement",
                        "replacedExternalItemId": reference.get("externalItemId"),
                    },
                }
            )
        )
    return records


def augment_reference_accession_changes_for_replacement(
    changes: list[dict[str, Any]],
    *,
    reference: dict[str, Any],
    accession: dict[str, Any],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    if metadata.get("accessionMode") != "create-uuid-replacement":
        return changes
    for change in changes:
        if change["modelName"] == "Reference" and change["action"] == "create":
            expected = change["expected"]
            if expected.get("lineageId") != reference.get("lineageId"):
                change["action"] = "update"
                change["current"] = reference
    return changes


def next_reference_version_for_accession(
    reference: dict[str, Any],
    import_run_id: str,
    accession: dict[str, Any],
    actor_label: str,
    now: str,
) -> dict[str, Any]:
    metadata = parse_jsonish(reference.get("metadata")) if isinstance(reference.get("metadata"), str) else {}
    metadata.update(
        {
            "source_readiness": "accessioned",
            "accessioned_at": now,
            "accessioned_by": actor_label,
            "accession_import_run_id": import_run_id,
        }
    )
    next_reference = {
        **reference,
        "importRunId": import_run_id,
        "importedAt": now,
        "storagePath": accession["storagePath"],
        "mediaType": accession["mediaType"],
        "byteSize": accession["byteSize"],
        "sha256": accession["sha256"],
        "retrievedAt": reference.get("retrievedAt") or now,
        "metadata": json.dumps(metadata, sort_keys=True),
        "updatedAt": now,
        "versionCreatedAt": now,
        "versionCreatedBy": actor_label,
        "changeReason": "reference-corpus-accession",
    }
    next_reference["contentHash"] = hash_short(
        {
            "referenceId": next_reference["id"],
            "storagePath": next_reference["storagePath"],
            "sha256": next_reference["sha256"],
            "curationStatus": next_reference.get("curationStatus"),
        }
    )
    return next_reference


def new_reference_for_accession_replacement(
    reference: dict[str, Any],
    corpus_id: str,
    import_run_id: str,
    accession: dict[str, Any],
    actor_label: str,
    now: str,
) -> dict[str, Any]:
    lineage_id = reference_lineage_id_for(corpus_id, accession["biblicusItemId"])
    metadata = parse_jsonish(reference.get("metadata")) if isinstance(reference.get("metadata"), str) else {}
    metadata.update(
        {
            "source_readiness": "accessioned",
            "accessioned_at": now,
            "accessioned_by": actor_label,
            "replaced_reference_id": reference["id"],
            "replaced_reference_lineage_id": reference["lineageId"],
        }
    )
    next_reference = {
        **reference,
        "id": f"{lineage_id}-v1",
        "lineageId": lineage_id,
        "versionNumber": 1,
        "previousVersionId": None,
        "versionState": "current",
        "versionCreatedAt": now,
        "versionCreatedBy": actor_label,
        "changeReason": "reference-corpus-accession-replacement",
        "externalItemId": accession["biblicusItemId"],
        "corpusId": corpus_id,
        "importRunId": import_run_id,
        "importedAt": now,
        "storagePath": accession["storagePath"],
        "mediaType": accession["mediaType"],
        "byteSize": accession["byteSize"],
        "sha256": accession["sha256"],
        "curationStatus": reference.get("curationStatus") or "pending",
        "curationStatusKey": f"{corpus_id}#{reference.get('curationStatus') or 'pending'}",
        "reviewedFeedKey": (
            None
            if (reference.get("curationStatus") or "pending") == "pending"
            else "references#reviewed"
        ),
        "metadata": json.dumps(metadata, sort_keys=True),
        "updatedAt": now,
    }
    next_reference["contentHash"] = hash_short(
        {
            "referenceId": next_reference["id"],
            "storagePath": next_reference["storagePath"],
            "sha256": next_reference["sha256"],
            "curationStatus": next_reference.get("curationStatus"),
        }
    )
    return next_reference


def reference_attachment_for_accession(reference: dict[str, Any], accession: dict[str, Any], import_run_id: str, now: str) -> dict[str, Any]:
    reference_version_key = f"reference#{reference['id']}"
    return {
        "id": f"reference-attachment-{hash_short([reference_version_key, 'source', '001-source', accession['storagePath']])}",
        "referenceId": reference["id"],
        "referenceLineageId": reference["lineageId"],
        "referenceVersionNumber": reference.get("versionNumber"),
        "referenceVersionKey": reference_version_key,
        "role": "source",
        "sortKey": "001-source",
        "storagePath": accession["storagePath"],
        "sourceUri": accession["sourceUri"],
        "filename": Path(accession["localPath"]).name,
        "mediaType": accession["mediaType"],
        "byteSize": accession["byteSize"],
        "sha256": accession["sha256"],
        "importRunId": import_run_id,
        "importedAt": now,
        "metadata": json.dumps(
            {
                "source": "reference.corpus-accession",
                "localPath": accession["localPath"],
                "sidecarPath": accession["sidecarPath"],
                "biblicusItemId": accession["biblicusItemId"],
            }
        ),
    }


def _assignment_semantic_state_key(assignment_id: str) -> str:
    return f"assignment#{assignment_id}#current"


def resolve_accession_assignment_metadata(
    client: PapyrusGraphQLAuthoringClient,
    assignment: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = assignment_metadata(client, assignment)
    if metadata.get("kind") == "reference.corpus-accession.requested":
        return metadata

    reference_id = normalize_string(metadata.get("referenceId"))
    if not reference_id:
        relations = client.list_semantic_relations_by_subject_state(_assignment_semantic_state_key(assignment["id"]))
        for relation in relations:
            if str(relation.get("predicate") or "") != "requests_work_on":
                continue
            if str(relation.get("objectKind") or "") != "reference":
                continue
            reference_id = normalize_string(relation.get("objectId"))
            if reference_id:
                break
    if not reference_id:
        raise ValueError(
            f"Assignment {assignment['id']} is missing reference.corpus-accession.requested metadata and no linked Reference was found."
        )

    reference = client.get_record("Reference", reference_id)
    if not reference:
        raise ReferenceAccessionError(f"Reference {reference_id} was not found.", kind="missing_reference")

    steering_config = load_steering_config(options.get("config") if options else None) or require_steering_config()
    corpus_config = require_corpus_config_by_id_or_key(
        steering_config,
        reference["corpusId"],
        (options or {}).get("corpus-key"),
    )
    corpus_id = knowledge_corpus_id(corpus_config)
    attachments = client.list_records("ReferenceAttachment")
    readiness = reference_source_readiness(reference, attachments, None)
    rebuilt = reference_accession_assignment_record(
        reference,
        readiness,
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        actor_label=str((options or {}).get("assignee-key") or (options or {}).get("actor") or "papyrus-cli"),
        now=_utc_now(),
    )
    rebuilt_metadata = parse_jsonish(rebuilt.get("metadata"))
    if not isinstance(rebuilt_metadata, dict):
        raise ValueError(f"Assignment {assignment['id']} metadata could not be reconstructed.")
    return rebuilt_metadata


def _download_reference_payload(download_uri: str) -> tuple[bytes, str, str]:
    request = urllib.request.Request(
        download_uri,
        headers={"user-agent": "papyrus-reference-accession/1"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            content_type = response.headers.get_content_type() or media_type_from_url(download_uri) or "application/octet-stream"
            buffer = response.read()
    except urllib.error.HTTPError as error:
        raise ReferenceAccessionError(
            f"Failed to download {download_uri}: {error.code} {error.reason}.",
            kind="download_failed",
        ) from error
    if not buffer:
        raise ReferenceAccessionError(f"Downloaded source from {download_uri} was empty.", kind="download_empty")
    return buffer, content_type, download_uri


def source_download_uri_for_reference(reference: dict[str, Any]) -> str:
    source_uri = str(reference.get("sourceUri") or "").strip()
    if not source_uri:
        return ""
    if _uri_likely_direct_pdf(source_uri):
        return source_uri

    existing_canonical = _resolve_existing_canonical_uri(reference)
    if existing_canonical and _uri_likely_direct_pdf(existing_canonical):
        return existing_canonical

    enrichment = resolve_source_site_enrichment(
        reference={
            "id": reference.get("id"),
            "title": reference.get("title"),
            "metadata": reference.get("metadata"),
        },
        source_uri=source_uri,
    )
    variants = enrichment.get("sourceVariants") if isinstance(enrichment.get("sourceVariants"), dict) else {}
    canonical_pdf_url = str(variants.get("canonicalPdfUrl") or "").strip()
    if canonical_pdf_url:
        return canonical_pdf_url

    canonical_source_uri = str(enrichment.get("canonicalSourceUri") or "").strip()
    plugin_key = str(enrichment.get("pluginKey") or "").strip().lower()
    if canonical_source_uri and (
        _uri_likely_direct_pdf(canonical_source_uri)
        or plugin_key in {"acm", "arxiv", "acl_anthology"}
    ):
        return canonical_source_uri

    return source_uri


def _uri_likely_direct_pdf(url: str) -> bool:
    lowered = str(url or "").strip().lower()
    if not lowered:
        return False
    if lowered.endswith(".pdf"):
        return True
    parsed = urlparse(lowered)
    if (parsed.hostname or "").lower() == "dl.acm.org" and "/doi/pdf/" in (parsed.path or "").lower():
        return True
    return False


def media_type_from_url(url: str) -> str | None:
    guessed, _ = mimetypes.guess_type(urlparse(url).path)
    return guessed


def reference_accession_filename(*, item_id: str, source_uri: str, title: str | None, media_type: str) -> str:
    extension = mimetypes.guess_extension(media_type) or Path(urlparse(source_uri).path).suffix or ".bin"
    slug = safe_id(title or item_id)[:80]
    return f"{item_id}--{slug}{extension}"


def resolve_biblicus_workdir(options: dict[str, Any]) -> Path:
    return resolve_biblicus_runtime_dir(options)


class ReferenceAccessionError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "reference_accession_failed") -> None:
        super().__init__(message)
        self.kind = kind


def print_reference_accession_assignment_summary(rows: list[dict[str, Any]], changes: list[dict[str, Any]], *, apply: bool) -> None:
    model_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for change in changes:
        model_counts[change["modelName"]] = model_counts.get(change["modelName"], 0) + 1
        action_counts[change["action"]] = action_counts.get(change["action"], 0) + 1
    print(f"references\tprocess-create-accession-assignments\tcandidates\t{len(rows)}")
    print(
        "references\tprocess-create-accession-assignments\tmodels\t"
        + " ".join(f"{model}={count}" for model, count in sorted(model_counts.items()))
    )
    print(
        "references\tprocess-create-accession-assignments\tsummary\t"
        f"create={action_counts.get('create', 0)}\tupdate={action_counts.get('update', 0)}\tnoop={action_counts.get('noop', 0)}"
    )
    print(f"references\tprocess-create-accession-assignments\tapply\t{'yes' if apply else 'no'}")


def next_reference_source_command(row: dict[str, Any]) -> str:
    if row["state"] == SOURCE_READINESS_STATES["URL_ONLY"]:
        return f"poetry run papyrus references process-accession-now --reference {row['reference']['id']}"
    if row["readiness"].get("textState") == "snapshot_extracted":
        return "run references process-attach-extracted-text for this corpus"
    if row["state"] == SOURCE_READINESS_STATES["EXTRACTABLE"]:
        return "run references process-extract-text-now for this corpus"
    if row["state"] == SOURCE_READINESS_STATES["BLOCKED"]:
        return "add sourceUri or corpus storagePath before extraction"
    return "-"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
