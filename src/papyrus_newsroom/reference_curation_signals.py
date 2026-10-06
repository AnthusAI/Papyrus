"""Reference summary and quality curation signals.

The module owns the reusable planning/writing contract for budgeted reference
summaries and one-to-five quality ratings. It intentionally uses the same
SemanticRelation state-key shape as the rest of Papyrus so Tactus, CLI, and
ranking code can share one graph contract.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

try:
    import tiktoken
except ModuleNotFoundError:  # pragma: no cover - dependency exists in normal envs
    tiktoken = None

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - PyYAML is a project dependency
    yaml = None

from .semantic import PapyrusSemanticClient, semantic_state_key, semantic_version_key
from . import web_search_providers


PAPYRUS_ROOT = Path(__file__).resolve().parents[2]
BIBLICUS_ROOT = PAPYRUS_ROOT.parent / "Biblicus"
SUMMARY_TOKEN_BUDGETS = (100, 200, 500, 1000, 1800)
SUMMARY_MESSAGE_KIND = "reference_summary"
SUMMARY_MESSAGE_DOMAIN = "summarization"
SUMMARY_SOURCE = "papyrus-summary-generator"
SUMMARY_PROMPT_VERSION = "reference-summary-v3-source-voice"
SUMMARY_PROCEDURE_ALIAS_SUMMARIZE = "references.summarize"
SUMMARY_PROCEDURE_ALIAS_SUMMARIZE_BATCH = "references.summarize-batch"
SUMMARY_PROCEDURE_ALIAS_TITLE_SUBTITLE_RESOLVE = "references.title-subtitle.resolve"
SUMMARY_PROCEDURE_ALIAS_TITLE_SUBTITLE_BATCH = "references.title-subtitle.batch"
SUMMARY_PROCEDURE_ALIAS_TITLE_SUBTITLE_ENRICH_CATALOG = "references.title-subtitle.enrich-catalog"
SUMMARY_PROCEDURE_OUTPUT_MARKERS = ("mode", "summary_text", "prompt_version")
PUBLICATION_DOCTRINE_SLUGS = ("editorial-doctrine-mission", "editorial-doctrine-policy")
DOCTRINE_POLICY_USE = "context_only_not_reference_rubric"
QUALITY_RELATION_TYPE_KEY = "quality_rating_is"
QUALITY_NODE_KIND = "qualityRating"
QUALITY_ASSESSMENT_SOURCE = "papyrus-quality-assessor"
QUALITY_ASSESSMENT_PROMPT_VERSION = "reference-quality-v1-publication-doctrine"
QUALITY_ASSESSMENT_RUBRIC = """
Rate the source quality of this Reference from 1 to 5.

5 = Landmark or very strong primary source: rigorous research, important method/result, high relevance, clear evidence.
4 = Strong useful source: credible, substantive, relevant, and likely valuable for context packs or editorial research.
3 = Adequate source: credible or useful but limited, narrow, derivative, preliminary, or only moderately relevant.
2 = Weak source: low evidentiary value, shallow, noisy, unclear provenance, or only tangentially useful.
1 = Very weak source: unreliable, spammy, mostly irrelevant, content-free, or not useful as knowledge-base evidence.

