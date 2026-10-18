from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .accession import assignment_created_event_record, resolve_biblicus_workdir
from .catalog import semantic_relation_record
from .env import PAPYRUS_ROOT
from .ids import hash_short, knowledge_corpus_id
from .options import parse_boolean_option
from .reference_attachments import build_extracted_text_attachment_plans
from .records import apply_record_changes, build_record_changes, build_record_changes_targeted_by_id
from .source_readiness import build_extraction_index
from .steering import load_steering_config, require_corpus_config, require_steering_config
from .model_defaults import DEFAULT_LLM_MODEL


IDENTIFIER_TYPES = frozenset({"doi", "arxiv_id", "isbn13", "publisher_item"})

TEXT_EXTRACTION_POLICY = {
    "assignmentTypeKey": "reference.text-extraction",
    "handlerKey": "reference.text-extraction",
    "executionMode": "queued",
    "claimPolicy": "exclusive",
    "defaultClaimTtlSeconds": 3600,
}

IDENTIFIER_BACKFILL_POLICY = {
    "assignmentTypeKey": "reference.identifier-backfill",
    "handlerKey": "reference.identifier-backfill",
    "executionMode": "queued",
    "claimPolicy": "exclusive",
    "defaultClaimTtlSeconds": 3600,
}


def normalize_identifier_types(value: Any, *, default_types: list[str] | None = None) -> list[str]:
    default_types = default_types or ["doi"]
    if isinstance(value, list):
        raw = value
    elif value:
        raw = [part.strip() for part in str(value).split(",") if part.strip()]
    else:
        raw = default_types
    types: list[str] = []
    for entry in raw:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(entry or "").strip().lower()).strip("_")
        if not normalized:
            continue
        if normalized == "arxiv":
            normalized = "arxiv_id"
        elif normalized == "isbn":
            normalized = "isbn13"
        if normalized not in IDENTIFIER_TYPES:
            raise ValueError(f"Unsupported identifier type: {entry}.")
        if normalized not in types:
            types.append(normalized)
    return types or list(default_types)


def timestamp_for_path(value: str | None = None) -> str:
    iso = value or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return re.sub(r"[^0-9A-Za-z]+", "-", iso).strip("-")


def normalize_extraction_stages(value: Any) -> list[str]:
    if isinstance(value, list) and value:
        return [str(entry) for entry in value if str(entry).strip()]
    if isinstance(value, str) and value.strip():
        return [entry.strip() for entry in value.split(",") if entry.strip()]
    return ["pass-through-text", "pdf-text", "metadata-text"]


