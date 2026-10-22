"""Inbound email submission intake: authorize senders and create/find/process direct citations."""

from __future__ import annotations

import json
import re
import uuid
from email import policy
from email.parser import BytesParser
from typing import Any
from urllib.parse import urlparse

from papyrus_content.assignments_workflow import build_research_proposal_catalog_items
from papyrus_content.env import PAPYRUS_ROOT, resolve_corpora_file
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
from papyrus_content.message_contract import build_canonical_message_expected
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


def extract_sender_from_ses_mail(mail: dict[str, Any]) -> str:
    headers = mail.get("commonHeaders") if isinstance(mail.get("commonHeaders"), dict) else {}
    from_values = headers.get("from") if isinstance(headers.get("from"), list) else []
    if from_values:
        return normalize_email_address(str(from_values[0]))
    source = str(mail.get("source") or "").strip()
    return normalize_email_address(source)


def extract_recipients_from_ses_mail(mail: dict[str, Any]) -> list[str]:
    headers = mail.get("commonHeaders") if isinstance(mail.get("commonHeaders"), dict) else {}
    recipients: list[str] = []
    for key in ("to", "cc"):
        values = headers.get(key)
        if not isinstance(values, list):
            continue
        for entry in values:
            normalized = normalize_email_address(str(entry))
            if normalized:
                recipients.append(normalized)
    destination = mail.get("destination")
    if isinstance(destination, list):
        for entry in destination:
            normalized = normalize_email_address(str(entry))
            if normalized and normalized not in recipients:
                recipients.append(normalized)
    return recipients


def parse_inbound_email_body(raw_bytes: bytes) -> dict[str, str]:
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            content_type = str(part.get_content_type() or "")
            if part.get_content_disposition() == "attachment":
                continue
            try:
                payload = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True)
            if not isinstance(payload, str):
                continue
            if content_type == "text/plain":
                plain_parts.append(payload)
            elif content_type == "text/html":
                html_parts.append(payload)
    else:
        try:
            payload = message.get_content()
        except Exception:
            payload = message.get_payload(decode=True)
        if isinstance(payload, str):
            if str(message.get_content_type() or "") == "text/html":
                html_parts.append(payload)
            else:
                plain_parts.append(payload)
    text = "\n\n".join(part.strip() for part in plain_parts if part.strip())
    if not text and html_parts:
        text = _html_to_text("\n\n".join(html_parts))
    subject = str(message.get("subject") or "").strip()
    return {"subject": subject, "text": text.strip()}


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


def lookup_registered_user_profile_id(client: PapyrusGraphQLAuthoringClient, sender_email: str) -> str | None:
    normalized = normalize_email_address(sender_email)
    if not normalized:
        return None
    identities = client.list_records("UserIdentity")
    for identity in identities:
        if normalize_email_address(identity.get("email")) != normalized:
            continue
        if str(identity.get("status") or "").strip().lower() not in {"", "active"}:
            continue
        profile_id = str(identity.get("userProfileId") or "").strip()
        if profile_id:
            return profile_id
    profiles = client.list_records("UserProfile")
    for profile in profiles:
        if normalize_email_address(profile.get("email")) == normalized:
            return str(profile.get("id") or "").strip() or None
    return None


def build_email_submission_message_record(
    *,
    message_id: str,
    now: str,
    subject: str,
    body_text: str,
    sender_email: str,
    recipient_email: str,
    ses_message_id: str | None,
    s3_bucket: str | None,
    s3_key: str | None,
    authorized: bool,
    author_user_profile_id: str | None,
    author_label: str,
    citations: list[dict[str, str]],
    status: str,
    response_status: str,
    response_error: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "channel": "email",
        "senderEmail": sender_email,
        "recipientEmail": recipient_email,
        "sesMessageId": ses_message_id,
        "s3Bucket": s3_bucket,
        "s3Key": s3_key,
        "authorized": authorized,
        "directCitationCount": len(citations),
        "directCitations": citations,
    }
    if not authorized:
        metadata["rejectionKind"] = REJECTION_KIND_UNREGISTERED_SENDER
    return build_canonical_message_expected(
        {
            "id": message_id,
            "messageKind": MESSAGE_KIND_EMAIL_SUBMISSION,
            "messageDomain": MESSAGE_DOMAIN_REFERENCE_INTAKE,
            "messageType": MESSAGE_TYPE_INBOUND_EMAIL,
            "status": status,
            "summary": subject or "Email submission",
            "source": "inbound-email",
            "authorLabel": author_label,
            "authorUserProfileId": author_user_profile_id,
            "body": body_text,
            "responseTarget": RESPONSE_TARGET_EMAIL_PROCESSOR,
            "responseStatus": response_status,
            "responseOwner": "papyrus-email-submission-processor",
            "responseStartedAt": now if response_status == "IN_PROGRESS" else None,
            "responseCompletedAt": now if response_status in {"COMPLETED", "FAILED", "REJECTED"} else None,
            "responseError": response_error,
            "metadata": metadata,
            "createdAt": now,
            "updatedAt": now,
            "newsroomFeedKey": "submissions",
        },
        default_source="inbound-email",
        default_author_label=author_label,
        default_response_owner="papyrus-email-submission-processor",
    )