Assess the Reference as source material. Do not punish a Reference for disagreeing with Papyrus editorial policies; those policies are context only.
"""
QUALITY_NODE_KEYS = {
    1: "quality.rating.1_star",
    2: "quality.rating.2_star",
    3: "quality.rating.3_star",
    4: "quality.rating.4_star",
    5: "quality.rating.5_star",
}
TITLE_SUBTITLE_SOURCE = "papyrus-title-subtitle-enricher"
TITLE_SUBTITLE_PROMPT_VERSION = "reference-title-subtitle-v1-verbatim-source"
TITLE_SUBTITLE_SUMMARY_PROMPT_VERSION = "reference-title-subtitle-summary-v2-source-voice"
TITLE_SUBTITLE_SUMMARY_TOKEN_BUDGET_DEFAULT = 1800
TITLE_SUBTITLE_BATCH_WORKERS = 8
SUMMARY_SOURCE_TEXT_MAX_CHARS = 12000
REFERENCE_METADATA_MODEL_DEFAULT = "gpt-5.4-nano"
BIBLICUS_SUMMARIZE_MAP_REDUCE_PROMPT_VERSION = "summarize-map-reduce-v2"
BIBLICUS_CATALOG_ITEM_ROOT_FIELDS = frozenset(
    {
        "id",
        "relpath",
        "sha256",
        "bytes",
        "media_type",
        "title",
        "tags",
        "metadata",
        "dates",
        "created_at",
        "source_uri",
    }
)
CATALOG_EXTENSION_ROOT_FIELDS = frozenset(
    {
        "identifiers",
        "identifier_resolution",
        "papyrus",
        "summary",
        "summary_resolution",
        "title_subtitle_resolution",
        "subtitle",
        "quality",
    }
)
IDENTIFIER_PREPASS_TYPES = ("doi", "arxiv_id", "isbn13", "publisher_item")
IDENTIFIER_PREPASS_SOURCE_ORDER = {
    "metadata.identifiers": 0,
    "explicit_field": 1,
    "source_uri": 2,
    "title": 3,
    "subtitle": 4,
}
IDENTIFIER_ALIASES = {
    "doi": ("doi", "source_doi"),
    "arxiv_id": ("arxiv_id", "arxivId", "arxiv"),
    "isbn13": ("isbn13", "isbn"),
    "publisher_item": ("publisher_item", "publisherItem"),
}
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", flags=re.IGNORECASE)
ARXIV_MODERN_RE = re.compile(r"\b([0-9]{4}\.[0-9]{4,5})(?:v\d+)?\b", flags=re.IGNORECASE)
ARXIV_LEGACY_RE = re.compile(r"\b([a-z-]+(?:\.[a-z]{2})?/[0-9]{7})(?:v\d+)?\b", flags=re.IGNORECASE)
ISBN13_TEXT_RE = re.compile(r"\b97[89][0-9\-\s]{10,20}\b")
ISBN10_TEXT_RE = re.compile(r"\b[0-9][0-9\-\s]{8,16}[0-9Xx]\b")


REFERENCE_FIELDS = """
id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash
corpusId externalItemId title authors sourceUri storagePath mediaType byteSize sha256 sourcePublishedAt sourceUpdatedAt
retrievedAt importRunId importedAt curationStatus curationStatusKey curationStatusUpdatedAt curationStatusUpdatedBy curationStatusReason updatedAt
"""

LIST_REFERENCES_BY_CORPUS_QUERY = f"""
query ListReferencesByCorpus($corpusId: ID!, $limit: Int, $nextToken: String) {{
  listReferencesByCorpusAndExternalItem(corpusId: $corpusId, limit: $limit, nextToken: $nextToken) {{
    items {{ {REFERENCE_FIELDS} }}
    nextToken
  }}
}}
"""

LIST_REFERENCES_BY_NEWSROOM_FEED_IMPORTED_QUERY = f"""
query ListReferencesByNewsroomFeedAndImportedAt($newsroomFeedKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelReferenceFilterInput) {{
  listReferencesByNewsroomFeedAndImportedAt(newsroomFeedKey: $newsroomFeedKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {{
    items {{ {REFERENCE_FIELDS} }}
    nextToken
  }}
}}
"""

LIST_REFERENCE_ATTACHMENTS_BY_LINEAGE_QUERY = """
query ListReferenceAttachmentsByLineage($referenceLineageId: ID!, $limit: Int, $nextToken: String) {
  listReferenceAttachmentsByReferenceLineageAndSortKey(referenceLineageId: $referenceLineageId, limit: $limit, nextToken: $nextToken) {
    items {
      id
      referenceId
      referenceLineageId
      role
      sortKey
      storagePath
      sourceUri
      filename
      mediaType
      importRunId
      importedAt
      status
      metadata
    }
    nextToken
  }
}
"""

CREATE_MODEL_ATTACHMENT_UPLOAD_MUTATION = """
mutation CreateModelAttachmentUpload(
  $ownerKind: String!
  $ownerId: ID!
  $ownerLineageId: ID
  $ownerVersionNumber: Int
  $ownerVersionKey: String
  $role: String!
  $sortKey: String
  $filename: String!
  $mediaType: String!
  $byteSize: Int!
  $sha256: String
  $importRunId: ID
  $status: String
) {
  createModelAttachmentUpload(
    ownerKind: $ownerKind
    ownerId: $ownerId
    ownerLineageId: $ownerLineageId
    ownerVersionNumber: $ownerVersionNumber
    ownerVersionKey: $ownerVersionKey
    role: $role
    sortKey: $sortKey
    filename: $filename
    mediaType: $mediaType
    byteSize: $byteSize
    sha256: $sha256
    importRunId: $importRunId
    status: $status
  ) {
    uploadId
    uploadUrl
    storagePath
    requiredHeaders
  }
}
"""

COMPLETE_MODEL_ATTACHMENT_UPLOAD_MUTATION = """
mutation CompleteModelAttachmentUpload(
  $uploadId: String!
  $ownerKind: String!
  $ownerId: ID!
  $ownerLineageId: ID
  $ownerVersionNumber: Int
  $ownerVersionKey: String
  $role: String!
  $sortKey: String
  $filename: String!
  $mediaType: String!
  $byteSize: Int!
  $sha256: String
  $importRunId: ID
  $status: String
) {
  completeModelAttachmentUpload(
    uploadId: $uploadId
    ownerKind: $ownerKind
    ownerId: $ownerId
    ownerLineageId: $ownerLineageId
    ownerVersionNumber: $ownerVersionNumber
    ownerVersionKey: $ownerVersionKey
    role: $role
    sortKey: $sortKey
    filename: $filename
    mediaType: $mediaType
    byteSize: $byteSize
    sha256: $sha256
    importRunId: $importRunId
    status: $status
  ) {
    id
  }
}
"""

UPDATE_NEWSROOM_SUMMARY_MUTATION = """
mutation UpdateNewsroomSummary($delta: AWSJSON!, $actorLabel: String, $reason: String) {
  updateNewsroomSummary(delta: $delta, actorLabel: $actorLabel, reason: $reason) {
    generatedAt
  }
}
"""

LIST_DOCTRINE_ITEMS_BY_SLUG_QUERY = """
query ListDoctrineItemsBySlug($slug: String!, $limit: Int, $nextToken: String) {
  itemBySlug(slug: $slug, limit: $limit, nextToken: $nextToken) {
    items {
      id
      lineageId
      versionNumber
      versionState
      type
      status
      typeStatus
      slug
      title
      headline
      body
      editorial
      updatedAt
    }
    nextToken
  }
}
"""


def summary_relation_type_key(max_tokens: int) -> str:
    budget = normalize_summary_budget(max_tokens)
    return f"reference_summary_{budget}_tokens"


def normalize_summary_budget(value: Any) -> int:
    try:
        budget = int(value)
    except (TypeError, ValueError):
        raise ValueError("summary max tokens must be one of 100, 200, 500, 1000, or 1800") from None
    if budget not in SUMMARY_TOKEN_BUDGETS:
        raise ValueError("summary max tokens must be one of 100, 200, 500, 1000, or 1800")
    return budget


def normalize_title_subtitle_summary_budget(value: Any) -> int:
    try:
        budget = int(value)
    except (TypeError, ValueError):
        raise ValueError("summary max tokens must be a positive integer") from None
    if budget <= 0:
        raise ValueError("summary max tokens must be a positive integer")
    return budget


def normalize_quality_rating(value: Any) -> int:
    try:
        rating = int(value)
    except (TypeError, ValueError):
        raise ValueError("quality rating must be an integer from 1 to 5") from None
    if rating < 1 or rating > 5:
        raise ValueError("quality rating must be an integer from 1 to 5")
    return rating


def quality_node_key(rating: int) -> str:
    return QUALITY_NODE_KEYS[normalize_quality_rating(rating)]


def quality_node_lineage_id(rating: int) -> str:
    return f"semantic-node-{_safe_id(quality_node_key(rating))}"


def quality_node_id(rating: int) -> str:
    return f"{quality_node_lineage_id(rating)}-v1"


def build_reference_quality_plan(
    *,
    reference: dict[str, Any],
    rating: int,
    note: str = "",
    actor_label: str = "papyrus",
    source: str = "manual",
    refresh: bool = False,
    run_id: str = "",
    assignment_id: str = "",
    now: str | None = None,
    semantic_client: PapyrusSemanticClient | None = None,
) -> dict[str, Any]:
    now = now or _now()
    rating = normalize_quality_rating(rating)
    reference = _require_reference(reference)
    semantic = semantic_client or _semantic_client()
    existing = _current_relations(
        semantic.list_outgoing("reference", reference["lineageId"])["relations"],
        QUALITY_RELATION_TYPE_KEY,
    )
    target_node_id = quality_node_id(rating)
    quality_node_record = None
    try:
        semantic.get_semantic_object("semanticNode", target_node_id)
    except ValueError:
        quality_node_record = _quality_semantic_node_record(rating, now)
    same_current = [
        relation for relation in existing
        if relation.get("objectLineageId") == quality_node_lineage_id(rating)
        and _number_or_none(relation.get("score")) == float(rating)
    ]
    if same_current and not refresh:
        return {
            "kind": "reference.quality-rating.plan",
            "action": "noop",
            "reference": _reference_summary(reference),
            "rating": rating,
            "existingRelationId": same_current[0].get("id"),
            "records": [],
            "warnings": [],
        }

    metadata = _compact_dict({
        "kind": "reference.quality-rating.linked",
        "qualityRating": rating,
        "source": source,
        "actorLabel": actor_label,
        "note": note,
        "runId": run_id,
        "assignmentId": assignment_id,
        "ratedAt": now,
    })
    stale_updates = [
        _supersede_relation_record(relation, now, {"supersededByRating": rating, "supersededAt": now})
        for relation in existing
    ]
    relation = _semantic_relation(
        predicate=QUALITY_RELATION_TYPE_KEY,
        subject_kind="reference",
        subject_id=reference["id"],
        subject_lineage_id=reference["lineageId"],
        subject_version_number=reference.get("versionNumber"),
        object_kind="semanticNode",
        object_id=target_node_id,
        object_lineage_id=quality_node_lineage_id(rating),
        object_version_number=1,
        score=rating,
        confidence=None,
        rank=1,
        classifier_id=None,
        model_version=None,
        import_run_id=reference.get("importRunId"),
        imported_at=now,
        metadata=metadata,
    )
    return {
        "kind": "reference.quality-rating.plan",
        "action": "create",
        "reference": _reference_summary(reference),
        "rating": rating,
        "records": [
            *([{"modelName": "SemanticNode", "action": "create", "input": quality_node_record}] if quality_node_record else []),
            {"modelName": "SemanticRelation", "action": "create", "input": relation},
            *stale_updates,
        ],
        "summaryDelta": _summary_delta_for_plan(
            messages=0,
            model_attachments=0,
            created_relations=1,
            superseded_relations=len(stale_updates),
            relation_type_key=QUALITY_RELATION_TYPE_KEY,
            relation_domain="curation",
            subject_kind="reference",
            object_kind="semanticNode",
            semantic_nodes=1 if quality_node_record else 0,
        ),
        "warnings": [],
    }


def build_reference_summary_plan(
    *,
    reference: dict[str, Any],
    max_tokens: int,
    summary_text: str,
    source_text: str = "",
    model: str = "",
    tokenizer: str = "tiktoken",
    prompt_version: str = SUMMARY_PROMPT_VERSION,
    rationale: str = "",
    doctrine_context: dict[str, Any] | None = None,
    actor_label: str = "papyrus-summary-generator",
    refresh: bool = False,
    run_id: str = "",
    assignment_id: str = "",
    identifier_prepass: dict[str, Any] | None = None,
    now: str | None = None,
    semantic_client: PapyrusSemanticClient | None = None,
) -> dict[str, Any]:
    now = now or _now()
    max_tokens = normalize_summary_budget(max_tokens)
    summary_text = _required(summary_text, "summary_text")
    reference = _require_reference(reference)
    metadata_payload = _load_reference_metadata_payload(reference)
    existing_summary = _normalize_outcome_summary_candidate(metadata_payload.get("summary") if isinstance(metadata_payload, dict) else "")
    if existing_summary == summary_text and not refresh:
        return {
            "kind": "reference.summary.plan",
            "action": "noop",
            "reference": _reference_summary(reference),
            "maxTokens": max_tokens,
            "existingSummary": existing_summary,
            "records": [],
            "warnings": [],
        }
    actual_tokens = estimate_tokens(summary_text, model=model)
    source_content_hash = _hash_text(source_text) if source_text else str(reference.get("contentHash") or reference.get("sha256") or "")
    doctrine_metadata = doctrine_summary_metadata(
        doctrine_context or manual_summary_doctrine_context()
    )
    metadata = _compact_dict({
        "kind": "reference.summary.generated",
        "maxTokens": max_tokens,
        "actualTokenEstimate": actual_tokens,
        "tokenizer": tokenizer,
        "model": model,
        "promptVersion": prompt_version,
        "sourceContentHash": source_content_hash,
        "referenceLineageId": reference["lineageId"],
        "runId": run_id,
        "assignmentId": assignment_id,
        "generatedAt": now,
        "rationale": rationale,
    })
    if isinstance(identifier_prepass, dict):
        metadata["identifierPrepass"] = {
            "status": identifier_prepass.get("status"),
            "failureReason": identifier_prepass.get("failureReason"),
            "extracted": identifier_prepass.get("extracted") or {},
            "resolution": identifier_prepass.get("resolution") or {},
        }
    metadata.update(doctrine_metadata)
    summary_resolution = _summary_resolution(
        summary=summary_text,
        summary_token_budget=max_tokens,
        model=model or "gpt-5.4-mini",
        source="llm_reference_summary" if model and model != "manual" else "manual_override",
        source_urls=[],
        run_id=run_id,
        resolved_at=now,
        rationale=rationale or "Generated canonical reference summary.",
        prompt_version=prompt_version,
    )
    next_metadata = dict(metadata_payload) if isinstance(metadata_payload, dict) else {}
    next_metadata["summary"] = summary_text
    next_metadata["summary_resolution"] = summary_resolution
    if identifier_prepass:
        next_metadata.update(
            _identifier_metadata_update(
                metadata=next_metadata,
                identifier_prepass=identifier_prepass,
            )
        )
    metadata_attachment = _model_attachment(
        owner_kind="reference",
        owner_id=reference["id"],
        role="metadata",
        sort_key="metadata",
        filename="metadata.json",
        media_type="application/json",
        content=next_metadata,
        import_run_id=reference.get("importRunId"),
        now=now,
    )
    return {
        "kind": "reference.summary.plan",
        "action": "create",
        "reference": _reference_summary(reference),
        "maxTokens": max_tokens,
        "metadata": metadata,
        "summary": summary_text,
        "summaryResolution": summary_resolution,
        "records": [
            {"modelName": "ModelAttachment", "action": "create", "input": metadata_attachment["record"], "body": metadata_attachment["body"]},
        ],
        "summaryDelta": _summary_delta_for_plan(
            messages=0,
            model_attachments=1,
            created_relations=0,
            superseded_relations=0,
            relation_type_key="",
            relation_domain="summarization",
            subject_kind="reference",
            object_kind="reference",
        ),
        "warnings": [],
    }


def resolve_reference_title_subtitle(
    reference: dict[str, Any] | None = None,
    catalog_entry: dict[str, Any] | None = None,
    sidecar: dict[str, Any] | None = None,
    source_text: str = "",
    web_search_enabled: bool = True,
    model: str = "gpt-5.4-mini",
    refresh: bool = False,
    include_summary: bool = False,
    summary_max_tokens: int = TITLE_SUBTITLE_SUMMARY_TOKEN_BUDGET_DEFAULT,
    refresh_summary: bool = False,
    run_id: str = "",
    now: str | None = None,
    fetcher: Any | None = None,
    llm_resolver: Any | None = None,
    llm_toolless_resolver: Any | None = None,
    summary_resolver: Any | None = None,
    summary_procedure_alias: str = SUMMARY_PROCEDURE_ALIAS_TITLE_SUBTITLE_RESOLVE,
    identifier_prepass: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve original title/subtitle metadata for a Reference-like record.

    Keep title/subtitle resolution straightforward and provenance-marked without
    hidden subtitle rewrite/suppression branches.
    """
    now = now or _now()
    fetcher = fetcher or _fetch_url_text
    llm_resolver = llm_resolver or generate_title_subtitle_with_web_search
    llm_toolless_resolver = llm_toolless_resolver or generate_title_subtitle_without_web_search
    summary_resolver = summary_resolver or generate_outcome_summary
    reference = reference or {}
    catalog_entry = catalog_entry or {}
    sidecar = sidecar or {}
    warnings: list[str] = []
    identifier_prepass = (
        identifier_prepass
        if isinstance(identifier_prepass, dict)
        else _run_identifier_prepass(reference=reference, catalog_entry=catalog_entry)
    )
    if identifier_prepass.get("status") == "failed":
        failure = identifier_prepass.get("failureReason") or "identifier prepass failed"
        warnings.append(f"identifier prepass failed: {failure}")
        return _title_subtitle_resolution(
            status="blocked",
            title="",
            subtitle="",
            title_mode="unresolved",
            subtitle_mode="unresolved",
            source="identifier_prepass",
            model=model,
            web_search_used=False,
            source_urls=[],
            rationale="Identifier prepass failed; title/subtitle and summary generation were blocked.",
            summary="",
            summary_resolution=_summary_resolution(
                summary="",
                summary_token_budget=summary_max_tokens,
                model=model,
                source="identifier_prepass_failed",
                source_urls=[],
                run_id=run_id,
                resolved_at=now,
                rationale=failure,
                prompt_version="",
            ) if include_summary else {},
            run_id=run_id,
            resolved_at=now,
            warnings=warnings,
            identifier_prepass=identifier_prepass,
        )
    summary_budget = normalize_title_subtitle_summary_budget(summary_max_tokens)
    local = _title_subtitle_from_local(reference=reference, catalog_entry=catalog_entry, sidecar=sidecar)
    local_catalog_title_without_subtitle = bool(
        local.get("title")
        and not _normalize_subtitle_candidate(local.get("subtitle"))
        and local.get("source") == "catalog"
    )
    existing_reference_title = _normalize_reference_title_candidate(reference.get("title"))
    title = local.get("title") if refresh or not existing_reference_title else existing_reference_title
    subtitle = "" if refresh else _normalize_subtitle_candidate(local.get("subtitle"))
    local_summary = _normalize_outcome_summary_candidate(local.get("summary"))
    summary = "" if (refresh or refresh_summary) else local_summary
    title_mode = local.get("titleMode") if title else None
    subtitle_mode = local.get("subtitleMode") if subtitle else None
    source_urls: list[str] = []
    source = local.get("source") or "unresolved"
    rationale = local.get("rationale") or ""
    summary_source = local.get("summarySource") or source
    summary_rationale = local.get("summaryRationale") or ("Resolved from local metadata summary." if summary else "")
    summary_prompt_version = ""

    if title and subtitle and (summary if include_summary else True) and not refresh and not refresh_summary:
        return _title_subtitle_resolution(
            status="resolved",
            title=title,
            subtitle=subtitle,
            title_mode=title_mode or "original_metadata",
            subtitle_mode=subtitle_mode or "original_metadata",
            source=source,
            model=model,
            web_search_used=False,
            source_urls=source_urls,
            rationale=rationale or "Title and subtitle were available from local metadata.",
            summary=summary if include_summary else "",
            summary_resolution=_summary_resolution(
                summary=summary,
                summary_token_budget=summary_budget,
                model=model,
                source=summary_source or "local_metadata",
                source_urls=source_urls,
                run_id=run_id,
                resolved_at=now,
                rationale=summary_rationale,
                prompt_version=TITLE_SUBTITLE_SUMMARY_PROMPT_VERSION if summary_source == "llm_outcome_summary" else "",
            ) if include_summary else {},
            run_id=run_id,
            resolved_at=now,
            warnings=warnings,
            identifier_prepass=identifier_prepass,
        )

    deterministic = _resolve_title_subtitle_deterministic(
        reference=reference,
        catalog_entry=catalog_entry,
        source_text=source_text,
        fetcher=fetcher,
    )
    if deterministic.get("sourceUrls"):
        source_urls.extend(deterministic["sourceUrls"])
    if not title and deterministic.get("title"):
        title = deterministic["title"]
        title_mode = deterministic.get("titleMode") or "original_web_metadata"
    if not subtitle and deterministic.get("subtitle"):
        subtitle = _clean_text(deterministic["subtitle"])
        subtitle_mode = deterministic.get("subtitleMode") or "original_web_metadata"
    if include_summary and not summary and deterministic.get("summary"):
        summary = _normalize_outcome_summary_candidate(deterministic.get("summary"))
        summary_source = deterministic.get("summarySource") or deterministic.get("source") or summary_source
        summary_rationale = deterministic.get("summaryRationale") or deterministic.get("rationale") or summary_rationale
    if deterministic.get("rationale"):
        rationale = deterministic["rationale"]
        source = deterministic.get("source") or source

    deterministic_subtitle_issue = _non_generated_subtitle_quality_issue(
        subtitle,
        subtitle_mode=subtitle_mode or "",
    )
    if deterministic_subtitle_issue:
        warnings.append(f"subtitle candidate rejected: {deterministic_subtitle_issue}")
        subtitle = ""
        subtitle_mode = "unresolved"

    if title and subtitle and (summary if include_summary else True):
        return _title_subtitle_resolution(
            status="resolved",
            title=title,
            subtitle=subtitle,
            title_mode=title_mode or "original_web_metadata",
            subtitle_mode=subtitle_mode or "original_web_metadata",
            source=source or "deterministic_metadata",
            model=model,
            web_search_used=False,
            source_urls=source_urls,
            rationale=rationale or "Title and subtitle were resolved deterministically.",
            summary=summary if include_summary else "",
            summary_resolution=_summary_resolution(
                summary=summary,
                summary_token_budget=summary_budget,
                model=model,
                source=summary_source or source or "deterministic_metadata",
                source_urls=source_urls,
                run_id=run_id,
                resolved_at=now,
                rationale=summary_rationale or "Resolved summary from deterministic metadata.",
                prompt_version="",
            ) if include_summary else {},
            run_id=run_id,
            resolved_at=now,
            warnings=warnings,
            identifier_prepass=identifier_prepass,
        )

    if not subtitle and not web_search_enabled and not (local_catalog_title_without_subtitle and title):
        try:
            llm = llm_toolless_resolver(
                reference=reference,
                catalog_entry=catalog_entry,
                source_text=source_text,
                known_title=title or "",
                known_subtitle=subtitle or "",
                model=model,
            )
            if llm.get("source_urls"):
                source_urls.extend(str(url) for url in llm.get("source_urls") or [] if str(url or "").strip())
            if not title and llm.get("title"):
                title = _clean_text(llm.get("title"))
                title_mode = _title_subtitle_mode(llm.get("title_mode"), default="original_web_metadata")
            if not subtitle and llm.get("subtitle"):
                candidate_subtitle = _clean_text(llm.get("subtitle"))
                candidate_subtitle_mode = _title_subtitle_mode(llm.get("subtitle_mode"), default="generated")
                if candidate_subtitle:
                    subtitle = candidate_subtitle
                    subtitle_mode = candidate_subtitle_mode
            rationale = _clean_text(llm.get("rationale")) or rationale
            source = "llm_no_web_search"
        except Exception as exc:
            warnings.append(f"title/subtitle tool-less LLM resolution failed: {exc}")

    if web_search_enabled and not subtitle and not (local_catalog_title_without_subtitle and title):
        try:
            llm = llm_resolver(
                reference=reference,
                catalog_entry=catalog_entry,
                source_text=source_text,
                known_title=title or "",
                known_subtitle=subtitle or "",
                model=model,
            )
            if llm.get("source_urls"):
                source_urls.extend(str(url) for url in llm.get("source_urls") or [] if str(url or "").strip())
            if not title and llm.get("title"):
                title = _clean_text(llm.get("title"))
                title_mode = _title_subtitle_mode(llm.get("title_mode"), default="original_web_metadata")
            if not subtitle and llm.get("subtitle"):
                candidate_subtitle = _clean_text(llm.get("subtitle"))
                candidate_subtitle_mode = _title_subtitle_mode(llm.get("subtitle_mode"), default="generated")
                if candidate_subtitle:
                    subtitle = candidate_subtitle
                    subtitle_mode = candidate_subtitle_mode
            rationale = _clean_text(llm.get("rationale")) or rationale
            source = "llm_web_search"
        except Exception as exc:
            warnings.append(f"title/subtitle web+LLM resolution failed: {exc}")

    title = _normalize_reference_title_candidate(title)
    if _placeholder_title(title):
        title = ""
        title_mode = "unresolved"
    subtitle = _clean_text(subtitle)
    if _placeholder_title(subtitle) and _title_subtitle_mode(subtitle_mode or "", default="") != "generated_fallback":
        subtitle = ""
        subtitle_mode = "unresolved"
    subtitle_quality_issue = _generated_subtitle_quality_issue(
        subtitle,
        subtitle_mode=subtitle_mode or "",
    )
    if subtitle_quality_issue:
        warnings.append(f"generated subtitle rejected: {subtitle_quality_issue}")
        subtitle = ""
        subtitle_mode = "unresolved"

    if include_summary and not summary:
        try:
            summary_result = summary_resolver(
                source_text,
                reference=reference,
                title=title,
                subtitle=subtitle,
                max_tokens=summary_budget,
                model=model,
                procedure_alias=summary_procedure_alias,
            )
            if isinstance(summary_result, str):
                summary_text = summary_result
                summary_prompt = TITLE_SUBTITLE_SUMMARY_PROMPT_VERSION
            else:
                summary_text = (summary_result or {}).get("summary_text")
                summary_prompt = _clean_text((summary_result or {}).get("prompt_version")) or TITLE_SUBTITLE_SUMMARY_PROMPT_VERSION
            summary = _normalize_outcome_summary_candidate(summary_text)
            if summary:
                summary_source = "llm_outcome_summary"
                summary_rationale = "Generated outcome-focused summary from source text."
                summary_prompt_version = summary_prompt
        except Exception as exc:
            warnings.append(f"summary generation failed: {exc}")

    summary_resolution = _summary_resolution(
        summary=summary if include_summary else "",
        summary_token_budget=summary_budget,
        model=model,
        source=summary_source if summary else "unresolved",
        source_urls=source_urls,
        run_id=run_id,
        resolved_at=now,
        rationale=summary_rationale if summary else "No reliable summary was produced.",
        prompt_version=summary_prompt_version if summary_source == "llm_outcome_summary" else "",
    ) if include_summary else {}

    status = "resolved" if title else "unresolved"
    return _title_subtitle_resolution(
        status=status,
        title=title or "",
        subtitle=subtitle or "",
        title_mode=title_mode or ("original_web_metadata" if title else "unresolved"),
        subtitle_mode=subtitle_mode or ("unresolved" if not subtitle else "generated"),
        source=source if status == "resolved" else "unresolved",
        model=model,
        web_search_used=bool(web_search_enabled and source == "llm_web_search"),
        source_urls=source_urls,
        rationale=rationale or ("Resolved title/subtitle." if status == "resolved" else "No reliable title candidate was found."),
        summary=summary if include_summary else "",
        summary_resolution=summary_resolution,
        run_id=run_id,
        resolved_at=now,
        warnings=warnings,
        identifier_prepass=identifier_prepass,
    )


def build_reference_title_subtitle_plan(
    *,
    reference: dict[str, Any],
    catalog_entry: dict[str, Any] | None = None,
    sidecar: dict[str, Any] | None = None,
    source_text: str = "",
    web_search_enabled: bool = True,
    model: str = "gpt-5.4-mini",
    refresh: bool = False,
    include_summary: bool = False,
    summary_max_tokens: int = TITLE_SUBTITLE_SUMMARY_TOKEN_BUDGET_DEFAULT,
    refresh_summary: bool = False,
    summary_procedure_alias: str = SUMMARY_PROCEDURE_ALIAS_TITLE_SUBTITLE_RESOLVE,
    run_id: str = "",
    now: str | None = None,
    semantic_client: PapyrusSemanticClient | None = None,
) -> dict[str, Any]:
    now = now or _now()
    reference = _require_reference(reference)
    run_id = run_id or f"title-subtitle-{_hash_short([reference.get('id'), now])}"
    metadata = _load_reference_metadata_payload(reference)
    identifier_prepass = _run_identifier_prepass(reference=reference, catalog_entry=catalog_entry or {})
    if identifier_prepass.get("status") == "failed":
        return {
            "kind": "reference.title-subtitle.plan",
            "action": "blocked",
            "reference": _reference_summary(reference),
            "identifierPrepass": identifier_prepass,
            "failureReason": identifier_prepass.get("failureReason") or "identifier prepass failed",
            "records": [],
            "warnings": [f"identifier prepass failed: {identifier_prepass.get('failureReason') or 'unknown error'}"],
        }
    existing_title = _normalize_reference_title_candidate(metadata.get("title") or reference.get("title"))
    existing_subtitle_raw = _normalize_subtitle_candidate(metadata.get("subtitle") or reference.get("subtitle"))
    existing_resolution = metadata.get("title_subtitle_resolution") if isinstance(metadata.get("title_subtitle_resolution"), dict) else {}
    existing_subtitle_mode = _clean_text(existing_resolution.get("subtitle_mode")) or "existing_reference_metadata"
    existing_subtitle_issue = _subtitle_candidate_quality_issue(
        existing_subtitle_raw,
        subtitle_mode=existing_subtitle_mode,
    )
    existing_subtitle = "" if existing_subtitle_issue else existing_subtitle_raw
    existing_summary = _normalize_outcome_summary_candidate(metadata.get("summary"))
    if existing_title and existing_subtitle and ((existing_summary and include_summary) or not include_summary) and not refresh and not refresh_summary:
        return {
            "kind": "reference.title-subtitle.plan",
            "action": "noop",
            "reference": _reference_summary(reference),
            "title": existing_title,
            "subtitle": existing_subtitle,
            "summary": existing_summary if include_summary else "",
            "identifierPrepass": identifier_prepass,
            "resolution": _title_subtitle_resolution(
                status="resolved",
                title=existing_title,
                subtitle=existing_subtitle,
                title_mode="existing_reference",
                subtitle_mode="existing_reference_metadata",
                source="existing_reference_metadata",
                model=model,
                web_search_used=False,
                source_urls=[],
                rationale="Reference already has title and subtitle.",
                summary=existing_summary if include_summary else "",
                summary_resolution=_summary_resolution(
                    summary=existing_summary if include_summary else "",
                    summary_token_budget=normalize_title_subtitle_summary_budget(summary_max_tokens),
                    model=model,
                    source="existing_reference_metadata",
                    source_urls=[],
                    run_id=run_id,
                    resolved_at=now,
                    rationale="Reference already has a metadata summary.",
                    prompt_version="",
                ) if include_summary else {},
                run_id=run_id,
                resolved_at=now,
                warnings=[],
                identifier_prepass=identifier_prepass,
            ),
            "records": [],
            "warnings": [],
        }
    resolution = resolve_reference_title_subtitle(
        reference=reference,
        catalog_entry=catalog_entry,
        sidecar=sidecar,
        source_text=source_text,
        web_search_enabled=web_search_enabled,
        model=model,
        refresh=refresh,
        include_summary=include_summary,
        summary_max_tokens=summary_max_tokens,
        refresh_summary=refresh_summary,
        summary_procedure_alias=summary_procedure_alias,
        run_id=run_id,
        now=now,
        identifier_prepass=identifier_prepass,
    )
    if resolution["status"] != "resolved" or not resolution.get("title"):
        action = "blocked" if resolution.get("status") == "blocked" else "unresolved"
        return {
            "kind": "reference.title-subtitle.plan",
            "action": action,
            "reference": _reference_summary(reference),
            "identifierPrepass": resolution.get("identifierPrepass") or identifier_prepass,
            "resolution": resolution,
            "records": [],
            "warnings": resolution.get("warnings") or [],
        }
    identifier_metadata = _identifier_metadata_update(
        metadata=metadata,
        identifier_prepass=resolution.get("identifierPrepass") or identifier_prepass,
    )
    next_metadata = {
        **metadata,
        "title": resolution["title"],
        "subtitle": resolution.get("subtitle") or "",
        "title_subtitle_resolution": _title_subtitle_provenance(resolution),
        **identifier_metadata,
    }
    if include_summary:
        next_metadata["summary"] = resolution.get("summary") or existing_summary or ""
        next_metadata["summary_resolution"] = _summary_resolution_provenance(resolution)
    summary_changed = (
        include_summary
        and (
            refresh
            or refresh_summary
            or existing_summary != (resolution.get("summary") or "")
            or metadata.get("summary_resolution") != next_metadata.get("summary_resolution")
        )
    )
    metadata_changed = (
        refresh
        or not existing_title
        or existing_title != resolution["title"]
        or existing_subtitle != (resolution.get("subtitle") or "")
        or metadata.get("title_subtitle_resolution") != next_metadata.get("title_subtitle_resolution")
        or summary_changed
        or metadata != next_metadata
    )
    records = []
    if metadata_changed:
        next_metadata["updatedAt"] = now
    metadata_attachment = _model_attachment(
        owner_kind="reference",
        owner_id=reference["id"],
        role="metadata",
        sort_key="metadata",
        filename="metadata.json",
        media_type="application/json",
        content=next_metadata,
        import_run_id=reference.get("importRunId"),
        now=now,
    )
    if metadata_changed:
        records.append({"modelName": "ModelAttachment", "action": "create", "input": metadata_attachment["record"], "body": metadata_attachment["body"]})
    return {
        "kind": "reference.title-subtitle.plan",
        "action": "update" if records else "noop",
        "reference": _reference_summary(reference),
        "title": resolution["title"],
        "subtitle": next_metadata.get("subtitle") or "",
        "summary": next_metadata.get("summary") or "",
        "identifierPrepass": resolution.get("identifierPrepass") or identifier_prepass,
        "resolution": resolution,
        "records": records,
        "warnings": resolution.get("warnings") or [],
    }


def reference_title_subtitle_resolve(
    *,
    reference_id: str,
    model: str = "gpt-5.4-mini",
    apply: bool = False,
    refresh: bool = False,
    summary: bool = False,
    summary_max_tokens: int = TITLE_SUBTITLE_SUMMARY_TOKEN_BUDGET_DEFAULT,
    refresh_summary: bool = False,
    web_search: bool = True,
    summary_procedure_alias: str = SUMMARY_PROCEDURE_ALIAS_TITLE_SUBTITLE_RESOLVE,
    persist_local_metadata: bool = True,
    vector_sync: bool = True,
    source_text: str = "",
    source_text_file: str = "",
) -> dict[str, Any]:
    semantic = _semantic_client()
    reference = _resolve_reference(semantic, reference_id)
    source = _resolve_source_text(reference, source_text=source_text, source_text_file=source_text_file) if (source_text or source_text_file or summary) else ""
    sidecar = _read_reference_sidecar(reference)
    catalog_entry = _read_reference_catalog_entry(reference)
    plan = build_reference_title_subtitle_plan(
        reference=reference,
        catalog_entry=catalog_entry,
        sidecar=sidecar,
        source_text=source,
        web_search_enabled=web_search,
        model=model,
        refresh=refresh,
        include_summary=summary,
        summary_max_tokens=summary_max_tokens,
        refresh_summary=refresh_summary,
        summary_procedure_alias=summary_procedure_alias,
        semantic_client=semantic,
    )
    result = _apply_plan_if_requested(plan, apply=apply, actor_label=TITLE_SUBTITLE_SOURCE, reason="references title-subtitle resolve")
    result["localMetadata"] = build_title_subtitle_local_metadata_plan(reference=reference, resolution=plan.get("resolution") or {})
    if apply and persist_local_metadata and plan.get("resolution", {}).get("status") == "resolved":
        result["localMetadata"] = apply_title_subtitle_local_metadata(reference=reference, resolution=plan["resolution"])
    elif apply and not persist_local_metadata:
        result["localMetadata"] = {**result["localMetadata"], "skipped": True, "reason": "local_metadata_persistence_disabled"}
    return _attach_title_subtitle_surface_statuses(
        result,
        references=[reference],
        apply=apply,
        vector_sync=vector_sync,
    )


def reference_title_subtitle_batch(
    *,
    corpus_key: str,
    max_count: int = 10,
    status: str = "all",
    model: str = "gpt-5.4-mini",
    apply: bool = False,
    refresh: bool = False,
    summary: bool = False,
    summary_max_tokens: int = TITLE_SUBTITLE_SUMMARY_TOKEN_BUDGET_DEFAULT,
    refresh_summary: bool = False,
    only_missing: bool = True,
    web_search: bool = True,
    persist_local_metadata: bool = True,
    vector_sync: bool = True,
    scan_limit: int = 1000,
) -> dict[str, Any]:
    references = _select_references_for_curation_batch(
        corpus_key=corpus_key,
        status=status,
        max_count=max_count,
        scan_limit=scan_limit,
    )
    worker_count = TITLE_SUBTITLE_BATCH_WORKERS

    def _process_reference(reference: dict[str, Any]) -> dict[str, Any]:
        identifier_prepass = _run_identifier_prepass(reference=reference, catalog_entry={})
        if identifier_prepass.get("status") == "failed":
            return {
                "kind": "reference.title-subtitle.resolve",
                "action": "blocked",
                "reference": _reference_summary(reference),
                "identifierPrepass": identifier_prepass,
                "failureReason": identifier_prepass.get("failureReason") or "identifier prepass failed",
                "apply": False,
            }
        metadata = _load_reference_metadata_payload(reference)
        has_title = bool(_normalize_reference_title_candidate(metadata.get("title") or reference.get("title")))
        subtitle_candidate = _normalize_subtitle_candidate(metadata.get("subtitle") or reference.get("subtitle"))
        subtitle_resolution = metadata.get("title_subtitle_resolution") if isinstance(metadata.get("title_subtitle_resolution"), dict) else {}
        subtitle_mode = _clean_text(subtitle_resolution.get("subtitle_mode")) or "existing_reference_metadata"
        has_subtitle = bool(subtitle_candidate) and not _subtitle_candidate_quality_issue(
            subtitle_candidate,
            subtitle_mode=subtitle_mode,
        )
        has_summary = bool(_normalize_outcome_summary_candidate(metadata.get("summary")))
        if only_missing and has_title and has_subtitle and (has_summary if summary else True) and not refresh and not refresh_summary:
            return {
                "kind": "reference.title-subtitle.resolve",
                "action": "noop",
                "reference": _reference_summary(reference),
                "title": _normalize_reference_title_candidate(reference.get("title")),
                "subtitle": _normalize_subtitle_candidate(metadata.get("subtitle") or reference.get("subtitle")),
                "summary": _normalize_outcome_summary_candidate(metadata.get("summary")),
                "identifierPrepass": identifier_prepass,
                "apply": False,
            }
        try:
            item = reference_title_subtitle_resolve(
                reference_id=reference["id"],
                model=model,
                apply=apply,
                refresh=refresh,
                summary=summary,
                summary_max_tokens=summary_max_tokens,
                refresh_summary=refresh_summary,
                web_search=web_search,
                summary_procedure_alias=SUMMARY_PROCEDURE_ALIAS_TITLE_SUBTITLE_BATCH,
                persist_local_metadata=persist_local_metadata,
                vector_sync=False,
            )
            item["identifierPrepass"] = item.get("identifierPrepass") or identifier_prepass
            return item
        except Exception as exc:
            return {
                "kind": "reference.title-subtitle.resolve",
                "action": "error",
                "reference": _reference_summary(reference),
                "identifierPrepass": identifier_prepass,
                "error": str(exc),
                "apply": False,
            }

    items_by_index: dict[int, dict[str, Any]] = {}
    if worker_count == 1 or len(references) <= 1:
        for index, reference in enumerate(references):
            items_by_index[index] = _process_reference(reference)
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(_process_reference, reference): index
                for index, reference in enumerate(references)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    items_by_index[index] = future.result()
                except Exception as exc:  # pragma: no cover - defensive worker guard
                    reference = references[index]
                    items_by_index[index] = {
                        "kind": "reference.title-subtitle.resolve",
                        "action": "error",
                        "reference": _reference_summary(reference),
                        "identifierPrepass": {"status": "failed", "failureReason": "worker execution failed"},
                        "error": str(exc),
                        "apply": False,
                    }
    items = [items_by_index[index] for index in range(len(references))]
    result = _title_subtitle_batch_result(
        kind="reference.title-subtitle.batch",
        corpus_key=corpus_key,
        status=status,
        model=model,
        apply=apply,
        web_search=web_search,
        items=items,
    )
    if apply and vector_sync:
        changed_references = [
            reference for reference, item in zip(references, items)
            if item.get("action") == "update" and item.get("apply")
        ]
        vector_result = _sync_reference_vectors(changed_references)
        result["vectorSync"] = vector_result
        _apply_vector_sync_results_to_items(items, vector_result)
        if vector_result.get("failed"):
            result["partialFailure"] = True
            result.setdefault("warnings", []).append(vector_result["message"])
    else:
        result["vectorSync"] = {
            "resultsByLineageId": {},
            "resultsByReferenceId": {},
            "skippedReason": "vector_sync_disabled" if not vector_sync else "not_applied",
        }
        _apply_vector_sync_results_to_items(items, result["vectorSync"])
    return result


def _title_subtitle_batch_result(
    *,
    kind: str,
    corpus_key: str,
    status: str,
    model: str,
    apply: bool,
    web_search: bool,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "corpusKey": corpus_key,
        "status": status or "all",
        "model": model,
        "apply": apply,
        "webSearch": web_search,
        "count": len(items),
        "updated": sum(1 for item in items if item.get("action") == "update"),
        "summaryGenerated": sum(
            1 for item in items
            if item.get("action") == "update" and _clean_text((item.get("resolution") or {}).get("summary"))
        ),
        "unresolved": sum(1 for item in items if item.get("action") == "unresolved"),
        "blocked": sum(1 for item in items if item.get("action") == "blocked"),
        "noop": sum(1 for item in items if item.get("action") == "noop"),
        "errors": sum(1 for item in items if item.get("action") == "error"),
        "items": items,
    }


def enrich_reference_catalog_title_subtitle(
    *,
    catalog: dict[str, Any],
    web_search: bool = True,
    model: str = "gpt-5.4-mini",
    summary: bool = False,
    summary_max_tokens: int = TITLE_SUBTITLE_SUMMARY_TOKEN_BUDGET_DEFAULT,
    refresh_summary: bool = False,
    only_missing: bool = True,
    max_count: int = 0,
) -> dict[str, Any]:
    items_value = catalog.get("items") if isinstance(catalog, dict) else []
    entries = _catalog_entries(items_value)
    entries.sort(key=lambda entry: _catalog_entry_chrono_key(entry[1]), reverse=True)
    output_items = items_value.copy() if isinstance(items_value, list) else dict(items_value or {})
    results = []
    processed = 0
    for key, item in entries:
        if max_count and processed >= max_count:
            break
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        reference = _reference_from_catalog_item(item)
        identifier_prepass = _run_identifier_prepass(reference=reference, catalog_entry=item)
        if identifier_prepass.get("status") == "failed":
            processed += 1
            results.append({
                "action": "blocked",
                "itemKey": key,
                "identifierPrepass": identifier_prepass,
                "failureReason": identifier_prepass.get("failureReason") or "identifier prepass failed",
            })
            continue
        has_durable_title = bool(_clean_text(item.get("title")) and _clean_text(metadata.get("title")))
        has_durable_subtitle = bool(_normalize_subtitle_candidate(item.get("subtitle")) and _normalize_subtitle_candidate(metadata.get("subtitle")))
        has_durable_summary = bool(_normalize_outcome_summary_candidate(item.get("summary")) and _normalize_outcome_summary_candidate(metadata.get("summary")))
        if only_missing and has_durable_title and has_durable_subtitle and (has_durable_summary if summary else True) and not refresh_summary:
            results.append({
                "action": "noop",
                "itemKey": key,
                "title": item.get("title"),
                "subtitle": item.get("subtitle") or metadata.get("subtitle"),
                "summary": item.get("summary") or metadata.get("summary"),
                "identifierPrepass": identifier_prepass,
            })
            continue
        processed += 1
        resolution = resolve_reference_title_subtitle(
            reference=reference,
            catalog_entry=item,
            sidecar={},
            source_text=_catalog_source_text(item),
            web_search_enabled=web_search,
            model=model,
            include_summary=summary,
            summary_max_tokens=summary_max_tokens,
            refresh_summary=refresh_summary,
            summary_procedure_alias=SUMMARY_PROCEDURE_ALIAS_TITLE_SUBTITLE_ENRICH_CATALOG,
            identifier_prepass=identifier_prepass,
        )
        if resolution["status"] != "resolved":
            action = "blocked" if resolution.get("status") == "blocked" else "unresolved"
            results.append({"action": action, "itemKey": key, "resolution": resolution, "identifierPrepass": identifier_prepass})
            continue
        enriched = apply_title_subtitle_to_catalog_item(item, resolution=resolution)
        if isinstance(output_items, list):
            output_items[int(key)] = enriched
        else:
            output_items[key] = enriched
        results.append({"action": "update", "itemKey": key, "resolution": resolution, "identifierPrepass": identifier_prepass})
    output = {
        **catalog,
        "items": output_items,
        "title_subtitle_enrichment": {
            "tool": TITLE_SUBTITLE_SOURCE,
            "model": model,
            "web_search": web_search,
            "summary": summary,
            "summary_max_tokens": summary_max_tokens,
            "updated_at": _now(),
            "processed": processed,
            "updated": sum(1 for item in results if item.get("action") == "update"),
            "summary_generated": sum(
                1 for item in results
                if item.get("action") == "update" and _clean_text((item.get("resolution") or {}).get("summary"))
            ),
            "unresolved": sum(1 for item in results if item.get("action") == "unresolved"),
            "blocked": sum(1 for item in results if item.get("action") == "blocked"),
            "noop": sum(1 for item in results if item.get("action") == "noop"),
        },
    }
    return {"kind": "reference.title-subtitle.enrich-catalog", "catalog": output, "items": results, **output["title_subtitle_enrichment"]}


def reference_title_subtitle_enrich_catalog_file(
    *,
    catalog_path: str,
    output_path: str,
    web_search: bool = True,
    model: str = "gpt-5.4-mini",
    summary: bool = False,
    summary_max_tokens: int = TITLE_SUBTITLE_SUMMARY_TOKEN_BUDGET_DEFAULT,
    refresh_summary: bool = False,
    only_missing: bool = True,
    max_count: int = 0,
) -> dict[str, Any]:
    path = Path(catalog_path).expanduser()
    catalog = json.loads(path.read_text(encoding="utf-8"))
    result = enrich_reference_catalog_title_subtitle(
        catalog=catalog,
        web_search=web_search,
        model=model,
        summary=summary,
        summary_max_tokens=summary_max_tokens,
        refresh_summary=refresh_summary,
        only_missing=only_missing,
        max_count=max_count,
    )
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result["catalog"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {key: value for key, value in result.items() if key != "catalog"} | {"outputPath": str(output)}


def reference_quality_set(
    *,
    reference_id: str,
    rating: int,
    note: str = "",
    actor_label: str = "papyrus",
    apply: bool = False,
    refresh: bool = False,
    persist_local_metadata: bool = True,
) -> dict[str, Any]:
    semantic = _semantic_client()
    reference = _resolve_reference(semantic, reference_id)
    plan = build_reference_quality_plan(
        reference=reference,
        rating=rating,
        note=note,
        actor_label=actor_label,
        refresh=refresh,
        semantic_client=semantic,
    )
    local_metadata_plan = build_quality_local_metadata_plan(
        reference=reference,
        rating=rating,
        note=note,
        actor_label=actor_label,
    )
    result = _apply_plan_if_requested(plan, apply=apply, actor_label=actor_label, reason="references quality set")
    result["localMetadata"] = local_metadata_plan
    if apply and persist_local_metadata:
        local_result = apply_quality_local_metadata(reference=reference, rating=rating, note=note, actor_label=actor_label)
        result["localMetadata"] = local_result
        if local_result.get("errors"):
            result.setdefault("warnings", []).append(f"Quality local metadata persistence had {len(local_result['errors'])} error(s).")
    elif apply and not persist_local_metadata:
        result["localMetadata"] = {**local_metadata_plan, "skipped": True, "reason": "local_metadata_persistence_disabled"}
    return result


def reference_quality_assess(
    *,
    reference_id: str,
    model: str = "gpt-5.4-mini",
    apply: bool = False,
    refresh: bool = False,
    persist_local_metadata: bool = True,
    source_text: str = "",
    source_text_file: str = "",
) -> dict[str, Any]:
    semantic = _semantic_client()
    reference = _resolve_reference(semantic, reference_id)
    existing = _current_relations(
        semantic.list_outgoing("reference", reference["lineageId"])["relations"],
        QUALITY_RELATION_TYPE_KEY,
    )
    if existing and not refresh:
        quality = _quality_from_relation(existing[0])
        return {
            "kind": "reference.quality.assess",
            "action": "noop",
            "reference": _reference_summary(reference),
            "quality": quality,
            "existingRelationId": existing[0].get("id"),
            "warnings": [],
            "apply": False,
        }
    source = _resolve_source_text(reference, source_text=source_text, source_text_file=source_text_file)
    doctrine_context = load_publication_doctrine_context()
    assessment = generate_quality_assessment(
        source,
        reference=reference,
        model=model,
        doctrine_context=doctrine_context,
    )
    note = _quality_assessment_note(assessment)
    plan = build_reference_quality_plan(
        reference=reference,
        rating=assessment["rating"],
        note=note,
        actor_label=QUALITY_ASSESSMENT_SOURCE,
        source=QUALITY_ASSESSMENT_SOURCE,
        refresh=refresh,
        semantic_client=semantic,
    )
    plan["kind"] = "reference.quality.assess"
    plan["assessment"] = assessment
    plan["model"] = model
    plan["promptVersion"] = QUALITY_ASSESSMENT_PROMPT_VERSION
    plan["doctrineContext"] = doctrine_summary_metadata(doctrine_context)
    result = _apply_plan_if_requested(plan, apply=apply, actor_label=QUALITY_ASSESSMENT_SOURCE, reason="references quality assess")
    result = _with_doctrine_warnings(result, doctrine_context)
    result["localMetadata"] = build_quality_local_metadata_plan(
        reference=reference,
        rating=assessment["rating"],
        note=note,
        actor_label=QUALITY_ASSESSMENT_SOURCE,
    )
    if apply and persist_local_metadata:
        local_result = apply_quality_local_metadata(
            reference=reference,
            rating=assessment["rating"],
            note=note,
            actor_label=QUALITY_ASSESSMENT_SOURCE,
        )
        result["localMetadata"] = local_result
        if local_result.get("errors"):
            result.setdefault("warnings", []).append(f"Quality local metadata persistence had {len(local_result['errors'])} error(s).")
    elif apply and not persist_local_metadata:
        result["localMetadata"] = {**result["localMetadata"], "skipped": True, "reason": "local_metadata_persistence_disabled"}
    return result


def reference_quality_assess_batch(
    *,
    corpus_key: str,
    max_count: int = 10,
    status: str = "accepted",
    model: str = "gpt-5.4-mini",
    apply: bool = False,
    refresh: bool = False,
    only_missing: bool = True,
    persist_local_metadata: bool = True,
    scan_limit: int = 1000,
) -> dict[str, Any]:
    semantic = _semantic_client()
    references = _select_references_for_curation_batch(
        corpus_key=corpus_key,
        status=status,
        max_count=max_count,
        scan_limit=scan_limit,
    )
    doctrine_context = load_publication_doctrine_context()
    items = []
    rating_counts: dict[str, int] = {}
    for reference in references:
        existing = _current_relations(
            semantic.list_outgoing("reference", reference["lineageId"])["relations"],
            QUALITY_RELATION_TYPE_KEY,
        )
        if existing and only_missing and not refresh:
            quality = _quality_from_relation(existing[0])
            item = {
                "kind": "reference.quality.assess",
                "action": "noop",
                "reference": _reference_summary(reference),
                "quality": quality,
                "existingRelationId": existing[0].get("id"),
                "warnings": [],
                "apply": False,
            }
            items.append(item)
            if quality and quality.get("rating") is not None:
                key = str(quality["rating"])
                rating_counts[key] = rating_counts.get(key, 0) + 1
            continue
        try:
            source = _resolve_source_text(reference)
            assessment = generate_quality_assessment(
                source,
                reference=reference,
                model=model,
                doctrine_context=doctrine_context,
            )
            note = _quality_assessment_note(assessment)
            plan = build_reference_quality_plan(
                reference=reference,
                rating=assessment["rating"],
                note=note,
                actor_label=QUALITY_ASSESSMENT_SOURCE,
                source=QUALITY_ASSESSMENT_SOURCE,
                refresh=refresh or bool(existing and not only_missing),
                semantic_client=semantic,
            )
            plan["kind"] = "reference.quality.assess"
            plan["assessment"] = assessment
            plan["model"] = model
            plan["promptVersion"] = QUALITY_ASSESSMENT_PROMPT_VERSION
            plan["doctrineContext"] = doctrine_summary_metadata(doctrine_context)
            item = _apply_plan_if_requested(plan, apply=apply, actor_label=QUALITY_ASSESSMENT_SOURCE, reason="references quality assess-batch")
            item = _with_doctrine_warnings(item, doctrine_context)
            item["localMetadata"] = build_quality_local_metadata_plan(
                reference=reference,
                rating=assessment["rating"],
                note=note,
                actor_label=QUALITY_ASSESSMENT_SOURCE,
            )
            if apply and persist_local_metadata:
                local_result = apply_quality_local_metadata(
                    reference=reference,
                    rating=assessment["rating"],
                    note=note,
                    actor_label=QUALITY_ASSESSMENT_SOURCE,
                )
                item["localMetadata"] = local_result
                if local_result.get("errors"):
                    item.setdefault("warnings", []).append(f"Quality local metadata persistence had {len(local_result['errors'])} error(s).")
            elif apply and not persist_local_metadata:
                item["localMetadata"] = {**item["localMetadata"], "skipped": True, "reason": "local_metadata_persistence_disabled"}
            items.append(item)
            key = str(assessment["rating"])
            rating_counts[key] = rating_counts.get(key, 0) + 1
        except Exception as exc:
            items.append({
                "kind": "reference.quality.assess",
                "action": "error",
                "reference": _reference_summary(reference),
                "error": str(exc),
                "warnings": [],
                "apply": False,
            })
    return {
        "kind": "reference.quality.assess-batch",
        "corpusKey": corpus_key,
        "status": status,
        "model": model,
        "apply": apply,
        "doctrineContext": doctrine_summary_metadata(doctrine_context),
        "warnings": list(doctrine_context.get("warnings") or []),
        "count": len(items),
        "created": sum(1 for item in items if item.get("action") == "create"),
        "noop": sum(1 for item in items if item.get("action") == "noop"),
        "errors": sum(1 for item in items if item.get("action") == "error"),
        "ratingCounts": dict(sorted(rating_counts.items())),
        "items": items,
    }


def reference_quality_get(*, reference_id: str) -> dict[str, Any]:
    semantic = _semantic_client()
    reference = _resolve_reference(semantic, reference_id)
    relations = _current_relations(
        semantic.list_outgoing("reference", reference["lineageId"])["relations"],
        QUALITY_RELATION_TYPE_KEY,
    )
    relation = relations[0] if relations else None
    return {
        "kind": "reference.quality.get",
        "reference": _reference_summary(reference),
        "quality": _quality_from_relation(relation) if relation else None,
        "relation": _quality_relation_for_output(relation),
    }


def build_quality_local_metadata_plan(
    *,
    reference: dict[str, Any],
    rating: int,
    note: str = "",
    actor_label: str = "papyrus",
) -> dict[str, Any]:
    reference = _require_reference(reference)
    sidecar_path = _sidecar_path_for_reference(reference)
    catalog_path, catalog_item_key = _catalog_location_for_reference(reference)
    return {
        "kind": "reference.quality.local-metadata.plan",
        "referenceId": reference.get("id"),
        "externalItemId": reference.get("externalItemId"),
        "rating": normalize_quality_rating(rating),
        "qualityNodeKey": quality_node_key(rating),
        "sidecarPath": str(sidecar_path) if sidecar_path else None,
        "catalogPath": str(catalog_path) if catalog_path else None,
        "catalogItemKey": catalog_item_key,
        "note": note,
        "actorLabel": actor_label,
    }


def apply_quality_local_metadata(
    *,
    reference: dict[str, Any],
    rating: int,
    note: str = "",
    actor_label: str = "papyrus",
) -> dict[str, Any]:
    now = _now()
    rating = normalize_quality_rating(rating)
    payload = _quality_local_metadata_payload(rating=rating, note=note, actor_label=actor_label, now=now)
    sidecar_path = _sidecar_path_for_reference(reference)
    catalog_path, catalog_item_key = _catalog_location_for_reference(reference)
    updated = []
    skipped = []
    errors = []

    if sidecar_path:
        try:
            existed = sidecar_path.exists()
            parsed = _read_yaml_file(sidecar_path) if existed else {}
            current_rating = _quality_rating_from_metadata(parsed)
            if current_rating == rating:
                skipped.append({"target": "sidecar", "path": str(sidecar_path), "reason": "quality_rating_already_present"})
            else:
                parsed["quality"] = {
                    **(parsed.get("quality") if isinstance(parsed.get("quality"), dict) else {}),
                    "rating": rating,
                    "rating_node_key": quality_node_key(rating),
                }
                parsed["papyrus"] = {
                    **(parsed.get("papyrus") if isinstance(parsed.get("papyrus"), dict) else {}),
                    "quality_rating": payload,
                }
                sidecar_path.parent.mkdir(parents=True, exist_ok=True)
                sidecar_path.write_text(_dump_yaml(parsed), encoding="utf-8")
                updated.append({"target": "sidecar", "path": str(sidecar_path), "created": not existed})
        except Exception as exc:
            errors.append({"target": "sidecar", "path": str(sidecar_path), "error": str(exc)})
    else:
        skipped.append({"target": "sidecar", "reason": "missing_local_source_path"})

    if catalog_path and catalog_item_key:
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            items = catalog.get("items") if isinstance(catalog, dict) else None
            item = items.get(catalog_item_key) if isinstance(items, dict) else None
            if not isinstance(item, dict):
                skipped.append({"target": "catalog", "path": str(catalog_path), "reason": "catalog_item_not_found"})
            else:
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                current_rating = _quality_rating_from_metadata(metadata) or _quality_rating_from_metadata(item)
                if current_rating == rating:
                    skipped.append({"target": "catalog", "path": str(catalog_path), "reason": "quality_rating_already_present"})
                else:
                    metadata["quality"] = {
                        **(metadata.get("quality") if isinstance(metadata.get("quality"), dict) else {}),
                        "rating": rating,
                        "rating_node_key": quality_node_key(rating),
                    }
                    metadata["papyrus"] = {
                        **(metadata.get("papyrus") if isinstance(metadata.get("papyrus"), dict) else {}),
                        "quality_rating": payload,
                    }
                    item["metadata"] = metadata
                    item.pop("quality", None)
                    catalog_path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                    updated.append({"target": "catalog", "path": str(catalog_path), "itemKey": catalog_item_key})
        except Exception as exc:
            errors.append({"target": "catalog", "path": str(catalog_path), "error": str(exc)})
    else:
        skipped.append({"target": "catalog", "reason": "catalog_not_found"})

    return {
        "kind": "reference.quality.local-metadata.applied",
        "referenceId": reference.get("id"),
        "externalItemId": reference.get("externalItemId"),
        "rating": rating,
        "qualityNodeKey": quality_node_key(rating),
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


def reference_quality_list(*, corpus_key: str, rating: int | None = None, min_rating: int | None = None, limit: int = 100) -> dict[str, Any]:
    semantic = _semantic_client()
    references = list_references_by_corpus(_knowledge_corpus_id(corpus_key), limit=limit)
    rows = []
    for reference in references:
        relations = _current_relations(
            semantic.list_outgoing("reference", reference["lineageId"])["relations"],
            QUALITY_RELATION_TYPE_KEY,
        )
        quality = _quality_from_relation(relations[0]) if relations else None
        if rating is not None and (not quality or quality["rating"] != normalize_quality_rating(rating)):
            continue
        if min_rating is not None and (not quality or quality["rating"] < normalize_quality_rating(min_rating)):
            continue
        rows.append({"reference": _reference_summary(reference), "quality": quality})
    return {"kind": "reference.quality.list", "corpusKey": corpus_key, "count": len(rows), "items": rows}


def reference_list(
    *,
    corpus_key: str,
    limit: int = 25,
    status: str = "",
    order: str = "newest",
    scan_limit: int = 1000,
) -> dict[str, Any]:
    corpus_id = _knowledge_corpus_id(corpus_key)
    normalized_status = str(status or "").strip().lower()
    normalized_order = _normalize_reference_list_order(order)
    reverse = normalized_order.endswith("-oldest") is False
    if normalized_order.startswith("imported"):
        references = list_references_by_newsroom_feed_imported(limit=max(scan_limit, limit), corpus_id=corpus_id)
    else:
        references = list_references_by_corpus(corpus_id, limit=max(scan_limit, limit))
    if normalized_status and normalized_status not in {"all", "*"}:
        references = [reference for reference in references if str(reference.get("curationStatus") or "").lower() == normalized_status]
    sort_key = _reference_list_sort_key(normalized_order)
    references.sort(key=sort_key, reverse=reverse)
    selected = references[:max(int(limit or 25), 1)]
    return {
        "kind": "reference.list",
        "corpusKey": corpus_key,
        "status": status or "all",
        "order": normalized_order,
        "count": len(selected),
        "scanned": len(references),
        "items": [_reference_summary(reference) | {
            "sourceUri": reference.get("sourceUri"),
            "storagePath": reference.get("storagePath"),
            "importedAt": reference.get("importedAt"),
            "updatedAt": reference.get("updatedAt"),
            "sourcePublishedAt": reference.get("sourcePublishedAt"),
        } for reference in selected],
    }


def reference_curate_recent(
    *,
    corpus_key: str,
    reference_ids: list[str] | None = None,
    since_hours: int = 48,
    since: str = "",
    curate_all: bool = False,
    max_count: int = 0,
    scan_limit: int = 1000,
    max_parallel: int = 1,
    model: str = "gpt-5.4-mini",
    summary_max_tokens: int = TITLE_SUBTITLE_SUMMARY_TOKEN_BUDGET_DEFAULT,
    refresh_summary: bool = False,
    refresh_quality: bool = False,
    apply: bool = False,
    resume: str = "",
) -> dict[str, Any]:
    run_started_at = _now()
    now_dt = _parse_iso_datetime(run_started_at) or _dt.datetime.now(_dt.UTC)
    explicit_reference_ids = [str(value).strip() for value in (reference_ids or []) if str(value).strip()]

    requested_since = _clean_text(since)
    since_source = "all" if curate_all else ("since" if requested_since else "since_hours")
    if curate_all:
        since_dt = None
    elif requested_since:
        since_dt = _parse_iso_datetime(requested_since)
        if since_dt is None:
            raise ValueError(f"Invalid --since value: {since}")
    else:
        since_dt = now_dt - _dt.timedelta(hours=max(int(since_hours or 0), 0))

    run_id = _hash_short([
        "reference-curation",
        run_started_at,
        corpus_key,
        explicit_reference_ids,
        "all" if curate_all else (requested_since or max(int(since_hours or 0), 0)),
        int(max_count or 0),
        int(scan_limit or 0),
    ])
    manifest_path = _reference_curation_manifest_path(run_id=run_id, resume=resume)
    manifest = _load_reference_curation_manifest(
        manifest_path=manifest_path,
        run_id=run_id,
        corpus_key=corpus_key,
        apply=apply,
        model=model,
        summary_max_tokens=summary_max_tokens,
        since=requested_since,
        since_hours=max(int(since_hours or 0), 0),
        curate_all=bool(curate_all),
        max_count=max(int(max_count or 0), 0),
        scan_limit=max(int(scan_limit or 1), 1),
        explicit_reference_ids=explicit_reference_ids,
    )
    manifest["updatedAt"] = run_started_at
    _save_reference_curation_manifest(manifest_path, manifest)

    semantic = _semantic_client()
    selection_failures: list[dict[str, Any]] = []

    if explicit_reference_ids:
        selected_references = []
        for reference_id in explicit_reference_ids:
            try:
                resolved = _resolve_reference(semantic, reference_id)
            except Exception as exc:
                selection_failures.append({
                    "referenceId": reference_id,
                    "status": "selection_failed",
                    "failureReason": str(exc),
                })
                continue
            selected_references.append(resolved)
    elif resume:
        selected_references = []
        manifest_references = manifest.get("references") if isinstance(manifest.get("references"), dict) else {}
        for reference_id in manifest_references.keys():
            try:
                resolved = _resolve_reference(semantic, str(reference_id))
            except Exception as exc:
                entry = manifest_references.get(reference_id) if isinstance(manifest_references.get(reference_id), dict) else {}
                snapshot = entry.get("reference") if isinstance(entry.get("reference"), dict) else {}
                if snapshot.get("id"):
                    selected_references.append({
                        "id": snapshot.get("id"),
                        "lineageId": snapshot.get("lineageId"),
                        "externalItemId": snapshot.get("externalItemId"),
                        "curationStatus": snapshot.get("curationStatus"),
                        "title": snapshot.get("title"),
                    })
                    selection_failures.append({
                        "referenceId": str(reference_id),
                        "status": "resume_snapshot_used",
                        "failureReason": f"Could not resolve live reference: {exc}",
                    })
                    continue
                selection_failures.append({
                    "referenceId": str(reference_id),
                    "status": "selection_failed",
                    "failureReason": str(exc),
                })
                continue
            selected_references.append(resolved)
    else:
        selected_references = _select_references_for_curate_recent(
            corpus_key=corpus_key,
            since_dt=since_dt,
            curate_all=curate_all,
            max_count=max_count,
            scan_limit=scan_limit,
        )

    results: list[dict[str, Any]] = []
    for reference in selected_references:
        reference_id = str(reference.get("id") or "")
        if not reference_id:
            continue
        manifest_reference = _reference_curation_manifest_reference_entry(
            manifest=manifest,
            reference=reference,
            reference_id=reference_id,
        )
        manifest_reference["updatedAt"] = _now()
        manifest_reference["status"] = "running"
        _save_reference_curation_manifest(manifest_path, manifest)

        result = {
            "reference": _reference_summary(reference),
            "referenceId": reference_id,
            "identifierPrepass": {},
            "stages": {},
            "failed": False,
            "degraded": False,
            "failureReasons": [],
            "apply": apply,
        }

        identifier_prepass, stage_result = _run_reference_curation_identifier_stage(
            reference=reference,
            manifest_reference=manifest_reference,
            allow_resume=True,
        )
        result["identifierPrepass"] = identifier_prepass
        result["stages"]["identifierPrepass"] = stage_result

        identifier_failed = not stage_result.get("success")

        title_result = _run_reference_curation_title_stage(
            reference=reference,
            model=model,
            apply=apply,
            manifest_reference=manifest_reference,
            identifier_failed=identifier_failed,
        )
        result["stages"]["titleSubtitle"] = title_result

        summary_result = _run_reference_curation_summary_stage(
            reference=reference,
            model=model,
            apply=apply,
            summary_max_tokens=summary_max_tokens,
            refresh_summary=refresh_summary,
            manifest_reference=manifest_reference,
            identifier_failed=identifier_failed,
        )
        result["stages"]["summary"] = summary_result

        quality_result = _run_reference_curation_quality_stage(
            reference=reference,
            model=model,
            apply=apply,
            refresh_quality=refresh_quality,
            manifest_reference=manifest_reference,
            identifier_failed=identifier_failed,
        )
        result["stages"]["quality"] = quality_result

        stage_failures = [
            stage for stage in result["stages"].values()
            if not stage.get("success")
        ]
        result["failed"] = len(stage_failures) > 0
        result["degraded"] = result["failed"]
        result["failureReasons"] = [stage.get("failureReason") for stage in stage_failures if stage.get("failureReason")]
        result["status"] = "failed" if result["failed"] else "ok"
        manifest_reference["status"] = result["status"]
        manifest_reference["updatedAt"] = _now()
        manifest_reference["completedAt"] = _now()
        if result["failureReasons"]:
            manifest_reference["lastError"] = result["failureReasons"][-1]
        results.append(result)
        _save_reference_curation_manifest(manifest_path, manifest)

    failed_count = sum(1 for item in results if item.get("failed")) + len(selection_failures)
    succeeded_count = sum(1 for item in results if not item.get("failed"))
    manifest["updatedAt"] = _now()
    manifest["summary"] = {
        "selectedCount": len(selected_references),
        "processedCount": len(results),
        "succeededCount": succeeded_count,
        "failedCount": failed_count,
        "selectionFailures": len(selection_failures),
        "titleUpdatedCount": sum(
            1 for item in results
            if (item.get("stages", {}).get("titleSubtitle", {}).get("action") == "update")
        ),
        "summaryCreatedCount": sum(
            1 for item in results
            if (item.get("stages", {}).get("summary", {}).get("action") == "create")
        ),
        "qualityCreatedCount": sum(
            1 for item in results
            if (item.get("stages", {}).get("quality", {}).get("action") == "create")
        ),
    }
    _save_reference_curation_manifest(manifest_path, manifest)

    return {
        "kind": "reference.curate-recent",
        "ok": failed_count == 0,
        "degraded": failed_count > 0,
        "command": "references curate-recent",
        "runId": manifest.get("runId"),
        "manifestPath": str(manifest_path),
        "apply": apply,
        "corpusKey": corpus_key,
        "selection": {
            "mode": "explicit"
            if explicit_reference_ids
            else ("resume" if resume else ("all" if curate_all else "recent_window")),
            "referenceIds": explicit_reference_ids,
            "since": requested_since or (since_dt.isoformat().replace("+00:00", "Z") if since_dt else ""),
            "sinceSource": since_source,
            "sinceHours": max(int(since_hours or 0), 0),
            "curateAll": bool(curate_all),
            "maxCount": max(int(max_count or 0), 0),
            "scanLimit": max(int(scan_limit or 1), 1),
            "maxParallel": max(int(max_parallel or 1), 1),
            "resume": str(manifest_path) if resume else "",
        },
        "summary": dict(manifest.get("summary") or {}),
        "selectionFailures": selection_failures,
        "count": len(results),
        "items": results,
        "warnings": (
            [f"max_parallel={max_parallel} requested; deterministic sequential execution is used in v1."]
            if int(max_parallel or 1) > 1 else []
        ),
    }


def _run_reference_curation_identifier_stage(
    *,
    reference: dict[str, Any],
    manifest_reference: dict[str, Any],
    allow_resume: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prior = _reference_curation_manifest_stage(manifest_reference, "identifierPrepass")
    if allow_resume and prior.get("success"):
        output = prior.get("output") if isinstance(prior.get("output"), dict) else {}
        return output, {
            "status": "reused",
            "success": True,
            "action": "reuse",
            "failureReason": "",
            "cached": True,
            "identifierPrepass": output,
        }
    prepass = _run_identifier_prepass(reference=reference, catalog_entry={})
    success = str(prepass.get("status") or "") in {"ok", "no_identifier_found"}
    stage = {
        "status": str(prepass.get("status") or "failed"),
        "success": success,
        "action": "run",
        "failureReason": str(prepass.get("failureReason") or ""),
        "cached": False,
        "identifierPrepass": prepass,
    }
    manifest_reference["stages"]["identifierPrepass"] = {
        "status": stage["status"],
        "success": success,
        "action": stage["action"],
        "failureReason": stage["failureReason"],
        "updatedAt": _now(),
        "output": prepass,
    }
    return prepass, stage


def _run_reference_curation_title_stage(
    *,
    reference: dict[str, Any],
    model: str,
    apply: bool,
    manifest_reference: dict[str, Any],
    identifier_failed: bool,
) -> dict[str, Any]:
    if identifier_failed:
        stage = {
            "status": "skipped",
            "success": False,
            "action": "skip",
            "failureReason": "identifier prepass failed",
            "cached": False,
        }
        manifest_reference["stages"]["titleSubtitle"] = {
            **stage,
            "updatedAt": _now(),
            "output": {},
        }
        return stage
    prior = _reference_curation_manifest_stage(manifest_reference, "titleSubtitle")
    if prior.get("success"):
        return {
            "status": "reused",
            "success": True,
            "action": "reuse",
            "failureReason": "",
            "cached": True,
            "output": prior.get("output") if isinstance(prior.get("output"), dict) else {},
        }
    try:
        output = reference_title_subtitle_resolve(
            reference_id=str(reference.get("id") or ""),
            model=model,
            apply=apply,
            summary=False,
            persist_local_metadata=True,
            vector_sync=True,
        )
        action = str(output.get("action") or "")
        success = action in {"update", "noop"}
        stage = {
            "status": action or "unknown",
            "success": success,
            "action": action or "unknown",
            "failureReason": "" if success else (output.get("failureReason") or f"title/subtitle action={action or 'unknown'}"),
            "cached": False,
            "output": output,
        }
    except Exception as exc:
        stage = {
            "status": "error",
            "success": False,
            "action": "error",
            "failureReason": str(exc),
            "cached": False,
            "output": {"error": str(exc)},
        }
    manifest_reference["stages"]["titleSubtitle"] = {
        "status": stage["status"],
        "success": stage["success"],
        "action": stage["action"],
        "failureReason": stage["failureReason"],
        "updatedAt": _now(),
        "output": stage.get("output") if isinstance(stage.get("output"), dict) else {},
    }
    return stage


def _run_reference_curation_summary_stage(
    *,
    reference: dict[str, Any],
    model: str,
    apply: bool,
    summary_max_tokens: int,
    refresh_summary: bool,
    manifest_reference: dict[str, Any],
    identifier_failed: bool,
) -> dict[str, Any]:
    if identifier_failed:
        stage = {
            "status": "skipped",
            "success": False,
            "action": "skip",
            "failureReason": "identifier prepass failed",
            "cached": False,
        }
        manifest_reference["stages"]["summary"] = {
            **stage,
            "updatedAt": _now(),
            "output": {},
        }
        return stage
    prior = _reference_curation_manifest_stage(manifest_reference, "summary")
    if prior.get("success") and not refresh_summary:
        return {
            "status": "reused",
            "success": True,
            "action": "reuse",
            "failureReason": "",
            "cached": True,
            "output": prior.get("output") if isinstance(prior.get("output"), dict) else {},
        }
    try:
        output = reference_summarize(
            reference_id=str(reference.get("id") or ""),
            max_tokens=summary_max_tokens,
            model=model,
            apply=apply,
            refresh=refresh_summary,
        )
        action = str(output.get("action") or "")
        success = action in {"create", "noop"}
        stage = {
            "status": action or "unknown",
            "success": success,
            "action": action or "unknown",
            "failureReason": "" if success else (output.get("failureReason") or f"summary action={action or 'unknown'}"),
            "cached": False,
            "output": output,
        }
    except Exception as exc:
        stage = {
            "status": "error",
            "success": False,
            "action": "error",
            "failureReason": str(exc),
            "cached": False,
            "output": {"error": str(exc)},
        }
    manifest_reference["stages"]["summary"] = {
        "status": stage["status"],
        "success": stage["success"],
        "action": stage["action"],
        "failureReason": stage["failureReason"],
        "updatedAt": _now(),
        "output": stage.get("output") if isinstance(stage.get("output"), dict) else {},
    }
    return stage


def _run_reference_curation_quality_stage(
    *,
    reference: dict[str, Any],
    model: str,
    apply: bool,
    refresh_quality: bool,
    manifest_reference: dict[str, Any],
    identifier_failed: bool,
) -> dict[str, Any]:
    if identifier_failed:
        stage = {
            "status": "skipped",
            "success": False,
            "action": "skip",
            "failureReason": "identifier prepass failed",
            "cached": False,
        }
        manifest_reference["stages"]["quality"] = {
            **stage,
            "updatedAt": _now(),
            "output": {},
        }
        return stage
    prior = _reference_curation_manifest_stage(manifest_reference, "quality")
    if prior.get("success") and not refresh_quality:
        return {
            "status": "reused",
            "success": True,
            "action": "reuse",
            "failureReason": "",
            "cached": True,
            "output": prior.get("output") if isinstance(prior.get("output"), dict) else {},
        }
    try:
        output = reference_quality_assess(
            reference_id=str(reference.get("id") or ""),
            model=model,
            apply=apply,
            refresh=refresh_quality,
            persist_local_metadata=True,
        )
        action = str(output.get("action") or "")
        success = action in {"create", "noop"}
        stage = {
            "status": action or "unknown",
            "success": success,
            "action": action or "unknown",
            "failureReason": "" if success else (output.get("failureReason") or f"quality action={action or 'unknown'}"),
            "cached": False,
            "output": output,
        }
    except Exception as exc:
        stage = {
            "status": "error",
            "success": False,
            "action": "error",
            "failureReason": str(exc),
            "cached": False,
            "output": {"error": str(exc)},
        }
    manifest_reference["stages"]["quality"] = {
        "status": stage["status"],
        "success": stage["success"],
        "action": stage["action"],
        "failureReason": stage["failureReason"],
        "updatedAt": _now(),
        "output": stage.get("output") if isinstance(stage.get("output"), dict) else {},
    }
    return stage


def _select_references_for_curate_recent(
    *,
    corpus_key: str,
    since_dt: _dt.datetime | None,
    curate_all: bool = False,
    max_count: int,
    scan_limit: int,
) -> list[dict[str, Any]]:
    references = list_references_by_corpus(_knowledge_corpus_id(corpus_key), limit=max(scan_limit, max_count or 1))
    references.sort(key=_reference_chrono_key, reverse=True)
    selected: list[dict[str, Any]] = []
    for reference in references:
        if not curate_all and since_dt is not None:
            reference_dt = _reference_datetime(reference)
            if reference_dt is None:
                continue
            if reference_dt < since_dt:
                continue
        selected.append(reference)
        if max_count and len(selected) >= int(max_count):
            break
    return selected


def _reference_datetime(reference: dict[str, Any]) -> _dt.datetime | None:
    for key in ("importedAt", "updatedAt", "retrievedAt", "sourceUpdatedAt", "sourcePublishedAt"):
        parsed = _parse_iso_datetime(reference.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_iso_datetime(value: Any) -> _dt.datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = f"{text[:-1]}+00:00" if text.endswith("Z") else text
    try:
        parsed = _dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_dt.UTC)
    return parsed.astimezone(_dt.UTC)


def _reference_curation_manifest_path(*, run_id: str, resume: str = "") -> Path:
    if resume:
        return Path(resume).expanduser().resolve()
    directory = PAPYRUS_ROOT / ".papyrus-runs" / f"reference-curation-{run_id}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "manifest.json"


def _load_reference_curation_manifest(
    *,
    manifest_path: Path,
    run_id: str,
    corpus_key: str,
    apply: bool,
    model: str,
    summary_max_tokens: int,
    since: str,
    since_hours: int,
    curate_all: bool = False,
    max_count: int,
    scan_limit: int,
    explicit_reference_ids: list[str],
) -> dict[str, Any]:
    if manifest_path.exists():
        parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError(f"Invalid resume manifest payload: {manifest_path}")
        parsed.setdefault("references", {})
        parsed.setdefault("summary", {})
        parsed["updatedAt"] = _now()
        return parsed
    now = _now()
    return {
        "kind": "reference.curate-recent.manifest",
        "version": 1,
        "runId": run_id,
        "createdAt": now,
        "updatedAt": now,
        "references": {},
        "summary": {},
        "inputs": {
            "corpusKey": corpus_key,
            "apply": apply,
            "model": model,
            "summaryMaxTokens": summary_max_tokens,
            "since": since,
            "sinceHours": since_hours,
            "curateAll": curate_all,
            "maxCount": max_count,
            "scanLimit": scan_limit,
            "referenceIds": explicit_reference_ids,
        },
    }


def _save_reference_curation_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _reference_curation_manifest_reference_entry(
    *,
    manifest: dict[str, Any],
    reference: dict[str, Any],
    reference_id: str,
) -> dict[str, Any]:
    entries = manifest.get("references")
    if not isinstance(entries, dict):
        entries = {}
        manifest["references"] = entries
    existing = entries.get(reference_id) if isinstance(entries.get(reference_id), dict) else {}
    entry = {
        "reference": {
            "id": reference_id,
            "lineageId": reference.get("lineageId"),
            "externalItemId": reference.get("externalItemId"),
            "curationStatus": reference.get("curationStatus"),
            "title": reference.get("title"),
        },
        "status": existing.get("status") or "pending",
        "startedAt": existing.get("startedAt") or _now(),
        "updatedAt": _now(),
        "completedAt": existing.get("completedAt"),
        "lastError": existing.get("lastError") or "",
        "stages": existing.get("stages") if isinstance(existing.get("stages"), dict) else {},
    }
    entries[reference_id] = entry
    return entry


def _reference_curation_manifest_stage(manifest_reference: dict[str, Any], stage_key: str) -> dict[str, Any]:
    stages = manifest_reference.get("stages")
    if not isinstance(stages, dict):
        stages = {}
        manifest_reference["stages"] = stages
    value = stages.get(stage_key)
    if isinstance(value, dict):
        return value
    return {}


def _select_references_for_curation_batch(
    *,
    corpus_key: str,
    status: str,
    max_count: int,
    scan_limit: int,
) -> list[dict[str, Any]]:
    references = list_references_by_corpus(_knowledge_corpus_id(corpus_key), limit=max(scan_limit, max_count or 1))
    if status and str(status).strip().lower() not in {"all", "*"}:
        normalized_status = status.strip().lower()
        references = [reference for reference in references if str(reference.get("curationStatus") or "").lower() == normalized_status]
    references.sort(key=_reference_chrono_key, reverse=True)
    return references[:max(int(max_count or 10), 1)]


def reference_summaries(*, reference_id: str, max_tokens: int | None = None) -> dict[str, Any]:
    semantic = _semantic_client()
    reference = _resolve_reference(semantic, reference_id)
    metadata_payload = _load_reference_metadata_payload(reference)
    summary_text = _normalize_outcome_summary_candidate(metadata_payload.get("summary"))
    summary_resolution = metadata_payload.get("summary_resolution") if isinstance(metadata_payload.get("summary_resolution"), dict) else {}
    budget = _number_or_none(summary_resolution.get("summaryTokenBudget"))
    if max_tokens is not None and budget is not None and int(budget) != int(max_tokens):
        summaries: list[dict[str, Any]] = []
    elif summary_text:
        summaries = [
            {
                "summary": summary_text,
                "summaryResolution": summary_resolution,
                "maxTokens": int(budget) if budget is not None else None,
                "source": "reference_metadata_attachment",
            }
        ]
    else:
        summaries = []
    return {
        "kind": "reference.summaries",
        "reference": _reference_summary(reference),
        "maxTokens": max_tokens,
        "count": len(summaries),
        "summaries": summaries,
    }


def reference_summary_cleanup_legacy(
    *,
    reference_id: str,
    apply: bool = False,
) -> dict[str, Any]:
    semantic = _semantic_client()
    reference = _resolve_reference(semantic, reference_id)
    legacy = semantic.list_reference_summaries(reference.get("lineageId") or reference.get("id"), None).get("summaries") or []
    records: list[dict[str, Any]] = []
    deleted_relations: list[str] = []
    deleted_messages: list[str] = []
    for entry in legacy:
        relation = entry.get("relation") if isinstance(entry.get("relation"), dict) else {}
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        relation_id = str(relation.get("id") or "")
        message_id = str(message.get("id") or "")
        if relation_id:
            records.append({"modelName": "SemanticRelation", "action": "delete", "input": {"id": relation_id}})
            deleted_relations.append(relation_id)
        if message_id:
            records.append({"modelName": "Message", "action": "delete", "input": {"id": message_id}})
            deleted_messages.append(message_id)
    plan = {
        "kind": "reference.summary.cleanup-legacy",
        "action": "delete" if records else "noop",
        "reference": _reference_summary(reference),
        "legacySummaryCount": len(legacy),
        "legacyRelationIds": deleted_relations,
        "legacyMessageIds": deleted_messages,
        "records": records,
        "warnings": [],
    }
    return _apply_plan_if_requested(
        plan,
        apply=apply,
        actor_label=SUMMARY_SOURCE,
        reason="references summary-cleanup-legacy",
    )


def reference_summarize(
    *,
    reference_id: str,
    max_tokens: int,
    summary_text: str = "",
    source_text: str = "",
    source_text_file: str = "",
    model: str = "gpt-5.4-mini",
    apply: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    semantic = _semantic_client()
    reference = _resolve_reference(semantic, reference_id)
    identifier_prepass = _run_identifier_prepass(reference=reference, catalog_entry={})
    if identifier_prepass.get("status") == "failed":
        return {
            "kind": "reference.summary.plan",
            "action": "blocked",
            "reference": _reference_summary(reference),
            "maxTokens": normalize_summary_budget(max_tokens),
            "identifierPrepass": identifier_prepass,
            "failureReason": identifier_prepass.get("failureReason") or "identifier prepass failed",
            "warnings": [f"identifier prepass failed: {identifier_prepass.get('failureReason') or 'unknown error'}"],
            "records": [],
            "apply": False,
        }
    source = (
        _resolve_source_text(reference, source_text=source_text, source_text_file=source_text_file)
        if (not summary_text or source_text or source_text_file)
        else ""
    )
    doctrine_context = manual_summary_doctrine_context() if summary_text else load_publication_doctrine_context()
    generated_result = (
        {
            "summary_text": summary_text,
            "prompt_version": SUMMARY_PROMPT_VERSION,
            "model": "manual",
        }
        if summary_text
        else generate_summary(
            source,
            max_tokens=max_tokens,
            model=model,
            reference=reference,
            doctrine_context=doctrine_context,
        )
    )
    generated = generated_result.get("summary_text") or ""
    plan = build_reference_summary_plan(
        reference=reference,
        max_tokens=max_tokens,
        summary_text=generated,
        source_text=source,
        model=generated_result.get("model") or (model if not summary_text else "manual"),
        prompt_version=generated_result.get("prompt_version") or SUMMARY_PROMPT_VERSION,
        doctrine_context=doctrine_context,
        refresh=refresh,
        identifier_prepass=identifier_prepass,
        semantic_client=semantic,
    )
    result = _apply_plan_if_requested(plan, apply=apply, actor_label=SUMMARY_SOURCE, reason="references summarize")
    result["identifierPrepass"] = identifier_prepass
    return _with_doctrine_warnings(result, doctrine_context)


def reference_summarize_batch(
    *,
    corpus_key: str,
    budgets: list[int],
    only_missing: bool = True,
    max_count: int = 0,
    max_parallel: int = 4,
    scan_limit: int = 5000,
    model: str = "gpt-5.4-mini",
    apply: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    if not budgets:
        budgets = [TITLE_SUBTITLE_SUMMARY_TOKEN_BUDGET_DEFAULT]
    budget = normalize_summary_budget(budgets[0])
    relation_key = summary_relation_type_key(budget)
    max_parallel = max(1, min(int(max_parallel or 1), 12))
    scan_limit = max(int(scan_limit or 1), 1)
    create_limit = max(int(max_count or 0), 0)

    semantic = _semantic_client()
    doctrine_context = load_publication_doctrine_context()
    references = list_references_by_corpus(_knowledge_corpus_id(corpus_key), limit=scan_limit)
    candidates: list[dict[str, Any]] = []
    skipped_existing = 0
    for reference in references:
        if reference.get("curationStatus") not in {None, "accepted"}:
            continue
        existing_metadata = _load_reference_metadata_payload(reference)
        existing_summary = _normalize_outcome_summary_candidate(existing_metadata.get("summary"))
        if existing_summary and only_missing and not refresh:
            skipped_existing += 1
            continue
        candidates.append(reference)
        if create_limit and len(candidates) >= create_limit:
            break

    apply_lock = threading.Lock()

    def process_reference(reference: dict[str, Any]) -> dict[str, Any]:
        identifier_prepass = _run_identifier_prepass(reference=reference, catalog_entry={})
        if identifier_prepass.get("status") == "failed":
            return {
                "kind": "reference.summary.plan",
                "action": "blocked",
                "reference": _reference_summary(reference),
                "maxTokens": budget,
                "identifierPrepass": identifier_prepass,
                "failureReason": identifier_prepass.get("failureReason") or "identifier prepass failed",
                "warnings": [f"identifier prepass failed: {identifier_prepass.get('failureReason') or 'unknown error'}"],
                "records": [],
            }
        source = _resolve_source_text(reference)
        generated_result = generate_summary(
            source,
            max_tokens=budget,
            model=model,
            reference=reference,
            doctrine_context=doctrine_context,
            procedure_alias=SUMMARY_PROCEDURE_ALIAS_SUMMARIZE_BATCH,
        )
        generated = generated_result.get("summary_text") or ""
        plan = build_reference_summary_plan(
            reference=reference,
            max_tokens=budget,
            summary_text=generated,
            source_text=source,
            model=generated_result.get("model") or model,
            prompt_version=generated_result.get("prompt_version") or SUMMARY_PROMPT_VERSION,
            doctrine_context=doctrine_context,
            refresh=refresh,
            identifier_prepass=identifier_prepass,
            semantic_client=semantic,
        )
        plan["identifierPrepass"] = identifier_prepass
        if apply and plan.get("action") != "noop" and plan.get("records"):
            with apply_lock:
                return _apply_plan_if_requested(
                    plan,
                    apply=True,
                    actor_label=SUMMARY_SOURCE,
                    reason="references summarize-batch",
                )
        return {**plan, "apply": False}

    applied: list[dict[str, Any]] = []
    if candidates:
        if max_parallel == 1:
            applied = [process_reference(reference) for reference in candidates]
        else:
            with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                futures = [executor.submit(process_reference, reference) for reference in candidates]
                for future in as_completed(futures):
                    applied.append(future.result())

    applied.sort(key=lambda item: str((item.get("reference") or {}).get("id") or ""))
    return {
        "kind": "reference.summary.batch",
        "corpusKey": corpus_key,
        "budgets": [budget],
        "apply": apply,
        "onlyMissing": only_missing,
        "maxParallel": max_parallel,
        "scanLimit": scan_limit,
        "scannedReferences": len(references),
        "skippedExisting": skipped_existing,
        "selectedCount": len(candidates),
        "doctrineContext": doctrine_summary_metadata(doctrine_context),
        "warnings": list(doctrine_context.get("warnings") or []),
        "count": len(applied),
        "created": sum(1 for item in applied if item.get("action") == "create"),
        "blocked": sum(1 for item in applied if item.get("action") == "blocked"),
        "failed": sum(1 for item in applied if item.get("action") not in {"create", "noop", "blocked"} and item.get("failureReason")),
        "noop": sum(1 for item in applied if item.get("action") == "noop"),
        "items": applied,
    }


def list_references_by_corpus(corpus_id: str, limit: int = 1000) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    next_token = None
    while True:
        data = _graphql(LIST_REFERENCES_BY_CORPUS_QUERY, {"corpusId": corpus_id, "limit": min(max(limit - len(records), 1), 100), "nextToken": next_token})
        connection = data.get("listReferencesByCorpusAndExternalItem") or {}
        records.extend(connection.get("items") or [])
        next_token = connection.get("nextToken")
        if not next_token or len(records) >= limit:
            break
    return [record for record in records if record.get("versionState") == "current"]


def list_references_by_newsroom_feed_imported(
    *,
    limit: int = 1000,
    corpus_id: str | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    next_token = None
    filter_input: dict[str, Any] = {
        "versionState": {"eq": "current"},
        "newsroomFeedKey": {"eq": "references"},
    }
    if corpus_id:
        filter_input["corpusId"] = {"eq": corpus_id}
    try:
        while True:
            data = _graphql(
                LIST_REFERENCES_BY_NEWSROOM_FEED_IMPORTED_QUERY,
                {
                    "newsroomFeedKey": "references",
                    "sortDirection": "DESC",
                    "limit": min(max(limit - len(records), 1), 100),
                    "nextToken": next_token,
                    "filter": filter_input,
                },
            )
            connection = data.get("listReferencesByNewsroomFeedAndImportedAt") or {}
            records.extend(connection.get("items") or [])
            next_token = connection.get("nextToken")
            if not next_token or len(records) >= limit:
                break
    except Exception as exc:
        message = str(exc)
        if "FieldUndefined" not in message or "listReferencesByNewsroomFeedAndImportedAt" not in message:
            raise
    if records:
        return [record for record in records if record.get("versionState") == "current"]
    if not corpus_id:
        return []
    return list_references_by_corpus(corpus_id, limit=limit)


def load_publication_doctrine_context(*, graphql_func: Any | None = None) -> dict[str, Any]:
    graphql = graphql_func or _graphql
    records = []
    warnings = []
    for slug in PUBLICATION_DOCTRINE_SLUGS:
        try:
            record = _get_current_doctrine_item_by_slug(slug, graphql)
        except Exception as exc:
            warnings.append(f"Could not load publication doctrine {slug}: {exc}")
            record = None
        if record:
            records.append(_doctrine_context_record(record))
        else:
            warnings.append(f"Publication doctrine {slug} is missing.")
    found_slugs = [record["slug"] for record in records]
    if len(found_slugs) == len(PUBLICATION_DOCTRINE_SLUGS):
        status = "loaded"
    elif found_slugs:
        status = "partial"
    else:
        status = "missing"
    content_hash = _hash_text(json.dumps(records, sort_keys=True)) if records else ""
    return {
        "status": status,
        "scope": "publication",
        "policyUse": DOCTRINE_POLICY_USE,
        "slugs": found_slugs,
        "records": records,
        "contentHash": content_hash,
        "warnings": warnings,
    }


def manual_summary_doctrine_context() -> dict[str, Any]:
    return {
        "status": "not_used_manual_summary",
        "scope": "publication",
        "policyUse": DOCTRINE_POLICY_USE,
        "slugs": [],
        "records": [],
        "contentHash": "",
        "warnings": [],
    }


def doctrine_summary_metadata(doctrine_context: dict[str, Any] | None) -> dict[str, Any]:
    context = doctrine_context or {}
    return {
        "doctrineContextStatus": context.get("status") or "missing",
        "doctrineSlugs": context.get("slugs") or [],
        "doctrineContentHash": context.get("contentHash") or "",
        "doctrineScope": context.get("scope") or "publication",
        "policyUse": context.get("policyUse") or DOCTRINE_POLICY_USE,
    }


def build_quality_assessment_prompt(
    source_text: str,
    *,
    reference: dict[str, Any],
    rubric: str,
    doctrine_context: dict[str, Any] | None = None,
) -> str:
    context = doctrine_context or load_publication_doctrine_context()
    return "\n".join([
        "Assess this Reference's source quality using the supplied quality rubric.",
        "Return only JSON with keys: rating, rationale, evidence, caveats.",
        "The rating must be an integer from 1 to 5.",
        "",
        "Publication Context:",
        _format_publication_doctrine_prompt_block(context),
        "",
        "Important policy-use rule: Do not score the Reference by whether it complies with publication policies. Score source quality under the quality rubric; doctrine is only background about the publication's interests.",
        "",
        "Quality Rubric:",
        rubric.strip(),
        "",
        f"Title: {reference.get('title') or ''}",
        f"Source URI: {reference.get('sourceUri') or ''}",
        "",
        source_text[:50000],
    ])


def build_title_subtitle_prompt(
    *,
    reference: dict[str, Any],
    catalog_entry: dict[str, Any],
    source_text: str = "",
    known_title: str = "",
    known_subtitle: str = "",
) -> str:
    return "\n".join([
        "Resolve the original title and subtitle for this Reference.",
        "Use the original title verbatim if available. Use the original subtitle verbatim if available. Do not paraphrase original titles or subtitles.",
        "If the known title includes citation wrappers or source labels like leading arXiv ids, trailing '- arXiv', trailing publisher branding, or 'accessed <date>', remove that noise and recover the original work title.",
        "If no original subtitle exists, generate one concise, informative subtitle and set subtitle_mode to generated.",
        "Generated subtitles must be specific and meaningful, not generic labels, and typically 4 to 12 words.",
        "Avoid self-referential document framing such as 'This article', 'This paper', 'This report', or 'This release'.",
        "You MAY mention evidence/method terms such as survey, poll, trial, study, or experiment when they are substantive to the finding.",
        "Generated subtitle must include at least one concrete content signal (who, what, result, or population).",
        "Do not return URLs, domains, source labels, or placeholder subtitles.",
        "Subtitle must be one short prose line. Do not use Markdown. Do not use bullet points. Do not use numbered lists. Do not include line breaks.",
        "Do not return placeholder subtitles like 'No subtitle available', 'generated fallback subtitle', 'arXiv preprint', or source-brand labels.",
        "Examples:",
        "Good subtitle: 'Survey finds 72% of teens have used AI companions'",
        "Good subtitle: 'U.S. teens report routine AI companion use'",
        "Bad subtitle: 'This article reports survey results'",
        "Bad subtitle: 'https://phys.org/news/...'",
        "Bad subtitle: 'Study'",
        "Return strict JSON with keys: title, subtitle, title_mode, subtitle_mode, source_urls, rationale.",
        "Allowed modes: original_metadata, original_web_metadata, original_source_heading, generated, unresolved.",
        "",
        f"Known title: {known_title}",
        f"Known subtitle: {known_subtitle}",
        f"Reference title: {reference.get('title') or ''}",
        f"External item id: {reference.get('externalItemId') or catalog_entry.get('item_id') or catalog_entry.get('id') or ''}",
        f"Source URI: {reference.get('sourceUri') or catalog_entry.get('source_uri') or catalog_entry.get('sourceUri') or catalog_entry.get('url') or ''}",
        f"Authors: {', '.join(_string_list(reference.get('authors') or catalog_entry.get('authors') or []))}",
        f"Catalog metadata: {json.dumps(_compact_catalog_prompt_metadata(catalog_entry), sort_keys=True)[:2000]}",
        "",
        "Source text excerpt:",
        _source_excerpt(source_text, max_chars=3000) or "(none)",
    ])


def _reference_summarization_cloud_input(
    *,
    mode: str,
    source_text: str,
    max_tokens: int,
    model: str,
    reference: dict[str, Any],
    title: str = "",
    subtitle: str = "",
    doctrine_context: dict[str, Any] | None = None,
    prompt_version: str = "",
) -> dict[str, Any]:
    sanitized_source_text = str(source_text or "").replace("\x00", "")
    return _compact_dict({
        "mode": mode,
        "source_text": sanitized_source_text[:SUMMARY_SOURCE_TEXT_MAX_CHARS],
        "max_tokens": int(max_tokens),
        "reference_title": _clean_text(reference.get("title")),
        "source_uri": _clean_text(reference.get("sourceUri")),
        "known_title": _clean_text(title),
        "known_subtitle": _clean_text(subtitle),
        "media_type": _clean_text(reference.get("mediaType")),
        "doctrine_context_text": _format_publication_doctrine_prompt_block(doctrine_context or {}),
        "model": model,
        "prompt_version": prompt_version,
    })


def _run_reference_summarization_cloud_procedure(
    *,
    alias: str,
    mode: str,
    source_text: str,
    max_tokens: int,
    model: str,
    reference: dict[str, Any],
    title: str = "",
    subtitle: str = "",
    doctrine_context: dict[str, Any] | None = None,
    prompt_version: str = "",
) -> dict[str, str]:
    from papyrus_content.cloud_procedures import start_cloud_procedure_run
    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.ids import safe_id
    from papyrus_content.reference_assignments import timestamp_for_path

    run_id = f"reference-summarization-{safe_id(mode)}-{safe_id(reference.get('lineageId') or reference.get('id') or 'reference')[:80]}-{timestamp_for_path()}"
    run_dir = PAPYRUS_ROOT / ".papyrus-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    source_path = run_dir / "reference-summarization.cloud.tac"
    stdout_path = run_dir / "reference-summarization.stdout.log"
    stderr_path = run_dir / "reference-summarization.stderr.log"
    client, _ = create_authoring_client()
    run = start_cloud_procedure_run(
        client=client,
        alias=alias,
        actor_label=SUMMARY_SOURCE,
        title=f"Run reference summarization ({mode}) for {reference.get('id') or reference.get('lineageId') or 'reference'}",
        summary="Triggered by reference summarization workflow via cloud procedure dispatch.",
        input_payload=_reference_summarization_cloud_input(
            mode=mode,
            source_text=source_text,
            max_tokens=max_tokens,
            model=model,
            reference=reference,
            title=title,
            subtitle=subtitle,
            doctrine_context=doctrine_context,
            prompt_version=prompt_version,
        ),
        run_dir=run_dir,
        source_path=source_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        output_markers=SUMMARY_PROCEDURE_OUTPUT_MARKERS,
    )
    output = run.get("output")
    if not isinstance(output, dict):
        raise RuntimeError("Cloud summarization procedure did not return a JSON object payload.")
    summary_text = _clean_text(output.get("summary_text"))
    if not summary_text:
        raise RuntimeError("Cloud summarization procedure output is missing summary_text.")
    return {
        "mode": _clean_text(output.get("mode")) or mode,
        "summary_text": summary_text,
        "prompt_version": _clean_text(output.get("prompt_version")) or _clean_text(prompt_version),
        "model": _clean_text(output.get("model")) or _clean_text(model),
    }


def generate_outcome_summary(
    source_text: str,
    *,
    reference: dict[str, Any],
    title: str,
    subtitle: str,
    max_tokens: int = TITLE_SUBTITLE_SUMMARY_TOKEN_BUDGET_DEFAULT,
    model: str = "gpt-5.4-mini",
    procedure_alias: str = SUMMARY_PROCEDURE_ALIAS_TITLE_SUBTITLE_RESOLVE,
) -> dict[str, str]:
    source_text = _required(source_text, "source_text").replace("\x00", "")
    budget = normalize_title_subtitle_summary_budget(max_tokens)
    return _run_reference_summarization_cloud_procedure(
        alias=procedure_alias,
        mode="outcome_summary",
        source_text=source_text,
        max_tokens=budget,
        model=model,
        reference=reference,
        title=title,
        subtitle=subtitle,
        prompt_version=TITLE_SUBTITLE_SUMMARY_PROMPT_VERSION,
    )


def reference_web_search(
    *,
    query: str,
    max_results: int = 20,
    model: str = "gpt-5.4-mini",
    return_token_budget: str = "default",
    provider: str | None = None,
) -> dict[str, Any]:
    return web_search_providers.reference_web_search(
        query=query,
        max_results=max_results,
        model=model,
        return_token_budget=return_token_budget,
        provider=provider,
    )


def _generate_title_subtitle_llm(
    *,
    reference: dict[str, Any],
    catalog_entry: dict[str, Any] | None = None,
    source_text: str = "",
    known_title: str = "",
    known_subtitle: str = "",
    model: str = "gpt-5.4-mini",
    web_search_enabled: bool,
) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for title/subtitle LLM enrichment.")
    catalog_entry = catalog_entry or {}
    prompt = build_title_subtitle_prompt(
        reference=reference,
        catalog_entry=catalog_entry,
        source_text=source_text,
        known_title=known_title,
        known_subtitle=known_subtitle,
    )
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": "You resolve bibliographic title metadata for a private editorial knowledge base. Return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "reference_title_subtitle",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "subtitle", "title_mode", "subtitle_mode", "source_urls", "rationale"],
                    "properties": {
                        "title": {"type": "string"},
                        "subtitle": {"type": "string"},
                        "title_mode": {"type": "string"},
                        "subtitle_mode": {"type": "string"},
                        "source_urls": {"type": "array", "items": {"type": "string"}},
                        "rationale": {"type": "string"},
                    },
                },
            },
        },
    }
    web_provider = web_search_providers.normalize_web_search_provider(None)
    supplemental_urls: list[str] = []
    supplemental_answer = ""
    if web_search_enabled and web_provider == "tavily":
        supplemental_urls, supplemental_answer = web_search_providers.web_search_urls_for_title_subtitle(
            reference=reference,
            catalog_entry=catalog_entry,
            known_title=known_title,
        )
        if supplemental_urls or supplemental_answer:
            prompt = "\n".join([
                prompt,
                "",
                "Web search context (Tavily):",
                supplemental_answer or "(no synthesized answer)",
                "Source URLs:",
                "\n".join(f"- {url}" for url in supplemental_urls[:12]) or "(none)",
            ])
            payload["input"][1]["content"] = prompt
    elif web_search_enabled:
        payload["tools"] = [{"type": "web_search"}]
        payload["tool_choice"] = "auto"
        payload["include"] = ["web_search_call.action.sources"]
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        lane = "web+LLM" if web_search_enabled else "tool-less"
        raise RuntimeError(f"OpenAI title/subtitle {lane} request failed: {error.code} {body[:400]}") from error
    text = _extract_response_text(parsed)
    if not text:
        raise RuntimeError("OpenAI title/subtitle request returned no text.")
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI title/subtitle request did not return JSON.") from exc
    urls = _string_list(result.get("source_urls") or [])
    if web_search_enabled and web_provider == "openai":
        urls.extend(_web_search_source_urls(parsed))
    elif web_search_enabled:
        urls.extend(supplemental_urls)
    return {
        "title": _clean_text(result.get("title")),
        "subtitle": _clean_text(result.get("subtitle")),
        "title_mode": _title_subtitle_mode(result.get("title_mode"), default="original_web_metadata"),
        "subtitle_mode": _title_subtitle_mode(result.get("subtitle_mode"), default="generated"),
        "source_urls": sorted(set(urls)),
        "rationale": _clean_text(result.get("rationale")),
        "promptVersion": TITLE_SUBTITLE_PROMPT_VERSION,
        "model": model,
    }


def generate_title_subtitle_without_web_search(
    *,
    reference: dict[str, Any],
    catalog_entry: dict[str, Any] | None = None,
    source_text: str = "",
    known_title: str = "",
    known_subtitle: str = "",
    model: str = "gpt-5.4-mini",
) -> dict[str, Any]:
    return _generate_title_subtitle_llm(
        reference=reference,
        catalog_entry=catalog_entry,
        source_text=source_text,
        known_title=known_title,
        known_subtitle=known_subtitle,
        model=model,
        web_search_enabled=False,
    )


def generate_title_subtitle_with_web_search(
    *,
    reference: dict[str, Any],
    catalog_entry: dict[str, Any] | None = None,
    source_text: str = "",
    known_title: str = "",
    known_subtitle: str = "",
    model: str = "gpt-5.4-mini",
) -> dict[str, Any]:
    return _generate_title_subtitle_llm(
        reference=reference,
        catalog_entry=catalog_entry,
        source_text=source_text,
        known_title=known_title,
        known_subtitle=known_subtitle,
        model=model,
        web_search_enabled=True,
    )


def generate_quality_assessment(
    source_text: str,
    *,
    reference: dict[str, Any],
    model: str,
    doctrine_context: dict[str, Any] | None = None,
    rubric: str = QUALITY_ASSESSMENT_RUBRIC,
) -> dict[str, Any]:
    source_text = _required(source_text, "source_text")
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for automated quality assessment.")
    prompt = build_quality_assessment_prompt(
        source_text,
        reference=reference,
        rubric=rubric,
        doctrine_context=doctrine_context,
    )
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": "You assess source quality for a private editorial knowledge base. You return strict JSON."},
            {"role": "user", "content": prompt},
        ],
        "max_output_tokens": 500,
        "text": {"format": {"type": "json_object"}},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI quality assessment request failed: {error.code} {body[:400]}") from error
    text = _extract_response_text(parsed)
    if not text:
        raise RuntimeError("OpenAI quality assessment request returned no text.")
    assessment = _jsonish(text)
    if not isinstance(assessment, dict):
        raise RuntimeError("OpenAI quality assessment did not return a JSON object.")
    rating = normalize_quality_rating(assessment.get("rating"))
    return {
        "rating": rating,
        "rationale": str(assessment.get("rationale") or "").strip(),
        "evidence": _string_list(assessment.get("evidence") or []),
        "caveats": _string_list(assessment.get("caveats") or []),
        "model": model,
        "promptVersion": QUALITY_ASSESSMENT_PROMPT_VERSION,
        "doctrine": doctrine_summary_metadata(doctrine_context),
    }


def generate_summary(
    source_text: str,
    *,
    max_tokens: int,
    model: str,
    reference: dict[str, Any],
    doctrine_context: dict[str, Any] | None = None,
    procedure_alias: str = SUMMARY_PROCEDURE_ALIAS_SUMMARIZE,
) -> dict[str, str]:
    source_text = _required(source_text, "source_text").replace("\x00", "")
    budget = normalize_summary_budget(max_tokens)
    return _run_reference_summarization_cloud_procedure(
        alias=procedure_alias,
        mode="reference_summary",
        source_text=source_text,
        max_tokens=budget,
        model=model,
        reference=reference,
        doctrine_context=doctrine_context,
        prompt_version=SUMMARY_PROMPT_VERSION,
    )


def resolve_reference_text_generation_context(
    *,
    extracted_text: str,
    original_title: str = "",
    original_subtitle: str = "",
) -> dict[str, Any]:
    normalized_text = str(extracted_text or "").replace("\x00", "").strip()
    errors: list[dict[str, str]] = []
    if not normalized_text:
        errors.append({
            "code": "missing_extracted_text",
            "message": "Extracted text is required before metadata generation.",
        })
    return {
        "ok": not errors,
        "errors": errors,
        "extractedText": normalized_text,
        "originalTitle": _clean_text(original_title),
        "originalSubtitle": _clean_text(original_subtitle),
    }


def generate_title_from_reference_text(
    *,
    reference: dict[str, Any],
    extracted_text: str,
    original_title: str = "",
    original_subtitle: str = "",
    model: str = REFERENCE_METADATA_MODEL_DEFAULT,
) -> dict[str, Any]:
    context = resolve_reference_text_generation_context(
        extracted_text=extracted_text,
        original_title=original_title,
        original_subtitle=original_subtitle,
    )
    if not context["ok"]:
        raise RuntimeError("Cannot generate title without extracted text.")
    result = _run_metadata_map_reduce(
        output_kind="title",
        reference=reference,
        context=context,
        model=model,
    )
    title = _normalize_reference_title_candidate(result.get("value"))
    if not title:
        raise RuntimeError("Title generation returned an empty value.")
    return {
        "title": title,
        "model": model,
        "promptVersion": result["promptVersion"],
        "mapReduce": result["mapReduce"],
    }


def generate_subtitle_from_reference_text(
    *,
    reference: dict[str, Any],
    extracted_text: str,
    original_title: str = "",
    original_subtitle: str = "",
    model: str = REFERENCE_METADATA_MODEL_DEFAULT,
) -> dict[str, Any]:
    context = resolve_reference_text_generation_context(
        extracted_text=extracted_text,
        original_title=original_title,
        original_subtitle=original_subtitle,
    )
    if not context["ok"]:
        raise RuntimeError("Cannot generate subtitle without extracted text.")
    result = _run_metadata_map_reduce(
        output_kind="subtitle",
        reference=reference,
        context=context,
        model=model,
    )
    subtitle = _normalize_subtitle_candidate(result.get("value"))
    if not subtitle:
        raise RuntimeError("Subtitle generation returned an empty value.")
    issue = _generated_subtitle_quality_issue(subtitle, subtitle_mode="generated")
    if issue:
        raise RuntimeError(f"Generated subtitle failed quality checks: {issue}")
    return {
        "subtitle": subtitle,
        "model": model,
        "promptVersion": result["promptVersion"],
        "mapReduce": result["mapReduce"],
    }


def generate_summary_from_reference_text(
    *,
    reference: dict[str, Any],
    extracted_text: str,
    original_title: str = "",
    original_subtitle: str = "",
    model: str = REFERENCE_METADATA_MODEL_DEFAULT,
) -> dict[str, Any]:
    context = resolve_reference_text_generation_context(
        extracted_text=extracted_text,
        original_title=original_title,
        original_subtitle=original_subtitle,
    )
    if not context["ok"]:
        raise RuntimeError("Cannot generate summary without extracted text.")
    result = _run_metadata_map_reduce(
        output_kind="summary",
        reference=reference,
        context=context,
        model=model,
    )
    summary = _normalize_outcome_summary_candidate(result.get("value"))
    if not summary:
        raise RuntimeError("Summary generation returned an empty value.")
    return {
        "summary": summary,
        "model": model,
        "promptVersion": result["promptVersion"],
        "mapReduce": result["mapReduce"],
    }


def reference_generate_metadata_from_extracted_text(
    *,
    reference_id: str,
    extracted_text: str,
    original_title: str = "",
    original_subtitle: str = "",
    model: str = REFERENCE_METADATA_MODEL_DEFAULT,
    apply: bool = False,
    refresh: bool = True,
    reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(reference, dict) and str(reference.get("id") or "").strip():
        resolved_reference = reference
    else:
        semantic = _semantic_client()
        resolved_reference = _resolve_reference(semantic, reference_id)
    reference = resolved_reference
    context = resolve_reference_text_generation_context(
        extracted_text=extracted_text,
        original_title=original_title or str(reference.get("title") or ""),
        original_subtitle=original_subtitle,
    )
    if not context["ok"]:
        return {
            "kind": "reference.metadata.from-extracted-text",
            "status": "skipped_missing_text",
            "reference": _reference_summary(reference),
            "errors": context["errors"],
            "apply": False,
            "action": "skipped_missing_text",
            "records": [],
        }

    now = _now()
    run_id = f"metadata-from-extracted-text-{_hash_short([reference.get('lineageId') or reference.get('id') or '', now])}"
    title_result = generate_title_from_reference_text(
        reference=reference,
        extracted_text=context["extractedText"],
        original_title=context["originalTitle"],
        original_subtitle=context["originalSubtitle"],
        model=model,
    )
    subtitle_result = generate_subtitle_from_reference_text(
        reference=reference,
        extracted_text=context["extractedText"],
        original_title=context["originalTitle"],
        original_subtitle=context["originalSubtitle"],
        model=model,
    )
    summary_result = generate_summary_from_reference_text(
        reference=reference,
        extracted_text=context["extractedText"],
        original_title=context["originalTitle"],
        original_subtitle=context["originalSubtitle"],
        model=model,
    )

    metadata_payload = _load_reference_metadata_payload(reference)
    next_metadata = dict(metadata_payload) if isinstance(metadata_payload, dict) else {}
    next_metadata["title"] = title_result["title"]
    next_metadata["subtitle"] = subtitle_result["subtitle"]
    next_metadata["summary"] = summary_result["summary"]
    prompt_version = title_result["promptVersion"]
    next_metadata["title_subtitle_resolution"] = {
        "status": "resolved",
        "title_mode": "generated_from_extracted_text",
        "subtitle_mode": "generated_from_extracted_text",
        "source": "biblicus_map_reduce",
        "model": model,
        "web_search_used": False,
        "source_urls": [],
        "rationale": "Generated from extracted text with Biblicus map-reduce.",
        "run_id": run_id,
        "resolved_at": now,
        "prompt_version": prompt_version,
        "context": {
            "original_title": context["originalTitle"],
            "original_subtitle": context["originalSubtitle"],
            "extracted_text_chars": len(context["extractedText"]),
            "refresh": bool(refresh),
        },
    }
    next_metadata["summary_resolution"] = _summary_resolution(
        summary=summary_result["summary"],
        summary_token_budget=TITLE_SUBTITLE_SUMMARY_TOKEN_BUDGET_DEFAULT,
        model=model,
        source="biblicus_map_reduce",
        source_urls=[],
        run_id=run_id,
        resolved_at=now,
        rationale="Generated from extracted text with Biblicus map-reduce.",
        prompt_version=prompt_version,
    )
    next_metadata["metadata_generation"] = {
        "promptVersion": prompt_version,
        "model": model,
        "generatedAt": now,
        "source": "biblicus_cli",
        "webSearchUsed": False,
        "title": title_result["mapReduce"],
        "subtitle": subtitle_result["mapReduce"],
        "summary": summary_result["mapReduce"],
    }
    next_metadata["updatedAt"] = now

    metadata_attachment = _model_attachment(
        owner_kind="reference",
        owner_id=reference["id"],
        role="metadata",
        sort_key="metadata",
        filename="metadata.json",
        media_type="application/json",
        content=next_metadata,
        import_run_id=reference.get("importRunId"),
        now=now,
    )
    plan = {
        "kind": "reference.metadata.from-extracted-text",
        "action": "update",
        "status": "generated",
        "reference": _reference_summary(reference),
        "generated": {
            "title": title_result["title"],
            "subtitle": subtitle_result["subtitle"],
            "summary": summary_result["summary"],
        },
        "records": [
            {
                "modelName": "ModelAttachment",
                "action": "create",
                "input": metadata_attachment["record"],
                "body": metadata_attachment["body"],
            }
        ],
        "warnings": [],
    }
    return _apply_plan_if_requested(
        plan,
        apply=apply,
        actor_label=TITLE_SUBTITLE_SOURCE,
        reason="references metadata from extracted text",
    )


def _run_metadata_map_reduce(
    *,
    output_kind: str,
    reference: dict[str, Any],
    context: dict[str, Any],
    model: str,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    del max_output_tokens
    payload = _run_biblicus_summarize_map_reduce(
        output_kind=output_kind,
        reference=reference,
        context=context,
        model=model,
    )
    value = _clean_text(payload.get("value"))
    return {
        "value": value,
        "promptVersion": _clean_text(payload.get("prompt_version")) or BIBLICUS_SUMMARIZE_MAP_REDUCE_PROMPT_VERSION,
        "mapReduce": payload.get("map_reduce") if isinstance(payload.get("map_reduce"), dict) else {},
    }


def _run_biblicus_summarize_map_reduce(
    *,
    output_kind: str,
    reference: dict[str, Any],
    context: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    if not BIBLICUS_ROOT.is_dir():
        raise RuntimeError(f"Biblicus checkout not found at {BIBLICUS_ROOT}")
    command = [
        str(_biblicus_python_executable()),
        "-m",
        "biblicus",
        "summarize",
        "map-reduce",
        "--task",
        output_kind,
        "--model",
        model,
        "--input-json",
        "-",
        "--format",
        "json",
    ]
    input_payload = {
        "extracted_text": context.get("extractedText") or "",
        "original_title": context.get("originalTitle") or "",
        "original_subtitle": context.get("originalSubtitle") or "",
        "reference_title": reference.get("title") or "",
        "source_uri": reference.get("sourceUri") or "",
    }
    env = dict(os.environ)
    biblicus_src = str(BIBLICUS_ROOT / "src")
    env["PYTHONPATH"] = (
        f"{biblicus_src}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else biblicus_src
    )
    completed = subprocess.run(
        command,
        cwd=BIBLICUS_ROOT,
        check=False,
        capture_output=True,
        text=True,
        input=json.dumps(input_payload),
        env=env,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            "Biblicus summarize map-reduce command failed: "
            f"{detail or f'exit status {completed.returncode}'}"
        )
    parsed = _jsonish((completed.stdout or "").strip())
    if not isinstance(parsed, dict):
        raise RuntimeError("Biblicus summarize map-reduce command returned invalid JSON output.")
    if _clean_text(parsed.get("task")) != output_kind:
        raise RuntimeError("Biblicus summarize map-reduce command returned an unexpected task payload.")
    return parsed


def _biblicus_python_executable() -> Path:
    for candidate in (
        BIBLICUS_ROOT / ".venv" / "bin" / "python",
        BIBLICUS_ROOT / ".venv" / "bin" / "python3",
    ):
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def estimate_tokens(text: str, *, model: str = "") -> int:
    if not text:
        return 0
    if tiktoken is not None:
        try:
            encoding = tiktoken.encoding_for_model(model or "gpt-5.4-mini")
        except Exception:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    return max(1, round(len(text.split()) * 1.33))


def _semantic_client() -> PapyrusSemanticClient:
    return PapyrusSemanticClient(_graphql)


def _resolve_reference(semantic: PapyrusSemanticClient, reference_id: str) -> dict[str, Any]:
    reference_id = _required(reference_id, "reference")
    try:
        return semantic.get_reference(reference_id)["reference"]
    except Exception:
        current = semantic._resolve_current_by_lineage("reference", reference_id)
        if current:
            return current
        raise


def _reference_metadata_attachment_id(reference_id: str) -> str:
    return f"model-attachment-{_safe_id('reference')}-{_safe_id(reference_id)}-{_safe_id('metadata')}-{_safe_id('metadata')}"


def _load_reference_metadata_payload(reference: dict[str, Any]) -> dict[str, Any]:
    reference_id = str(reference.get("id") or "").strip()
    if not reference_id:
        return {}
    try:
        from papyrus_content.graphql_authoring import create_authoring_client
        from papyrus_content.model_attachments import download_attachment_buffer

        client, _ = create_authoring_client()
        attachments = client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", reference_id, limit=20)
        metadata_candidates = [
            entry
            for entry in attachments
            if str(entry.get("role") or "").strip() == "metadata"
            and str(entry.get("status") or "").strip() != "deleted"
        ]
        if not metadata_candidates:
            return {}
        attachment = next(
            (entry for entry in metadata_candidates if str(entry.get("status") or "").strip() == "active"),
            metadata_candidates[0],
        )
        payload = download_attachment_buffer(client, attachment)
        if not payload:
            return {}
        parsed = _jsonish(payload.decode("utf-8", errors="replace"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _resolve_source_text(reference: dict[str, Any], *, source_text: str = "", source_text_file: str = "") -> str:
    if source_text:
        return source_text
    if source_text_file:
        return Path(source_text_file).expanduser().read_text(encoding="utf-8", errors="replace")
    storage_path = str(reference.get("storagePath") or "").strip()
    if storage_path:
        candidates = [
            Path(storage_path).expanduser(),
            PAPYRUS_ROOT / storage_path,
            PAPYRUS_ROOT.parent / "Biblicus" / storage_path,
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate.read_text(encoding="utf-8", errors="replace")
    raise RuntimeError(
        "Could not resolve source text for reference. Metadata generation requires extracted text; "
        "fetch extracted text first or pass --source-text-file."
    )


def _get_current_doctrine_item_by_slug(slug: str, graphql_func: Any) -> dict[str, Any] | None:
    records: list[dict[str, Any]] = []
    next_token = None
    while True:
        data = graphql_func(LIST_DOCTRINE_ITEMS_BY_SLUG_QUERY, {"slug": slug, "limit": 100, "nextToken": next_token})
        connection = data.get("itemBySlug") or {}
        records.extend(connection.get("items") or [])
        next_token = connection.get("nextToken")
        if not next_token:
            break
    doctrine_records = [
        record for record in records
        if record and record.get("type") == "doctrine" and record.get("status") == "private"
    ] or [
        record for record in records
        if record and record.get("type") == "doctrine"
    ]
    return _select_current_record(doctrine_records)


def _select_current_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    def rank(record: dict[str, Any]) -> tuple[int, int]:
        state = record.get("versionState")
        state_rank = 0 if state == "current" else 1 if state == "draft" else 8 if state == "superseded" else 5
        try:
            version = int(record.get("versionNumber") or 0)
        except (TypeError, ValueError):
            version = 0
        return (state_rank, -version)

    candidates = [record for record in records if record and record.get("status") != "deprecated"]
    return sorted(candidates, key=rank)[0] if candidates else None


def _doctrine_context_record(record: dict[str, Any]) -> dict[str, Any]:
    editorial = _jsonish(record.get("editorial")) or {}
    body = _string_list(record.get("body") or [])
    return _compact_dict({
        "id": record.get("id"),
        "lineageId": record.get("lineageId"),
        "slug": record.get("slug"),
        "kind": editorial.get("kind") or _doctrine_kind_from_slug(record.get("slug")),
        "label": record.get("headline") or record.get("title") or record.get("slug"),
        "body": body,
        "updatedAt": record.get("updatedAt"),
    })


def _doctrine_kind_from_slug(slug: Any) -> str:
    text = str(slug or "")
    if "policy" in text:
        return "policy"
    if "mission" in text:
        return "mission"
    return "doctrine"


def _format_publication_doctrine_prompt_block(doctrine_context: dict[str, Any]) -> str:
    records = doctrine_context.get("records") if isinstance(doctrine_context, dict) else []
    if not records:
        return "No publication doctrine records were available. Continue using only the Reference text and title."
    sections = []
    for record in records:
        label = str(record.get("label") or record.get("slug") or "Publication Doctrine")
        body = _string_list(record.get("body") or [])
        sections.append("\n".join([f"{label}:", *[f"- {paragraph}" for paragraph in body]]))
    return "\n\n".join(sections)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _with_doctrine_warnings(result: dict[str, Any], doctrine_context: dict[str, Any]) -> dict[str, Any]:
    warnings = [*list(result.get("warnings") or []), *list(doctrine_context.get("warnings") or [])]
    return {**result, "warnings": warnings}


def _quality_assessment_note(assessment: dict[str, Any]) -> str:
    pieces = [
        f"Automated quality assessment ({assessment.get('model')}, {assessment.get('promptVersion')}): {assessment.get('rationale') or ''}".strip(),
    ]
    evidence = _string_list(assessment.get("evidence") or [])
    caveats = _string_list(assessment.get("caveats") or [])
    if evidence:
        pieces.append("Evidence: " + "; ".join(evidence[:3]))
    if caveats:
        pieces.append("Caveats: " + "; ".join(caveats[:3]))
    return "\n".join(piece for piece in pieces if piece)


def _apply_plan_if_requested(plan: dict[str, Any], *, apply: bool, actor_label: str, reason: str) -> dict[str, Any]:
    records = list(plan.get("records") or [])
    if not apply or plan.get("action") == "noop" or not records:
        return {**plan, "apply": False}
    applied = []
    for record in records:
        action = record.get("action")
        model_name = record.get("modelName")
        if model_name == "ModelAttachment":
            _upload_model_attachment(record["input"], record.get("body") or "")
        elif action == "delete":
            _delete_record(model_name, record["input"])
        elif action == "create":
            _create_record(model_name, record["input"])
        elif action == "update":
            _update_record(model_name, record["input"])
        else:
            raise ValueError(f"Unsupported record action: {action}")
        applied.append({"modelName": model_name, "action": action, "id": record.get("input", {}).get("id")})
    summary_delta = plan.get("summaryDelta")
    warnings = list(plan.get("warnings") or [])
    if summary_delta:
        try:
            _update_newsroom_summary(summary_delta, actor_label=actor_label, reason=reason)
        except Exception as exc:  # pragma: no cover - depends on deployed sandbox state
            warnings.append(f"Could not update Newsroom summary snapshot: {exc}")
    return {**plan, "apply": True, "applied": applied, "warnings": warnings}


def _attach_title_subtitle_surface_statuses(
    result: dict[str, Any],
    *,
    references: list[dict[str, Any]],
    apply: bool,
    vector_sync: bool,
) -> dict[str, Any]:
    updated = dict(result)
    local_metadata = updated.get("localMetadata") if isinstance(updated.get("localMetadata"), dict) else {}
    updated["localUpdated"] = bool(local_metadata.get("updated"))
    updated["graphqlUpdated"] = bool(updated.get("applied"))
    if apply and vector_sync and updated["graphqlUpdated"]:
        vector_result = _sync_reference_vectors(references)
    else:
        vector_result = {
            "resultsByLineageId": {},
            "resultsByReferenceId": {},
            "skippedReason": "vector_sync_disabled" if not vector_sync else "not_applied" if not apply else "graphql_not_updated",
        }
    updated["vectorSync"] = vector_result
    _apply_vector_sync_results_to_items([updated], vector_result, default_reference=references[0] if references else None)
    if vector_result.get("failed"):
        updated["partialFailure"] = True
        updated.setdefault("warnings", []).append(vector_result["message"])
    return updated


def _apply_vector_sync_results_to_items(
    items: list[dict[str, Any]],
    vector_result: dict[str, Any],
    *,
    default_reference: dict[str, Any] | None = None,
) -> None:
    by_lineage = vector_result.get("resultsByLineageId") if isinstance(vector_result.get("resultsByLineageId"), dict) else {}
    by_id = vector_result.get("resultsByReferenceId") if isinstance(vector_result.get("resultsByReferenceId"), dict) else {}
    skipped_reason = vector_result.get("skippedReason")
    failed = bool(vector_result.get("failed"))
    for item in items:
        reference = item.get("reference") if isinstance(item.get("reference"), dict) else default_reference or {}
        lineage_id = reference.get("lineageId")
        reference_id = reference.get("id")
        status = (
            by_lineage.get(str(lineage_id)) if lineage_id is not None else None
        ) or (
            by_id.get(str(reference_id)) if reference_id is not None else None
        )
        if status:
            item["vectorIndexUpdated"] = bool(status.get("updated"))
            item["vectorIndexSkipped"] = status.get("skipped")
            item["vectorIndexFailed"] = status.get("failed")
            continue
        item["vectorIndexUpdated"] = False
        item["vectorIndexSkipped"] = skipped_reason or ("failed" if failed else "not_requested")
        item["vectorIndexFailed"] = vector_result.get("message") if failed else None


def _sync_reference_vectors(references: list[dict[str, Any]]) -> dict[str, Any]:
    references = [reference for reference in references if isinstance(reference, dict)]
    if not references:
        return {
            "requested": 0,
            "eligible": 0,
            "resultsByLineageId": {},
            "resultsByReferenceId": {},
            "skippedReason": "no_graphql_updates",
        }
    results_by_lineage: dict[str, dict[str, Any]] = {}
    results_by_reference: dict[str, dict[str, Any]] = {}
    eligible: list[dict[str, Any]] = []
    for reference in references:
        lineage_id = str(reference.get("lineageId") or "")
        reference_id = str(reference.get("id") or "")
        if not _reference_is_vector_eligible(reference):
            result = {"updated": False, "skipped": "not_accepted", "failed": None}
            if lineage_id:
                results_by_lineage[lineage_id] = result
            if reference_id:
                results_by_reference[reference_id] = result
            continue
        eligible.append(reference)
    if not eligible:
        return {
            "requested": len(references),
            "eligible": 0,
            "resultsByLineageId": results_by_lineage,
            "resultsByReferenceId": results_by_reference,
            "skippedReason": "not_accepted",
        }

    from papyrus_knowledge_query.services import build_environment_services
    from papyrus_knowledge_query.vector_index import VectorIndexOptions, index_reference_passages

    reference_ids = tuple(
        str(reference.get("lineageId") or reference.get("id"))
        for reference in eligible
        if reference.get("lineageId") or reference.get("id")
    )
    try:
        payload = index_reference_passages(
            build_environment_services(),
            VectorIndexOptions(
                action="sync",
                reference_ids=reference_ids,
                force=True,
                progress_every=0,
            ),
        )
    except Exception as exc:
        command = _reference_vector_sync_command(reference_ids)
        message = f"Vector index sync failed after GraphQL/local updates. Retry with: {command}. Error: {exc}"
        for reference in eligible:
            lineage_id = str(reference.get("lineageId") or "")
            reference_id = str(reference.get("id") or "")
            result = {"updated": False, "skipped": None, "failed": message}
            if lineage_id:
                results_by_lineage[lineage_id] = result
            if reference_id:
                results_by_reference[reference_id] = result
        return {
            "requested": len(references),
            "eligible": len(eligible),
            "failed": True,
            "message": message,
            "nextSuggestedCommand": command,
            "resultsByLineageId": results_by_lineage,
            "resultsByReferenceId": results_by_reference,
        }

    for reference_result in payload.get("referenceResults") or []:
        lineage_id = str(reference_result.get("referenceLineageId") or "")
        reference_id = str(reference_result.get("referenceId") or "")
        status = str(reference_result.get("status") or "")
        mapped = {
            "updated": status == "indexed",
            "skipped": None if status == "indexed" else status or "unknown",
            "failed": None,
        }
        if lineage_id:
            results_by_lineage[lineage_id] = mapped
        if reference_id:
            results_by_reference[reference_id] = mapped
    for reference in eligible:
        lineage_id = str(reference.get("lineageId") or "")
        reference_id = str(reference.get("id") or "")
        if lineage_id and lineage_id not in results_by_lineage:
            result = {"updated": False, "skipped": "not_reported", "failed": None}
            results_by_lineage[lineage_id] = result
            if reference_id:
                results_by_reference[reference_id] = result
    return {
        "requested": len(references),
        "eligible": len(eligible),
        "failed": False,
        "payload": payload,
        "resultsByLineageId": results_by_lineage,
        "resultsByReferenceId": results_by_reference,
    }


def _reference_vector_sync_command(reference_ids: tuple[str, ...]) -> str:
    flags = " ".join(f"--reference-id {reference_id}" for reference_id in reference_ids)
    return f"poetry run papyrus knowledge-vector-index --action sync --force --progress-every 0 {flags}".strip()


def _reference_is_vector_eligible(reference: dict[str, Any]) -> bool:
    return (
        reference.get("versionState") == "current"
        and str(reference.get("curationStatus") or "").lower() == "accepted"
    )


def _create_record(model_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    query = f"""
mutation Create{model_name}($input: Create{model_name}Input!) {{
  create{model_name}(input: $input) {{ id }}
}}
"""
    return _graphql(query, {"input": _prepare_graphql_input(input_payload)})


def _update_record(model_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    query = f"""
mutation Update{model_name}($input: Update{model_name}Input!) {{
  update{model_name}(input: $input) {{ id }}
}}
"""
    return _graphql(query, {"input": _prepare_graphql_input(input_payload)})


def _delete_record(model_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    query = f"""
mutation Delete{model_name}($input: Delete{model_name}Input!) {{
  delete{model_name}(input: $input) {{ id }}
}}
"""
    return _graphql(query, {"input": _prepare_graphql_input(input_payload)})


def _upload_model_attachment(attachment: dict[str, Any], body: str) -> None:
    body_bytes = body.encode("utf-8")
    upload_args = {
        "ownerKind": attachment["ownerKind"],
        "ownerId": attachment["ownerId"],
        "ownerLineageId": attachment.get("ownerLineageId"),
        "ownerVersionNumber": attachment.get("ownerVersionNumber"),
        "ownerVersionKey": attachment.get("ownerVersionKey"),
        "role": attachment["role"],
        "sortKey": attachment["sortKey"],
        "filename": attachment["filename"],
        "mediaType": attachment["mediaType"],
        "byteSize": len(body_bytes),
        "sha256": hashlib.sha256(body_bytes).hexdigest(),
        "importRunId": attachment.get("importRunId"),
        "status": attachment.get("status") or "active",
    }
    slot = _graphql(CREATE_MODEL_ATTACHMENT_UPLOAD_MUTATION, upload_args).get("createModelAttachmentUpload") or {}
    upload_url = slot.get("uploadUrl")
    if not upload_url:
        raise RuntimeError("createModelAttachmentUpload did not return uploadUrl")
    headers = _jsonish(slot.get("requiredHeaders")) or {}
    request = urllib.request.Request(upload_url, data=body_bytes, headers={str(k): str(v) for k, v in headers.items()}, method="PUT")
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status >= 400:
            raise RuntimeError(f"ModelAttachment upload failed with HTTP {response.status}")
    _graphql(COMPLETE_MODEL_ATTACHMENT_UPLOAD_MUTATION, {"uploadId": slot["uploadId"], **upload_args})


def _update_newsroom_summary(delta: dict[str, Any], *, actor_label: str, reason: str) -> None:
    _graphql(UPDATE_NEWSROOM_SUMMARY_MUTATION, {
        "delta": json.dumps(delta, sort_keys=True),
        "actorLabel": actor_label,
        "reason": reason,
    })


def _summary_delta_for_plan(
    *,
    messages: int,
    model_attachments: int,
    created_relations: int,
    superseded_relations: int,
    relation_type_key: str,
    relation_domain: str,
    subject_kind: str,
    object_kind: str,
    semantic_nodes: int = 0,
) -> dict[str, Any]:
    relation_delta = created_relations - superseded_relations
    return {
        "source": "incremental",
        "countDeltas": {
            "messages": messages,
            "modelAttachments": model_attachments,
            "semanticRelations": relation_delta,
            "semanticNodes": semantic_nodes,
        },
        "messageKindDeltas": {"reference_summary": messages} if messages else {},
        "messageDomainDeltas": {"summarization": messages} if messages else {},
        "facetDeltas": {
            "messages": {
                "byKind": {"reference_summary": messages} if messages else {},
                "byDomain": {"summarization": messages} if messages else {},
                "byStatus": {"active": messages} if messages else {},
                "domainByKind": {"reference_summary": {"summarization": messages}} if messages else {},
            },
            "semanticRelations": {
                "byRelationTypeKey": {relation_type_key: relation_delta} if relation_delta else {},
                "byRelationDomain": {relation_domain: relation_delta} if relation_delta else {},
                "bySubjectKind": {subject_kind: relation_delta} if relation_delta else {},
                "byObjectKind": {object_kind: relation_delta} if relation_delta else {},
            },
        },
    }


def _semantic_relation(
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
    score: float | None,
    confidence: float | None,
    rank: int | None,
    classifier_id: str | None,
    model_version: str | None,
    import_run_id: str | None,
    imported_at: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    subject_state_key = semantic_state_key(subject_kind, subject_lineage_id)
    object_state_key = semantic_state_key(object_kind, object_lineage_id)
    relation = {
        "id": "semantic-relation-" + _hash_short([semantic_version_key(subject_kind, subject_id), predicate, semantic_version_key(object_kind, object_id), imported_at]),
        "relationState": "current",
        "predicate": predicate,
        **_relation_type_fields(predicate),
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
        "subjectVersionKey": semantic_version_key(subject_kind, subject_id),
        "objectVersionKey": semantic_version_key(object_kind, object_id),
        "score": score,
        "confidence": confidence,
        "rank": rank,
        "classifierId": classifier_id,
        "modelVersion": model_version,
        "reviewRecommended": False,
        "importRunId": import_run_id,
        "importedAt": imported_at,
        "createdAt": imported_at,
        "updatedAt": imported_at,
        "newsroomFeedKey": "semanticRelations",
        "metadata": metadata,
    }
    return {key: value for key, value in relation.items() if value is not None}


def _quality_semantic_node_record(rating: int, now: str) -> dict[str, Any]:
    rating = normalize_quality_rating(rating)
    names = {
        1: ("One-Star Quality", "The lowest accepted quality rating for a reference."),
        2: ("Two-Star Quality", "A low quality rating for a reference."),
        3: ("Three-Star Quality", "A neutral or adequate quality rating for a reference."),
        4: ("Four-Star Quality", "A strong quality rating for a reference."),
        5: ("Five-Star Quality", "The highest accepted quality rating for a reference."),
    }
    display_name, description = names[rating]
    node_key = quality_node_key(rating)
    record = {
        "id": quality_node_id(rating),
        "lineageId": quality_node_lineage_id(rating),
        "versionNumber": 1,
        "previousVersionId": None,
        "versionState": "current",
        "versionCreatedAt": now,
        "versionCreatedBy": "papyrus",
        "changeReason": "qualityRating-seed",
        "contentHash": _hash_short([node_key, QUALITY_NODE_KIND, display_name, description]),
        "nodeKey": node_key,
        "nodeKind": QUALITY_NODE_KIND,
        "corpusId": None,
        "categorySetId": None,
        "categoryLineageId": None,
        "categoryKey": None,
        "displayName": display_name,
        "description": description,
        "aliases": [f"{rating} star", f"{rating} stars"],
        "status": "accepted",
        "createdAt": now,
        "newsroomFeedKey": "semanticNodes",
        "updatedAt": now,
    }
    return {key: value for key, value in record.items() if value is not None}


def _relation_type_fields(predicate: str) -> dict[str, str]:
    key = _normalize_relation_type_key(predicate)
    domain = "curation" if key == QUALITY_RELATION_TYPE_KEY else "summarization" if key.startswith("reference_summary_") else "generic"
    return {
        "relationTypeId": f"semantic-relation-type-{_safe_id(key)}",
        "relationTypeKey": key,
        "relationDomain": domain,
    }


def _model_attachment(
    *,
    owner_kind: str,
    owner_id: str,
    role: str,
    sort_key: str,
    filename: str,
    media_type: str,
    content: Any,
    import_run_id: str | None,
    now: str,
) -> dict[str, Any]:
    body = content if isinstance(content, str) else json.dumps(content or {}, indent=2, sort_keys=True) + "\n"
    body_bytes = body.encode("utf-8")
    attachment = {
        "id": f"model-attachment-{_safe_id(owner_kind)}-{_safe_id(owner_id)}-{_safe_id(role)}-{_safe_id(sort_key)}",
        "ownerKind": owner_kind,
        "ownerId": owner_id,
        "ownerLineageId": owner_id,
        "ownerVersionNumber": None,
        "ownerVersionKey": None,
        "role": role,
        "sortKey": sort_key,
        "storagePath": f"newsroom/payloads/{_safe_id(owner_kind)}/{_safe_id(owner_id)}/{_safe_id(role)}/{filename}",
        "filename": filename,
        "mediaType": media_type,
        "byteSize": len(body_bytes),
        "sha256": hashlib.sha256(body_bytes).hexdigest(),
        "etag": None,
        "importRunId": import_run_id,
        "createdAt": now,
        "updatedAt": now,
        "status": "active",
    }
    return {"record": attachment, "body": body}


def _supersede_relation_record(relation: dict[str, Any], now: str, metadata_patch: dict[str, Any]) -> dict[str, Any]:
    metadata = _jsonish(relation.get("metadata")) or {}
    metadata.update(metadata_patch)
    return {
        "modelName": "SemanticRelation",
        "action": "update",
        "input": {
            "id": relation["id"],
            "relationState": "superseded",
            "updatedAt": now,
            "metadata": metadata,
        },
    }


def _current_relations(relations: list[dict[str, Any]], relation_type_key: str) -> list[dict[str, Any]]:
    return [
        relation for relation in relations
        if relation.get("relationState") == "current"
        and (relation.get("relationTypeKey") == relation_type_key or relation.get("predicate") == relation_type_key)
    ]


def _quality_from_relation(relation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not relation:
        return None
    score = _number_or_none(relation.get("score"))
    rating = int(score) if score and score.is_integer() else _rating_from_node_key(relation.get("objectLineageId") or relation.get("objectId"))
    return {
        "rating": rating,
        "relationId": relation.get("id"),
        "nodeLineageId": relation.get("objectLineageId"),
        "score": rating,
        "metadata": _jsonish(relation.get("metadata")) or {},
    }


def _quality_relation_for_output(relation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not relation:
        return None
    output = dict(relation)
    output.pop("confidence", None)
    quality = _quality_from_relation(relation)
    if quality and quality.get("rating") is not None:
        output["score"] = quality["rating"]
    return output


def _rating_from_node_key(value: Any) -> int | None:
    match = re.search(r"([1-5])[-_.]?star", str(value or ""))
    return int(match.group(1)) if match else None


def _prepare_graphql_input(input_payload: dict[str, Any]) -> dict[str, Any]:
    prepared = {key: value for key, value in input_payload.items() if value is not None}
    if "metadata" in prepared and not isinstance(prepared["metadata"], str):
        prepared["metadata"] = json.dumps(prepared["metadata"], sort_keys=True)
    return prepared


def _graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    from papyrus_content.graphql_http import execute_graphql

    return execute_graphql(query, variables, timeout=60)


def _extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            if isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks)


def _reference_summary(reference: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": reference.get("id"),
        "lineageId": reference.get("lineageId"),
        "versionNumber": reference.get("versionNumber"),
        "corpusId": reference.get("corpusId"),
        "externalItemId": reference.get("externalItemId"),
        "title": reference.get("title"),
        "curationStatus": reference.get("curationStatus"),
    }


def _normalize_reference_list_order(order: str) -> str:
    normalized = str(order or "").strip().lower().replace("_", "-")
    if normalized in {"imported", "import", "import-date", "imported-newest"}:
        return "imported"
    if normalized in {"imported-oldest", "import-oldest"}:
        return "imported-oldest"
    if normalized in {"published", "publication", "publication-date", "published-newest"}:
        return "published"
    if normalized in {"published-oldest", "publication-oldest"}:
        return "published-oldest"
    if normalized == "oldest":
        return "oldest"
    return "newest"


def _reference_list_sort_key(order: str) -> Callable[[dict[str, Any]], str]:
    normalized = _normalize_reference_list_order(order)
    if normalized.startswith("imported"):
        return _reference_imported_key
    if normalized.startswith("published"):
        return _reference_publication_key
    return _reference_chrono_key


def _reference_imported_key(reference: dict[str, Any]) -> str:
    return str(reference.get("importedAt") or reference.get("createdAt") or reference.get("id") or "")


def _reference_publication_key(reference: dict[str, Any]) -> str:
    return str(
        reference.get("sourcePublishedAt")
        or reference.get("sourceUpdatedAt")
        or reference.get("retrievedAt")
        or reference.get("importedAt")
        or reference.get("updatedAt")
        or reference.get("id")
        or ""
    )


def _reference_chrono_key(reference: dict[str, Any]) -> str:
    return str(
        reference.get("importedAt")
        or reference.get("updatedAt")
        or reference.get("retrievedAt")
        or reference.get("sourceUpdatedAt")
        or reference.get("sourcePublishedAt")
        or reference.get("id")
        or ""
    )


def _catalog_entry_chrono_key(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    dates = item.get("dates") if isinstance(item.get("dates"), dict) else {}
    metadata_dates = metadata.get("dates") if isinstance(metadata.get("dates"), dict) else {}
    return str(
        item.get("created_at")
        or item.get("updated_at")
        or item.get("imported_at")
        or item.get("retrieved_at")
        or dates.get("updated_at")
        or dates.get("retrieved_at")
        or dates.get("published_at")
        or metadata.get("created_at")
        or metadata.get("updated_at")
        or metadata.get("imported_at")
        or metadata.get("retrieved_at")
        or metadata_dates.get("updated_at")
        or metadata_dates.get("retrieved_at")
        or metadata_dates.get("published_at")
        or item.get("id")
        or ""
    )


def build_title_subtitle_local_metadata_plan(*, reference: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    sidecar_path = _sidecar_path_for_reference(reference)
    catalog_path, catalog_item_key = _catalog_location_for_reference(reference)
    return {
        "kind": "reference.title-subtitle.local-metadata.plan",
        "referenceId": reference.get("id"),
        "externalItemId": reference.get("externalItemId"),
        "title": resolution.get("title"),
        "subtitle": resolution.get("subtitle"),
        "summary": resolution.get("summary"),
        "sidecarPath": str(sidecar_path) if sidecar_path else None,
        "catalogPath": str(catalog_path) if catalog_path else None,
        "catalogItemKey": catalog_item_key,
    }


def apply_title_subtitle_local_metadata(*, reference: dict[str, Any], resolution: dict[str, Any]) -> dict[str, Any]:
    sidecar_path = _sidecar_path_for_reference(reference)
    catalog_path, catalog_item_key = _catalog_location_for_reference(reference)
    updated = []
    skipped = []
    errors = []
    if sidecar_path:
        try:
            existed = sidecar_path.exists()
            parsed = _read_yaml_file(sidecar_path) if existed else {}
            _apply_title_subtitle_to_mapping(parsed, resolution)
            sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            sidecar_path.write_text(_dump_yaml(parsed), encoding="utf-8")
            updated.append({"target": "sidecar", "path": str(sidecar_path), "created": not existed})
        except Exception as exc:
            errors.append({"target": "sidecar", "path": str(sidecar_path), "error": str(exc)})
    else:
        skipped.append({"target": "sidecar", "reason": "missing_local_source_path"})
    if catalog_path and catalog_item_key:
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            items = catalog.get("items") if isinstance(catalog, dict) else None
            item = items.get(catalog_item_key) if isinstance(items, dict) else None
            if not isinstance(item, dict):
                skipped.append({"target": "catalog", "path": str(catalog_path), "reason": "catalog_item_not_found"})
            else:
                items[catalog_item_key] = apply_title_subtitle_to_catalog_item(item, resolution=resolution)
                catalog_path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                updated.append({"target": "catalog", "path": str(catalog_path), "itemKey": catalog_item_key})
        except Exception as exc:
            errors.append({"target": "catalog", "path": str(catalog_path), "error": str(exc)})
    else:
        skipped.append({"target": "catalog", "reason": "catalog_not_found"})
    return {
        "kind": "reference.title-subtitle.local-metadata.applied",
        "referenceId": reference.get("id"),
        "externalItemId": reference.get("externalItemId"),
        "title": resolution.get("title"),
        "subtitle": resolution.get("subtitle"),
        "summary": resolution.get("summary"),
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


def apply_title_subtitle_to_catalog_item(item: dict[str, Any], *, resolution: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(item)
    metadata = dict(enriched.get("metadata") if isinstance(enriched.get("metadata"), dict) else {})
    if _is_biblicus_catalog_item(enriched):
        title = _clean_text(resolution.get("title"))
        if title:
            enriched["title"] = title
        _apply_title_subtitle_to_mapping(metadata, resolution)
        enriched["metadata"] = metadata
        for key in CATALOG_EXTENSION_ROOT_FIELDS:
            enriched.pop(key, None)
        return enriched
    _apply_title_subtitle_to_mapping(enriched, resolution)
    _apply_title_subtitle_to_mapping(metadata, resolution)
    enriched["metadata"] = metadata
    return enriched


def _is_biblicus_catalog_item(item: dict[str, Any]) -> bool:
    return bool(_clean_text(item.get("relpath")) and _clean_text(item.get("sha256")))


def _apply_title_subtitle_to_mapping(target: dict[str, Any], resolution: dict[str, Any]) -> None:
    title = _clean_text(resolution.get("title"))
    subtitle = _normalize_subtitle_candidate(resolution.get("subtitle"))
    summary = _normalize_outcome_summary_candidate(resolution.get("summary"))
    identifier_metadata = _identifier_metadata_update(
        metadata=target if isinstance(target, dict) else {},
        identifier_prepass=resolution.get("identifierPrepass") if isinstance(resolution, dict) else {},
    )
    if title:
        target["title"] = title
    if subtitle:
        target["subtitle"] = subtitle
    if summary:
        target["summary"] = summary
    target["identifiers"] = identifier_metadata.get("identifiers") or {}
    target["identifier_resolution"] = identifier_metadata.get("identifier_resolution") or {}
    papyrus = target.get("papyrus") if isinstance(target.get("papyrus"), dict) else {}
    papyrus["title_subtitle"] = {
        "title": title,
        "subtitle": subtitle,
        "summary": summary,
        **_title_subtitle_provenance(resolution),
    }
    papyrus["title_subtitle"]["identifier_prepass"] = {
        "status": (resolution.get("identifierPrepass") or {}).get("status"),
        "failureReason": (resolution.get("identifierPrepass") or {}).get("failureReason"),
        "extracted": (resolution.get("identifierPrepass") or {}).get("extracted") or {},
    }
    if summary:
        papyrus["title_subtitle"]["summary_resolution"] = _summary_resolution_provenance(resolution)
    target["papyrus"] = papyrus
    target["title_subtitle_resolution"] = _title_subtitle_provenance(resolution)
    if summary:
        target["summary_resolution"] = _summary_resolution_provenance(resolution)


def _quality_local_metadata_payload(*, rating: int, note: str, actor_label: str, now: str) -> dict[str, Any]:
    return _compact_dict({
        "rating": rating,
        "rating_node_key": quality_node_key(rating),
        "relation_type_key": QUALITY_RELATION_TYPE_KEY,
        "rated_at": now,
        "updated_by": actor_label,
        "note": note,
    })


def _quality_rating_from_metadata(value: Any) -> int | None:
    if not isinstance(value, dict):
        return None
    for container in (
        value.get("quality"),
        value.get("papyrus", {}).get("quality_rating") if isinstance(value.get("papyrus"), dict) else None,
    ):
        if isinstance(container, dict):
            try:
                return normalize_quality_rating(container.get("rating"))
            except ValueError:
                continue
    return None


def _title_subtitle_from_local(*, reference: dict[str, Any], catalog_entry: dict[str, Any], sidecar: dict[str, Any]) -> dict[str, Any]:
    sources = [
        ("reference", reference),
        ("catalog", catalog_entry),
        ("sidecar", sidecar),
        ("reference_metadata", _jsonish(reference.get("metadata")) or {}),
        ("catalog_metadata", catalog_entry.get("metadata") if isinstance(catalog_entry.get("metadata"), dict) else {}),
        ("sidecar_papyrus", sidecar.get("papyrus", {}).get("title_subtitle") if isinstance(sidecar.get("papyrus"), dict) else {}),
    ]
    title = ""
    subtitle = ""
    summary = ""
    title_source = ""
    subtitle_source = ""
    summary_source = ""
    for label, value in sources:
        if not isinstance(value, dict):
            continue
        if not title:
            title = _normalize_reference_title_candidate(value.get("title") or value.get("original_title") or value.get("originalTitle"))
            if title:
                title_source = label
        if not subtitle:
            subtitle = _clean_text(value.get("subtitle") or value.get("sub_title") or value.get("subTitle") or value.get("deck"))
            if subtitle:
                subtitle_source = label
        if not summary:
            summary = _normalize_outcome_summary_candidate(value.get("summary"))
            if summary:
                summary_source = label
    return {
        "title": title,
        "subtitle": subtitle,
        "summary": summary,
        "titleMode": "original_metadata" if title else None,
        "subtitleMode": "original_metadata" if subtitle else None,
        "summarySource": summary_source,
        "source": title_source or subtitle_source or "",
        "rationale": f"Resolved from local {title_source or subtitle_source} metadata." if (title or subtitle) else "",
        "summaryRationale": f"Resolved summary from local {summary_source} metadata." if summary else "",
    }


def _run_identifier_prepass(*, reference: dict[str, Any], catalog_entry: dict[str, Any]) -> dict[str, Any]:
    try:
        ref = reference if isinstance(reference, dict) else {}
        catalog = catalog_entry if isinstance(catalog_entry, dict) else {}
        extracted: dict[str, Any] = {}
        identifiers: dict[str, str] = {}
        resolution: dict[str, Any] = {}

        for identifier_type in IDENTIFIER_PREPASS_TYPES:
            selected, candidates = _select_identifier_prepass_candidate(
                identifier_type=identifier_type,
                reference=ref,
                catalog_entry=catalog,
            )
            if selected:
                value = selected.get("value") or ""
                identifiers[identifier_type] = value
                extracted[identifier_type] = {
                    "value": value,
                    "source": selected.get("source") or "",
                    "sourceRank": selected.get("sourceRank"),
                    "raw": selected.get("raw") or "",
                }
            resolution[identifier_type] = {
                "selectedValue": selected.get("value") if selected else "",
                "selectedSource": selected.get("source") if selected else "",
                "selectedSourceRank": selected.get("sourceRank") if selected else None,
                "candidates": [
                    {
                        "value": candidate.get("value") or "",
                        "source": candidate.get("source") or "",
                        "sourceRank": candidate.get("sourceRank"),
                        "raw": candidate.get("raw") or "",
                    }
                    for candidate in candidates
                ],
            }

        status = "ok" if identifiers else "no_identifier_found"
        return {
            "status": status,
            "failureReason": "",
            "identifiers": identifiers,
            "extracted": extracted,
            "resolution": resolution,
            "sourceOrder": list(IDENTIFIER_PREPASS_SOURCE_ORDER.keys()),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "failureReason": str(exc),
            "identifiers": {},
            "extracted": {},
            "resolution": {},
            "sourceOrder": list(IDENTIFIER_PREPASS_SOURCE_ORDER.keys()),
        }


def _identifier_metadata_update(*, metadata: dict[str, Any], identifier_prepass: dict[str, Any]) -> dict[str, Any]:
    current_metadata = metadata if isinstance(metadata, dict) else {}
    prepass = identifier_prepass if isinstance(identifier_prepass, dict) else {}
    existing = _identifiers_from_mapping(current_metadata)
    prepass_identifiers = prepass.get("identifiers") if isinstance(prepass.get("identifiers"), dict) else {}
    prepass_resolution = prepass.get("resolution") if isinstance(prepass.get("resolution"), dict) else {}

    merged: dict[str, str] = {}
    resolution_types: dict[str, Any] = {}
    for identifier_type in IDENTIFIER_PREPASS_TYPES:
        existing_value = _normalize_identifier_value(identifier_type, existing.get(identifier_type))
        proposed_value = _normalize_identifier_value(identifier_type, prepass_identifiers.get(identifier_type))
        chosen_value = existing_value or proposed_value
        if chosen_value:
            merged[identifier_type] = chosen_value

        type_resolution = prepass_resolution.get(identifier_type) if isinstance(prepass_resolution.get(identifier_type), dict) else {}
        selected_source = str(type_resolution.get("selectedSource") or "")
        selected_source_rank = type_resolution.get("selectedSourceRank")
        if existing_value:
            selected_source = "metadata.identifiers"
            selected_source_rank = IDENTIFIER_PREPASS_SOURCE_ORDER.get("metadata.identifiers", 0)
        resolution_types[identifier_type] = {
            "value": chosen_value or "",
            "selectedSource": selected_source,
            "selectedSourceRank": selected_source_rank,
            "candidates": type_resolution.get("candidates") if isinstance(type_resolution.get("candidates"), list) else [],
            "preservedExisting": bool(existing_value and proposed_value and existing_value != proposed_value),
            "discardedInferredValue": proposed_value if existing_value and proposed_value and existing_value != proposed_value else "",
        }

    status = str(prepass.get("status") or "").strip() or ("ok" if merged else "no_identifier_found")
    if status != "failed" and merged:
        status = "ok"

    return {
        "identifiers": merged,
        "identifier_resolution": {
            "status": status,
            "failureReason": str(prepass.get("failureReason") or ""),
            "sourceOrder": list(IDENTIFIER_PREPASS_SOURCE_ORDER.keys()),
            "types": resolution_types,
        },
    }


def _select_identifier_prepass_candidate(
    *,
    identifier_type: str,
    reference: dict[str, Any],
    catalog_entry: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    candidates_by_value: dict[str, dict[str, Any]] = {}
    for source, raw in _identifier_raw_inputs(
        identifier_type=identifier_type,
        reference=reference,
        catalog_entry=catalog_entry,
    ):
        value = _normalize_identifier_value(identifier_type, raw)
        if not value:
            continue
        source_rank = _identifier_source_rank(source)
        candidate = {
            "value": value,
            "source": source,
            "sourceRank": source_rank,
            "raw": _clean_text(raw),
        }
        existing = candidates_by_value.get(value)
        if existing is None:
            candidates_by_value[value] = candidate
            continue
        if source_rank < _identifier_candidate_rank(existing):
            candidates_by_value[value] = candidate
            continue

    candidates = sorted(
        candidates_by_value.values(),
        key=lambda candidate: (
            _identifier_candidate_rank(candidate),
            str(candidate.get("source") or ""),
            str(candidate.get("value") or ""),
        ),
    )
    return (candidates[0] if candidates else None, candidates)


def _identifier_raw_inputs(
    *,
    identifier_type: str,
    reference: dict[str, Any],
    catalog_entry: dict[str, Any],
) -> list[tuple[str, str]]:
    reference_metadata = _jsonish(reference.get("metadata")) or {}
    catalog_metadata = catalog_entry.get("metadata") if isinstance(catalog_entry.get("metadata"), dict) else {}

    values: list[tuple[str, str]] = []

    def _append(source: str, candidate: Any) -> None:
        text = _clean_text(candidate)
        if text:
            values.append((source, text))

    aliases = IDENTIFIER_ALIASES.get(identifier_type, (identifier_type,))
    for mapping in (
        reference_metadata.get("identifiers") if isinstance(reference_metadata.get("identifiers"), dict) else {},
        catalog_metadata.get("identifiers") if isinstance(catalog_metadata.get("identifiers"), dict) else {},
    ):
        for alias in aliases:
            _append("metadata.identifiers", mapping.get(alias))

    for mapping in (reference, catalog_entry, reference_metadata, catalog_metadata):
        if not isinstance(mapping, dict):
            continue
        for alias in aliases:
            _append("explicit_field", mapping.get(alias))

    source_uri_fields = ("sourceUri", "source_uri", "url", "uri")
    for mapping in (reference, catalog_entry, reference_metadata, catalog_metadata):
        if not isinstance(mapping, dict):
            continue
        for key in source_uri_fields:
            _append("source_uri", mapping.get(key))

    for mapping in (reference, catalog_entry, reference_metadata, catalog_metadata):
        if not isinstance(mapping, dict):
            continue
        _append("title", mapping.get("title"))

    for mapping in (reference, catalog_entry, reference_metadata, catalog_metadata):
        if not isinstance(mapping, dict):
            continue
        for key in ("subtitle", "subTitle", "sub_title", "deck"):
            _append("subtitle", mapping.get(key))

    return values


def _identifier_source_rank(source: str) -> int:
    return int(IDENTIFIER_PREPASS_SOURCE_ORDER.get(source, 999))


def _identifier_candidate_rank(candidate: dict[str, Any]) -> int:
    value = candidate.get("sourceRank")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 999


def _normalize_identifier_value(identifier_type: str, value: Any) -> str:
    if identifier_type == "doi":
        return _normalize_doi(value)
    if identifier_type == "arxiv_id":
        return _normalize_arxiv_id(value)
    if identifier_type == "isbn13":
        return _normalize_isbn13(value)
    if identifier_type == "publisher_item":
        return _normalize_publisher_item(value)
    return ""


def _identifiers_from_mapping(value: dict[str, Any]) -> dict[str, str]:
    mapping = value if isinstance(value, dict) else {}
    nested_identifiers = mapping.get("identifiers") if isinstance(mapping.get("identifiers"), dict) else {}
    resolved: dict[str, str] = {}
    for identifier_type in IDENTIFIER_PREPASS_TYPES:
        aliases = IDENTIFIER_ALIASES.get(identifier_type, (identifier_type,))
        candidates = [nested_identifiers.get(alias) for alias in aliases]
        candidates.extend(mapping.get(alias) for alias in aliases)
        for candidate in candidates:
            normalized = _normalize_identifier_value(identifier_type, candidate)
            if normalized:
                resolved[identifier_type] = normalized
                break
    return resolved


def _resolve_title_subtitle_deterministic(*, reference: dict[str, Any], catalog_entry: dict[str, Any], source_text: str, fetcher: Any) -> dict[str, Any]:
    source_uri = _clean_text(reference.get("sourceUri") or catalog_entry.get("source_uri") or catalog_entry.get("sourceUri") or catalog_entry.get("url") or catalog_entry.get("uri"))
    if source_text:
        local_html = _title_subtitle_from_local_html(source_text)
        if local_html.get("title"):
            return local_html
        heading = _title_subtitle_from_source_heading(source_text)
        if heading.get("title"):
            return heading
    if source_uri:
        arxiv = _title_subtitle_from_arxiv(source_uri, fetcher=fetcher)
        if arxiv.get("title"):
            return arxiv
        doi = _title_subtitle_from_crossref(source_uri, fetcher=fetcher)
        if doi.get("title"):
            return doi
        html_meta = _title_subtitle_from_html(source_uri, fetcher=fetcher)
        if html_meta.get("title"):
            return html_meta
    return {}


def _title_subtitle_from_source_heading(source_text: str) -> dict[str, Any]:
    lines = [_clean_text(line) for line in source_text.splitlines()[:30]]
    lines = [line for line in lines if line and len(line) >= 8]
    if not lines:
        return {}
    title = lines[0]
    subtitle = ""
    return {
        "title": title,
        "subtitle": subtitle,
        "titleMode": "original_source_heading",
        "subtitleMode": "original_source_heading" if subtitle else "unresolved",
        "source": "source_heading",
        "sourceUrls": [],
        "rationale": "Resolved from the first clear source-text heading lines.",
    }


def _title_subtitle_from_local_html(source_text: str) -> dict[str, Any]:
    text = source_text or ""
    if "<html" not in text.lower():
        return {}
    from papyrus_content.web_structured_metadata import resolve_web_title_subtitle

    resolved = resolve_web_title_subtitle("", html_content=text)
    if resolved.get("title"):
        return {
            **resolved,
            "titleMode": "original_source_heading",
            "subtitleMode": "original_source_heading" if resolved.get("subtitle") else "unresolved",
            "source": "local_html_metadata",
            "sourceUrls": [],
            "rationale": "Resolved from local imported HTML via shared web heuristics.",
        }
    return {}


def _title_subtitle_from_arxiv(source_uri: str, *, fetcher: Any) -> dict[str, Any]:
    match = re.search(r"arxiv\.org/(?:abs|pdf|html|src)/([^?#/]+)", source_uri, flags=re.IGNORECASE)
    if not match:
        return {}
    arxiv_id = re.sub(r"\.pdf$", "", match.group(1), flags=re.IGNORECASE)
    api = f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(arxiv_id)}"
    try:
        body = fetcher(api, timeout=20)
        root = ET.fromstring(body)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            return {}
        title = _clean_text(" ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split()))
        summary = _clean_text(" ".join((entry.findtext("atom:summary", default="", namespaces=ns) or "").split()))
        return {
            "title": title,
            "subtitle": "",
            "summary": _normalize_outcome_summary_candidate(summary),
            "titleMode": "original_web_metadata",
            "subtitleMode": "unresolved",
            "source": "arxiv_metadata",
            "sourceUrls": [api, source_uri],
            "rationale": f"Resolved title from arXiv metadata. Abstract available: {bool(summary)}.",
            "summarySource": "arxiv_metadata" if summary else "",
            "summaryRationale": "Resolved summary from arXiv abstract metadata." if summary else "",
        } if title else {}
    except Exception:
        return {}


def _title_subtitle_from_crossref(source_uri: str, *, fetcher: Any) -> dict[str, Any]:
    doi = _doi_from_text(source_uri)
    if not doi:
        return {}
    api = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
    try:
        payload = json.loads(fetcher(api, timeout=20))
        message = payload.get("message") or {}
        title = _clean_text((message.get("title") or [""])[0])
        subtitle = _clean_text((message.get("subtitle") or [""])[0])
        return {
            "title": title,
            "subtitle": subtitle,
            "titleMode": "original_web_metadata",
            "subtitleMode": "original_web_metadata" if subtitle else "unresolved",
            "source": "crossref_metadata",
            "sourceUrls": [api, source_uri],
            "rationale": "Resolved from Crossref work metadata.",
        } if title else {}
    except Exception:
        return {}


def _title_subtitle_from_html(source_uri: str, *, fetcher: Any) -> dict[str, Any]:
    if not re.match(r"^https?://", source_uri, flags=re.IGNORECASE):
        return {}
    from papyrus_content.web_structured_metadata import resolve_web_title_subtitle

    def _fetch(url: str, timeout: int = 20) -> str:
        return str(fetcher(url, timeout=timeout) or "")

    resolved = resolve_web_title_subtitle(source_uri, fetcher=_fetch)
    if resolved.get("title"):
        return resolved
    try:
        body = fetcher(source_uri, timeout=20)
    except Exception:
        return {}
    title = _html_meta_content(body, "citation_title") or _html_meta_content(body, "og:title") or _html_title(body)
    subtitle = _html_meta_content(body, "description") or _html_meta_content(body, "og:description")
    title = _clean_html_title(title)
    subtitle = _clean_text(subtitle)
    if subtitle and subtitle == title:
        subtitle = ""
    return {
        "title": title,
        "subtitle": subtitle,
        "titleMode": "original_web_metadata",
        "subtitleMode": "original_web_metadata" if subtitle else "unresolved",
        "source": "html_metadata",
        "sourceUrls": [source_uri],
        "rationale": "Resolved from HTML title/meta tags (regex fallback).",
    } if title else {}


def _html_meta_content(body: str, key: str) -> str:
    return _html_meta_content_from_text(body, key)


def _html_meta_content_from_text(body: str, key: str, *, property_name: bool = False) -> str:
    attr = "property" if property_name else "(?:name|property)"
    pattern = rf"<meta\b[^>]*{attr}=[\"']{re.escape(key)}[\"'][^>]*content=[\"']([^\"']+)[\"'][^>]*>"
    match = re.search(pattern, body, flags=re.IGNORECASE)
    if not match:
        pattern = rf"<meta\b[^>]*content=[\"']([^\"']+)[\"'][^>]*{attr}=[\"']{re.escape(key)}[\"'][^>]*>"
        match = re.search(pattern, body, flags=re.IGNORECASE)
    return html.unescape(match.group(1)).strip() if match else ""


def _html_title(body: str) -> str:
    return _html_title_from_text(body)


def _html_title_from_text(body: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
    return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip() if match else ""


def _clean_html_title(value: str) -> str:
    text = _clean_text(value)
    if " | " in text:
        return _clean_text(text.split(" | ")[0])
    return text


def _doi_from_text(value: str) -> str:
    return _normalize_doi(value)


def _normalize_doi(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    stripped = (
        text
        .replace("https://doi.org/", "")
        .replace("http://doi.org/", "")
        .replace("https://dx.doi.org/", "")
        .replace("http://dx.doi.org/", "")
    )
    stripped = re.sub(r"^doi:\s*", "", stripped, flags=re.IGNORECASE).strip()
    match = DOI_RE.search(stripped)
    if not match:
        return ""
    return match.group(0).rstrip(".,);]>").lower()


def _normalize_arxiv_id(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    candidates = [text]
    try:
        parsed = urllib.parse.urlparse(text)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            path = parsed.path or ""
            path = re.sub(r"^/(?:abs|pdf|html|src)/", "", path, flags=re.IGNORECASE)
            path = re.sub(r"\.pdf$", "", path, flags=re.IGNORECASE)
            path = path.strip("/")
            if path:
                candidates.append(path)
    except Exception:
        pass
    for candidate in candidates:
        cleaned = re.sub(r"^arxiv:\s*", "", candidate, flags=re.IGNORECASE)
        modern = ARXIV_MODERN_RE.search(cleaned)
        if modern:
            return modern.group(1).lower()
        legacy = ARXIV_LEGACY_RE.search(cleaned)
        if legacy:
            return legacy.group(1).lower()
    return ""


def _normalize_isbn13(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    has_isbn_marker = bool(re.search(r"\bisbn(?:-1[03])?:?\b", text, flags=re.IGNORECASE))
    for pattern in (ISBN13_TEXT_RE, ISBN10_TEXT_RE):
        for match in pattern.finditer(text):
            candidate = _isbn13_from_token(match.group(0), allow_isbn10_conversion=has_isbn_marker)
            if candidate:
                return candidate
    return _isbn13_from_token(text, allow_isbn10_conversion=has_isbn_marker)


def _isbn13_from_token(value: str, *, allow_isbn10_conversion: bool) -> str:
    raw = re.sub(r"[^0-9Xx]", "", str(value or "")).upper()
    if len(raw) == 13 and raw.isdigit() and _is_valid_isbn13(raw):
        return raw
    if allow_isbn10_conversion and len(raw) == 10 and re.fullmatch(r"[0-9]{9}[0-9X]", raw) and _is_valid_isbn10(raw):
        return _isbn10_to_isbn13(raw)
    return ""


def _is_valid_isbn10(value: str) -> bool:
    total = 0
    for index, char in enumerate(value[:10]):
        digit = 10 if char == "X" else int(char)
        total += digit * (10 - index)
    return total % 11 == 0


def _is_valid_isbn13(value: str) -> bool:
    total = 0
    for index, char in enumerate(value[:13]):
        total += int(char) * (1 if index % 2 == 0 else 3)
    return total % 10 == 0


def _isbn10_to_isbn13(value: str) -> str:
    body = f"978{value[:9]}"
    total = 0
    for index, char in enumerate(body):
        total += int(char) * (1 if index % 2 == 0 else 3)
    check = (10 - (total % 10)) % 10
    return f"{body}{check}"


def _normalize_publisher_item(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    parsed = _publisher_item_from_uri(text)
    candidate = parsed or text
    if not parsed and (" " in candidate or len(candidate) > 240):
        return ""
    normalized = (
        candidate.lower()
        .replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
    )
    normalized = re.sub(r"[?#].*$", "", normalized)
    normalized = re.sub(r"/+$", "", normalized)
    normalized = re.sub(r"[^a-z0-9._:/-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized[:240] if normalized else ""


def _publisher_item_from_uri(value: str) -> str:
    try:
        parsed = urllib.parse.urlparse(value)
    except Exception:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", parsed.path or "")
    acl_match = re.match(r"^/([0-9]{4}\.[a-z0-9-]+\.[0-9]+)(?:\.pdf)?$", path, flags=re.IGNORECASE)
    if host == "aclanthology.org" and acl_match:
        return f"aclanthology:{acl_match.group(1).lower()}"
    if host == "openreview.net":
        query_id = urllib.parse.parse_qs(parsed.query).get("id")
        if query_id and query_id[0]:
            return f"openreview:{query_id[0]}"
        pdf_match = re.search(r"/pdf/([^/]+)$", path, flags=re.IGNORECASE)
        if pdf_match:
            return f"openreview:{pdf_match.group(1)}"
    if host == "neurips.cc":
        poster_match = re.search(r"/poster/([^/]+)$", path, flags=re.IGNORECASE)
        if poster_match:
            return f"neurips-poster:{poster_match.group(1)}"
    if host == "semanticscholar.org":
        paper_match = re.search(r"/paper/(?:[^/]+/)?([a-f0-9]{20,})", path, flags=re.IGNORECASE)
        if paper_match:
            return f"semanticscholar:{paper_match.group(1).lower()}"
    if host == "dl.acm.org":
        doi_match = re.search(r"/doi/(?:abs|fullHtml|pdf)?/?(10\..+)$", path, flags=re.IGNORECASE)
        if doi_match:
            normalized_doi = _normalize_doi(doi_match.group(1))
            return f"acm:{normalized_doi or doi_match.group(1).lower()}"
    return f"{host}{path}".strip("/")


def _fetch_url_text(url: str, *, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Papyrus reference title subtitle enrichment"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _title_subtitle_resolution(
    *,
    status: str,
    title: str,
    subtitle: str,
    title_mode: str,
    subtitle_mode: str,
    source: str,
    model: str,
    web_search_used: bool,
    source_urls: list[str],
    rationale: str,
    run_id: str,
    resolved_at: str,
    warnings: list[str],
    summary: str = "",
    summary_resolution: dict[str, Any] | None = None,
    identifier_prepass: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "title": _clean_text(title),
        "subtitle": _clean_text(subtitle),
        "title_mode": _title_subtitle_mode(title_mode, default="unresolved"),
        "subtitle_mode": _title_subtitle_mode(subtitle_mode, default="unresolved"),
        "summary": _normalize_outcome_summary_candidate(summary),
        "summary_resolution": summary_resolution or {},
        "source": source,
        "model": model,
        "web_search_used": web_search_used,
        "source_urls": sorted(set(_string_list(source_urls))),
        "rationale": rationale,
        "run_id": run_id,
        "resolved_at": resolved_at,
        "prompt_version": TITLE_SUBTITLE_PROMPT_VERSION if source in {"llm_web_search", "llm_no_web_search"} else "",
        "warnings": warnings,
        "identifierPrepass": identifier_prepass or {},
    }


def _title_subtitle_provenance(resolution: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": resolution.get("run_id"),
        "resolved_at": resolution.get("resolved_at"),
        "source": resolution.get("source"),
        "model": resolution.get("model"),
        "web_search_used": bool(resolution.get("web_search_used")),
        "source_urls": resolution.get("source_urls") or [],
        "title_mode": resolution.get("title_mode"),
        "subtitle_mode": resolution.get("subtitle_mode"),
        "rationale": resolution.get("rationale"),
        "prompt_version": resolution.get("prompt_version") or TITLE_SUBTITLE_PROMPT_VERSION,
    }


def _summary_resolution(
    *,
    summary: str,
    summary_token_budget: int,
    model: str,
    source: str,
    source_urls: list[str],
    run_id: str,
    resolved_at: str,
    rationale: str,
    prompt_version: str,
) -> dict[str, Any]:
    text = _normalize_outcome_summary_candidate(summary)
    return {
        "summaryTokenBudget": normalize_title_subtitle_summary_budget(summary_token_budget),
        "actualTokenEstimate": estimate_tokens(text, model=model) if text else 0,
        "model": model,
        "promptVersion": prompt_version or TITLE_SUBTITLE_SUMMARY_PROMPT_VERSION,
        "source": source,
        "source_urls": sorted(set(_string_list(source_urls))),
        "run_id": run_id,
        "resolved_at": resolved_at,
        "rationale": _clean_text(rationale),
    }


def _summary_resolution_provenance(resolution: dict[str, Any]) -> dict[str, Any]:
    candidate = resolution.get("summary_resolution")
    return candidate if isinstance(candidate, dict) else {}


def _title_subtitle_mode(value: Any, *, default: str) -> str:
    allowed = {
        "original_metadata",
        "original_web_metadata",
        "original_source_heading",
        "generated",
        "generated_fallback",
        "existing_reference",
        "existing_reference_metadata",
        "unresolved",
    }
    text = _clean_text(value)
    return text if text in allowed else default


def _web_search_source_urls(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for item in payload.get("output") or []:
        action = item.get("action") if isinstance(item, dict) else None
        sources = action.get("sources") if isinstance(action, dict) else None
        if isinstance(sources, list):
            urls.extend(str(source.get("url") or "") for source in sources if isinstance(source, dict))
    return [url for url in urls if url]


def _compact_catalog_prompt_metadata(catalog_entry: dict[str, Any]) -> dict[str, Any]:
    metadata = catalog_entry.get("metadata") if isinstance(catalog_entry.get("metadata"), dict) else {}
    keys = ("title", "subtitle", "abstract", "summary", "source_uri", "sourceUri", "doi", "arxiv_id", "publisher_item")
    return {key: metadata.get(key) for key in keys if metadata.get(key)}


def _source_excerpt(value: str, *, max_chars: int) -> str:
    return _clean_text(value)[:max_chars]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\x00", " ")).strip()


def _looks_like_list_line(value: str) -> bool:
    return bool(re.match(r"^(?:[-*•]\s+|\d+[.)]\s+)", _clean_text(value)))


def _normalize_subtitle_candidate(value: Any) -> str:
    return _clean_text(_strip_html_fragments(value))


def _generated_subtitle_quality_issue(value: Any, *, subtitle_mode: str) -> str:
    mode = _title_subtitle_mode(subtitle_mode, default="")
    if mode not in {"generated", "generated_fallback"}:
        return ""
    text = _normalize_subtitle_candidate(value)
    if not text:
        return ""
    lowered = text.lower()
    if re.match(r"^https?://", text, flags=re.IGNORECASE):
        return "looks like URL"
    if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(?:/|$)", lowered):
        return "looks like domain or URL path"
    if re.match(r"^(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}$", lowered):
        return "looks like domain"
    words = re.findall(r"[A-Za-z0-9]+", text)
    if len(words) == 1 and words[0].lower() in {"study", "survey", "report", "paper", "article", "review", "preprint"}:
        return "generic one-word label"
    if len(words) < 2:
        return "must be informative multi-word phrase"
    return ""


def _subtitle_candidate_quality_issue(value: Any, *, subtitle_mode: str) -> str:
    text = _normalize_subtitle_candidate(value)
    if not text:
        return ""
    lowered = text.lower()
    if re.match(r"^https?://", text, flags=re.IGNORECASE):
        return "looks like URL"
    if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(?:/|$)", lowered):
        return "looks like domain or URL path"
    if re.match(r"^(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}$", lowered):
        return "looks like domain"
    generated_issue = _generated_subtitle_quality_issue(value, subtitle_mode=subtitle_mode)
    if generated_issue:
        return generated_issue
    return _non_generated_subtitle_quality_issue(value, subtitle_mode=subtitle_mode)


def _non_generated_subtitle_quality_issue(value: Any, *, subtitle_mode: str) -> str:
    mode = _title_subtitle_mode(subtitle_mode, default="")
    if mode in {"", "generated", "original_metadata", "existing_reference_metadata", "existing_reference"}:
        return ""
    text = _normalize_subtitle_candidate(value)
    if not text:
        return ""
    lowered = text.lower()
    if re.match(r"^\s*(?:this|the)\s+(?:pilot\s+)?(?:study|survey|report|paper|article|review|work)\b", lowered):
        return "self-referential subtitle framing"
    if re.match(r"^\s*(?:an?\s+|the\s+)?pilot study\s*$", lowered):
        return "generic pilot-study subtitle"
    if re.match(r"^\s*abstract page for arxiv paper\b", lowered):
        return "source-page boilerplate subtitle"
    if re.match(r"^\s*(?:an?\s+|the\s+)?(?:study|survey|report|paper|article|review|preprint)\s*$", lowered):
        return "generic non-informative subtitle"
    words = re.findall(r"[A-Za-z0-9]+", text)
    if len(words) > 20 or len(text) > 180:
        return "subtitle looks like an abstract/description instead of a subtitle"
    if len(words) < 4:
        return "subtitle is too short to be informative"
    return ""


def _strip_html_fragments(value: Any) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    stripped = re.sub(r"<[^>]+>", " ", raw)
    stripped = html.unescape(stripped)
    return stripped.replace("\xa0", " ")


def _normalize_outcome_summary_candidate(value: Any) -> str:
    raw = str(value or "")
    lines = [line.strip() for line in re.split(r"[\r\n]+", raw) if line.strip()]
    if lines and _looks_like_list_line(lines[0]):
        return ""
    return _clean_text(raw)


def _normalize_reference_title_candidate(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if re.match(r"^https?://", text, flags=re.IGNORECASE):
        return ""
    if re.match(r"^arxiv:\d{4}\.\d{4,5}(?:v\d+)?\s+\[[^\]]+\]\s+\d{1,2}\s+\w+\s+\d{4}$", text, flags=re.IGNORECASE):
        return ""
    text = re.sub(r"^\[(?:\d{4}\.\d{4,5}(?:v\d+)?)\]\s*", "", text)
    text = re.sub(r"^arXiv:\s*(?:\d{4}\.\d{4,5}(?:v\d+)?)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^NeurIPS Poster\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r",?\s*accessed\s+[A-Za-z]+\s+\d{1,2},\s+\d{4},?\s*$", "", text, flags=re.IGNORECASE)
    while True:
        updated = re.sub(
            r"(?:\s+-\s+|\s+\|\s+)(?:arXiv|ACL Anthology|Microsoft|OpenReview|Semantic Scholar|GitHub|Medium|Salesforce|Google DeepMind|DeepMind|Stanford HAI|Hugging Face|ResearchGate|PMC|Wikipedia|Reddit|Meta AI|Amazon Science|ScienceDirect|Nature|Frontiers|NeurIPS|IJCAI|NIST|OpenAI)\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        )
        if updated == text:
            break
        text = updated.strip()
    text = re.sub(
        r":\s*(?:study|report|review|analysis|survey|paper|article|preprint)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if re.match(r"^\[[^\]]+\]\s+\d{1,2}\s+\w+\s+\d{4}$", text):
        return ""
    return _clean_text(text.rstrip(" ,;:-|"))


def _placeholder_title(value: Any) -> bool:
    text = _clean_text(value).lower()
    return text in {
        "",
        "unresolved",
        "no title found",
        "unknown",
        "title unavailable",
    }


def _placeholder_title_or_subtitle(value: Any) -> bool:
    return _placeholder_title(value)


def _catalog_entries(items_value: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(items_value, list):
        return [(str(index), item) for index, item in enumerate(items_value) if isinstance(item, dict)]
    if isinstance(items_value, dict):
        return [(str(key), item) for key, item in items_value.items() if isinstance(item, dict)]
    return []


def _reference_from_catalog_item(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "id": item.get("id") or item.get("item_id") or item.get("externalItemId") or _hash_short([item]),
        "lineageId": item.get("lineageId") or item.get("id") or item.get("item_id") or item.get("externalItemId") or _hash_short([item]),
        "versionNumber": item.get("versionNumber") or 1,
        "externalItemId": item.get("item_id") or item.get("externalItemId") or item.get("id"),
        "title": item.get("title") or metadata.get("title"),
        "authors": item.get("authors") or metadata.get("authors") or [],
        "sourceUri": item.get("source_uri") or item.get("sourceUri") or metadata.get("source_uri") or metadata.get("sourceUri") or item.get("url") or item.get("uri"),
        "storagePath": item.get("storage_path") or item.get("storagePath") or item.get("relpath"),
        "metadata": metadata,
    }


def _catalog_source_text(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    local_source = _catalog_local_source_text(item)
    parts = [
        local_source,
        metadata.get("abstract"),
        metadata.get("summary"),
        metadata.get("description"),
        item.get("summary"),
        item.get("description"),
    ]
    return "\n\n".join(part for part in (_clean_text(value) for value in parts) if part)


def _catalog_local_source_text(item: dict[str, Any]) -> str:
    relpath = _clean_text(item.get("relpath"))
    if not relpath:
        return ""
    path = None
    if relpath.startswith("/"):
        path = Path(relpath)
    else:
        for candidate in (BIBLICUS_ROOT / "corpora").iterdir():
            candidate_path = candidate / relpath
            if candidate_path.exists() and candidate_path.is_file():
                path = candidate_path
                break
    if not path or not path.exists() or not path.is_file():
        return ""
    media_type = _clean_text(item.get("media_type") or (item.get("metadata") or {}).get("media_type")).lower()
    if media_type and not media_type.startswith("text/"):
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _read_reference_sidecar(reference: dict[str, Any]) -> dict[str, Any]:
    path = _sidecar_path_for_reference(reference)
    if not path or not path.exists():
        return {}
    try:
        return _read_yaml_file(path)
    except Exception:
        return {}


def _read_reference_catalog_entry(reference: dict[str, Any]) -> dict[str, Any]:
    catalog_path, catalog_item_key = _catalog_location_for_reference(reference)
    if not catalog_path or not catalog_item_key:
        return {}
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        items = catalog.get("items") if isinstance(catalog, dict) else None
        item = items.get(catalog_item_key) if isinstance(items, dict) else None
        return item if isinstance(item, dict) else {}
    except Exception:
        return {}


def _sidecar_path_for_reference(reference: dict[str, Any]) -> Path | None:
    local_source = _local_source_path_for_reference(reference)
    if not local_source:
        return None
    return Path(f"{local_source}.biblicus.yml")


def _local_source_path_for_reference(reference: dict[str, Any]) -> Path | None:
    storage_path = str(reference.get("storagePath") or "").replace("\\", "/").lstrip("/")
    if not storage_path:
        return None
    parts = storage_path.split("/")
    if len(parts) >= 3 and parts[0] == "corpora":
        return BIBLICUS_ROOT / "corpora" / parts[1] / Path(*parts[2:])
    candidate = BIBLICUS_ROOT / storage_path
    return candidate


def _catalog_location_for_reference(reference: dict[str, Any]) -> tuple[Path | None, str | None]:
    local_source = _local_source_path_for_reference(reference)
    if not local_source:
        return None, None
    corpus_path = _corpus_path_for_local_source(local_source)
    if not corpus_path:
        return None, None
    catalog_path = corpus_path / "metadata" / "catalog.json"
    if not catalog_path.exists():
        alt_path = corpus_path / ".biblicus" / "catalog.json"
        catalog_path = alt_path if alt_path.exists() else catalog_path
    external_item_id = str(reference.get("externalItemId") or "").strip()
    return (catalog_path if catalog_path.exists() else None), (external_item_id or None)


def _corpus_path_for_local_source(local_source: Path) -> Path | None:
    try:
        relative = local_source.resolve().relative_to((BIBLICUS_ROOT / "corpora").resolve())
    except Exception:
        return None
    parts = relative.parts
    if not parts:
        return None
    return BIBLICUS_ROOT / "corpora" / parts[0]


def _read_yaml_file(filepath: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to update Biblicus sidecars")
    parsed = yaml.safe_load(filepath.read_text(encoding="utf-8")) if filepath.exists() else {}
    return parsed if isinstance(parsed, dict) else {}


def _dump_yaml(value: dict[str, Any]) -> str:
    if yaml is None:
        raise RuntimeError("PyYAML is required to update Biblicus sidecars")
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=False)


def _require_reference(reference: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(reference, dict) or not reference.get("id") or not reference.get("lineageId"):
        raise ValueError("reference must include id and lineageId")
    return reference


def _knowledge_corpus_id(corpus_key: str) -> str:
    return f"knowledge-corpus-{_safe_id(corpus_key)}"


def _normalize_relation_type_key(value: Any) -> str:
    return re.sub(r"(^_+|_+$)", "", re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()))


def _safe_id(value: Any) -> str:
    return re.sub(r"(^-+|-+$)", "", re.sub(r"[^a-z0-9]+", "-", str(value or "").lower())).strip("-") or _hash_short(value)


def _hash_short(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat().replace("+00:00", "Z")


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return value


def _compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: entry for key, entry in value.items() if entry not in (None, "", [], {})}


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def print_json(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
