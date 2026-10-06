from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .env import graphql_endpoint, storage_bucket_from_amplify_outputs
from .graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client
from .model_attachments import (
    build_json_model_payload_attachment,
    model_attachment_id,
    upload_attachment_body,
)
from .options import normalize_non_negative_integer, parse_comma_list, parse_options
from .records import apply_record_changes, build_record_change_from_current, is_missing_graphql_model_error
from .steering import load_steering_config, selected_corpus_configs

REHYDRATION_MODELS: tuple[str, ...] = (
    "KnowledgeCorpus",
    "KnowledgeImportRun",
    "ProcedureDefinition",
    "ProcedureVersion",
    "ProcedureRun",
    "UserRoleAssignment",
    "NewsroomSection",
    "CategorySet",
    "Category",
    "SteeringProposal",
    "SteeringDecision",
    "Reference",
    "ReferenceAttachment",
    "KnowledgeRawPayload",
    "KnowledgeArtifact",
    "Assignment",
    "AssignmentEvent",
    "MessageThread",
    "Message",
    "SemanticNode",
    "SemanticRelationType",
    "SemanticRelation",
    "Tag",
    "Item",
    "MediaAsset",
    "ItemTag",
    "Edition",
    "EditionItem",
    "PublishedItem",
    "PublishedMediaAsset",
    "PublishedEdition",
    "PublishedEditionItem",
    "PublishedCategorySet",
    "PublishedCategory",
)

REHYDRATION_MODEL_ORDER: tuple[str, ...] = (
    "KnowledgeCorpus",
    "KnowledgeImportRun",
    "ProcedureDefinition",
    "ProcedureVersion",
    "ProcedureRun",
    "UserRoleAssignment",
    "NewsroomSection",
    "CategorySet",
    "Category",
    "SteeringProposal",
    "SteeringDecision",
    "Reference",
    "ReferenceAttachment",
    "KnowledgeRawPayload",
    "KnowledgeArtifact",
    "Assignment",
    "AssignmentEvent",
    "MessageThread",
    "Message",
    "SemanticNode",
    "SemanticRelationType",
    "SemanticRelation",
    "Tag",
    "Item",
    "MediaAsset",
    "ItemTag",
    "Edition",
    "EditionItem",
    "PublishedItem",
    "PublishedMediaAsset",
    "PublishedEdition",
    "PublishedEditionItem",
    "PublishedCategorySet",
    "PublishedCategory",
)

OWNER_KIND_BY_MODEL: dict[str, str] = {
    "Assignment": "assignment",
    "AssignmentEvent": "assignmentEvent",
    "Category": "category",
    "CategorySet": "categorySet",
    "Edition": "edition",
    "EditionItem": "editionItem",
    "Item": "item",
    "ItemTag": "itemTag",
    "KnowledgeArtifact": "knowledgeArtifact",
    "KnowledgeCorpus": "knowledgeCorpus",
    "KnowledgeImportRun": "knowledgeImportRun",
    "KnowledgeRawPayload": "knowledgeRawPayload",
    "MediaAsset": "mediaAsset",
    "Message": "message",
    "MessageThread": "messageThread",
    "NewsroomSection": "newsroomSection",
    "ProcedureDefinition": "procedureDefinition",
    "ProcedureRun": "procedureRun",
    "ProcedureVersion": "procedureVersion",
    "PublishedEdition": "publishedEdition",
    "PublishedEditionItem": "publishedEditionItem",
    "PublishedItem": "publishedItem",
    "PublishedMediaAsset": "publishedMediaAsset",
    "PublishedCategorySet": "publishedCategorySet",
    "PublishedCategory": "publishedCategory",
    "Reference": "reference",
    "ReferenceAttachment": "referenceAttachment",
    "SemanticNode": "semanticNode",
    "SemanticRelation": "semanticRelation",
    "SemanticRelationType": "semanticRelationType",
    "SteeringDecision": "steeringDecision",
    "SteeringProposal": "steeringProposal",
    "Tag": "tag",
    "UserRoleAssignment": "userRoleAssignment",
}
MODEL_BY_OWNER_KIND = {owner_kind: model_name for model_name, owner_kind in OWNER_KIND_BY_MODEL.items()}