def reference_text_extraction_assignment_record(
    *,
    corpus_config: dict[str, Any],
    corpus_id: str,
    actor_label: str,
    now: str,
    options: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    assignment_type_key = "reference.text-extraction"
    queue_key = f"{assignment_type_key}#{corpus_id}"
    stages = normalize_extraction_stages(options.get("stage"))
    metadata = {
        "kind": "reference.text-extraction.requested",
        "runId": run_id,
        "corpusKey": corpus_config["key"],
        "corpusId": corpus_id,
        "corpusPath": corpus_config.get("path"),
        "expectedStoragePrefix": corpus_config.get("s3Prefix"),
        "extractionPipeline": None if options.get("configuration") else stages,
        "extractionConfigurationPath": options.get("configuration"),
        "options": {
            key: value
            for key, value in {
                "configuration": options.get("configuration"),
                "stage": stages,
                "force": parse_boolean_option(options.get("force"), False, "--force"),
                "max-workers": options.get("max-workers"),
            }.items()
            if value is not None
        },
        "instructions": (
            "Run Biblicus text extraction against accessioned corpus source files, then register "
            "snapshot-backed extracted_text ReferenceAttachment rows."
        ),
        "assignmentTypePolicy": TEXT_EXTRACTION_POLICY,
    }
    return {
        "id": f"assignment-reference-text-extraction-{hash_short([corpus_id, run_id])}",
        "assignmentTypeKey": assignment_type_key,
        "queueKey": queue_key,
        "queueStatusKey": f"{queue_key}#open",
        "status": "open",
        "priority": 0,
        "title": f"Extract reference text for {corpus_config['key']}",
        "brief": f"Run Biblicus extraction for {corpus_config['key']} and register extracted text attachments.",
        "instructions": metadata["instructions"],
        "metadata": json.dumps(metadata),
        "corpusId": corpus_id,
        "importRunId": None,
        "createdBy": actor_label,
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "assignments",
    }


def build_reference_identifier_backfill_assignment_plan(
    *,
    options: dict[str, Any],
    actor_label: str,
    now: str,
    run_id: str,
    types: list[str] | None = None,
) -> dict[str, Any]:
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus_config)
    assignment_type_key = "reference.identifier-backfill"
    queue_key = f"{assignment_type_key}#{corpus_id}"
    selected_types = types or normalize_identifier_types(options.get("types"))
    use_llm = parse_boolean_option(options.get("use-llm"), False, "--use-llm")
    only_missing = parse_boolean_option(options.get("only-missing"), False, "--only-missing")
    metadata = {
        "kind": "reference.identifier-backfill.requested",
        "runId": run_id,
        "corpusKey": corpus_config["key"],
        "corpusId": corpus_id,
        "types": selected_types,
        "scope": {"versionState": "current", "curationStatus": "all"},
        "resolverMode": "deterministic-first",
        "useLlm": use_llm,
        "llmModel": options.get("llm-model") or DEFAULT_LLM_MODEL,
        "llmReasoningEffort": options.get("llm-reasoning-effort") or "low",
        "sidecarPersistenceMode": "enabled"
        if parse_boolean_option(options.get("persist-sidecars"), True, "--persist-sidecars")
        else "disabled",
        "onlyMissing": only_missing,
        "progressEvery": options.get("progress-every"),
        "writeChunkSize": int(options.get("write-chunk-size") or 100),
        "maxCount": options.get("max-count"),
        "steeringConfigPath": steering_config.get("configPath") or options.get("config"),
        "corpusPath": corpus_config.get("path"),
        "assignmentTypePolicy": IDENTIFIER_BACKFILL_POLICY,
    }
    assignment = {
        "id": f"assignment-reference-identifier-backfill-{hash_short([corpus_id, run_id])}",
        "assignmentTypeKey": assignment_type_key,
        "queueKey": queue_key,
        "queueStatusKey": f"{queue_key}#open",
        "status": "open",
        "priority": 45,
        "title": f"Identifier backfill for {corpus_config['key']}",
        "brief": (
            f"Resolve {', '.join(selected_types)} identifiers for current references, write semantic "
            "identifier relations, and persist provenance to metadata and sidecars."
        ),
        "instructions": (
            "Use deterministic identifier resolution first, use LLM adjudication only when ambiguous, "
            "create identifier semantic relations, and run one corpus reindex after sidecar updates."
        ),
        "corpusId": corpus_id,
        "importRunId": None,
        "createdBy": actor_label,
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "assignments",
        "metadata": json.dumps(metadata),
    }
    records = [
        {"modelName": "Assignment", "expected": assignment},
        {"modelName": "AssignmentEvent", "expected": assignment_created_event_record(assignment, actor_label, now)},
        semantic_relation_record(
            {
                "predicate": "requests_work_on",
                "subjectKind": "assignment",
                "subjectId": assignment["id"],
                "subjectLineageId": assignment["id"],
                "subjectVersionNumber": None,
                "objectKind": "knowledge_corpus",
                "objectId": corpus_id,
                "objectLineageId": corpus_id,
                "objectVersionNumber": None,
                "rank": 1,
                "importedAt": now,
                "metadata": {
                    "kind": "reference.identifier-backfill.requests_work_on",
                    "corpusKey": corpus_config["key"],
                    "types": selected_types,
                },
            }
        ),
    ]
    return {
        "assignment": assignment,
        "records": records,
        "metadata": metadata,
        "corpusId": corpus_id,
        "corpusConfig": corpus_config,
    }


def build_text_extraction_assignment_records(
    *,
    corpus_config: dict[str, Any],
    corpus_id: str,
    actor_label: str,
    now: str,
    options: dict[str, Any],
    run_id: str,
) -> list[dict[str, Any]]:
    assignment = reference_text_extraction_assignment_record(
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        actor_label=actor_label,
        now=now,
        options=options,
        run_id=run_id,
    )
    return [
        {"modelName": "Assignment", "expected": assignment},
        {"modelName": "AssignmentEvent", "expected": assignment_created_event_record(assignment, actor_label, now)},
        semantic_relation_record(
            {
                "predicate": "requests_work_on",
                "subjectKind": "assignment",
                "subjectId": assignment["id"],
                "subjectLineageId": assignment["id"],
                "subjectVersionNumber": None,
                "objectKind": "knowledge_corpus",
                "objectId": corpus_id,
                "objectLineageId": corpus_id,
                "objectVersionNumber": None,
                "rank": 1,
                "importedAt": now,
                "metadata": {
                    "kind": "reference.text-extraction.requests_work_on",
                    "corpusKey": corpus_config["key"],
                },
            }
        ),
    ]


