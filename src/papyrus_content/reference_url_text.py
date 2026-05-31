from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .env import BIBLICUS_ROOT, load_amplify_outputs, storage_bucket_from_amplify_outputs
from .ids import hash_short, reference_lineage_id_for, semantic_node_lineage_id_for, safe_id
from .model_defaults import DEFAULT_REFERENCE_FILTER_MODEL
from .relation_types import semantic_relation_type_fields_for_predicate
from .source_site_plugins import resolve_accessible_pdf_url_for_reference, resolve_source_site_enrichment
from .source_readiness import (
    select_reference_attachment_by_role,
    select_extracted_text_attachment,
    select_extracted_text_raw_attachment,
)

try:
    import boto3
except ModuleNotFoundError:  # pragma: no cover - boto3 exists in normal runtime
    boto3 = None

ARTICLE_TEXT_SUBPROCESS_TIMEOUT_SECONDS = 240


def build_reference_url_text_attachment_plans(
    *,
    references: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    semantic_relations: list[dict[str, Any]] | None = None,
    corpus_key_by_id: dict[str, str] | None = None,
    corpus_id: str | None = None,
    reference_ids: set[str] | None = None,
    external_item_ids: set[str] | None = None,
    curation_status: str = "all",
    max_count: int | None = None,
    force: bool = False,
    model: str = DEFAULT_REFERENCE_FILTER_MODEL,
    pdf_only: bool = False,
    grobid_url: str | None = None,
    allow_discovery: bool = False,
    find_only: bool = False,
) -> dict[str, Any]:
    corpus_key_by_id = corpus_key_by_id or {}
    semantic_relations = semantic_relations or []
    selected_reference_ids = set(reference_ids or [])
    selected_external_item_ids = set(external_item_ids or [])
    plans: list[dict[str, Any]] = []
    reference_records: list[dict[str, Any]] = []
    graph_records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    filter_fallbacks: list[dict[str, Any]] = []
    skipped_existing = 0
    eligible = 0
    planned_references = 0
    filtered_count = 0
    fallback_raw_count = 0
    skipped_missing_source = 0
    skipped_needs_find = 0
    skipped_non_pdf = 0
    failed_grobid = 0
    authors_parsed = 0
    authors_linked = 0
    citations_parsed = 0
    citations_upserted = 0
    citations_skipped_low_confidence = 0
    citation_relations_created = 0
    citation_graph_warnings: list[dict[str, Any]] = []
    doi_resolved = 0
    doi_pdf_selected = 0
    doi_pdf_missed = 0
    doi_search_used = 0
    doi_search_hit = 0
    doi_api_fallback_used = 0
    doi_paywalled_or_blocked = 0
    seen_lineages: set[str] = set()
    for reference in _iter_candidate_references(
        references=references,
        corpus_id=corpus_id,
        curation_status=curation_status,
        reference_ids=selected_reference_ids,
        external_item_ids=selected_external_item_ids,
    ):
        lineage_id = str(reference.get("lineageId") or "")
        if not lineage_id or lineage_id in seen_lineages:
            continue
        seen_lineages.add(lineage_id)
        source_uri = normalize_http_url(reference.get("sourceUri"))
        if not source_uri:
            source_uri = _reference_find_seed_uri(reference) if allow_discovery else None
        if not source_uri:
            skipped_missing_source += 1
            continue
        existing_canonical = select_extracted_text_attachment(reference, attachments)
        existing_raw = select_extracted_text_raw_attachment(reference, attachments)
        try:
            enrichment: dict[str, Any] = {}
            extraction_source_uri = ""
            if allow_discovery:
                enrichment = resolve_source_site_enrichment(
                    reference=reference,
                    source_uri=source_uri,
                )
                doi_metrics = _doi_resolution_metrics(enrichment)
                doi_resolved += doi_metrics.get("doiResolved", 0)
                doi_pdf_selected += doi_metrics.get("doiPdfSelected", 0)
                doi_pdf_missed += doi_metrics.get("doiPdfMissed", 0)
                doi_search_used += doi_metrics.get("doiSearchUsed", 0)
                doi_search_hit += doi_metrics.get("doiSearchHit", 0)
                doi_api_fallback_used += doi_metrics.get("doiApiFallbackUsed", 0)
                doi_paywalled_or_blocked += doi_metrics.get("doiPaywalledOrBlocked", 0)
                extraction_source_uri = normalize_http_url(enrichment.get("canonicalSourceUri")) or source_uri
            else:
                extraction_source_uri, needs_find_reason = _resolve_process_source_uri(reference, attachments)
                if not extraction_source_uri:
                    skipped_needs_find += 1
                    items.append(
                        {
                            "reference": _reference_row(reference),
                            "status": "needs_find",
                            "error": needs_find_reason
                            or {
                                "code": "needs_find",
                                "message": "Reference must complete find stage before processing.",
                            },
                        }
                    )
                    continue
            if pdf_only and not _looks_like_pdf_uri(extraction_source_uri):
                skipped_non_pdf += 1
                continue
            eligible += 1
            if existing_canonical and not force:
                skipped_existing += 1
                continue
            if find_only:
                if allow_discovery:
                    reference_record = _reference_metadata_update_record(
                        reference=reference,
                        enrichment=enrichment,
                        source_uri=source_uri,
                        canonical_uri=extraction_source_uri,
                        publication_date_resolution={
                            "resolvedSourcePublishedAt": reference.get("sourcePublishedAt"),
                            "strategy": "find-stage",
                            "source": "reference.sourcePublishedAt",
                        },
                    )
                    if reference_record is not None:
                        reference_records.append(reference_record)
                    if _looks_like_pdf_uri(extraction_source_uri):
                        corpus_key = (
                            corpus_key_by_id.get(str(reference.get("corpusId") or ""))
                            or _corpus_key_from_reference(reference)
                        )
                        existing_source = select_reference_attachment_by_role(reference, attachments, role="source")
                        source_attachment = _reference_source_attachment_record(
                            reference=reference,
                            corpus_key=corpus_key,
                            source_uri=extraction_source_uri,
                            metadata={
                                "source": "reference-find-stage",
                                "sourcePlugin": enrichment.get("pluginKey"),
                                "doiResolution": _doi_resolution_for_metadata(enrichment),
                                "downloadedAt": _utc_now(),
                            },
                            content=_download_source_attachment_from_uri(
                                extraction_source_uri,
                                reference=reference,
                            ),
                            media_type="application/pdf",
                            existing_attachment=existing_source,
                        )
                        plans.append(
                            {
                                "reference": reference,
                                "record": {"modelName": "ReferenceAttachment", "expected": source_attachment},
                                "body": source_attachment.pop("__attachmentBody"),
                            }
                        )
                planned_references += 1
                items.append(
                    {
                        "reference": _reference_row(reference),
                        "status": "found",
                        "sourcePlugin": enrichment.get("pluginKey") if allow_discovery else "none",
                        "sourceUri": extraction_source_uri,
                    }
                )
                if max_count and planned_references >= max_count:
                    break
                continue
            extracted = _extract_url_text(
                extraction_source_uri,
                reference_title=str(reference.get("title") or ""),
                grobid_url=grobid_url,
            )
            structured = extracted.get("structured") if isinstance(extracted.get("structured"), dict) else None
            is_pdf_source = _should_passthrough_pdf_content(
                source_uri=extraction_source_uri,
                extracted=extracted,
            )
            publication_date_resolution = _resolve_pdf_publication_date_resolution(
                reference=reference,
                extracted=extracted,
                structured=structured,
                is_pdf_source=is_pdf_source,
            )
            if is_pdf_source and structured is None:
                raise ReferenceUrlTextExtractionError(
                    reason={
                        "code": "grobid_structured_unavailable",
                        "message": "GROBID PDF extraction did not return structured authors/citations payload.",
                        "details": {"sourceUri": extraction_source_uri},
                    }
                )
            if allow_discovery:
                reference_record = _reference_metadata_update_record(
                    reference=reference,
                    enrichment=enrichment,
                    source_uri=source_uri,
                    canonical_uri=extraction_source_uri,
                    publication_date_resolution=publication_date_resolution,
                )
                if reference_record is not None:
                    reference_records.append(reference_record)
            raw_text = str(extracted.get("text") or "").strip()
            raw_markdown = str(extracted.get("markdown") or raw_text)
            if not raw_text:
                raise ValueError("Biblicus URL text extraction returned empty text.")
            corpus_key = (
                corpus_key_by_id.get(str(reference.get("corpusId") or ""))
                or _corpus_key_from_reference(reference)
            )

            if allow_discovery:
                existing_source = select_reference_attachment_by_role(reference, attachments, role="source")
                if is_pdf_source:
                    source_attachment = _reference_source_attachment_record(
                        reference=reference,
                        corpus_key=corpus_key,
                        source_uri=extraction_source_uri,
                        metadata={
                            "source": "biblicus-url-text",
                            "sourcePlugin": enrichment.get("pluginKey"),
                            "doiResolution": _doi_resolution_for_metadata(enrichment),
                            "downloadedAt": _utc_now(),
                        },
                        content=_download_source_attachment_from_uri(
                            extraction_source_uri,
                            reference=reference,
                        ),
                        media_type=str(extracted.get("contentType") or "application/pdf"),
                        existing_attachment=existing_source,
                    )
                    plans.append(
                        {
                            "reference": reference,
                            "record": {"modelName": "ReferenceAttachment", "expected": source_attachment},
                            "body": source_attachment.pop("__attachmentBody"),
                        }
                    )

            if is_pdf_source:
                filter_result = {
                    "status": "ok",
                    "text": raw_text,
                    "spanCount": 1,
                    "promptVersion": "pdf-pass-through-v1",
                    "model": "passthrough",
                    "warnings": ["PDF source detected; skipped article-style filtering and kept full extracted text."],
                    "retryTrace": [],
                    "retryFailureCount": 0,
                    "retryRoundsUsed": 0,
                    "retryLastCode": None,
                    "agenticLoop": {
                        "version": "pdf-pass-through-v1",
                        "rounds_used": 0,
                        "actions": [],
                    },
                    "error": None,
                }
            else:
                filter_result = _filter_article_text(
                    extracted_text=raw_text,
                    source_uri=extraction_source_uri,
                    reference_title=str(reference.get("title") or ""),
                    original_title=str(reference.get("title") or ""),
                    original_subtitle=_original_subtitle(reference),
                    model=model,
                )
            canonical_text = str(filter_result.get("text") or "").strip() or raw_text

            raw_metadata = {
                "source": "biblicus-url-text",
                "extractorId": "biblicus.extract.url-text",
                "sourceUri": extraction_source_uri,
                "sourceUriOriginal": source_uri if allow_discovery else None,
                "extractedAt": _utc_now(),
                "externalItemId": str(reference.get("externalItemId") or reference.get("id") or "") or None,
                "title": extracted.get("title"),
                "textLength": len(raw_text),
                "sourceKind": extracted.get("sourceKind"),
                "strategy": extracted.get("strategy"),
                "contentType": extracted.get("contentType"),
                "promptVersion": extracted.get("promptVersion"),
                "attempts": extracted.get("attempts"),
                "method": extracted.get("method"),
                "grobid": extracted.get("grobid"),
                "structured": _structured_summary_for_metadata(structured),
                "publicationDateResolution": publication_date_resolution,
            }
            if allow_discovery:
                raw_metadata.update(_enrichment_attachment_metadata(enrichment))
            raw_expected = _reference_attachment_record(
                reference=reference,
                role="extracted_text_raw",
                corpus_key=corpus_key,
                storage_namespace="raw",
                markdown=raw_markdown,
                source_uri=None,
                metadata=raw_metadata,
                existing_attachment=existing_raw,
            )
            plans.append(
                {
                    "reference": reference,
                    "record": {"modelName": "ReferenceAttachment", "expected": raw_expected},
                    "body": raw_expected.pop("__attachmentBody"),
                }
            )

            canonical_status = "filtered" if filter_result.get("status") == "ok" else "fallback_raw"
            if canonical_status == "filtered":
                filtered_count += 1
            else:
                fallback_raw_count += 1
                filter_fallback = {
                    "referenceId": reference.get("id"),
                    "externalItemId": reference.get("externalItemId"),
                    "sourceUri": extraction_source_uri,
                    "reason": filter_result.get("error")
                    or {"code": "article_filter_failed", "message": "Article-text filter failed."},
                }
                filter_fallbacks.append(filter_fallback)

            canonical_metadata = {
                "source": "biblicus-article-text-filter",
                "extractorId": "biblicus.extract.article-text",
                "sourceUri": extraction_source_uri,
                "sourceUriOriginal": source_uri if allow_discovery else None,
                "filteredAt": _utc_now(),
                "filterStatus": canonical_status,
                "filterPromptVersion": filter_result.get("promptVersion"),
                "filterModel": filter_result.get("model") or model,
                "filterSpanCount": filter_result.get("spanCount"),
                "filterWarnings": filter_result.get("warnings"),
                "filterError": filter_result.get("error"),
                "filterRetryFailureCount": int(filter_result.get("retryFailureCount") or 0),
                "filterRetryRoundsUsed": int(filter_result.get("retryRoundsUsed") or 0),
                "filterRetryLastCode": filter_result.get("retryLastCode"),
                "filterAgenticLoop": filter_result.get("agenticLoop"),
                "urlExtraction": {
                    "sourceKind": extracted.get("sourceKind"),
                    "strategy": extracted.get("strategy"),
                    "contentType": extracted.get("contentType"),
                    "promptVersion": extracted.get("promptVersion"),
                    "method": extracted.get("method"),
                    "grobid": extracted.get("grobid"),
                    "structured": _structured_summary_for_metadata(structured),
                    "publicationDateResolution": publication_date_resolution,
                },
                "textLength": len(canonical_text),
            }
            if allow_discovery:
                canonical_metadata.update(_enrichment_attachment_metadata(enrichment))
            disable_citation_ingestion = (
                str(os.environ.get("PAPYRUS_DISABLE_CITATION_INGESTION") or "").strip().lower()
                in {"1", "true", "yes", "on"}
            )
            if disable_citation_ingestion:
                graph_plan = {
                    "records": [],
                    "referenceRecords": [],
                    "authorsParsed": 0,
                    "authorsLinked": 0,
                    "citationsParsed": 0,
                    "citationsUpserted": 0,
                    "citationsSkippedLowConfidence": 0,
                    "citationRelationsCreated": 0,
                    "warnings": [
                        {
                            "code": "citation_ingestion_disabled",
                            "message": "Skipped citation graph ingestion for this extraction run.",
                        }
                    ],
                }
            else:
                graph_plan = _plan_grobid_citation_graph_records(
                    source_reference=reference,
                    all_references=references,
                    semantic_relations=semantic_relations,
                    structured=structured,
                    now=canonical_metadata["filteredAt"],
                )
            graph_plan_warnings = (
                [entry for entry in (graph_plan.get("warnings") or []) if isinstance(entry, dict)]
                if isinstance(graph_plan.get("warnings"), list)
                else []
            )
            graph_records.extend(graph_plan["records"])
            reference_records = _merge_planned_reference_records(
                reference_records,
                graph_plan.get("referenceRecords") or [],
            )
            authors_parsed += int(graph_plan.get("authorsParsed", 0))
            authors_linked += int(graph_plan.get("authorsLinked", 0))
            citations_parsed += int(graph_plan.get("citationsParsed", 0))
            citations_upserted += int(graph_plan.get("citationsUpserted", 0))
            citations_skipped_low_confidence += int(graph_plan.get("citationsSkippedLowConfidence", 0))
            citation_relations_created += int(graph_plan.get("citationRelationsCreated", 0))
            citation_graph_warnings.extend(graph_plan_warnings)

            if graph_plan_warnings:
                existing_filter_warnings = canonical_metadata.get("filterWarnings")
                warning_rows = (
                    list(existing_filter_warnings)
                    if isinstance(existing_filter_warnings, list)
                    else []
                )
                warning_rows.extend(
                    [
                        f"citation_graph:{str(row.get('code') or 'warning')}:{str(row.get('message') or '')}"
                        for row in graph_plan_warnings[-20:]
                    ]
                )
                canonical_metadata["filterWarnings"] = warning_rows[-40:]
            canonical_metadata["citationGraph"] = {
                "authorsParsed": int(graph_plan.get("authorsParsed", 0)),
                "authorsLinked": int(graph_plan.get("authorsLinked", 0)),
                "citationsParsed": int(graph_plan.get("citationsParsed", 0)),
                "citationsUpserted": int(graph_plan.get("citationsUpserted", 0)),
                "citationsSkippedLowConfidence": int(graph_plan.get("citationsSkippedLowConfidence", 0)),
                "citationRelationsCreated": int(graph_plan.get("citationRelationsCreated", 0)),
                "warnings": graph_plan.get("warnings") if isinstance(graph_plan.get("warnings"), list) else [],
            }
            canonical_expected = _reference_attachment_record(
                reference=reference,
                role="extracted_text",
                corpus_key=corpus_key,
                storage_namespace="text",
                markdown=canonical_text,
                source_uri=None,
                metadata=canonical_metadata,
                existing_attachment=existing_canonical,
            )
            plans.append(
                {
                    "reference": reference,
                    "record": {"modelName": "ReferenceAttachment", "expected": canonical_expected},
                    "body": canonical_expected.pop("__attachmentBody"),
                }
            )
            planned_references += 1
            items.append(
                {
                    "reference": _reference_row(reference),
                    "status": canonical_status,
                    "sourcePlugin": enrichment.get("pluginKey") if allow_discovery else "find_stage",
                    "filter": {
                        "status": filter_result.get("status"),
                        "spanCount": filter_result.get("spanCount"),
                        "error": filter_result.get("error"),
                    },
                    "urlExtraction": {
                        "sourceKind": extracted.get("sourceKind"),
                        "strategy": extracted.get("strategy"),
                    },
                    "citationGraph": {
                        "authorsParsed": int(graph_plan.get("authorsParsed", 0)),
                        "authorsLinked": int(graph_plan.get("authorsLinked", 0)),
                        "citationsParsed": int(graph_plan.get("citationsParsed", 0)),
                        "citationsUpserted": int(graph_plan.get("citationsUpserted", 0)),
                        "citationsSkippedLowConfidence": int(graph_plan.get("citationsSkippedLowConfidence", 0)),
                        "citationRelationsCreated": int(graph_plan.get("citationRelationsCreated", 0)),
                    },
                }
            )
        except Exception as error:
            reason = _reference_url_text_failure_reason(error)
            if _is_grobid_failure_reason(reason):
                failed_grobid += 1
            failures.append(
                {
                    "referenceId": reference.get("id"),
                    "externalItemId": reference.get("externalItemId"),
                    "sourceUri": extraction_source_uri or source_uri,
                    "reason": reason,
                    "error": json.dumps(reason, sort_keys=True),
                }
            )
            items.append(
                {
                    "reference": _reference_row(reference),
                    "status": "failed",
                    "error": reason,
                }
            )
        if max_count and planned_references >= max_count:
            break
    return {
        "plans": plans,
        "referenceRecords": reference_records,
        "graphRecords": graph_records,
        "failures": failures,
        "items": items,
        "filterFallbacks": filter_fallbacks,
        "eligibleCount": eligible,
        "plannedCount": planned_references,
        "plannedAttachmentCount": len(plans),
        "plannedReferenceMetadataCount": len(reference_records),
        "filteredCount": filtered_count,
        "fallbackRawCount": fallback_raw_count,
        "skippedExistingCount": skipped_existing,
        "skippedMissingSourceCount": skipped_missing_source,
        "skippedNeedsFindCount": skipped_needs_find,
        "skippedNonPdfCount": skipped_non_pdf,
        "failedGrobidCount": failed_grobid,
        "authorsParsedCount": authors_parsed,
        "authorsLinkedCount": authors_linked,
        "citationsParsedCount": citations_parsed,
        "citationsUpsertedCount": citations_upserted,
        "citationsSkippedLowConfidenceCount": citations_skipped_low_confidence,
        "citationRelationsCreatedCount": citation_relations_created,
        "citationGraphWarnings": citation_graph_warnings,
        "doiResolvedCount": doi_resolved,
        "doiPdfSelectedCount": doi_pdf_selected,
        "doiPdfMissedCount": doi_pdf_missed,
        "doiSearchUsedCount": doi_search_used,
        "doiSearchHitCount": doi_search_hit,
        "doiApiFallbackUsedCount": doi_api_fallback_used,
        "doiPaywalledOrBlockedCount": doi_paywalled_or_blocked,
    }