RECORD_ROLE = "record"
RECORD_SORT_KEY = "record"
RECORD_FILENAME = "record.json"
RECORD_SCHEMA_VERSION = 1
RECORD_CONTRACT = "papyrus.rehydration.record"

INLINE_FIELD_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("Message", "content"),
    ("Message", "metadata"),
    ("Message", "summary"),
    ("Assignment", "summary"),
    ("AssignmentEvent", "note"),
    ("AssignmentEvent", "metadata"),
    ("SemanticRelation", "metadata"),
    ("Item", "body"),
    ("Item", "layout"),
    ("Item", "editorial"),
    ("Edition", "layoutPlan"),
    ("Edition", "metadata"),
    ("PublishedItem", "body"),
    ("PublishedItem", "layout"),
    ("PublishedItem", "editorial"),
    ("PublishedEdition", "layoutPlan"),
    ("PublishedEdition", "metadata"),
    ("PublishedCategorySet", "metadata"),
    ("PublishedCategory", "metadata"),
)


@dataclass
class RecordAudit:
    model_name: str
    record_id: str
    owner_kind: str
    expected_attachment_id: str
    expected_storage_path: str
    expected_sha256: str
    expected_bytes: int
    status: str
    current_attachment_id: str | None
    current_sha256: str | None
    current_bytes: int | None


