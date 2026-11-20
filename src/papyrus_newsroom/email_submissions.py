"""Inbound email submission intake: authorize senders and create/find/process direct citations."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from papyrus_content.assignments_workflow import build_research_proposal_catalog_items
from papyrus_content.env import PAPYRUS_ROOT, resolve_corpora_file
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
from papyrus_content.records import apply_record_changes, build_record_changes
from papyrus_content.steering import default_corpus_key, load_steering_config, require_corpus_config

MESSAGE_KIND_EMAIL_SUBMISSION = "email_submission"

REJECTION_KIND_UNREGISTERED_SENDER = "unregistered_sender"
UNREGISTERED_SENDER_RESPONSE_ERROR = (
    "This submission was not accepted because only registered Papyrus users "
    "may send reference submissions by email."
)
MESSAGE_DOMAIN_REFERENCE_INTAKE = "reference_intake"
MESSAGE_TYPE_INBOUND_EMAIL = "INBOUND_EMAIL"
RESPONSE_TARGET_EMAIL_PROCESSOR = "email_submission_processor"

INBOUND_EMAIL_INTAKE_PREFIX = "inbound-email/"
INBOUND_EMAIL_ARCHIVE_PREFIX = "inbound-email-archived/"


def should_process_inbound_s3_key(key: str | None) -> bool:
    normalized = str(key or "").strip()
    if not normalized.startswith(INBOUND_EMAIL_INTAKE_PREFIX):
        return False
    if normalized.startswith(INBOUND_EMAIL_ARCHIVE_PREFIX):
        return False
    basename = normalized.split("/")[-1]
    if not basename or basename == "AMAZON_SES_SETUP_NOTIFICATION":
        return False
    remainder = normalized[len(INBOUND_EMAIL_INTAKE_PREFIX) :]
    return "/" not in remainder


def inbound_message_id_for_s3(bucket: str, key: str) -> str:
    import hashlib

    digest = hashlib.sha256(f"{bucket}/{key}".encode("utf-8")).hexdigest()[:20]
    return f"message-email-submission-{digest}"


def archive_inbound_mime_object(*, bucket: str, key: str, s3_client: Any | None = None) -> dict[str, Any]:
    if not should_process_inbound_s3_key(key):
        return {"archived": False, "reason": "skip"}
    import boto3
    from botocore.exceptions import ClientError

    client = s3_client or boto3.client("s3")
    relative = key[len(INBOUND_EMAIL_INTAKE_PREFIX) :] if key.startswith(INBOUND_EMAIL_INTAKE_PREFIX) else key
    archive_key = f"{INBOUND_EMAIL_ARCHIVE_PREFIX}{relative}"

    def _object_exists(object_key: str) -> bool:
        try:
            client.head_object(Bucket=bucket, Key=object_key)
            return True
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    if not _object_exists(key):
        if _object_exists(archive_key):
            return {"archived": True, "archiveKey": archive_key, "alreadyArchived": True}
        return {"archived": False, "reason": "source-missing"}

    if not _object_exists(archive_key):
        client.copy_object(Bucket=bucket, Key=archive_key, CopySource={"Bucket": bucket, "Key": key})
    client.delete_object(Bucket=bucket, Key=key)
    return {"archived": True, "archiveKey": archive_key}


def release_inbound_mime_after_success(client: PapyrusGraphQLAuthoringClient, *, message_id: str) -> dict[str, Any]:
    from papyrus_content.newsroom_commands import now_iso

    message = client.get_record("Message", message_id) or {}
    metadata = _message_metadata(message)
    bucket = str(metadata.get("s3Bucket") or "").strip()
    key = str(metadata.get("s3Key") or "").strip()
    if not bucket or not key:
        return {"released": False, "reason": "no-s3-pointer"}
    try:
        result = archive_inbound_mime_object(bucket=bucket, key=key)
        metadata["inboundMimeArchivedAt"] = now_iso()
        if result.get("archiveKey"):
            metadata["inboundMimeArchiveKey"] = result["archiveKey"]
        client.graphql(
            """
            mutation UpdateEmailSubmissionInboundMimeArchive($input: UpdateMessageInput!) {
              updateMessage(input: $input) { id }
            }
            """,
            {
                "input": {
                    "id": message_id,
                    "metadata": json.dumps(metadata, sort_keys=True),
                    "updatedAt": now_iso(),
                }
            },
        )
        if result.get("alreadyArchived"):
            return {"released": True, "alreadyArchived": True, **result}
        return {"released": True, **result}
    except Exception as error:
        metadata["inboundMimeArchiveError"] = str(error)
        client.graphql(
            """
            mutation UpdateEmailSubmissionInboundMimeArchiveError($input: UpdateMessageInput!) {
              updateMessage(input: $input) { id }
            }
            """,
            {
                "input": {
                    "id": message_id,
                    "metadata": json.dumps(metadata, sort_keys=True),
                    "updatedAt": now_iso(),
                }
            },
        )
        return {"released": False, "error": str(error)}
DEFAULT_STEERING_CONFIG = resolve_corpora_file("corpora/papyrus-steering.yml")

_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"')\]]+",
    re.IGNORECASE,
)
_DOI_PATTERN = re.compile(
    r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+",
    re.IGNORECASE,
)
_RESEARCH_ASSIGNMENT_PHRASES = (
    "research assignment",
    "assignment to research",
    "find sources on",
    "research the topic",
    "look into the topic",
    "investigate whether",
)


def normalize_email_address(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "<" in raw and ">" in raw:
        match = re.search(r"<([^>]+)>", raw)
        if match:
            raw = match.group(1).strip().lower()
    return raw


def _html_to_text(html: str) -> str:
    without_tags = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    without_tags = re.sub(r"<[^>]+>", " ", without_tags)
    return re.sub(r"\s+", " ", without_tags).strip()


def extract_direct_citations(text: str) -> list[dict[str, str]]:
    body = str(text or "")
    citations: list[dict[str, str]] = []
    seen: set[str] = set()

    for match in _URL_PATTERN.finditer(body):
        url = match.group(0).rstrip(".,);]")
        if url in seen:
            continue
        seen.add(url)
        citations.append(
            {
                "kind": "url",
                "url": url,
                "title": _title_from_url(url),
                "ingestion_rationale": _direct_citation_rationale(url),
            }
        )

    for match in _DOI_PATTERN.finditer(body):
        doi = match.group(0).rstrip(".,);]")
        doi_url = f"https://doi.org/{doi}"
        if doi_url in seen:
            continue
        seen.add(doi_url)
        citations.append(
            {
                "kind": "doi",
                "url": doi_url,
                "doi": doi,
                "title": f"DOI {doi}",
                "ingestion_rationale": _direct_citation_rationale(doi_url),
            }
        )
    return citations


def looks_like_research_assignment_request(text: str, *, citation_count: int) -> bool:
    if citation_count > 0:
        return False
    lowered = str(text or "").lower()
    return any(phrase in lowered for phrase in _RESEARCH_ASSIGNMENT_PHRASES)


def process_email_submission_message(
    client: PapyrusGraphQLAuthoringClient,
    *,
    message_id: str,
    corpus_key: str | None = None,
    steering_config_path: str | None = None,
    apply: bool = True,
) -> dict[str, Any]:
    from papyrus_newsroom.email_submission_replies import process_inbound_email_submission

    corpus_key = corpus_key or default_corpus_key()
    message = client.get_record("Message", message_id)
    if not message:
        raise ValueError(f"Message not found: {message_id}")
    if str(message.get("messageKind") or "") != MESSAGE_KIND_EMAIL_SUBMISSION:
        raise ValueError(f"Message {message_id} is not an email submission.")
    return process_inbound_email_submission(
        client,
        message_id=message_id,
        corpus_key=corpus_key,
        steering_config_path=steering_config_path,
        apply=apply,
    )


def _load_registered_reference_processing_records(
    client: Any,
    *,
    registered_reference_ids: set[str],
    import_run_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Point lookups for inbound email processing — avoid scanning entire Reference tables."""
    if not registered_reference_ids:
        return [], [], []
    references_by_id = client.get_records_by_id("Reference", sorted(registered_reference_ids))
    references = list(references_by_id.values())
    attachments: list[dict[str, Any]] = []
    seen_attachment_ids: set[str] = set()
    for reference in references:
        lineage_id = str(
            reference.get("lineageId") or reference.get("referenceLineageId") or reference.get("id") or ""
        ).strip()
        if not lineage_id:
            continue
        for attachment in client.list_reference_attachments_by_lineage(lineage_id):
            attachment_id = str(attachment.get("id") or "")
            if attachment_id and attachment_id in seen_attachment_ids:
                continue
            if attachment_id:
                seen_attachment_ids.add(attachment_id)
            attachments.append(attachment)
    relations: list[dict[str, Any]] = []
    if import_run_id:
        relations = client.list_semantic_relations_by_import_run_and_imported_at(import_run_id)
    return references, attachments, relations


