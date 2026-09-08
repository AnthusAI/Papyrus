from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .ids import hash_short, knowledge_corpus_id, reference_lineage_id_for, safe_id
from .source_site_plugins import youtube_video_id_from_uri
from .message_contract import build_canonical_message_expected
from .reference_policy import (
    normalize_reference_curation_status,
    normalize_reference_rejection_reason_code,
)
from .relation_types import semantic_relation_type_fields_for_predicate


def catalog_items(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    items = catalog.get("items") or catalog.get("references") or catalog.get("records") or []
    if isinstance(items, list):
        return items
    if isinstance(items, dict):
        return list(items.values())
    return []


def catalog_external_item_id_for(item: dict[str, Any]) -> str | None:
    existing = _string_or_null(item.get("item_id") or item.get("externalItemId") or item.get("id"))
    if existing:
        return existing
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    source_uri = _string_or_null(
        item.get("source_uri")
        or item.get("sourceUri")
        or metadata.get("source_uri")
        or metadata.get("sourceUri")
        or item.get("url")
        or item.get("uri")
    )
    if not source_uri:
        return None
    video_id = youtube_video_id_from_uri(source_uri)
    if video_id:
        return f"yt-{safe_id(video_id)}"
    return f"url-ref-{hash_short(source_uri)}"


def catalog_item_with_external_item_id(item: dict[str, Any]) -> dict[str, Any]:
    item_id = catalog_external_item_id_for(item)
    if not item_id:
        return item
    enriched = {**item, "item_id": item_id}
    if not enriched.get("id"):
        enriched["id"] = item_id
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    source_uri = _string_or_null(
        item.get("source_uri")
        or item.get("sourceUri")
        or metadata.get("source_uri")
        or metadata.get("sourceUri")
    )
    if source_uri and youtube_video_id_from_uri(source_uri):
        media_type = _string_or_null(item.get("media_type") or item.get("mediaType"))
        if not media_type:
            enriched["media_type"] = "video/youtube"
    return enriched


def build_prepared_reference_catalog(catalog: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    corpus_key = options.get("corpusKey") or (options.get("corpusConfig") or {}).get("key") or (catalog.get("corpus") or {}).get("key")
    publication_name = options.get("publicationName") or "the publication"
    items_value = catalog.get("items") or catalog.get("references") or catalog.get("records") or []
    prepared_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def prepare_item(item: dict[str, Any]) -> dict[str, Any]:
        item = catalog_item_with_external_item_id(item)
        if ingestion_rationale_from(item):
            return item
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        title = _string_or_null(item.get("title") or metadata.get("title")) or _string_or_null(
            item.get("id") or item.get("item_id") or item.get("externalItemId")
        ) or "Untitled source material"
        abstract = _string_or_null(
            item.get("abstract") or metadata.get("abstract") or item.get("summary") or metadata.get("summary")
        )
        source_uri = _string_or_null(
            item.get("source_uri")
            or item.get("sourceUri")
            or metadata.get("source_uri")
            or metadata.get("sourceUri")
            or item.get("url")
            or item.get("uri")
        )
        media_type = _string_or_null(item.get("media_type") or item.get("mediaType") or metadata.get("media_type"))
        source_clause = f" Source: {source_uri}." if source_uri else ""
        type_clause = f" Media type: {media_type}." if media_type else ""
        focus_clause = f" It is being staged for the {corpus_key} corpus." if corpus_key else ""
        summary_clause = (
            f" Summary: {abstract}"
            if abstract
            else " Summary is not yet available in the catalog; review the source material during curation."
        )
        return {
            **item,
            "ingestion_rationale": (
                f"{title} is a reference prospect for {publication_name}.{focus_clause}{type_clause}"
                f"{source_clause}{summary_clause}"
            ),
        }

    output = {
        **catalog,
        "prepared_at": prepared_at,
        "preparation": {
            "tool": "papyrus references prepare-catalog",
            "corpus_key": corpus_key,
            "rationale_policy": "derived-from-title-abstract-source-when-missing",
        },
    }
    if isinstance(items_value, list):
        output["items"] = [prepare_item(item) for item in items_value]
    elif isinstance(items_value, dict):
        output["items"] = {key: prepare_item(value) for key, value in items_value.items()}
    else:
        output["items"] = []
    output.pop("references", None)
    output.pop("records", None)
    return output


def build_reference_catalog_registration_records(catalog: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    now = options.get("importedAt") or _utc_now()
    corpus_config = options.get("corpusConfig") or options.get("corpus") or {}
    corpus_id = options.get("corpusId") or knowledge_corpus_id(corpus_config)
    classifier_id = options.get("classifierId")
    category_set_id = options.get("categorySetId")
    status = normalize_reference_curation_status(options.get("status") or catalog.get("status"), "pending")
    reason_code = normalize_reference_rejection_reason_code(
        options.get("reasonCode") or options.get("reason_code"),
        required=status == "rejected",
    )
    source_snapshot_id = catalog.get("latest_snapshot_id") or catalog.get("latestSnapshotId")
    item_ids = sorted(
        str(item.get("id") or item.get("item_id") or item.get("externalItemId") or "")
        for item in catalog_items(catalog)
    )
    batch_id = f"reference-intake-{safe_id(corpus_id)}-{hash_short([catalog.get('generated_at') or catalog.get('generatedAt') or now, source_snapshot_id or '', item_ids, status, reason_code or ''])}"
    items = [
        normalize_catalog_reference_item(
            item,
            corpus_config=corpus_config,
            status=status,
            reason_code=reason_code,
            note=options.get("note"),
            ingestion_rationale=options.get("ingestionRationale") or options.get("ingestion_rationale"),
            batch_id=batch_id,
            now=now,
        )
        for item in catalog_items(catalog)
    ]
    import_run_id = f"knowledge-import-{safe_id(corpus_id)}-reference-catalog-{hash_short([batch_id, status, reason_code or ''])}"
    records: list[dict[str, Any]] = [
        _record(
            "KnowledgeCorpus",
            {
                "id": corpus_id,
                "name": corpus_config.get("name") or corpus_config.get("key"),
                "role": corpus_config.get("role"),
                "itemCount": len(items),
                "generatedAt": _date_or_null(catalog.get("generated_at") or catalog.get("generatedAt")),
                "latestImportRunId": import_run_id,
                "createdAt": now,
                "updatedAt": now,
            },
        ),
        _record(
            "KnowledgeImportRun",
            {
                "id": import_run_id,
                "corpusId": corpus_id,
                "importKind": "reference-catalog-registration",
                "classifierId": classifier_id,
                "sourceSnapshotId": source_snapshot_id,
                "status": "imported",
                "generatedAt": _date_or_null(catalog.get("generated_at") or catalog.get("generatedAt")),
                "importedAt": now,
                "itemCount": len(items),
                "categoryCount": 0,
                "proposalCount": 0,
                "artifactCount": 0,
                "referenceCount": len(items),
                "relationCount": 0,
                "warningCount": 0,
            },
        ),
        _raw_payload_record(
            "importRun",
            import_run_id,
            "reference-intake-catalog",
            sanitized_reference_catalog_snapshot(
                catalog,
                {
                    "batchId": batch_id,
                    "corpusId": corpus_id,
                    "status": status,
                    "reasonCode": reason_code,
                    "itemCount": len(items),
                    "sourceSnapshotId": source_snapshot_id,
                },
            ),
            import_run_id,
            now,
        ),
    ]

    for item in items:
        item_records = reference_records(
            item,
            {
                "corpusId": corpus_id,
                "categorySetId": category_set_id,
                "classifierId": classifier_id,
                "sourceSnapshotId": source_snapshot_id,
                "importRunId": import_run_id,
                "now": now,
                "actor": options.get("actor") or "Papyrus content CLI",
                "createCurationAssignment": status == "pending" or bool(options.get("createCurationAssignment")),
                "createIngestionRationaleMessage": bool(
                    options.get("createIngestionRationaleMessage")
                    or options.get("create_ingestion_rationale_message")
                ),
            },
        )
        records.extend(item_records)
        if status == "rejected":
            reference = next(entry["expected"] for entry in item_records if entry["modelName"] == "Reference")
            records.extend(
                reference_curation_message_records(
                    reference=reference,
                    action="reject",
                    status=status,
                    reason_code=reason_code,
                    note=item.get("curation_note") or item.get("ingestion_rationale"),
                    actor=options.get("actor") or "papyrus-register-catalog",
                    source="papyrus-register-catalog",
                    import_run_id=import_run_id,
                    now=now,
                )
            )

    import_run = next(entry for entry in records if entry["modelName"] == "KnowledgeImportRun")
    import_run["expected"]["relationCount"] = sum(1 for entry in records if entry["modelName"] == "SemanticRelation")

    return {
        "batchId": batch_id,
        "importRunId": import_run_id,
        "corpusId": corpus_id,
        "status": status,
        "reasonCode": reason_code,
        "itemCount": len(items),
        "records": records,
    }


def normalize_catalog_reference_item(
    item: dict[str, Any],
    *,
    corpus_config: dict[str, Any],
    status: str,
    reason_code: str | None,
    note: str | None,
    ingestion_rationale: str | None,
    batch_id: str,
    now: str,
) -> dict[str, Any]:
    metadata = sanitize_reference_metadata(item.get("metadata") if isinstance(item.get("metadata"), dict) else {})
    relpath = _string_or_null(item.get("relpath") or item.get("relative_path") or item.get("relativePath"))
    from .corpus_storage_paths import corpus_storage_path_prefix

    configured_path = _string_or_null(corpus_config.get("path")) or (
        corpus_storage_path_prefix(str(corpus_config["key"])) if corpus_config.get("key") else None
    )
    storage_path = _string_or_null(item.get("storage_path") or item.get("storagePath"))
    if not storage_path and relpath and configured_path:
        storage_path = f"{configured_path.rstrip('/')}/{relpath.lstrip('/')}"
    item_ingestion_rationale = _string_or_null(ingestion_rationale) or ingestion_rationale_from(item)
    curation_note = (
        _string_or_null(note)
        or _string_or_null(item.get("curation_note") or item.get("curationNote"))
        or item_ingestion_rationale
    )
    if status == "pending" and not item_ingestion_rationale:
        raise ValueError(
            f"Pending reference {item.get('id') or item.get('item_id') or 'unknown'} requires ingestion_rationale or --ingestion-rationale."
        )
    if status == "rejected" and not curation_note:
        raise ValueError(
            f"Rejected reference {item.get('id') or item.get('item_id') or 'unknown'} requires --note or catalog rationale."
        )
    return {
        **item,
        "item_id": item.get("item_id") or item.get("externalItemId") or item.get("id"),
        "storage_path": storage_path,
        "source_uri": item.get("source_uri")
        or item.get("sourceUri")
        or metadata.get("source_uri")
        or metadata.get("sourceUri")
        or item.get("url")
        or item.get("uri"),
        "media_type": item.get("media_type") or item.get("mediaType") or metadata.get("media_type"),
        "curation_status": status,
        "curation_note": curation_note,
        "ingestion_rationale": item_ingestion_rationale,
        "metadata": {
            **metadata,
            "reference_intake_batch_id": batch_id,
            "reference_intake_status": status,
            "curation_status": status,
            "curation_reason_code": reason_code,
            "registered_at": now,
        },
    }


def reference_records(item: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    reference = reference_record(item, context)
    records = [
        reference,
        *reference_attachment_records(item, reference["expected"], context),
    ]
    if context.get("createIngestionRationaleMessage"):
        records.extend(reference_message_records(item, reference["expected"], context))
    if context.get("createCurationAssignment", True):
        records.extend(reference_curation_assignment_records(item, reference["expected"], context))
    return records


def reference_record(item: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    external_item_id = _required_string(item.get("item_id") or item.get("id") or item.get("externalItemId"), "item_id")
    lineage_id = reference_lineage_id_for(context["corpusId"], external_item_id)
    metadata = sanitize_reference_metadata(item.get("metadata") if isinstance(item.get("metadata"), dict) else {})
    item_ingestion_rationale = ingestion_rationale_from(item)
    if item_ingestion_rationale:
        metadata = {**metadata, "ingestion_rationale": item_ingestion_rationale}
    path_value = item.get("storage_path") or item.get("storagePath") or item.get("relpath") or item.get("path")
    normalized_path = normalize_storage_path(path_value)
    curation_status = normalize_reference_curation_status(
        item.get("curation_status")
        or item.get("curationStatus")
        or item.get("status")
        or metadata.get("curation_status")
        or metadata.get("status"),
        "accepted",
    )
    reference = {
        "id": f"{lineage_id}-v1",
        "lineageId": lineage_id,
        "corpusId": context["corpusId"],
        "externalItemId": external_item_id,
        "title": _string_or_null(item.get("title") or metadata.get("title")),
        "authors": _string_array(item.get("authors") or metadata.get("authors")),
        "sourceUri": _string_or_null(item.get("source_uri") or item.get("sourceUri")) or normalized_path.get("sourceUri"),
        "storagePath": normalized_path.get("storagePath"),
        "mediaType": _string_or_null(item.get("media_type") or item.get("mediaType")),
        "byteSize": _integer_or_null(item.get("bytes") or item.get("byte_size") or item.get("byteSize")),
        "sha256": _string_or_null(item.get("sha256") or item.get("checksum")),
        "sourcePublishedAt": _string_or_null(item.get("published_at") or item.get("publishedAt")),
        "sourceUpdatedAt": _string_or_null(item.get("updated_at") or item.get("updatedAt")),
        "retrievedAt": _string_or_null(item.get("retrieved_at") or item.get("retrievedAt")),
        "importRunId": context["importRunId"],
        "importedAt": context["now"],
        "createdAt": context["now"],
        "curationStatus": curation_status,
        "curationStatusKey": f"{context['corpusId']}#{curation_status}",
        "curationStatusUpdatedAt": context["now"],
        "curationStatusUpdatedBy": context.get("actor") or "biblicus-import",
        "curationStatusReason": (
            "trusted import"
            if curation_status == "accepted"
            else _string_or_null(item.get("curation_note") or item.get("ingestion_rationale"))
        ),
        "newsroomFeedKey": "references",
        "reviewedFeedKey": None if curation_status == "pending" else "references#reviewed",
        "metadata": json.dumps(metadata, sort_keys=True),
        "updatedAt": context["now"],
    }
    return _record(
        "Reference",
        versioned_record(
            reference,
            now=context["now"],
            actor=context.get("actor") or "biblicus-import",
            reason="reference-import",
            content=sanitize_reference_content(reference),
        ),
    )


def reference_attachment_records(item: dict[str, Any], reference: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    if reference.get("storagePath") or reference.get("sourceUri"):
        records.append(
            _record(
                "ReferenceAttachment",
                {
                    "id": f"reference-attachment-{hash_short(['reference#' + str(reference['id']), 'source', '001-source', reference.get('storagePath') or '', reference.get('sourceUri') or ''])}",
                    "referenceId": reference["id"],
                    "referenceLineageId": reference["lineageId"],
                    "referenceVersionNumber": reference.get("versionNumber"),
                    "referenceVersionKey": f"reference#{reference['id']}",
                    "role": "source",
                    "sortKey": "001-source",
                    "storagePath": reference.get("storagePath"),
                    "sourceUri": reference.get("sourceUri"),
                    "filename": (reference.get("storagePath") or reference.get("sourceUri") or "").split("/")[-1],
                    "mediaType": reference.get("mediaType"),
                    "byteSize": reference.get("byteSize"),
                    "sha256": reference.get("sha256"),
                    "etag": None,
                    "importRunId": context["importRunId"],
                    "importedAt": context["now"],
                    "metadata": json.dumps({}),
                },
            )
        )
    return records


def reference_message_records(item: dict[str, Any], reference: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    rationale = ingestion_rationale_from(item)
    if not rationale:
        return []
    message = message_record(
        {
            "messageKind": "ingestion_rationale",
            "messageDomain": "commentary",
            "body": rationale,
            "summary": reference.get("title") or reference.get("externalItemId") or "Ingestion rationale",
            "source": "biblicus-import",
            "importRunId": context["importRunId"],
            "createdAt": context["now"],
            "metadata": {
                "externalItemId": reference.get("externalItemId"),
                "corpusId": reference.get("corpusId"),
            },
        }
    )
    return [
        message,
        semantic_relation_record(
            {
                "predicate": "ingestion_rationale",
                "subjectKind": "message",
                "subjectId": message["expected"]["id"],
                "subjectLineageId": message["expected"]["id"],
                "subjectVersionNumber": 1,
                "objectKind": "reference",
                "objectId": reference["id"],
                "objectLineageId": reference["lineageId"],
                "objectVersionNumber": reference.get("versionNumber"),
                "rank": 1,
                "importRunId": context["importRunId"],
                "importedAt": context["now"],
                "metadata": {
                    "messageKind": "ingestion_rationale",
                    "externalItemId": reference.get("externalItemId"),
                    "corpusId": reference.get("corpusId"),
                },
            }
        ),
    ]


def reference_curation_assignment_records(item: dict[str, Any], reference: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    assignment_type_key = "curation.reference-intake"
    queue_key = f"{assignment_type_key}#{context['corpusId']}"
    assignment_id = f"assignment-{safe_id(assignment_type_key)}-{hash_short([context['corpusId'], reference['lineageId']])}"
    title = (
        f"Curate reference: {reference['title']}"
        if reference.get("title")
        else f"Curate reference {reference.get('externalItemId')}"
    )
    assignment = _record(
        "Assignment",
        {
            "id": assignment_id,
            "assignmentTypeKey": assignment_type_key,
            "queueKey": queue_key,
            "queueStatusKey": f"{queue_key}#open",
            "status": "open",
            "priority": 50,
            "title": title,
            "brief": "Review this knowledge-base reference and add any useful curation notes.",
            "instructions": "Inspect linked Reference metadata and private corpus attachments.",
            "corpusId": context["corpusId"],
            "categorySetId": context.get("categorySetId"),
            "classifierId": context.get("classifierId"),
            "sourceSnapshotId": context.get("sourceSnapshotId"),
            "importRunId": context["importRunId"],
            "createdBy": context.get("actor") or "biblicus-import",
            "createdAt": context["now"],
            "updatedAt": context["now"],
            "newsroomFeedKey": "assignments",
            "metadata": json.dumps(
                {
                    "referenceLineageId": reference["lineageId"],
                    "referenceId": reference["id"],
                    "externalItemId": reference.get("externalItemId"),
                    "sourceUri": reference.get("sourceUri"),
                    "storagePath": reference.get("storagePath"),
                    "contentHash": reference.get("contentHash"),
                }
            ),
        },
    )
    relation = semantic_relation_record(
        {
            "predicate": "requests_work_on",
            "subjectKind": "assignment",
            "subjectId": assignment["expected"]["id"],
            "subjectLineageId": assignment["expected"]["id"],
            "subjectVersionNumber": None,
            "objectKind": "reference",
            "objectId": reference["id"],
            "objectLineageId": reference["lineageId"],
            "objectVersionNumber": reference.get("versionNumber"),
            "rank": 1,
            "classifierId": context.get("classifierId"),
            "importRunId": context["importRunId"],
            "importedAt": context["now"],
            "metadata": {
                "assignmentTypeKey": assignment_type_key,
                "queueKey": queue_key,
                "externalItemId": reference.get("externalItemId"),
                "title": reference.get("title") or item.get("title"),
            },
        }
    )
    return [assignment, relation]


def reference_curation_message_records(
    *,
    reference: dict[str, Any],
    action: str,
    status: str,
    reason_code: str | None,
    note: str | None,
    actor: str,
    source: str,
    import_run_id: str,
    now: str,
) -> list[dict[str, Any]]:
    body = note or f"{actor} marked this reference {status}."
    message = message_record(
        {
            "messageKind": "reference_curation",
            "messageDomain": "commentary",
            "body": body,
            "summary": f"{reference.get('title') or reference.get('externalItemId') or reference['id']}: {status}",
            "source": source,
            "importRunId": import_run_id,
            "authorLabel": actor,
            "createdAt": now,
            "metadata": {
                "action": action,
                "curationStatus": status,
                "reasonCode": reason_code,
                "referenceId": reference["id"],
                "referenceLineageId": reference["lineageId"],
            },
        }
    )
    return [
        message,
        semantic_relation_record(
            {
                "predicate": "comment",
                "subjectKind": "message",
                "subjectId": message["expected"]["id"],
                "subjectLineageId": message["expected"]["id"],
                "subjectVersionNumber": 1,
                "objectKind": "reference",
                "objectId": reference["id"],
                "objectLineageId": reference["lineageId"],
                "objectVersionNumber": reference.get("versionNumber"),
                "rank": 1,
                "importRunId": import_run_id,
                "importedAt": now,
                "metadata": {
                    "action": action,
                    "curationStatus": status,
                    "reasonCode": reason_code,
                    "messageKind": "reference_curation",
                },
            }
        ),
    ]


def message_record(input_payload: dict[str, Any]) -> dict[str, Any]:
    metadata = sanitize_reference_metadata(input_payload.get("metadata") or {})
    body = str(input_payload.get("body") or "")
    source = _string_or_null(input_payload.get("source")) or "papyrus"
    record_id = input_payload.get("id") or f"message-{hash_short([input_payload.get('messageKind'), body, source, metadata])}"
    return _record(
        "Message",
        build_canonical_message_expected(
            {
                "id": record_id,
                "messageKind": input_payload.get("messageKind") or "comment",
                "messageDomain": input_payload.get("messageDomain") or "commentary",
                "status": input_payload.get("status") or "active",
                "body": body,
                "summary": input_payload.get("summary"),
                "source": source,
                "importRunId": input_payload.get("importRunId"),
                "authorSub": input_payload.get("authorSub"),
                "authorUserProfileId": input_payload.get("authorUserProfileId"),
                "authorLabel": _string_or_null(input_payload.get("authorLabel")) or source,
                "createdAt": input_payload.get("createdAt"),
                "updatedAt": input_payload.get("updatedAt") or input_payload.get("createdAt"),
                "newsroomFeedKey": "messages",
                "metadata": metadata,
                "responseTarget": input_payload.get("responseTarget"),
                "responseStatus": input_payload.get("responseStatus"),
                "responseOwner": input_payload.get("responseOwner"),
                "responseStartedAt": input_payload.get("responseStartedAt"),
                "responseCompletedAt": input_payload.get("responseCompletedAt"),
                "responseError": input_payload.get("responseError"),
                "threadId": input_payload.get("threadId"),
                "parentMessageId": input_payload.get("parentMessageId"),
                "sequenceNumber": input_payload.get("sequenceNumber"),
            },
            default_source="papyrus",
            default_author_label=source,
            default_response_owner="papyrus-cli",
        ),
    )


def semantic_relation_record(input_payload: dict[str, Any]) -> dict[str, Any]:
    subject_version_key = f"{input_payload['subjectKind']}#{input_payload['subjectId']}"
    object_version_key = f"{input_payload['objectKind']}#{input_payload['objectId']}"
    subject_state_key = f"{input_payload['subjectKind']}#{input_payload['subjectLineageId']}#current"
    object_state_key = f"{input_payload['objectKind']}#{input_payload['objectLineageId']}#current"
    return _record(
        "SemanticRelation",
        {
            "id": f"semantic-relation-{hash_short([subject_version_key, input_payload['predicate'], object_version_key, input_payload.get('rank'), input_payload.get('classifierId'), input_payload.get('modelVersion')])}",
            "relationState": "current",
            "predicate": input_payload["predicate"],
            **semantic_relation_type_fields_for_predicate(input_payload["predicate"]),
            "subjectKind": input_payload["subjectKind"],
            "subjectId": input_payload["subjectId"],
            "subjectLineageId": input_payload["subjectLineageId"],
            "subjectVersionNumber": input_payload.get("subjectVersionNumber"),
            "objectKind": input_payload["objectKind"],
            "objectId": input_payload["objectId"],
            "objectLineageId": input_payload["objectLineageId"],
            "objectVersionNumber": input_payload.get("objectVersionNumber"),
            "subjectStateKey": subject_state_key,
            "objectStateKey": object_state_key,
            "objectSubjectStateKey": f"{object_state_key}#{input_payload['subjectKind']}",
            "predicateObjectStateKey": f"{input_payload['predicate']}#{object_state_key}",
            "subjectVersionKey": subject_version_key,
            "objectVersionKey": object_version_key,
            "score": input_payload.get("score") if input_payload.get("score") is not None else 1,
            "confidence": input_payload.get("confidence"),
            "rank": input_payload.get("rank"),
            "classifierId": input_payload.get("classifierId"),
            "modelVersion": input_payload.get("modelVersion"),
            "reviewRecommended": bool(input_payload.get("reviewRecommended")),
            "sourceSnapshotId": input_payload.get("sourceSnapshotId"),
            "importRunId": input_payload.get("importRunId"),
            "importedAt": input_payload.get("importedAt"),
            "createdAt": input_payload.get("importedAt"),
            "updatedAt": input_payload.get("importedAt"),
            "newsroomFeedKey": "semanticRelations",
            "metadata": json.dumps(input_payload.get("metadata") or {}, sort_keys=True),
        },
    )


def assert_reference_catalog_plan_safety(plan: dict[str, Any]) -> None:
    unsafe_models = sorted({entry["modelName"] for entry in plan["records"] if entry["modelName"] not in {
        "KnowledgeCorpus",
        "KnowledgeImportRun",
        "KnowledgeRawPayload",
        "Reference",
        "ReferenceAttachment",
        "Assignment",
        "Message",
        "SemanticRelation",
        "ModelAttachment",
    }})
    if unsafe_models:
        raise ValueError(f"references create-from-catalog produced unsupported models: {', '.join(unsafe_models)}.")
    unsafe_predicates = [
        entry["expected"].get("relationTypeKey") or entry["expected"].get("predicate")
        for entry in plan["records"]
        if entry["modelName"] == "SemanticRelation"
        and (entry["expected"].get("relationTypeKey") or entry["expected"].get("predicate")) in {"classified_as", "uses_evidence"}
    ]
    if unsafe_predicates:
        raise ValueError(
            "references create-from-catalog cannot create evidence or classification relations: "
            + ", ".join(str(value) for value in unsafe_predicates)
        )


def _record(model_name: str, expected: dict[str, Any]) -> dict[str, Any]:
    if model_name == "KnowledgeImportRun":
        corpus_id = _string_or_null(expected.get("corpusId"))
        import_kind = _string_or_null(expected.get("importKind"))
        expected = {
            **expected,
            "corpusImportKindKey": f"{corpus_id}#{import_kind}" if corpus_id and import_kind else None,
        }
    return {"modelName": model_name, "expected": expected}


def versioned_record(record: dict[str, Any], *, now: str, actor: str, reason: str, content: Any) -> dict[str, Any]:
    versioned = {
        **record,
        "versionNumber": record.get("versionNumber") or 1,
        "previousVersionId": record.get("previousVersionId"),
        "versionState": record.get("versionState") or "current",
        "versionCreatedAt": record.get("versionCreatedAt") or now,
        "versionCreatedBy": record.get("versionCreatedBy") or actor,
        "changeReason": record.get("changeReason") or reason,
    }
    versioned["contentHash"] = record.get("contentHash") or hash_short(content or versioned)
    return versioned


def _raw_payload_record(owner_type: str, owner_id: str, payload_kind: str, payload: Any, import_run_id: str, now: str) -> dict[str, Any]:
    return _record(
        "KnowledgeRawPayload",
        {
            "id": f"knowledge-raw-payload-{safe_id(owner_id)}-{safe_id(payload_kind)}",
            "ownerType": owner_type,
            "ownerId": owner_id,
            "payloadKind": payload_kind,
            "importRunId": import_run_id,
            "payload": json.dumps(payload, sort_keys=True),
            "createdAt": now,
            "updatedAt": now,
        },
    )


def sanitized_reference_catalog_snapshot(catalog: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    items = catalog_items(catalog)
    return {
        "schema_version": 1,
        "snapshot_kind": "papyrus-reference-intake-catalog",
        "snapshot_policy": "bounded-summary",
        "batch_id": context["batchId"],
        "corpus_id": context["corpusId"],
        "status": context["status"],
        "reason_code": context.get("reasonCode"),
        "item_count": context["itemCount"],
        "source_snapshot_id": context.get("sourceSnapshotId"),
        "items": items[:50],
        "truncated": len(items) > 50,
    }


def sanitize_reference_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if value is not None}


def sanitize_reference_content(reference: dict[str, Any]) -> dict[str, Any]:
    return {
        key: reference.get(key)
        for key in (
            "id",
            "lineageId",
            "corpusId",
            "externalItemId",
            "title",
            "sourceUri",
            "storagePath",
            "mediaType",
            "byteSize",
            "sha256",
            "curationStatus",
        )
    }


def normalize_storage_path(value: Any) -> dict[str, str | None]:
    raw = _string_or_null(value)
    if not raw:
        return {"storagePath": None, "sourceUri": None}
    if raw.startswith("corpora/"):
        return {"storagePath": raw, "sourceUri": None}
    if raw.startswith("http://") or raw.startswith("https://"):
        return {"storagePath": None, "sourceUri": raw}
    if raw.startswith("/") and "/corpora/" in raw:
        return {"storagePath": raw[raw.index("/corpora/") + 1 :], "sourceUri": raw}
    if raw.startswith("s3://"):
        path = raw.split("://", 1)[1].split("/", 1)
        storage = path[1] if len(path) > 1 else ""
        if storage.startswith("corpora/"):
            return {"storagePath": storage, "sourceUri": raw}
        return {"storagePath": None, "sourceUri": raw}
    if "/" in raw:
        return {"storagePath": raw if raw.startswith("corpora/") else None, "sourceUri": None}
    return {"storagePath": None, "sourceUri": raw}


def ingestion_rationale_from(item: dict[str, Any]) -> str | None:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return _string_or_null(
        item.get("ingestion_rationale")
        or item.get("ingestionRationale")
        or metadata.get("ingestion_rationale")
        or metadata.get("ingestionRationale")
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _date_or_null(value: Any) -> str | None:
    return _string_or_null(value)


def _string_or_null(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _required_string(value: Any, field_name: str) -> str:
    text = _string_or_null(value)
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def _integer_or_null(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _string_array(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(entry).strip() for entry in value if str(entry).strip()]