def rehydration_audit_records(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    models = resolve_rehydration_models(options)
    preflight = rehydration_preflight(options)
    report = collect_rehydration_audit(client, models)
    payload = {
        "ok": report["summary"]["missing"] == 0 and report["summary"]["stale"] == 0,
        "command": "rehydration audit-records",
        "endpoint": graphql_endpoint(),
        "preflight": preflight,
        "models": models,
        "summary": report["summary"],
        "skippedModels": report["skippedModels"],
        "inlineFieldCandidates": report["inlineFieldCandidates"],
        "records": report["records"],
    }
    if options.get("output"):
        with open(str(options["output"]), "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2) + "\n")
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return

    print(f"rehydration\taudit\tendpoint\t{payload['endpoint']}")
    print(f"rehydration\taudit\tmodels\t{len(models)}")
    print(f"rehydration\taudit\trecords\t{report['summary']['total']}")
    print(f"rehydration\taudit\tok\t{report['summary']['ok']}")
    print(f"rehydration\taudit\tmissing\t{report['summary']['missing']}")
    print(f"rehydration\taudit\tstale\t{report['summary']['stale']}")
    if report["skippedModels"]:
        print(f"rehydration\taudit\tskipped-models\t{','.join(report['skippedModels'])}")
    print(f"rehydration\taudit\tinline-candidates\t{len(report['inlineFieldCandidates'])}")
    limit = normalize_non_negative_integer(options.get("limit"), "--limit")
    if limit is None:
        limit = 50
    selected = report["records"] if limit == 0 else report["records"][:limit]
    for entry in selected:
        print(
            "\t".join(
                [
                    "rehydration-record",
                    entry["status"],
                    entry["modelName"],
                    entry["recordId"],
                    entry["expectedAttachmentId"],
                    entry.get("currentAttachmentId") or "-",
                ]
            )
        )
    if len(report["records"]) > len(selected):
        print(f"rehydration\taudit\tomitted\t{len(report['records']) - len(selected)}")


def rehydration_backfill_records(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    models = resolve_rehydration_models(options)
    preflight = rehydration_preflight(options)
    assert_bucket_alignment_for_apply(options, preflight)
    report = collect_rehydration_audit(client, models)
    actionable = [entry for entry in report["audits"] if entry.status in {"missing", "stale"}]

    if not options.get("apply"):
        result = {
            "ok": True,
            "command": "rehydration backfill-records",
            "mode": "dry-run",
            "endpoint": graphql_endpoint(),
            "preflight": preflight,
            "models": models,
            "planned": len(actionable),
            "missing": report["summary"]["missing"],
            "stale": report["summary"]["stale"],
            "skippedModels": report["skippedModels"],
            "next": "poetry run papyrus-content rehydration backfill-records --apply",
        }
        if options.get("json"):
            print(json.dumps(result, indent=2))
        else:
            print(f"rehydration\tbackfill\tmode\tdry-run")
            print(f"rehydration\tbackfill\tplanned\t{len(actionable)}")
            print("rehydration\tbackfill\tapply\tskipped\tpass --apply to write record.json attachments")
        return

    now = utc_now()
    updates = 0
    creates = 0
    for audit in actionable:
        record = client.get_record(audit.model_name, audit.record_id)
        if not record:
            continue
        attachment_record = build_record_attachment_record(
            model_name=audit.model_name,
            record=record,
            now=now,
        )
        upload_attachment_body(client, attachment_record["attachment"], attachment_record["body"])
        client.upsert("ModelAttachment", attachment_record["attachment"])
        if audit.status == "missing":
            creates += 1
        else:
            updates += 1

    result = {
        "ok": True,
        "command": "rehydration backfill-records",
        "mode": "apply",
        "endpoint": graphql_endpoint(),
        "preflight": preflight,
        "models": models,
        "skippedModels": report["skippedModels"],
        "created": creates,
        "updated": updates,
        "applied": creates + updates,
    }
    if options.get("json"):
        print(json.dumps(result, indent=2))
    else:
        print(f"rehydration\tbackfill\tcreated\t{creates}")
        print(f"rehydration\tbackfill\tupdated\t{updates}")
        print(f"rehydration\tbackfill\tapplied\t{creates + updates}")


def rehydration_export_manifest(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("output"):
        raise ValueError("rehydration export-manifest requires --output <manifest.json>.")
    client, _ = create_authoring_client()
    models = resolve_rehydration_models(options)
    preflight = rehydration_preflight(options)
    report = collect_rehydration_audit(client, models)
    manifest = {
        "schemaVersion": 1,
        "manifestKind": "papyrus-rehydration-manifest",
        "generatedAt": utc_now(),
        "endpoint": graphql_endpoint(),
        "expectedBucket": storage_bucket_from_amplify_outputs(),
        "preflight": preflight,
        "models": models,
        "skippedModels": report["skippedModels"],
        "summary": report["summary"],
        "records": report["records"],
        "inlineFieldCandidates": report["inlineFieldCandidates"],
    }
    with open(str(options["output"]), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, indent=2) + "\n")
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "rehydration export-manifest", "output": options["output"], "count": len(report["records"])}, indent=2))
    else:
        print(f"rehydration\texport-manifest\t{len(report['records'])}\t{options['output']}")


