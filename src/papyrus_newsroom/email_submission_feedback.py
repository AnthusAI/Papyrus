"""Outbound acknowledgment emails for inbound reference submissions."""

from __future__ import annotations

import html
import json
import os
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, parseaddr
from typing import Any
from urllib.parse import urlparse

from papyrus_content.papyrus_config import build_newsroom_reference_public_url
from papyrus_newsroom.email_submission_replies import feedback_rfc_message_id
from papyrus_newsroom.email_submissions import (
    REJECTION_KIND_UNREGISTERED_SENDER,
    UNREGISTERED_SENDER_RESPONSE_ERROR,
)
from papyrus_content.env import required_environment_value
from papyrus_content.steering import default_corpus_key
from papyrus_content.source_readiness import (
    select_extracted_text_attachment,
    select_reference_attachment_by_role,
)

_ACADEMIC_SOURCE_PLUGINS = frozenset(
    {
        "acm",
        "acl_anthology",
        "arxiv",
        "doi",
        "ieee",
        "springer",
        "default",
    }
)
_NON_PDF_SOURCE_PLUGINS = frozenset({"youtube"})

# Inline styles aligned with app/globals.css (paper, ink, news-desk-semantic-detail).
_EMAIL_PAPER = "#f7f7f4"
_EMAIL_INK = "rgba(0, 0, 0, 0.9)"
_EMAIL_INK_DISPLAY = "rgba(0, 0, 0, 0.86)"
_EMAIL_MUTED = "rgba(0, 0, 0, 0.62)"
_EMAIL_MUTED_STRONG = "rgba(0, 0, 0, 0.74)"
_EMAIL_RULE = "rgba(0, 0, 0, 0.28)"
_EMAIL_SERIF = "Georgia, 'Times New Roman', Times, serif"
_EMAIL_SANS = "Arial, Helvetica, sans-serif"
_EMAIL_RHYTHM_PX = 19


def _email_story_label_style(*, margin: str = "0 0 8px") -> str:
    return (
        f"margin:{margin};color:{_EMAIL_MUTED};font-family:{_EMAIL_SANS};font-size:11px;"
        f"font-weight:800;letter-spacing:0.08em;line-height:1.28;text-transform:uppercase;"
    )


def _email_reference_title_style() -> str:
    return (
        f"margin:0 0 8px;color:{_EMAIL_INK_DISPLAY};font-family:{_EMAIL_SERIF};"
        f"font-size:20px;font-weight:900;line-height:1.08;letter-spacing:0;"
    )


def _email_reference_subtitle_style() -> str:
    return (
        f"margin:0 0 {_EMAIL_RHYTHM_PX}px;color:rgba(0, 0, 0, 0.72);font-family:{_EMAIL_SANS};"
        f"font-size:14px;font-weight:500;line-height:1.38;max-width:34em;"
    )


def _email_reference_summary_style() -> str:
    return (
        f"margin:0 0 {_EMAIL_RHYTHM_PX}px;color:rgba(0, 0, 0, 0.72);font-family:{_EMAIL_SANS};"
        f"font-size:13px;font-weight:500;line-height:1.34;max-width:36em;"
    )