def run_biblicus_text_extraction_for_corpus(
    *,
    corpus_path: Path,
    biblicus_workdir: Path,
    run_dir: Path,
    options: dict[str, Any],
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = run_dir / "biblicus-extract.stdout.log"
    stderr_log = run_dir / "biblicus-extract.stderr.log"
    args = ["run", "--extra", "topic-modeling", "biblicus", "extract", "build", "--corpus", str(corpus_path)]
    if options.get("configuration"):
        args.extend(["--configuration", str(options["configuration"])])
    else:
        for stage in normalize_extraction_stages(options.get("stage")):
            args.extend(["--stage", stage])
    if parse_boolean_option(options.get("force"), False, "--force"):
        args.append("--force")
    if options.get("max-workers"):
        args.extend(["--max-workers", str(options["max-workers"])])
    completed = subprocess.run(["uv", *args], cwd=biblicus_workdir, capture_output=True, text=True, check=False)
    stdout_log.write_text(completed.stdout or "", encoding="utf-8")
    stderr_log.write_text(completed.stderr or "", encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"Biblicus text extraction failed for {corpus_path}. See {stderr_log}."
        )
    return {
        "label": "biblicus-extract-build",
        "executable": "uv",
        "args": args,
        "stdoutLogPath": str(stdout_log),
        "stderrLogPath": str(stderr_log),
        "exitStatus": completed.returncode,
    }


def execute_reference_text_extraction_assignment(client, assignment: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    from .assignments import assignment_metadata
    from .newsroom_summary import update_newsroom_summary_after_extracted_text_attachments

    if assignment.get("assignmentTypeKey") != "reference.text-extraction":
        raise ValueError(
            f"Assignment {assignment['id']} is {assignment.get('assignmentTypeKey')}; expected reference.text-extraction."
        )
    if assignment.get("status") != "claimed":
        raise ValueError(
            f"Assignment {assignment['id']} must be claimed before execution (current={assignment.get('status')})."
        )
    metadata = assignment_metadata(client, assignment)
    if metadata.get("kind") != "reference.text-extraction.requested":
        raise ValueError(f"Assignment {assignment['id']} metadata is not reference.text-extraction.requested.")
    run_id = options.get("run-id") or metadata.get("runId") or f"reference-text-extraction-{hash_short([assignment['id']])}"
    run_dir = PAPYRUS_ROOT / ".papyrus-runs" / run_id
    manifest_path = run_dir / "execution-manifest.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    steering_config = load_steering_config(options.get("config") or metadata.get("steeringConfigPath")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, metadata["corpusKey"], "assignment.metadata.corpusKey")
    corpus_id = knowledge_corpus_id(corpus_config)
    corpus_path = Path(corpus_config["path"]).resolve()
    biblicus_workdir = resolve_biblicus_workdir(options)
    actor_label = options.get("actor") or options.get("assignee-key") or "papyrus-cli"
    extraction_result = run_biblicus_text_extraction_for_corpus(
        corpus_path=corpus_path,
        biblicus_workdir=biblicus_workdir,
        run_dir=run_dir,
        options={**metadata.get("options", {}), **options},
    )
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    extraction_index = build_extraction_index(corpus_config.get("path"))
    plans = build_extracted_text_attachment_plans(
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        references=references,
        attachments=attachments,
        extraction_index=extraction_index,
    )
    records = [plan["record"] for plan in plans if plan.get("record")]
    changes = build_record_changes(client, records)
    apply_record_changes(client, changes)
    update_newsroom_summary_after_extracted_text_attachments(
        client,
        changes,
        actor_label=actor_label,
        reason=f"references text extraction {assignment['id']}",
    )
    import_summary = {
        "importedRecords": len([change for change in changes if change.get("action") != "noop"]),
        "importRuns": [],
    }
    manifest = {
        "runId": run_id,
        "assignmentId": assignment["id"],
        "assignmentTypeKey": assignment["assignmentTypeKey"],
        "status": "executed",
        "corpusId": corpus_id,
        "corpusPath": str(corpus_path),
        "extraction": extraction_result,
        "extractionSnapshots": extraction_index.snapshot_ids,
        "plannedTextAttachments": len(records),
        "importSummary": import_summary,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "assignmentId": assignment["id"],
        "runId": run_id,
        "runDir": str(run_dir),
        "manifestPath": str(manifest_path),
        "importSummary": import_summary,
        "commandResults": [extraction_result],
    }


def doi_backfill_compatibility_flags(flags: list[str]) -> list[str]:
    next_flags: list[str] = []
    index = 0
    while index < len(flags):
        flag = flags[index]
        if flag == "--only-missing-doi":
            next_flags.append("--only-missing")
            if index + 1 < len(flags) and not flags[index + 1].startswith("--"):
                next_flags.append(flags[index + 1])
                index += 1
            index += 1
            continue
        next_flags.append(flag)
        index += 1
    if not any(flag == "--types" for flag in next_flags):
        next_flags.extend(["--types", "doi"])
    return next_flags