def rehydration_hydrate(flags: list[str]) -> None:
    options = parse_options(flags)
    source_bucket = str(options.get("source-bucket") or "").strip()
    if not source_bucket:
        raise ValueError("rehydration hydrate requires --source-bucket <bucket>.")
    source_prefix = str(options.get("source-prefix") or "newsroom/payloads/").strip()
    if not source_prefix.endswith("/"):
        source_prefix = f"{source_prefix}/"
    client, _ = create_authoring_client()
    preflight = rehydration_preflight(options)
    aws_profile = normalize_optional_string(options.get("aws-profile"))
    objects = list_s3_objects(source_bucket, source_prefix, profile=aws_profile)
    record_objects = [obj for obj in objects if str(obj.get("Key") or "").endswith("/record/record.json")]

    hydrated_records: dict[tuple[str, str], dict[str, Any]] = {}
    record_attachment_rows: dict[str, dict[str, Any]] = {}
    for obj in record_objects:
        key = str(obj.get("Key") or "")
        owner_kind, owner_id = owner_from_record_key(key)
        if not owner_kind or not owner_id:
            continue
        model_name = MODEL_BY_OWNER_KIND.get(owner_kind)
        if not model_name:
            continue
        body = read_s3_object_text(source_bucket, key, profile=aws_profile)
        if not body:
            continue
        payload = json.loads(body)
        if payload.get("contract") != RECORD_CONTRACT:
            continue
        if payload.get("modelName") != model_name:
            continue
        record = payload.get("record")
        if not isinstance(record, dict):
            continue
        record_id = str(record.get("id") or "")
        if not record_id:
            continue
        hydrated_records[(model_name, record_id)] = record
        now = normalize_iso(payload.get("capturedAt")) or utc_now()
        buffer = body.encode("utf-8")
        record_attachment_rows[model_attachment_id(owner_kind, record_id, RECORD_ROLE, RECORD_SORT_KEY)] = {
            "id": model_attachment_id(owner_kind, record_id, RECORD_ROLE, RECORD_SORT_KEY),
            "ownerKind": owner_kind,
            "ownerId": record_id,
            "ownerLineageId": str(record.get("lineageId") or record_id),
            "ownerVersionNumber": record.get("versionNumber"),
            "ownerVersionKey": semantic_version_key(owner_kind, record_id),
            "role": RECORD_ROLE,
            "sortKey": RECORD_SORT_KEY,
            "storagePath": key,
            "filename": RECORD_FILENAME,
            "mediaType": "application/json",
            "byteSize": len(buffer),
            "sha256": hashlib.sha256(buffer).hexdigest(),
            "etag": normalize_etag(obj.get("ETag")),
            "importRunId": record.get("importRunId"),
            "createdAt": now,
            "updatedAt": now,
            "status": "active",
        }

    counts_by_model: dict[str, int] = {}
    for model_name, _ in hydrated_records:
        counts_by_model[model_name] = counts_by_model.get(model_name, 0) + 1

    if not options.get("apply"):
        result = {
            "ok": True,
            "command": "rehydration hydrate",
            "mode": "dry-run",
            "endpoint": graphql_endpoint(),
            "preflight": preflight,
            "sourceBucket": source_bucket,
            "sourcePrefix": source_prefix,
            "recordObjects": len(record_objects),
            "plannedRecords": len(hydrated_records),
            "plannedModelAttachments": len(record_attachment_rows),
            "byModel": dict(sorted(counts_by_model.items())),
            "next": f"poetry run papyrus-content rehydration hydrate --source-bucket {source_bucket} --apply",
        }
        if options.get("json"):
            print(json.dumps(result, indent=2))
        else:
            print(f"rehydration\thydrate\tmode\tdry-run")
            print(f"rehydration\thydrate\trecord-objects\t{len(record_objects)}")
            print(f"rehydration\thydrate\tplanned-records\t{len(hydrated_records)}")
        return

    ordered_models = [model for model in REHYDRATION_MODEL_ORDER if any(key[0] == model for key in hydrated_records.keys())]
    ordered_models += sorted({model for model, _ in hydrated_records.keys()} - set(ordered_models))

    applied = 0
    for model_name in ordered_models:
        model_rows = [record for (model, _), record in hydrated_records.items() if model == model_name]
        model_rows.sort(key=lambda row: str(row.get("id") or ""))
        for row in model_rows:
            client.upsert(model_name, row)
            applied += 1

    attachment_changes: list[dict[str, Any]] = []
    for attachment in sorted(record_attachment_rows.values(), key=lambda row: str(row.get("id") or "")):
        current = client.get_record("ModelAttachment", attachment["id"])
        attachment_changes.append(build_record_change_from_current("ModelAttachment", attachment, current))
    apply_record_changes(client, attachment_changes)

    result = {
        "ok": True,
        "command": "rehydration hydrate",
        "mode": "apply",
        "endpoint": graphql_endpoint(),
        "preflight": preflight,
        "sourceBucket": source_bucket,
        "sourcePrefix": source_prefix,
        "recordObjects": len(record_objects),
        "appliedRecords": applied,
        "appliedModelAttachments": sum(1 for change in attachment_changes if change.get("action") != "noop"),
        "byModel": dict(sorted(counts_by_model.items())),
    }
    if options.get("json"):
        print(json.dumps(result, indent=2))
    else:
        print(f"rehydration\thydrate\tapplied-records\t{applied}")
        print(f"rehydration\thydrate\tapplied-model-attachments\t{result['appliedModelAttachments']}")