def run_reference_url_text_extraction(
    *,
    client: Any,
    references: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    semantic_relations: list[dict[str, Any]] | None = None,
    corpus_key_by_id: dict[str, str] | None = None,
    corpus_id: str | None = None,
    reference_ids: set[str] | None = None,
    external_item_ids: set[str] | None = None,
    curation_status: str = "all",
    max_count: int | None = None,
    force: bool = False,
    apply: bool = False,
    bucket: str | None = None,
    model: str = DEFAULT_REFERENCE_FILTER_MODEL,
    pdf_only: bool = False,
    grobid_url: str | None = None,
) -> dict[str, Any]:
    from .records import build_record_changes, build_record_changes_targeted_by_id

    planned = build_reference_url_text_attachment_plans(
        references=references,
        attachments=attachments,
        semantic_relations=semantic_relations,
        corpus_key_by_id=corpus_key_by_id,
        corpus_id=corpus_id,
        reference_ids=reference_ids,
        external_item_ids=external_item_ids,
        curation_status=curation_status,
        max_count=max_count,
        force=force,
        model=model,
        pdf_only=pdf_only,
        grobid_url=grobid_url,
    )
    attachment_records = [plan["record"] for plan in planned["plans"]]
    graph_records = planned.get("graphRecords") or []
    attachment_changes = build_record_changes(client, attachment_records)
    graph_changes = build_record_changes(client, graph_records)
    reference_changes = build_record_changes_targeted_by_id(client, planned.get("referenceRecords") or [])
    changes = [*reference_changes, *graph_changes, *attachment_changes]
    summary = {
        "plans": planned["plans"],
        "referenceRecords": planned.get("referenceRecords") or [],
        "graphRecords": graph_records,
        "failures": planned["failures"],
        "items": planned["items"],
        "filterFallbacks": planned["filterFallbacks"],
        "eligibleCount": planned["eligibleCount"],
        "plannedCount": planned["plannedCount"],
        "plannedAttachmentCount": planned["plannedAttachmentCount"],
        "plannedReferenceMetadataCount": planned.get("plannedReferenceMetadataCount", 0),
        "filteredCount": planned["filteredCount"],
        "fallbackRawCount": planned["fallbackRawCount"],
        "skippedExistingCount": planned["skippedExistingCount"],
        "skippedMissingSourceCount": planned.get("skippedMissingSourceCount", 0),
        "skippedNeedsFindCount": planned.get("skippedNeedsFindCount", 0),
        "skippedNonPdfCount": planned.get("skippedNonPdfCount", 0),
        "failedGrobidCount": planned.get("failedGrobidCount", 0),
        "authorsParsedCount": planned.get("authorsParsedCount", 0),
        "authorsLinkedCount": planned.get("authorsLinkedCount", 0),
        "citationsParsedCount": planned.get("citationsParsedCount", 0),
        "citationsUpsertedCount": planned.get("citationsUpsertedCount", 0),
        "citationsSkippedLowConfidenceCount": planned.get("citationsSkippedLowConfidenceCount", 0),
        "citationRelationsCreatedCount": planned.get("citationRelationsCreatedCount", 0),
        "citationGraphWarnings": planned.get("citationGraphWarnings") or [],
        "doiResolvedCount": planned.get("doiResolvedCount", 0),
        "doiPdfSelectedCount": planned.get("doiPdfSelectedCount", 0),
        "doiPdfMissedCount": planned.get("doiPdfMissedCount", 0),
        "doiSearchUsedCount": planned.get("doiSearchUsedCount", 0),
        "doiSearchHitCount": planned.get("doiSearchHitCount", 0),
        "doiApiFallbackUsedCount": planned.get("doiApiFallbackUsedCount", 0),
        "doiPaywalledOrBlockedCount": planned.get("doiPaywalledOrBlockedCount", 0),
        "changes": changes,
        "graphChangeCount": len([change for change in graph_changes if change.get("action") != "noop"]),
        "attachmentChangeCount": len([change for change in attachment_changes if change.get("action") != "noop"]),
        "referenceMetadataChangeCount": len([change for change in reference_changes if change.get("action") != "noop"]),
        "changeCount": len([change for change in changes if change.get("action") != "noop"]),
    }
    if apply:
        summary["applySummary"] = apply_reference_url_text_attachment_changes(
            client=client,
            changes=changes,
            plans=planned["plans"],
            bucket=bucket,
        )
    return summary


def run_reference_source_find(
    *,
    client: Any,
    references: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    corpus_key_by_id: dict[str, str] | None = None,
    corpus_id: str | None = None,
    reference_ids: set[str] | None = None,
    external_item_ids: set[str] | None = None,
    curation_status: str = "all",
    max_count: int | None = None,
    force: bool = False,
    apply: bool = False,
    bucket: str | None = None,
    pdf_only: bool = False,
) -> dict[str, Any]:
    from .records import build_record_changes, build_record_changes_targeted_by_id

    planned = build_reference_url_text_attachment_plans(
        references=references,
        attachments=attachments,
        semantic_relations=[],
        corpus_key_by_id=corpus_key_by_id,
        corpus_id=corpus_id,
        reference_ids=reference_ids,
        external_item_ids=external_item_ids,
        curation_status=curation_status,
        max_count=max_count,
        force=force,
        pdf_only=pdf_only,
        allow_discovery=True,
        find_only=True,
    )
    attachment_records = [plan["record"] for plan in planned["plans"]]
    reference_changes = build_record_changes_targeted_by_id(client, planned.get("referenceRecords") or [])
    attachment_changes = build_record_changes(client, attachment_records)
    changes = [*reference_changes, *attachment_changes]
    summary = {
        "plans": planned["plans"],
        "referenceRecords": planned.get("referenceRecords") or [],
        "graphRecords": [],
        "failures": planned["failures"],
        "items": planned["items"],
        "filterFallbacks": [],
        "eligibleCount": planned["eligibleCount"],
        "plannedCount": planned["plannedCount"],
        "plannedAttachmentCount": planned["plannedAttachmentCount"],
        "plannedReferenceMetadataCount": planned.get("plannedReferenceMetadataCount", 0),
        "filteredCount": 0,
        "fallbackRawCount": 0,
        "skippedExistingCount": planned["skippedExistingCount"],
        "skippedMissingSourceCount": planned.get("skippedMissingSourceCount", 0),
        "skippedNeedsFindCount": 0,
        "skippedNonPdfCount": planned.get("skippedNonPdfCount", 0),
        "failedGrobidCount": 0,
        "authorsParsedCount": 0,
        "authorsLinkedCount": 0,
        "citationsParsedCount": 0,
        "citationsUpsertedCount": 0,
        "citationsSkippedLowConfidenceCount": 0,
        "citationRelationsCreatedCount": 0,
        "citationGraphWarnings": [],
        "doiResolvedCount": planned.get("doiResolvedCount", 0),
        "doiPdfSelectedCount": planned.get("doiPdfSelectedCount", 0),
        "doiPdfMissedCount": planned.get("doiPdfMissedCount", 0),
        "doiSearchUsedCount": planned.get("doiSearchUsedCount", 0),
        "doiSearchHitCount": planned.get("doiSearchHitCount", 0),
        "doiApiFallbackUsedCount": planned.get("doiApiFallbackUsedCount", 0),
        "doiPaywalledOrBlockedCount": planned.get("doiPaywalledOrBlockedCount", 0),
        "changes": changes,
        "graphChangeCount": 0,
        "attachmentChangeCount": len([change for change in attachment_changes if change.get("action") != "noop"]),
        "referenceMetadataChangeCount": len([change for change in reference_changes if change.get("action") != "noop"]),
        "changeCount": len([change for change in changes if change.get("action") != "noop"]),
    }
    if apply:
        summary["applySummary"] = apply_reference_url_text_attachment_changes(
            client=client,
            changes=changes,
            plans=planned["plans"],
            bucket=bucket,
        )
    return summary


def build_reference_citation_count_records(
    *,
    references: list[dict[str, Any]],
    semantic_relations: list[dict[str, Any]],
    corpus_id: str | None = None,
    reference_ids: set[str] | None = None,
    external_item_ids: set[str] | None = None,
    curation_status: str = "all",
) -> dict[str, Any]:
    selected_reference_ids = set(reference_ids or [])
    selected_external_item_ids = set(external_item_ids or [])
    inbound_by_lineage: dict[str, int] = {}
    outbound_by_lineage: dict[str, int] = {}
    for relation in semantic_relations:
        if str(relation.get("relationState") or "") != "current":
            continue
        if _relation_predicate_key(relation) != "cites":
            continue
        subject_lineage_id = str(relation.get("subjectLineageId") or "")
        object_lineage_id = str(relation.get("objectLineageId") or "")
        if subject_lineage_id:
            outbound_by_lineage[subject_lineage_id] = outbound_by_lineage.get(subject_lineage_id, 0) + 1
        if object_lineage_id:
            inbound_by_lineage[object_lineage_id] = inbound_by_lineage.get(object_lineage_id, 0) + 1

    records: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    seen_lineages: set[str] = set()
    for reference in _iter_candidate_references(
        references=references,
        corpus_id=corpus_id,
        curation_status=curation_status,
        reference_ids=selected_reference_ids,
        external_item_ids=selected_external_item_ids,
    ):
        lineage_id = str(reference.get("lineageId") or "")
        if not lineage_id or lineage_id in seen_lineages:
            continue
        seen_lineages.add(lineage_id)
        inbound_count = inbound_by_lineage.get(lineage_id, 0)
        outbound_count = outbound_by_lineage.get(lineage_id, 0)
        records.append(
            {
                "modelName": "Reference",
                "expected": {
                    "id": str(reference.get("id") or ""),
                    "inboundCitationCount": inbound_count,
                    "outboundCitationCount": outbound_count,
                    "updatedAt": _utc_now(),
                },
            }
        )
        items.append(
            {
                "reference": _reference_row(reference),
                "inboundCitationCount": inbound_count,
                "outboundCitationCount": outbound_count,
            }
        )
    return {
        "records": records,
        "items": items,
        "referenceCount": len(items),
    }


