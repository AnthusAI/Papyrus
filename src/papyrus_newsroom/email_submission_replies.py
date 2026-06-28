"""Inbound email reply handling for submission feedback threads."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from typing import Any

_SUBMISSION_MESSAGE_ID_PATTERN = re.compile(
    r"^(message-email-submission-[a-f0-9]{20})(?:@|$)",
    re.IGNORECASE,
)
_REPLY_QUOTE_MARKERS = (
    re.compile(r"^\s*On .+ wrote:\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*From:\s*.+$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*_{5,}\s*$", re.MULTILINE),
)
_CONSOLE_MESSAGE_KIND = "console_chat_turn"
_CONSOLE_MESSAGE_DOMAIN = "conversation"
_CONSOLE_NEWSROOM_FEED_KEY = "consoleChat"
_CONSOLE_THREAD_ANCHOR_KEY = "site#papyrus"
_MIN_COMPOSED_PROSE_CHARS_FOR_AGENT = 120
_URL_IN_PROSE_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


@dataclass(frozen=True)
class InboundMimeAttachment:
    filename: str
    media_type: str
    payload: bytes


@dataclass(frozen=True)
class InboundMimeEnvelope:
    subject: str
    body_text: str
    in_reply_to: str | None
    references_header: str | None
    message_id: str | None
    attachments: list[InboundMimeAttachment]
    html_parts: tuple[str, ...] = ()


def feedback_rfc_message_id(submission_message_id: str) -> str:
    domain = str(os.environ.get("PAPYRUS_INBOUND_EMAIL_DOMAIN") or "p.apyr.us").strip().lower()
    message_id = str(submission_message_id or "").strip()
    if not message_id:
        raise ValueError("submission_message_id is required for feedback RFC Message-ID.")
    return f"<{message_id}@{domain}>"


def parse_submission_message_id_from_rfc_message_id(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    tokens = re.findall(r"<([^>]+)>", raw) or [raw.strip("<> ")]
    for token in tokens:
        normalized = token.strip()
        match = _SUBMISSION_MESSAGE_ID_PATTERN.match(normalized)
        if match:
            return match.group(1)
        if normalized.startswith("message-email-submission-"):
            return normalized.split("@", 1)[0]
    return None


def resolve_parent_submission_message_id(
    *,
    in_reply_to: str | None,
    references_header: str | None,
) -> str | None:
    for header in (in_reply_to, references_header):
        resolved = parse_submission_message_id_from_rfc_message_id(header)
        if resolved:
            return resolved
    return None


def extract_user_composed_reply_text(body_text: str) -> str:
    text = str(body_text or "").replace("\r\n", "\n")
    if not text.strip():
        return ""
    earliest_index: int | None = None
    for pattern in _REPLY_QUOTE_MARKERS:
        match = pattern.search(text)
        if match and (earliest_index is None or match.start() < earliest_index):
            earliest_index = match.start()
    if earliest_index is not None and earliest_index > 0:
        text = text[:earliest_index]
    lines: list[str] = []
    for line in text.split("\n"):
        if line.startswith(">"):
            break
        if re.match(r"^\s*On .+ wrote:\s*$", line, re.IGNORECASE):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def parse_inbound_mime_envelope(raw_bytes: bytes) -> InboundMimeEnvelope:
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[InboundMimeAttachment] = []
    if message.is_multipart():
        for part in message.walk():
            if part.is_multipart():
                continue
            disposition = str(part.get_content_disposition() or "").lower()
            content_type = str(part.get_content_type() or "").lower()
            try:
                payload = part.get_payload(decode=True)
            except Exception:
                payload = part.get_payload()
            if not isinstance(payload, (bytes, bytearray)):
                continue
            body = bytes(payload)
            if disposition == "attachment" or (
                disposition != "inline" and content_type == "application/pdf" and part.get_filename()
            ):
                filename = str(part.get_filename() or "attachment").strip() or "attachment"
                attachments.append(
                    InboundMimeAttachment(
                        filename=filename,
                        media_type=content_type or "application/octet-stream",
                        payload=body,
                    )
                )
                continue
            if content_type == "text/plain":
                plain_parts.append(body.decode(part.get_content_charset() or "utf-8", errors="replace"))
            elif content_type == "text/html":
                html_parts.append(body.decode(part.get_content_charset() or "utf-8", errors="replace"))
    else:
        try:
            payload = message.get_payload(decode=True)
        except Exception:
            payload = message.get_payload()
        if isinstance(payload, (bytes, bytearray)):
            decoded = payload.decode(message.get_content_charset() or "utf-8", errors="replace")
            if str(message.get_content_type() or "") == "text/html":
                html_parts.append(decoded)
            else:
                plain_parts.append(decoded)
    text = "\n\n".join(part.strip() for part in plain_parts if part.strip())
    if not text and html_parts:
        text = _html_to_text("\n\n".join(html_parts))
    return InboundMimeEnvelope(
        subject=str(message.get("subject") or "").strip(),
        body_text=text.strip(),
        in_reply_to=str(message.get("In-Reply-To") or "").strip() or None,
        references_header=str(message.get("References") or "").strip() or None,
        message_id=str(message.get("Message-ID") or "").strip() or None,
        attachments=attachments,
        html_parts=tuple(html_parts),
    )


def _html_to_text(html: str) -> str:
    without_tags = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    without_tags = re.sub(r"<[^>]+>", " ", without_tags)
    return re.sub(r"\s+", " ", without_tags).strip()


def load_inbound_mime_envelope_from_metadata(metadata: dict[str, Any]) -> InboundMimeEnvelope | None:
    bucket = str(metadata.get("s3Bucket") or "").strip()
    key = str(metadata.get("s3Key") or "").strip()
    if not bucket or not key:
        return None
    try:
        import boto3
    except ModuleNotFoundError:
        return None
    raw_object = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    raw_bytes = raw_object["Body"].read()
    return parse_inbound_mime_envelope(raw_bytes)


def _citation_urls(citations: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        url = str(citation.get("url") or "").strip()
        if url:
            urls.append(url)
    return urls


def prose_after_stripping_citations(body_text: str, citations: list[dict[str, Any]]) -> str:
    text = str(body_text or "")
    for url in _citation_urls(citations):
        text = text.replace(url, " ")
    text = _URL_IN_PROSE_PATTERN.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def has_substantial_composed_prose(body_text: str, citations: list[dict[str, Any]]) -> bool:
    prose = prose_after_stripping_citations(body_text, citations)
    if len(prose) >= _MIN_COMPOSED_PROSE_CHARS_FOR_AGENT:
        return True
    clauses = [segment.strip() for segment in re.split(r"[.!?\n]+", prose) if len(segment.strip()) >= 24]
    return len(clauses) >= 2


def classify_new_submission_intake(
    body_text: str,
    citations: list[dict[str, Any]],
    attachments: list[InboundMimeAttachment] | None = None,
) -> str:
    pdf_attachments = _pdf_attachments(attachments or [])
    if citations and pdf_attachments:
        return "agent_intake"
    if not citations and pdf_attachments:
        if len(pdf_attachments) > 1:
            return "agent_intake"
        if has_substantial_composed_prose(body_text, []):
            return "agent_intake"
        return "pdf_only_intake"
    if not citations:
        return "new_submission"
    if len(citations) > 1:
        return "agent_intake"
    if has_substantial_composed_prose(body_text, citations):
        return "agent_intake"
    return "direct_citation_intake"


def classify_inbound_reply(
    *,
    body_text: str,
    parent_message_id: str | None,
    attachments: list[InboundMimeAttachment],
) -> str:
    if not parent_message_id:
        return "new_submission"
    user_text = extract_user_composed_reply_text(body_text)
    if attachments and not user_text:
        return "attachment_only_reply"
    if user_text or attachments:
        return "conversational_reply"
    return "empty_reply"


def classify_inbound_email_intake(
    *,
    body_text: str,
    citations: list[dict[str, Any]],
    parent_message_id: str | None,
    attachments: list[InboundMimeAttachment],
) -> str:
    if parent_message_id:
        return classify_inbound_reply(
            body_text=body_text,
            parent_message_id=parent_message_id,
            attachments=attachments,
        )
    return classify_new_submission_intake(body_text, citations, attachments)


def _email_agent_instructions() -> str:
    return (
        "You are handling authorized inbound email for Papyrus reference intake.\n"
        "Use execute_tactus with the papyrus.* tool surface.\n\n"
        "Goals:\n"
        "1. Register scholarly references for each relevant URL/DOI the submitter cited "
        "(newsletter forwards may contain many links — file the real references, skip "
        "unsubscribe/footer/nav links).\n"
        "2. When prose discusses a specific reference (commentary, summary, critique), "
        "create an insight Message on that reference lineage via papyrus.reference.insight_create.\n"
        "3. When the submitter asks a question or gives a command (knowledge search, list "
        "recent references, curation review), use the appropriate tools — do not treat "
        "commands as insights.\n"
        "4. Decide per paragraph: filing-only, editorial insight, question, or follow-up command.\n"
    )


def _pdf_attachments(attachments: list[InboundMimeAttachment]) -> list[InboundMimeAttachment]:
    pdfs: list[InboundMimeAttachment] = []
    for attachment in attachments:
        media_type = str(attachment.media_type or "").split(";", 1)[0].strip().lower()
        filename = str(attachment.filename or "").lower()
        if media_type == "application/pdf" or filename.endswith(".pdf"):
            pdfs.append(attachment)
    return pdfs


def _registered_reference_ids_from_parent(parent_message: dict[str, Any], metadata: dict[str, Any]) -> list[str]:
    processing = metadata.get("processingResult")
    if isinstance(processing, dict):
        ids = processing.get("registeredReferenceIds")
        if isinstance(ids, list):
            normalized = [str(row).strip() for row in ids if str(row).strip()]
            if normalized:
                return normalized
    feedback_report = metadata.get("feedbackReport")
    if isinstance(feedback_report, dict):
        references = feedback_report.get("references")
        if isinstance(references, list):
            from_ids = [
                str(row.get("referenceId") or "").strip()
                for row in references
                if isinstance(row, dict) and str(row.get("referenceId") or "").strip()
            ]
            if from_ids:
                return from_ids
    return []


def try_file_attachment_only_reply(
    client: Any,
    *,
    reply_message_id: str,
    parent_message_id: str,
    envelope: InboundMimeEnvelope,
    corpus_key: str,
) -> dict[str, Any]:
    from papyrus_newsroom.email_pdf_intake import file_pdf_payloads_against_reference
    from papyrus_newsroom.email_submissions import _load_registered_reference_processing_records, _message_metadata

    parent_message = client.get_record("Message", parent_message_id) or {}
    if not parent_message:
        return {"ok": False, "reason": "parent-message-not-found"}
    parent_metadata = _message_metadata(parent_message)
    reference_ids = _registered_reference_ids_from_parent(parent_message, parent_metadata)
    if len(reference_ids) != 1:
        return {
            "ok": False,
            "reason": "ambiguous-reference-count",
            "referenceCount": len(reference_ids),
        }

    pdf_attachments = _pdf_attachments(envelope.attachments)
    if not pdf_attachments:
        return {"ok": False, "reason": "no-pdf-attachments"}

    references, _attachments, _relations = _load_registered_reference_processing_records(
        client,
        registered_reference_ids=set(reference_ids),
        import_run_id=str((parent_metadata.get("processingResult") or {}).get("importRunId") or "").strip() or None,
    )
    if not references:
        return {"ok": False, "reason": "reference-not-found"}
    return file_pdf_payloads_against_reference(
        client,
        reference=references[0],
        pdf_attachments=pdf_attachments,
        corpus_key=corpus_key,
        channel="email_reply",
        submission_message_id=reply_message_id,
        parent_submission_message_id=parent_message_id,
    )


def enqueue_console_chat_for_email_reply(
    client: Any,
    *,
    reply_message_id: str,
    parent_message_id: str,
    envelope: InboundMimeEnvelope,
    parent_message: dict[str, Any],
    parent_metadata: dict[str, Any],
    failure_reason: str | None = None,
) -> dict[str, Any]:
    from papyrus_content.newsroom_commands import now_iso

    now = now_iso()
    thread_id = f"thread-email-reply-{parent_message_id}"
    user_text = extract_user_composed_reply_text(envelope.body_text)
    response_target = str(os.environ.get("PAPYRUS_CONSOLE_RESPONSE_TARGET") or "cloud").strip() or "cloud"
    feedback_report = parent_metadata.get("feedbackReport") if isinstance(parent_metadata.get("feedbackReport"), dict) else {}
    prompt_lines = [
        _email_agent_instructions(),
        "",
        "You are handling a reply to a Papyrus inbound reference submission acknowledgment email.",
        f"Parent submission message id: {parent_message_id}",
        f"Inbound reply message id: {reply_message_id}",
        f"Subject: {envelope.subject or parent_message.get('summary') or '(no subject)'}",
    ]
    if failure_reason:
        prompt_lines.append(f"Automatic attachment filing did not complete: {failure_reason}")
    if user_text:
        prompt_lines.extend(["", "Submitter wrote:", user_text])
    else:
        prompt_lines.append("")
        prompt_lines.append("The submitter did not include new prose beyond quoting the acknowledgment.")
    if envelope.attachments:
        prompt_lines.append("")
        prompt_lines.append("MIME attachments present:")
        for attachment in envelope.attachments:
            prompt_lines.append(f"- {attachment.filename} ({attachment.media_type}, {len(attachment.payload)} bytes)")
    if feedback_report:
        prompt_lines.extend(["", "Stored feedback report JSON:", json.dumps(feedback_report, indent=2, sort_keys=True)])
    prompt = "\n".join(prompt_lines).strip()

    thread_input = {
        "id": thread_id,
        "threadKind": "console",
        "status": "active",
        "title": f"Email reply {parent_message_id}",
        "summary": "Inbound email reply assistance",
        "primaryAnchorKind": "message",
        "primaryAnchorId": parent_message_id,
        "primaryAnchorLineageId": parent_message_id,
        "primaryAnchorKey": _CONSOLE_THREAD_ANCHOR_KEY,
        "createdByLabel": str(parent_metadata.get("senderEmail") or parent_message.get("authorLabel") or "email-reply"),
        "messageCount": 0,
        "metadata": json.dumps(
            {
                "channel": "email_reply",
                "parentSubmissionMessageId": parent_message_id,
                "replyMessageId": reply_message_id,
            },
            sort_keys=True,
        ),
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": _CONSOLE_NEWSROOM_FEED_KEY,
    }
    existing_thread = client.get_record("MessageThread", thread_id)
    if not existing_thread:
        client.graphql(
            """
            mutation CreateEmailReplyThread($input: CreateMessageThreadInput!) {
              createMessageThread(input: $input) { id }
            }
            """,
            {"input": thread_input},
        )

    sequence_number = int(existing_thread.get("messageCount") or 0) + 1 if existing_thread else 1
    chat_message_id = f"message-console-email-reply-{uuid.uuid4().hex[:20]}"
    message_input = {
        "id": chat_message_id,
        "threadId": thread_id,
        "parentMessageId": None,
        "sequenceNumber": sequence_number,
        "role": "USER",
        "messageKind": _CONSOLE_MESSAGE_KIND,
        "messageDomain": _CONSOLE_MESSAGE_DOMAIN,
        "messageType": "MESSAGE",
        "content": prompt,
        "status": "active",
        "summary": (envelope.subject or "Email reply")[:180],
        "source": "email-reply",
        "authorLabel": str(parent_metadata.get("senderEmail") or parent_message.get("authorLabel") or "email-reply"),
        "semanticLayer": "working_memory",
        "searchVisibility": "private",
        "responseTarget": response_target,
        "responseStatus": "PENDING",
        "metadata": json.dumps(
            {
                "channel": "email_reply",
                "parentSubmissionMessageId": parent_message_id,
                "replyMessageId": reply_message_id,
                "failureReason": failure_reason,
            },
            sort_keys=True,
        ),
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": _CONSOLE_NEWSROOM_FEED_KEY,
    }
    client.graphql(
        """
        mutation CreateEmailReplyConsoleTurn($input: CreateMessageInput!) {
          createMessage(input: $input) { id }
        }
        """,
        {"input": message_input},
    )
    return {
        "queued": True,
        "threadId": thread_id,
        "chatMessageId": chat_message_id,
        "responseTarget": response_target,
    }


def enqueue_console_chat_for_email_intake(
    client: Any,
    *,
    submission_message_id: str,
    envelope: InboundMimeEnvelope | None,
    message: dict[str, Any],
    metadata: dict[str, Any],
    citations: list[dict[str, Any]],
    corpus_key: str,
) -> dict[str, Any]:
    from papyrus_content.newsroom_commands import now_iso

    now = now_iso()
    thread_id = f"thread-email-intake-{submission_message_id}"
    response_target = str(os.environ.get("PAPYRUS_CONSOLE_RESPONSE_TARGET") or "cloud").strip() or "cloud"
    body_text = envelope.body_text if envelope else _message_body_text(client, message)
    subject = (envelope.subject if envelope else None) or str(message.get("summary") or "(no subject)")
    prompt_lines = [
        _email_agent_instructions(),
        "",
        f"Submission message id: {submission_message_id}",
        f"Corpus key: {corpus_key}",
        f"Subject: {subject}",
        f"Detected citation count: {len(citations)}",
        "",
        "Detected citations JSON:",
        json.dumps(citations, indent=2, sort_keys=True),
        "",
        "Full email body:",
        body_text,
    ]
    if envelope and envelope.attachments:
        prompt_lines.extend(["", "MIME attachments present:"])
        for attachment in envelope.attachments:
            prompt_lines.append(f"- {attachment.filename} ({attachment.media_type}, {len(attachment.payload)} bytes)")
    prompt = "\n".join(prompt_lines).strip()

    thread_input = {
        "id": thread_id,
        "threadKind": "console",
        "status": "active",
        "title": f"Email intake {submission_message_id}",
        "summary": "Inbound email agent intake",
        "primaryAnchorKind": "message",
        "primaryAnchorId": submission_message_id,
        "primaryAnchorLineageId": submission_message_id,
        "primaryAnchorKey": _CONSOLE_THREAD_ANCHOR_KEY,
        "createdByLabel": str(metadata.get("senderEmail") or message.get("authorLabel") or "email-intake"),
        "messageCount": 0,
        "metadata": json.dumps(
            {
                "channel": "email_intake",
                "submissionMessageId": submission_message_id,
                "corpusKey": corpus_key,
            },
            sort_keys=True,
        ),
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": _CONSOLE_NEWSROOM_FEED_KEY,
    }
    existing_thread = client.get_record("MessageThread", thread_id)
    if not existing_thread:
        client.graphql(
            """
            mutation CreateEmailIntakeThread($input: CreateMessageThreadInput!) {
              createMessageThread(input: $input) { id }
            }
            """,
            {"input": thread_input},
        )

    sequence_number = int(existing_thread.get("messageCount") or 0) + 1 if existing_thread else 1
    chat_message_id = f"message-console-email-intake-{uuid.uuid4().hex[:20]}"
    message_input = {
        "id": chat_message_id,
        "threadId": thread_id,
        "parentMessageId": None,
        "sequenceNumber": sequence_number,
        "role": "USER",
        "messageKind": _CONSOLE_MESSAGE_KIND,
        "messageDomain": _CONSOLE_MESSAGE_DOMAIN,
        "messageType": "MESSAGE",
        "content": prompt,
        "status": "active",
        "summary": subject[:180],
        "source": "email-intake",
        "authorLabel": str(metadata.get("senderEmail") or message.get("authorLabel") or "email-intake"),
        "semanticLayer": "working_memory",
        "searchVisibility": "private",
        "responseTarget": response_target,
        "responseStatus": "PENDING",
        "metadata": json.dumps(
            {
                "channel": "email_intake",
                "submissionMessageId": submission_message_id,
                "corpusKey": corpus_key,
                "citationCount": len(citations),
                "captureModelContext": True,
            },
            sort_keys=True,
        ),
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": _CONSOLE_NEWSROOM_FEED_KEY,
    }
    client.graphql(
        """
        mutation CreateEmailIntakeConsoleTurn($input: CreateMessageInput!) {
          createMessage(input: $input) { id }
        }
        """,
        {"input": message_input},
    )
    return {
        "queued": True,
        "threadId": thread_id,
        "chatMessageId": chat_message_id,
        "responseTarget": response_target,
    }


def _message_body_text(client: Any, message: dict[str, Any]) -> str:
    message_id = str(message.get("id") or "").strip()
    if message_id:
        try:
            from papyrus_content.model_attachments import download_attachment_buffer

            attachments = client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", message_id, limit=20)
            body_attachments = [
                entry
                for entry in attachments
                if str(entry.get("role") or "") == "message_body"
                and str(entry.get("status") or "").strip().lower() not in {"deleted", "aborted"}
            ]
            body_attachments.sort(key=lambda entry: str(entry.get("updatedAt") or ""), reverse=True)
            for attachment in body_attachments:
                payload = download_attachment_buffer(client, attachment)
                if payload:
                    return payload.decode("utf-8", errors="replace").strip()
        except Exception:
            pass
    return str(message.get("content") or "")


def process_inbound_email_submission(
    client: Any,
    *,
    message_id: str,
    corpus_key: str,
    steering_config_path: str | None = None,
    apply: bool = True,
) -> dict[str, Any]:
    from papyrus_content.newsroom_commands import now_iso
    from papyrus_newsroom.email_pdf_intake import process_pdf_only_intake
    from papyrus_newsroom.email_submissions import (
        DEFAULT_STEERING_CONFIG,
        _create_find_process_direct_citations,
        _mark_message_completed,
        _mark_message_failed,
        _mark_message_processing,
        _message_metadata,
        _try_send_submission_feedback,
        release_inbound_mime_after_success,
    )

    message = client.get_record("Message", message_id) or {}
    metadata = _message_metadata(message)
    if not metadata.get("authorized"):
        from papyrus_newsroom.email_submissions import UNREGISTERED_SENDER_RESPONSE_ERROR

        rejection_error = str(
            metadata.get("responseError") or message.get("responseError") or UNREGISTERED_SENDER_RESPONSE_ERROR
        ).strip()
        feedback = _try_send_submission_feedback(
            client,
            message_id=message_id,
            processing_error=rejection_error,
        )
        return {
            "ok": False,
            "messageId": message_id,
            "status": "rejected",
            "error": rejection_error,
            "feedbackEmail": feedback,
        }

    envelope = load_inbound_mime_envelope_from_metadata(metadata)
    parent_message_id = (
        str(metadata.get("parentSubmissionMessageId") or "").strip()
        or (
            resolve_parent_submission_message_id(
                in_reply_to=envelope.in_reply_to if envelope else None,
                references_header=envelope.references_header if envelope else None,
            )
            if envelope
            else None
        )
    )
    body_for_classification = envelope.body_text if envelope else _message_body_text(client, message)
    attachments_for_classification = envelope.attachments if envelope else []
    citations = metadata.get("directCitations") if isinstance(metadata.get("directCitations"), list) else []
    if envelope and not citations:
        from papyrus_newsroom.email_mime_intake import extract_direct_citations_from_intake_text

        citations = extract_direct_citations_from_intake_text(
            body_text=envelope.body_text,
            html_parts=list(envelope.html_parts),
        )
        if citations:
            metadata["directCitations"] = citations
            metadata["directCitationCount"] = len(citations)
    classification = (
        str(metadata.get("intakeClassification") or "").strip()
        or classify_inbound_email_intake(
            body_text=body_for_classification,
            citations=[row for row in citations if isinstance(row, dict)],
            parent_message_id=parent_message_id,
            attachments=attachments_for_classification,
        )
    )
    metadata["parentSubmissionMessageId"] = parent_message_id
    metadata["intakeClassification"] = classification
    if envelope:
        metadata["inboundInReplyTo"] = envelope.in_reply_to
        metadata["inboundReferences"] = envelope.references_header
        metadata["inboundAttachmentCount"] = len(envelope.attachments)

    has_agent_attachments = bool(envelope and envelope.attachments)
    if classification == "agent_intake" and (citations or has_agent_attachments):
        started_at = now_iso()
        _mark_message_processing(client, message_id=message_id, started_at=started_at)
        chat = enqueue_console_chat_for_email_intake(
            client,
            submission_message_id=message_id,
            envelope=envelope,
            message=message,
            metadata=metadata,
            citations=[row for row in citations if isinstance(row, dict)],
            corpus_key=corpus_key,
        )
        metadata["chatAgent"] = chat
        finished_at = now_iso()
        result = {"mode": "agent_intake", "chat": chat, "citationCount": len(citations)}
        _mark_message_completed(client, message_id=message_id, finished_at=finished_at, result=result)
        release_inbound_mime_after_success(client, message_id=message_id)
        metadata["feedbackEmailDeferred"] = True
        metadata["feedbackEmailDeferReason"] = "agent-intake-awaiting-filed-references"
        feedback = {
            "sent": False,
            "skipped": True,
            "reason": "deferred-agent-intake",
        }
        client.graphql(
            """
            mutation UpdateEmailIntakeAgentMetadata($input: UpdateMessageInput!) {
              updateMessage(input: $input) { id }
            }
            """,
            {"input": {"id": message_id, "metadata": json.dumps(metadata, sort_keys=True), "updatedAt": finished_at}},
        )
        return {
            "ok": True,
            "messageId": message_id,
            "status": "completed",
            "mode": "agent_intake",
            "chat": chat,
            "feedbackEmail": feedback,
        }

    if classification == "attachment_only_reply" and parent_message_id and envelope:
        started_at = now_iso()
        _mark_message_processing(client, message_id=message_id, started_at=started_at)
        filing = try_file_attachment_only_reply(
            client,
            reply_message_id=message_id,
            parent_message_id=parent_message_id,
            envelope=envelope,
            corpus_key=corpus_key,
        )
        if filing.get("ok"):
            finished_at = now_iso()
            result = {
                "mode": "attachment_only_reply",
                "parentSubmissionMessageId": parent_message_id,
                "filing": filing,
            }
            metadata["attachmentOnlyFiling"] = filing
            _mark_message_completed(client, message_id=message_id, finished_at=finished_at, result=result)
            release_inbound_mime_after_success(client, message_id=message_id)
            client.graphql(
                """
                mutation UpdateEmailReplyMetadata($input: UpdateMessageInput!) {
                  updateMessage(input: $input) { id }
                }
                """,
                {
                    "input": {
                        "id": message_id,
                        "metadata": json.dumps(metadata, sort_keys=True),
                        "updatedAt": finished_at,
                    }
                },
            )
            return {
                "ok": True,
                "messageId": message_id,
                "status": "completed",
                "mode": "attachment_only_reply",
                "filing": filing,
            }

        parent_message = client.get_record("Message", parent_message_id) or {}
        parent_metadata = _message_metadata(parent_message)
        chat = enqueue_console_chat_for_email_reply(
            client,
            reply_message_id=message_id,
            parent_message_id=parent_message_id,
            envelope=envelope,
            parent_message=parent_message,
            parent_metadata=parent_metadata,
            failure_reason=str(filing.get("reason") or "attachment-filing-failed"),
        )
        metadata["attachmentOnlyFiling"] = filing
        metadata["chatFallback"] = chat
        finished_at = now_iso()
        _mark_message_completed(
            client,
            message_id=message_id,
            finished_at=finished_at,
            result={"mode": "chat_fallback", "parentSubmissionMessageId": parent_message_id, "filing": filing, "chat": chat},
        )
        client.graphql(
            """
            mutation UpdateEmailReplyMetadata($input: UpdateMessageInput!) {
              updateMessage(input: $input) { id }
            }
            """,
            {"input": {"id": message_id, "metadata": json.dumps(metadata, sort_keys=True), "updatedAt": finished_at}},
        )
        return {
            "ok": True,
            "messageId": message_id,
            "status": "completed",
            "mode": "chat_fallback",
            "filing": filing,
            "chat": chat,
        }

    if classification == "pdf_only_intake" and envelope:
        started_at = now_iso()
        _mark_message_processing(client, message_id=message_id, started_at=started_at)
        pdf_result = process_pdf_only_intake(
            client,
            message_id=message_id,
            message=message,
            envelope=envelope,
            corpus_key=corpus_key,
            steering_config_path=steering_config_path or str(DEFAULT_STEERING_CONFIG),
            apply=apply,
        )
        if pdf_result.get("ok"):
            finished_at = now_iso()
            metadata["pdfOnlyIntake"] = pdf_result
            result = {"mode": "pdf_only_intake", "pdfOnly": pdf_result}
            _mark_message_completed(client, message_id=message_id, finished_at=finished_at, result=result)
            release_inbound_mime_after_success(client, message_id=message_id)
            create_result = pdf_result.get("createResult") if isinstance(pdf_result.get("createResult"), dict) else None
            reference_entries = (
                create_result.get("referenceFeedback")
                if isinstance(create_result, dict) and isinstance(create_result.get("referenceFeedback"), list)
                else None
            )
            if reference_entries is None and str((pdf_result.get("filing") or {}).get("referenceId") or "").strip():
                from papyrus_newsroom.email_submission_feedback import build_reference_feedback_entries
                from papyrus_newsroom.email_submissions import _load_registered_reference_processing_records

                ref_id = str((pdf_result.get("filing") or {}).get("referenceId") or "").strip()
                refs, atts, _rels = _load_registered_reference_processing_records(
                    client,
                    registered_reference_ids={ref_id},
                    import_run_id=(
                        str((create_result or {}).get("importRunId") or "").strip() if create_result else None
                    ),
                )
                reference_entries = build_reference_feedback_entries(
                    references=refs,
                    attachments=atts,
                    find_result={},
                    process_result={},
                )
            feedback = _try_send_submission_feedback(
                client,
                message_id=message_id,
                processing_result=create_result or pdf_result,
                reference_entries=reference_entries,
            )
            client.graphql(
                """
                mutation UpdateEmailPdfOnlyMetadata($input: UpdateMessageInput!) {
                  updateMessage(input: $input) { id }
                }
                """,
                {"input": {"id": message_id, "metadata": json.dumps(metadata, sort_keys=True), "updatedAt": finished_at}},
            )
            return {
                "ok": True,
                "messageId": message_id,
                "status": "completed",
                "mode": "pdf_only_intake",
                "pdfOnly": pdf_result,
                "feedbackEmail": feedback,
            }

        chat = enqueue_console_chat_for_email_intake(
            client,
            submission_message_id=message_id,
            envelope=envelope,
            message=message,
            metadata=metadata,
            citations=[],
            corpus_key=corpus_key,
        )
        metadata["pdfOnlyIntake"] = pdf_result
        metadata["chatFallback"] = chat
        finished_at = now_iso()
        _mark_message_completed(
            client,
            message_id=message_id,
            finished_at=finished_at,
            result={
                "mode": "pdf_only_agent_fallback",
                "pdfOnly": pdf_result,
                "chat": chat,
            },
        )
        client.graphql(
            """
            mutation UpdateEmailPdfOnlyFallbackMetadata($input: UpdateMessageInput!) {
              updateMessage(input: $input) { id }
            }
            """,
            {"input": {"id": message_id, "metadata": json.dumps(metadata, sort_keys=True), "updatedAt": finished_at}},
        )
        return {
            "ok": True,
            "messageId": message_id,
            "status": "completed",
            "mode": "pdf_only_agent_fallback",
            "pdfOnly": pdf_result,
            "chat": chat,
        }

    if classification == "conversational_reply" and parent_message_id and envelope:
        started_at = now_iso()
        _mark_message_processing(client, message_id=message_id, started_at=started_at)
        parent_message = client.get_record("Message", parent_message_id) or {}
        parent_metadata = _message_metadata(parent_message)
        chat = enqueue_console_chat_for_email_reply(
            client,
            reply_message_id=message_id,
            parent_message_id=parent_message_id,
            envelope=envelope,
            parent_message=parent_message,
            parent_metadata=parent_metadata,
        )
        metadata["chatFallback"] = chat
        finished_at = now_iso()
        _mark_message_completed(
            client,
            message_id=message_id,
            finished_at=finished_at,
            result={"mode": "chat_fallback", "parentSubmissionMessageId": parent_message_id, "chat": chat},
        )
        client.graphql(
            """
            mutation UpdateEmailReplyMetadata($input: UpdateMessageInput!) {
              updateMessage(input: $input) { id }
            }
            """,
            {"input": {"id": message_id, "metadata": json.dumps(metadata, sort_keys=True), "updatedAt": finished_at}},
        )
        return {
            "ok": True,
            "messageId": message_id,
            "status": "completed",
            "mode": "chat_fallback",
            "chat": chat,
        }

    if not citations:
        feedback = _try_send_submission_feedback(
            client,
            message_id=message_id,
            processing_error="No direct citations to process.",
        )
        return {
            "ok": False,
            "messageId": message_id,
            "status": "rejected",
            "error": "No direct citations to process.",
            "feedbackEmail": feedback,
        }

    started_at = now_iso()
    _mark_message_processing(client, message_id=message_id, started_at=started_at)
    try:
        result = _create_find_process_direct_citations(
            client,
            message=message,
            citations=citations,
            corpus_key=corpus_key,
            steering_config_path=steering_config_path or str(DEFAULT_STEERING_CONFIG),
            apply=apply,
        )
        finished_at = now_iso()
        _mark_message_completed(client, message_id=message_id, finished_at=finished_at, result=result)
        mime_release = release_inbound_mime_after_success(client, message_id=message_id)
        feedback = _try_send_submission_feedback(
            client,
            message_id=message_id,
            processing_result=result,
            reference_entries=result.get("referenceFeedback") if isinstance(result.get("referenceFeedback"), list) else None,
        )
        return {
            "ok": True,
            "messageId": message_id,
            "status": "completed",
            "mimeRelease": mime_release,
            "feedbackEmail": feedback,
            **result,
        }
    except Exception as error:
        finished_at = now_iso()
        error_message = str(error)
        _mark_message_failed(client, message_id=message_id, finished_at=finished_at, error_message=error_message)
        feedback = _try_send_submission_feedback(
            client,
            message_id=message_id,
            processing_error=error_message,
        )
        return {
            "ok": False,
            "messageId": message_id,
            "status": "failed",
            "error": error_message,
            "feedbackEmail": feedback,
        }