def resolve_rehydration_models(options: dict[str, Any]) -> list[str]:
    requested = parse_comma_list(options.get("models"))
    if not requested:
        return list(REHYDRATION_MODELS)
    allowed = set(REHYDRATION_MODELS)
    unsupported = [model for model in requested if model not in allowed]
    if unsupported:
        raise ValueError(f"Unsupported rehydration model(s): {', '.join(sorted(unsupported))}.")
    return requested


def collect_rehydration_audit(client: PapyrusGraphQLAuthoringClient, models: list[str]) -> dict[str, Any]:
    audits: list[RecordAudit] = []
    rows_by_model: dict[str, list[dict[str, Any]]] = {}
    skipped_models: list[str] = []
    for model_name in models:
        try:
            rows_by_model[model_name] = client.list_records(model_name)
        except RuntimeError as error:
            if is_not_authorized_error(error) or is_missing_graphql_model_error(error, model_name):
                skipped_models.append(model_name)
                rows_by_model[model_name] = []
                continue
            raise
    inline_candidates = compute_inline_field_candidates(rows_by_model)

    for model_name in models:
        owner_kind = owner_kind_for_model(model_name)
        for row in rows_by_model[model_name]:
            record_id = str(row.get("id") or "")
            if not record_id:
                continue
            attachment_entry = build_record_attachment_record(model_name=model_name, record=row, now=utc_now())
            attachment = attachment_entry["attachment"]
            current = client.get_record("ModelAttachment", attachment["id"])
            status = "ok"
            current_sha = normalize_optional_string(current.get("sha256") if current else None)
            current_bytes = current.get("byteSize") if current else None
            if not current:
                status = "missing"
            elif current_sha != attachment.get("sha256") or normalize_int(current_bytes) != normalize_int(attachment.get("byteSize")):
                status = "stale"
            audits.append(
                RecordAudit(
                    model_name=model_name,
                    record_id=record_id,
                    owner_kind=owner_kind,
                    expected_attachment_id=str(attachment["id"]),
                    expected_storage_path=str(attachment["storagePath"]),
                    expected_sha256=str(attachment.get("sha256") or ""),
                    expected_bytes=normalize_int(attachment.get("byteSize")) or 0,
                    status=status,
                    current_attachment_id=str(current.get("id") or "") if current else None,
                    current_sha256=current_sha,
                    current_bytes=normalize_int(current_bytes),
                )
            )

    audits.sort(key=lambda entry: (entry.model_name, entry.record_id))
    summary = {
        "total": len(audits),
        "ok": sum(1 for entry in audits if entry.status == "ok"),
        "missing": sum(1 for entry in audits if entry.status == "missing"),
        "stale": sum(1 for entry in audits if entry.status == "stale"),
    }
    records = [
        {
            "modelName": entry.model_name,
            "recordId": entry.record_id,
            "ownerKind": entry.owner_kind,
            "status": entry.status,
            "expectedAttachmentId": entry.expected_attachment_id,
            "expectedStoragePath": entry.expected_storage_path,
            "expectedSha256": entry.expected_sha256,
            "expectedBytes": entry.expected_bytes,
            "currentAttachmentId": entry.current_attachment_id,
            "currentSha256": entry.current_sha256,
            "currentBytes": entry.current_bytes,
        }
        for entry in audits
    ]
    return {
        "audits": audits,
        "records": records,
        "summary": summary,
        "skippedModels": skipped_models,
        "inlineFieldCandidates": inline_candidates,
    }