def run_registered_reference_enrichment(
    client: PapyrusGraphQLAuthoringClient,
    *,
    registered_reference_ids: set[str],
    import_run_id: str | None,
    corpus_key: str,
    steering_config_path: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    """Re-run source find, text extraction, and summarization for registered references."""
    from papyrus_content.ids import knowledge_corpus_id
    from papyrus_content.reference_metadata_generation import run_reference_metadata_generation_from_extracted_text
    from papyrus_content.reference_url_text import run_reference_source_find, run_reference_url_text_extraction

    steering_config = load_steering_config(steering_config_path) or {}
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key")
    if not registered_reference_ids:
        empty_find = {"eligibleCount": 0, "plannedCount": 0, "changeCount": 0, "failures": [], "items": []}
        empty_process = {"attemptedCount": 0, "generatedCount": 0, "items": []}
        return [], [], empty_find, empty_find, empty_process

    scoped_references, scoped_attachments, scoped_relations = _load_registered_reference_processing_records(
        client,
        registered_reference_ids=registered_reference_ids,
        import_run_id=import_run_id,
    )
    corpus_id = knowledge_corpus_id(corpus_config)
    corpus_key_by_id = {corpus_id: str(corpus_config.get("key") or "")}
    source_find_result = run_reference_source_find(
        client=client,
        references=scoped_references,
        attachments=scoped_attachments,
        corpus_key_by_id=corpus_key_by_id,
        corpus_id=corpus_id,
        reference_ids=registered_reference_ids,
        curation_status="pending",
        apply=True,
    )
    scoped_references, scoped_attachments, scoped_relations = _load_registered_reference_processing_records(
        client,
        registered_reference_ids=registered_reference_ids,
        import_run_id=import_run_id,
    )
    find_result = run_reference_url_text_extraction(
        client=client,
        references=scoped_references,
        attachments=scoped_attachments,
        semantic_relations=scoped_relations,
        corpus_key_by_id=corpus_key_by_id,
        corpus_id=corpus_id,
        reference_ids=registered_reference_ids,
        curation_status="pending",
        apply=True,
    )
    process_result = run_reference_metadata_generation_from_extracted_text(
        references=scoped_references,
        attachments=scoped_attachments,
        corpus_id=corpus_id,
        reference_ids=registered_reference_ids,
        curation_status="pending",
        apply=True,
    )
    scoped_references, scoped_attachments, _scoped_relations = _load_registered_reference_processing_records(
        client,
        registered_reference_ids=registered_reference_ids,
        import_run_id=import_run_id,
    )
    return scoped_references, scoped_attachments, source_find_result, find_result, process_result


def _create_find_process_direct_citations(
    client: PapyrusGraphQLAuthoringClient,
    *,
    message: dict[str, Any],
    citations: list[dict[str, Any]],
    corpus_key: str,
    steering_config_path: str,
    apply: bool,
) -> dict[str, Any]:
    steering_config = load_steering_config(steering_config_path) or {}
    require_corpus_config(steering_config, corpus_key, "--corpus-key")
    proposals = [
        {
            "title": citation.get("title") or citation.get("url") or "Untitled citation",
            "url": citation.get("url"),
            "ingestion_rationale": citation.get("ingestion_rationale")
            or _direct_citation_rationale(str(citation.get("url") or "")),
            "submissionMessageId": message.get("id"),
        }
        for citation in citations
        if citation.get("url")
    ]
    catalog_items = build_research_proposal_catalog_items(
        proposals,
        assignment={"id": f"email-submission-{message.get('id')}", "title": message.get("summary") or "Email submission"},
        message=message,
        packet={"proposedReferences": proposals, "researchMode": "direct_citation_intake"},
    )
    if not catalog_items:
        raise ValueError("Direct citation catalog was empty after normalization.")
    catalog = {
        "schema_version": 1,
        "catalog_kind": "papyrus-email-submission-citations",
        "generated_at": message.get("createdAt"),
        "message_id": message.get("id"),
        "items": catalog_items,
    }
    from papyrus_content.catalog import assert_reference_catalog_plan_safety, build_reference_catalog_registration_records
    from papyrus_content.ids import knowledge_corpus_id
    from papyrus_content.newsroom_summary import update_newsroom_summary_after_reference_registration
    from papyrus_content.steering import resolve_classifier_for_corpus

    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key")
    plan_options = {
        "corpusConfig": corpus_config,
        "corpusId": knowledge_corpus_id(corpus_config),
        "classifierId": resolve_classifier_for_corpus(steering_config, corpus_config, None),
        "status": "pending",
        "note": f"Registered from inbound email submission {message.get('id')}",
        "actor": normalize_email_address(str((message.get("authorLabel") or ""))) or "Papyrus inbound email",
    }
    plan = build_reference_catalog_registration_records(catalog, plan_options)
    assert_reference_catalog_plan_safety(plan)
    planned_reference_ids = {
        str(record["expected"].get("id") or "")
        for record in plan["records"]
        if record.get("modelName") == "Reference"
    }
    planned_reference_ids.discard("")
    changes = build_record_changes(client, plan["records"])
    registered_reference_ids: set[str] = set(planned_reference_ids)
    prediction = None
    if apply:
        apply_record_changes(client, changes)
        update_newsroom_summary_after_reference_registration(client, changes, plan)
        from papyrus_content.reference_prediction_queue import references_created_by, request_predictions
        wanted_predictions = references_created_by(changes)   # one Cyclotron prediction per new Reference, requested once, here
        prediction = request_predictions(client, wanted_predictions).to_json() if wanted_predictions else None
        from papyrus_content.reference_images import attach_preview
        for change in changes:   # newly created References only; never raises
            if change.get("modelName") == "Reference" and change.get("action") == "create":
                attach_preview(client, change["expected"])
        applied_reference_ids = {
            str(change["expected"].get("id") or "")
            for change in changes
            if change.get("modelName") == "Reference" and change.get("action") in {"create", "update"}
        }
        applied_reference_ids.discard("")
        if applied_reference_ids:
            registered_reference_ids = applied_reference_ids
        import_run_id = str(plan.get("importRunId") or "").strip() or None
        (
            scoped_references,
            scoped_attachments,
            source_find_result,
            find_result,
            process_result,
        ) = run_registered_reference_enrichment(
            client,
            registered_reference_ids=registered_reference_ids,
            import_run_id=import_run_id,
            corpus_key=corpus_key,
            steering_config_path=steering_config_path,
        )
    else:
        scoped_references = []
        scoped_attachments = []
        source_find_result = {"eligibleCount": 0, "plannedCount": 0, "changeCount": 0, "failures": [], "items": []}
        find_result = {"eligibleCount": 0, "plannedCount": 0, "changeCount": 0, "failures": [], "items": []}
        process_result = {"attemptedCount": 0, "generatedCount": 0, "items": []}

    from papyrus_newsroom.email_submission_feedback import build_reference_feedback_entries

    reference_feedback = build_reference_feedback_entries(
        references=scoped_references,
        attachments=scoped_attachments,
        find_result=find_result,
        process_result=process_result,
    )

    return {
        "importRunId": plan.get("importRunId"),
        "prediction": prediction,
        "registeredReferenceCount": len(registered_reference_ids),
        "registeredReferenceIds": sorted(registered_reference_ids),
        "directCitationCount": len(citations),
        "find": {
            "sourceDiscovery": {
                "eligible": source_find_result.get("eligibleCount", 0),
                "planned": source_find_result.get("plannedCount", 0),
                "changes": source_find_result.get("changeCount", 0),
                "failures": len(source_find_result.get("failures", [])),
            },
            "extractedText": {
                "eligible": find_result.get("eligibleCount", 0),
                "planned": find_result.get("plannedCount", 0),
                "changes": find_result.get("changeCount", 0),
                "failures": len(find_result.get("failures", [])),
            },
            "eligible": find_result.get("eligibleCount", 0),
            "planned": find_result.get("plannedCount", 0),
            "changes": int(source_find_result.get("changeCount", 0)) + int(find_result.get("changeCount", 0)),
            "failures": len(source_find_result.get("failures", [])) + len(find_result.get("failures", [])),
        },
        "process": {
            "attempted": process_result.get("attemptedCount", 0),
            "generated": process_result.get("generatedCount", 0),
        },
        "referenceFeedback": reference_feedback,
    }


def _message_metadata(message: dict[str, Any]) -> dict[str, Any]:
    raw = message.get("metadata")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _message_response_index_fields(message: dict[str, Any]) -> dict[str, Any]:
    """GSI sort-key fields required when mutating Message.responseStatus."""
    fields: dict[str, Any] = {}
    created_at = str(message.get("createdAt") or "").strip()
    if created_at:
        fields["createdAt"] = created_at
    response_target = str(message.get("responseTarget") or "").strip()
    if response_target:
        fields["responseTarget"] = response_target
    return fields


def _try_send_submission_feedback(
    client: PapyrusGraphQLAuthoringClient,
    *,
    message_id: str,
    processing_result: dict[str, Any] | None = None,
    processing_error: str | None = None,
    reference_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        from papyrus_newsroom.email_submission_feedback import maybe_send_submission_feedback_email

        return maybe_send_submission_feedback_email(
            client,
            message_id=message_id,
            processing_result=processing_result,
            processing_error=processing_error,
            reference_entries=reference_entries,
        )
    except Exception as error:
        return {"sent": False, "error": str(error)}


def send_submission_feedback_for_message(
    client: PapyrusGraphQLAuthoringClient,
    *,
    message_id: str,
) -> dict[str, Any]:
    from papyrus_newsroom.email_submission_feedback import send_feedback_only_for_message

    return send_feedback_only_for_message(client, message_id=message_id)


def _mark_message_processing(client: PapyrusGraphQLAuthoringClient, *, message_id: str, started_at: str) -> None:
    current = client.get_record("Message", message_id) or {}
    metadata = _message_metadata(current)
    metadata["processingStartedAt"] = started_at
    client.graphql(
        """
        mutation UpdateEmailSubmissionMessage($input: UpdateMessageInput!) {
          updateMessage(input: $input) { id status responseStatus }
        }
        """,
        {
            "input": {
                "id": message_id,
                "status": "processing",
                "responseStatus": "IN_PROGRESS",
                "responseStartedAt": started_at,
                "responseOwner": "papyrus-email-submission-processor",
                "metadata": json.dumps(metadata, sort_keys=True),
                "updatedAt": started_at,
                **_message_response_index_fields(current),
            }
        },
    )


def _mark_message_completed(
    client: PapyrusGraphQLAuthoringClient,
    *,
    message_id: str,
    finished_at: str,
    result: dict[str, Any],
) -> None:
    current = client.get_record("Message", message_id) or {}
    metadata = _message_metadata(current)
    metadata["processingResult"] = result
    metadata["processingCompletedAt"] = finished_at
    client.graphql(
        """
        mutation UpdateEmailSubmissionMessage($input: UpdateMessageInput!) {
          updateMessage(input: $input) { id status responseStatus }
        }
        """,
        {
            "input": {
                "id": message_id,
                "status": "completed",
                "responseStatus": "COMPLETED",
                "responseCompletedAt": finished_at,
                "responseError": None,
                "metadata": json.dumps(metadata, sort_keys=True),
                "updatedAt": finished_at,
                **_message_response_index_fields(current),
            }
        },
    )


def _mark_message_failed(
    client: PapyrusGraphQLAuthoringClient,
    *,
    message_id: str,
    finished_at: str,
    error_message: str,
) -> None:
    current = client.get_record("Message", message_id) or {}
    metadata = _message_metadata(current)
    metadata["processingError"] = error_message
    metadata["processingCompletedAt"] = finished_at
    client.graphql(
        """
        mutation UpdateEmailSubmissionMessage($input: UpdateMessageInput!) {
          updateMessage(input: $input) { id status responseStatus }
        }
        """,
        {
            "input": {
                "id": message_id,
                "status": "failed",
                "responseStatus": "FAILED",
                "responseCompletedAt": finished_at,
                "responseError": error_message,
                "metadata": json.dumps(metadata, sort_keys=True),
                "updatedAt": finished_at,
                **_message_response_index_fields(current),
            }
        },
    )


def _title_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "source").removeprefix("www.")
    path = (parsed.path or "/").strip("/")
    if not path:
        return host
    last_segment = path.split("/")[-1]
    cleaned = re.sub(r"[-_]+", " ", last_segment).strip()
    return cleaned[:120] if cleaned else host


def _direct_citation_rationale(source: str) -> str:
    return (
        f"Direct citation submitted by email: {source}. "
        "This is explicit source material for reference create/find/process intake, not a research assignment."
    )