def run_reference_identifier_dedupe(
    *,
    client: Any,
    references: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    semantic_relations: list[dict[str, Any]],
    corpus_id: str | None = None,
    reference_ids: set[str] | None = None,
    external_item_ids: set[str] | None = None,
    curation_status: str = "all",
    touched_reference_ids: set[str] | None = None,
    force: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    from .records import apply_record_changes, build_record_changes, build_record_changes_targeted_by_id

    planned = build_reference_identifier_dedupe_records(
        references=references,
        attachments=attachments,
        semantic_relations=semantic_relations,
        corpus_id=corpus_id,
        reference_ids=reference_ids,
        external_item_ids=external_item_ids,
        curation_status=curation_status,
        touched_reference_ids=touched_reference_ids,
        force=force,
    )
    reference_records = [
        record
        for record in planned["records"]
        if str(record.get("modelName") or "") == "Reference"
    ]
    relation_records = [
        record
        for record in planned["records"]
        if str(record.get("modelName") or "") != "Reference"
    ]
    reference_changes = build_record_changes_targeted_by_id(client, reference_records)
    relation_changes = build_record_changes(client, relation_records)
    changes = [*reference_changes, *relation_changes]
    changed = [change for change in changes if change.get("action") != "noop"]
    summary = {
        **planned,
        "changes": changes,
        "changeCount": len(changed),
    }
    if apply and changed:
        apply_record_changes(client, changed)
    return summary


def build_reference_identifier_dedupe_records(
    *,
    references: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    semantic_relations: list[dict[str, Any]],
    corpus_id: str | None = None,
    reference_ids: set[str] | None = None,
    external_item_ids: set[str] | None = None,
    curation_status: str = "all",
    touched_reference_ids: set[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    now = _utc_now()
    selected_reference_ids = set(reference_ids or [])
    selected_external_item_ids = set(external_item_ids or [])
    touched_reference_ids = set(touched_reference_ids or [])
    current_references = [
        reference
        for reference in references
        if str(reference.get("versionState") or "") == "current"
        and (not corpus_id or str(reference.get("corpusId") or "") == str(corpus_id))
        and (curation_status == "all" or str(reference.get("curationStatus") or "") == curation_status)
    ]
    by_lineage: dict[str, dict[str, Any]] = {}
    for reference in current_references:
        lineage_id = str(reference.get("lineageId") or "")
        if lineage_id and lineage_id not in by_lineage:
            by_lineage[lineage_id] = reference
    if not by_lineage:
        return _empty_reference_dedupe_result()

    touched_lineages: set[str] = set()
    if touched_reference_ids:
        touched_lineages = {
            str(reference.get("lineageId") or "")
            for reference in current_references
            if str(reference.get("id") or "") in touched_reference_ids
        }

    key_to_lineages: dict[str, set[str]] = {}
    for lineage_id, reference in by_lineage.items():
        if selected_reference_ids and str(reference.get("id") or "") not in selected_reference_ids:
            continue
        if selected_external_item_ids and str(reference.get("externalItemId") or "") not in selected_external_item_ids:
            continue
        for key in _reference_identifier_keys(reference):
            key_to_lineages.setdefault(key, set()).add(lineage_id)

    groups = _identifier_connected_components(key_to_lineages)
    if touched_lineages:
        groups = [group for group in groups if group.intersection(touched_lineages)]

    if not groups:
        return _empty_reference_dedupe_result()

    has_extracted_text = _lineages_with_extracted_text(attachments)
    citation_degree = _reference_citation_degree(semantic_relations)
    references_by_id = {
        str(reference.get("id") or ""): reference
        for reference in current_references
        if str(reference.get("id") or "")
    }
    losers_by_winner_lineage: dict[str, list[dict[str, Any]]] = {}
    winner_by_loser_lineage: dict[str, dict[str, Any]] = {}

    for group in groups:
        members = [by_lineage[lineage_id] for lineage_id in sorted(group) if lineage_id in by_lineage]
        if len(members) < 2:
            continue
        winner = _select_reference_dedupe_winner(
            members=members,
            has_extracted_text=has_extracted_text,
            citation_degree=citation_degree,
        )
        winner_lineage = str(winner.get("lineageId") or "")
        losers = [row for row in members if str(row.get("lineageId") or "") != winner_lineage]
        if not losers:
            continue
        losers_by_winner_lineage[winner_lineage] = losers
        for loser in losers:
            winner_by_loser_lineage[str(loser.get("lineageId") or "")] = winner

    if not winner_by_loser_lineage:
        return _empty_reference_dedupe_result()

    reference_expected_by_id: dict[str, dict[str, Any]] = {}
    losers_blocked = 0
    references_merged = 0
    merged_pairs: list[dict[str, str]] = []
    for loser_lineage, winner in winner_by_loser_lineage.items():
        loser = by_lineage.get(loser_lineage)
        if not isinstance(loser, dict):
            continue
        loser_id = str(loser.get("id") or "")
        winner_id = str(winner.get("id") or "")
        winner_lineage = str(winner.get("lineageId") or "")
        if not loser_id or not winner_id or not winner_lineage:
            continue
        metadata = _reference_metadata_object(loser)
        if not force and str(metadata.get("mergedIntoReferenceId") or "") == winner_id:
            continue
        papyrus = metadata.get("papyrus")
        if not isinstance(papyrus, dict):
            papyrus = {}
        dedupe_payload = {
            "status": "blocked",
            "state": "superseded",
            "mergedIntoReferenceId": winner_id,
            "mergedIntoReferenceLineageId": winner_lineage,
            "mergeReason": "identifier_dedupe",
            "mergedAt": now,
        }
        papyrus["processing"] = dedupe_payload
        metadata["papyrus"] = papyrus
        metadata["mergedIntoReferenceId"] = winner_id
        metadata["mergedIntoReferenceLineageId"] = winner_lineage
        metadata["mergeReason"] = "identifier_dedupe"
        metadata["mergedAt"] = now
        reference_expected_by_id[loser_id] = {
            "id": loser_id,
            "metadata": json.dumps(metadata, sort_keys=True),
            "updatedAt": now,
        }
        references_merged += 1
        losers_blocked += 1
        merged_pairs.append(
            {
                "loserId": loser_id,
                "loserLineageId": loser_lineage,
                "winnerId": winner_id,
                "winnerLineageId": winner_lineage,
            }
        )

    rewired_relation_records, relation_metrics, touched_lineages_from_relations = _plan_cites_relation_rewire(
        semantic_relations=semantic_relations,
        winner_by_loser_lineage=winner_by_loser_lineage,
        references_by_lineage=by_lineage,
        now=now,
    )

    impacted_lineages = set(touched_lineages_from_relations)
    impacted_lineages.update(winner_by_loser_lineage.keys())
    impacted_lineages.update(str(reference.get("lineageId") or "") for reference in winner_by_loser_lineage.values())

    citation_counter_records = _plan_reference_counter_updates_from_relation_records(
        references_by_lineage=by_lineage,
        semantic_relations=semantic_relations,
        relation_records=rewired_relation_records,
        impacted_lineages=impacted_lineages,
        now=now,
    )
    for expected in citation_counter_records:
        record_id = str(expected.get("id") or "")
        if not record_id:
            continue
        current = reference_expected_by_id.get(record_id, {"id": record_id})
        current.update(expected)
        reference_expected_by_id[record_id] = current

    records = [{"modelName": "Reference", "expected": expected} for expected in reference_expected_by_id.values()]
    records.extend(rewired_relation_records)
    return {
        "records": records,
        "items": merged_pairs,
        "duplicateGroupCount": len(losers_by_winner_lineage),
        "referencesMergedCount": references_merged,
        "relationsRewiredCount": relation_metrics["relationsRewiredCount"],
        "losersBlockedCount": losers_blocked,
    }


def _empty_reference_dedupe_result() -> dict[str, Any]:
    return {
        "records": [],
        "items": [],
        "duplicateGroupCount": 0,
        "referencesMergedCount": 0,
        "relationsRewiredCount": 0,
        "losersBlockedCount": 0,
    }


def _reference_identifier_keys(reference: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    external_item_id = str(reference.get("externalItemId") or "").strip()
    external_lower = external_item_id.lower()
    if external_lower.startswith("doi:"):
        keys.add(f"doi:{external_lower.removeprefix('doi:')}")
    elif external_lower.startswith("arxiv:"):
        keys.add(f"arxiv:{external_lower.removeprefix('arxiv:')}")
    elif external_lower.startswith("pmid:"):
        keys.add(f"pmid:{external_lower.removeprefix('pmid:')}")
    elif external_lower.startswith("isbn:"):
        keys.add(f"isbn:{external_lower.removeprefix('isbn:')}")

    metadata = _reference_metadata_object(reference)
    identifiers = metadata.get("identifiers")
    resolved = identifiers.get("resolved") if isinstance(identifiers, dict) else {}
    resolved = resolved if isinstance(resolved, dict) else {}
    doi = _normalize_doi(resolved.get("doi") or metadata.get("doi"))
    arxiv_id = _normalize_arxiv_id(resolved.get("arxiv_id") or metadata.get("arxiv_id"))
    pmid = _normalize_pmid(resolved.get("pmid") or metadata.get("pmid"))
    isbn = _normalize_isbn(resolved.get("isbn") or metadata.get("isbn"))
    if doi:
        keys.add(f"doi:{doi.lower()}")
    if arxiv_id:
        keys.add(f"arxiv:{arxiv_id.lower()}")
    if pmid:
        keys.add(f"pmid:{pmid}")
    if isbn:
        keys.add(f"isbn:{isbn.lower()}")

    for candidate_url in (
        reference.get("sourceUri"),
        resolved.get("canonical_uri"),
        resolved.get("source_uri"),
    ):
        normalized_url = _normalize_canonical_url_key(candidate_url)
        if normalized_url:
            keys.add(f"url:{normalized_url}")
    return keys


def _normalize_pmid(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    digits = re.sub(r"[^0-9]+", "", text)
    return digits


def _normalize_canonical_url_key(value: Any) -> str:
    raw = normalize_http_url(value)
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    host = str(parsed.netloc or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+", "/", str(parsed.path or "/").strip())
    if not path:
        path = "/"
    path = path.rstrip("/")
    if not path:
        path = "/"
    return f"{host}{path}"


def _identifier_connected_components(key_to_lineages: dict[str, set[str]]) -> list[set[str]]:
    adjacency: dict[str, set[str]] = {}
    for members in key_to_lineages.values():
        lineage_ids = sorted(str(lineage_id) for lineage_id in members if str(lineage_id))
        if len(lineage_ids) < 2:
            continue
        for lineage_id in lineage_ids:
            adjacency.setdefault(lineage_id, set()).update(other for other in lineage_ids if other != lineage_id)
    visited: set[str] = set()
    groups: list[set[str]] = []
    for lineage_id in sorted(adjacency):
        if lineage_id in visited:
            continue
        stack = [lineage_id]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            stack.extend(sorted(adjacency.get(current, set()) - visited))
        if len(component) > 1:
            groups.append(component)
    return groups


def _lineages_with_extracted_text(attachments: list[dict[str, Any]]) -> set[str]:
    lineages: set[str] = set()
    for attachment in attachments:
        if str(attachment.get("role") or "") != "extracted_text":
            continue
        lineage_id = str(attachment.get("referenceLineageId") or "")
        if lineage_id:
            lineages.add(lineage_id)
    return lineages


def _reference_citation_degree(semantic_relations: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for relation in semantic_relations:
        if str(relation.get("relationState") or "") != "current":
            continue
        if _relation_predicate_key(relation) != "cites":
            continue
        subject_lineage_id = str(relation.get("subjectLineageId") or "")
        object_lineage_id = str(relation.get("objectLineageId") or "")
        if subject_lineage_id:
            counts[subject_lineage_id] = counts.get(subject_lineage_id, 0) + 1
        if object_lineage_id:
            counts[object_lineage_id] = counts.get(object_lineage_id, 0) + 1
    return counts


def _select_reference_dedupe_winner(
    *,
    members: list[dict[str, Any]],
    has_extracted_text: set[str],
    citation_degree: dict[str, int],
) -> dict[str, Any]:
    def rank(reference: dict[str, Any]) -> tuple[int, int, int, str]:
        lineage_id = str(reference.get("lineageId") or "")
        curation = _reference_curation_rank(reference.get("curationStatus"))
        extracted = 1 if lineage_id in has_extracted_text else 0
        degree = int(citation_degree.get(lineage_id, 0))
        stable = str(reference.get("id") or "")
        return (curation, extracted, degree, stable)

    return sorted(members, key=rank, reverse=True)[0]


def _reference_curation_rank(value: Any) -> int:
    token = str(value or "").strip().lower()
    if token == "accepted":
        return 4
    if token == "pending":
        return 3
    if token == "rejected":
        return 2
    if token == "archived":
        return 1
    return 0


def _plan_cites_relation_rewire(
    *,
    semantic_relations: list[dict[str, Any]],
    winner_by_loser_lineage: dict[str, dict[str, Any]],
    references_by_lineage: dict[str, dict[str, Any]],
    now: str,
) -> tuple[list[dict[str, Any]], dict[str, int], set[str]]:
    rewired_count = 0
    touched_lineages: set[str] = set()
    current_cites = [
        relation
        for relation in semantic_relations
        if str(relation.get("relationState") or "") == "current" and _relation_predicate_key(relation) == "cites"
    ]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for relation in current_cites:
        subject_lineage_id = str(relation.get("subjectLineageId") or "")
        object_lineage_id = str(relation.get("objectLineageId") or "")
        if (
            subject_lineage_id not in winner_by_loser_lineage
            and object_lineage_id not in winner_by_loser_lineage
        ):
            continue
        mapped_subject = str(
            (winner_by_loser_lineage.get(subject_lineage_id) or {}).get("lineageId") or subject_lineage_id
        )
        mapped_object = str(
            (winner_by_loser_lineage.get(object_lineage_id) or {}).get("lineageId") or object_lineage_id
        )
        if not mapped_subject or not mapped_object:
            continue
        touched_lineages.update({subject_lineage_id, object_lineage_id, mapped_subject, mapped_object})
        mapping_changed = mapped_subject != subject_lineage_id or mapped_object != object_lineage_id
        if mapping_changed:
            rewired_count += 1
        grouped.setdefault((mapped_subject, mapped_object), []).append(
            {
                "source": relation,
                "mappingChanged": mapping_changed,
                "subjectLineageId": mapped_subject,
                "objectLineageId": mapped_object,
            }
        )

    records: list[dict[str, Any]] = []
    for (subject_lineage_id, object_lineage_id), rows in grouped.items():
        if subject_lineage_id == object_lineage_id:
            for row in rows:
                relation_id = str((row.get("source") or {}).get("id") or "")
                if relation_id:
                    records.append(
                        {
                            "modelName": "SemanticRelation",
                            "expected": {
                                "id": relation_id,
                                "relationState": "superseded",
                                "updatedAt": now,
                            },
                        }
                    )
            continue
        subject_reference = references_by_lineage.get(subject_lineage_id)
        object_reference = references_by_lineage.get(object_lineage_id)
        if not isinstance(subject_reference, dict) or not isinstance(object_reference, dict):
            continue
        keeper = sorted(rows, key=lambda row: str((row.get("source") or {}).get("id") or ""))[0]
        keeper_source = keeper.get("source") if isinstance(keeper.get("source"), dict) else {}
        keeper_same = (
            str(keeper_source.get("subjectLineageId") or "") == subject_lineage_id
            and str(keeper_source.get("objectLineageId") or "") == object_lineage_id
            and not keeper.get("mappingChanged")
        )
        if not keeper_same:
            records.append(
                {
                    "modelName": "SemanticRelation",
                    "expected": _semantic_relation_record(
                        predicate="cites",
                        subject_kind="reference",
                        subject_id=str(subject_reference.get("id") or ""),
                        subject_lineage_id=subject_lineage_id,
                        subject_version_number=int(subject_reference.get("versionNumber") or 1),
                        object_kind="reference",
                        object_id=str(object_reference.get("id") or ""),
                        object_lineage_id=object_lineage_id,
                        object_version_number=int(object_reference.get("versionNumber") or 1),
                        rank=1,
                        score=1,
                        confidence=float(keeper_source.get("confidence") or 0.75),
                        now=now,
                        metadata={
                            "source": "identifier_dedupe_rewire",
                            "dedupeMergedFromRelationIds": [
                                str((row.get("source") or {}).get("id") or "")
                                for row in rows
                                if str((row.get("source") or {}).get("id") or "")
                            ],
                        },
                    ),
                }
            )
        for row in rows:
            relation_id = str((row.get("source") or {}).get("id") or "")
            if not relation_id:
                continue
            if keeper_same and relation_id == str(keeper_source.get("id") or ""):
                continue
            records.append(
                {
                    "modelName": "SemanticRelation",
                    "expected": {
                        "id": relation_id,
                        "relationState": "superseded",
                        "updatedAt": now,
                    },
                }
            )
    deduped = _dedupe_planned_semantic_relation_records(records)
    return (
        deduped,
        {"relationsRewiredCount": rewired_count},
        {lineage_id for lineage_id in touched_lineages if lineage_id},
    )


def _dedupe_planned_semantic_relation_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("modelName") != "SemanticRelation":
            continue
        expected = record.get("expected")
        if not isinstance(expected, dict):
            continue
        relation_id = str(expected.get("id") or "")
        if not relation_id:
            continue
        merged = dict(by_id.get(relation_id, {}))
        merged.update(expected)
        by_id[relation_id] = merged
    return [{"modelName": "SemanticRelation", "expected": expected} for _, expected in sorted(by_id.items())]


def _plan_reference_counter_updates_from_relation_records(
    *,
    references_by_lineage: dict[str, dict[str, Any]],
    semantic_relations: list[dict[str, Any]],
    relation_records: list[dict[str, Any]],
    impacted_lineages: set[str],
    now: str,
) -> list[dict[str, Any]]:
    existing = {
        str(relation.get("id") or ""): relation
        for relation in semantic_relations
        if _relation_predicate_key(relation) == "cites"
    }
    current = {
        relation_id: relation
        for relation_id, relation in existing.items()
        if str(relation.get("relationState") or "") == "current"
    }
    for record in relation_records:
        expected = record.get("expected") if isinstance(record.get("expected"), dict) else {}
        relation_id = str(expected.get("id") or "")
        if not relation_id:
            continue
        merged = dict(existing.get(relation_id, {}))
        merged.update(expected)
        if str(merged.get("relationState") or "") == "current":
            current[relation_id] = merged
        else:
            current.pop(relation_id, None)
    inbound_by_lineage: dict[str, int] = {}
    outbound_by_lineage: dict[str, int] = {}
    for relation in current.values():
        if str(relation.get("relationState") or "") != "current":
            continue
        subject_lineage_id = str(relation.get("subjectLineageId") or "")
        object_lineage_id = str(relation.get("objectLineageId") or "")
        if subject_lineage_id:
            outbound_by_lineage[subject_lineage_id] = outbound_by_lineage.get(subject_lineage_id, 0) + 1
        if object_lineage_id:
            inbound_by_lineage[object_lineage_id] = inbound_by_lineage.get(object_lineage_id, 0) + 1
    records: list[dict[str, Any]] = []
    for lineage_id in sorted(lineage_id for lineage_id in impacted_lineages if lineage_id):
        reference = references_by_lineage.get(lineage_id)
        if not isinstance(reference, dict):
            continue
        reference_id = str(reference.get("id") or "")
        if not reference_id:
            continue
        records.append(
            {
                "id": reference_id,
                "inboundCitationCount": inbound_by_lineage.get(lineage_id, 0),
                "outboundCitationCount": outbound_by_lineage.get(lineage_id, 0),
                "updatedAt": now,
            }
        )
    return records


def build_reference_extracted_text_filter_attachment_plans(
    *,
    references: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    corpus_id: str | None = None,
    reference_ids: set[str] | None = None,
    external_item_ids: set[str] | None = None,
    curation_status: str = "all",
    max_count: int | None = None,
    force: bool = True,
    model: str = DEFAULT_REFERENCE_FILTER_MODEL,
    bucket: str | None = None,
) -> dict[str, Any]:
    selected_reference_ids = set(reference_ids or [])
    selected_external_item_ids = set(external_item_ids or [])
    plans: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    filter_fallbacks: list[dict[str, Any]] = []
    attempted = 0
    planned_references = 0
    planned_attachments = 0
    filtered_count = 0
    fallback_raw_count = 0
    skipped_missing_source = 0
    seen_lineages: set[str] = set()
    active_bucket = bucket or resolve_storage_bucket_name()
    s3_client = None
    if active_bucket:
        if boto3 is None:
            raise RuntimeError("boto3 is required to read and write reference text attachments.")
        s3_client = boto3.client("s3")

    for reference in _iter_candidate_references(
        references=references,
        corpus_id=corpus_id,
        curation_status=curation_status,
        reference_ids=selected_reference_ids,
        external_item_ids=selected_external_item_ids,
    ):
        lineage_id = str(reference.get("lineageId") or "")
        if not lineage_id or lineage_id in seen_lineages:
            continue
        seen_lineages.add(lineage_id)
        existing_canonical = select_extracted_text_attachment(reference, attachments)
        existing_raw = select_extracted_text_raw_attachment(reference, attachments)
        if existing_canonical and not force:
            items.append(
                {
                    "reference": _reference_row(reference),
                    "status": "skipped_existing",
                }
            )
            continue
        source_uri = normalize_http_url(reference.get("sourceUri")) or ""
        source_attachment = existing_raw
        if source_attachment is None and _canonical_attachment_is_clearly_non_filtered(existing_canonical):
            source_attachment = existing_canonical
        if source_attachment is None and not source_uri:
            skipped_missing_source += 1
            items.append(
                {
                    "reference": _reference_row(reference),
                    "status": "skipped_missing_source",
                    "error": {
                        "code": "missing_source_attachment",
                        "message": "Reference has no extracted_text_raw attachment and no sourceUri for raw text reconstruction.",
                    },
                }
            )
            continue
        attempted += 1
        if max_count and planned_references >= max_count:
            break
        try:
            if not active_bucket or s3_client is None:
                raise RuntimeError("Could not resolve storage bucket for extracted text attachment filtering.")
            source_text = ""
            source_attachment_id = str(source_attachment.get("id") or "") if isinstance(source_attachment, dict) else ""
            if source_attachment is not None:
                source_text = _read_attachment_text_from_s3(
                    s3_client=s3_client,
                    bucket=active_bucket,
                    attachment=source_attachment,
                )
            else:
                extracted = _extract_url_text(
                    source_uri,
                    reference_title=str(reference.get("title") or ""),
                )
                source_text = str(extracted.get("text") or "").strip()
                if not source_text:
                    raise ValueError("Biblicus URL text extraction returned empty text during raw reconstruction.")

            corpus_key = _corpus_key_from_reference(reference)
            raw_metadata = _base_raw_metadata_for_filter(
                existing_raw=existing_raw,
                source_attachment=source_attachment,
                source_uri=source_uri,
                source_text=source_text,
            )
            raw_expected = _reference_attachment_record(
                reference=reference,
                role="extracted_text_raw",
                corpus_key=corpus_key,
                storage_namespace="raw",
                markdown=source_text,
                source_uri=None,
                metadata=raw_metadata,
                existing_attachment=existing_raw,
            )
            plans.append(
                {
                    "reference": reference,
                    "record": {"modelName": "ReferenceAttachment", "expected": raw_expected},
                    "body": raw_expected.pop("__attachmentBody"),
                }
            )
            planned_attachments += 1
            if not source_attachment_id:
                source_attachment_id = str(raw_expected.get("id") or "")

            if _looks_like_pdf_uri(source_uri):
                filter_result = {
                    "status": "ok",
                    "text": source_text,
                    "spanCount": 1,
                    "promptVersion": "pdf-pass-through-v1",
                    "model": "passthrough",
                    "warnings": ["PDF source detected; skipped article-style filtering and kept full extracted text."],
                    "retryTrace": [],
                    "retryFailureCount": 0,
                    "retryRoundsUsed": 0,
                    "retryLastCode": None,
                    "agenticLoop": {
                        "version": "pdf-pass-through-v1",
                        "rounds_used": 0,
                        "actions": [],
                    },
                    "error": None,
                }
            else:
                filter_result = _filter_article_text(
                    extracted_text=source_text,
                    source_uri=source_uri,
                    reference_title=str(reference.get("title") or ""),
                    original_title=str(reference.get("title") or ""),
                    original_subtitle=_original_subtitle(reference),
                    model=model,
                )
            canonical_status = "filtered" if filter_result.get("status") == "ok" else "fallback_raw"
            if canonical_status == "filtered":
                filtered_count += 1
            else:
                fallback_raw_count += 1
                filter_fallbacks.append(
                    {
                        "referenceId": reference.get("id"),
                        "externalItemId": reference.get("externalItemId"),
                        "sourceUri": source_uri,
                        "reason": filter_result.get("error")
                        or {"code": "article_filter_failed", "message": "Article-text filter failed."},
                    }
                )
            canonical_text = str(filter_result.get("text") or "").strip() or source_text

            canonical_metadata = {
                "source": "biblicus-article-text-filter",
                "extractorId": "biblicus.extract.article-text",
                "sourceUri": source_uri or None,
                "filteredAt": _utc_now(),
                "filterStatus": canonical_status,
                "filterPromptVersion": filter_result.get("promptVersion"),
                "filterModel": filter_result.get("model") or model,
                "filterSpanCount": filter_result.get("spanCount"),
                "filterWarnings": filter_result.get("warnings"),
                "filterError": filter_result.get("error"),
                "filterRetryFailureCount": int(filter_result.get("retryFailureCount") or 0),
                "filterRetryRoundsUsed": int(filter_result.get("retryRoundsUsed") or 0),
                "filterRetryLastCode": filter_result.get("retryLastCode"),
                "filterAgenticLoop": filter_result.get("agenticLoop"),
                "sourceAttachmentId": source_attachment_id or None,
                "textLength": len(canonical_text),
            }
            canonical_expected = _reference_attachment_record(
                reference=reference,
                role="extracted_text",
                corpus_key=corpus_key,
                storage_namespace="text",
                markdown=canonical_text,
                source_uri=None,
                metadata=canonical_metadata,
                existing_attachment=existing_canonical,
            )
            plans.append(
                {
                    "reference": reference,
                    "record": {"modelName": "ReferenceAttachment", "expected": canonical_expected},
                    "body": canonical_expected.pop("__attachmentBody"),
                }
            )
            planned_references += 1
            planned_attachments += 1
            items.append(
                {
                    "reference": _reference_row(reference),
                    "status": canonical_status,
                    "filter": {
                        "status": filter_result.get("status"),
                        "spanCount": filter_result.get("spanCount"),
                        "error": filter_result.get("error"),
                    },
                    "sourceAttachmentId": source_attachment_id or None,
                }
            )
        except Exception as error:
            reason = _reference_url_text_failure_reason(error)
            failures.append(
                {
                    "referenceId": reference.get("id"),
                    "externalItemId": reference.get("externalItemId"),
                    "sourceUri": source_uri or reference.get("sourceUri"),
                    "reason": reason,
                    "error": json.dumps(reason, sort_keys=True),
                }
            )
            items.append(
                {
                    "reference": _reference_row(reference),
                    "status": "failed",
                    "error": reason,
                }
            )
    processed_reference_ids = [
        str(entry["reference"].get("id"))
        for entry in items
        if entry.get("status") in {"filtered", "fallback_raw"}
        and isinstance(entry.get("reference"), dict)
        and entry["reference"].get("id")
    ]
    return {
        "plans": plans,
        "items": items,
        "failures": failures,
        "filterFallbacks": filter_fallbacks,
        "attemptedCount": attempted,
        "plannedCount": planned_references,
        "plannedAttachmentCount": planned_attachments,
        "filteredCount": filtered_count,
        "fallbackRawCount": fallback_raw_count,
        "skippedMissingSourceCount": skipped_missing_source,
        "processedReferenceIds": processed_reference_ids,
    }


def run_reference_extracted_text_filtering(
    *,
    client: Any,
    references: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
    corpus_id: str | None = None,
    reference_ids: set[str] | None = None,
    external_item_ids: set[str] | None = None,
    curation_status: str = "all",
    max_count: int | None = None,
    force: bool = True,
    model: str = DEFAULT_REFERENCE_FILTER_MODEL,
    apply: bool = False,
    bucket: str | None = None,
) -> dict[str, Any]:
    from .records import build_record_changes

    planned = build_reference_extracted_text_filter_attachment_plans(
        references=references,
        attachments=attachments,
        corpus_id=corpus_id,
        reference_ids=reference_ids,
        external_item_ids=external_item_ids,
        curation_status=curation_status,
        max_count=max_count,
        force=force,
        model=model,
        bucket=bucket,
    )
    records = [plan["record"] for plan in planned["plans"]]
    changes = build_record_changes(client, records)
    summary = {
        "plans": planned["plans"],
        "items": planned["items"],
        "failures": planned["failures"],
        "filterFallbacks": planned["filterFallbacks"],
        "attemptedCount": planned["attemptedCount"],
        "plannedCount": planned["plannedCount"],
        "plannedAttachmentCount": planned["plannedAttachmentCount"],
        "filteredCount": planned["filteredCount"],
        "fallbackRawCount": planned["fallbackRawCount"],
        "skippedMissingSourceCount": planned["skippedMissingSourceCount"],
        "processedReferenceIds": planned["processedReferenceIds"],
        "changes": changes,
        "changeCount": len([change for change in changes if change.get("action") != "noop"]),
    }
    if apply:
        summary["applySummary"] = apply_reference_url_text_attachment_changes(
            client=client,
            changes=changes,
            plans=planned["plans"],
            bucket=bucket,
        )
    return summary


def apply_reference_url_text_attachment_changes(
    *,
    client: Any,
    changes: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    bucket: str | None = None,
) -> dict[str, Any]:
    from .records import apply_record_changes

    attachment_changes = [
        change
        for change in changes
        if change.get("modelName") == "ReferenceAttachment" and change.get("action") in {"create", "update"}
    ]
    other_changes = [
        change
        for change in changes
        if change.get("modelName") != "ReferenceAttachment" and change.get("action") != "noop"
    ]
    warnings: list[dict[str, Any]] = []
    if attachment_changes:
        upload_plan_bodies_to_s3(
            plans=plans,
            bucket=bucket,
            allowed_attachment_ids={change["expected"]["id"] for change in attachment_changes},
        )
        apply_record_changes(client, attachment_changes)
    for change in other_changes:
        try:
            apply_record_changes(client, [change])
        except Exception as error:
            warnings.append(
                {
                    "code": "non_attachment_change_failed",
                    "modelName": change.get("modelName"),
                    "id": (change.get("expected") or {}).get("id"),
                    "message": str(error),
                }
            )
    return {
        "uploaded": len(attachment_changes),
        "changed": len([change for change in changes if change.get("action") != "noop"]),
        "created": len([change for change in changes if change.get("action") == "create"]),
        "warnings": warnings,
    }


def upload_plan_bodies_to_s3(
    *,
    plans: list[dict[str, Any]],
    bucket: str | None = None,
    allowed_attachment_ids: set[str] | None = None,
) -> None:
    try:
        import boto3
    except ModuleNotFoundError as error:
        raise RuntimeError("boto3 is required to upload extracted reference text attachments.") from error
    target_bucket = bucket or resolve_storage_bucket_name()
    if not target_bucket:
        raise RuntimeError("Could not resolve storage bucket for extracted reference text attachments.")
    allowed_ids = set(allowed_attachment_ids or [])
    s3 = boto3.client("s3")
    for plan in plans:
        expected = (plan.get("record") or {}).get("expected") or {}
        attachment_id = str(expected.get("id") or "")
        if allowed_ids and attachment_id not in allowed_ids:
            continue
        body = plan.get("body")
        if not isinstance(body, (bytes, bytearray)) or not body:
            raise ValueError(f"Missing attachment body for ReferenceAttachment {attachment_id}.")
        storage_path = str(expected.get("storagePath") or "")
        if not storage_path:
            raise ValueError(f"Missing storagePath for ReferenceAttachment {attachment_id}.")
        s3.put_object(
            Bucket=target_bucket,
            Key=storage_path,
            Body=bytes(body),
            ContentType=str(expected.get("mediaType") or "text/markdown"),
        )


def resolve_storage_bucket_name() -> str | None:
    explicit_bucket = (
        os.environ.get("papyrusMedia_BUCKET_NAME")
        or os.environ.get("PAPYRUS_MEDIA_BUCKET_NAME")
        or os.environ.get("STORAGE_BUCKET_NAME")
        or os.environ.get("AMPLIFY_STORAGE_BUCKET_NAME")
    )
    if explicit_bucket:
        return explicit_bucket
    fallback_bucket = storage_bucket_from_amplify_outputs()
    if not fallback_bucket:
        return None
    if _graphql_endpoint_overrides_amplify_outputs():
        explicit_endpoint = str(os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT") or "").strip()
        fallback_endpoint = _graphql_endpoint_from_amplify_outputs() or "unknown"
        raise RuntimeError(
            "PAPYRUS_GRAPHQL_ENDPOINT does not match amplify_outputs.json. "
            f"Refusing to infer storage bucket from amplify_outputs ({fallback_endpoint}) while "
            f"authoring endpoint is {explicit_endpoint}. "
            "Pass --bucket or set PAPYRUS_MEDIA_BUCKET_NAME explicitly."
        )
    return fallback_bucket


def _graphql_endpoint_overrides_amplify_outputs() -> bool:
    explicit = str(os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT") or "").strip()
    if not explicit:
        return False
    fallback = _graphql_endpoint_from_amplify_outputs()
    if not fallback:
        return False
    return _endpoint_authority(explicit) != _endpoint_authority(fallback)


def _graphql_endpoint_from_amplify_outputs() -> str | None:
    try:
        parsed = load_amplify_outputs()
    except Exception:
        return None
    endpoint = parsed.get("data", {}).get("url") or parsed.get("aws_appsync_graphqlEndpoint")
    normalized = str(endpoint or "").strip()
    return normalized or None


def _endpoint_authority(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return url.strip().lower()
    host = (parsed.netloc or "").strip().lower()
    path = (parsed.path or "").strip()
    return f"{host}{path}"


def normalize_http_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    return raw


class ReferenceUrlTextExtractionError(RuntimeError):
    def __init__(self, *, reason: dict[str, Any]):
        self.reason = dict(reason)
        super().__init__(str(self.reason.get("message") or self.reason.get("code") or "URL text extraction failed."))


def _extract_url_text(source_uri: str, *, reference_title: str = "", grobid_url: str | None = None) -> dict[str, Any]:
    payload = {
        "source_uri": source_uri,
        "reference_title": reference_title or "",
    }
    result = _run_biblicus_url_text(payload, grobid_url=grobid_url)
    status = str(result.get("status") or "").strip().lower()
    if status != "ok":
        reason = result.get("error") if isinstance(result.get("error"), dict) else None
        if not reason:
            reason = {
                "code": "biblicus_url_text_failed",
                "message": "Biblicus URL text extraction failed.",
                "details": {"result": result},
            }
        raise ReferenceUrlTextExtractionError(reason=reason)
    text = str(result.get("text") or "").strip()
    if not text:
        raise ReferenceUrlTextExtractionError(
            reason={
                "code": "empty_text",
                "message": "Biblicus URL text extraction produced empty text.",
                "details": {"sourceUri": source_uri},
            }
        )
    return {
        "text": text,
        "markdown": str(result.get("markdown") or text),
        "title": str(result.get("title") or "") or None,
        "sourceKind": str(result.get("source_kind") or "") or None,
        "strategy": str(result.get("strategy") or "") or None,
        "contentType": str(result.get("content_type") or "") or None,
        "promptVersion": str(result.get("prompt_version") or "") or None,
        "method": str(result.get("method") or "") or None,
        "grobid": result.get("grobid") if isinstance(result.get("grobid"), dict) else None,
        "structured": result.get("structured") if isinstance(result.get("structured"), dict) else None,
        "attempts": result.get("attempts") if isinstance(result.get("attempts"), list) else [],
    }


def _filter_article_text(
    *,
    extracted_text: str,
    source_uri: str,
    reference_title: str,
    original_title: str,
    original_subtitle: str,
    model: str,
) -> dict[str, Any]:
    cleaned_text = str(extracted_text or "").replace("\x00", "").strip()
    if not cleaned_text:
        return {
            "status": "failed",
            "text": "",
            "spanCount": 0,
            "promptVersion": None,
            "model": model,
            "warnings": [],
            "retryTrace": [],
            "retryFailureCount": 0,
            "retryRoundsUsed": 0,
            "retryLastCode": None,
            "error": {"code": "empty_extracted_text", "message": "Cannot filter empty extracted text."},
        }
    payload = {
        "extracted_text": cleaned_text,
        "source_uri": source_uri,
        "reference_title": reference_title,
        "original_title": original_title,
        "original_subtitle": original_subtitle,
        "model": model,
    }
    try:
        result = _run_biblicus_article_text(payload)
    except Exception as error:
        return {
            "status": "failed",
            "text": "",
            "spanCount": 0,
            "promptVersion": None,
            "model": model,
            "warnings": [],
            "retryTrace": [],
            "retryFailureCount": 0,
            "retryRoundsUsed": 0,
            "retryLastCode": None,
            "error": {"code": "biblicus_article_text_failed", "message": str(error)},
        }
    retry_trace = _bounded_retry_trace(result.get("retry_trace"), limit=10)
    retry_failure_count = _coerce_non_negative_int(result.get("retry_failure_count"))
    if retry_failure_count is None:
        retry_failure_count = len(retry_trace)
    retry_rounds_used = _coerce_non_negative_int(result.get("retry_rounds_used")) or 0
    retry_last_code = ""
    if retry_trace:
        retry_last_code = str((retry_trace[-1] or {}).get("failure_code") or "").strip()
    agentic_loop = result.get("agentic_loop") if isinstance(result.get("agentic_loop"), dict) else None
    status = str(result.get("status") or "").strip().lower()
    filtered_text = str(result.get("text") or "").strip()
    if status == "ok" and filtered_text:
        return {
            "status": "ok",
            "text": filtered_text,
            "spanCount": int(result.get("span_count") or 0),
            "promptVersion": result.get("prompt_version"),
            "model": result.get("model") or model,
            "warnings": result.get("warnings") if isinstance(result.get("warnings"), list) else [],
            "retryTrace": retry_trace,
            "retryFailureCount": retry_failure_count,
            "retryRoundsUsed": retry_rounds_used,
            "retryLastCode": retry_last_code or None,
            "agenticLoop": agentic_loop,
            "error": None,
        }
    reason = result.get("error") if isinstance(result.get("error"), dict) else None
    if not reason:
        reason = {
            "code": "article_filter_failed",
            "message": "Biblicus article-text filtering failed.",
            "details": {"result": result},
        }
    reason = _attach_retry_trace_to_reason(
        reason=reason,
        retry_trace=retry_trace,
        retry_failure_count=retry_failure_count,
        retry_rounds_used=retry_rounds_used,
    )
    return {
        "status": "failed",
        "text": "",
        "spanCount": int(result.get("span_count") or 0),
        "promptVersion": result.get("prompt_version"),
        "model": result.get("model") or model,
        "warnings": result.get("warnings") if isinstance(result.get("warnings"), list) else [],
        "retryTrace": retry_trace,
        "retryFailureCount": retry_failure_count,
        "retryRoundsUsed": retry_rounds_used,
        "retryLastCode": retry_last_code or None,
        "agenticLoop": agentic_loop,
        "error": reason,
    }


def _run_biblicus_url_text(payload: dict[str, Any], *, grobid_url: str | None = None) -> dict[str, Any]:
    if not BIBLICUS_ROOT.is_dir():
        raise ReferenceUrlTextExtractionError(
            reason={
                "code": "biblicus_checkout_missing",
                "message": f"Biblicus checkout not found at {BIBLICUS_ROOT}.",
            }
        )
    command = [
        str(_biblicus_python_executable()),
        "-m",
        "biblicus",
        "extract",
        "url-text",
        "--input-json",
        "-",
        "--format",
        "json",
    ]
    env = _biblicus_env(grobid_url=grobid_url)
    completed = subprocess.run(
        command,
        cwd=BIBLICUS_ROOT,
        capture_output=True,
        text=True,
        check=False,
        input=json.dumps(payload),
        env=env,
    )
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    parsed_stdout = _json_object_or_none(stdout)
    if completed.returncode != 0 and _is_missing_markitdown_error(parsed_stdout) and shutil.which("uv"):
        uv_command = [
            "uv",
            "run",
            "--extra",
            "markitdown",
            "biblicus",
            "extract",
            "url-text",
            "--input-json",
            "-",
            "--format",
            "json",
        ]
        completed = subprocess.run(
            uv_command,
            cwd=BIBLICUS_ROOT,
            capture_output=True,
            text=True,
            check=False,
            input=json.dumps(payload),
            env=env,
        )
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        parsed_stdout = _json_object_or_none(stdout)
    if completed.returncode != 0:
        reason = (
            parsed_stdout.get("error")
            if isinstance(parsed_stdout, dict) and isinstance(parsed_stdout.get("error"), dict)
            else {
                "code": "biblicus_cli_failed",
                "message": stderr or stdout or f"Biblicus URL text command exited {completed.returncode}.",
            }
        )
        raise ReferenceUrlTextExtractionError(reason=reason)
    if not isinstance(parsed_stdout, dict):
        raise ReferenceUrlTextExtractionError(
            reason={
                "code": "invalid_biblicus_output",
                "message": "Biblicus URL text command returned invalid JSON output.",
                "details": {"stdout": stdout},
            }
        )
    return parsed_stdout


def _run_biblicus_article_text(payload: dict[str, Any]) -> dict[str, Any]:
    if not BIBLICUS_ROOT.is_dir():
        raise RuntimeError(f"Biblicus checkout not found at {BIBLICUS_ROOT}.")
    command = [
        str(_biblicus_python_executable()),
        "-m",
        "biblicus",
        "extract",
        "article-text",
        "--input-json",
        "-",
        "--format",
        "json",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=BIBLICUS_ROOT,
            capture_output=True,
            text=True,
            check=False,
            input=json.dumps(payload),
            env=_biblicus_env(),
            timeout=ARTICLE_TEXT_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Biblicus article-text command timed out after {ARTICLE_TEXT_SUBPROCESS_TIMEOUT_SECONDS} seconds."
        ) from error
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    parsed_stdout = _json_object_or_none(stdout)
    if _is_missing_dspy_error(parsed_stdout) and shutil.which("uv"):
        uv_command = [
            "uv",
            "run",
            "--extra",
            "dspy",
            "--extra",
            "openai",
            "biblicus",
            "extract",
            "article-text",
            "--input-json",
            "-",
            "--format",
            "json",
        ]
        try:
            completed = subprocess.run(
                uv_command,
                cwd=BIBLICUS_ROOT,
                capture_output=True,
                text=True,
                check=False,
                input=json.dumps(payload),
                env=_biblicus_env(),
                timeout=ARTICLE_TEXT_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"Biblicus article-text command timed out after {ARTICLE_TEXT_SUBPROCESS_TIMEOUT_SECONDS} seconds."
            ) from error
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        parsed_stdout = _json_object_or_none(stdout)
    if completed.returncode != 0:
        if isinstance(parsed_stdout, dict) and isinstance(parsed_stdout.get("error"), dict):
            error = parsed_stdout["error"]
            raise RuntimeError(str(error.get("message") or error.get("code") or "Biblicus article-text command failed."))
        raise RuntimeError(stderr or stdout or f"Biblicus article-text command exited {completed.returncode}.")
    if not isinstance(parsed_stdout, dict):
        raise RuntimeError("Biblicus article-text command returned invalid JSON output.")
    return parsed_stdout


def _biblicus_env(*, grobid_url: str | None = None) -> dict[str, str]:
    env = dict(os.environ)
    biblicus_src = str(BIBLICUS_ROOT / "src")
    env["PYTHONPATH"] = (
        f"{biblicus_src}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else biblicus_src
    )
    resolved_grobid = str(grobid_url or env.get("BIBLICUS_GROBID_URL") or "").strip()
    if resolved_grobid:
        env["BIBLICUS_GROBID_URL"] = resolved_grobid
    return env


def _biblicus_python_executable() -> str:
    for candidate in (
        BIBLICUS_ROOT / ".venv" / "bin" / "python",
        BIBLICUS_ROOT / ".venv" / "bin" / "python3",
    ):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def _read_attachment_text_from_s3(*, s3_client: Any, bucket: str, attachment: dict[str, Any]) -> str:
    storage_path = str(attachment.get("storagePath") or "").strip()
    if not storage_path:
        raise ValueError("Attachment is missing storagePath.")
    response = s3_client.get_object(Bucket=bucket, Key=storage_path)
    raw = response["Body"].read()
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError(f"Attachment {attachment.get('id') or '-'} is empty.")
    return text


def _json_object_or_none(raw_text: str) -> dict[str, Any] | None:
    if not raw_text:
        return None
    try:
        parsed = json.loads(raw_text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        stripped = raw_text.strip()
        if not stripped:
            return None
        decoder = json.JSONDecoder()
        for index, character in enumerate(stripped):
            if character != "{":
                continue
            try:
                candidate, end_index = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            if not isinstance(candidate, dict):
                continue
            if stripped[index + end_index :].strip():
                continue
            return candidate
        return None


def _bounded_retry_trace(value: Any, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        rows.append(
            {
                "attempt": int(entry.get("attempt") or 0),
                "max_rounds": int(entry.get("max_rounds") or 0),
                "retries_left": int(entry.get("retries_left") or 0),
                "failure_code": str(entry.get("failure_code") or ""),
                "error_message": str(entry.get("error_message") or ""),
                "next_action": str(entry.get("next_action") or ""),
            }
        )
    if limit <= 0:
        return rows
    return rows[-limit:]


def _attach_retry_trace_to_reason(
    *,
    reason: dict[str, Any],
    retry_trace: list[dict[str, Any]],
    retry_failure_count: int,
    retry_rounds_used: int,
) -> dict[str, Any]:
    payload = dict(reason)
    details = payload.get("details")
    if not isinstance(details, dict):
        details = {}
    details["retry_trace"] = retry_trace
    details["retry_failure_count"] = int(retry_failure_count)
    details["retry_rounds_used"] = int(retry_rounds_used)
    payload["details"] = details
    return payload


def _coerce_non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _is_missing_markitdown_error(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    return isinstance(error, dict) and str(error.get("code") or "") == "missing_markitdown_dependency"


def _looks_like_pdf_uri(value: Any) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return False
    return raw.endswith(".pdf")


def _should_passthrough_pdf_content(*, source_uri: str, extracted: dict[str, Any]) -> bool:
    if _looks_like_pdf_uri(source_uri):
        return True
    content_type = str(extracted.get("contentType") or "").strip().lower()
    if "pdf" in content_type:
        return True
    source_kind = str(extracted.get("sourceKind") or "").strip().lower()
    if source_kind == "pdf":
        return True
    return False


def _is_missing_dspy_error(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    if not isinstance(error, dict):
        return False
    code = str(error.get("code") or "").strip()
    message = str(error.get("message") or "").lower()
    return code in {"missing_dspy_dependency", "article_text_filter_failed"} and "biblicus[dspy]" in message


def _is_grobid_failure_reason(reason: dict[str, Any] | None) -> bool:
    if not isinstance(reason, dict):
        return False
    code = str(reason.get("code") or "").lower()
    if code.startswith("grobid_"):
        return True
    details = reason.get("details")
    if isinstance(details, dict):
        fetch_error = details.get("fetch_error")
        if isinstance(fetch_error, dict) and str(fetch_error.get("code") or "").lower().startswith("grobid_"):
            return True
    return False


def _plan_grobid_citation_graph_records(
    *,
    source_reference: dict[str, Any],
    all_references: list[dict[str, Any]],
    semantic_relations: list[dict[str, Any]] | None,
    structured: dict[str, Any] | None,
    now: str,
) -> dict[str, Any]:
    if not isinstance(structured, dict):
        return {
            "records": [],
            "referenceRecords": [],
            "authorsParsed": 0,
            "authorsLinked": 0,
            "citationsParsed": 0,
            "citationsUpserted": 0,
            "citationsSkippedLowConfidence": 0,
            "citationRelationsCreated": 0,
            "warnings": [],
        }
    corpus_id = str(source_reference.get("corpusId") or "")
    source_reference_id = str(source_reference.get("id") or "")
    source_lineage_id = str(source_reference.get("lineageId") or "")
    source_version_number = int(source_reference.get("versionNumber") or 1)
    if not corpus_id or not source_reference_id or not source_lineage_id:
        return {
            "records": [],
            "referenceRecords": [],
            "authorsParsed": 0,
            "authorsLinked": 0,
            "citationsParsed": 0,
            "citationsUpserted": 0,
            "citationsSkippedLowConfidence": 0,
            "citationRelationsCreated": 0,
            "warnings": [
                {
                    "code": "source_reference_incomplete",
                    "message": "Source reference is missing required identity fields for citation graph ingestion.",
                }
            ],
        }

    records: list[dict[str, Any]] = []
    reference_records: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    authors = _normalize_grobid_authors(structured.get("authors"))
    citations = _normalize_grobid_citations(structured.get("citations"))
    existing_lookup = _build_existing_reference_lookup(all_references=all_references, corpus_id=corpus_id)

    authors_linked = 0
    for index, author in enumerate(authors):
        author_node = _author_semantic_node_record(author=author, now=now)
        records.append({"modelName": "SemanticNode", "expected": author_node})
        records.append(
            {
                "modelName": "SemanticRelation",
                "expected": _semantic_relation_record(
                    predicate="authored_by",
                    subject_kind="reference",
                    subject_id=source_reference_id,
                    subject_lineage_id=source_lineage_id,
                    subject_version_number=source_version_number,
                    object_kind="semanticNode",
                    object_id=author_node["id"],
                    object_lineage_id=author_node["lineageId"],
                    object_version_number=int(author_node.get("versionNumber") or 1),
                    rank=index + 1,
                    score=1,
                    confidence=1.0,
                    now=now,
                    metadata={
                        "source": "grobid",
                        "authorName": author["name"],
                        "authorOrcid": author.get("orcid"),
                    },
                ),
            }
        )
        authors_linked += 1

    citations_upserted = 0
    citations_skipped_low_confidence = 0
    citation_relations_created = 0
    planned_current_citation_relation_ids: set[str] = set()
    for index, citation in enumerate(citations):
        confidence = _citation_confidence(citation)
        if not confidence["accepted"]:
            citations_skipped_low_confidence += 1
            warnings.append(
                {
                    "code": "citation_low_confidence",
                    "message": f"Skipped citation {index + 1}: {confidence['reason']}",
                    "citation": _bounded_citation_warning_payload(citation),
                }
            )
            continue

        cited_reference = _resolve_or_build_cited_reference_record(
            citation=citation,
            corpus_id=corpus_id,
            existing_lookup=existing_lookup,
            now=now,
        )
        if cited_reference.get("isNew"):
            records.append({"modelName": "Reference", "expected": cited_reference["record"]})
            citations_upserted += 1

        records.append(
            {
                "modelName": "SemanticRelation",
                "expected": _semantic_relation_record(
                    predicate="cites",
                    subject_kind="reference",
                    subject_id=source_reference_id,
                    subject_lineage_id=source_lineage_id,
                    subject_version_number=source_version_number,
                    object_kind="reference",
                    object_id=cited_reference["record"]["id"],
                    object_lineage_id=cited_reference["record"]["lineageId"],
                    object_version_number=int(cited_reference["record"].get("versionNumber") or 1),
                    rank=index + 1,
                    score=1,
                    confidence=confidence["score"],
                    now=now,
                    metadata={
                        "source": "grobid",
                        "confidence": confidence["score"],
                        "reason": confidence["reason"],
                        "citationTitle": citation.get("title"),
                        "citationYear": citation.get("year"),
                        "citationDoi": citation.get("doi"),
                        "citationArxivId": citation.get("arxiv_id"),
                        "citationIsbn": citation.get("isbn"),
                    },
                ),
            }
        )
        planned_current_citation_relation_ids.add(
            _semantic_relation_record(
                predicate="cites",
                subject_kind="reference",
                subject_id=source_reference_id,
                subject_lineage_id=source_lineage_id,
                subject_version_number=source_version_number,
                object_kind="reference",
                object_id=cited_reference["record"]["id"],
                object_lineage_id=cited_reference["record"]["lineageId"],
                object_version_number=int(cited_reference["record"].get("versionNumber") or 1),
                rank=index + 1,
                score=1,
                confidence=confidence["score"],
                now=now,
                metadata={},
            )["id"]
        )
        citation_relations_created += 1

    for relation in _current_cites_relations_for_subject(semantic_relations or [], source_lineage_id):
        relation_id = str(relation.get("id") or "")
        if not relation_id or relation_id in planned_current_citation_relation_ids:
            continue
        records.append(
            {
                "modelName": "SemanticRelation",
                "expected": {
                    "id": relation_id,
                    "relationState": "superseded",
                    "updatedAt": now,
                },
            }
        )

    citation_counter_plan = _plan_reference_citation_counter_updates(
        source_reference=source_reference,
        all_references=all_references,
        semantic_relations=semantic_relations or [],
        planned_records=records,
        now=now,
    )
    reference_records.extend(citation_counter_plan["referenceRecords"])
    _apply_citation_counts_to_planned_reference_records(
        records=records,
        reference_counts_by_id=citation_counter_plan["newReferenceCountsById"],
    )

    if authors or citations or warnings:
        payload = {
            "sourceReferenceId": source_reference_id,
            "sourceReferenceLineageId": source_lineage_id,
            "source": "grobid",
            "authors": authors,
            "citations": citations,
            "warnings": warnings,
            "summary": {
                "authorsParsed": len(authors),
                "authorsLinked": authors_linked,
                "citationsParsed": len(citations),
                "citationsUpserted": citations_upserted,
                "citationsSkippedLowConfidence": citations_skipped_low_confidence,
                "citationRelationsCreated": citation_relations_created,
            },
        }
        records.append(
            {
                "modelName": "KnowledgeRawPayload",
                "expected": {
                    "id": f"knowledge-raw-payload-{safe_id(source_reference_id)}-grobid-citation-graph",
                    "ownerType": "reference",
                    "ownerId": source_reference_id,
                    "payloadKind": "grobid-citation-graph",
                    "importRunId": None,
                    "payload": json.dumps(payload, sort_keys=True),
                    "createdAt": now,
                    "updatedAt": now,
                },
            }
        )

    return {
        "records": records,
        "referenceRecords": reference_records,
        "authorsParsed": len(authors),
        "authorsLinked": authors_linked,
        "citationsParsed": len(citations),
        "citationsUpserted": citations_upserted,
        "citationsSkippedLowConfidence": citations_skipped_low_confidence,
        "citationRelationsCreated": citation_relations_created,
        "warnings": warnings,
    }


def _merge_planned_reference_records(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in [*existing, *incoming]:
        if record.get("modelName") != "Reference":
            continue
        expected = record.get("expected") if isinstance(record.get("expected"), dict) else {}
        record_id = str(expected.get("id") or "")
        if not record_id:
            continue
        if record_id not in merged:
            order.append(record_id)
            merged[record_id] = {"modelName": "Reference", "expected": dict(expected)}
            continue
        merged[record_id]["expected"].update(expected)
    return [merged[record_id] for record_id in order]


def _current_cites_relations_for_subject(
    semantic_relations: list[dict[str, Any]],
    subject_lineage_id: str,
) -> list[dict[str, Any]]:
    return [
        relation
        for relation in semantic_relations
        if str(relation.get("relationState") or "") == "current"
        and str(relation.get("subjectLineageId") or "") == subject_lineage_id
        and _relation_predicate_key(relation) == "cites"
    ]


def _relation_predicate_key(relation: dict[str, Any]) -> str:
    return str(relation.get("relationTypeKey") or relation.get("predicate") or "").strip()


def _plan_reference_citation_counter_updates(
    *,
    source_reference: dict[str, Any],
    all_references: list[dict[str, Any]],
    semantic_relations: list[dict[str, Any]],
    planned_records: list[dict[str, Any]],
    now: str,
) -> dict[str, Any]:
    source_lineage_id = str(source_reference.get("lineageId") or "")
    existing_relations_by_id = {
        str(relation.get("id") or ""): relation
        for relation in semantic_relations
        if _relation_predicate_key(relation) == "cites"
    }
    final_current_relations_by_id = {
        relation_id: relation
        for relation_id, relation in existing_relations_by_id.items()
        if str(relation.get("relationState") or "") == "current"
    }
    impacted_lineage_ids: set[str] = {source_lineage_id} if source_lineage_id else set()

    for relation in existing_relations_by_id.values():
        if str(relation.get("subjectLineageId") or "") != source_lineage_id:
            continue
        object_lineage_id = str(relation.get("objectLineageId") or "")
        if object_lineage_id:
            impacted_lineage_ids.add(object_lineage_id)

    for record in planned_records:
        if record.get("modelName") != "SemanticRelation":
            continue
        expected = record.get("expected") if isinstance(record.get("expected"), dict) else {}
        relation_id = str(expected.get("id") or "")
        relation_key = _relation_predicate_key(expected) or _relation_predicate_key(existing_relations_by_id.get(relation_id, {}))
        if relation_key != "cites" or not relation_id:
            continue
        current_relation = existing_relations_by_id.get(relation_id, {})
        merged_relation = {**current_relation, **expected}
        if str(merged_relation.get("relationState") or "") == "current":
            final_current_relations_by_id[relation_id] = merged_relation
        else:
            final_current_relations_by_id.pop(relation_id, None)
        if str(merged_relation.get("subjectLineageId") or current_relation.get("subjectLineageId") or "") == source_lineage_id:
            object_lineage_id = str(merged_relation.get("objectLineageId") or current_relation.get("objectLineageId") or "")
            if object_lineage_id:
                impacted_lineage_ids.add(object_lineage_id)

    inbound_by_lineage: dict[str, int] = {}
    outbound_by_lineage: dict[str, int] = {}
    for relation in final_current_relations_by_id.values():
        if str(relation.get("relationState") or "") != "current":
            continue
        subject_lineage_id = str(relation.get("subjectLineageId") or "")
        object_lineage_id = str(relation.get("objectLineageId") or "")
        if subject_lineage_id:
            outbound_by_lineage[subject_lineage_id] = outbound_by_lineage.get(subject_lineage_id, 0) + 1
        if object_lineage_id:
            inbound_by_lineage[object_lineage_id] = inbound_by_lineage.get(object_lineage_id, 0) + 1

    existing_references_by_lineage = {
        str(reference.get("lineageId") or ""): reference
        for reference in all_references
        if str(reference.get("lineageId") or "")
    }
    new_reference_counts_by_id: dict[str, dict[str, int]] = {}
    reference_records: list[dict[str, Any]] = []

    for record in planned_records:
        if record.get("modelName") != "Reference":
            continue
        expected = record.get("expected") if isinstance(record.get("expected"), dict) else {}
        lineage_id = str(expected.get("lineageId") or "")
        record_id = str(expected.get("id") or "")
        if not lineage_id or not record_id:
            continue
        existing_references_by_lineage.setdefault(lineage_id, expected)

    for lineage_id in sorted(lineage_id for lineage_id in impacted_lineage_ids if lineage_id):
        inbound_count = inbound_by_lineage.get(lineage_id, 0)
        outbound_count = outbound_by_lineage.get(lineage_id, 0)
        reference = existing_references_by_lineage.get(lineage_id)
        if not isinstance(reference, dict):
            continue
        record_id = str(reference.get("id") or "")
        if not record_id:
            continue
        is_new_reference = any(
            record.get("modelName") == "Reference"
            and str((record.get("expected") or {}).get("id") or "") == record_id
            for record in planned_records
        )
        if is_new_reference:
            new_reference_counts_by_id[record_id] = {
                "inboundCitationCount": inbound_count,
                "outboundCitationCount": outbound_count,
            }
            continue
        reference_records.append(
            {
                "modelName": "Reference",
                "expected": {
                    "id": record_id,
                    "inboundCitationCount": inbound_count,
                    "outboundCitationCount": outbound_count,
                    "updatedAt": now,
                },
            }
        )

    return {
        "referenceRecords": reference_records,
        "newReferenceCountsById": new_reference_counts_by_id,
    }


def _apply_citation_counts_to_planned_reference_records(
    *,
    records: list[dict[str, Any]],
    reference_counts_by_id: dict[str, dict[str, int]],
) -> None:
    if not reference_counts_by_id:
        return
    for record in records:
        if record.get("modelName") != "Reference":
            continue
        expected = record.get("expected")
        if not isinstance(expected, dict):
            continue
        counts = reference_counts_by_id.get(str(expected.get("id") or ""))
        if not counts:
            continue
        expected.update(counts)


def _normalize_grobid_authors(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        normalized_name = _normalize_author_identity_name(entry.get("normalized_name") or name)
        orcid = _normalize_orcid(entry.get("orcid"))
        identity_key = orcid.lower() if orcid else normalized_name
        if not identity_key or identity_key in seen:
            continue
        seen.add(identity_key)
        rows.append(
            {
                "name": name,
                "normalized_name": normalized_name,
                "orcid": orcid or None,
                "email": str(entry.get("email") or "").strip() or None,
                "affiliation": str(entry.get("affiliation") or "").strip() or None,
            }
        )
    return rows


def _normalize_grobid_citations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        authors = [
            str(name).strip()
            for name in (entry.get("authors") or [])
            if str(name).strip()
        ] if isinstance(entry.get("authors"), list) else []
        year = _coerce_year(entry.get("year"))
        citation = {
            "title": title or None,
            "authors": authors,
            "year": year,
            "venue": str(entry.get("venue") or "").strip() or None,
            "doi": _normalize_doi(entry.get("doi")),
            "arxiv_id": _normalize_arxiv_id(entry.get("arxiv_id") or entry.get("arxivId")),
            "isbn": _normalize_isbn(entry.get("isbn")),
            "url": str(entry.get("url") or "").strip() or None,
            "raw": str(entry.get("raw") or "").strip() or None,
        }
        rows.append(citation)
    return rows


def _citation_confidence(citation: dict[str, Any]) -> dict[str, Any]:
    if str(citation.get("doi") or "").strip():
        return {"accepted": True, "score": 1.0, "reason": "doi"}
    if str(citation.get("arxiv_id") or "").strip():
        return {"accepted": True, "score": 1.0, "reason": "arxiv_id"}
    if str(citation.get("isbn") or "").strip():
        return {"accepted": True, "score": 0.95, "reason": "isbn"}

    title = str(citation.get("title") or "").strip()
    year = citation.get("year")
    author_count = len(citation.get("authors") or [])
    if len(title) >= 20 and year is not None and author_count >= 1:
        return {"accepted": True, "score": 0.8, "reason": "title_year_author"}
    return {"accepted": False, "score": 0.0, "reason": "missing_identifier_or_strong_signal"}


def _resolve_or_build_cited_reference_record(
    *,
    citation: dict[str, Any],
    corpus_id: str,
    existing_lookup: dict[str, dict[str, Any]],
    now: str,
) -> dict[str, Any]:
    external_item_id = _citation_external_item_id(citation)
    existing = existing_lookup.get(external_item_id)
    if existing:
        return {"record": existing, "isNew": False}
    lineage_id = reference_lineage_id_for(corpus_id, external_item_id)
    source_uri = _citation_source_uri(citation)
    metadata = {
        "citation_auto_created": True,
        "citation_source": "grobid",
        "citation_doi": citation.get("doi"),
        "citation_arxiv_id": citation.get("arxiv_id"),
        "citation_isbn": citation.get("isbn"),
        "citation_year": citation.get("year"),
        "citation_venue": citation.get("venue"),
        "citation_raw": citation.get("raw"),
        "identifiers": {
            "resolved": {
                "doi": citation.get("doi"),
                "arxiv_id": citation.get("arxiv_id"),
                "isbn": citation.get("isbn"),
            },
            "primary": _citation_primary_identifier(citation),
        },
    }
    record = {
        "id": f"{lineage_id}-v1",
        "lineageId": lineage_id,
        "versionNumber": 1,
        "previousVersionId": None,
        "versionState": "current",
        "versionCreatedAt": now,
        "versionCreatedBy": "papyrus-reference-url-text",
        "changeReason": "grobid-citation-graph",
        "contentHash": hash_short(
            {
                "externalItemId": external_item_id,
                "title": citation.get("title"),
                "authors": citation.get("authors"),
                "year": citation.get("year"),
                "venue": citation.get("venue"),
                "doi": citation.get("doi"),
                "arxiv_id": citation.get("arxiv_id"),
                "isbn": citation.get("isbn"),
            }
        ),
        "corpusId": corpus_id,
        "externalItemId": external_item_id,
        "title": str(citation.get("title") or "").strip() or None,
        "authors": citation.get("authors") or [],
        "sourceUri": source_uri,
        "storagePath": None,
        "mediaType": None,
        "byteSize": None,
        "sha256": None,
        "sourcePublishedAt": _year_to_iso(citation.get("year")),
        "sourceUpdatedAt": None,
        "retrievedAt": now,
        "inboundCitationCount": 0,
        "outboundCitationCount": 0,
        "importRunId": None,
        "importedAt": now,
        "createdAt": now,
        "curationStatus": "pending",
        "curationStatusKey": f"{corpus_id}#pending",
        "curationStatusUpdatedAt": now,
        "curationStatusUpdatedBy": "papyrus-reference-url-text",
        "curationStatusReason": "auto-created from GROBID citation graph",
        "newsroomFeedKey": "references",
        "reviewedFeedKey": None,
        "metadata": json.dumps(metadata, sort_keys=True),
        "updatedAt": now,
    }
    existing_lookup[external_item_id] = record
    return {"record": record, "isNew": True}


def _build_existing_reference_lookup(*, all_references: list[dict[str, Any]], corpus_id: str) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for reference in all_references:
        if str(reference.get("versionState") or "") != "current":
            continue
        if str(reference.get("corpusId") or "") != corpus_id:
            continue
        external_item_id = str(reference.get("externalItemId") or "").strip()
        if external_item_id:
            lookup.setdefault(external_item_id, reference)
        metadata = _reference_metadata_object(reference)
        identifiers = metadata.get("identifiers") if isinstance(metadata, dict) else {}
        resolved = identifiers.get("resolved") if isinstance(identifiers, dict) else {}
        doi = _normalize_doi((resolved or {}).get("doi")) if isinstance(resolved, dict) else ""
        arxiv_id = _normalize_arxiv_id((resolved or {}).get("arxiv_id")) if isinstance(resolved, dict) else ""
        isbn = _normalize_isbn((resolved or {}).get("isbn")) if isinstance(resolved, dict) else ""
        if doi:
            lookup.setdefault(f"doi:{doi.lower()}", reference)
        if arxiv_id:
            lookup.setdefault(f"arxiv:{arxiv_id.lower()}", reference)
        if isbn:
            lookup.setdefault(f"isbn:{isbn.lower()}", reference)
    return lookup


def _citation_external_item_id(citation: dict[str, Any]) -> str:
    doi = str(citation.get("doi") or "").strip()
    if doi:
        return f"doi:{doi.lower()}"
    arxiv_id = str(citation.get("arxiv_id") or "").strip()
    if arxiv_id:
        return f"arxiv:{arxiv_id.lower()}"
    isbn = str(citation.get("isbn") or "").strip()
    if isbn:
        return f"isbn:{isbn.lower()}"
    signature = {
        "title": str(citation.get("title") or "").strip().lower(),
        "year": citation.get("year"),
        "authors": [str(name or "").strip().lower() for name in (citation.get("authors") or [])[:3]],
        "venue": str(citation.get("venue") or "").strip().lower(),
    }
    return f"citation:{hash_short(signature)}"


def _citation_source_uri(citation: dict[str, Any]) -> str | None:
    url = str(citation.get("url") or "").strip()
    if url:
        return url
    doi = str(citation.get("doi") or "").strip()
    if doi:
        return f"https://doi.org/{doi}"
    arxiv_id = str(citation.get("arxiv_id") or "").strip()
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    return None


def _citation_primary_identifier(citation: dict[str, Any]) -> dict[str, str] | None:
    for key in ("doi", "arxiv_id", "isbn"):
        value = str(citation.get(key) or "").strip()
        if value:
            return {"type": key, "value": value}
    return None


def _author_semantic_node_record(*, author: dict[str, Any], now: str) -> dict[str, Any]:
    orcid = str(author.get("orcid") or "").strip()
    normalized_name = str(author.get("normalized_name") or "").strip()
    node_key = (
        f"author.orcid.{orcid.lower()}"
        if orcid
        else f"author.name.{safe_id(normalized_name or author.get('name') or '')}"
    )
    lineage_id = semantic_node_lineage_id_for(node_key)
    return {
        "id": f"{lineage_id}-v1",
        "lineageId": lineage_id,
        "versionNumber": 1,
        "previousVersionId": None,
        "versionState": "current",
        "versionCreatedAt": now,
        "versionCreatedBy": "papyrus-reference-url-text",
        "changeReason": "grobid-author-concept",
        "contentHash": hash_short(
            {
                "nodeKey": node_key,
                "name": author.get("name"),
                "orcid": orcid,
                "affiliation": author.get("affiliation"),
            }
        ),
        "nodeKey": node_key,
        "nodeKind": "personAuthor",
        "corpusId": None,
        "categorySetId": None,
        "categoryLineageId": None,
        "categoryKey": None,
        "displayName": str(author.get("name") or "").strip() or "Unknown Author",
        "description": (
            f"Publication author concept for {str(author.get('name') or '').strip()}."
            if str(author.get("name") or "").strip()
            else "Publication author concept."
        ),
        "aliases": [str(author.get("name") or "").strip()] if str(author.get("name") or "").strip() else [],
        "status": "accepted",
        "importRunId": None,
        "createdAt": now,
        "newsroomFeedKey": "semanticNodes",
        "updatedAt": now,
    }


def _semantic_relation_record(
    *,
    predicate: str,
    subject_kind: str,
    subject_id: str,
    subject_lineage_id: str,
    subject_version_number: int | None,
    object_kind: str,
    object_id: str,
    object_lineage_id: str,
    object_version_number: int | None,
    rank: int | None,
    score: float | int,
    confidence: float | None,
    now: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    subject_version_key = f"{subject_kind}#{subject_id}"
    object_version_key = f"{object_kind}#{object_id}"
    subject_state_key = f"{subject_kind}#{subject_lineage_id}#current"
    object_state_key = f"{object_kind}#{object_lineage_id}#current"
    relation = {
        "id": (
            "semantic-relation-"
            + hash_short([subject_version_key, predicate, object_version_key, rank, None, None])
        ),
        "relationState": "current",
        "predicate": predicate,
        **semantic_relation_type_fields_for_predicate(predicate),
        "subjectKind": subject_kind,
        "subjectId": subject_id,
        "subjectLineageId": subject_lineage_id,
        "subjectVersionNumber": subject_version_number,
        "objectKind": object_kind,
        "objectId": object_id,
        "objectLineageId": object_lineage_id,
        "objectVersionNumber": object_version_number,
        "subjectStateKey": subject_state_key,
        "objectStateKey": object_state_key,
        "objectSubjectStateKey": f"{object_state_key}#{subject_kind}",
        "predicateObjectStateKey": f"{predicate}#{object_state_key}",
        "subjectVersionKey": subject_version_key,
        "objectVersionKey": object_version_key,
        "score": score,
        "confidence": confidence,
        "rank": rank,
        "classifierId": None,
        "modelVersion": None,
        "reviewRecommended": False,
        "sourceSnapshotId": None,
        "importRunId": None,
        "importedAt": now,
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "semanticRelations",
        "metadata": json.dumps(metadata, sort_keys=True),
    }
    return {key: value for key, value in relation.items() if value is not None}


def _coerce_year(value: Any) -> int | None:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    if 1800 <= year <= 2200:
        return year
    return None


def _year_to_iso(value: Any) -> str | None:
    year = _coerce_year(value)
    if year is None:
        return None
    return f"{year:04d}-01-01T00:00:00Z"


def _normalize_author_identity_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def _normalize_orcid(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])", text)
    if match:
        return match.group(1).upper()
    return ""


def _normalize_doi(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", text)
    if match:
        return match.group(1)
    return ""


def _normalize_arxiv_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def _normalize_isbn(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = re.sub(r"[^0-9Xx]+", "", text)
    if len(normalized) in {10, 13}:
        return normalized.upper()
    return ""


def _bounded_citation_warning_payload(citation: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": citation.get("title"),
        "year": citation.get("year"),
        "authors": (citation.get("authors") or [])[:3],
        "doi": citation.get("doi"),
        "arxiv_id": citation.get("arxiv_id"),
        "isbn": citation.get("isbn"),
    }


def _resolve_pdf_publication_date_resolution(
    *,
    reference: dict[str, Any],
    extracted: dict[str, Any],
    structured: dict[str, Any] | None,
    is_pdf_source: bool,
) -> dict[str, Any]:
    existing_value = str(reference.get("sourcePublishedAt") or "").strip() or None
    if not is_pdf_source:
        return {
            "source": "fallback",
            "isPdfSource": False,
            "resolvedSourcePublishedAt": None,
            "fallbackSourcePublishedAt": existing_value,
            "rawCandidates": [],
            "normalizedCandidates": [],
            "warnings": [],
        }

    raw_candidates = _grobid_publication_date_candidates(
        structured=structured,
        extracted=extracted,
    )
    normalized_candidates: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    for raw_value in raw_candidates:
        parsed = _normalize_publication_date_token(raw_value)
        normalized_candidates.append(
            {
                "raw": raw_value,
                "normalized": parsed.get("value"),
                "precision": parsed.get("precision"),
                "rank": parsed.get("rank"),
                "valid": bool(parsed.get("value")),
            }
        )
        if not parsed.get("value"):
            continue
        if best is None or int(parsed.get("rank") or 99) < int(best.get("rank") or 99):
            best = parsed

    warnings: list[str] = []
    if raw_candidates and best is None:
        warnings.append("grobid_date_parse_failed")
    if not raw_candidates:
        warnings.append("grobid_date_not_found")

    resolved = str(best.get("value") or "").strip() if isinstance(best, dict) else ""
    source = "grobid" if resolved else "fallback"
    return {
        "source": source,
        "isPdfSource": True,
        "resolvedSourcePublishedAt": resolved or None,
        "resolvedPrecision": best.get("precision") if isinstance(best, dict) else None,
        "fallbackSourcePublishedAt": existing_value,
        "rawCandidates": raw_candidates[:30],
        "selectedRaw": best.get("raw") if isinstance(best, dict) else None,
        "normalizedCandidates": normalized_candidates[:30],
        "warnings": warnings,
    }


def _grobid_publication_date_candidates(*, structured: dict[str, Any] | None, extracted: dict[str, Any]) -> list[str]:
    values: list[str] = []
    date_keys = {
        "date",
        "publication_date",
        "published",
        "published_at",
        "published_date",
        "publicationdate",
        "publicationyear",
        "year",
        "when",
    }
    for payload in (structured, extracted.get("grobid")):
        if not isinstance(payload, (dict, list)):
            continue
        values.extend(_collect_date_like_values(payload, date_keys=date_keys))
    deduped: list[str] = []
    seen: set[str] = set()
    for row in values:
        token = str(row or "").strip()
        if not token:
            continue
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(token)
    return deduped


def _collect_date_like_values(payload: Any, *, date_keys: set[str], depth: int = 0) -> list[str]:
    if depth > 8:
        return []
    rows: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = str(key or "").strip().lower()
            if normalized_key in {"authors", "citations", "references", "biblio", "bibliography"}:
                continue
            if normalized_key in date_keys:
                if isinstance(value, (str, int, float)):
                    rows.append(str(value))
            rows.extend(_collect_date_like_values(value, date_keys=date_keys, depth=depth + 1))
    elif isinstance(payload, list):
        for entry in payload:
            rows.extend(_collect_date_like_values(entry, date_keys=date_keys, depth=depth + 1))
    return rows


def _normalize_publication_date_token(raw_value: str) -> dict[str, Any]:
    token = str(raw_value or "").strip()
    if not token:
        return {"raw": raw_value, "value": None, "precision": None, "rank": 99}
    normalized = token.replace("/", "-").replace(".", "-")
    full = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", normalized)
    if full:
        year, month, day = (int(full.group(1)), int(full.group(2)), int(full.group(3)))
        try:
            iso = date(year, month, day).isoformat()
        except ValueError:
            return {"raw": raw_value, "value": None, "precision": None, "rank": 99}
        return {"raw": raw_value, "value": iso, "precision": "day", "rank": 1}
    month_match = re.fullmatch(r"(\d{4})-(\d{2})", normalized)
    if month_match:
        year, month = (int(month_match.group(1)), int(month_match.group(2)))
        try:
            iso = date(year, month, 1).isoformat()
        except ValueError:
            return {"raw": raw_value, "value": None, "precision": None, "rank": 99}
        return {"raw": raw_value, "value": iso, "precision": "month", "rank": 2}
    year_match = re.fullmatch(r"(\d{4})", normalized)
    if year_match:
        year = int(year_match.group(1))
        try:
            iso = date(year, 1, 1).isoformat()
        except ValueError:
            return {"raw": raw_value, "value": None, "precision": None, "rank": 99}
        return {"raw": raw_value, "value": iso, "precision": "year", "rank": 3}
    return {"raw": raw_value, "value": None, "precision": None, "rank": 99}


def _structured_summary_for_metadata(structured: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(structured, dict):
        return None
    summary = structured.get("summary") if isinstance(structured.get("summary"), dict) else {}
    authors = structured.get("authors") if isinstance(structured.get("authors"), list) else []
    citations = structured.get("citations") if isinstance(structured.get("citations"), list) else []
    warnings = structured.get("warnings") if isinstance(structured.get("warnings"), list) else []
    return {
        "summary": {
            "authors_count": int(summary.get("authors_count") or len(authors)),
            "citations_count": int(summary.get("citations_count") or len(citations)),
            "citations_with_identifiers": int(summary.get("citations_with_identifiers") or 0),
        },
        "warningCount": len(warnings),
    }


def _reference_url_text_failure_reason(error: Exception) -> dict[str, Any]:
    if isinstance(error, ReferenceUrlTextExtractionError):
        return error.reason
    return {
        "code": "url_text_extraction_failed",
        "message": str(error),
    }


def _reference_attachment_record(
    *,
    reference: dict[str, Any],
    role: str,
    corpus_key: str,
    storage_namespace: str,
    markdown: str,
    source_uri: str | None,
    metadata: dict[str, Any],
    existing_attachment: dict[str, Any] | None,
) -> dict[str, Any]:
    now = _utc_now()
    lineage_id = str(reference.get("lineageId") or "")
    filename = _attachment_filename_for_role(role)
    reference_folder = _attachment_reference_folder(reference)
    storage_path = (
        f"corpora/{_safe_token(corpus_key)}/extracted/markitdown/{_safe_token(storage_namespace)}/{reference_folder}/{filename}"
        if corpus_key
        else f"corpora/reference-extracted/markitdown/{_safe_token(storage_namespace)}/{reference_folder}/{filename}"
    )
    body = str(markdown or "").encode("utf-8")
    sha256 = hashlib.sha256(body).hexdigest()
    key = f"{lineage_id}\n{role}"
    sort_key = "900-extracted-text" if role == "extracted_text" else "890-extracted-text-raw"
    return {
        "id": existing_attachment.get("id") if existing_attachment else f"reference-attachment-{hash_short(key)}",
        "referenceId": reference["id"],
        "referenceLineageId": lineage_id,
        "referenceVersionNumber": reference.get("versionNumber"),
        "referenceVersionKey": f"reference#{reference['id']}",
        "role": role,
        "sortKey": sort_key,
        "storagePath": storage_path,
        "sourceUri": source_uri,
        "filename": filename,
        "mediaType": "text/markdown",
        "byteSize": len(body),
        "sha256": sha256,
        "etag": None,
        "importRunId": None,
        "importedAt": now,
        "metadata": json.dumps(metadata),
        "__attachmentBody": body,
    }


def _reference_source_attachment_record(
    *,
    reference: dict[str, Any],
    corpus_key: str,
    source_uri: str,
    metadata: dict[str, Any],
    content: bytes,
    media_type: str,
    existing_attachment: dict[str, Any] | None,
) -> dict[str, Any]:
    now = _utc_now()
    lineage_id = str(reference.get("lineageId") or "")
    reference_folder = _attachment_reference_folder(reference)
    filename = _source_filename_for_uri(source_uri=source_uri, media_type=media_type)
    storage_path = (
        f"corpora/{_safe_token(corpus_key)}/source/{reference_folder}/{filename}"
        if corpus_key
        else f"corpora/reference-source/{reference_folder}/{filename}"
    )
    body = bytes(content)
    sha256 = hashlib.sha256(body).hexdigest()
    key = f"{lineage_id}\nsource\n{storage_path}"
    return {
        "id": existing_attachment.get("id") if existing_attachment else f"reference-attachment-{hash_short(key)}",
        "referenceId": reference["id"],
        "referenceLineageId": lineage_id,
        "referenceVersionNumber": reference.get("versionNumber"),
        "referenceVersionKey": f"reference#{reference['id']}",
        "role": "source",
        "sortKey": "001-source",
        "storagePath": storage_path,
        "sourceUri": source_uri,
        "filename": filename,
        "mediaType": media_type or "application/pdf",
        "byteSize": len(body),
        "sha256": sha256,
        "etag": None,
        "importRunId": None,
        "importedAt": now,
        "metadata": json.dumps(metadata),
        "__attachmentBody": body,
    }


def _download_source_attachment_from_uri(source_uri: str, *, reference: dict[str, Any] | None = None) -> bytes:
    parsed = urlparse(source_uri)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported source URI scheme for source attachment download: {source_uri}")
    request = Request(source_uri, headers={"User-Agent": "Papyrus reference source downloader"})
    try:
        with urlopen(request, timeout=45) as response:
            payload = response.read()
    except Exception as error:
        if reference is None:
            raise
        fallback = resolve_accessible_pdf_url_for_reference(
            reference,
            source_uri=str(reference.get("sourceUri") or source_uri),
            failed_uri=source_uri,
        )
        fallback_uri = normalize_http_url(fallback.get("selectedPdfUrl"))
        if not fallback_uri or fallback_uri == normalize_http_url(source_uri):
            raise
        request = Request(fallback_uri, headers={"User-Agent": "Papyrus reference source downloader"})
        with urlopen(request, timeout=45) as response:
            payload = response.read()
        if not payload:
            raise ValueError(f"Downloaded empty source payload from {fallback_uri}") from error
        return payload
    if not payload:
        raise ValueError(f"Downloaded empty source payload from {source_uri}")
    return payload


def _source_filename_for_uri(*, source_uri: str, media_type: str) -> str:
    parsed = urlparse(source_uri)
    token = Path(parsed.path or "").name or ""
    if token and "." in token:
        return _safe_token(token)
    extension = ".pdf"
    normalized = str(media_type or "").split(";", 1)[0].strip().lower()
    if normalized in {"text/html", "application/xhtml+xml"}:
        extension = ".html"
    elif normalized in {"text/plain"}:
        extension = ".txt"
    return f"source{extension}"


def _doi_resolution_for_metadata(enrichment: dict[str, Any]) -> dict[str, Any] | None:
    metadata = enrichment.get("metadata") if isinstance(enrichment.get("metadata"), dict) else {}
    resolution = metadata.get("doiResolution")
    return resolution if isinstance(resolution, dict) else None


def _iter_candidate_references(
    *,
    references: list[dict[str, Any]],
    corpus_id: str | None,
    curation_status: str,
    reference_ids: set[str],
    external_item_ids: set[str],
) -> list[dict[str, Any]]:
    rows = [
        reference
        for reference in references
        if reference.get("versionState") == "current"
        and (not corpus_id or reference.get("corpusId") == corpus_id)
        and (curation_status == "all" or reference.get("curationStatus") == curation_status)
        and (not reference_ids or str(reference.get("id") or "") in reference_ids)
        and (
            not external_item_ids
            or str(reference.get("externalItemId") or "") in external_item_ids
        )
    ]
    rows.sort(
        key=lambda reference: (
            str(reference.get("updatedAt") or reference.get("createdAt") or ""),
            str(reference.get("versionNumber") or ""),
            str(reference.get("id") or ""),
        ),
        reverse=True,
    )
    return rows


def _corpus_key_from_reference(reference: dict[str, Any]) -> str:
    corpus_id = str(reference.get("corpusId") or "")
    if corpus_id.startswith("knowledge-corpus-"):
        return corpus_id.removeprefix("knowledge-corpus-")
    return "unknown"


def _reference_metadata_update_record(
    *,
    reference: dict[str, Any],
    enrichment: dict[str, Any],
    source_uri: str,
    canonical_uri: str,
    publication_date_resolution: dict[str, Any],
) -> dict[str, Any] | None:
    reference_id = str(reference.get("id") or "").strip()
    if not reference_id:
        return None
    current_metadata = _reference_metadata_object(reference)
    next_metadata = _merge_reference_metadata_with_enrichment(
        current_metadata=current_metadata,
        enrichment=enrichment,
        source_uri=source_uri,
        canonical_uri=canonical_uri,
        publication_date_resolution=publication_date_resolution,
    )
    expected: dict[str, Any] = {
        "id": reference_id,
        "metadata": json.dumps(next_metadata, sort_keys=True),
        "updatedAt": _utc_now(),
    }
    resolved_source_published_at = publication_date_resolution.get("resolvedSourcePublishedAt")
    if resolved_source_published_at is not None:
        expected["sourcePublishedAt"] = resolved_source_published_at
    return {
        "modelName": "Reference",
        "expected": expected,
    }


def _reference_metadata_object(reference: dict[str, Any]) -> dict[str, Any]:
    metadata = reference.get("metadata")
    if isinstance(metadata, dict):
        return dict(metadata)
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _resolve_existing_canonical_uri(reference: dict[str, Any]) -> str | None:
    metadata = _reference_metadata_object(reference)
    identifiers = metadata.get("identifiers") if isinstance(metadata.get("identifiers"), dict) else {}
    resolved = identifiers.get("resolved") if isinstance(identifiers.get("resolved"), dict) else {}
    canonical_uri = normalize_http_url(resolved.get("canonical_uri"))
    if canonical_uri:
        return canonical_uri
    source_uri = normalize_http_url(resolved.get("source_uri"))
    if source_uri:
        return source_uri
    papyrus = metadata.get("papyrus") if isinstance(metadata.get("papyrus"), dict) else {}
    source_resolution = papyrus.get("source_resolution") if isinstance(papyrus.get("source_resolution"), dict) else {}
    for payload in source_resolution.values():
        if not isinstance(payload, dict):
            continue
        candidate = normalize_http_url(payload.get("canonicalUri")) or normalize_http_url(payload.get("sourceUri"))
        if candidate:
            return candidate
    return None


def _resolve_process_source_uri(
    reference: dict[str, Any],
    attachments: list[dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None]:
    source_attachment = select_reference_attachment_by_role(reference, attachments, role="source")
    if isinstance(source_attachment, dict):
        source_uri = normalize_http_url(source_attachment.get("sourceUri"))
        if source_uri:
            return source_uri, None
    canonical_uri = _resolve_existing_canonical_uri(reference)
    if canonical_uri:
        return canonical_uri, None
    return None, {
        "code": "needs_find_missing_canonical_source",
        "message": "Reference processing requires find-stage canonical source resolution first.",
    }


def _reference_find_seed_uri(reference: dict[str, Any]) -> str | None:
    direct_source_uri = normalize_http_url(reference.get("sourceUri"))
    if direct_source_uri:
        return direct_source_uri
    external_item_id = str(reference.get("externalItemId") or "").strip()
    if external_item_id.lower().startswith("doi:"):
        doi_value = external_item_id[4:].strip()
        if doi_value:
            return normalize_http_url(f"https://doi.org/{doi_value}")
    return None


def _merge_reference_metadata_with_enrichment(
    *,
    current_metadata: dict[str, Any],
    enrichment: dict[str, Any],
    source_uri: str,
    canonical_uri: str,
    publication_date_resolution: dict[str, Any],
) -> dict[str, Any]:
    output = dict(current_metadata)
    plugin_key = str(enrichment.get("pluginKey") or "default")

    papyrus = output.get("papyrus")
    if not isinstance(papyrus, dict):
        papyrus = {}
    source_resolution = papyrus.get("source_resolution")
    if not isinstance(source_resolution, dict):
        source_resolution = {}
    plugin_metadata = enrichment.get("metadata")
    plugin_payload = dict(plugin_metadata) if isinstance(plugin_metadata, dict) else {}
    plugin_payload.setdefault("sourceUri", source_uri)
    plugin_payload.setdefault("canonicalUri", canonical_uri)
    plugin_payload.setdefault("sourceVariants", enrichment.get("sourceVariants") if isinstance(enrichment.get("sourceVariants"), dict) else {})
    source_resolution[plugin_key] = plugin_payload
    papyrus["source_resolution"] = source_resolution
    papyrus["publication_date_resolution"] = publication_date_resolution
    output["papyrus"] = papyrus

    identifiers = output.get("identifiers")
    if not isinstance(identifiers, dict):
        identifiers = {}
    resolved_existing = identifiers.get("resolved")
    resolved = dict(resolved_existing) if isinstance(resolved_existing, dict) else {}
    enriched_identifiers = enrichment.get("identifiers")
    enriched_identifiers = enriched_identifiers if isinstance(enriched_identifiers, dict) else {}
    resolved.update(
        {
            str(key): str(value)
            for key, value in (enriched_identifiers.get("resolved") or {}).items()
            if str(value).strip()
        }
    )
    resolved["source_uri"] = source_uri
    resolved["canonical_uri"] = canonical_uri

    candidates_existing = identifiers.get("candidates")
    merged_candidates = list(candidates_existing) if isinstance(candidates_existing, list) else []
    if isinstance(enriched_identifiers.get("candidates"), list):
        merged_candidates.extend(enriched_identifiers.get("candidates") or [])
    merged_candidates = _dedupe_identifier_candidates(merged_candidates)

    warnings_existing = identifiers.get("warnings")
    merged_warnings = list(warnings_existing) if isinstance(warnings_existing, list) else []
    if isinstance(enriched_identifiers.get("warnings"), list):
        merged_warnings.extend(enriched_identifiers.get("warnings") or [])
    if isinstance(enrichment.get("warnings"), list):
        merged_warnings.extend(enrichment.get("warnings") or [])
    merged_warnings = _dedupe_warning_objects(merged_warnings)

    primary = enriched_identifiers.get("primary")
    if not isinstance(primary, dict) or not primary.get("type") or not primary.get("value"):
        primary = _primary_identifier_from_candidates(resolved=resolved, candidates=merged_candidates)

    identifiers["resolved"] = resolved
    identifiers["candidates"] = merged_candidates
    identifiers["primary"] = primary
    identifiers["warnings"] = merged_warnings
    identifiers["provenance"] = {
        "sourcePlugin": plugin_key,
        "resolvedAt": _utc_now(),
    }
    output["identifiers"] = identifiers
    return output


def _primary_identifier_from_candidates(*, resolved: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, str] | None:
    precedence = ("arxiv_id", "doi", "youtube_video_id", "canonical_uri", "source_uri")
    for key in precedence:
        value = str(resolved.get(key) or "").strip()
        if value:
            return {"type": key, "value": value}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        id_type = str(candidate.get("type") or "").strip()
        value = str(candidate.get("value") or "").strip()
        if id_type and value:
            return {"type": id_type, "value": value}
    return None


def _dedupe_identifier_candidates(candidates: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in candidates:
        if not isinstance(row, dict):
            continue
        id_type = str(row.get("type") or "").strip()
        value = str(row.get("value") or "").strip()
        source = str(row.get("source") or "").strip()
        if not id_type or not value:
            continue
        key = (id_type, value, source)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "type": id_type,
                "value": value,
                "source": source,
                "confidence": row.get("confidence"),
                "rank": row.get("rank"),
            }
        )
    normalized.sort(key=lambda row: (int(row.get("rank") or 999), row.get("type") or "", row.get("value") or ""))
    return normalized


def _dedupe_warning_objects(rows: list[Any]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            payload = row
        else:
            payload = {"message": str(row)}
        key = json.dumps(payload, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(payload)
    return deduped


def _enrichment_attachment_metadata(enrichment: dict[str, Any]) -> dict[str, Any]:
    identifiers = enrichment.get("identifiers")
    identifiers = identifiers if isinstance(identifiers, dict) else {}
    payload = {
        "sourcePlugin": enrichment.get("pluginKey"),
        "sourceVariants": enrichment.get("sourceVariants") if isinstance(enrichment.get("sourceVariants"), dict) else {},
        "identifiers": {
            "resolved": identifiers.get("resolved") if isinstance(identifiers.get("resolved"), dict) else {},
            "primary": identifiers.get("primary") if isinstance(identifiers.get("primary"), dict) else None,
        },
        "pluginWarnings": identifiers.get("warnings") if isinstance(identifiers.get("warnings"), list) else [],
    }
    attachment_metadata = enrichment.get("attachmentMetadata")
    if isinstance(attachment_metadata, dict):
        payload.update(attachment_metadata)
    enriched_metadata = enrichment.get("metadata")
    if isinstance(enriched_metadata, dict):
        if str(enriched_metadata.get("abstract") or "").strip():
            payload["abstract"] = str(enriched_metadata.get("abstract") or "")
        if str(enriched_metadata.get("abstractSource") or "").strip():
            payload["abstractSource"] = str(enriched_metadata.get("abstractSource") or "")
        if str(enriched_metadata.get("doi") or "").strip():
            payload["doi"] = str(enriched_metadata.get("doi") or "")
        if isinstance(enriched_metadata.get("doiResolution"), dict):
            payload["doiResolution"] = enriched_metadata.get("doiResolution")
    return payload


def _doi_resolution_metrics(enrichment: dict[str, Any]) -> dict[str, int]:
    if str(enrichment.get("pluginKey") or "").strip().lower() != "doi":
        return {
            "doiResolved": 0,
            "doiPdfSelected": 0,
            "doiPdfMissed": 0,
            "doiSearchUsed": 0,
            "doiSearchHit": 0,
            "doiApiFallbackUsed": 0,
            "doiPaywalledOrBlocked": 0,
        }
    metadata = enrichment.get("metadata") if isinstance(enrichment.get("metadata"), dict) else {}
    resolution = metadata.get("doiResolution") if isinstance(metadata.get("doiResolution"), dict) else {}
    outcome = str(resolution.get("outcome") or "").strip().lower()
    return {
        "doiResolved": 1 if outcome and outcome != "doi_unresolved" else 0,
        "doiPdfSelected": 1 if outcome == "pdf_selected" else 0,
        "doiPdfMissed": 1 if outcome and outcome != "pdf_selected" else 0,
        "doiSearchUsed": 1 if bool(resolution.get("searchUsed")) else 0,
        "doiSearchHit": 1 if bool(resolution.get("searchHit")) else 0,
        "doiApiFallbackUsed": 1 if bool(resolution.get("apiFallbackUsed")) else 0,
        "doiPaywalledOrBlocked": 1 if bool(resolution.get("paywalledOrBlocked")) else 0,
    }


def _original_subtitle(reference: dict[str, Any]) -> str:
    metadata = reference.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return str(
        metadata.get("original_subtitle")
        or metadata.get("originalSubtitle")
        or metadata.get("subtitle")
        or reference.get("subtitle")
        or ""
    ).strip()


def _reference_row(reference: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": reference.get("id"),
        "lineageId": reference.get("lineageId"),
        "externalItemId": reference.get("externalItemId"),
        "sourceUri": reference.get("sourceUri"),
        "curationStatus": reference.get("curationStatus"),
        "title": reference.get("title"),
    }


def _safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return token[:180] or "reference"


def _attachment_filename_for_role(role: str) -> str:
    normalized = str(role or "").strip()
    if normalized == "extracted_text":
        return "extracted_text.md"
    if normalized == "extracted_text_raw":
        return "extracted_text_raw.md"
    return f"{_safe_token(normalized or 'attachment')}.md"


def _attachment_reference_folder(reference: dict[str, Any]) -> str:
    return _safe_token(
        str(
            reference.get("lineageId")
            or reference.get("id")
            or reference.get("externalItemId")
            or "reference"
        )
    )


def _attachment_metadata_object(attachment: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(attachment, dict):
        return {}
    metadata = attachment.get("metadata")
    if isinstance(metadata, dict):
        return dict(metadata)
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _attachment_filter_status(attachment: dict[str, Any] | None) -> str:
    metadata = _attachment_metadata_object(attachment)
    return str(metadata.get("filterStatus") or metadata.get("filter_status") or "").strip().lower()


def _canonical_attachment_is_clearly_non_filtered(attachment: dict[str, Any] | None) -> bool:
    if not isinstance(attachment, dict):
        return False
    if str(attachment.get("role") or "") != "extracted_text":
        return False
    status = _attachment_filter_status(attachment)
    if status == "filtered":
        return False
    if status in {"fallback_raw", "raw", "unfiltered"}:
        return True
    metadata = _attachment_metadata_object(attachment)
    source = str(metadata.get("source") or "").strip().lower()
    if source == "biblicus-article-text-filter":
        return False
    return source in {"biblicus-url-text", "papyrus-reference-text-filter"}


def _base_raw_metadata_for_filter(
    *,
    existing_raw: dict[str, Any] | None,
    source_attachment: dict[str, Any] | None,
    source_uri: str,
    source_text: str,
) -> dict[str, Any]:
    metadata = _attachment_metadata_object(existing_raw)
    metadata.setdefault("source", "papyrus-reference-text-filter")
    metadata.setdefault("extractorId", "papyrus.references.process-filter-text")
    metadata["sourceUri"] = source_uri or metadata.get("sourceUri")
    metadata["importedAt"] = _utc_now()
    metadata["textLength"] = len(source_text)
    if source_attachment is not None:
        metadata["copiedFromAttachmentId"] = source_attachment.get("id")
    else:
        metadata["reconstructedFromSourceUri"] = source_uri or None
    return metadata


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