def compute_inline_field_candidates(rows_by_model: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for model_name, field_name in INLINE_FIELD_CANDIDATES:
        rows = rows_by_model.get(model_name) or []
        populated = 0
        estimated_bytes = 0
        for row in rows:
            value = row.get(field_name)
            if value in (None, "", [], {}):
                continue
            populated += 1
            estimated_bytes += len(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        if populated == 0:
            continue
        candidates.append(
            {
                "modelName": model_name,
                "field": field_name,
                "rowsWithValue": populated,
                "estimatedBytes": estimated_bytes,
            }
        )
    candidates.sort(key=lambda entry: (-entry["estimatedBytes"], entry["modelName"], entry["field"]))
    return candidates


def build_record_attachment_record(*, model_name: str, record: dict[str, Any], now: str) -> dict[str, Any]:
    owner_kind = owner_kind_for_model(model_name)
    record_id = str(record.get("id") or "")
    if not record_id:
        raise ValueError(f"{model_name} record is missing id")
    canonical_record = canonicalize_value(record)
    canonical_bytes = canonical_json_bytes(canonical_record)
    canonical_hash = hashlib.sha256(canonical_bytes).hexdigest()
    captured_at = stable_record_timestamp(record)
    payload = {
        "schemaVersion": RECORD_SCHEMA_VERSION,
        "contract": RECORD_CONTRACT,
        "modelName": model_name,
        "recordVersion": 1,
        "recordId": record_id,
        "capturedAt": captured_at,
        "canonicalHash": canonical_hash,
        "record": canonical_record,
    }
    attachment_entry = build_json_model_payload_attachment(
        {
            "ownerKind": owner_kind,
            "ownerId": record_id,
            "ownerLineageId": str(record.get("lineageId") or record_id),
            "ownerVersionNumber": record.get("versionNumber"),
            "ownerVersionKey": semantic_version_key(owner_kind, record_id),
            "role": RECORD_ROLE,
            "sortKey": RECORD_SORT_KEY,
            "filename": RECORD_FILENAME,
            "content": payload,
            "importRunId": record.get("importRunId"),
            "now": now,
        }
    )
    return {
        "payload": payload,
        "attachment": attachment_entry["attachment"],
        "body": attachment_entry["body"],
    }


def stable_record_timestamp(record: dict[str, Any]) -> str:
    for field_name in ("updatedAt", "createdAt", "versionCreatedAt", "importedAt", "publishedAt", "generatedAt"):
        value = normalize_iso(record.get(field_name))
        if value:
            return value
    return "unknown"


def canonicalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key in sorted(value.keys()):
            item = canonicalize_value(value[key])
            if item is None:
                continue
            normalized[str(key)] = item
        return normalized
    if isinstance(value, list):
        return [canonicalize_value(item) for item in value]
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return value
    if value is None:
        return None
    return value


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def rehydration_preflight(options: dict[str, Any]) -> dict[str, Any]:
    profile = str(options.get("aws-profile") or "").strip() or None
    caller = aws_caller_identity(profile)
    expected_bucket = storage_bucket_from_amplify_outputs()
    configured_buckets = steering_buckets(options.get("config"), options.get("corpus-key"))
    return {
        "aws": {
            "profile": profile,
            "callerIdentity": caller,
        },
        "bucket": {
            "expectedFromAmplifyOutputs": expected_bucket,
            "configuredFromSteering": configured_buckets,
            "mismatch": bool(expected_bucket and configured_buckets and any(bucket != expected_bucket for bucket in configured_buckets)),
        },
    }


def assert_bucket_alignment_for_apply(options: dict[str, Any], preflight: dict[str, Any]) -> None:
    if not options.get("apply"):
        return
    if options.get("force"):
        return
    bucket = preflight.get("bucket") or {}
    if bucket.get("mismatch"):
        raise ValueError(
            "Refusing rehydration --apply because steering-config buckets do not match amplify_outputs bucket. "
            "Pass --force only when you intentionally target a different bucket/account."
        )


def steering_buckets(config_path: Any, corpus_key: Any) -> list[str]:
    config = load_steering_config(config_path)
    if not config:
        return []
    buckets: list[str] = []
    for corpus in selected_corpus_configs(config, corpus_key):
        prefix = str(corpus.get("s3Prefix") or "")
        if prefix.startswith("s3://"):
            bucket = prefix[5:].split("/", 1)[0].strip()
            if bucket:
                buckets.append(bucket)
    return sorted(set(buckets))


def aws_caller_identity(profile: str | None) -> dict[str, Any] | None:
    args = ["aws", "sts", "get-caller-identity", "--output", "json"]
    if profile:
        args.extend(["--profile", profile])
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        return {"ok": False, "error": stderr}
    try:
        parsed = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid-json"}
    return {
        "ok": True,
        "account": parsed.get("Account"),
        "arn": parsed.get("Arn"),
        "userId": parsed.get("UserId"),
    }


def owner_kind_for_model(model_name: str) -> str:
    owner_kind = OWNER_KIND_BY_MODEL.get(model_name)
    if not owner_kind:
        raise ValueError(f"No owner kind mapping is defined for {model_name}.")
    return owner_kind


def semantic_version_key(owner_kind: str, owner_id: str) -> str:
    return f"{owner_kind}#{owner_id}"


def list_s3_objects(bucket: str, prefix: str, *, profile: str | None = None) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    continuation: str | None = None
    while True:
        args = [
            "aws",
            "s3api",
            "list-objects-v2",
            "--bucket",
            bucket,
            "--prefix",
            prefix,
            "--output",
            "json",
        ]
        if continuation:
            args.extend(["--continuation-token", continuation])
        if profile:
            args.extend(["--profile", profile])
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"Failed to list s3://{bucket}/{prefix}: {detail}")
        payload = json.loads(result.stdout or "{}")
        objects.extend(payload.get("Contents") or [])
        if not payload.get("IsTruncated"):
            break
        continuation = payload.get("NextContinuationToken")
        if not continuation:
            break
    return objects


def read_s3_object_text(bucket: str, key: str, *, profile: str | None = None) -> str:
    args = ["aws", "s3", "cp", f"s3://{bucket}/{key}", "-"]
    if profile:
        args.extend(["--profile", profile])
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Failed to read s3://{bucket}/{key}: {detail}")
    return result.stdout.decode("utf-8", errors="replace")


def owner_from_record_key(key: str) -> tuple[str | None, str | None]:
    parts = [segment for segment in str(key).split("/") if segment]
    if len(parts) < 6:
        return None, None
    # newsroom/payloads/<ownerKind>/<ownerId>/record/record.json
    if parts[0] != "newsroom" or parts[1] != "payloads":
        return None, None
    owner_kind = parts[2]
    owner_id = parts[3]
    role = parts[4]
    filename = parts[5]
    if role != RECORD_ROLE or filename != RECORD_FILENAME:
        return None, None
    return owner_kind, owner_id


def normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_iso(value: Any) -> str | None:
    text = normalize_optional_string(value)
    if not text:
        return None
    return text


def normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_etag(value: Any) -> str | None:
    text = normalize_optional_string(value)
    if not text:
        return None
    return text.replace('"', "")


def is_not_authorized_error(error: Exception) -> bool:
    message = str(error).lower()
    return "not authorized" in message or "unauthorized" in message or "access denied" in message


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