def feedback_email_enabled() -> bool:
    raw = str(os.environ.get("PAPYRUS_INBOUND_FEEDBACK_EMAIL_ENABLED", "true")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def default_feedback_from_address() -> str:
    explicit = str(os.environ.get("PAPYRUS_INBOUND_FEEDBACK_FROM_EMAIL") or "").strip()
    if explicit:
        return explicit
    domain = required_environment_value("PAPYRUS_INBOUND_EMAIL_DOMAIN").lower()
    local_part = str(os.environ.get("PAPYRUS_INBOUND_FEEDBACK_FROM_LOCAL_PART") or "submissions").strip()
    return f"Papyrus Submissions <{local_part}@{domain}>"


def default_feedback_reply_to_address() -> str:
    explicit = str(os.environ.get("PAPYRUS_INBOUND_FEEDBACK_REPLY_TO_EMAIL") or "").strip()
    if explicit:
        return explicit
    domain = required_environment_value("PAPYRUS_INBOUND_EMAIL_DOMAIN").lower()
    local_part = str(os.environ.get("PAPYRUS_INBOUND_EMAIL_LOCAL_PARTS") or "submissions").split(",")[0].strip()
    return f"{local_part or 'submissions'}@{domain}"


def parse_attachment_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def extract_source_plugin_from_attachments(
    reference: dict[str, Any],
    attachments: list[dict[str, Any]],
) -> str | None:
    source_attachment = select_reference_attachment_by_role(reference, attachments, role="source")
    if source_attachment:
        metadata = parse_attachment_metadata(source_attachment.get("metadata"))
        plugin = str(metadata.get("sourcePlugin") or "").strip()
        if plugin:
            return plugin
    for attachment in attachments:
        if str(attachment.get("referenceLineageId") or "") != str(reference.get("lineageId") or ""):
            continue
        metadata = parse_attachment_metadata(attachment.get("metadata"))
        plugin = str(metadata.get("sourcePlugin") or "").strip()
        if plugin:
            return plugin
    return None


def _looks_like_pdf_attachment(attachment: dict[str, Any]) -> bool:
    media_type = str(attachment.get("mediaType") or "").split(";", 1)[0].strip().lower()
    if media_type == "application/pdf":
        return True
    filename = str(attachment.get("filename") or attachment.get("sourceUri") or "").lower()
    return filename.endswith(".pdf")


def pdf_status_for_reference(
    reference: dict[str, Any],
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    lineage_id = str(reference.get("lineageId") or reference.get("referenceLineageId") or "")
    source_attachment = select_reference_attachment_by_role(reference, attachments, role="source")
    pdf_attachments = [
        attachment
        for attachment in attachments
        if str(attachment.get("referenceLineageId") or "") == lineage_id and _looks_like_pdf_attachment(attachment)
    ]
    located = bool(source_attachment and _looks_like_pdf_attachment(source_attachment)) or bool(pdf_attachments)
    primary = source_attachment or (pdf_attachments[0] if pdf_attachments else None)
    return {
        "pdfLocated": located,
        "pdfAttachmentId": str(primary.get("id") or "") if primary else None,
        "pdfFilename": str(primary.get("filename") or "") if primary else None,
        "pdfStoragePath": str(primary.get("storagePath") or "") if primary else None,
        "pdfMediaType": str(primary.get("mediaType") or "") if primary else None,
    }


def is_academic_paper_reference(
    reference: dict[str, Any],
    *,
    source_plugin: str | None = None,
) -> bool:
    plugin = str(source_plugin or "").strip().lower()
    if plugin in _NON_PDF_SOURCE_PLUGINS:
        return False
    if plugin in _ACADEMIC_SOURCE_PLUGINS:
        return True
    source_uri = str(reference.get("sourceUri") or "").lower()
    host = (urlparse(source_uri).netloc or "").lower()
    if any(token in host for token in ("arxiv.org", "doi.org", "acm.org", "aclweb.org", "ieee.org", "springer.com")):
        return True
    if re.search(r"\b10\.\d{4,9}/", source_uri):
        return True
    media_type = str(reference.get("mediaType") or "").lower()
    return media_type == "application/pdf"


def summarize_recorded_attachments(
    reference: dict[str, Any],
    attachments: list[dict[str, Any]],
) -> list[dict[str, str]]:
    lineage_id = str(reference.get("lineageId") or reference.get("referenceLineageId") or "")
    rows: list[dict[str, str]] = []
    for attachment in attachments:
        if str(attachment.get("referenceLineageId") or "") != lineage_id:
            continue
        rows.append(
            {
                "id": str(attachment.get("id") or ""),
                "role": str(attachment.get("role") or ""),
                "filename": str(attachment.get("filename") or ""),
                "mediaType": str(attachment.get("mediaType") or ""),
                "storagePath": str(attachment.get("storagePath") or ""),
            }
        )
    rows.sort(key=lambda row: (row.get("role") or "", row.get("id") or ""))
    return rows


def _process_items_by_reference_id(process_result: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    items = (process_result or {}).get("items")
    if not isinstance(items, list):
        return indexed
    for item in items:
        if not isinstance(item, dict):
            continue
        reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
        reference_id = str(reference.get("id") or "").strip()
        if reference_id:
            indexed[reference_id] = item
    return indexed


def _find_item_by_reference_id(find_result: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    items = (find_result or {}).get("items")
    if not isinstance(items, list):
        return indexed
    for item in items:
        if not isinstance(item, dict):
            continue
        reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
        reference_id = str(reference.get("id") or "").strip()
        if reference_id:
            indexed[reference_id] = item
    return indexed


def _stored_reference_display_fields(reference: dict[str, Any]) -> dict[str, str]:
    try:
        from papyrus_newsroom.reference_curation_signals import _load_reference_metadata_payload

        payload = _load_reference_metadata_payload(reference)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    published = (
        str(reference.get("sourcePublishedAt") or "").strip()
        or str(payload.get("sourcePublishedAt") or payload.get("publishedAt") or "").strip()
    )
    return {
        "title": str(payload.get("title") or "").strip(),
        "subtitle": str(payload.get("subtitle") or "").strip(),
        "summary": str(payload.get("summary") or "").strip(),
        "sourcePublishedAt": published,
    }


def _normalize_url_for_match(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").rstrip("/")
    return f"{host}{path}".lower()


def _match_intake_citation(
    source_uri: str,
    citations: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not citations:
        return None
    normalized_source = _normalize_url_for_match(source_uri)
    if not normalized_source:
        return None
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        citation_url = str(citation.get("url") or "").strip()
        if not citation_url:
            continue
        if _normalize_url_for_match(citation_url) == normalized_source:
            return citation
        if citation_url.rstrip("/") == source_uri.rstrip("/"):
            return citation
    return None


def _looks_like_placeholder_title(title: str, source_uri: str) -> bool:
    normalized_title = str(title or "").strip()
    if not normalized_title:
        return True
    normalized_uri = str(source_uri or "").strip()
    if normalized_uri and normalized_title.lower() in {normalized_uri.lower(), normalized_uri.rstrip("/").lower()}:
        return True
    if re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", normalized_title, flags=re.IGNORECASE):
        return True
    if re.search(r"\barxiv[:\s]*\d{4}\.\d{4,5}", normalized_title, flags=re.IGNORECASE):
        return True
    basename = normalized_uri.rsplit("/", 1)[-1].lower()
    if basename and normalized_title.lower() in {basename, basename.removesuffix(".pdf")}:
        return True
    return False


def reference_entry_is_receipt_ready(entry: dict[str, Any]) -> bool:
    title = str(entry.get("title") or "").strip()
    subtitle = str(entry.get("subtitle") or "").strip()
    summary = str(entry.get("summary") or "").strip()
    if not (title and subtitle and summary):
        return False
    if _looks_like_placeholder_title(title, str(entry.get("sourceUri") or "")):
        return False
    return True


def _format_publication_date_label(raw: str | None) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:.]+Z?", value):
        return value[:10]
    return value


def _human_pipeline_status(find_status: str, summarize_status: str, *, has_extracted_text: bool) -> list[str]:
    notes: list[str] = []
    normalized_find = str(find_status or "").strip().lower()
    normalized_summarize = str(summarize_status or "").strip().lower()
    if normalized_find in {"failed", "error"}:
        notes.append("Source fetch did not complete — we could not retrieve the full text from the URL.")
    elif normalized_find in {"skipped", "skipped_missing_text", "skipped-missing-text"}:
        notes.append("Source fetch was skipped — no extractable text was available at the URL.")
    elif normalized_find in {"not_run", "not-run"} and not has_extracted_text:
        notes.append("Source fetch has not run yet.")
    if normalized_summarize in {"failed", "error"}:
        notes.append("Summary generation failed.")
    elif normalized_summarize in {"skipped", "skipped_missing_text", "skipped-missing-text"}:
        notes.append("Summary was skipped because there was no extracted text to summarize.")
    elif normalized_summarize in {"not_run", "not-run"}:
        notes.append("Summary has not been generated yet.")
    return notes


def build_intake_citation_entries(citations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        url = str(citation.get("url") or "").strip()
        if not url:
            continue
        rows.append(
            {
                "url": url,
                "title": str(citation.get("title") or "").strip() or None,
                "kind": str(citation.get("kind") or citation.get("sourceKind") or "").strip() or None,
                "ingestionRationale": str(citation.get("ingestion_rationale") or citation.get("ingestionRationale") or "").strip()
                or None,
            }
        )
    return rows


def build_reference_feedback_entries(
    *,
    references: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    find_result: dict[str, Any] | None = None,
    process_result: dict[str, Any] | None = None,
    intake_citations: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    find_by_id = _find_item_by_reference_id(find_result)
    process_by_id = _process_items_by_reference_id(process_result)
    entries: list[dict[str, Any]] = []
    for reference in references:
        reference_id = str(reference.get("id") or "").strip()
        if not reference_id:
            continue
        source_plugin = extract_source_plugin_from_attachments(reference, attachments)
        process_item = process_by_id.get(reference_id) or {}
        find_item = find_by_id.get(reference_id) or {}
        generated_subtitle = str(process_item.get("subtitle") or "").strip()
        generated_summary = str(process_item.get("summary") or "").strip()
        generated_title = str(process_item.get("title") or "").strip()
        stored = (
            _stored_reference_display_fields(reference)
            if not (generated_title and generated_subtitle and generated_summary)
            else {
                "title": "",
                "subtitle": "",
                "summary": "",
                "sourcePublishedAt": str(reference.get("sourcePublishedAt") or "").strip(),
            }
        )
        source_uri = str(reference.get("sourceUri") or "")
        intake_match = _match_intake_citation(source_uri, intake_citations)
        title = generated_title or stored["title"] or str(reference.get("title") or "").strip()
        subtitle = generated_subtitle or stored["subtitle"]
        summary = generated_summary or stored["summary"]
        find_status = str(find_item.get("status") or "").strip()
        summarize_status = str(process_item.get("status") or "").strip()
        has_extracted_text = select_extracted_text_attachment(reference, attachments) is not None
        pdf_info = pdf_status_for_reference(reference, attachments)
        academic = is_academic_paper_reference(reference, source_plugin=source_plugin)
        lineage_id = str(reference.get("lineageId") or reference.get("referenceLineageId") or "").strip()
        newsroom_url = build_newsroom_reference_public_url(lineage_id) if lineage_id else None
        publication_date = _format_publication_date_label(
            stored.get("sourcePublishedAt") or str(reference.get("sourcePublishedAt") or "")
        )
        entry = {
            "referenceId": reference_id,
            "referenceLineageId": lineage_id or None,
            "newsroomUrl": newsroom_url,
            "sourceUri": source_uri,
            "receivedUrl": str(intake_match.get("url") or source_uri) if intake_match else source_uri,
            "receivedTitle": str(intake_match.get("title") or "").strip() or None if intake_match else None,
            "title": title,
            "subtitle": subtitle,
            "summary": summary,
            "sourcePublishedAt": publication_date,
            "sourcePlugin": source_plugin,
            "findStatus": find_status or ("found" if has_extracted_text else "not_run"),
            "summarizeStatus": summarize_status or ("generated" if generated_summary else "not_run"),
            "pdfConfirmationRequired": academic,
            "pdfLocated": pdf_info["pdfLocated"] if academic else None,
            "pdfAttachmentId": pdf_info["pdfAttachmentId"],
            "pdfFilename": pdf_info["pdfFilename"],
            "attachments": summarize_recorded_attachments(reference, attachments),
        }
        entry["receiptReady"] = reference_entry_is_receipt_ready(entry)
        entry["statusNotes"] = _human_pipeline_status(
            str(entry.get("findStatus") or ""),
            str(entry.get("summarizeStatus") or ""),
            has_extracted_text=has_extracted_text,
        )
        if entry["receiptReady"]:
            entry["statusNotes"] = ["Ready in your newsroom — title, subtitle, and summary are complete."]
            if publication_date:
                entry["statusNotes"].append(f"Publication date: {publication_date}")
        entries.append(entry)
    return entries


def build_submission_feedback_report(
    *,
    message: dict[str, Any],
    metadata: dict[str, Any],
    processing_result: dict[str, Any] | None = None,
    processing_error: str | None = None,
    reference_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    response_status = str(message.get("responseStatus") or metadata.get("responseStatus") or "").upper()
    result = processing_result if isinstance(processing_result, dict) else metadata.get("processingResult")
    if not isinstance(result, dict):
        result = {}
    if processing_result and isinstance(processing_result, dict):
        result = {**result, **processing_result}
    find_summary = result.get("find") if isinstance(result.get("find"), dict) else {}
    process_summary = result.get("process") if isinstance(result.get("process"), dict) else {}
    citations = metadata.get("directCitations") if isinstance(metadata.get("directCitations"), list) else []
    intake_citations = build_intake_citation_entries([row for row in citations if isinstance(row, dict)])
    return {
        "messageId": str(message.get("id") or ""),
        "subject": str(message.get("summary") or "Email submission"),
        "senderEmail": str(metadata.get("senderEmail") or message.get("authorLabel") or ""),
        "recipientEmail": str(metadata.get("recipientEmail") or ""),
        "responseStatus": response_status,
        "responseError": str(message.get("responseError") or metadata.get("responseError") or processing_error or ""),
        "authorized": metadata.get("authorized") is True,
        "rejectionKind": str(metadata.get("rejectionKind") or "").strip() or None,
        "intakeClassification": str(metadata.get("intakeClassification") or "").strip() or None,
        "directCitationCount": len(citations),
        "intakeCitations": intake_citations,
        "registeredReferenceCount": int(result.get("registeredReferenceCount") or 0),
        "pipeline": {
            "find": {
                "eligible": int(find_summary.get("eligible") or 0),
                "planned": int(find_summary.get("planned") or 0),
                "changes": int(find_summary.get("changes") or 0),
                "failures": int(find_summary.get("failures") or 0),
            },
            "process": {
                "attempted": int(process_summary.get("attempted") or 0),
                "generated": int(process_summary.get("generated") or 0),
            },
        },
        "references": reference_entries or [],
        "processingResult": result,
    }


def _public_site_base_url() -> str:
    return required_environment_value("PAPYRUS_PUBLIC_SITE_BASE_URL").rstrip("/")


def is_unregistered_sender_rejection(report: dict[str, Any]) -> bool:
    if report.get("authorized") is True:
        return False
    if str(report.get("rejectionKind") or "").strip() == REJECTION_KIND_UNREGISTERED_SENDER:
        return True
    status = str(report.get("responseStatus") or "").upper()
    if status != "REJECTED":
        return False
    error = str(report.get("responseError") or "").lower()
    return "only registered papyrus users" in error or "not registered" in error


def format_unregistered_sender_feedback_email(report: dict[str, Any]) -> tuple[str, str, str]:
    subject_line = str(report.get("subject") or "your submission")
    subject = f"Re: {subject_line} — submission not accepted"
    message_id = str(report.get("messageId") or "(unknown)")
    recipient = str(report.get("recipientEmail") or default_feedback_reply_to_address()).strip()
    site_url = _public_site_base_url()
    explanation = UNREGISTERED_SENDER_RESPONSE_ERROR
    body_text = "\n".join(
        [
            "Papyrus could not accept your email submission.",
            "",
            explanation,
            "",
            "Reference submissions by email are limited to registered Papyrus users. "
            "Sign in with the same email address you use for your account, then send citations to "
            f"{recipient}.",
            "",
            f"Sign in: {site_url}",
            "",
            f"Message ID: {message_id}",
        ]
    )
    escaped_explanation = html.escape(explanation)
    escaped_recipient = html.escape(recipient)
    escaped_site = html.escape(site_url, quote=True)
    message_id_html = html.escape(message_id)
    body_html = (
        f'<!DOCTYPE html><html><body style="margin:0;padding:0;background:{_EMAIL_PAPER};color:{_EMAIL_INK};">'
        f'<div style="max-width:640px;margin:0 auto;padding:calc({_EMAIL_RHYTHM_PX}px * 1.5) 16px;'
        f'font-family:{_EMAIL_SERIF};">'
        f'<div style="background:{_EMAIL_PAPER};border:1px solid {_EMAIL_RULE};'
        f'padding:calc({_EMAIL_RHYTHM_PX}px * 1.5);">'
        f'<p style="margin:0 0 {_EMAIL_RHYTHM_PX}px;color:{_EMAIL_INK_DISPLAY};font-family:{_EMAIL_SERIF};'
        f'font-size:22px;font-weight:900;line-height:1.08;">Submission not accepted</p>'
        f'<p style="{_email_story_label_style(margin="0 0 8px")}">Message {message_id_html}</p>'
        f'<p style="margin:0 0 {_EMAIL_RHYTHM_PX}px;">{_status_label_html("REJECTED")}</p>'
        f'<p style="margin:{_EMAIL_RHYTHM_PX}px 0;padding:12px 14px;border-left:3px solid {_EMAIL_RULE};'
        f"background:rgba(0, 0, 0, 0.04);color:{_EMAIL_INK};font-family:{_EMAIL_SANS};"
        f'font-size:14px;line-height:1.5;">{escaped_explanation}</p>'
        f'<p style="margin:0 0 {_EMAIL_RHYTHM_PX}px;color:{_EMAIL_INK};font-family:{_EMAIL_SANS};'
        f'font-size:14px;line-height:1.5;">Reference submissions by email are limited to registered '
        f"Papyrus users. Sign in with the same email address you use for your account, then send citations "
        f"to <strong>{escaped_recipient}</strong>.</p>"
        f'<p style="margin:0 0 {_EMAIL_RHYTHM_PX}px;">'
        f'<a href="{escaped_site}" style="display:inline-block;padding:0 12px;border:1px solid {_EMAIL_RULE};'
        f"background:transparent;color:{_EMAIL_MUTED_STRONG};font-family:{_EMAIL_SANS};"
        f'font-size:11px;font-weight:900;letter-spacing:0.08em;line-height:32px;text-decoration:none;'
        f'text-transform:uppercase;">Sign in to Papyrus</a></p>'
        "</div></div></body></html>"
    )
    return subject, body_text, body_html


def _feedback_email_subject(report: dict[str, Any]) -> tuple[str, str]:
    subject_line = str(report.get("subject") or "your submission")
    status = str(report.get("responseStatus") or "").upper()
    if is_unregistered_sender_rejection(report):
        return f"Re: {subject_line} — submission not accepted", status
    if status == "COMPLETED":
        subject = f"Re: {subject_line} — processed"
    elif status == "FAILED":
        subject = f"Re: {subject_line} — processing failed"
    elif status == "REJECTED":
        subject = f"Re: {subject_line} — not accepted"
    else:
        subject = f"Re: {subject_line} — update"
    return subject, status


def _status_label_html(status: str) -> str:
    normalized = status or "UNKNOWN"
    return (
        f'<span style="display:inline-block;padding:4px 10px;border:1px solid {_EMAIL_RULE};'
        f"background:rgba(0, 0, 0, 0.06);color:{_EMAIL_INK_DISPLAY};font-family:{_EMAIL_SANS};"
        f'font-size:11px;font-weight:800;letter-spacing:0.08em;line-height:1;text-transform:uppercase;">'
        f"{html.escape(normalized)}</span>"
    )


def _append_intake_citations_plain(lines: list[str], citations: list[dict[str, Any]]) -> None:
    if not citations:
        return
    lines.extend(["", "What we received:"])
    for index, citation in enumerate(citations, start=1):
        if not isinstance(citation, dict):
            continue
        label = citation.get("title") or citation.get("url") or "(link)"
        lines.append(f"  {index}. {label}")
        url = str(citation.get("url") or "").strip()
        if url and label != url:
            lines.append(f"     {url}")
        kind = str(citation.get("kind") or "").strip()
        if kind:
            lines.append(f"     Type: {kind}")


def _append_reference_feedback_plain(lines: list[str], entry: dict[str, Any], index: int) -> None:
    lines.append("")
    lines.append(f"{index}. {entry.get('title') or '(untitled)'}")
    received_title = str(entry.get("receivedTitle") or "").strip()
    received_url = str(entry.get("receivedUrl") or entry.get("sourceUri") or "").strip()
    if received_title and received_title != str(entry.get("title") or "").strip():
        lines.append(f"   Received as: {received_title}")
    if received_url:
        lines.append(f"   Source URL: {received_url}")
    if entry.get("sourcePublishedAt"):
        lines.append(f"   Publication date: {entry.get('sourcePublishedAt')}")
    if entry.get("subtitle"):
        lines.append(f"   {entry.get('subtitle')}")
    if entry.get("summary"):
        lines.append("")
        lines.append(f"   {entry.get('summary')}")
    newsroom_url = str(entry.get("newsroomUrl") or "").strip()
    if newsroom_url:
        lines.append("")
        lines.append(f"   {newsroom_url}")
    status_notes = entry.get("statusNotes") if isinstance(entry.get("statusNotes"), list) else []
    for note in status_notes:
        if isinstance(note, str) and note.strip():
            lines.append(f"   {note.strip()}")
    plugin = entry.get("sourcePlugin")
    if plugin:
        lines.append(f"   Source plugin: {plugin}")
    if entry.get("pdfConfirmationRequired"):
        located = entry.get("pdfLocated")
        if located is True:
            pdf_name = entry.get("pdfFilename") or entry.get("pdfAttachmentId") or "source PDF"
            lines.append(f"   PDF: located ({pdf_name})")
        elif located is False:
            lines.append("   PDF: not located")
        else:
            lines.append("   PDF: unknown")
    attachments = entry.get("attachments") if isinstance(entry.get("attachments"), list) else []
    if attachments:
        lines.append("   Attachments recorded:")
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            role = attachment.get("role") or "attachment"
            name = attachment.get("filename") or attachment.get("id") or "file"
            media_type = attachment.get("mediaType") or ""
            suffix = f" ({media_type})" if media_type else ""
            lines.append(f"     - {role}: {name}{suffix}")


def _intake_citations_html_block(citations: list[dict[str, Any]]) -> str:
    if not citations:
        return ""
    items: list[str] = []
    for index, citation in enumerate(citations, start=1):
        if not isinstance(citation, dict):
            continue
        url = str(citation.get("url") or "").strip()
        label = str(citation.get("title") or url or "(link)")
        escaped_label = html.escape(label)
        row = f'<li style="margin:0 0 10px;color:{_EMAIL_INK};font-family:{_EMAIL_SANS};font-size:13px;line-height:1.4;">'
        row += f'<span style="{_email_story_label_style(margin="0 0 4px")}">Received {index}</span><br/>'
        if url:
            escaped_url = html.escape(url, quote=True)
            row += f'<a href="{escaped_url}" style="color:{_EMAIL_INK};text-decoration:underline;">{escaped_label}</a>'
        else:
            row += escaped_label
        kind = str(citation.get("kind") or "").strip()
        if kind:
            row += f'<br/><span style="color:{_EMAIL_MUTED};font-size:11px;">{html.escape(kind)}</span>'
        row += "</li>"
        items.append(row)
    return (
        f'<p style="{_email_story_label_style(margin=f"{_EMAIL_RHYTHM_PX}px 0 12px")}">What we received</p>'
        f'<ul style="margin:0 0 {_EMAIL_RHYTHM_PX}px;padding:0;list-style:none;">{"".join(items)}</ul>'
    )


def _reference_feedback_html_block(entry: dict[str, Any], index: int) -> str:
    title = html.escape(str(entry.get("title") or "(untitled)"))
    newsroom_url = str(entry.get("newsroomUrl") or "").strip()
    parts = [
        f'<article style="margin:0 0 {_EMAIL_RHYTHM_PX}px;padding:{_EMAIL_RHYTHM_PX}px 0 0;'
        f"border-top:2px solid {_EMAIL_RULE};min-width:0;\">",
        f'<p style="{_email_story_label_style(margin="0 0 10px")}">Reference {index}</p>',
        f'<p style="{_email_reference_title_style()}">{title}</p>',
    ]
    received_title = str(entry.get("receivedTitle") or "").strip()
    received_url = str(entry.get("receivedUrl") or entry.get("sourceUri") or "").strip()
    if received_title and received_title != str(entry.get("title") or "").strip():
        parts.append(
            f'<p style="margin:0 0 8px;color:{_EMAIL_MUTED};font-family:{_EMAIL_SANS};font-size:12px;line-height:1.34;">'
            f"Received as: {html.escape(received_title)}</p>"
        )
    publication_date = str(entry.get("sourcePublishedAt") or "").strip()
    if publication_date:
        parts.append(
            f'<p style="margin:0 0 8px;color:{_EMAIL_MUTED_STRONG};font-family:{_EMAIL_SANS};'
            f'font-size:12px;font-weight:600;line-height:1.34;">'
            f"Publication date: {html.escape(publication_date)}</p>"
        )
    subtitle = str(entry.get("subtitle") or "").strip()
    if subtitle:
        parts.append(f'<p style="{_email_reference_subtitle_style()}">{html.escape(subtitle)}</p>')
    summary = str(entry.get("summary") or "").strip()
    if summary:
        parts.append(f'<p style="{_email_reference_summary_style()}">{html.escape(summary)}</p>')
    if newsroom_url:
        escaped_url = html.escape(newsroom_url, quote=True)
        parts.append(
            '<p style="margin:0 0 12px;">'
            f'<a href="{escaped_url}" style="display:inline-block;padding:0 12px;border:1px solid {_EMAIL_RULE};'
            f"background:transparent;color:{_EMAIL_MUTED_STRONG};font-family:{_EMAIL_SANS};"
            f'font-size:11px;font-weight:900;letter-spacing:0.08em;line-height:32px;text-decoration:none;'
            f'text-transform:uppercase;">Open in Papyrus</a></p>'
        )
    if received_url:
        escaped_source = html.escape(received_url, quote=True)
        parts.append(
            f'<p style="margin:0 0 12px;font-family:{_EMAIL_SANS};font-size:12px;line-height:1.34;">'
            f'<a href="{escaped_source}" style="color:{_EMAIL_INK};text-decoration:underline;'
            f'text-underline-offset:2px;word-break:break-all;">{html.escape(received_url)}</a></p>'
        )
    status_notes = entry.get("statusNotes") if isinstance(entry.get("statusNotes"), list) else []
    for note in status_notes:
        if not isinstance(note, str) or not note.strip():
            continue
        parts.append(
            f'<p style="margin:0 0 8px;color:{_EMAIL_MUTED};font-family:{_EMAIL_SANS};'
            f'font-size:12px;line-height:1.4;">{html.escape(note.strip())}</p>'
        )
    plugin = entry.get("sourcePlugin")
    pdf_note: str | None = None
    if entry.get("pdfConfirmationRequired"):
        located = entry.get("pdfLocated")
        if located is True:
            pdf_name = entry.get("pdfFilename") or entry.get("pdfAttachmentId") or "source PDF"
            pdf_note = f"PDF on file: {pdf_name}"
        elif located is False:
            pdf_note = "PDF not located yet"
    meta_tokens: list[str] = []
    if plugin:
        meta_tokens.append(html.escape(str(plugin)))
    if pdf_note:
        meta_tokens.append(html.escape(pdf_note))
    if meta_tokens:
        parts.append(
            f'<p style="{_email_story_label_style(margin="0")}">{" · ".join(meta_tokens)}</p>'
        )
    attachments = entry.get("attachments") if isinstance(entry.get("attachments"), list) else []
    if attachments:
        attachment_items: list[str] = []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            role = html.escape(str(attachment.get("role") or "attachment").upper())
            name = html.escape(str(attachment.get("filename") or attachment.get("id") or "file"))
            attachment_items.append(
                f'<li style="margin:0 0 6px;{_email_story_label_style(margin="0")}">{role} · {name}</li>'
            )
        if attachment_items:
            parts.append(
                f'<ul style="margin:12px 0 0;padding:0;list-style:none;">{"".join(attachment_items)}</ul>'
            )
    parts.append("</article>")
    return "".join(parts)


def _pipeline_stats_html(
    *,
    find_summary: dict[str, Any],
    process_summary: dict[str, Any],
    registered_reference_count: int,
) -> str:
    rows = [
        ("Find", f"{find_summary.get('changes', 0)} applied · {find_summary.get('failures', 0)} failed"),
        ("Summarize", f"{process_summary.get('generated', 0)} / {process_summary.get('attempted', 0)}"),
        ("Registered", str(registered_reference_count)),
    ]
    row_html: list[str] = []
    for label, value in rows:
        row_html.append(
            f'<tr><td style="padding:5px 0;{_email_story_label_style(margin="0")}">{html.escape(label)}</td>'
            f'<td style="padding:5px 0;text-align:right;color:{_EMAIL_INK_DISPLAY};font-family:{_EMAIL_SANS};'
            f'font-size:13px;font-weight:600;line-height:1.34;">{html.escape(value)}</td></tr>'
        )
    return (
        f'<table style="width:100%;margin:{_EMAIL_RHYTHM_PX}px 0;border-collapse:collapse;" role="presentation">'
        f"<tbody>{''.join(row_html)}</tbody></table>"
    )


def is_agent_intake_acknowledgment(report: dict[str, Any]) -> bool:
    if str(report.get("intakeClassification") or "").strip() != "agent_intake":
        return False
    result = report.get("processingResult")
    if isinstance(result, dict) and str(result.get("mode") or "").strip() == "agent_intake":
        return True
    return int(report.get("directCitationCount") or 0) > 1


def format_agent_intake_feedback_email(report: dict[str, Any]) -> tuple[str, str, str]:
    subject_line = str(report.get("subject") or "your submission")
    subject = f"Re: {subject_line} — received for agent intake"
    message_id = str(report.get("messageId") or "(unknown)")
    citation_count = int(report.get("directCitationCount") or 0)
    body_text = "\n".join(
        [
            "Papyrus received your email submission.",
            "",
            f"We found {citation_count} link(s) and started the intake agent to file relevant references",
            "(newsletter-style submissions may include many links — footer and unsubscribe links are skipped).",
            "",
            "You will receive another message when individual references are registered and summarized.",
            "",
            f"Message ID: {message_id}",
        ]
    )
    message_id_html = html.escape(message_id)
    body_html = (
        f'<!DOCTYPE html><html><body style="margin:0;padding:0;background:{_EMAIL_PAPER};color:{_EMAIL_INK};">'
        f'<div style="max-width:640px;margin:0 auto;padding:calc({_EMAIL_RHYTHM_PX}px * 1.5) 16px;">'
        f'<div style="background:{_EMAIL_PAPER};border:1px solid {_EMAIL_RULE};padding:calc({_EMAIL_RHYTHM_PX}px * 1.5);">'
        f'<p style="margin:0 0 {_EMAIL_RHYTHM_PX}px;font-family:{_EMAIL_SERIF};font-size:22px;font-weight:900;">'
        f"Submission received</p>"
        f'<p style="{_email_story_label_style(margin="0 0 8px")}">Message {message_id_html}</p>'
        f'<p style="margin:0;color:{_EMAIL_INK};font-family:{_EMAIL_SANS};font-size:14px;line-height:1.5;">'
        f"We found <strong>{citation_count}</strong> link(s) and started the intake agent to file relevant "
        f"references. Newsletter-style mail may include many links; navigation and unsubscribe URLs are skipped."
        f"</p></div></div></body></html>"
    )
    return subject, body_text, body_html


def format_submission_feedback_email(report: dict[str, Any]) -> tuple[str, str, str]:
    if is_unregistered_sender_rejection(report):
        return format_unregistered_sender_feedback_email(report)

    subject, status = _feedback_email_subject(report)

    lines = [
        "Papyrus received your reference submission.",
        "",
        f"Message ID: {report.get('messageId') or '(unknown)'}",
        f"Status: {status or 'UNKNOWN'}",
    ]
    error = str(report.get("responseError") or "").strip()
    if error:
        lines.extend(["", f"Details: {error}"])

    pipeline = report.get("pipeline") if isinstance(report.get("pipeline"), dict) else {}
    find_summary = pipeline.get("find") if isinstance(pipeline.get("find"), dict) else {}
    process_summary = pipeline.get("process") if isinstance(pipeline.get("process"), dict) else {}
    if status in {"COMPLETED", "FAILED", "IN_PROGRESS"}:
        lines.extend(
            [
                "",
                "Pipeline:",
                (
                    f"- Find: {find_summary.get('changes', 0)} change(s) applied, "
                    f"{find_summary.get('failures', 0)} failure(s) "
                    f"({find_summary.get('eligible', 0)} eligible)"
                ),
                (
                    f"- Summarize: {process_summary.get('generated', 0)} generated of "
                    f"{process_summary.get('attempted', 0)} attempted"
                ),
                f"- References registered: {report.get('registeredReferenceCount', 0)}",
            ]
        )

    intake_citations = report.get("intakeCitations") if isinstance(report.get("intakeCitations"), list) else []
    _append_intake_citations_plain(lines, [row for row in intake_citations if isinstance(row, dict)])

    references = report.get("references") if isinstance(report.get("references"), list) else []
    reference_blocks_html: list[str] = []
    if references:
        lines.extend(["", "References filed in Papyrus:"])
        index = 0
        for entry in references:
            if not isinstance(entry, dict):
                continue
            index += 1
            _append_reference_feedback_plain(lines, entry, index)
            reference_blocks_html.append(_reference_feedback_html_block(entry, index))

    lines.extend(
        [
            "",
            (
                "Send a single PDF with no URL in the body to register or update a paper from the file. "
                "Reply with only PDF attachments (no message text) to file a missing source on a single-reference submission. "
                "Include a message in your reply, or questions, and the Papyrus agent will help. "
                f"New citations with a URL or DOI: email {default_feedback_reply_to_address()}."
            ),
        ]
    )
    body_text = "\n".join(lines)

    message_id = html.escape(str(report.get("messageId") or "(unknown)"))
    error_html = ""
    if error:
        error_html = (
            f'<p style="margin:{_EMAIL_RHYTHM_PX}px 0;padding:12px 14px;border-left:3px solid {_EMAIL_RULE};'
            f"background:rgba(0, 0, 0, 0.04);color:{_EMAIL_INK};font-family:{_EMAIL_SANS};"
            f'font-size:13px;line-height:1.45;">{html.escape(error)}</p>'
        )
    pipeline_html = ""
    if status in {"COMPLETED", "FAILED", "IN_PROGRESS"}:
        pipeline_html = _pipeline_stats_html(
            find_summary=find_summary,
            process_summary=process_summary,
            registered_reference_count=int(report.get("registeredReferenceCount") or 0),
        )
    intake_html = _intake_citations_html_block([row for row in intake_citations if isinstance(row, dict)])
    references_html = "".join(reference_blocks_html)
    if references_html:
        references_html = (
            f'<p style="{_email_story_label_style(margin=f"{_EMAIL_RHYTHM_PX}px 0 12px")}">References filed in Papyrus</p>'
            f"{references_html}"
        )

    body_html = (
        f'<!DOCTYPE html><html><body style="margin:0;padding:0;background:{_EMAIL_PAPER};color:{_EMAIL_INK};">'
        f'<div style="max-width:640px;margin:0 auto;padding:calc({_EMAIL_RHYTHM_PX}px * 1.5) 16px;'
        f'font-family:{_EMAIL_SERIF};">'
        f'<div style="background:{_EMAIL_PAPER};border:1px solid {_EMAIL_RULE};'
        f'padding:calc({_EMAIL_RHYTHM_PX}px * 1.5);">'
        f'<p style="margin:0 0 {_EMAIL_RHYTHM_PX}px;color:{_EMAIL_INK_DISPLAY};font-family:{_EMAIL_SERIF};'
        f'font-size:22px;font-weight:900;line-height:1.08;">Your reference submission</p>'
        f'<p style="{_email_story_label_style(margin="0 0 8px")}">Message {message_id}</p>'
        f'<p style="margin:0 0 {_EMAIL_RHYTHM_PX}px;">{_status_label_html(status)}</p>'
        f"{error_html}"
        f"{pipeline_html}"
        f"{intake_html}"
        f"{references_html}"
        f'<p style="margin:calc({_EMAIL_RHYTHM_PX}px * 1.5) 0 0;padding-top:{_EMAIL_RHYTHM_PX}px;'
        f'border-top:1px solid {_EMAIL_RULE};color:{_EMAIL_MUTED};font-family:{_EMAIL_SANS};'
        f'font-size:12px;line-height:1.45;">Send a single PDF with no URL in the body to register or update a paper from the file. '
        f"Reply with only PDF attachments (no message text) to file a missing source on a single-reference submission. "
        f"Include a message in your reply, or questions, and the Papyrus agent will help. "
        f"New citations with a URL or DOI: email {html.escape(default_feedback_reply_to_address())}.</p>"
        "</div>"
        "</div></body></html>"
    )
    return subject, body_text, body_html


FEEDBACK_EMAIL_MAX_DEFER_ATTEMPTS = 3


def _registered_reference_ids_from_processing(processing_result: dict[str, Any] | None) -> set[str]:
    if not isinstance(processing_result, dict):
        return set()
    ids = {
        str(row).strip()
        for row in (processing_result.get("registeredReferenceIds") or [])
        if str(row).strip()
    }
    return ids


def prepare_reference_entries_for_feedback(
    client: Any,
    *,
    message: dict[str, Any],
    metadata: dict[str, Any],
    processing_result: dict[str, Any] | None = None,
    reference_entries: list[dict[str, Any]] | None = None,
    corpus_key: str | None = None,
    steering_config_path: str | None = None,
    re_enrich: bool = True,
) -> list[dict[str, Any]]:
    """Load references, optionally re-run enrichment, and build receipt-ready feedback rows."""
    from papyrus_newsroom.email_submissions import (
        DEFAULT_STEERING_CONFIG,
        _load_registered_reference_processing_records,
        run_registered_reference_enrichment,
    )

    result = processing_result if isinstance(processing_result, dict) else metadata.get("processingResult")
    if not isinstance(result, dict):
        result = {}
    registered_reference_ids = _registered_reference_ids_from_processing(result)
    import_run_id = str(result.get("importRunId") or "").strip() or None
    resolved_corpus_key = (
        str(corpus_key or os.environ.get("PAPYRUS_INBOUND_EMAIL_CORPUS_KEY") or default_corpus_key()).strip()
    )
    resolved_steering = steering_config_path or str(DEFAULT_STEERING_CONFIG)
    citations = metadata.get("directCitations") if isinstance(metadata.get("directCitations"), list) else []

    find_result: dict[str, Any] | None = None
    process_result: dict[str, Any] | None = None
    references: list[dict[str, Any]] = []
    attachments: list[dict[str, Any]] = []

    if registered_reference_ids and re_enrich:
        references, attachments, _source_find, find_result, process_result = run_registered_reference_enrichment(
            client,
            registered_reference_ids=registered_reference_ids,
            import_run_id=import_run_id,
            corpus_key=resolved_corpus_key,
            steering_config_path=resolved_steering,
        )
    elif registered_reference_ids:
        references, attachments, _relations = _load_registered_reference_processing_records(
            client,
            registered_reference_ids=registered_reference_ids,
            import_run_id=import_run_id,
        )
    elif reference_entries:
        return reference_entries

    if references:
        return build_reference_feedback_entries(
            references=references,
            attachments=attachments,
            find_result=find_result,
            process_result=process_result,
            intake_citations=[row for row in citations if isinstance(row, dict)],
        )
    if reference_entries:
        return reference_entries
    return []


def references_are_receipt_ready(reference_entries: list[dict[str, Any]]) -> bool:
    if not reference_entries:
        return False
    return all(reference_entry_is_receipt_ready(entry) for entry in reference_entries if isinstance(entry, dict))


def _should_send_partial_failure_receipt(metadata: dict[str, Any]) -> bool:
    attempts = int(metadata.get("feedbackEmailDeferAttempts") or 0)
    return attempts >= FEEDBACK_EMAIL_MAX_DEFER_ATTEMPTS


def _record_feedback_deferred(
    client: Any,
    *,
    message_id: str,
    metadata: dict[str, Any],
    reason: str,
    reference_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from papyrus_content.newsroom_commands import now_iso

    metadata["feedbackEmailDeferred"] = True
    metadata["feedbackEmailDeferReason"] = reason
    metadata["feedbackEmailDeferAttempts"] = int(metadata.get("feedbackEmailDeferAttempts") or 0) + 1
    metadata["feedbackEmailDeferredAt"] = now_iso()
    if reference_entries is not None:
        metadata["feedbackEmailPendingReferences"] = reference_entries
    client.graphql(
        """
        mutation UpdateEmailSubmissionFeedbackDefer($input: UpdateMessageInput!) {
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
    return {
        "sent": False,
        "skipped": True,
        "reason": "deferred-awaiting-enrichment",
        "deferReason": reason,
        "deferAttempts": metadata.get("feedbackEmailDeferAttempts"),
    }


def send_submission_feedback_email(
    *,
    to_address: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    from_address: str | None = None,
    reply_to: str | None = None,
    submission_message_id: str | None = None,
    ses_client: Any | None = None,
) -> dict[str, Any]:
    recipient = parseaddr(str(to_address or "").strip())[1]
    if not recipient:
        raise ValueError("Feedback email requires a recipient address.")

    sender = from_address or default_feedback_from_address()
    _, sender_email = parseaddr(sender)
    if not sender_email:
        raise ValueError("Feedback email requires a valid From address.")

    import boto3

    client = ses_client or boto3.client("ses")
    reply_target = str(reply_to or default_feedback_reply_to_address()).strip()
    rfc_message_id = (
        feedback_rfc_message_id(submission_message_id) if str(submission_message_id or "").strip() else None
    )
    if body_html:
        mime_message: MIMEMultipart | MIMEText = MIMEMultipart("alternative")
        mime_message.attach(MIMEText(body_text, "plain", "utf-8"))
        mime_message.attach(MIMEText(body_html, "html", "utf-8"))
    else:
        mime_message = MIMEText(body_text, "plain", "utf-8")
    mime_message["Subject"] = subject
    mime_message["From"] = sender
    mime_message["To"] = recipient
    mime_message["Date"] = formatdate(localtime=True)
    if reply_target:
        mime_message["Reply-To"] = reply_target
    if rfc_message_id:
        mime_message["Message-ID"] = rfc_message_id

    response = client.send_raw_email(
        Source=sender_email,
        Destinations=[recipient],
        RawMessage={"Data": mime_message.as_bytes()},
    )
    return {
        "sent": True,
        "messageId": response.get("MessageId"),
        "rfcMessageId": rfc_message_id,
        "to": recipient,
        "from": sender,
    }


def maybe_send_submission_feedback_email(
    client: Any,
    *,
    message_id: str,
    reference_entries: list[dict[str, Any]] | None = None,
    processing_result: dict[str, Any] | None = None,
    processing_error: str | None = None,
    ses_client: Any | None = None,
    force: bool = False,
) -> dict[str, Any]:
    from papyrus_content.newsroom_commands import now_iso
    from papyrus_newsroom.email_submissions import _message_metadata

    if not feedback_email_enabled():
        return {"sent": False, "skipped": True, "reason": "disabled"}

    message = client.get_record("Message", message_id) or {}
    if not message:
        return {"sent": False, "skipped": True, "reason": "message-not-found"}

    metadata = _message_metadata(message)
    if metadata.get("feedbackEmailSentAt") and not force:
        return {
            "sent": False,
            "skipped": True,
            "reason": "already-sent",
            "feedbackEmailMessageId": metadata.get("feedbackEmailMessageId"),
        }

    sender_email = str(metadata.get("senderEmail") or message.get("authorLabel") or "").strip()
    if not sender_email:
        return {"sent": False, "skipped": True, "reason": "missing-sender"}

    response_status = str(message.get("responseStatus") or metadata.get("responseStatus") or "").upper()
    is_rejection = response_status == "REJECTED" or metadata.get("authorized") is False
    resolved_processing = (
        processing_result
        if isinstance(processing_result, dict)
        else metadata.get("processingResult") if isinstance(metadata.get("processingResult"), dict) else None
    )
    prepared_entries = reference_entries
    if not is_rejection:
        prepared_entries = prepare_reference_entries_for_feedback(
            client,
            message=message,
            metadata=metadata,
            processing_result=resolved_processing,
            reference_entries=reference_entries,
            re_enrich=not force,
        )
        registered_ids = _registered_reference_ids_from_processing(resolved_processing)
        intake_classification = str(metadata.get("intakeClassification") or "").strip()
        if intake_classification == "agent_intake" and not registered_ids and not force:
            return _record_feedback_deferred(
                client,
                message_id=message_id,
                metadata=metadata,
                reason="agent-intake-awaiting-filed-references",
                reference_entries=prepared_entries,
            )
        if registered_ids and prepared_entries and not references_are_receipt_ready(prepared_entries):
            if not force and not _should_send_partial_failure_receipt(metadata):
                return _record_feedback_deferred(
                    client,
                    message_id=message_id,
                    metadata=metadata,
                    reason="awaiting-title-subtitle-summary",
                    reference_entries=prepared_entries,
                )

    report = build_submission_feedback_report(
        message=message,
        metadata=metadata,
        processing_result=processing_result,
        processing_error=processing_error,
        reference_entries=prepared_entries,
    )
    subject, body_text, body_html = format_submission_feedback_email(report)
    send_result = send_submission_feedback_email(
        to_address=sender_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        reply_to=default_feedback_reply_to_address(),
        submission_message_id=message_id,
        ses_client=ses_client,
    )

    metadata["feedbackEmailSentAt"] = now_iso()
    metadata["feedbackEmailMessageId"] = send_result.get("messageId")
    metadata["feedbackRfcMessageId"] = send_result.get("rfcMessageId")
    metadata["feedbackEmailTo"] = send_result.get("to")
    metadata["feedbackEmailFrom"] = send_result.get("from")
    metadata["feedbackReport"] = report
    metadata.pop("feedbackEmailDeferred", None)
    metadata.pop("feedbackEmailDeferReason", None)
    metadata.pop("feedbackEmailPendingReferences", None)
    client.graphql(
        """
        mutation UpdateEmailSubmissionFeedbackMetadata($input: UpdateMessageInput!) {
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
    return send_result


def send_feedback_only_for_message(
    client: Any,
    *,
    message_id: str,
    ses_client: Any | None = None,
) -> dict[str, Any]:
    """Send acknowledgment for an existing message without re-running processing."""
    from papyrus_newsroom.email_submissions import _message_metadata

    message = client.get_record("Message", message_id) or {}
    metadata = _message_metadata(message)
    processing_result = metadata.get("processingResult") if isinstance(metadata.get("processingResult"), dict) else None
    reference_entries: list[dict[str, Any]] = []
    existing_report = metadata.get("feedbackReport")
    if isinstance(existing_report, dict) and isinstance(existing_report.get("references"), list):
        reference_entries = [row for row in existing_report["references"] if isinstance(row, dict)]
    if not reference_entries and isinstance(processing_result, dict):
        stored_feedback = processing_result.get("referenceFeedback")
        if isinstance(stored_feedback, list):
            reference_entries = [row for row in stored_feedback if isinstance(row, dict)]
    if not reference_entries:
        reference_entries = prepare_reference_entries_for_feedback(
            client,
            message=message,
            metadata=metadata,
            processing_result=processing_result if isinstance(processing_result, dict) else None,
            reference_entries=None,
        )
    return maybe_send_submission_feedback_email(
        client,
        message_id=message_id,
        reference_entries=reference_entries or None,
        processing_result=processing_result,
        ses_client=ses_client,
        force=True,
    )