def register_inbound_email_message(
    client: PapyrusGraphQLAuthoringClient,
    *,
    sender_email: str,
    recipient_email: str,
    subject: str,
    body_text: str,
    ses_message_id: str | None,
    s3_bucket: str | None,
    s3_key: str | None,
    now: str | None = None,
) -> dict[str, Any]:
    from papyrus_content.newsroom_commands import now_iso

    timestamp = now or now_iso()
    bucket_name = str(s3_bucket or "").strip()
    key_name = str(s3_key or "").strip()
    message_id = (
        inbound_message_id_for_s3(bucket_name, key_name)
        if bucket_name and key_name
        else f"message-email-submission-{uuid.uuid4().hex[:20]}"
    )
    normalized_sender = normalize_email_address(sender_email)
    profile_id = lookup_registered_user_profile_id(client, normalized_sender)
    authorized = bool(profile_id)
    citations: list[dict[str, str]] = []
    parent_submission_message_id: str | None = None
    intake_classification = "new_submission"
    inbound_attachment_count = 0
    inbound_in_reply_to: str | None = None
    inbound_references: str | None = None
    envelope = None
    if bucket_name and key_name:
        from papyrus_newsroom.email_submission_replies import (
            load_inbound_mime_envelope_from_metadata,
            resolve_parent_submission_message_id,
        )

        envelope = load_inbound_mime_envelope_from_metadata({"s3Bucket": bucket_name, "s3Key": key_name})
        if envelope:
            inbound_in_reply_to = envelope.in_reply_to
            inbound_references = envelope.references_header
            inbound_attachment_count = len(envelope.attachments)
            parent_submission_message_id = resolve_parent_submission_message_id(
                in_reply_to=envelope.in_reply_to,
                references_header=envelope.references_header,
            )
    if authorized:
        if envelope and envelope.html_parts:
            from papyrus_newsroom.email_mime_intake import extract_direct_citations_from_intake_text

            citations = extract_direct_citations_from_intake_text(
                body_text=envelope.body_text,
                html_parts=list(envelope.html_parts),
            )
        elif envelope:
            citations = extract_direct_citations(envelope.body_text)
        else:
            citations = extract_direct_citations(body_text)
    from papyrus_newsroom.email_submission_replies import classify_inbound_email_intake

    intake_classification = classify_inbound_email_intake(
        body_text=envelope.body_text if envelope else body_text,
        citations=citations,
        parent_message_id=parent_submission_message_id,
        attachments=envelope.attachments if envelope else [],
    )
    attachment_only_reply = intake_classification == "attachment_only_reply"
    conversational_reply = intake_classification == "conversational_reply"
    agent_intake = intake_classification == "agent_intake"
    pdf_only_intake = intake_classification == "pdf_only_intake"
    status = "received" if authorized else "rejected"
    response_status = "PENDING" if authorized else "REJECTED"
    response_error = None if authorized else UNREGISTERED_SENDER_RESPONSE_ERROR
    if authorized and looks_like_research_assignment_request(body_text, citation_count=len(citations)):
        status = "rejected"
        response_status = "REJECTED"
        response_error = (
            "Submission looks like a research assignment request. "
            "Send direct citations (URLs or DOIs), not open-ended research tasks."
        )
    elif (
        authorized
        and not citations
        and not attachment_only_reply
        and not conversational_reply
        and not agent_intake
        and not pdf_only_intake
    ):
        status = "rejected"
        response_status = "REJECTED"
        response_error = "No direct citations (URL or DOI) were found in the email body."

    record = build_email_submission_message_record(
        message_id=message_id,
        now=timestamp,
        subject=subject,
        body_text=body_text,
        sender_email=normalized_sender,
        recipient_email=normalize_email_address(recipient_email),
        ses_message_id=ses_message_id,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        authorized=authorized,
        author_user_profile_id=profile_id,
        author_label=normalized_sender or "unknown-sender",
        citations=citations,
        status=status,
        response_status=response_status,
        response_error=response_error,
    )
    metadata = record.get("metadata")
    if isinstance(metadata, str) and metadata:
        metadata_payload = json.loads(metadata)
        metadata_payload["parentSubmissionMessageId"] = parent_submission_message_id
        metadata_payload["intakeClassification"] = intake_classification
        metadata_payload["inboundInReplyTo"] = inbound_in_reply_to
        metadata_payload["inboundReferences"] = inbound_references
        metadata_payload["inboundAttachmentCount"] = inbound_attachment_count
        record["metadata"] = json.dumps(metadata_payload, sort_keys=True)
    changes = build_record_changes(client, [{"modelName": "Message", "expected": record}])
    apply_record_changes(client, changes)
    return {
        "messageId": message_id,
        "authorized": authorized,
        "status": status,
        "responseStatus": response_status,
        "responseError": response_error,
        "directCitationCount": len(citations),
        "citations": citations,
    }


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


def run_email_submission_cloud_procedure(
    client: PapyrusGraphQLAuthoringClient,
    *,
    message_id: str,
    corpus_key: str | None = None,
    actor_label: str = "Papyrus inbound email",
) -> dict[str, Any]:
    from papyrus_content.cloud_procedures import start_cloud_procedure_run

    corpus_key = corpus_key or default_corpus_key()
    return start_cloud_procedure_run(
        client=client,
        alias="submissions.process-email",
        actor_label=actor_label,
        title=f"Process email submission {message_id}",
        summary="Create, find, and process direct citations from an inbound submission email.",
        input_payload={
            "message_id": message_id,
            "corpus_key": corpus_key,
            "apply": True,
        },
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
    if apply:
        apply_record_changes(client, changes)
        update_newsroom_summary_after_reference_registration(client, changes, plan)
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
