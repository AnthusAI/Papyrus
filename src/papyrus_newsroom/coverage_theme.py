from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_SECTIONS = ["culture", "methods", "business", "law"]
DEFAULT_SECTION_BUDGETS = {
    "culture": 2,
    "arts": 2,
    "methods": 1,
    "business": 1,
    "law": 1,
    "law-policy": 1,
}
SECTION_ALIASES = {
    "culture": "arts",
    "law": "law-policy",
}
OPTIONAL_DESK_SECTION_TYPES = frozenset({"floating", "rotating"})
GENERIC_EDITION_FORUM_TITLES = frozenset({"", "edition forum", "upcoming edition"})
DEFAULT_STEERING_WINDOW_HOURS = 48
SECTION_RESEARCH_LENSES = {
    "culture": "creative workflows, game design, player experience, generative media",
    "arts": "creative workflows, game design, player experience, generative media",
    "methods": "implementation patterns, NPC behavior, procedural generation, evaluation",
    "business": "studios, tooling markets, labor, production economics",
    "law": "copyright, likeness, licensing, liability, platform policy",
    "law-policy": "copyright, likeness, licensing, liability, platform policy",
}
REPORTING_ANGLE_LENSES = [
    {"key": "accountability", "label": "accountability", "prompt": "who is responsible, who is affected, and what changed"},
    {"key": "reader-impact", "label": "reader impact", "prompt": "what a reader can use, decide, or watch next"},
    {"key": "coverage-gap", "label": "coverage gap", "prompt": "what remains underreported and which source trail can close it"},
    {"key": "evidence-check", "label": "evidence check", "prompt": "what is confirmed, contested, or still needs verification"},
]
THROUGH_PHASES = {"plan", "rotating_desk", "research", "reporting"}
PLANNING_KNOWLEDGE_STATE_MODELS = ["Reference", "SemanticNode", "SemanticRelation"]
DEFAULT_CONCEPT_REPORT_LIMIT = 12
DEFAULT_TREND_WINDOW_DAYS = 30
ROTATING_DESK_PROCEDURE_ALIAS = "edition-plan.rotating-desk"
STOPWORDS = {
    "about", "after", "against", "also", "among", "because", "before", "being", "between", "could", "from",
    "have", "into", "more", "over", "than", "that", "their", "there", "these", "this", "through", "with",
    "would", "using", "research", "study", "paper", "report", "analysis", "system", "systems",
}
TREND_TOPIC_STOP_TERMS = STOPWORDS | {
    "abs", "arxiv", "doi", "http", "https", "org", "www", "com", "edu", "net", "io", "pdf", "html",
}
RELATION_DOMAINS = {
    "classified_as": "classification",
    "uses_evidence": "evidence",
    "uses_signal": "evidence",
    "requests_work_on": "workflow",
    "planned_for_edition": "publication",
    "targets_lane": "editorial",
    "targets_slot": "editorial",
    "selected_by": "workflow",
    "targets_section": "editorial",
    "targets_topic": "editorial",
    "scoped_to_topic": "ontology",
    "produces": "workflow",
    "derived_from": "evidence",
    "comment": "commentary",
}

REFERENCE_FIELDS = """
id lineageId versionNumber versionState corpusId externalItemId title authors sourceUri storagePath mediaType
sourcePublishedAt sourceUpdatedAt retrievedAt importRunId importedAt curationStatus curationStatusKey updatedAt
"""
CATEGORY_FIELDS = """
id lineageId versionNumber versionState categorySetId corpusId categoryKey parentCategoryId parentCategoryKey displayName
shortTitle subtitle description aliases status rank depth importRunId updatedAt
"""
CATEGORY_SET_FIELDS = """
id lineageId versionNumber versionState corpusId classifierId displayName description status generatedAt categoryCount importRunId
"""
NEWSROOM_SECTION_FIELDS = """
id title shortTitle type editorialMission editorialPolicy enabled enabledStatus sortOrder defaultArticleTypes defaultPageBudget
assignmentGuidance killCriteria visualGuidance createdAt updatedAt
"""
EDITION_FIELDS = """
id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash
slug title status editionDate publishedAt description layoutPlan metadata
"""
ASSIGNMENT_FIELDS = """
id assignmentTypeKey queueKey queueStatusKey status priority title summary assigneeType assigneeId assigneeKey claimedAt claimExpiresAt
completedAt canceledAt corpusId categorySetId classifierId sourceSnapshotId importRunId sectionId sectionKey sectionType sectionStatusKey
sectionQueueStatusKey primaryFocusCategoryKey topicScopeCategoryKeys createdBy createdAt updatedAt newsroomFeedKey
"""
ASSIGNMENT_EVENT_FIELDS = """
id assignmentId assignmentTypeKey queueKey eventType fromStatus toStatus actorSub actorLabel note createdAt
"""
MESSAGE_FIELDS = """
id messageKind messageDomain status summary source importRunId authorLabel threadId parentMessageId sequenceNumber role
messageType content metadata responseTarget responseStatus responseOwner responseStartedAt responseCompletedAt responseError
newsroomFeedKey createdAt updatedAt
"""
MESSAGE_THREAD_FIELDS = """
id threadKind status title summary primaryAnchorKind primaryAnchorId primaryAnchorLineageId primaryAnchorKey createdBySub
createdByUserProfileId createdByLabel messageCount lastMessageId lastMessageAt contextDigest activeResponseMessageId
responseLockOwner responseLockExpiresAt metadata createdAt updatedAt newsroomFeedKey
"""
SEMANTIC_NODE_FIELDS = """
id lineageId versionNumber previousVersionId versionState versionCreatedAt versionCreatedBy changeReason contentHash
nodeKey nodeKind corpusId categorySetId categoryLineageId categoryKey displayName description aliases authorityScore authorityRank
acceptedReferenceMentionCount distinctSourceKindCount relationCount status importRunId createdAt updatedAt
newsroomFeedKey
"""
SEMANTIC_RELATION_FIELDS = """
id relationState predicate relationTypeId relationTypeKey relationDomain subjectKind subjectId subjectLineageId subjectVersionNumber
objectKind objectId objectLineageId objectVersionNumber subjectStateKey objectStateKey objectSubjectStateKey predicateObjectStateKey
subjectVersionKey objectVersionKey score confidence rank classifierId modelVersion reviewRecommended sourceSnapshotId importRunId importedAt
createdAt updatedAt newsroomFeedKey metadata
"""
MODEL_ATTACHMENT_FIELDS = """
id ownerKind ownerId ownerLineageId ownerVersionNumber ownerVersionKey role sortKey storagePath filename mediaType byteSize sha256 etag
importRunId createdAt updatedAt status
"""
ITEM_FIELDS = """
id lineageId versionNumber versionState type status typeStatus slug shortSlug section sectionStatus title headline deck byline dateline
publishedAt editionDate sortTitle body editorial updatedAt
"""
EDITION_ITEM_FIELDS = """
id editionId itemId publishedEditionId publishedItemId sourceEditionId sourceItemId editionLineageId itemLineageId placementKey sortKey
pageNumber priority metadata
"""
EDITION_SLOT_FIELDS = """
id editionId sectionKey slotRank targetType targetLengthBand minImageAssets status selectedAssignmentId metadata createdAt updatedAt
"""

LIST_FIELDS = {
    "Reference": ("listReferences", REFERENCE_FIELDS),
    "Category": ("listCategories", CATEGORY_FIELDS),
    "CategorySet": ("listCategorySets", CATEGORY_SET_FIELDS),
    "NewsroomSection": ("listNewsroomSections", NEWSROOM_SECTION_FIELDS),
    "Edition": ("listEditions", EDITION_FIELDS),
    "Assignment": ("listAssignments", ASSIGNMENT_FIELDS),
    "AssignmentEvent": ("listAssignmentEvents", ASSIGNMENT_EVENT_FIELDS),
    "Message": ("listMessages", MESSAGE_FIELDS),
    "MessageThread": ("listMessageThreads", MESSAGE_THREAD_FIELDS),
    "SemanticNode": ("listSemanticNodes", SEMANTIC_NODE_FIELDS),
    "SemanticRelation": ("listSemanticRelations", SEMANTIC_RELATION_FIELDS),
    "ModelAttachment": ("listModelAttachments", MODEL_ATTACHMENT_FIELDS),
    "Item": ("listItems", ITEM_FIELDS),
    "EditionItem": ("listEditionItems", EDITION_ITEM_FIELDS),
    "EditionSlot": ("listEditionSlots", EDITION_SLOT_FIELDS),
}
GET_FIELDS = {
    model: (f"get{model}", fields)
    for model, (_, fields) in LIST_FIELDS.items()
}

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
  ) { ok uploadId attachmentId method uploadUrl storagePath requiredHeaders }
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
  ) { id }
}
"""
CREATE_MODEL_ATTACHMENT_DOWNLOAD_MUTATION = """
mutation CreateModelAttachmentDownload($attachmentId: ID!) {
  createModelAttachmentDownload(attachmentId: $attachmentId) {
    ok attachmentId method downloadUrl storagePath mediaType byteSize sha256 expiresAt requiredHeaders
  }
}
"""


def signals_trend_report(
    *,
    corpus_key: str,
    date: str = "",
    category_key: str = "",
    topic: str = "",
    coverage_key: str = "",
    sections: list[str] | None = None,
    since_days: int = 30,
    limit: int = 10,
    run_id: str = "",
    references: list[dict[str, Any]] | None = None,
    semantic_nodes: list[dict[str, Any]] | None = None,
    apply: bool = False,
    now: str = "",
) -> dict[str, Any]:
    now = now or _now_iso()
    sections = _resolve_section_keys(sections or [])
    if references is None:
        state = load_live_state(models=["Reference", "SemanticNode"])
        references = state.get("references", [])
        semantic_nodes = state.get("semanticNodes", [])
    semantic_nodes = semantic_nodes or []
    run_id = run_id or f"signal-report-{_safe_id(topic or category_key or corpus_key)}-{_timestamp_for_path(now)}"
    signals = build_trend_signals(
        references=references,
        semantic_nodes=semantic_nodes,
        corpus_key=corpus_key,
        category_key=category_key,
        topic=topic,
        coverage_key=coverage_key,
        sections=sections,
        since_days=since_days,
        limit=limit,
        now=now,
    )
    report = {
        "ok": True,
        "command": "signals trend-report",
        "runId": run_id,
        "date": date or _date_from_iso(now),
        "corpusKey": corpus_key,
        "categoryKey": category_key,
        "topic": topic,
        "coverageKey": coverage_key,
        "sections": sections,
        "sinceDays": since_days,
        "generatedAt": now,
        "signals": signals,
        "summary": {
            "signalCount": len(signals),
            "acceptedReferenceCount": len(_accepted_references(references, corpus_key)),
            "createsItemOrEditionItem": False,
        },
    }
    records = build_signal_report_records(report)
    output = {
        **report,
        "records": records,
        "apply": False,
    }
    if apply:
        output = {**output, **apply_records(records)}
    return output


def signals_concept_report(
    *,
    corpus_key: str,
    report_type: str = "all",
    limit: int = 25,
    trend_window_days: int = 30,
    pagerank_iterations: int = 30,
    pagerank_damping: float = 0.85,
    node_kinds: list[str] | None = None,
    max_nodes_per_reference: int = 50,
    order: str = "most",
    run_id: str = "",
    references: list[dict[str, Any]] | None = None,
    semantic_nodes: list[dict[str, Any]] | None = None,
    semantic_relations: list[dict[str, Any]] | None = None,
    apply: bool = False,
    now: str = "",
) -> dict[str, Any]:
    now = now or _now_iso()
    report_type = _normalize_concept_report_type(report_type)
    order = _normalize_centrality_order(order)
    if references is None or semantic_nodes is None or semantic_relations is None:
        state = load_live_state(models=["Reference", "SemanticNode", "SemanticRelation"])
        references = state.get("references", []) if references is None else references
        semantic_nodes = state.get("semanticNodes", []) if semantic_nodes is None else semantic_nodes
        semantic_relations = state.get("semanticRelations", []) if semantic_relations is None else semantic_relations
    references = references or []
    semantic_nodes = semantic_nodes or []
    semantic_relations = semantic_relations or []
    run_id = run_id or f"concept-report-{_safe_id(corpus_key)}-{_timestamp_for_path(now)}"
    reports = build_concept_reports(
        references=references,
        semantic_nodes=semantic_nodes,
        semantic_relations=semantic_relations,
        corpus_key=corpus_key,
        report_type=report_type,
        limit=limit,
        trend_window_days=trend_window_days,
        pagerank_iterations=pagerank_iterations,
        pagerank_damping=pagerank_damping,
        node_kinds=node_kinds or [],
        max_nodes_per_reference=max_nodes_per_reference,
        order=order,
        now=now,
    )
    mention_relation_count = sum(len(report.get("mentionRelationIds") or []) for report in reports)
    ranked_concept_ids = {
        concept.get("conceptId")
        for report in reports
        for concept in report.get("rankedConcepts") or []
        if concept.get("conceptId")
    }
    reports_by_type = {
        str(section.get("reportType") or ""): list(section.get("rankedConcepts") or [])
        for section in reports
    }
    popularity = reports_by_type.get("popularity", [])
    trending = reports_by_type.get("trending", [])
    pagerank = reports_by_type.get("pagerank", [])
    centrality = reports_by_type.get("centrality", [])
    centrality_stability = next(
        (section.get("stability") for section in reports if section.get("reportType") == "centrality"),
        None,
    )
    report = {
        "ok": True,
        "command": "signals concept-report",
        "runId": run_id,
        "corpusKey": corpus_key,
        "reportType": report_type,
        "order": order if report_type == "centrality" else "most",
        "generatedAt": now,
        "reports": reports,
        "popularity": popularity,
        "trending": trending,
        "pagerank": pagerank,
        "centrality": centrality,
        "summary": {
            "reportCount": len(reports),
            "rankedConceptCount": len(ranked_concept_ids),
            "popularityCount": len(popularity),
            "trendingCount": len(trending),
            "pagerankCount": len(pagerank),
            "centralityCount": len(centrality),
            "centralityStability": centrality_stability,
            "acceptedReferenceCount": len(_accepted_references(references, corpus_key)),
            "mentionRelationCount": mention_relation_count,
            "createsItemOrEditionItem": False,
        },
    }
    records = build_concept_report_records(report)
    output = {
        **report,
        "records": records,
        "apply": False,
    }
    if apply:
        output = {**output, **apply_records(records)}
    return output


def build_trend_signals(
    *,
    references: list[dict[str, Any]],
    semantic_nodes: list[dict[str, Any]],
    corpus_key: str,
    category_key: str = "",
    topic: str = "",
    coverage_key: str = "",
    sections: list[str] | None = None,
    since_days: int = 30,
    limit: int = 10,
    now: str = "",
) -> list[dict[str, Any]]:
    now_dt = _parse_datetime(now) or dt.datetime.now(dt.UTC)
    accepted = _accepted_references(references, corpus_key)
    if since_days > 0:
        cutoff = now_dt - dt.timedelta(days=since_days)
        accepted = [ref for ref in accepted if (_reference_datetime(ref) or now_dt) >= cutoff]
    sections = sections or []
    topics: dict[str, dict[str, Any]] = {}
    if topic:
        key = _safe_id(topic)
        topics[key] = {
            "label": topic,
            "terms": _terms(topic),
            "references": [],
            "semanticNodes": _matching_nodes(semantic_nodes, topic, coverage_key),
        }
    else:
        term_counts: dict[str, int] = {}
        for ref in accepted:
            for term in _terms(" ".join([str(ref.get("title") or ""), str(ref.get("sourceUri") or "")])):
                term_counts[term] = term_counts.get(term, 0) + 1
        for term, _count in sorted(term_counts.items(), key=lambda item: (-item[1], item[0]))[: max(limit * 2, 1)]:
            topics[term] = {"label": term.replace("-", " ").title(), "terms": [term], "references": [], "semanticNodes": []}
    if not topics and category_key:
        key = _safe_id(category_key)
        topics[key] = {"label": category_key, "terms": _terms(category_key), "references": [], "semanticNodes": []}
    for ref in accepted:
        haystack = " ".join([str(ref.get("title") or ""), str(ref.get("sourceUri") or "")]).lower()
        for candidate in topics.values():
            terms = candidate["terms"] or _terms(candidate["label"])
            if not terms or any(term in haystack for term in terms):
                candidate["references"].append(ref)
    signals: list[dict[str, Any]] = []
    for index, (key, candidate) in enumerate(topics.items(), start=1):
        refs = _dedupe_by_id(candidate["references"])
        if not refs and topic:
            refs = accepted[: min(5, len(accepted))]
        domains = sorted({_domain(ref.get("sourceUri")) for ref in refs if _domain(ref.get("sourceUri"))})
        recency_values = [_recency_score(_reference_datetime(ref), now_dt, since_days) for ref in refs]
        freshness = round(sum(recency_values) / len(recency_values), 3) if recency_values else 0.0
        velocity = len(refs)
        diversity = round(min(1.0, len(domains) / max(len(refs), 1)), 3) if refs else 0.0
        section_fit = _section_fit_scores(candidate["label"], refs, sections)
        average_section_fit = round(sum(section_fit.values()) / len(section_fit), 3) if section_fit else 0.0
        evidence_quality = 1.0 if refs else 0.0
        coverage_gap_value = round(1.0 / (1 + max(len(refs) - 1, 0)), 3) if refs else 1.0
        score = round((velocity * 2.0) + freshness + diversity + average_section_fit + evidence_quality + coverage_gap_value, 3)
        signal_coverage_key = coverage_key if topic and coverage_key else f"coverage.{key.replace('-', '.')}"
        proposed_sections = [section for section, fit in sorted(section_fit.items(), key=lambda item: (-item[1], item[0])) if fit > 0]
        if not proposed_sections:
            proposed_sections = sections[:]
        signals.append({
            "signalId": f"signal-{_hash_short([corpus_key, category_key, signal_coverage_key, candidate['label']])}",
            "rank": index,
            "topic": candidate["label"],
            "coverageKey": signal_coverage_key,
            "categoryKey": category_key,
            "score": score,
            "scoreBreakdown": {
                "velocity": velocity,
                "freshness": freshness,
                "sourceDiversity": diversity,
                "sectionFit": average_section_fit,
                "evidenceQuality": evidence_quality,
                "coverageGapValue": coverage_gap_value,
            },
            "whyNow": _why_now(candidate["label"], refs, domains, since_days),
            "sourceReferenceIds": [ref["id"] for ref in refs if ref.get("id")],
            "acceptedEvidenceCount": len(refs),
            "sourceDomains": domains,
            "sectionFit": section_fit,
            "proposedSections": proposed_sections,
            "coverageGaps": _coverage_gaps(candidate["label"], refs),
            "openQuestions": _open_questions(candidate["label"], sections),
            "suggestedAngles": _suggested_angles(candidate["label"], sections),
        })
    return sorted(signals, key=lambda item: (-float(item["score"]), item["topic"]))[:limit]


def build_concept_reports(
    *,
    references: list[dict[str, Any]],
    semantic_nodes: list[dict[str, Any]],
    semantic_relations: list[dict[str, Any]],
    corpus_key: str,
    report_type: str,
    limit: int,
    trend_window_days: int,
    pagerank_iterations: int,
    pagerank_damping: float,
    node_kinds: list[str],
    max_nodes_per_reference: int,
    order: str = "most",
    now: str,
) -> list[dict[str, Any]]:
    report_type = _normalize_concept_report_type(report_type)
    order = _normalize_centrality_order(order)
    limit = max(1, int(limit or 1))
    context = _concept_report_context(
        references=references,
        semantic_nodes=semantic_nodes,
        semantic_relations=semantic_relations,
        corpus_key=corpus_key,
        node_kinds=node_kinds,
        now=now,
    )
    requested = ["popularity", "trending", "pagerank"] if report_type == "all" else [report_type]
    reports: list[dict[str, Any]] = []
    for current_type in requested:
        if current_type == "popularity":
            reports.append(_build_concept_popularity_report(context, limit))
        elif current_type == "trending":
            reports.append(_build_concept_trending_report(context, limit, trend_window_days))
        elif current_type == "pagerank":
            reports.append(_build_concept_pagerank_report(context, limit, pagerank_iterations, pagerank_damping, max_nodes_per_reference))
        elif current_type == "centrality":
            reports.append(
                _build_concept_centrality_report(
                    context=context,
                    references=references,
                    semantic_nodes=semantic_nodes,
                    semantic_relations=semantic_relations,
                    corpus_key=corpus_key,
                    node_kinds=node_kinds,
                    limit=limit,
                    order=order,
                    pagerank_iterations=pagerank_iterations,
                    pagerank_damping=pagerank_damping,
                )
            )
    return reports


def build_signal_report_records(report: dict[str, Any]) -> list[dict[str, Any]]:
    now = str(report.get("generatedAt") or _now_iso())
    run_id = str(report["runId"])
    message_id = f"message-edition-signal-report-{_safe_id(run_id)}"
    summary = f"Edition signal report: {len(report.get('signals') or [])} ranked knowledge-base signal(s)."
    message = {
        "id": message_id,
        "messageKind": "edition_signal_report",
        "messageDomain": "edition_planning",
        "status": "active",
        "summary": summary,
        "source": "papyrus knowledge signals trend-report",
        "importRunId": run_id,
        "authorLabel": "papyrus",
        "newsroomFeedKey": "message#edition_signal_report",
        "createdAt": now,
        "updatedAt": now,
    }
    body = _signal_report_body(report)
    records = [
        _record("Message", message),
        _attachment_record(message_id, "message_body", "message", "message.txt", "text/plain", body, run_id, now),
        _attachment_record(message_id, "metadata", "metadata", "metadata.json", "application/json", {"kind": "edition.signal_report", **report}, run_id, now),
    ]
    for signal in report.get("signals") or []:
        node = coverage_node_record(
            coverage_key=signal["coverageKey"],
            topic=signal["topic"],
            corpus_key=str(report.get("corpusKey") or ""),
            category=None,
            category_set=None,
            now=now,
            change_reason="edition-signal-report",
        )
        records.append(_record("SemanticNode", node))
        records.append(_record("SemanticRelation", semantic_relation(
            predicate="uses_signal",
            subject_kind="message",
            subject_id=message_id,
            object_kind="semanticNode",
            object_id=node["id"],
            object_lineage_id=node["lineageId"],
            object_version_number=node["versionNumber"],
            rank=signal.get("rank"),
            import_run_id=run_id,
            now=now,
            metadata={"signalId": signal["signalId"], "coverageKey": signal["coverageKey"], "topic": signal["topic"]},
        )))
        for rank, reference_id in enumerate(signal.get("sourceReferenceIds") or [], start=1):
            records.append(_record("SemanticRelation", semantic_relation(
                predicate="uses_evidence",
                subject_kind="message",
                subject_id=message_id,
                object_kind="reference",
                object_id=reference_id,
                object_lineage_id=reference_id,
                rank=rank,
                import_run_id=run_id,
                now=now,
                metadata={"signalId": signal["signalId"], "coverageKey": signal["coverageKey"]},
            )))
    return _dedupe_records(records)


def build_concept_report_records(report: dict[str, Any]) -> list[dict[str, Any]]:
    now = str(report.get("generatedAt") or _now_iso())
    run_id = str(report["runId"])
    message_id = f"message-concept-report-{_safe_id(run_id)}"
    summary = f"Concept analytics report: {len(report.get('reports') or [])} report section(s)."
    message = {
        "id": message_id,
        "messageKind": "concept_report",
        "messageDomain": "analytics",
        "status": "active",
        "summary": summary,
        "source": "papyrus-newsroom signals concept-report",
        "importRunId": run_id,
        "authorLabel": "papyrus-newsroom",
        "newsroomFeedKey": "message#concept_report",
        "createdAt": now,
        "updatedAt": now,
    }
    records = [
        _record("Message", message),
        _attachment_record(message_id, "message_body", "message", "message.txt", "text/plain", _concept_report_body(report), run_id, now),
        _attachment_record(message_id, "metadata", "metadata", "metadata.json", "application/json", {"kind": "analytics.concept_report", **report}, run_id, now),
    ]
    linked_concept_reports: set[str] = set()
    linked_references: set[str] = set()
    for report_section in report.get("reports") or []:
        for concept in report_section.get("rankedConcepts") or []:
            concept_id = str(concept.get("conceptId") or "")
            report_key = f"{concept_id}:{report_section.get('reportType')}"
            if concept_id and report_key not in linked_concept_reports:
                linked_concept_reports.add(report_key)
                records.append(_record("SemanticRelation", semantic_relation(
                    predicate="uses_signal",
                    subject_kind="message",
                    subject_id=message_id,
                    object_kind="semanticNode",
                    object_id=concept_id,
                    object_lineage_id=str(concept.get("conceptLineageId") or concept_id),
                    rank=concept.get("rank"),
                    score=concept.get("score"),
                    import_run_id=run_id,
                    now=now,
                    metadata={
                        "reportType": report_section.get("reportType"),
                        "displayName": concept.get("displayName"),
                        "metric": concept.get("metric"),
                    },
                )))
            for reference_id in concept.get("sourceReferenceIds") or []:
                reference_id = str(reference_id or "")
                if not reference_id or reference_id in linked_references:
                    continue
                linked_references.add(reference_id)
                records.append(_record("SemanticRelation", semantic_relation(
                    predicate="uses_evidence",
                    subject_kind="message",
                    subject_id=message_id,
                    object_kind="reference",
                    object_id=reference_id,
                    object_lineage_id=reference_id,
                    rank=len(linked_references),
                    import_run_id=run_id,
                    now=now,
                    metadata={"reportType": report_section.get("reportType")},
                )))
    return _dedupe_records(records)


def editions_plan(
    *,
    date: str,
    sections: list[str],
    section_budgets: dict[str, int],
    corpus_key: str,
    category_key: str = "",
    topic: str = "",
    coverage_key: str = "",
    signal_report: dict[str, Any] | None = None,
    theme_limit: int = 3,
    run_id: str = "",
    apply: bool = False,
    now: str = "",
) -> dict[str, Any]:
    now = now or _now_iso()
    if signal_report is None:
        signal_report = signals_trend_report(
            corpus_key=corpus_key,
            date=date,
            category_key=category_key,
            topic=topic,
            coverage_key=coverage_key,
            sections=sections,
            limit=max(theme_limit, 1),
            now=now,
        )
    signals = list(signal_report.get("signals") or [])[: max(theme_limit, 1)]
    if not signals:
        signals = [{
            "topic": topic or category_key or corpus_key,
            "coverageKey": coverage_key or f"coverage.{_safe_id(topic or category_key or corpus_key).replace('-', '.')}",
            "categoryKey": category_key,
            "signalId": f"signal-{_hash_short([corpus_key, topic, coverage_key])}",
            "rank": 1,
            "sourceReferenceIds": [],
            "coverageGaps": [],
            "openQuestions": [],
            "suggestedAngles": [],
        }]
    state = load_live_state(models=["NewsroomSection", "Category", "CategorySet", "MessageThread", "Message"]) if apply else {}
    records: list[dict[str, Any]] = []
    plans = []
    for index, signal in enumerate(signals, start=1):
        theme_run_id = run_id or f"coverage-theme-{_safe_id(date)}-{_safe_id(signal['coverageKey'])}"
        if len(signals) > 1:
            theme_run_id = f"{theme_run_id}-{index:02d}"
        plan = build_coverage_theme_plan(
            date=date,
            topic=str(signal.get("topic") or topic or ""),
            corpus_key=corpus_key,
            category_key=str(signal.get("categoryKey") or category_key or ""),
            coverage_key=str(signal.get("coverageKey") or coverage_key or ""),
            sections=sections,
            section_budgets=section_budgets,
            run_id=theme_run_id,
            now=now,
            state=state,
            signal=signal,
        )
        plans.append(_without_records(plan))
        records.extend(plan["records"])
    output = {
        "ok": True,
        "command": "editions plan",
        "date": date,
        "runId": run_id or f"edition-plan-{_safe_id(date)}",
        "signalReportRunId": signal_report.get("runId"),
        "coverageThemes": plans,
        "records": _dedupe_records(records),
        "summary": {
            "coverageThemeCount": len(plans),
            "assignmentCount": sum(1 for record in _dedupe_records(records) if record["modelName"] == "Assignment"),
            "createsMessage": False,
            "createsItemOrEditionItem": False,
        },
        "apply": False,
    }
    if apply:
        output = {**output, **apply_records(output["records"])}
    return output


def coverage_theme_run(
    *,
    date: str,
    topic: str,
    corpus_key: str,
    category_key: str,
    coverage_key: str,
    sections: list[str],
    section_budgets: dict[str, int],
    run_id: str = "",
    through: str = "reporting",
    research_mode: str = "source_discovery",
    allow_fallback: bool = False,
    require_agent_success: bool = False,
    refresh_packets: bool = False,
    apply: bool = False,
    now: str = "",
    selected_optional_desk_key: str = "",
    include_optional_desks: bool = False,
    skip_rotating_desk: bool = False,
    select_rotating_desk: bool | None = None,
    refresh_forum_kickoff: bool = False,
    refresh_forum: bool = False,
    rotating_desk_steering_notes: str = "",
) -> dict[str, Any]:
    now = now or _now_iso()
    through = normalize_through(through)
    state_models = [
        *PLANNING_KNOWLEDGE_STATE_MODELS,
        "NewsroomSection",
        "Category",
        "CategorySet",
        "MessageThread",
        "Message",
        "Edition",
    ]
    if apply:
        state_models.extend(["Assignment", "EditionSlot"])
    state = load_live_state(models=state_models) if apply else {}
    plan = build_coverage_theme_plan(
        date=date,
        topic=topic,
        corpus_key=corpus_key,
        category_key=category_key,
        coverage_key=coverage_key,
        sections=sections,
        section_budgets=section_budgets,
        run_id=run_id,
        research_mode=research_mode,
        now=now,
        state=state,
        selected_optional_desk_key=selected_optional_desk_key if include_optional_desks else "",
        include_optional_desks=include_optional_desks,
        refresh_forum_kickoff=refresh_forum_kickoff,
        refresh_forum=refresh_forum,
    )
    records = list(plan["records"])
    if apply and (refresh_forum or refresh_forum_kickoff):
        _mark_forum_supersede_records_in_state(state, records)
    rotating_desk_step: dict[str, Any] | None = None
    cloud_client = None
    if select_rotating_desk is None:
        select_rotating_desk = through in {"rotating_desk", "research", "reporting"}
    should_select_rotating_desk = (
        not skip_rotating_desk
        and not include_optional_desks
        and select_rotating_desk
        and (bool(plan.get("provisionalOptionalDesks")) or bool(selected_optional_desk_key))
    )
    if should_select_rotating_desk and apply:
        if through in {"rotating_desk", "research", "reporting"}:
            try:
                cloud_client = _create_cloud_procedure_client()
            except Exception:
                if not allow_fallback and through == "rotating_desk":
                    return _coverage_theme_cloud_error(
                        plan,
                        through,
                        apply,
                        {
                            "code": "cloud_procedure_failed",
                            "message": "Cloud procedure client is unavailable for rotating-desk selection.",
                            "alias": ROTATING_DESK_PROCEDURE_ALIAS,
                            "remediation": "Run poetry run papyrus procedures seed-required",
                        },
                    )
        rotating_desk_step = run_rotating_desk_planning_step(
            plan=plan,
            topic=topic,
            corpus_key=corpus_key,
            coverage_key=coverage_key or plan.get("coverageKey") or "",
            sections=sections,
            section_budgets=section_budgets,
            run_id=plan["runId"],
            research_mode=research_mode,
            now=now,
            state=state,
            client=cloud_client,
            allow_fallback=allow_fallback,
            selected_optional_desk_key=selected_optional_desk_key,
            steering_notes=rotating_desk_steering_notes,
        )
        if rotating_desk_step.get("ok") is False:
            return {
                **_without_records(plan),
                "ok": False,
                "command": "coverage-themes run",
                "through": through,
                "apply": False,
                "error": rotating_desk_step.get("error"),
            }
        if rotating_desk_step:
            if through == "rotating_desk" and apply and find_planning_edition_for_date(state, date):
                records = list(rotating_desk_step.get("records") or [])
            else:
                records.extend(rotating_desk_step.get("records") or [])
            if not rotating_desk_step.get("skipped"):
                plan["researchAssignments"] = [
                    *(plan.get("researchAssignments") or []),
                    *(rotating_desk_step.get("researchAssignments") or []),
                ]
                plan["reportingAssignments"] = [
                    *(plan.get("reportingAssignments") or []),
                    *(rotating_desk_step.get("reportingAssignments") or []),
                ]
                plan["editionSlots"] = [
                    *(plan.get("editionSlots") or []),
                    *(rotating_desk_step.get("editionSlots") or []),
                ]
            if plan.get("edition") and isinstance(plan["edition"].get("metadata"), dict):
                plan["edition"]["metadata"]["rotatingDeskStatus"] = "selected"
                plan["edition"]["metadata"]["selectedOptionalDeskKey"] = rotating_desk_step.get("selectedOptionalDeskKey")
        _merge_forum_messages_from_records_into_state(state, records)
    if through == "rotating_desk":
        reporting_dispatch_forum: dict[str, Any] | None = None
        if apply and rotating_desk_step and rotating_desk_step.get("ok") is not False:
            reporting_dispatch_forum = append_reporting_dispatch_forum_records(
                records,
                plan=plan,
                topic=topic,
                coverage_key=coverage_key or plan.get("coverageKey") or "",
                section_budgets=section_budgets,
                run_id=plan["runId"],
                now=now,
                state=state,
            )
        output = {
            **_without_records(plan),
            "ok": True,
            "command": "coverage-themes run",
            "through": through,
            "rotatingDesk": rotating_desk_step,
            "reportingDispatchForum": reporting_dispatch_forum,
            "records": _dedupe_records(records),
            "summary": {
                **(plan.get("summary") or {}),
                "rotatingDeskSelected": bool(rotating_desk_step and not rotating_desk_step.get("skipped")),
                "reportingDispatchForumPosted": bool(
                    reporting_dispatch_forum and reporting_dispatch_forum.get("action") != "skip"
                ),
            },
            "apply": False,
        }
        if apply:
            output = {**output, **apply_records(output["records"])}
        return output
    packet_runs: dict[str, list[dict[str, Any]]] = {"research": [], "reporting": []}
    degraded = bool(rotating_desk_step and rotating_desk_step.get("degraded"))
    if through in {"research", "reporting"} and cloud_client is None:
        try:
            cloud_client = _create_cloud_procedure_client()
        except Exception as error:
            if not allow_fallback:
                return _coverage_theme_cloud_error(
                    plan,
                    through,
                    apply,
                    {
                        "code": "cloud_procedure_failed",
                        "message": str(error),
                        "alias": "story-cycle.research",
                        "remediation": "Run poetry run papyrus procedures seed-required to preload standard procedures if the required cloud procedure is missing or stale.",
                    },
                )
    if through in {"research", "reporting"}:
        for assignment in plan["researchAssignments"]:
            packet_plan = run_or_fallback_research_packet_records(
                client=cloud_client,
                run_id=plan["runId"],
                assignment=assignment,
                topic=topic,
                corpus_key=corpus_key,
                coverage_key=coverage_key,
                research_mode=research_mode,
                now=now,
                allow_fallback=allow_fallback,
                refresh_packets=refresh_packets,
            )
            if packet_plan.get("ok") is False:
                return _coverage_theme_cloud_error(plan, through, apply, packet_plan["error"])
            degraded = degraded or bool(packet_plan["degraded"])
            packet_runs["research"].append(packet_plan["run"])
            records.extend(packet_plan["records"])
    if through == "reporting":
        research_by_section = {assignment["sectionKey"]: assignment for assignment in plan["researchAssignments"]}
        research_messages = {run["sectionKey"]: run.get("messageId") for run in packet_runs["research"]}
        for assignment in plan["reportingAssignments"]:
            packet_plan = run_or_fallback_reporting_packet_records(
                client=cloud_client,
                run_id=plan["runId"],
                assignment=assignment,
                topic=topic,
                corpus_key=corpus_key,
                coverage_key=coverage_key,
                source_research_assignment=research_by_section.get(assignment["sectionKey"]),
                source_research_packet_id=research_messages.get(assignment["sectionKey"]),
                now=now,
                allow_fallback=allow_fallback,
                refresh_packets=refresh_packets,
            )
            if packet_plan.get("ok") is False:
                return _coverage_theme_cloud_error(plan, through, apply, packet_plan["error"])
            degraded = degraded or bool(packet_plan["degraded"])
            packet_runs["reporting"].append(packet_plan["run"])
            records.extend(packet_plan["records"])
    if degraded and (require_agent_success or (apply and not allow_fallback)):
        return {
            **_without_records(plan),
            "ok": False,
            "command": "coverage-themes run",
            "through": through,
            "apply": False,
            "degraded": True,
            "error": {
                "code": "agent_success_required",
                "message": "coverage-themes run generated deterministic fallback packets; pass --allow-fallback to persist degraded output.",
            },
        }
    reporting_dispatch_forum: dict[str, Any] | None = None
    if (
        apply
        and through == "plan"
        and not should_defer_reporting_dispatch_forum(
            plan,
            skip_rotating_desk=skip_rotating_desk,
            include_optional_desks=include_optional_desks,
            selected_optional_desk_key=selected_optional_desk_key,
        )
    ):
        reporting_dispatch_forum = append_reporting_dispatch_forum_records(
            records,
            plan=plan,
            topic=topic,
            coverage_key=coverage_key or plan.get("coverageKey") or "",
            section_budgets=section_budgets,
            run_id=plan["runId"],
            now=now,
            state=state,
        )
    output = {
        **_without_records(plan),
        "ok": True,
        "command": "coverage-themes run",
        "through": through,
        "researchRuns": packet_runs["research"],
        "reportingRuns": packet_runs["reporting"],
        "records": _dedupe_records(records),
        "rotatingDesk": rotating_desk_step,
        "reportingDispatchForum": reporting_dispatch_forum,
        "summary": {
            **plan["summary"],
            "researchPacketCount": len(packet_runs["research"]),
            "reportingPacketCount": len(packet_runs["reporting"]),
            "rotatingDeskSelected": bool(rotating_desk_step and not rotating_desk_step.get("skipped")),
            "reportingDispatchForumPosted": bool(
                reporting_dispatch_forum and reporting_dispatch_forum.get("action") != "skip"
            ),
            "degraded": degraded,
            "createsItemOrEditionItem": False,
        },
        "apply": False,
        "degraded": degraded,
    }
    if apply:
        apply_records_list = list(output["records"])
        if (refresh_forum_kickoff or refresh_forum) and through == "plan":
            apply_records_list = [
                record
                for record in apply_records_list
                if record.get("modelName") in {"Edition", "Message", "MessageThread", "SemanticRelation"}
            ]
        output = {**output, **apply_records(apply_records_list)}
    return output


def _coverage_theme_cloud_error(plan: dict[str, Any], through: str, apply: bool, error: dict[str, Any]) -> dict[str, Any]:
    return {
        **_without_records(plan),
        "ok": False,
        "command": "coverage-themes run",
        "through": through,
        "apply": False,
        "degraded": False,
        "error": error,
        "summary": {
            **(plan.get("summary") or {}),
            "researchPacketCount": 0,
            "reportingPacketCount": 0,
            "degraded": False,
            "createsItemOrEditionItem": False,
            "requestedApply": apply,
        },
    }


def _create_cloud_procedure_client() -> Any:
    from papyrus_content.graphql_authoring import create_authoring_client

    client, _ = create_authoring_client()
    return client


def _start_cloud_procedure_run(**kwargs: Any) -> dict[str, Any]:
    from papyrus_content.cloud_procedures import start_cloud_procedure_run

    return start_cloud_procedure_run(**kwargs)


def run_or_fallback_research_packet_records(
    *,
    client: Any,
    run_id: str,
    assignment: dict[str, Any],
    topic: str,
    corpus_key: str,
    coverage_key: str,
    research_mode: str,
    now: str,
    allow_fallback: bool,
    refresh_packets: bool,
) -> dict[str, Any]:
    if client is None:
        if not allow_fallback:
            return {
                "ok": False,
                "error": _cloud_procedure_error_payload(
                    "story-cycle.research",
                    assignment,
                    ValueError("Cloud procedure client is unavailable."),
                ),
            }
        return build_research_packet_records(
            assignment=assignment,
            topic=topic,
            corpus_key=corpus_key,
            coverage_key=coverage_key,
            research_mode=research_mode,
            now=now,
            degraded=True,
            refresh_packets=refresh_packets,
        )
    try:
        return build_cloud_research_packet_records(
            client=client,
            run_id=run_id,
            assignment=assignment,
            topic=topic,
            corpus_key=corpus_key,
            coverage_key=coverage_key,
            research_mode=research_mode,
            now=now,
            refresh_packets=refresh_packets,
        )
    except Exception as error:
        if not allow_fallback:
            return {"ok": False, "error": _cloud_procedure_error_payload("story-cycle.research", assignment, error)}
        return build_research_packet_records(
            assignment=assignment,
            topic=topic,
            corpus_key=corpus_key,
            coverage_key=coverage_key,
            research_mode=research_mode,
            now=now,
            degraded=True,
            refresh_packets=refresh_packets,
        )


def run_or_fallback_reporting_packet_records(
    *,
    client: Any,
    run_id: str,
    assignment: dict[str, Any],
    topic: str,
    corpus_key: str,
    coverage_key: str,
    source_research_assignment: dict[str, Any] | None,
    source_research_packet_id: str | None,
    now: str,
    allow_fallback: bool,
    refresh_packets: bool,
) -> dict[str, Any]:
    if client is None:
        if not allow_fallback:
            return {
                "ok": False,
                "error": _cloud_procedure_error_payload(
                    "story-cycle.reporting",
                    assignment,
                    ValueError("Cloud procedure client is unavailable."),
                ),
            }
        return build_reporting_packet_records(
            assignment=assignment,
            topic=topic,
            corpus_key=corpus_key,
            coverage_key=coverage_key,
            source_research_assignment=source_research_assignment,
            source_research_packet_id=source_research_packet_id,
            now=now,
            degraded=True,
            refresh_packets=refresh_packets,
        )
    try:
        return build_cloud_reporting_packet_records(
            client=client,
            run_id=run_id,
            assignment=assignment,
            topic=topic,
            corpus_key=corpus_key,
            coverage_key=coverage_key,
            source_research_assignment=source_research_assignment,
            source_research_packet_id=source_research_packet_id,
            now=now,
            refresh_packets=refresh_packets,
        )
    except Exception as error:
        if not allow_fallback:
            return {"ok": False, "error": _cloud_procedure_error_payload("story-cycle.reporting", assignment, error)}
        return build_reporting_packet_records(
            assignment=assignment,
            topic=topic,
            corpus_key=corpus_key,
            coverage_key=coverage_key,
            source_research_assignment=source_research_assignment,
            source_research_packet_id=source_research_packet_id,
            now=now,
            degraded=True,
            refresh_packets=refresh_packets,
        )


def build_cloud_research_packet_records(
    *,
    client: Any,
    run_id: str,
    assignment: dict[str, Any],
    topic: str,
    corpus_key: str,
    coverage_key: str,
    research_mode: str,
    now: str,
    refresh_packets: bool,
) -> dict[str, Any]:
    metadata = _metadata(assignment)
    run_dir = Path(".papyrus-runs") / run_id / _safe_id(assignment["id"])
    cloud_run = _start_cloud_procedure_run(
        client=client,
        alias="story-cycle.research",
        actor_label="papyrus coverage-themes run",
        title=f"Run story-cycle research for {metadata.get('sectionTitle') or assignment.get('sectionKey')}",
        summary=f"Coverage Theme research for {topic}.",
        input_payload={
            "assignment_item_id": assignment["id"],
            "assignment_json": assignment,
            "corpus_key": corpus_key,
            "context_profile": "researcher",
            "research_mode": research_mode,
            "research_questions": metadata.get("researchLens") or "",
            "max_evidence_items": 20,
        },
        run_dir=run_dir,
        source_path=run_dir / "research.cloud.tac",
        stdout_path=run_dir / "research.stdout.log",
        stderr_path=run_dir / "research.stderr.log",
    )
    output = cloud_run.get("output") if isinstance(cloud_run.get("output"), dict) else {}
    packet = output.get("research_packet") or output.get("researchPacket")
    if not isinstance(packet, dict):
        raise ValueError(
            f"Cloud procedure output for {assignment['id']} is missing research_packet. "
            "Run poetry run papyrus procedures seed-required if procedure seeds are stale."
        )
    normalized_packet = normalize_story_cycle_research_packet(
        packet,
        assignment=assignment,
        topic=topic,
        corpus_key=corpus_key,
        coverage_key=coverage_key,
        research_mode=research_mode,
    )
    return build_research_packet_records_from_packet(
        assignment=assignment,
        packet=normalized_packet,
        cloud_run=cloud_run,
        now=now,
        refresh_packets=refresh_packets,
    )


def build_cloud_reporting_packet_records(
    *,
    client: Any,
    run_id: str,
    assignment: dict[str, Any],
    topic: str,
    corpus_key: str,
    coverage_key: str,
    source_research_assignment: dict[str, Any] | None,
    source_research_packet_id: str | None,
    now: str,
    refresh_packets: bool,
) -> dict[str, Any]:
    metadata = _metadata(assignment)
    run_dir = Path(".papyrus-runs") / run_id / _safe_id(assignment["id"])
    cloud_run = _start_cloud_procedure_run(
        client=client,
        alias="story-cycle.reporting",
        actor_label="papyrus coverage-themes run",
        title=f"Run story-cycle reporting for {metadata.get('sectionTitle') or assignment.get('sectionKey')}",
        summary=f"Coverage Theme reporting context for {topic}.",
        input_payload={
            "assignment_item_id": assignment["id"],
            "assignment_json": assignment,
            "corpus_key": corpus_key,
            "context_profile": "reporting",
            "source_research_assignment_id": (source_research_assignment or {}).get("id"),
            "source_research_packet_id": source_research_packet_id,
        },
        run_dir=run_dir,
        source_path=run_dir / "reporting.cloud.tac",
        stdout_path=run_dir / "reporting.stdout.log",
        stderr_path=run_dir / "reporting.stderr.log",
    )
    output = cloud_run.get("output") if isinstance(cloud_run.get("output"), dict) else {}
    packet = output.get("reporting_context_packet") or output.get("reportingContextPacket")
    if not isinstance(packet, dict):
        raise ValueError(
            f"Cloud procedure output for {assignment['id']} is missing reporting_context_packet. "
            "Run poetry run papyrus procedures seed-required if procedure seeds are stale."
        )
    normalized_packet = normalize_story_cycle_reporting_packet(
        packet,
        assignment=assignment,
        topic=topic,
        coverage_key=coverage_key,
        source_research_assignment=source_research_assignment,
        source_research_packet_id=source_research_packet_id,
    )
    return build_reporting_packet_records_from_packet(
        assignment=assignment,
        packet=normalized_packet,
        cloud_run=cloud_run,
        source_research_packet_id=source_research_packet_id,
        now=now,
        refresh_packets=refresh_packets,
    )


def _cloud_procedure_error_payload(alias: str, assignment: dict[str, Any], error: Exception) -> dict[str, Any]:
    return {
        "code": "cloud_procedure_failed",
        "message": str(error),
        "alias": alias,
        "assignmentId": assignment.get("id"),
        "remediation": "Run poetry run papyrus procedures seed-required to preload standard procedures if the required cloud procedure is missing or stale.",
    }


def _build_sections_dispatch_bundle(
    *,
    dispatch_sections: list[dict[str, Any]],
    edition: dict[str, Any],
    section_budgets: dict[str, int],
    run_id: str,
    date: str,
    topic: str,
    corpus_key: str,
    category_key: str,
    category: dict[str, Any] | None,
    category_set: dict[str, Any] | None,
    coverage_node: dict[str, Any],
    reporting_lane: dict[str, Any],
    research_mode: str,
    signal: dict[str, Any] | None,
    now: str,
    priority_offset: int = 0,
) -> dict[str, Any]:
    edition_slots = build_edition_slots(
        edition=edition,
        resolved_sections=dispatch_sections,
        section_budgets=section_budgets,
        run_id=run_id,
        now=now,
    )
    slots_by_section: dict[str, list[dict[str, Any]]] = {}
    for slot in edition_slots:
        slots_by_section.setdefault(slot["sectionKey"], []).append(slot)
    records: list[dict[str, Any]] = [_record("EditionSlot", slot) for slot in edition_slots]
    research_assignments: list[dict[str, Any]] = []
    reporting_assignments: list[dict[str, Any]] = []
    for section_index, section in enumerate(dispatch_sections, start=1):
        priority_base = priority_offset + section_index * 100
        research_assignment = research_assignment_record(
            run_id=run_id,
            date=date,
            topic=topic,
            corpus_key=corpus_key,
            category_key=category_key,
            category=category,
            category_set=category_set,
            coverage_node=coverage_node,
            edition=edition,
            section=section,
            research_mode=research_mode,
            signal=signal,
            now=now,
            priority=priority_base,
        )
        research_assignments.append(research_assignment)
        records.extend(assignment_records(research_assignment, edition, coverage_node, section, category, category_set, now, signal=signal))
        slots = max(1, int(section_budgets.get(section["id"], DEFAULT_SECTION_BUDGETS.get(section["id"], 1))))
        section_slots = slots_by_section.get(section["id"], [])
        dispatch_count = math.ceil(slots * 1.5)
        concept_pool = list((signal or {}).get("conceptSnapshot", {}).get("rankedForDispatch") or [])
        for rank in range(1, dispatch_count + 1):
            angle = REPORTING_ANGLE_LENSES[(rank - 1) % len(REPORTING_ANGLE_LENSES)]
            slot_rank = ((rank - 1) % slots) + 1 if slots > 0 else 1
            assigned_slot = next((slot for slot in section_slots if slot.get("slotRank") == slot_rank), None)
            concept = concept_pool[(rank - 1) % len(concept_pool)] if concept_pool else None
            reporting_assignment = reporting_assignment_record(
                run_id=run_id,
                date=date,
                topic=topic,
                corpus_key=corpus_key,
                category_key=category_key,
                category=category,
                category_set=category_set,
                coverage_node=coverage_node,
                edition=edition,
                section=section,
                slots=slots,
                dispatch_count=dispatch_count,
                angle=angle,
                candidate_rank=rank,
                assigned_slot=assigned_slot,
                source_research_assignment=research_assignment,
                signal=signal,
                concept=concept,
                now=now,
                priority=priority_base + rank,
            )
            reporting_assignments.append(reporting_assignment)
            records.extend(assignment_records(reporting_assignment, edition, coverage_node, section, category, category_set, now, signal=signal))
            records.append(_record("SemanticRelation", semantic_relation(
                predicate="targets_lane",
                subject_kind="assignment",
                subject_id=reporting_assignment["id"],
                object_kind="semanticNode",
                object_id=reporting_lane["id"],
                object_lineage_id=reporting_lane["lineageId"],
                object_version_number=reporting_lane["versionNumber"],
                rank=1,
                classifier_id=category_set.get("classifierId") if category_set else None,
                import_run_id=reporting_assignment.get("importRunId"),
                now=now,
                metadata={
                    "runId": run_id,
                    "laneKey": "reporting",
                    "laneNodeKey": reporting_lane["nodeKey"],
                    "slotTarget": _metadata(reporting_assignment).get("slotTarget"),
                    "angleDiversity": _metadata(reporting_assignment).get("angleDiversity"),
                },
            )))
            records.append(_record("SemanticRelation", semantic_relation(
                predicate="derived_from",
                subject_kind="assignment",
                subject_id=reporting_assignment["id"],
                object_kind="assignment",
                object_id=research_assignment["id"],
                object_lineage_id=research_assignment["id"],
                rank=1,
                classifier_id=category_set.get("classifierId") if category_set else None,
                import_run_id=reporting_assignment.get("importRunId"),
                now=now,
                metadata={"runId": run_id, "sourceKind": "section_research_assignment", "coverageKey": coverage_node.get("nodeKey")},
            )))
    return {
        "records": records,
        "editionSlots": edition_slots,
        "researchAssignments": research_assignments,
        "reportingAssignments": reporting_assignments,
    }


def find_planning_edition_for_date(
    state: dict[str, list[dict[str, Any]]],
    date: str,
) -> dict[str, Any] | None:
    slug = f"edition-{date}"
    for edition in state.get("editions") or []:
        if str(edition.get("editionDate") or "") == date:
            return edition
        if str(edition.get("slug") or "") == slug:
            return edition
    return None


def resolve_coverage_theme_run_id(
    *,
    date: str,
    topic: str,
    coverage_key: str,
    run_id: str,
    state: dict[str, list[dict[str, Any]]],
) -> str:
    if str(run_id or "").strip():
        return str(run_id).strip()
    existing = find_planning_edition_for_date(state, date)
    if existing:
        metadata = _metadata(existing)
        for key in ("coverageThemeRunId", "lastKickoffRunId"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
    return f"coverage-theme-{_safe_id(date)}-{_safe_id(coverage_key or topic)}"


def build_coverage_theme_plan(
    *,
    date: str,
    topic: str,
    corpus_key: str,
    category_key: str,
    coverage_key: str,
    sections: list[str],
    section_budgets: dict[str, int],
    run_id: str = "",
    research_mode: str = "source_discovery",
    now: str = "",
    state: dict[str, list[dict[str, Any]]] | None = None,
    signal: dict[str, Any] | None = None,
    selected_optional_desk_key: str = "",
    include_optional_desks: bool = False,
    refresh_forum_kickoff: bool = False,
    refresh_forum: bool = False,
) -> dict[str, Any]:
    now = now or _now_iso()
    state = state or {}
    coverage_key = coverage_key or f"coverage.{_safe_id(topic).replace('-', '.')}"
    run_id = resolve_coverage_theme_run_id(
        date=date,
        topic=topic,
        coverage_key=coverage_key,
        run_id=run_id,
        state=state,
    )
    resolved_sections = resolve_sections(sections or DEFAULT_SECTIONS, state.get("newsroomSections") or [])
    dispatch_sections, provisional_optional_sections = partition_sections_for_dispatch(
        resolved_sections,
        selected_optional_desk_key=selected_optional_desk_key,
        include_optional_desks=include_optional_desks,
    )
    category = find_category(category_key, state.get("categories") or [])
    category_set = find_category_set(category, state.get("categorySets") or [])
    existing_edition = find_planning_edition_for_date(state, date)
    edition = dict(existing_edition) if existing_edition else edition_record(
        date=date,
        section_budgets=section_budgets,
        run_id=run_id,
        now=now,
    )
    if not existing_edition:
        edition_metadata = dict(edition.get("metadata") or {})
        edition_metadata["coverageThemeRunId"] = run_id
        edition["metadata"] = edition_metadata
    if selected_optional_desk_key:
        edition_metadata = dict(edition.get("metadata") or {})
        edition_metadata["selectedOptionalDeskKey"] = selected_optional_desk_key
        edition_metadata["rotatingDeskStatus"] = "selected"
        edition["metadata"] = edition_metadata
    coverage_node = coverage_node_record(
        coverage_key=coverage_key,
        topic=topic,
        corpus_key=corpus_key,
        category=category,
        category_set=category_set,
        now=now,
    )
    reporting_lane = lane_node_record("editorial.form.reporting", "Reporting", "reported story", now)
    dispatch_bundle = _build_sections_dispatch_bundle(
        dispatch_sections=dispatch_sections,
        edition=edition,
        section_budgets=section_budgets,
        run_id=run_id,
        date=date,
        topic=topic,
        corpus_key=corpus_key,
        category_key=category_key,
        category=category,
        category_set=category_set,
        coverage_node=coverage_node,
        reporting_lane=reporting_lane,
        research_mode=research_mode,
        signal=signal,
        now=now,
    )
    edition_slots = dispatch_bundle["editionSlots"]
    research_assignments = dispatch_bundle["researchAssignments"]
    reporting_assignments = dispatch_bundle["reportingAssignments"]
    records = [
        _record("Edition", edition),
        *dispatch_bundle["records"],
        _record("SemanticNode", coverage_node),
        _record("SemanticNode", reporting_lane),
    ]
    if category:
        records.append(_record("SemanticRelation", semantic_relation(
            predicate="scoped_to_topic",
            subject_kind="semanticNode",
            subject_id=coverage_node["id"],
            subject_lineage_id=coverage_node["lineageId"],
            subject_version_number=coverage_node["versionNumber"],
            object_kind="category",
            object_id=category["id"],
            object_lineage_id=category.get("lineageId") or category["id"],
            object_version_number=category.get("versionNumber"),
            classifier_id=category_set.get("classifierId") if category_set else None,
            now=now,
            metadata={"runId": run_id, "coverageKey": coverage_key, "categoryKey": category.get("categoryKey")},
        )))
    forum_kickoff = build_edition_forum_kickoff_records(
        edition=edition,
        sections=resolved_sections,
        section_budgets=section_budgets,
        reporting_assignments=reporting_assignments,
        topic=topic,
        coverage_key=coverage_key,
        corpus_key=corpus_key,
        category_key=category_key,
        run_id=run_id,
        now=now,
        existing_threads=state.get("messageThreads") or [],
        existing_messages=state.get("messages") or [],
        existing_editions=state.get("editions") or [],
        signal=signal,
        state=state,
        refresh_forum_kickoff=refresh_forum_kickoff,
        refresh_forum=refresh_forum,
    )
    records.extend(forum_kickoff["records"])
    return {
        "ok": True,
        "command": "coverage-themes plan",
        "workflowName": "Coverage Theme",
        "runId": run_id,
        "date": date,
        "topic": topic,
        "corpusKey": corpus_key,
        "categoryKey": category_key,
        "coverageKey": coverage_key,
        "edition": edition,
        "coverageNode": coverage_node,
        "sections": [
            {"key": section["id"], "title": section["title"], "researchLens": section_research_lens(section["id"]), "slots": section_budgets.get(section["id"], DEFAULT_SECTION_BUDGETS.get(section["id"], 1))}
            for section in resolved_sections
        ],
        "dispatchSections": [
            {"key": section["id"], "title": section.get("title"), "planningRole": _section_planning_role(section)}
            for section in dispatch_sections
        ],
        "provisionalOptionalDesks": [
            {"key": section["id"], "title": section.get("title"), "sectionType": _normalize_section_type(section.get("type"))}
            for section in provisional_optional_sections
        ],
        "editionSlots": edition_slots,
        "forumKickoff": forum_kickoff["kickoff"],
        "forumPlanningNextStep": (
            "run-story-cycle --through rotating-desk"
            if provisional_optional_sections
            else "reporting dispatch posts with plan apply when no optional desk is pending"
        ),
        "researchAssignments": research_assignments,
        "reportingAssignments": reporting_assignments,
        "records": _dedupe_records(records),
        "summary": {
            "sectionCount": len(resolved_sections),
            "dispatchSectionCount": len(dispatch_sections),
            "provisionalOptionalDeskCount": len(provisional_optional_sections),
            "slotCount": len(edition_slots),
            "forumThreadCount": forum_kickoff["summary"]["threadCount"],
            "forumMessageCount": forum_kickoff["summary"]["messageCount"],
            "researchAssignmentCount": len(research_assignments),
            "reportingAssignmentCount": len(reporting_assignments),
            "createsItemOrEditionItem": False,
        },
    }


def build_edition_forum_kickoff_records(
    *,
    edition: dict[str, Any],
    sections: list[dict[str, Any]],
    section_budgets: dict[str, int],
    reporting_assignments: list[dict[str, Any]],
    topic: str,
    coverage_key: str,
    corpus_key: str = "",
    category_key: str = "",
    run_id: str,
    now: str,
    existing_threads: list[dict[str, Any]] | None = None,
    existing_messages: list[dict[str, Any]] | None = None,
    existing_editions: list[dict[str, Any]] | None = None,
    signal: dict[str, Any] | None = None,
    state: dict[str, list[dict[str, Any]]] | None = None,
    steering_window_hours: int = DEFAULT_STEERING_WINDOW_HOURS,
    refresh_forum_kickoff: bool = False,
    refresh_forum: bool = False,
) -> dict[str, Any]:
    edition_id = str(edition.get("id") or "")
    existing_threads = existing_threads or []
    existing_messages = existing_messages or []
    existing_messages_by_thread: dict[str, list[dict[str, Any]]] = {}
    for message in existing_messages:
        thread_id = str(message.get("threadId") or "").strip()
        if not thread_id:
            continue
        existing_messages_by_thread.setdefault(thread_id, []).append(message)
    records: list[dict[str, Any]] = []
    if refresh_forum:
        records.extend(_plan_forum_refresh_supersede_records(existing_messages_by_thread, now=now))
    elif refresh_forum_kickoff:
        records.extend(_plan_forum_kickoff_supersede_records(existing_messages_by_thread, now=now))

    section_summary: list[dict[str, Any]] = []
    for section in sections:
        section_key = str(section.get("id") or "")
        slots = max(1, int(section_budgets.get(section_key, DEFAULT_SECTION_BUDGETS.get(section_key, 1))))
        dispatch_count = math.ceil(slots * 1.5)
        section_type = _normalize_section_type(section.get("type"))
        planning_role = _section_planning_role(section)
        section_summary.append({
            "sectionId": section_key,
            "sectionKey": section_key,
            "sectionTitle": section.get("title") or section_key,
            "sectionType": section_type,
            "planningRole": planning_role,
            "slots": slots,
            "dispatchCount": dispatch_count,
            "suggestedTopics": [topic],
        })
    core_sections, optional_desk_sections = _partition_sections_for_planning(section_summary)
    recent_optional_desk_usage = collect_recent_optional_desk_usage(
        existing_editions or [],
        exclude_edition_id=edition_id,
    )
    section_keys = [str(section.get("id") or "") for section in sections if section.get("id")]
    resolved_signal = resolve_edition_theme_signal(
        signal=signal,
        topic=topic,
        coverage_key=coverage_key,
        corpus_key=corpus_key,
        category_key=category_key,
        sections=section_keys,
        state=state or {},
        now=now,
    )
    recent_edition_themes = collect_recent_edition_themes(
        existing_editions or [],
        existing_messages or [],
        exclude_edition_id=edition_id,
    )
    kickoff_draft = build_edition_theme_kickoff_draft(
        topic=topic,
        coverage_key=coverage_key,
        signal=resolved_signal,
        core_sections=core_sections,
        optional_desk_sections=optional_desk_sections,
        recent_optional_desk_usage=recent_optional_desk_usage,
        recent_edition_themes=recent_edition_themes,
        edition_date=str(edition.get("editionDate") or ""),
    )

    canonical_edition_thread_id = _canonical_edition_forum_thread_id(edition_id)
    existing_edition_thread = next(
        (
            thread
            for thread in existing_threads
            if str(thread.get("threadKind") or "") == "edition_forum"
            and str(thread.get("primaryAnchorKind") or "") == "edition"
            and str(thread.get("primaryAnchorId") or "") == edition_id
            and str(thread.get("id") or "") == canonical_edition_thread_id
        ),
        None,
    )
    edition_kickoff_plan = _plan_forum_kickoff_scope(
        canonical_thread_id=canonical_edition_thread_id,
        summary=kickoff_draft["message_summary"],
        content=kickoff_draft["body"],
        run_id=run_id,
        now=now,
        replan_heading="Edition replan",
        existing_threads=existing_threads,
        existing_messages_by_thread=existing_messages_by_thread,
        refresh_existing=refresh_forum or refresh_forum_kickoff,
        build_thread=lambda thread_id, _sequence_number: edition_forum_thread_record(
            edition_id=edition_id,
            run_id=run_id,
            now=now,
            thread_id=thread_id,
            title=kickoff_draft["thread_title"],
            summary=kickoff_draft["thread_summary"],
            existing=existing_edition_thread if thread_id == canonical_edition_thread_id else None,
            message_count=int((existing_edition_thread or {}).get("messageCount") or 0),
            last_message_id=str((existing_edition_thread or {}).get("lastMessageId") or ""),
        ),
        message_metadata={"planningPhase": "edition_theme_kickoff"},
    )
    edition_thread = edition_kickoff_plan["thread"]
    edition_message = edition_kickoff_plan["message"]
    records.extend(edition_kickoff_plan["records"])
    existing_title = str((existing_edition_thread or {}).get("title") or "").strip()
    if (
        edition_kickoff_plan["action"] == "skip"
        and existing_edition_thread
        and _is_generic_edition_forum_title(existing_title)
        and kickoff_draft["thread_title"].lower() not in GENERIC_EDITION_FORUM_TITLES
    ):
        patched_thread = edition_forum_thread_record(
            edition_id=edition_id,
            run_id=run_id,
            now=now,
            thread_id=canonical_edition_thread_id,
            title=kickoff_draft["thread_title"],
            summary=kickoff_draft["thread_summary"],
            existing=existing_edition_thread,
            message_count=int(existing_edition_thread.get("messageCount") or 1),
            last_message_id=str(existing_edition_thread.get("lastMessageId") or ""),
        )
        edition_thread = patched_thread
        records.append(_record("MessageThread", patched_thread))
    if edition_kickoff_plan["action"] != "skip":
        edition_metadata = dict(_metadata(edition))
        edition_metadata.update({
            "proposedEditionTheme": kickoff_draft["primary_theme"],
            "proposedCoverageKey": coverage_key,
            "kickoffThreadTitle": kickoff_draft["thread_title"],
            "signalId": resolved_signal.get("signalId"),
            "signalRank": resolved_signal.get("rank"),
        })
        records.append(_record("Edition", {
            **edition,
            "metadata": edition_metadata,
        }))
        records.append(_record("SemanticRelation", semantic_relation(
            predicate="planned_for_edition",
            subject_kind="message",
            subject_id=edition_message["id"],
            object_kind="edition",
            object_id=edition_id,
            object_lineage_id=edition.get("lineageId") or edition_id,
            object_version_number=edition.get("versionNumber") or 1,
            import_run_id=run_id,
            now=now,
            metadata={"runId": run_id, "threadId": edition_thread["id"], "forumScope": "edition", "planningPhase": "theme_proposal"},
        )))

    return {
        "records": records,
        "kickoff": {
            "editionThreadId": edition_thread["id"],
            "editionMessageId": edition_message["id"],
            "editionKickoffAction": edition_kickoff_plan["action"],
            "planningPhase": "theme_proposal",
            "rotatingDeskStatus": "pending_selection" if optional_desk_sections else "not_applicable",
            "reportingDispatchStatus": "pending_optional_desk" if optional_desk_sections else "pending_dispatch_post",
            "coreSectionKeys": [section["sectionKey"] for section in core_sections],
            "optionalDeskSectionKeys": [section["sectionKey"] for section in optional_desk_sections],
            "recentOptionalDeskUsage": recent_optional_desk_usage,
            "sectionThreadIds": [],
            "sectionMessageIds": [],
            "edition": {
                "threadId": edition_thread["id"],
                "messageId": edition_message["id"],
                "summary": edition_message["summary"],
                "content": edition_message["content"],
                "kickoffAction": edition_kickoff_plan["action"],
            },
            "sections": [],
        },
        "summary": {
            "threadCount": 1,
            "messageCount": 0 if edition_kickoff_plan["action"] == "skip" else 1,
        },
    }


def edition_forum_thread_record(
    *,
    edition_id: str,
    run_id: str,
    now: str,
    thread_id: str = "",
    title: str = "",
    summary: str = "",
    existing: dict[str, Any] | None = None,
    message_count: int = 1,
    last_message_id: str = "",
) -> dict[str, Any]:
    thread_id = thread_id or f"message-thread-edition-forum-{_safe_id(edition_id)}"
    existing_metadata = _metadata(existing or {})
    return {
        "id": thread_id,
        "threadKind": "edition_forum",
        "status": "active",
        "title": title or (existing or {}).get("title") or "Upcoming edition",
        "summary": summary or (existing or {}).get("summary") or "Edition planning thread.",
        "primaryAnchorKind": "edition",
        "primaryAnchorId": edition_id,
        "primaryAnchorLineageId": edition_id,
        "primaryAnchorKey": f"edition#{edition_id}",
        "createdByLabel": (existing or {}).get("createdByLabel") or "papyrus-editor",
        "messageCount": max(message_count, 1),
        "lastMessageId": last_message_id or f"message-forum-{_safe_id(thread_id)}-0001",
        "lastMessageAt": now,
        "metadata": {**existing_metadata, "editionId": edition_id, "runId": run_id, "lastKickoffRunId": run_id},
        "createdAt": (existing or {}).get("createdAt") or now,
        "updatedAt": now,
        "newsroomFeedKey": "messages",
    }


def section_forum_thread_record(
    *,
    edition_id: str,
    section_id: str,
    section_key: str,
    section_title: str,
    run_id: str,
    now: str,
    thread_id: str = "",
    existing: dict[str, Any] | None = None,
    message_count: int = 1,
    last_message_id: str = "",
) -> dict[str, Any]:
    thread_id = thread_id or f"message-thread-section-forum-{_safe_id(edition_id)}-{_safe_id(section_id)}"
    existing_metadata = _metadata(existing or {})
    return {
        "id": thread_id,
        "threadKind": "section_forum",
        "status": "active",
        "title": f"Section Forum: {section_title}",
        "summary": "Section-scoped coordination and steering for this edition.",
        "primaryAnchorKind": "newsroom_section",
        "primaryAnchorId": section_id,
        "primaryAnchorLineageId": edition_id,
        "primaryAnchorKey": f"edition#{edition_id}#section#{section_id}",
        "createdByLabel": (existing or {}).get("createdByLabel") or "papyrus-editor",
        "messageCount": max(message_count, 1),
        "lastMessageId": last_message_id or f"message-forum-{_safe_id(thread_id)}-0001",
        "lastMessageAt": now,
        "metadata": {
            **existing_metadata,
            "editionId": edition_id,
            "sectionId": section_id,
            "sectionKey": section_key,
            "sectionTitle": section_title,
            "runId": run_id,
            "lastKickoffRunId": run_id,
        },
        "createdAt": (existing or {}).get("createdAt") or now,
        "updatedAt": now,
        "newsroomFeedKey": "messages",
    }


def forum_kickoff_message_record(
    *,
    thread: dict[str, Any],
    role: str,
    author_label: str,
    summary: str,
    content: str,
    now: str,
    sequence_number: int = 1,
    message_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sequence_number = max(1, int(sequence_number or 1))
    return {
        "id": f"message-forum-{_safe_id(thread.get('id'))}-{sequence_number:04d}",
        "messageKind": "forum_post",
        "messageDomain": "edition_coordination",
        "status": "active",
        "summary": summary,
        "source": "papyrus assignments run-story-cycle",
        "importRunId": ((thread.get("metadata") or {}) if isinstance(thread.get("metadata"), dict) else {}).get("runId"),
        "authorLabel": author_label,
        "threadId": thread.get("id"),
        "parentMessageId": None,
        "sequenceNumber": sequence_number,
        "role": role,
        "messageType": "forum_message",
        "content": content,
        "metadata": {
            "threadKind": thread.get("threadKind"),
            "anchorKind": thread.get("primaryAnchorKind"),
            "anchorId": thread.get("primaryAnchorId"),
            "anchorLineageId": thread.get("primaryAnchorLineageId"),
            **(message_metadata or {}),
        },
        "newsroomFeedKey": "messages",
        "createdAt": now,
        "updatedAt": now,
    }


def _is_generic_edition_forum_title(title: str) -> bool:
    return str(title or "").strip().lower() in GENERIC_EDITION_FORUM_TITLES


def _looks_like_domain_label(text: str) -> bool:
    cleaned = str(text or "").strip().lower()
    if not cleaned or " " in cleaned:
        return False
    return bool(re.fullmatch(r"[\w.-]+\.(org|com|edu|net|io|gov|uk|de|ai)", cleaned))


def _is_usable_theme_label(text: str) -> bool:
    label = re.sub(r"\s+", " ", str(text or "").strip())
    if len(label) < 8:
        return False
    if _looks_like_domain_label(label):
        return False
    terms = _terms(label)
    if not terms:
        return False
    significant = [term for term in terms if term not in TREND_TOPIC_STOP_TERMS]
    if len(significant) < 2:
        return False
    if all(term in TREND_TOPIC_STOP_TERMS for term in terms):
        return False
    return True


def _theme_phrases_from_reference_titles(titles: list[str], *, limit: int = 3) -> list[str]:
    counts: dict[str, int] = {}
    for raw_title in titles:
        words = [
            word
            for word in re.findall(r"[A-Za-z][A-Za-z0-9-]+", str(raw_title or ""))
            if word.lower() not in TREND_TOPIC_STOP_TERMS and len(word) >= 3
        ]
        for index in range(len(words) - 1):
            phrase = f"{words[index]} {words[index + 1]}"
            if not _is_usable_theme_label(phrase):
                continue
            key = phrase.lower()
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    labels: list[str] = []
    for key, _count in ranked:
        label = " ".join(part.capitalize() if part.islower() else part for part in key.split())
        if label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _related_theme_labels_for_title(
    *,
    signal: dict[str, Any] | None,
    primary_theme: str,
) -> list[str]:
    theme = re.sub(r"\s+", " ", str(primary_theme or "").strip())
    labels: list[str] = []
    kb_snapshot = (signal or {}).get("knowledgeBaseSnapshot")
    if isinstance(kb_snapshot, dict):
        for entry in kb_snapshot.get("alternateTrendTopics") or []:
            if not isinstance(entry, dict):
                continue
            label = re.sub(r"\s+", " ", str(entry.get("topic") or "").strip())
            if not label or label.lower() == theme.lower() or not _is_usable_theme_label(label):
                continue
            if label not in labels:
                labels.append(label)
            if len(labels) >= 3:
                return labels
        for label in _theme_phrases_from_reference_titles(list(kb_snapshot.get("sampleTitles") or [])):
            if label.lower() == theme.lower() or label in labels:
                continue
            labels.append(label)
            if len(labels) >= 3:
                break
    return labels


def _editorial_title_hook(
    *,
    why_now: str,
    signal: dict[str, Any] | None,
    core_sections: list[dict[str, Any]] | None,
    primary_theme: str,
    related_themes: list[str] | None = None,
) -> str:
    theme = re.sub(r"\s+", " ", str(primary_theme or "").strip())
    related = [
        label
        for label in (related_themes or _related_theme_labels_for_title(signal=signal, primary_theme=theme))
        if label and label.lower() != theme.lower() and not _looks_like_domain_label(label)
    ]
    if related:
        return " · ".join(related[:3])
    _ = (why_now, core_sections)
    return ""


def _first_editorial_phrase(text: str, *, max_len: int = 44) -> str:
    cleaned = re.sub(r"[*`_]", "", str(text or "")).strip()
    if not cleaned:
        return ""
    clause = re.split(r"[.!?\n]", cleaned, maxsplit=1)[0].strip()
    if len(clause) <= max_len:
        return clause
    shortened = clause[: max_len - 1].rsplit(" ", 1)[0].strip()
    return shortened or clause[: max_len - 1].strip()


def derive_edition_forum_thread_title(
    *,
    theme_line: str,
    signal: dict[str, Any] | None = None,
    why_fragment: str = "",
    core_sections: list[dict[str, Any]] | None = None,
    related_themes: list[str] | None = None,
) -> str:
    headline = re.sub(r"\s+", " ", str(theme_line or "").strip())
    if not headline:
        return "Upcoming edition"
    hook = _editorial_title_hook(
        why_now=why_fragment or str((signal or {}).get("whyNow") or ""),
        signal=signal,
        core_sections=core_sections,
        primary_theme=headline,
        related_themes=related_themes,
    )
    if hook and not _looks_like_domain_label(hook) and hook.lower() != headline.lower():
        candidate = f"{headline} — {hook}"
        headline = candidate if len(candidate) <= 80 else headline
    if len(headline) <= 80:
        return headline
    shortened = headline[:77].rsplit(" ", 1)[0].strip()
    return f"{shortened}…" if shortened else f"{headline[:77]}…"


def summarize_knowledge_base_for_planning(
    *,
    references: list[dict[str, Any]],
    semantic_nodes: list[dict[str, Any]],
    corpus_key: str,
    topic: str,
    category_key: str = "",
    sections: list[str] | None = None,
    since_days: int = DEFAULT_TREND_WINDOW_DAYS,
    now: str = "",
) -> dict[str, Any]:
    now_dt = _parse_datetime(now) or dt.datetime.now(dt.UTC)
    cutoff = now_dt - dt.timedelta(days=since_days) if since_days > 0 else None
    accepted = _accepted_references(references, corpus_key)
    recent_accepted: list[dict[str, Any]] = []
    for ref in accepted:
        ref_dt = _reference_datetime(ref)
        if cutoff and ref_dt and ref_dt < cutoff:
            continue
        recent_accepted.append(ref)
    topic_terms = _terms(topic)
    topic_matched: list[dict[str, Any]] = []
    for ref in recent_accepted:
        haystack = " ".join([str(ref.get("title") or ""), str(ref.get("sourceUri") or "")]).lower()
        if not topic_terms or any(term in haystack for term in topic_terms):
            topic_matched.append(ref)
    domains = sorted({
        _domain(ref.get("sourceUri"))
        for ref in topic_matched
        if _domain(ref.get("sourceUri"))
    })
    sample_titles = [
        str(ref.get("title") or "").strip()
        for ref in sorted(
            topic_matched,
            key=lambda row: _reference_datetime(row) or now_dt,
            reverse=True,
        )[:5]
        if str(ref.get("title") or "").strip()
    ]
    alternate_topics: list[dict[str, Any]] = []
    if accepted:
        ranked = build_trend_signals(
            references=references,
            semantic_nodes=semantic_nodes,
            corpus_key=corpus_key,
            category_key=category_key,
            topic="",
            coverage_key="",
            sections=sections or [],
            since_days=since_days,
            limit=6,
            now=now,
        )
        for entry in ranked:
            label = str(entry.get("topic") or "").strip()
            if not label or label.lower() == str(topic or "").strip().lower():
                continue
            if not _is_usable_theme_label(label):
                continue
            alternate_topics.append({
                "topic": label,
                "score": entry.get("score"),
                "acceptedEvidenceCount": entry.get("acceptedEvidenceCount"),
            })
            if len(alternate_topics) >= 4:
                break
    return {
        "corpusKey": corpus_key,
        "totalReferencesLoaded": len(references),
        "acceptedCorpusCount": len(accepted),
        "recentAcceptedInWindow": len(recent_accepted),
        "topicMatchedInWindow": len(topic_matched),
        "windowDays": since_days,
        "sourceDomains": domains[:6],
        "sampleTitles": sample_titles,
        "alternateTrendTopics": alternate_topics,
    }


def _why_now_from_knowledge_base_snapshot(
    *,
    topic: str,
    corpus_key: str,
    snapshot: dict[str, Any],
) -> str:
    accepted = int(snapshot.get("acceptedCorpusCount") or 0)
    recent = int(snapshot.get("recentAcceptedInWindow") or 0)
    matched = int(snapshot.get("topicMatchedInWindow") or 0)
    window_days = int(snapshot.get("windowDays") or DEFAULT_TREND_WINDOW_DAYS)
    if accepted <= 0:
        loaded = int(snapshot.get("totalReferencesLoaded") or 0)
        return (
            f"No **accepted** references were found for corpus `{corpus_key}` "
            f"(loaded {loaded} reference record(s) from the knowledge base)."
        )
    if matched > 0:
        domains = ", ".join(list(snapshot.get("sourceDomains") or [])[:3]) or "mixed domains"
        return (
            f"**{topic}** matches {matched} accepted reference(s) in the last {window_days} days "
            f"out of {accepted} accepted in `{corpus_key}` ({recent} recent in-window overall); "
            f"domains include {domains}."
        )
    return (
        f"The `{corpus_key}` corpus has **{accepted}** accepted references ({recent} with activity in the "
        f"last {window_days} days), but **{matched}** clearly mention **{topic}** in that window — "
        f"the spine is editorially proposed; validate against primary sources before filing."
    )


def _coverage_gaps_from_knowledge_base_snapshot(
    *,
    topic: str,
    snapshot: dict[str, Any],
) -> list[str]:
    accepted = int(snapshot.get("acceptedCorpusCount") or 0)
    matched = int(snapshot.get("topicMatchedInWindow") or 0)
    if accepted <= 0:
        return [f"No accepted references are indexed for this corpus yet."]
    if matched <= 0:
        return [
            f"The knowledge base is active ({accepted} accepted references), but **{topic}** "
            f"has no strong in-window keyword matches — confirm the spine against desk sources.",
        ]
    return _coverage_gaps(topic, [])


def _concept_snapshot_from_semantic_nodes(
    *,
    semantic_nodes: list[dict[str, Any]],
    corpus_key: str,
    topic: str,
    limit: int,
) -> dict[str, Any]:
    corpus_id = f"knowledge-corpus-{_safe_id(corpus_key)}"
    topic_terms = _terms(topic)
    rows: list[dict[str, Any]] = []
    for raw_node in semantic_nodes:
        node = _decode_record(raw_node)
        if node.get("versionState") not in {None, "current"}:
            continue
        if node.get("status") not in {None, "", "active", "accepted", "current"}:
            continue
        if corpus_key and node.get("corpusId") not in {None, "", corpus_id, corpus_key}:
            continue
        node_kind = str(node.get("nodeKind") or "")
        if node_kind.startswith(("coverage.", "editorial.form.")):
            continue
        display_name = str(node.get("displayName") or node.get("nodeKey") or "").strip()
        if not display_name or not _is_usable_theme_label(display_name):
            continue
        if display_name.lower() == str(topic or "").strip().lower():
            continue
        haystack = " ".join([display_name, str(node.get("nodeKey") or ""), str(node.get("description") or "")]).lower()
        topic_relevance = sum(1 for term in topic_terms if term in haystack)
        mention_count = int(node.get("acceptedReferenceMentionCount") or 0)
        relation_count = int(node.get("relationCount") or 0)
        if mention_count <= 0 and relation_count <= 0 and topic_relevance <= 0:
            continue
        rows.append({
            "conceptId": str(node.get("id") or ""),
            "conceptLineageId": str(node.get("lineageId") or node.get("id") or ""),
            "displayName": display_name,
            "metric": "acceptedReferenceMentionCount",
            "score": max(mention_count, relation_count),
            "mentionCount": mention_count,
            "distinctReferenceCount": max(mention_count, relation_count),
            "topicRelevance": topic_relevance,
            "authorityScore": float(node.get("authorityScore") or 0),
            "source": "semantic_node",
        })
    rows.sort(
        key=lambda row: (
            -int(row.get("topicRelevance") or 0),
            -int(row.get("mentionCount") or 0),
            -float(row.get("authorityScore") or 0),
            str(row.get("displayName") or ""),
        ),
    )
    capped = rows[:limit]
    return {
        "popularity": capped,
        "trending": [row for row in capped if int(row.get("topicRelevance") or 0) > 0][:limit],
        "rankedForDispatch": capped,
        "source": "semantic_nodes_fallback",
    }


def summarize_concepts_for_planning(
    *,
    references: list[dict[str, Any]],
    semantic_nodes: list[dict[str, Any]],
    semantic_relations: list[dict[str, Any]],
    corpus_key: str,
    topic: str,
    limit: int = DEFAULT_CONCEPT_REPORT_LIMIT,
    now: str = "",
) -> dict[str, Any]:
    if not references or not semantic_nodes:
        return {"popularity": [], "trending": [], "rankedForDispatch": []}
    accepted = _accepted_references(references, corpus_key)
    if not semantic_relations:
        return _concept_snapshot_from_semantic_nodes(
            semantic_nodes=semantic_nodes,
            corpus_key=corpus_key,
            topic=topic,
            limit=limit,
        )
    reports = build_concept_reports(
        references=references,
        semantic_nodes=semantic_nodes,
        semantic_relations=semantic_relations,
        corpus_key=corpus_key,
        report_type="all",
        limit=max(limit, 1),
        trend_window_days=DEFAULT_TREND_WINDOW_DAYS,
        pagerank_iterations=20,
        pagerank_damping=0.85,
        node_kinds=[],
        max_nodes_per_reference=12,
        now=now,
    )
    reports_by_type = {
        str(report.get("reportType") or ""): report
        for report in reports
    }
    popularity = list((reports_by_type.get("popularity") or {}).get("rankedConcepts") or [])
    trending = list((reports_by_type.get("trending") or {}).get("rankedConcepts") or [])
    topic_terms = _terms(topic)

    def topic_relevance(concept: dict[str, Any]) -> int:
        haystack = " ".join([
            str(concept.get("displayName") or ""),
            str(concept.get("nodeKey") or ""),
        ]).lower()
        return sum(1 for term in topic_terms if term in haystack)

    ranked_for_dispatch: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pool in (trending, popularity):
        for concept in pool:
            concept_id = str(concept.get("conceptId") or "")
            if not concept_id or concept_id in seen:
                continue
            seen.add(concept_id)
            ranked_for_dispatch.append({
                **concept,
                "topicRelevance": topic_relevance(concept),
            })
    ranked_for_dispatch.sort(
        key=lambda row: (
            -int(row.get("topicRelevance") or 0),
            -float(row.get("score") or 0),
            str(row.get("displayName") or ""),
        ),
    )
    if not ranked_for_dispatch:
        trend_rows: list[dict[str, Any]] = []
        for signal in build_trend_signals(
            references=references,
            semantic_nodes=semantic_nodes,
            corpus_key=corpus_key,
            topic="",
            sections=[],
            since_days=DEFAULT_TREND_WINDOW_DAYS,
            limit=max(limit * 2, 8),
            now=now,
        ):
            label = str(signal.get("topic") or "").strip()
            if not label or label.lower() == str(topic or "").strip().lower():
                continue
            if not _is_usable_theme_label(label):
                continue
            trend_rows.append({
                "conceptId": str(signal.get("signalId") or ""),
                "displayName": label,
                "metric": "trendSignalScore",
                "score": signal.get("score"),
                "distinctReferenceCount": signal.get("acceptedEvidenceCount"),
                "topicRelevance": 0,
                "source": "trend_signal",
            })
            if len(trend_rows) >= limit:
                break
        if trend_rows:
            return {
                "popularity": trend_rows,
                "trending": trend_rows,
                "rankedForDispatch": trend_rows,
                "source": "trend_signals",
            }
        phrase_rows: list[dict[str, Any]] = []
        topic_terms = _terms(topic)
        topic_matched_titles = [
            str(ref.get("title") or "")
            for ref in accepted
            if not topic_terms or any(term in str(ref.get("title") or "").lower() for term in topic_terms)
        ]
        for label in _theme_phrases_from_reference_titles(topic_matched_titles[:400], limit=limit):
            phrase_rows.append({
                "conceptId": f"phrase-{_hash_short([label])}",
                "displayName": label,
                "metric": "titlePhrase",
                "score": 1,
                "distinctReferenceCount": 1,
                "topicRelevance": 1,
                "source": "reference_title_phrase",
            })
        if phrase_rows:
            return {
                "popularity": phrase_rows,
                "trending": phrase_rows,
                "rankedForDispatch": phrase_rows,
                "source": "reference_title_phrases",
            }
        return _concept_snapshot_from_semantic_nodes(
            semantic_nodes=semantic_nodes,
            corpus_key=corpus_key,
            topic=topic,
            limit=limit,
        )
    return {
        "popularity": popularity[:limit],
        "trending": trending[:limit],
        "rankedForDispatch": ranked_for_dispatch[:limit],
        "source": "concept_mentions",
    }


def _format_concept_planning_section(concept_snapshot: dict[str, Any], *, topic: str) -> list[str]:
    if not concept_snapshot:
        return []
    popularity = list(concept_snapshot.get("popularity") or [])
    trending = list(concept_snapshot.get("trending") or [])
    if not popularity and not trending:
        return []
    lines = [
        "",
        "## Ranked concepts in corpus",
        (
            f"Knowledge-graph concepts most cited in accepted references "
            f"(topic filter: **{topic}** where noted)."
        ),
    ]
    if trending:
        lines.append("")
        lines.append("### Trending (30-day velocity)")
        topic_terms = _terms(topic)
        for concept in trending[:8]:
            name = concept.get("displayName") or concept.get("conceptId")
            recent = concept.get("recentDistinctReferenceCount")
            score = concept.get("score")
            haystack = f"{name} {concept.get('nodeKey') or ''}".lower()
            rel = " · spine-related" if any(term in haystack for term in topic_terms) else ""
            lines.append(
                f"- **{name}** (velocity {score}, {recent} recent sources){rel}"
            )
    if popularity:
        lines.append("")
        lines.append("### Most referenced (corpus-wide)")
        topic_terms = _terms(topic)
        for concept in popularity[:8]:
            name = concept.get("displayName") or concept.get("conceptId")
            refs = concept.get("distinctReferenceCount")
            score = concept.get("score")
            haystack = f"{name} {concept.get('nodeKey') or ''}".lower()
            rel = " · spine-related" if any(term in haystack for term in topic_terms) else ""
            lines.append(f"- **{name}** ({refs} sources, score {score}){rel}")
    dispatch_ranked = list(concept_snapshot.get("rankedForDispatch") or [])
    if dispatch_ranked:
        lines.append("")
        lines.append("### Suggested concept hooks for reporting candidates")
        for concept in dispatch_ranked[:10]:
            name = concept.get("displayName") or concept.get("conceptId")
            lines.append(
                f"- {name} — use for a {topic} story with accountability, reader impact, or evidence-check angles"
            )
    return lines


def _format_knowledge_base_kickoff_section(snapshot: dict[str, Any]) -> list[str]:
    if not snapshot:
        return []
    lines = [
        "",
        "## Knowledge base",
        (
            f"- Corpus `{snapshot.get('corpusKey') or 'unknown'}`: "
            f"**{int(snapshot.get('acceptedCorpusCount') or 0):,}** accepted references "
            f"({int(snapshot.get('recentAcceptedInWindow') or 0):,} with dates in the last "
            f"{int(snapshot.get('windowDays') or DEFAULT_TREND_WINDOW_DAYS)} days)."
        ),
        (
            f"- Topic match for this spine: **{int(snapshot.get('topicMatchedInWindow') or 0):,}** "
            f"accepted reference(s) in-window."
        ),
    ]
    loaded = int(snapshot.get("totalReferencesLoaded") or 0)
    accepted = int(snapshot.get("acceptedCorpusCount") or 0)
    if loaded > accepted:
        lines.append(f"- Loaded **{loaded:,}** reference record(s) from GraphQL; **{accepted:,}** pass accepted + corpus filters.")
    domains = list(snapshot.get("sourceDomains") or [])
    if domains:
        lines.append(f"- Matching source domains: {', '.join(domains)}.")
    sample_titles = list(snapshot.get("sampleTitles") or [])
    if sample_titles:
        lines.append("- Recent matching headlines:")
        for title in sample_titles:
            lines.append(f"  - {title}")
    alternates = list(snapshot.get("alternateTrendTopics") or [])
    if alternates:
        lines.append("- Other trending clusters in-window:")
        for entry in alternates:
            if not isinstance(entry, dict):
                continue
            label = entry.get("topic")
            count = entry.get("acceptedEvidenceCount")
            score = entry.get("score")
            lines.append(f"  - {label} ({count} refs, score {score})")
    return lines


def resolve_edition_theme_signal(
    *,
    signal: dict[str, Any] | None,
    topic: str,
    coverage_key: str,
    corpus_key: str,
    category_key: str,
    sections: list[str],
    state: dict[str, list[dict[str, Any]]],
    now: str = "",
) -> dict[str, Any]:
    if signal:
        return signal
    references = state.get("references") or []
    semantic_nodes = state.get("semanticNodes") or []
    semantic_relations = state.get("semanticRelations") or []
    kb_snapshot = summarize_knowledge_base_for_planning(
        references=references,
        semantic_nodes=semantic_nodes,
        corpus_key=corpus_key,
        topic=topic,
        category_key=category_key,
        sections=sections,
        now=now,
    )
    concept_snapshot = summarize_concepts_for_planning(
        references=references,
        semantic_nodes=semantic_nodes,
        semantic_relations=semantic_relations,
        corpus_key=corpus_key,
        topic=topic,
        now=now,
    )
    if references and corpus_key:
        ranked = build_trend_signals(
            references=references,
            semantic_nodes=semantic_nodes,
            corpus_key=corpus_key,
            category_key=category_key,
            topic=topic,
            coverage_key=coverage_key,
            sections=sections,
            now=now,
        )
        if ranked:
            resolved = dict(ranked[0])
            resolved["knowledgeBaseSnapshot"] = kb_snapshot
            resolved["conceptSnapshot"] = concept_snapshot
            return resolved
    return {
        "signalId": f"signal-{_hash_short([corpus_key, topic, coverage_key])}",
        "rank": 1,
        "topic": topic,
        "coverageKey": coverage_key,
        "categoryKey": category_key,
        "score": 0.0,
        "scoreBreakdown": {},
        "whyNow": _why_now_from_knowledge_base_snapshot(
            topic=topic,
            corpus_key=corpus_key,
            snapshot=kb_snapshot,
        ),
        "sourceReferenceIds": [],
        "acceptedEvidenceCount": int(kb_snapshot.get("topicMatchedInWindow") or 0),
        "sourceDomains": list(kb_snapshot.get("sourceDomains") or []),
        "sectionFit": {},
        "proposedSections": sections,
        "coverageGaps": _coverage_gaps_from_knowledge_base_snapshot(topic=topic, snapshot=kb_snapshot),
        "openQuestions": _open_questions(topic, sections),
        "suggestedAngles": _suggested_angles(topic, sections),
        "knowledgeBaseSnapshot": kb_snapshot,
        "conceptSnapshot": concept_snapshot,
    }


def collect_recent_edition_themes(
    editions: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    *,
    exclude_edition_id: str,
    limit: int = 6,
) -> list[dict[str, str]]:
    themes: list[dict[str, str]] = []
    messages_by_thread: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        thread_id = str(message.get("threadId") or "").strip()
        if thread_id:
            messages_by_thread.setdefault(thread_id, []).append(message)
    for edition in sorted(editions, key=lambda row: str(row.get("editionDate") or ""), reverse=True):
        edition_id = str(edition.get("id") or "")
        if not edition_id or edition_id == exclude_edition_id:
            continue
        metadata = _metadata(edition)
        theme = str(metadata.get("proposedEditionTheme") or metadata.get("kickoffThreadTitle") or "").strip()
        if not theme:
            thread_id = f"message-thread-edition-forum-{_safe_id(edition_id)}"
            kickoff_messages = sorted(
                messages_by_thread.get(thread_id, []),
                key=lambda row: int(row.get("sequenceNumber") or 0),
            )
            for message in kickoff_messages:
                if _message_planning_phase(message) == "edition_theme_kickoff":
                    theme = str(message.get("summary") or "").strip()
                    break
                if "edition theme (phase 1)" in str(message.get("summary") or "").lower():
                    theme = str(message.get("summary") or "").split(":", 1)[-1].strip()
                    break
        if not theme:
            continue
        themes.append({
            "editionDate": str(edition.get("editionDate") or ""),
            "theme": theme,
        })
        if len(themes) >= limit:
            break
    return themes


def build_edition_theme_kickoff_draft(
    *,
    topic: str,
    coverage_key: str,
    signal: dict[str, Any],
    core_sections: list[dict[str, Any]],
    optional_desk_sections: list[dict[str, Any]],
    recent_optional_desk_usage: list[dict[str, Any]],
    recent_edition_themes: list[dict[str, str]],
    edition_date: str = "",
) -> dict[str, str]:
    primary_theme = str(signal.get("topic") or topic).strip() or topic
    resolved_coverage = str(signal.get("coverageKey") or coverage_key).strip() or coverage_key
    why_now = str(signal.get("whyNow") or "").strip()
    score_breakdown = signal.get("scoreBreakdown") if isinstance(signal.get("scoreBreakdown"), dict) else {}
    lines = [
        f"# {primary_theme}",
        "",
        "## Why this edition",
        why_now or f"Accepted knowledge-base activity supports treating **{primary_theme}** as the edition spine.",
        f"Coverage concept: `{resolved_coverage}`.",
    ]
    if edition_date:
        lines.append(f"Edition date: {edition_date}.")
    kb_snapshot = signal.get("knowledgeBaseSnapshot")
    if isinstance(kb_snapshot, dict):
        lines.extend(_format_knowledge_base_kickoff_section(kb_snapshot))
    concept_snapshot = signal.get("conceptSnapshot")
    if isinstance(concept_snapshot, dict):
        lines.extend(_format_concept_planning_section(concept_snapshot, topic=primary_theme))
    if score_breakdown:
        lines.append("")
        lines.append("Signal mix (from trend report):")
        for key, value in score_breakdown.items():
            lines.append(f"- {key}: {value}")
    evidence_count = int(signal.get("acceptedEvidenceCount") or 0)
    domains = list(signal.get("sourceDomains") or [])[:6]
    if evidence_count:
        domain_text = ", ".join(domains) if domains else "mixed domains"
        lines.append(f"- {evidence_count} accepted reference(s) in the signal window; domains include {domain_text}.")
    if recent_edition_themes:
        lines.append("")
        lines.append("Recent edition spines (avoid repeating without a reason):")
        for entry in recent_edition_themes:
            date_label = entry.get("editionDate") or "unknown date"
            lines.append(f"- {date_label}: {entry.get('theme')}")
    lines.extend([
        "",
        "## Proposed spine",
        (
            f"Lead with **{primary_theme}** as the shared coverage question, not as the headline for every desk. "
            "Each section should pursue distinct story seeds below."
        ),
        "",
        "## Desk-shaped story seeds",
    ])
    angles_by_section: dict[str, str] = {}
    for entry in signal.get("suggestedAngles") or []:
        if isinstance(entry, dict):
            key = str(entry.get("sectionKey") or "").strip()
            angle = str(entry.get("angle") or "").strip()
            if key and angle:
                angles_by_section[key] = angle
    section_fit = signal.get("sectionFit") if isinstance(signal.get("sectionFit"), dict) else {}
    if core_sections:
        for section in core_sections:
            section_title = section.get("sectionTitle") or section.get("sectionKey")
            section_key = str(section.get("sectionKey") or section.get("sectionId") or "")
            slots = int(section.get("slots") or 1)
            fit_score = section_fit.get(section_key)
            lines.append("")
            lines.append(f"### {section_title}")
            desk_lens = section_research_lens(section_key)
            fit_note = f" KB fit {fit_score:.2f}." if isinstance(fit_score, (int, float)) else ""
            lines.append(f"Target: {slots} slot(s). Desk lens: {desk_lens}.{fit_note}")
            section_angle = angles_by_section.get(section_key) or f"{desk_lens} applied to {primary_theme}"
            angle_lenses = list(REPORTING_ANGLE_LENSES)
            for index in range(max(slots, min(3, len(angle_lenses)))):
                angle = angle_lenses[index % len(angle_lenses)]
                seed = section_angle if index == 0 else f"{primary_theme} — {angle['label']}: {angle['prompt']}"
                lines.append(f"- **{angle['label']}**: {seed}")
    else:
        lines.append("- No canonical desks were slotted in this pass.")
    gaps = list(signal.get("coverageGaps") or [])
    questions = list(signal.get("openQuestions") or [])
    if gaps or questions:
        lines.append("")
        lines.append("Open editorial questions")
        for item in [*gaps, *questions][:8]:
            lines.append(f"- {item}")
    if optional_desk_sections or recent_optional_desk_usage:
        lines.append("")
        lines.append("Optional desk rotation")
        if recent_optional_desk_usage:
            for entry in recent_optional_desk_usage:
                lines.append(
                    f"- {entry.get('editionDate') or 'unknown date'} used optional desk "
                    f"{entry.get('sectionTitle') or entry.get('sectionKey')}"
                )
        if optional_desk_sections:
            optional_names = ", ".join(
                str(section.get("sectionTitle") or section.get("sectionKey") or "")
                for section in optional_desk_sections
            )
            if optional_names:
                lines.append(f"- Candidate optional desks this cycle: {optional_names}.")
    body = "\n".join(lines).strip() + "\n"
    related_themes = _related_theme_labels_for_title(signal=signal, primary_theme=primary_theme)
    thread_title = derive_edition_forum_thread_title(
        theme_line=primary_theme,
        signal=signal,
        why_fragment=why_now,
        core_sections=core_sections,
        related_themes=related_themes,
    )
    return {
        "primary_theme": primary_theme,
        "body": body,
        "thread_title": thread_title,
        "thread_summary": thread_title,
        "message_summary": thread_title,
    }


def _edition_theme_forum_body(
    *,
    topic: str,
    coverage_key: str,
    core_sections: list[dict[str, Any]],
    optional_desk_sections: list[dict[str, Any]],
    recent_optional_desk_usage: list[dict[str, Any]],
    steering_window_hours: int = DEFAULT_STEERING_WINDOW_HOURS,
    signal: dict[str, Any] | None = None,
    recent_edition_themes: list[dict[str, str]] | None = None,
    edition_date: str = "",
) -> str:
    _ = steering_window_hours
    draft = build_edition_theme_kickoff_draft(
        topic=topic,
        coverage_key=coverage_key,
        signal=signal or resolve_edition_theme_signal(
            signal=None,
            topic=topic,
            coverage_key=coverage_key,
            corpus_key="",
            category_key="",
            sections=[str(section.get("sectionKey") or "") for section in core_sections],
            state={},
        ),
        core_sections=core_sections,
        optional_desk_sections=optional_desk_sections,
        recent_optional_desk_usage=recent_optional_desk_usage,
        recent_edition_themes=recent_edition_themes or [],
        edition_date=edition_date,
    )
    return draft["body"]


def _edition_forum_kickoff_body(**kwargs: Any) -> str:
    """Backward-compatible alias for tests and replan helpers."""
    return _edition_theme_forum_body(**kwargs)


def _message_planning_phase(message: dict[str, Any]) -> str:
    metadata = _metadata(message)
    return str(metadata.get("planningPhase") or "").strip()


def should_defer_reporting_dispatch_forum(
    plan: dict[str, Any],
    *,
    skip_rotating_desk: bool,
    include_optional_desks: bool,
    selected_optional_desk_key: str,
) -> bool:
    """Phase 3 waits for phase 2 when optional desks are still provisional."""
    if include_optional_desks or selected_optional_desk_key:
        return False
    if skip_rotating_desk:
        return False
    return bool(plan.get("provisionalOptionalDesks"))


def _reporting_dispatch_forum_body(
    *,
    topic: str,
    coverage_key: str,
    reporting_assignments: list[dict[str, Any]],
    edition_slots: list[dict[str, Any]],
    section_budgets: dict[str, int],
    section_titles: dict[str, str],
    concept_snapshot: dict[str, Any] | None = None,
) -> str:
    slots_by_section: dict[str, list[dict[str, Any]]] = {}
    for slot in edition_slots:
        section_key = str(slot.get("sectionKey") or "")
        slots_by_section.setdefault(section_key, []).append(slot)
    assignments_by_section: dict[str, list[dict[str, Any]]] = {}
    for assignment in reporting_assignments:
        section_key = str(assignment.get("sectionKey") or "")
        assignments_by_section.setdefault(section_key, []).append(assignment)
    section_keys = sorted(set(slots_by_section) | set(assignments_by_section))
    _ = section_budgets
    lines = [
        "# Reporting candidates",
        "",
    ]
    if isinstance(concept_snapshot, dict) and concept_snapshot.get("rankedForDispatch"):
        lines.extend(_format_concept_planning_section(concept_snapshot, topic=topic))
        lines.append("")
    lines.extend([
        "## By desk",
    ])
    if not section_keys:
        lines.append("- No reporting assignments were materialized for this pass.")
    for section_key in section_keys:
        section_title = section_titles.get(section_key) or section_key
        lines.append("")
        lines.append(f"### {section_title} (`{section_key}`)")
        candidates = sorted(
            assignments_by_section.get(section_key, []),
            key=lambda row: (
                int((_metadata(row).get("slotTarget") or {}).get("candidateRank") or 0),
                str(row.get("id") or ""),
            ),
        )
        if not candidates:
            lines.append("- No reporting assignments listed for this desk.")
            continue
        for assignment in candidates:
            meta = _metadata(assignment)
            slot_target = meta.get("slotTarget") or {}
            angle = (meta.get("angleDiversity") or {})
            candidate_rank = slot_target.get("candidateRank") or "?"
            slot_rank = slot_target.get("slotRank") or "?"
            angle_label = angle.get("lensLabel") or angle.get("lensKey") or "angle"
            concept_hook = (meta.get("conceptHook") or {}).get("displayName")
            concept_suffix = f" · concept: {concept_hook}" if concept_hook else ""
            lines.append(
                f"- Candidate {candidate_rank} → slot {slot_rank} ({angle_label}){concept_suffix}: {assignment.get('title')}"
            )
    return "\n".join(lines).strip() + "\n"


def _existing_reporting_dispatch_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in _active_forum_thread_messages(messages):
        if _message_planning_phase(message) == "reporting_dispatch":
            return message
        summary = str(message.get("summary") or "").lower()
        content = str(message.get("content") or "").lower()
        if "reporting dispatch (phase 3)" in summary or content.startswith("# reporting candidates"):
            return message
    return None


def build_reporting_dispatch_forum_records(
    *,
    edition: dict[str, Any],
    topic: str,
    coverage_key: str,
    reporting_assignments: list[dict[str, Any]],
    edition_slots: list[dict[str, Any]],
    section_budgets: dict[str, int],
    section_titles: dict[str, str],
    run_id: str,
    now: str,
    existing_threads: list[dict[str, Any]] | None = None,
    existing_messages: list[dict[str, Any]] | None = None,
    concept_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    edition_id = str(edition.get("id") or "")
    existing_threads = existing_threads or []
    existing_messages = existing_messages or []
    canonical_thread_id = _canonical_edition_forum_thread_id(edition_id)
    existing_messages_by_thread: dict[str, list[dict[str, Any]]] = {}
    for message in existing_messages:
        thread_id = str(message.get("threadId") or "").strip()
        if thread_id:
            existing_messages_by_thread.setdefault(thread_id, []).append(message)
    thread_messages = existing_messages_by_thread.get(canonical_thread_id, [])
    existing_dispatch = _existing_reporting_dispatch_message(thread_messages)
    if existing_dispatch:
        existing_thread = next(
            (thread for thread in existing_threads if str(thread.get("id") or "") == canonical_thread_id),
            edition_forum_thread_record(edition_id=edition_id, run_id=run_id, now=now, thread_id=canonical_thread_id),
        )
        return {
            "thread": existing_thread,
            "message": existing_dispatch,
            "records": [],
            "action": "skip",
        }
    existing_edition_thread = next(
        (thread for thread in existing_threads if str(thread.get("id") or "") == canonical_thread_id),
        None,
    )
    thread = edition_forum_thread_record(
        edition_id=edition_id,
        run_id=run_id,
        now=now,
        thread_id=canonical_thread_id,
        existing=existing_edition_thread,
        message_count=int((existing_edition_thread or {}).get("messageCount") or 0),
        last_message_id=str((existing_edition_thread or {}).get("lastMessageId") or ""),
    )
    sequence_number = _next_forum_sequence(thread_messages)
    if concept_snapshot is None:
        concept_snapshot = {}
    content = _reporting_dispatch_forum_body(
        topic=topic,
        coverage_key=coverage_key,
        reporting_assignments=reporting_assignments,
        edition_slots=edition_slots,
        section_budgets=section_budgets,
        section_titles=section_titles,
        concept_snapshot=concept_snapshot,
    )
    message = forum_kickoff_message_record(
        thread=thread,
        role="editor",
        author_label="papyrus-editor",
        summary=f"Reporting candidates: {topic}",
        content=content,
        now=now,
        sequence_number=sequence_number,
        message_metadata={"planningPhase": "reporting_dispatch"},
    )
    thread["messageCount"] = max(int(thread.get("messageCount") or 0), sequence_number)
    thread["lastMessageId"] = message["id"]
    thread["lastMessageAt"] = now
    return {
        "thread": thread,
        "message": message,
        "records": [
            _record("MessageThread", thread),
            _record("Message", message),
            _record("SemanticRelation", semantic_relation(
                predicate="planned_for_edition",
                subject_kind="message",
                subject_id=message["id"],
                object_kind="edition",
                object_id=edition_id,
                object_lineage_id=edition.get("lineageId") or edition_id,
                object_version_number=edition.get("versionNumber") or 1,
                import_run_id=run_id,
                now=now,
                metadata={
                    "runId": run_id,
                    "threadId": thread["id"],
                    "forumScope": "edition",
                    "planningPhase": "reporting_dispatch",
                },
            )),
        ],
        "action": "create",
    }


def _section_titles_for_dispatch(plan: dict[str, Any]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for section in plan.get("sections") or []:
        key = str(section.get("key") or "")
        if key:
            titles[key] = str(section.get("title") or key)
    for section in plan.get("dispatchSections") or []:
        key = str(section.get("key") or "")
        if key:
            titles[key] = str(section.get("title") or key)
    selected = str(_metadata(plan.get("edition") or {}).get("selectedOptionalDeskKey") or "")
    if selected and selected not in titles:
        titles[selected] = selected
    return titles


def _reporting_assignments_for_edition_from_state(
    state: dict[str, list[dict[str, Any]]],
    *,
    edition_id: str,
    fallback: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    assignments = []
    for assignment in state.get("assignments") or []:
        if str(assignment.get("assignmentTypeKey") or "") != "reporting.edition-candidate":
            continue
        metadata = _metadata(assignment)
        if str(metadata.get("editionId") or "") != edition_id:
            continue
        assignments.append(assignment)
    if assignments:
        return assignments
    return list(fallback or [])


def _edition_slots_for_edition_from_state(
    state: dict[str, list[dict[str, Any]]],
    *,
    edition_id: str,
    fallback: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    slots = [
        slot
        for slot in (state.get("editionSlots") or [])
        if str(slot.get("editionId") or "") == edition_id
    ]
    if slots:
        return slots
    return list(fallback or [])


def append_reporting_dispatch_forum_records(
    records: list[dict[str, Any]],
    *,
    plan: dict[str, Any],
    topic: str,
    coverage_key: str,
    section_budgets: dict[str, int],
    run_id: str,
    now: str,
    state: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    edition = plan["edition"]
    edition_id = str(edition.get("id") or "")
    thread_messages = _canonical_edition_forum_thread_messages(
        edition_id=edition_id,
        state=state,
        pending_records=records,
    )
    concept_snapshot = summarize_concepts_for_planning(
        references=state.get("references") or [],
        semantic_nodes=state.get("semanticNodes") or [],
        semantic_relations=state.get("semanticRelations") or [],
        corpus_key=str(plan.get("corpusKey") or ""),
        topic=topic,
        now=now,
    )
    dispatch_forum = build_reporting_dispatch_forum_records(
        edition=edition,
        topic=topic,
        coverage_key=coverage_key or plan.get("coverageKey") or "",
        reporting_assignments=_reporting_assignments_for_edition_from_state(
            state,
            edition_id=edition_id,
            fallback=list(plan.get("reportingAssignments") or []),
        ),
        edition_slots=_edition_slots_for_edition_from_state(
            state,
            edition_id=edition_id,
            fallback=list(plan.get("editionSlots") or []),
        ),
        section_budgets=section_budgets,
        section_titles=_section_titles_for_dispatch(plan),
        run_id=run_id,
        now=now,
        existing_threads=state.get("messageThreads") or [],
        existing_messages=thread_messages,
        concept_snapshot=concept_snapshot,
    )
    if dispatch_forum.get("records"):
        records.extend(dispatch_forum["records"])
    return dispatch_forum


def _section_forum_kickoff_body(
    *,
    topic: str,
    section: dict[str, Any],
    coverage_key: str,
    steering_window_hours: int = DEFAULT_STEERING_WINDOW_HOURS,
) -> str:
    _ = steering_window_hours, section.get("slots"), section.get("dispatchCount")
    return "\n".join([
        f"# {section['sectionTitle']}",
        "",
        f"Edition theme: **{topic}**",
        f"Coverage: `{coverage_key}`",
    ]).strip() + "\n"


def _section_planning_role(section: dict[str, Any]) -> str:
    section_type = _normalize_section_type(section.get("type"))
    if section_type in OPTIONAL_DESK_SECTION_TYPES:
        return "optional_desk"
    return "canonical"


def _partition_sections_for_planning(
    section_summary: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    core_sections = [section for section in section_summary if section.get("planningRole") != "optional_desk"]
    optional_desk_sections = [section for section in section_summary if section.get("planningRole") == "optional_desk"]
    return core_sections, optional_desk_sections


def confirmed_optional_desk_key_for_edition(edition: dict[str, Any]) -> str:
    """Return the optional desk only when phase 2 (or a human override) confirmed it."""
    metadata = _metadata(edition)
    section_key = str(metadata.get("selectedOptionalDeskKey") or "").strip()
    if section_key:
        return section_key
    if str(metadata.get("rotatingDeskStatus") or "").strip().lower() != "selected":
        return ""
    recommendation = metadata.get("optionalDeskRecommendation")
    if isinstance(recommendation, dict):
        return str(recommendation.get("recommendedSectionKey") or "").strip()
    return ""


def collect_recent_optional_desk_usage(
    editions: list[dict[str, Any]],
    *,
    section_budgets: dict[str, int] | None = None,
    exclude_edition_id: str = "",
    limit: int = 8,
) -> list[dict[str, Any]]:
    """
    Grounded optional-desk history from prior editions that completed step 2.

    sectionBudgets and provisional phase-1 names are intentionally ignored so
    planning runs do not invent rotation history.
    """
    _ = section_budgets
    section_seeds = {section["id"]: section for section in load_newsroom_section_seeds()}
    excluded = str(exclude_edition_id or "").strip()
    usage: list[dict[str, Any]] = []
    for edition in sorted(editions, key=lambda row: str(row.get("editionDate") or ""), reverse=True):
        if excluded and str(edition.get("id") or "") == excluded:
            continue
        section_key = confirmed_optional_desk_key_for_edition(edition)
        if not section_key:
            continue
        seed = section_seeds.get(section_key) or {}
        section_type = _normalize_section_type(seed.get("type"))
        if section_type not in OPTIONAL_DESK_SECTION_TYPES:
            continue
        usage.append({
            "editionId": edition.get("id"),
            "editionDate": edition.get("editionDate"),
            "sectionKey": section_key,
            "sectionTitle": seed.get("title") or section_key,
            "sectionType": section_type,
            "selectionSource": "confirmed",
        })
        if len(usage) >= limit:
            break
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in usage:
        key = f"{entry.get('editionDate')}:{entry.get('sectionKey')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
        if len(deduped) >= limit:
            break
    return deduped


def load_newsroom_section_seeds() -> list[dict[str, Any]]:
    try:
        from papyrus_content.newsroom_sections import load_newsroom_section_seeds as _load_seeds
    except ImportError:  # pragma: no cover - package layout fallback
        return []
    return _load_seeds()


def build_rotating_section_selection_context(
    *,
    edition: dict[str, Any],
    topic: str,
    coverage_key: str,
    existing_editions: list[dict[str, Any]] | None = None,
    candidate_section_keys: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build structured input for the rotating-desk selector Tactus procedure (planning step 2).
    """
    seeds = {section["id"]: section for section in load_newsroom_section_seeds()}
    candidates = []
    for section_key in candidate_section_keys or []:
        seed = seeds.get(section_key)
        if not seed:
            continue
        if _normalize_section_type(seed.get("type")) not in OPTIONAL_DESK_SECTION_TYPES:
            continue
        candidates.append({
            "sectionKey": section_key,
            "sectionTitle": seed.get("title") or section_key,
            "sectionType": _normalize_section_type(seed.get("type")),
            "editorialMission": seed.get("editorialMission"),
        })
    if not candidates:
        candidates = [
            {
                "sectionKey": section["id"],
                "sectionTitle": section.get("title") or section["id"],
                "sectionType": _normalize_section_type(section.get("type")),
                "editorialMission": section.get("editorialMission"),
            }
            for section in seeds.values()
            if _normalize_section_type(section.get("type")) in OPTIONAL_DESK_SECTION_TYPES and section.get("enabled", True)
        ]
    return {
        "editionId": edition.get("id"),
        "editionDate": edition.get("editionDate"),
        "acceptedTheme": topic,
        "coverageKey": coverage_key,
        "candidateSections": candidates,
        "recentOptionalDeskUsage": collect_recent_optional_desk_usage(
            existing_editions or [],
            exclude_edition_id=str(edition.get("id") or ""),
        ),
        "procedurePath": "procedures/newsroom/rotating_section_selector.tac",
    }


def build_edition_metadata_update_record(
    edition: dict[str, Any],
    metadata_patch: dict[str, Any],
) -> dict[str, Any]:
    merged_metadata = {**_metadata(edition), **metadata_patch}
    payload = {
        "id": edition.get("id"),
        "metadata": merged_metadata,
        "contentHash": _hash_stable({
            "slug": edition.get("slug"),
            "editionDate": edition.get("editionDate"),
            "metadata": merged_metadata,
        }),
    }
    return _record("Edition", _prepare_input("Edition", payload), action="update")


def optional_desk_research_assignment_id(*, run_id: str, section_key: str) -> str:
    return f"assignment-coverage-theme-research-{_safe_id(run_id)}-{_safe_id(section_key)}"


def optional_desk_slot_ids(*, edition_id: str, section_key: str, slots: int) -> list[str]:
    slot_count = max(1, int(slots or 1))
    return [
        f"edition-slot-{_safe_id(edition_id)}-{_safe_id(section_key)}-{rank:02d}-v1"
        for rank in range(1, slot_count + 1)
    ]


def optional_desk_assignments_from_state(
    state: dict[str, list[dict[str, Any]]],
    *,
    run_id: str,
    section_key: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    research_id = optional_desk_research_assignment_id(run_id=run_id, section_key=section_key)
    research_assignments: list[dict[str, Any]] = []
    reporting_assignments: list[dict[str, Any]] = []
    section_token = _safe_id(section_key)
    run_token = _safe_id(run_id)
    for assignment in state.get("assignments") or []:
        assignment_id = str(assignment.get("id") or "")
        if assignment_id == research_id:
            research_assignments.append(assignment)
            continue
        if (
            "assignment-coverage-theme-reporting" in assignment_id
            and section_token in assignment_id
            and run_token in assignment_id
        ):
            reporting_assignments.append(assignment)
    return research_assignments, reporting_assignments


def optional_desk_dispatch_exists(
    state: dict[str, list[dict[str, Any]]],
    *,
    run_id: str,
    section_key: str,
    edition_id: str,
    section_budgets: dict[str, int],
) -> bool:
    slots = max(1, int(section_budgets.get(section_key, DEFAULT_SECTION_BUDGETS.get(section_key, 1))))
    expected_slots = set(optional_desk_slot_ids(edition_id=edition_id, section_key=section_key, slots=slots))
    edition_slot_ids = {str(slot.get("id") or "") for slot in (state.get("editionSlots") or [])}
    if not expected_slots.intersection(edition_slot_ids):
        return False
    assignment_ids = {
        str(assignment.get("id") or "")
        for assignment in (state.get("assignments") or [])
    }
    research_id = optional_desk_research_assignment_id(run_id=run_id, section_key=section_key)
    if research_id in assignment_ids:
        return True
    for assignment in state.get("assignments") or []:
        if str(assignment.get("sectionKey") or assignment.get("sectionId") or "") != section_key:
            continue
        if "assignment-coverage-theme-research" not in str(assignment.get("id") or ""):
            continue
        metadata = _metadata(assignment)
        if str(metadata.get("editionId") or "") == edition_id:
            return True
    return False


def _edition_theme_kickoff_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Phase-1 theme kickoff posts only — never optional-desk or reporting-dispatch messages."""
    result: list[dict[str, Any]] = []
    for message in _active_forum_thread_messages(messages):
        if _message_planning_phase(message) == "edition_theme_kickoff":
            result.append(message)
            continue
        content = str(message.get("content") or "")
        summary = str(message.get("summary") or "").lower()
        if "edition theme (phase 1)" in summary:
            result.append(message)
            continue
        if content.startswith("# ") and "## Why this edition" in content:
            result.append(message)
    return result


def _plan_forum_kickoff_supersede_records(
    existing_messages_by_thread: dict[str, list[dict[str, Any]]],
    *,
    now: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for messages in existing_messages_by_thread.values():
        for message in _edition_theme_kickoff_messages(messages):
            update_payload = _prepare_input(
                "Message",
                {**message, "status": "deleted", "updatedAt": now},
            )
            records.append(_record("Message", update_payload, action="update"))
    return records


def _edition_forum_planning_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All automated edition-forum planning posts (theme, optional desk, reporting)."""
    result: list[dict[str, Any]] = []
    for message in _active_forum_thread_messages(messages):
        phase = _message_planning_phase(message)
        if phase in {
            "edition_theme_kickoff",
            "theme_proposal",
            "rotating_desk_selection",
            "reporting_dispatch",
        }:
            result.append(message)
            continue
        summary = str(message.get("summary") or "").lower()
        content = str(message.get("content") or "")
        if "edition theme (phase 1)" in summary:
            result.append(message)
            continue
        if content.startswith("# ") and "## Why this edition" in content:
            result.append(message)
            continue
        if (
            summary.startswith("optional desk:")
            or "optional desk (phase 2)" in summary
            or "optional desk suggestion" in summary
        ):
            result.append(message)
            continue
        if content.startswith("# reporting candidates") or summary.startswith("reporting candidates:"):
            result.append(message)
    return result


def _plan_forum_refresh_supersede_records(
    existing_messages_by_thread: dict[str, list[dict[str, Any]]],
    *,
    now: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for messages in existing_messages_by_thread.values():
        for message in _edition_forum_planning_messages(messages):
            update_payload = _prepare_input(
                "Message",
                {**message, "status": "deleted", "updatedAt": now},
            )
            records.append(_record("Message", update_payload, action="update"))
    return records


def _mark_forum_supersede_records_in_state(
    state: dict[str, list[dict[str, Any]]],
    records: list[dict[str, Any]],
) -> None:
    updates = {
        str(record.get("input", {}).get("id") or ""): record.get("input") or {}
        for record in records
        if record.get("modelName") == "Message" and record.get("action") == "update"
    }
    if not updates:
        return
    for message in state.get("messages") or []:
        message_id = str(message.get("id") or "")
        if message_id in updates:
            message.update(updates[message_id])


def fallback_rotating_section_selection(
    *,
    context: dict[str, Any],
    provisional_section_keys: list[str] | None = None,
) -> dict[str, Any]:
    candidates = list(context.get("candidateSections") or [])
    if provisional_section_keys:
        allowed = {str(key) for key in provisional_section_keys}
        candidates = [candidate for candidate in candidates if candidate.get("sectionKey") in allowed]
    if not candidates:
        raise ValueError("No optional desk candidates available for rotating-desk selection.")
    recent_usage = list(context.get("recentOptionalDeskUsage") or [])
    recency_rank: dict[str, int] = {}
    for index, entry in enumerate(recent_usage):
        section_key = str(entry.get("sectionKey") or "").strip()
        if section_key and section_key not in recency_rank:
            recency_rank[section_key] = index
    ranked_candidates = sorted(
        candidates,
        key=lambda candidate: recency_rank.get(str(candidate.get("sectionKey") or ""), 999),
        reverse=True,
    )
    chosen = ranked_candidates[0]
    chosen_key = str(chosen.get("sectionKey") or "")
    has_prior_selections = bool(recent_usage)
    avoided = (
        [key for key in recency_rank if key and key != chosen_key]
        if has_prior_selections
        else []
    )
    never_used = chosen_key not in recency_rank
    chosen_title = chosen.get("sectionTitle") or chosen_key
    return _normalize_rotating_section_selection_output(
        {
            "recommended_section_key": chosen_key,
            "recommended_section_title": chosen_title,
            "recommendation_summary": (
                f"Propose {chosen_title} as the optional desk for this edition."
                if not has_prior_selections
                else (
                    f"Propose {chosen_title}; it has the oldest confirmed optional-desk use among prior editions."
                    if not never_used
                    else f"Propose {chosen_title}; it has not been the confirmed optional desk in prior editions."
                )
            ),
            "avoided_sections": avoided,
            "recent_usage": recent_usage,
            "rationale": (
                "Deterministic fallback chose an optional desk; no prior edition has confirmed one yet."
                if not has_prior_selections
                else (
                    "Deterministic fallback rotated away from the most recently confirmed optional desk."
                    if not never_used
                    else "Deterministic fallback chose an optional desk not used in confirmed prior editions."
                )
            ),
        },
        context=context,
    )


def _normalize_rotating_section_selection_output(
    output: dict[str, Any],
    *,
    context: dict[str, Any],
) -> dict[str, Any]:
    section_key = str(
        output.get("recommended_section_key")
        or output.get("recommendedSectionKey")
        or ""
    ).strip()
    section_title = str(
        output.get("recommended_section_title")
        or output.get("recommendedSectionTitle")
        or section_key
    ).strip()
    return {
        "editionId": context.get("editionId"),
        "acceptedTheme": context.get("acceptedTheme"),
        "recommendedSectionKey": section_key,
        "recommendedSectionTitle": section_title,
        "recommendationSummary": str(
            output.get("recommendation_summary") or output.get("recommendationSummary") or ""
        ).strip(),
        "avoidedSections": list(output.get("avoided_sections") or output.get("avoidedSections") or []),
        "recentUsage": list(context.get("recentOptionalDeskUsage") or []),
        "rationale": str(output.get("rationale") or "").strip(),
        "degraded": bool(output.get("degraded")),
    }


def run_cloud_rotating_section_selection(
    *,
    client: Any,
    run_id: str,
    context: dict[str, Any],
    steering_notes: str = "",
    provisional_section_keys: list[str] | None = None,
) -> dict[str, Any]:
    run_dir = Path(".papyrus-runs") / run_id / "rotating-desk"
    cloud_run = _start_cloud_procedure_run(
        client=client,
        alias=ROTATING_DESK_PROCEDURE_ALIAS,
        actor_label="papyrus coverage-themes run",
        title=f"Select optional desk for {context.get('editionDate') or context.get('editionId')}",
        summary=f"Rotating desk selection for {context.get('acceptedTheme')}.",
        input_payload={
            "edition_id": context.get("editionId"),
            "accepted_theme": context.get("acceptedTheme"),
            "coverage_key": context.get("coverageKey"),
            "candidate_sections_json": json.dumps(context.get("candidateSections") or []),
            "recent_usage_json": json.dumps(context.get("recentOptionalDeskUsage") or []),
            "steering_notes": steering_notes,
        },
        run_dir=run_dir,
        source_path=run_dir / "rotating-desk.cloud.tac",
        stdout_path=run_dir / "rotating-desk.stdout.log",
        stderr_path=run_dir / "rotating-desk.stderr.log",
    )
    output = cloud_run.get("output") if isinstance(cloud_run.get("output"), dict) else {}
    normalized = _normalize_rotating_section_selection_output(output, context=context)
    if not normalized["recommendedSectionKey"]:
        return fallback_rotating_section_selection(context=context, provisional_section_keys=provisional_section_keys)
    normalized["cloudRun"] = cloud_run
    return normalized


def run_or_fallback_rotating_section_selection(
    *,
    client: Any | None,
    run_id: str,
    context: dict[str, Any],
    allow_fallback: bool,
    steering_notes: str = "",
    provisional_section_keys: list[str] | None = None,
) -> dict[str, Any]:
    if client is None:
        if not allow_fallback:
            raise ValueError("Cloud procedure client is unavailable for rotating-desk selection.")
        selection = fallback_rotating_section_selection(
            context=context,
            provisional_section_keys=provisional_section_keys,
        )
        selection["degraded"] = True
        return {"ok": True, "selection": selection, "degraded": True}
    try:
        selection = run_cloud_rotating_section_selection(
            client=client,
            run_id=run_id,
            context=context,
            steering_notes=steering_notes,
            provisional_section_keys=provisional_section_keys,
        )
        return {"ok": True, "selection": selection, "degraded": bool(selection.get("degraded"))}
    except Exception as error:
        if not allow_fallback:
            raise
        selection = fallback_rotating_section_selection(
            context=context,
            provisional_section_keys=provisional_section_keys,
        )
        selection["degraded"] = True
        selection["error"] = str(error)
        return {"ok": True, "selection": selection, "degraded": True}


def build_rotating_desk_forum_records(
    *,
    edition: dict[str, Any],
    selection: dict[str, Any],
    topic: str,
    run_id: str,
    now: str,
    existing_threads: list[dict[str, Any]],
    existing_messages_by_thread: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    edition_id = str(edition.get("id") or "")
    canonical_thread_id = f"message-thread-edition-forum-{_safe_id(edition_id)}"
    section_title = str(selection.get("recommendedSectionTitle") or selection.get("recommendedSectionKey") or "")
    existing_recommendation = _existing_optional_desk_recommendation(
        existing_messages_by_thread.get(canonical_thread_id, []),
        section_title=section_title,
        run_id=run_id,
    )
    if existing_recommendation:
        existing_thread = next(
            (thread for thread in existing_threads if str(thread.get("id") or "") == canonical_thread_id),
            edition_forum_thread_record(edition_id=edition_id, run_id=run_id, now=now, thread_id=canonical_thread_id),
        )
        return {
            "thread": existing_thread,
            "message": existing_recommendation,
            "records": [],
            "action": "skip",
        }
    existing_edition_thread = next(
        (thread for thread in existing_threads if str(thread.get("id") or "") == canonical_thread_id),
        None,
    )
    thread = edition_forum_thread_record(
        edition_id=edition_id,
        run_id=run_id,
        now=now,
        thread_id=canonical_thread_id,
        existing=existing_edition_thread,
        message_count=int((existing_edition_thread or {}).get("messageCount") or 0),
        last_message_id=str((existing_edition_thread or {}).get("lastMessageId") or ""),
    )
    sequence_number = _next_forum_sequence(existing_messages_by_thread.get(canonical_thread_id, []))
    content = _rotating_desk_recommendation_body(topic=topic, selection=selection)
    desk_label = selection.get("recommendedSectionTitle") or selection.get("recommendedSectionKey")
    message = forum_kickoff_message_record(
        thread=thread,
        role="editor",
        author_label="papyrus-editor",
        summary=f"Optional desk: {desk_label}",
        content=content,
        now=now,
        sequence_number=sequence_number,
        message_metadata={"planningPhase": "rotating_desk_selection"},
    )
    thread["messageCount"] = max(int(thread.get("messageCount") or 0), sequence_number)
    thread["lastMessageId"] = message["id"]
    thread["lastMessageAt"] = now
    return {
        "thread": thread,
        "message": message,
        "records": [
            _record("MessageThread", thread),
            _record("Message", message),
            _record("SemanticRelation", semantic_relation(
                predicate="planned_for_edition",
                subject_kind="message",
                subject_id=message["id"],
                object_kind="edition",
                object_id=edition_id,
                object_lineage_id=edition.get("lineageId") or edition_id,
                object_version_number=edition.get("versionNumber") or 1,
                import_run_id=run_id,
                now=now,
                metadata={
                    "runId": run_id,
                    "threadId": thread["id"],
                    "forumScope": "edition",
                    "planningPhase": "rotating_desk_selection",
                },
            )),
        ],
    }


def _rotating_desk_recommendation_body(*, topic: str, selection: dict[str, Any]) -> str:
    avoided = selection.get("avoidedSections") or []
    recent = selection.get("recentUsage") or []
    desk_title = selection.get("recommendedSectionTitle") or selection.get("recommendedSectionKey")
    desk_key = selection.get("recommendedSectionKey") or ""
    summary_line = str(
        selection.get("recommendationSummary") or selection.get("rationale") or ""
    ).strip()
    lines = [
        f"# Optional desk: {desk_title}",
        "",
        f"Edition spine: **{topic}**",
        f"Suggested optional desk: **{desk_title}** (`{desk_key}`)",
    ]
    if summary_line:
        lines.extend(["", summary_line])
    if recent:
        lines.extend(["", "## Recent optional desks", *[
            f"- {entry.get('editionDate') or 'unknown'}: {entry.get('sectionTitle') or entry.get('sectionKey')}"
            for entry in recent[:8]
        ]])
    if avoided and recent:
        lines.extend(["", "## Deprioritize", *[f"- {key}" for key in avoided]])
    return "\n".join(lines).strip() + "\n"


def run_rotating_desk_planning_step(
    *,
    plan: dict[str, Any],
    topic: str,
    corpus_key: str,
    coverage_key: str,
    sections: list[str],
    section_budgets: dict[str, int],
    run_id: str,
    research_mode: str,
    now: str,
    state: dict[str, list[dict[str, Any]]],
    client: Any | None,
    allow_fallback: bool,
    selected_optional_desk_key: str = "",
    steering_notes: str = "",
) -> dict[str, Any]:
    provisional = list(plan.get("provisionalOptionalDesks") or [])
    if not provisional and not selected_optional_desk_key:
        return {"ok": True, "skipped": True, "records": [], "selection": None}
    edition = plan["edition"]
    if selected_optional_desk_key:
        selection = {
            "recommendedSectionKey": selected_optional_desk_key,
            "recommendedSectionTitle": selected_optional_desk_key,
            "recommendationSummary": f"Human override selected optional desk {selected_optional_desk_key}.",
            "avoidedSections": [],
            "recentUsage": [],
            "rationale": "Provided via --selected-optional-desk.",
            "degraded": False,
        }
        selection_run = {"ok": True, "selection": selection, "degraded": False}
    else:
        context = build_rotating_section_selection_context(
            edition=edition,
            topic=topic,
            coverage_key=coverage_key,
            existing_editions=state.get("editions") or [],
            candidate_section_keys=[entry.get("key") for entry in provisional if entry.get("key")],
        )
        selection_run = run_or_fallback_rotating_section_selection(
            client=client,
            run_id=run_id,
            context=context,
            allow_fallback=allow_fallback,
            steering_notes=steering_notes,
            provisional_section_keys=[entry.get("key") for entry in provisional if entry.get("key")],
        )
    selection = selection_run["selection"]
    section_key = str(selection.get("recommendedSectionKey") or "").strip()
    if not section_key:
        return {"ok": False, "error": {"code": "rotating_desk_empty", "message": "Rotating desk selection returned no section key."}}

    existing_messages = state.get("messages") or []
    existing_messages_by_thread: dict[str, list[dict[str, Any]]] = {}
    for message in existing_messages:
        thread_id = str(message.get("threadId") or "").strip()
        if thread_id:
            existing_messages_by_thread.setdefault(thread_id, []).append(message)

    forum_records = build_rotating_desk_forum_records(
        edition=edition,
        selection=selection,
        topic=topic,
        run_id=run_id,
        now=now,
        existing_threads=state.get("messageThreads") or [],
        existing_messages_by_thread=existing_messages_by_thread,
    )
    slots = max(1, int(section_budgets.get(section_key, DEFAULT_SECTION_BUDGETS.get(section_key, 1))))
    dispatch_exists = optional_desk_dispatch_exists(
        state,
        run_id=run_id,
        section_key=section_key,
        edition_id=str(edition.get("id") or ""),
        section_budgets=section_budgets,
    )
    metadata_record = build_edition_metadata_update_record(
        edition,
        {
            "selectedOptionalDeskKey": section_key,
            "rotatingDeskStatus": "selected",
            "optionalDeskRecommendation": selection,
            "planningPhase": "rotating_desk_selected",
        },
    )
    research_assignments, reporting_assignments = optional_desk_assignments_from_state(
        state,
        run_id=run_id,
        section_key=section_key,
    )
    if forum_records.get("action") == "skip" and forum_records.get("records") == [] and dispatch_exists:
        return {
            "ok": True,
            "skipped": True,
            "dispatchReused": True,
            "selection": selection,
            "records": [metadata_record],
            "researchAssignments": research_assignments,
            "reportingAssignments": reporting_assignments,
            "editionSlots": [
                slot
                for slot in (state.get("editionSlots") or [])
                if str(slot.get("sectionKey") or "") == section_key
                and str(slot.get("editionId") or "") == str(edition.get("id") or "")
            ],
            "selectedOptionalDeskKey": section_key,
        }
    optional_section = next(
        (
            section
            for section in resolve_sections(sections, state.get("newsroomSections") or [])
            if str(section.get("id") or "") == section_key
        ),
        None,
    )
    if not optional_section:
        return {"ok": False, "error": {"code": "rotating_desk_unknown", "message": f"Unknown optional desk section: {section_key}"}}

    category_key = str(plan.get("categoryKey") or "")
    category = find_category(category_key, state.get("categories") or [])
    category_set = find_category_set(category, state.get("categorySets") or [])
    reporting_lane = lane_node_record("editorial.form.reporting", "Reporting", "reported story", now)
    if dispatch_exists:
        edition_slots = [
            slot
            for slot in (state.get("editionSlots") or [])
            if str(slot.get("sectionKey") or "") == section_key
            and str(slot.get("editionId") or "") == str(edition.get("id") or "")
        ]
        dispatch_records: list[dict[str, Any]] = []
    else:
        dispatch_bundle = _build_sections_dispatch_bundle(
            dispatch_sections=[optional_section],
            edition=edition,
            section_budgets=section_budgets,
            run_id=run_id,
            date=str(plan.get("date") or edition.get("editionDate") or ""),
            topic=topic,
            corpus_key=corpus_key,
            category_key=category_key,
            category=category,
            category_set=category_set,
            coverage_node=plan["coverageNode"],
            reporting_lane=reporting_lane,
            research_mode=research_mode,
            signal=None,
            now=now,
            priority_offset=max(len(plan.get("dispatchSections") or []), 1) * 100,
        )
        research_assignments = dispatch_bundle["researchAssignments"]
        reporting_assignments = dispatch_bundle["reportingAssignments"]
        edition_slots = dispatch_bundle["editionSlots"]
        dispatch_records = list(dispatch_bundle["records"])
    records = [
        *forum_records["records"],
        *dispatch_records,
        metadata_record,
    ]
    return {
        "ok": True,
        "skipped": dispatch_exists and forum_records.get("action") == "skip",
        "degraded": bool(selection_run.get("degraded")),
        "selection": selection,
        "records": _dedupe_records(records),
        "researchAssignments": research_assignments,
        "reportingAssignments": reporting_assignments,
        "editionSlots": edition_slots,
        "forum": forum_records,
        "selectedOptionalDeskKey": section_key,
        "dispatchReused": dispatch_exists,
    }


def _next_forum_sequence(messages: list[dict[str, Any]]) -> int:
    max_sequence = 0
    for message in messages:
        try:
            max_sequence = max(max_sequence, int(message.get("sequenceNumber") or 0))
        except (TypeError, ValueError):
            continue
    return max_sequence + 1


def _active_forum_thread_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        message
        for message in messages
        if str(message.get("status") or "active") == "active"
        and str(message.get("messageKind") or "") == "forum_post"
    ]


def _forum_kickoff_content_hash(content: str) -> str:
    return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()


def _canonical_edition_forum_thread_id(edition_id: str) -> str:
    return f"message-thread-edition-forum-{_safe_id(edition_id)}"


def _canonical_edition_forum_thread_messages(
    *,
    edition_id: str,
    state: dict[str, list[dict[str, Any]]],
    pending_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    thread_id = _canonical_edition_forum_thread_id(edition_id)
    messages = [
        message
        for message in (state.get("messages") or [])
        if str(message.get("threadId") or "") == thread_id
    ]
    seen_ids = {str(message.get("id") or "") for message in messages}
    for record in pending_records or []:
        if record.get("modelName") != "Message":
            continue
        message = record.get("input") or {}
        if str(message.get("threadId") or "") != thread_id:
            continue
        message_id = str(message.get("id") or "")
        if message_id and message_id in seen_ids:
            continue
        messages.append(message)
        if message_id:
            seen_ids.add(message_id)
    return sorted(messages, key=lambda row: int(row.get("sequenceNumber") or 0))


def _merge_forum_messages_from_records_into_state(
    state: dict[str, list[dict[str, Any]]],
    records: list[dict[str, Any]],
) -> None:
    bucket = state.setdefault("messages", [])
    seen_ids = {str(message.get("id") or "") for message in bucket}
    for record in records:
        if record.get("modelName") != "Message":
            continue
        message = record.get("input") or {}
        message_id = str(message.get("id") or "")
        if message_id and message_id in seen_ids:
            continue
        bucket.append(message)
        if message_id:
            seen_ids.add(message_id)


def _existing_optional_desk_recommendation(
    messages: list[dict[str, Any]],
    *,
    section_title: str,
    run_id: str,
) -> dict[str, Any] | None:
    markers = (
        f"optional desk (phase 2): {section_title}".lower(),
        f"optional desk suggestion: {section_title}".lower(),
        f"optional desk: {section_title}".lower(),
    )
    for message in _active_forum_thread_messages(messages):
        if _message_planning_phase(message) == "rotating_desk_selection":
            return message
        summary = str(message.get("summary") or "").lower()
        if summary.startswith("optional desk:"):
            return message
        if any(marker in summary for marker in markers) or (
            str(message.get("importRunId") or "") == run_id
            and ("optional desk (phase 2)" in summary or "optional desk suggestion" in summary or summary.startswith("optional desk:"))
        ):
            return message
    return None


def _forum_kickoff_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary_markers = (
        "kickoff",
        "planning suggestions",
        "edition theme (phase 1)",
        "re-plan update",
        "optional desk (phase 2)",
        "optional desk suggestion",
        "reporting dispatch (phase 3)",
        "reporting candidates:",
        "optional desk:",
    )
    result: list[dict[str, Any]] = []
    for message in _active_forum_thread_messages(messages):
        summary = str(message.get("summary") or "").lower()
        if any(marker in summary for marker in summary_markers):
            result.append(message)
            continue
        phase = _message_planning_phase(message)
        if phase in {"edition_theme_kickoff", "theme_proposal"}:
            result.append(message)
            continue
        content = str(message.get("content") or "")
        if content.startswith("# ") and "## Why this edition" in content:
            result.append(message)
    return result


def _resolve_forum_kickoff_action(
    *,
    existing_messages: list[dict[str, Any]],
    summary: str,
    content: str,
    run_id: str,
) -> tuple[str, dict[str, Any] | None]:
    kickoff_messages = _forum_kickoff_messages(existing_messages)
    if not kickoff_messages:
        return "initial", None
    content_hash = _forum_kickoff_content_hash(content)
    for message in kickoff_messages:
        if str(message.get("importRunId") or "") == run_id:
            return "skip", message
        if _forum_kickoff_content_hash(str(message.get("content") or "")) == content_hash:
            return "skip", message
        if str(message.get("summary") or "") == summary:
            return "skip", message
    return "replan", kickoff_messages[-1]


def _replan_forum_thread_id(canonical_thread_id: str, run_id: str) -> str:
    suffix = f"run-{_safe_id(run_id)}"
    candidate = f"{canonical_thread_id}-{suffix}"
    if len(candidate) <= 120:
        return candidate
    return f"{canonical_thread_id}-{_hash_short([run_id])}"


def _wrap_replan_forum_body(*, heading: str, prior_summary: str, run_id: str, body: str) -> str:
    _ = run_id
    prior = str(prior_summary or "").strip()
    lines = [f"# {heading}", ""]
    if prior:
        lines.append(f"Updated edition spine (previous thread title: {prior}).")
        lines.append("")
    lines.append(body.strip())
    return "\n".join(lines).strip() + "\n"


def _plan_forum_kickoff_scope(
    *,
    canonical_thread_id: str,
    summary: str,
    content: str,
    run_id: str,
    now: str,
    replan_heading: str,
    existing_threads: list[dict[str, Any]],
    existing_messages_by_thread: dict[str, list[dict[str, Any]]],
    build_thread: Any,
    refresh_existing: bool = False,
    message_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    thread_messages = [] if refresh_existing else existing_messages_by_thread.get(canonical_thread_id, [])
    action, prior_message = _resolve_forum_kickoff_action(
        existing_messages=thread_messages,
        summary=summary,
        content=content,
        run_id=run_id,
    )
    if action == "skip":
        existing_thread = next(
            (thread for thread in existing_threads if str(thread.get("id") or "") == canonical_thread_id),
            build_thread(canonical_thread_id, 0),
        )
        assert prior_message is not None
        return {
            "action": "skip",
            "thread": existing_thread,
            "message": prior_message,
            "records": [],
        }

    if action == "replan":
        thread_id = _replan_forum_thread_id(canonical_thread_id, run_id)
        message_content = _wrap_replan_forum_body(
            heading=replan_heading,
            prior_summary=str((prior_message or {}).get("summary") or "earlier kickoff"),
            run_id=run_id,
            body=content,
        )
        sequence_number = 1
    else:
        thread_id = canonical_thread_id
        message_content = content
        sequence_number = _next_forum_sequence(thread_messages)

    thread = build_thread(thread_id, sequence_number)
    if action == "replan":
        thread_metadata = dict(thread.get("metadata") or {})
        thread_metadata.update({
            "parentThreadId": canonical_thread_id,
            "kickoffKind": "replan",
            "replanRunId": run_id,
        })
        thread["metadata"] = thread_metadata
    message = forum_kickoff_message_record(
        thread=thread,
        role="editor",
        author_label="papyrus-editor",
        summary=summary,
        content=message_content,
        now=now,
        sequence_number=sequence_number,
        message_metadata=message_metadata,
    )
    thread["messageCount"] = max(int(thread.get("messageCount") or 0), sequence_number)
    thread["lastMessageId"] = message["id"]
    thread["lastMessageAt"] = now
    return {
        "action": action,
        "thread": thread,
        "message": message,
        "records": [
            _record("MessageThread", thread),
            _record("Message", message),
        ],
    }


def build_research_packet_records(
    *,
    assignment: dict[str, Any],
    topic: str,
    corpus_key: str,
    coverage_key: str,
    research_mode: str,
    now: str,
    degraded: bool,
    refresh_packets: bool,
) -> dict[str, Any]:
    metadata = _metadata(assignment)
    message_id = story_cycle_packet_message_id(assignment, "research_packet")
    packet = {
        "summary": f"Research packet for {topic} through the {metadata.get('sectionTitle') or assignment.get('sectionKey')} lens.",
        "corpus_key": corpus_key,
        "research_mode": research_mode,
        "section_key": assignment.get("sectionKey"),
        "coverage_key": coverage_key,
        "coverage_node_id": metadata.get("coverageConceptId"),
        "section_lens": metadata.get("researchLens"),
        "evidence_item_ids": [],
        "source_snapshots": [],
        "proposed_references": [],
        "open_questions": [
            f"What accepted references best establish the current state of {topic}?",
            "Which fresh source prospects need intake before copywriting?",
        ],
        "coverage_gaps": ["No accepted evidence was attached by the deterministic planner."],
        "recommended_angle": metadata.get("researchLens") or f"Use the {assignment.get('sectionKey')} section lens.",
        "degraded": degraded,
        "fallbackReason": "deterministic_python_planner" if degraded else None,
    }
    message = packet_message(message_id, "research_packet", packet["summary"], "papyrus coverage-themes run", assignment, now)
    records = [
        _record("Message", message),
        _attachment_record(message_id, "message_body", "message", "message.txt", "text/plain", _research_packet_body(packet), assignment.get("importRunId"), now),
        _attachment_record(message_id, "metadata", "metadata", "metadata.json", "application/json", {"kind": "research.packet.created", "assignmentId": assignment["id"], "research": packet}, assignment.get("importRunId"), now),
        _record("SemanticRelation", semantic_relation(
            predicate="produces",
            subject_kind="assignment",
            subject_id=assignment["id"],
            object_kind="message",
            object_id=message_id,
            object_lineage_id=message_id,
            rank=1,
            classifier_id=assignment.get("classifierId"),
            import_run_id=assignment.get("importRunId"),
            now=now,
            metadata={"workProductKind": "research_packet", "messageKind": "research_packet", "refreshPackets": refresh_packets},
        )),
    ]
    return {
        "degraded": degraded,
        "records": records,
        "run": {
            "ok": not degraded,
            "phase": "research",
            "assignmentId": assignment["id"],
            "sectionKey": assignment.get("sectionKey"),
            "messageId": message_id,
            "packet": packet,
            "degraded": degraded,
            "fallbackReason": "deterministic_python_planner" if degraded else None,
            "fallbackKind": "research_packet" if degraded else None,
        },
    }


def build_research_packet_records_from_packet(
    *,
    assignment: dict[str, Any],
    packet: dict[str, Any],
    cloud_run: dict[str, Any],
    now: str,
    refresh_packets: bool,
) -> dict[str, Any]:
    message_id = story_cycle_packet_message_id(assignment, "research_packet")
    message = packet_message(message_id, "research_packet", packet["summary"], "papyrus coverage-themes run", assignment, now)
    records = [
        _record("Message", message),
        _attachment_record(message_id, "message_body", "message", "message.txt", "text/plain", _research_packet_body(packet), assignment.get("importRunId"), now),
        _attachment_record(message_id, "metadata", "metadata", "metadata.json", "application/json", {
            "kind": "research.packet.created",
            "assignmentId": assignment["id"],
            "research": packet,
            "cloudProcedure": cloud_run_metadata(cloud_run),
        }, assignment.get("importRunId"), now),
        _record("SemanticRelation", semantic_relation(
            predicate="produces",
            subject_kind="assignment",
            subject_id=assignment["id"],
            object_kind="message",
            object_id=message_id,
            object_lineage_id=message_id,
            rank=1,
            classifier_id=assignment.get("classifierId"),
            import_run_id=assignment.get("importRunId"),
            now=now,
            metadata={
                "workProductKind": "research_packet",
                "messageKind": "research_packet",
                "refreshPackets": refresh_packets,
                "procedureRunId": cloud_run.get("id"),
                "procedureKey": cloud_run.get("procedureKey"),
                "procedureVersionId": cloud_run.get("procedureVersionId"),
            },
        )),
    ]
    return {
        "degraded": False,
        "records": records,
        "run": {
            "ok": True,
            "phase": "research",
            "assignmentId": assignment["id"],
            "sectionKey": assignment.get("sectionKey"),
            "messageId": message_id,
            "packet": packet,
            "degraded": False,
            "cloudProcedure": cloud_run_metadata(cloud_run),
        },
    }


def build_reporting_packet_records(
    *,
    assignment: dict[str, Any],
    topic: str,
    corpus_key: str,
    coverage_key: str,
    source_research_assignment: dict[str, Any] | None,
    source_research_packet_id: str | None,
    now: str,
    degraded: bool,
    refresh_packets: bool,
) -> dict[str, Any]:
    metadata = _metadata(assignment)
    angle = (metadata.get("angleDiversity") or {}).get("lensLabel") or "reader impact"
    message_id = story_cycle_packet_message_id(assignment, "reporting_context_packet")
    packet = {
        "summary": f"Reporting context packet for {topic} / {assignment.get('sectionKey')} / {angle}.",
        "section_key": assignment.get("sectionKey"),
        "edition_id": metadata.get("editionId"),
        "coverage_key": coverage_key,
        "candidate_rank": (metadata.get("slotTarget") or {}).get("candidateRank"),
        "slot_target": metadata.get("slotTarget"),
        "why_now": f"The assignment desk identified {topic} as a Coverage Theme candidate for this edition.",
        "nut_graf_candidate": f"A reported item could explain what {topic} changes for readers through the {assignment.get('sectionKey')} lens.",
        "recommended_angle": angle,
        "confirmed_facts": [],
        "source_trail": [],
        "accepted_reference_ids": [],
        "proposed_references": [],
        "recent_desk_memory_used": [],
        "coverage_gaps": ["Accepted evidence and fresh source intake still need reporter verification."],
        "open_questions": [
            "Which accepted references should anchor the story?",
            "Which fresh source prospects should be registered before copywriting?",
        ],
        "risk_flags": ["degraded_packet" if degraded else "needs_evidence_review"],
        "verification_needs": ["Verify all facts against accepted References before copywriting."],
        "source_diversity_notes": "No source diversity assessment is available until research evidence is attached.",
        "copywriter_brief": f"Do not write final copy from this packet alone. Use it after editor selection with accepted evidence for {topic}.",
        "editor_recommendation": "hold" if degraded else "brief",
        "source_research_assignment_id": source_research_assignment.get("id") if source_research_assignment else metadata.get("sourceResearchAssignmentId"),
        "source_research_packet_id": source_research_packet_id,
        "degraded": degraded,
        "fallbackReason": "deterministic_python_planner" if degraded else None,
    }
    message = packet_message(message_id, "reporting_context_packet", packet["summary"], "papyrus coverage-themes run", assignment, now)
    records = [
        _record("Message", message),
        _attachment_record(message_id, "message_body", "message", "message.txt", "text/plain", _reporting_packet_body(packet), assignment.get("importRunId"), now),
        _attachment_record(message_id, "metadata", "metadata", "metadata.json", "application/json", {"kind": "reporting.context_packet.created", "assignmentId": assignment["id"], "reporting": packet}, assignment.get("importRunId"), now),
        _record("SemanticRelation", semantic_relation(
            predicate="produces",
            subject_kind="assignment",
            subject_id=assignment["id"],
            object_kind="message",
            object_id=message_id,
            object_lineage_id=message_id,
            rank=1,
            classifier_id=assignment.get("classifierId"),
            import_run_id=assignment.get("importRunId"),
            now=now,
            metadata={"workProductKind": "reporting_context_packet", "messageKind": "reporting_context_packet", "editorRecommendation": packet["editor_recommendation"], "refreshPackets": refresh_packets},
        )),
    ]
    if source_research_packet_id:
        records.append(_record("SemanticRelation", semantic_relation(
            predicate="derived_from",
            subject_kind="message",
            subject_id=message_id,
            object_kind="message",
            object_id=source_research_packet_id,
            object_lineage_id=source_research_packet_id,
            rank=1,
            classifier_id=assignment.get("classifierId"),
            import_run_id=assignment.get("importRunId"),
            now=now,
            metadata={"sourceKind": "section_research_packet", "coverageKey": coverage_key},
        )))
    return {
        "degraded": degraded,
        "records": records,
        "run": {
            "ok": not degraded,
            "phase": "reporting",
            "assignmentId": assignment["id"],
            "sectionKey": assignment.get("sectionKey"),
            "messageId": message_id,
            "angle": angle,
            "packet": packet,
            "degraded": degraded,
            "fallbackReason": "deterministic_python_planner" if degraded else None,
            "fallbackKind": "reporting_context_packet" if degraded else None,
        },
    }


def build_reporting_packet_records_from_packet(
    *,
    assignment: dict[str, Any],
    packet: dict[str, Any],
    cloud_run: dict[str, Any],
    source_research_packet_id: str | None,
    now: str,
    refresh_packets: bool,
) -> dict[str, Any]:
    message_id = story_cycle_packet_message_id(assignment, "reporting_context_packet")
    message = packet_message(message_id, "reporting_context_packet", packet["summary"], "papyrus coverage-themes run", assignment, now)
    records = [
        _record("Message", message),
        _attachment_record(message_id, "message_body", "message", "message.txt", "text/plain", _reporting_packet_body(packet), assignment.get("importRunId"), now),
        _attachment_record(message_id, "metadata", "metadata", "metadata.json", "application/json", {
            "kind": "reporting.context_packet.created",
            "assignmentId": assignment["id"],
            "reporting": packet,
            "cloudProcedure": cloud_run_metadata(cloud_run),
        }, assignment.get("importRunId"), now),
        _record("SemanticRelation", semantic_relation(
            predicate="produces",
            subject_kind="assignment",
            subject_id=assignment["id"],
            object_kind="message",
            object_id=message_id,
            object_lineage_id=message_id,
            rank=1,
            classifier_id=assignment.get("classifierId"),
            import_run_id=assignment.get("importRunId"),
            now=now,
            metadata={
                "workProductKind": "reporting_context_packet",
                "messageKind": "reporting_context_packet",
                "editorRecommendation": packet["editor_recommendation"],
                "refreshPackets": refresh_packets,
                "procedureRunId": cloud_run.get("id"),
                "procedureKey": cloud_run.get("procedureKey"),
                "procedureVersionId": cloud_run.get("procedureVersionId"),
            },
        )),
    ]
    if source_research_packet_id:
        records.append(_record("SemanticRelation", semantic_relation(
            predicate="derived_from",
            subject_kind="message",
            subject_id=message_id,
            object_kind="message",
            object_id=source_research_packet_id,
            object_lineage_id=source_research_packet_id,
            rank=1,
            classifier_id=assignment.get("classifierId"),
            import_run_id=assignment.get("importRunId"),
            now=now,
            metadata={"sourceKind": "section_research_packet", "coverageKey": packet.get("coverage_key")},
        )))
    return {
        "degraded": False,
        "records": records,
        "run": {
            "ok": True,
            "phase": "reporting",
            "assignmentId": assignment["id"],
            "sectionKey": assignment.get("sectionKey"),
            "messageId": message_id,
            "angle": packet.get("recommended_angle"),
            "packet": packet,
            "degraded": False,
            "cloudProcedure": cloud_run_metadata(cloud_run),
        },
    }


def cloud_run_metadata(cloud_run: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": cloud_run.get("id"),
        "procedureKey": cloud_run.get("procedureKey"),
        "procedureVersionId": cloud_run.get("procedureVersionId"),
        "procedureVersionNumber": cloud_run.get("procedureVersionNumber"),
        "runStatus": cloud_run.get("runStatus"),
        "sourcePath": cloud_run.get("sourcePath"),
        "stdoutPath": cloud_run.get("stdoutPath"),
        "stderrPath": cloud_run.get("stderrPath"),
    }


def normalize_story_cycle_research_packet(
    packet: dict[str, Any],
    *,
    assignment: dict[str, Any],
    topic: str,
    corpus_key: str,
    coverage_key: str,
    research_mode: str,
) -> dict[str, Any]:
    metadata = _metadata(assignment)
    return {
        **packet,
        "summary": _packet_value(packet, "summary") or f"Research packet for {topic}.",
        "corpus_key": _packet_value(packet, "corpus_key", "corpusKey") or corpus_key,
        "research_mode": _packet_value(packet, "research_mode", "researchMode") or research_mode,
        "section_key": _packet_value(packet, "section_key", "sectionKey") or assignment.get("sectionKey"),
        "coverage_key": _packet_value(packet, "coverage_key", "coverageKey") or coverage_key,
        "coverage_node_id": _packet_value(packet, "coverage_node_id", "coverageNodeId") or metadata.get("coverageConceptId"),
        "section_lens": _packet_value(packet, "section_lens", "sectionLens") or metadata.get("researchLens"),
        "evidence_item_ids": _packet_list(packet, "evidence_item_ids", "evidenceItemIds"),
        "source_snapshots": _packet_list(packet, "source_snapshots", "sourceSnapshots"),
        "proposed_references": _packet_list(packet, "proposed_references", "proposedReferences"),
        "open_questions": _packet_list(packet, "open_questions", "openQuestions"),
        "coverage_gaps": _packet_list(packet, "coverage_gaps", "coverageGaps"),
        "recommended_angle": _packet_value(packet, "recommended_angle", "recommendedAngle") or metadata.get("researchLens") or "",
        "degraded": False,
        "fallbackReason": None,
    }


def normalize_story_cycle_reporting_packet(
    packet: dict[str, Any],
    *,
    assignment: dict[str, Any],
    topic: str,
    coverage_key: str,
    source_research_assignment: dict[str, Any] | None,
    source_research_packet_id: str | None,
) -> dict[str, Any]:
    metadata = _metadata(assignment)
    angle = (metadata.get("angleDiversity") or {}).get("lensLabel") or "reader impact"
    return {
        **packet,
        "summary": _packet_value(packet, "summary") or f"Reporting context packet for {topic}.",
        "section_key": _packet_value(packet, "section_key", "sectionKey") or assignment.get("sectionKey"),
        "edition_id": _packet_value(packet, "edition_id", "editionId") or metadata.get("editionId"),
        "coverage_key": _packet_value(packet, "coverage_key", "coverageKey") or coverage_key,
        "recommended_angle": _packet_value(packet, "recommended_angle", "recommendedAngle") or angle,
        "editor_recommendation": _packet_value(packet, "editor_recommendation", "editorRecommendation") or "hold",
        "risk_flags": _packet_list(packet, "risk_flags", "riskFlags"),
        "coverage_gaps": _packet_list(packet, "coverage_gaps", "coverageGaps"),
        "open_questions": _packet_list(packet, "open_questions", "openQuestions"),
        "accepted_reference_ids": _packet_list(packet, "accepted_reference_ids", "acceptedReferenceIds", "accepted_referenceIds"),
        "proposed_references": _packet_list(packet, "proposed_references", "proposedReferences"),
        "copywriter_brief": _packet_value(packet, "copywriter_brief", "copywriterBrief") or "",
        "source_research_assignment_id": _packet_value(packet, "source_research_assignment_id", "sourceResearchAssignmentId") or (source_research_assignment or {}).get("id"),
        "source_research_packet_id": _packet_value(packet, "source_research_packet_id", "sourceResearchPacketId") or source_research_packet_id,
        "degraded": False,
        "fallbackReason": None,
    }


def _packet_value(packet: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = packet.get(key)
        if value not in (None, ""):
            return value
    return None


def _packet_list(packet: dict[str, Any], *keys: str) -> list[Any]:
    value = _packet_value(packet, *keys)
    return value if isinstance(value, list) else []


def story_budget_output(
    *,
    run_id: str = "",
    edition_id: str = "",
    coverage_key: str = "",
    section: str = "",
    state: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    state = state or load_story_budget_state(run_id=run_id)
    assignments = [_decode_record(record) for record in state.get("assignments", [])]
    relations = [_decode_record(record) for record in state.get("semanticRelations", [])]
    messages = {_decode_record(record).get("id"): _decode_record(record) for record in state.get("messages", [])}
    events = [_decode_record(record) for record in state.get("assignmentEvents", [])]
    items = {_decode_record(record).get("id"): _decode_record(record) for record in state.get("items", [])}
    edition_items = state.get("editionItems", [])
    edition_slots = [_decode_record(record) for record in state.get("editionSlots", [])]
    subject_relations = _relations_by_assignment(relations)
    filtered = []
    for assignment in assignments:
        metadata = {**_assignment_graph_metadata(assignment, subject_relations), **_metadata(assignment)}
        if assignment.get("assignmentTypeKey") not in {"research.edition-candidate", "reporting.edition-candidate", "copywriting.article-draft", "copywriting.brief-draft"}:
            continue
        if run_id and run_id not in {assignment.get("importRunId"), metadata.get("storyCycleRunId"), metadata.get("coverageThemeRunId"), metadata.get("runId")}:
            continue
        if edition_id and edition_id not in {metadata.get("editionId"), metadata.get("editionLineageId")}:
            continue
        if coverage_key and coverage_key != metadata.get("coverageConceptKey"):
            continue
        if section and section != assignment.get("sectionKey") and section != metadata.get("sectionKey"):
            continue
        filtered.append(assignment)
    produces = _relations_by_subject(relations, "produces")
    derived_from = _relations_by_subject(relations, "derived_from")
    events_by_assignment: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        events_by_assignment.setdefault(event.get("assignmentId"), []).append(event)
    sections: dict[str, dict[str, Any]] = {}
    for assignment in sorted(filtered, key=lambda item: (item.get("sectionKey") or "", item.get("priority") or 0, item.get("id") or "")):
        graph_metadata = _assignment_graph_metadata(assignment, subject_relations)
        assignment_metadata = _metadata(assignment)
        metadata = {**assignment_metadata, **graph_metadata}
        assignment_slot_target = assignment_metadata.get("slotTarget") if isinstance(assignment_metadata.get("slotTarget"), dict) else {}
        graph_slot_target = graph_metadata.get("slotTarget") if isinstance(graph_metadata.get("slotTarget"), dict) else {}
        if assignment_slot_target or graph_slot_target:
            metadata["slotTarget"] = {**assignment_slot_target, **graph_slot_target}
        section_key = assignment.get("sectionKey") or metadata.get("sectionKey") or "unsectioned"
        section_entry = sections.setdefault(section_key, {
            "sectionKey": section_key,
            "sectionTitle": metadata.get("sectionTitle") or section_key,
            "editionId": metadata.get("editionId"),
            "editionLabel": metadata.get("editionDate") or metadata.get("editionId"),
            "researchAssignments": [],
            "reportingCandidates": [],
            "copywritingAssignments": [],
            "slots": [],
            "counts": {
                "slots": 0,
                "research": 0,
                "reporting": 0,
                "copywriting": 0,
                "selected": 0,
                "briefed": 0,
                "held": 0,
                "killed": 0,
                "merged": 0,
                "undecided": 0,
                "filledSlots": 0,
                "unresolvedSlots": 0,
                "draftItems": 0,
                "editionItems": 0,
            },
        })
        packet_messages = [messages.get(rel.get("objectId")) for rel in produces.get(assignment["id"], []) if rel.get("objectKind") == "message"]
        packet_messages = [message for message in packet_messages if message]
        latest_decision = latest_reporting_decision(events_by_assignment.get(assignment["id"], []))
        draft_item_ids = [rel.get("objectId") for rel in produces.get(assignment["id"], []) if rel.get("objectKind") == "item"]
        row = {
            "assignmentId": assignment["id"],
            "assignmentTypeKey": assignment.get("assignmentTypeKey"),
            "status": assignment.get("status"),
            "title": assignment.get("title"),
            "sectionKey": section_key,
            "coverageKey": metadata.get("coverageConceptKey"),
            "packetMessageIds": [message.get("id") for message in packet_messages],
            "latestDecision": latest_decision,
            "draftItemIds": draft_item_ids,
            "draftItems": [items.get(item_id) for item_id in draft_item_ids if items.get(item_id)],
            "lineage": derived_from.get(assignment["id"], []),
            "metadata": {
                "slotTarget": metadata.get("slotTarget"),
                "angleDiversity": metadata.get("angleDiversity"),
                "expectedOutput": metadata.get("expectedOutput"),
            },
        }
        if assignment.get("assignmentTypeKey") == "research.edition-candidate":
            section_entry["researchAssignments"].append(row)
            section_entry["counts"]["research"] += 1
        elif assignment.get("assignmentTypeKey") == "reporting.edition-candidate":
            packet = _packet_summary(packet_messages, state.get("modelAttachments", []), "reporting")
            row.update(packet)
            section_entry["reportingCandidates"].append(row)
            section_entry["counts"]["reporting"] += 1
            decision = latest_decision.get("decision") if latest_decision else None
            if decision == "select":
                section_entry["counts"]["selected"] += 1
            elif decision == "brief":
                section_entry["counts"]["briefed"] += 1
            elif decision == "hold":
                section_entry["counts"]["held"] += 1
            elif decision == "kill":
                section_entry["counts"]["killed"] += 1
            elif decision == "merge":
                section_entry["counts"]["merged"] += 1
            else:
                section_entry["counts"]["undecided"] += 1
        else:
            section_entry["copywritingAssignments"].append(row)
            section_entry["counts"]["copywriting"] += 1
            section_entry["counts"]["draftItems"] += len(draft_item_ids)
    placed_item_ids = {record.get("itemId") or record.get("publishedItemId") or record.get("sourceItemId") for record in edition_items}
    for section_entry in sections.values():
        section_entry["counts"]["editionItems"] = sum(
            1
            for assignment in section_entry["copywritingAssignments"]
            for item_id in assignment.get("draftItemIds") or []
            if item_id in placed_item_ids
        )
        reporting_by_slot: dict[str, list[dict[str, Any]]] = {}
        synthetic_slot_by_id: dict[str, dict[str, Any]] = {}
        for candidate in section_entry["reportingCandidates"]:
            slot_target = ((candidate.get("metadata") or {}).get("slotTarget") or {}) if isinstance(candidate.get("metadata"), dict) else {}
            slot_id = slot_target.get("slotId")
            if not slot_id:
                rank = slot_target.get("slotRank")
                slot_id = f"synthetic-slot-{section_entry['sectionKey']}-{rank or '00'}"
                synthetic_slot_by_id.setdefault(
                    slot_id,
                    {
                        "id": slot_id,
                        "editionId": section_entry.get("editionId"),
                        "sectionKey": section_entry["sectionKey"],
                        "slotRank": rank or 0,
                        "targetType": "article",
                        "targetLengthBand": "standard",
                        "minImageAssets": None,
                        "status": "assigned",
                        "selectedAssignmentId": None,
                        "metadata": {"synthetic": True},
                    },
                )
            reporting_by_slot.setdefault(slot_id, []).append(candidate)

        section_slot_records = [
            slot for slot in edition_slots
            if slot.get("sectionKey") == section_entry["sectionKey"]
            and (not section_entry.get("editionId") or slot.get("editionId") == section_entry.get("editionId"))
        ]
        if not section_slot_records:
            section_slot_records = list(synthetic_slot_by_id.values())
        section_slot_records.sort(key=lambda slot: (int(slot.get("slotRank") or 0), str(slot.get("id") or "")))

        slot_rows: list[dict[str, Any]] = []
        filled_slots = 0
        for slot in section_slot_records:
            slot_id = slot.get("id")
            candidates = sorted(
                reporting_by_slot.get(slot_id, []),
                key=lambda row: (
                    int((((row.get("metadata") or {}).get("slotTarget") or {}).get("candidateRank") or 0)),
                    str(row.get("assignmentId") or ""),
                ),
            )
            status = str(slot.get("status") or "open")
            selected_assignment_id = slot.get("selectedAssignmentId")
            if not selected_assignment_id:
                for candidate in candidates:
                    decision = ((candidate.get("latestDecision") or {}).get("decision") or "").lower()
                    if decision in {"select", "brief"}:
                        selected_assignment_id = candidate.get("assignmentId")
                        break
            if selected_assignment_id and status in {"open", "assigned"}:
                status = "selected"
            filled = status in {"selected", "briefed", "filled"}
            if filled:
                filled_slots += 1
            slot_rows.append(
                {
                    "slotId": slot_id,
                    "slotRank": slot.get("slotRank"),
                    "targetType": slot.get("targetType"),
                    "targetLengthBand": slot.get("targetLengthBand"),
                    "minImageAssets": slot.get("minImageAssets"),
                    "status": status,
                    "selectedAssignmentId": selected_assignment_id,
                    "candidateCount": len(candidates),
                    "candidates": candidates,
                }
            )
        section_entry["slots"] = slot_rows
        section_entry["counts"]["slots"] = len(slot_rows)
        section_entry["counts"]["filledSlots"] = filled_slots
        section_entry["counts"]["unresolvedSlots"] = max(len(slot_rows) - filled_slots, 0)
    all_slots = [slot for section_entry in sections.values() for slot in section_entry.get("slots", [])]
    return {
        "ok": True,
        "command": "story-budget output",
        "runId": run_id or None,
        "editionId": edition_id or None,
        "coverageKey": coverage_key or None,
        "sections": list(sections.values()),
        "slots": all_slots,
        "summary": {
            "sectionCount": len(sections),
            "slotCount": len(all_slots),
            "assignmentCount": len(filtered),
            "createsItemOrEditionItem": False,
        },
    }


def assignment_records(
    assignment: dict[str, Any],
    edition: dict[str, Any],
    coverage_node: dict[str, Any],
    section: dict[str, Any],
    category: dict[str, Any] | None,
    category_set: dict[str, Any] | None,
    now: str,
    *,
    signal: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    records = [
        _record("Assignment", assignment),
        _record("AssignmentEvent", assignment_event_record(assignment, now)),
        _record("SemanticRelation", semantic_relation(
            predicate="planned_for_edition",
            subject_kind="assignment",
            subject_id=assignment["id"],
            object_kind="edition",
            object_id=edition["id"],
            object_lineage_id=edition["lineageId"],
            object_version_number=edition["versionNumber"],
            rank=1,
            classifier_id=assignment.get("classifierId"),
            import_run_id=assignment.get("importRunId"),
            now=now,
            metadata={"editionDate": edition["editionDate"], "editionSlug": edition["slug"], "assignmentTypeKey": assignment["assignmentTypeKey"]},
        )),
        _record("SemanticRelation", semantic_relation(
            predicate="targets_section",
            subject_kind="assignment",
            subject_id=assignment["id"],
            object_kind="newsroomSection",
            object_id=section["id"],
            object_lineage_id=section["id"],
            rank=1,
            classifier_id=assignment.get("classifierId"),
            import_run_id=assignment.get("importRunId"),
            now=now,
            metadata={"sectionKey": section["id"], "sectionTitle": section["title"], "runId": _metadata(assignment).get("coverageThemeRunId")},
        )),
        _record("SemanticRelation", semantic_relation(
            predicate="requests_work_on",
            subject_kind="assignment",
            subject_id=assignment["id"],
            object_kind="semanticNode",
            object_id=coverage_node["id"],
            object_lineage_id=coverage_node["lineageId"],
            object_version_number=coverage_node["versionNumber"],
            rank=1,
            classifier_id=assignment.get("classifierId"),
            import_run_id=assignment.get("importRunId"),
            now=now,
            metadata={"coverageConceptKey": coverage_node["nodeKey"], "coverageConceptTitle": coverage_node["displayName"]},
        )),
    ]
    if category:
        records.append(_record("SemanticRelation", semantic_relation(
            predicate="targets_topic",
            subject_kind="assignment",
            subject_id=assignment["id"],
            object_kind="category",
            object_id=category["id"],
            object_lineage_id=category.get("lineageId") or category["id"],
            object_version_number=category.get("versionNumber"),
            rank=1,
            classifier_id=assignment.get("classifierId"),
            import_run_id=assignment.get("importRunId"),
            now=now,
            metadata={"categoryKey": category.get("categoryKey"), "sectionKey": section["id"]},
        )))
    if signal:
        for rank, reference_id in enumerate(signal.get("sourceReferenceIds") or [], start=1):
            records.append(_record("SemanticRelation", semantic_relation(
                predicate="uses_evidence",
                subject_kind="assignment",
                subject_id=assignment["id"],
                object_kind="reference",
                object_id=reference_id,
                object_lineage_id=reference_id,
                rank=rank,
                classifier_id=assignment.get("classifierId"),
                import_run_id=assignment.get("importRunId"),
                now=now,
                metadata={"signalId": signal.get("signalId"), "coverageKey": signal.get("coverageKey")},
            )))
    slot_target = (_metadata(assignment) or {}).get("slotTarget") or {}
    slot_id = slot_target.get("slotId")
    slot_lineage_id = slot_target.get("slotLineageId") or slot_id
    if slot_id:
        records.append(_record("SemanticRelation", semantic_relation(
            predicate="targets_slot",
            subject_kind="assignment",
            subject_id=assignment["id"],
            object_kind="editionSlot",
            object_id=slot_id,
            object_lineage_id=slot_lineage_id,
            rank=1,
            classifier_id=assignment.get("classifierId"),
            import_run_id=assignment.get("importRunId"),
            now=now,
            metadata={
                "slotId": slot_id,
                "slotRank": slot_target.get("slotRank"),
                "sectionKey": slot_target.get("sectionKey"),
                "candidateRank": slot_target.get("candidateRank"),
                "dispatchCount": slot_target.get("dispatchCount"),
            },
        )))
    return records


def build_edition_slots(
    *,
    edition: dict[str, Any],
    resolved_sections: list[dict[str, Any]],
    section_budgets: dict[str, int],
    run_id: str,
    now: str,
) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for section in resolved_sections:
        section_key = section["id"]
        slot_count = max(1, int(section_budgets.get(section_key, DEFAULT_SECTION_BUDGETS.get(section_key, 1))))
        for rank in range(1, slot_count + 1):
            slot_lineage_id = f"edition-slot-{_safe_id(edition['id'])}-{_safe_id(section_key)}-{rank:02d}"
            slots.append(
                {
                    "id": f"{slot_lineage_id}-v1",
                    "editionId": edition["id"],
                    "sectionKey": section_key,
                    "slotRank": rank,
                    "targetType": "article",
                    "targetLengthBand": "standard",
                    "minImageAssets": 1,
                    "status": "assigned",
                    "selectedAssignmentId": None,
                    "metadata": {
                        "slotLineageId": slot_lineage_id,
                        "editionLineageId": edition.get("lineageId"),
                        "sectionTitle": section.get("title"),
                        "runId": run_id,
                    },
                    "createdAt": now,
                    "updatedAt": now,
                }
            )
    return slots


def edition_record(*, date: str, section_budgets: dict[str, int], run_id: str, now: str) -> dict[str, Any]:
    slug = f"edition-{date}"
    lineage_id = f"edition-{_safe_id(slug)}"
    metadata = {
        "planningKind": "edition-intelligence-coverage-theme-planning",
        "planningPhase": "theme_proposal",
        "rotatingDeskStatus": "pending_selection",
        "coverageThemeRunId": run_id,
        "generatedAt": now,
        "sectionBudgets": [{"sectionKey": key, "slots": value} for key, value in sorted(section_budgets.items())],
        "steeringWindowHours": DEFAULT_STEERING_WINDOW_HOURS,
        "publicReaderVisible": False,
        "createdBy": "papyrus editions plan",
    }
    record = {
        "id": f"{lineage_id}-v1",
        "lineageId": lineage_id,
        "versionNumber": 1,
        "previousVersionId": None,
        "versionState": "current",
        "versionCreatedAt": now,
        "versionCreatedBy": "papyrus",
        "changeReason": "edition-intelligence-planning",
        "slug": slug,
        "title": f"Edition Planning: {date}",
        "status": "planning",
        "editionDate": date,
        "publishedAt": None,
        "description": "Private Newsroom planning edition for signal-driven Coverage Theme assignment dispatch.",
        "layoutPlan": None,
        "metadata": metadata,
    }
    record["contentHash"] = _hash_stable({"slug": slug, "editionDate": date, "metadata": metadata})
    return record


def coverage_node_record(
    *,
    coverage_key: str,
    topic: str,
    corpus_key: str,
    category: dict[str, Any] | None,
    category_set: dict[str, Any] | None,
    now: str,
    change_reason: str = "coverage-theme-coverage-concept",
) -> dict[str, Any]:
    lineage_id = f"semantic-node-{_safe_id(coverage_key)}"
    record = {
        "id": f"{lineage_id}-v1",
        "lineageId": lineage_id,
        "versionNumber": 1,
        "previousVersionId": None,
        "versionState": "current",
        "versionCreatedAt": now,
        "versionCreatedBy": "papyrus",
        "changeReason": change_reason,
        "nodeKey": coverage_key,
        "nodeKind": "coverageQuestion",
        "corpusId": (category_set or {}).get("corpusId") or f"knowledge-corpus-{_safe_id(corpus_key)}",
        "categorySetId": (category_set or {}).get("id"),
        "categoryLineageId": (category or {}).get("lineageId"),
        "categoryKey": (category or {}).get("categoryKey"),
        "displayName": topic,
        "description": f"Coverage concept for edition intelligence, research, and reporting: {topic}.",
        "aliases": [],
        "status": "accepted",
        "importRunId": None,
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "semanticNodes",
    }
    record["contentHash"] = _hash_stable({"nodeKey": coverage_key, "nodeKind": record["nodeKind"], "displayName": topic})
    return {key: value for key, value in record.items() if value is not None}


def lane_node_record(node_key: str, display_name: str, alias: str, now: str) -> dict[str, Any]:
    lineage_id = f"semantic-node-{_safe_id(node_key)}"
    record = {
        "id": f"{lineage_id}-v1",
        "lineageId": lineage_id,
        "versionNumber": 1,
        "previousVersionId": None,
        "versionState": "current",
        "versionCreatedAt": now,
        "versionCreatedBy": "papyrus",
        "changeReason": "coverage-theme-lane-seed",
        "nodeKey": node_key,
        "nodeKind": "editorialForm",
        "displayName": display_name,
        "description": f"Editorial form lane for {display_name.lower()} assignments.",
        "aliases": [alias],
        "status": "accepted",
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "semanticNodes",
    }
    record["contentHash"] = _hash_stable({"nodeKey": node_key, "displayName": display_name, "aliases": [alias]})
    return record


def research_assignment_record(**kwargs: Any) -> dict[str, Any]:
    section = kwargs["section"]
    coverage_node = kwargs["coverage_node"]
    category = kwargs.get("category")
    category_set = kwargs.get("category_set")
    edition = kwargs["edition"]
    run_id = kwargs["run_id"]
    date = kwargs["date"]
    topic = kwargs["topic"]
    corpus_key = kwargs["corpus_key"]
    category_key = kwargs["category_key"]
    research_mode = kwargs["research_mode"]
    now = kwargs["now"]
    metadata = assignment_metadata(
        kind="coverage_theme.research_assignment",
        run_id=run_id,
        date=date,
        topic=topic,
        corpus_key=corpus_key,
        category_key=category_key,
        category=category,
        category_set=category_set,
        coverage_node=coverage_node,
        edition=edition,
        section=section,
        context_profile="researcher",
        expected_output="Private research packet for section-shaped reporting context, not reader copy.",
        research_mode=research_mode,
        research_lens=section_research_lens(section["id"]),
        signal=kwargs.get("signal"),
    )
    queue_key = f"coverage-theme:{date}:section:{section['id']}:lane:research"
    return {
        "id": f"assignment-coverage-theme-research-{_safe_id(run_id)}-{_safe_id(section['id'])}",
        "assignmentTypeKey": "research.edition-candidate",
        "queueKey": queue_key,
        "queueStatusKey": f"{queue_key}#open",
        "status": "open",
        "priority": kwargs["priority"],
        "title": f"Research {topic} for {section['title']}",
        "summary": f"Section-shaped research on {topic} for {section['title']}.",
        "brief": f"{section['title']} research lens: {section_research_lens(section['id'])}.",
        "instructions": f"Research {topic} through the {section['title']} section lens. Produce a private research_packet only.",
        "metadata": metadata,
        "corpusId": (category_set or {}).get("corpusId") or f"knowledge-corpus-{_safe_id(corpus_key)}",
        "categorySetId": (category_set or {}).get("id"),
        "classifierId": (category_set or {}).get("classifierId"),
        "sourceSnapshotId": None,
        "importRunId": run_id,
        "sectionId": section["id"],
        "sectionKey": section["id"],
        "sectionType": _normalize_section_type(section.get("type")),
        "sectionStatusKey": f"{section['id']}#open",
        "sectionQueueStatusKey": f"{section['id']}#{queue_key}#open",
        "primaryFocusCategoryKey": (category or {}).get("categoryKey") or category_key,
        "topicScopeCategoryKeys": [value for value in [(category or {}).get("categoryKey") or category_key] if value],
        "createdBy": "papyrus",
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "assignment#open",
    }


def reporting_assignment_record(**kwargs: Any) -> dict[str, Any]:
    section = kwargs["section"]
    coverage_node = kwargs["coverage_node"]
    category = kwargs.get("category")
    category_set = kwargs.get("category_set")
    edition = kwargs["edition"]
    run_id = kwargs["run_id"]
    date = kwargs["date"]
    topic = kwargs["topic"]
    corpus_key = kwargs["corpus_key"]
    category_key = kwargs["category_key"]
    now = kwargs["now"]
    angle = kwargs["angle"]
    concept = kwargs.get("concept") if isinstance(kwargs.get("concept"), dict) else None
    concept_name = str((concept or {}).get("displayName") or "").strip()
    metadata = assignment_metadata(
        kind="coverage_theme.reporting_assignment",
        run_id=run_id,
        date=date,
        topic=topic,
        corpus_key=corpus_key,
        category_key=category_key,
        category=category,
        category_set=category_set,
        coverage_node=coverage_node,
        edition=edition,
        section=section,
        context_profile="reporting",
        expected_output="Private reporting context packet for editor selection and copywriting, not reader copy.",
        research_mode=None,
        research_lens=section_research_lens(section["id"]),
        source_research_assignment_id=(kwargs.get("source_research_assignment") or {}).get("id"),
        slot_target={
            "slotId": (kwargs.get("assigned_slot") or {}).get("id"),
            "slotLineageId": ((kwargs.get("assigned_slot") or {}).get("metadata") or {}).get("slotLineageId"),
            "slotRank": ((kwargs.get("assigned_slot") or {}).get("slotRank") or ((kwargs["candidate_rank"] - 1) % max(kwargs["slots"], 1)) + 1),
            "sectionKey": section["id"],
            "slots": kwargs["slots"],
            "candidateRank": kwargs["candidate_rank"],
            "dispatchCount": kwargs["dispatch_count"],
        },
        angle_diversity={
            "lensKey": angle["key"],
            "lensLabel": angle["label"],
            "lensPrompt": angle["prompt"],
            "diversityKey": f"{section['id']}:{coverage_node['nodeKey']}:{angle['key']}:{kwargs['candidate_rank']}",
            "duplicateAnglePenalty": 0,
        },
        signal=kwargs.get("signal"),
        concept_hook={
            "conceptId": (concept or {}).get("conceptId"),
            "displayName": concept_name,
            "score": (concept or {}).get("score"),
            "metric": (concept or {}).get("metric"),
        } if concept_name else None,
    )
    if concept_name:
        title = f"{concept_name}: {topic} ({angle['label']})"
        summary = f"Reporting candidate on **{concept_name}** in the {topic} edition spine ({section['title']}, {angle['label']})."
        brief = (
            f"Build a private reporting context packet anchored on concept **{concept_name}**. "
            f"Edition spine: {topic}. Angle: {angle['prompt']}."
        )
    else:
        title = f"Report {topic} for {section['title']}: {angle['label']}"
        summary = f"Reporting candidate on {topic} for {section['title']}, angle: {angle['label']}."
        brief = f"Build a private reporting context packet. Angle: {angle['prompt']}."
    queue_key = f"coverage-theme:{date}:section:{section['id']}:lane:reporting"
    return {
        "id": f"assignment-coverage-theme-reporting-{_safe_id(run_id)}-{_safe_id(section['id'])}-{kwargs['candidate_rank']:02d}-{_safe_id(angle['key'])}",
        "assignmentTypeKey": "reporting.edition-candidate",
        "queueKey": queue_key,
        "queueStatusKey": f"{queue_key}#open",
        "status": "open",
        "priority": kwargs["priority"],
        "title": title,
        "summary": summary,
        "brief": brief,
        "instructions": f"Use the {section['title']} doctrine and section research packet. Produce reporting_context_packet only.",
        "metadata": metadata,
        "corpusId": (category_set or {}).get("corpusId") or f"knowledge-corpus-{_safe_id(corpus_key)}",
        "categorySetId": (category_set or {}).get("id"),
        "classifierId": (category_set or {}).get("classifierId"),
        "sourceSnapshotId": None,
        "importRunId": run_id,
        "sectionId": section["id"],
        "sectionKey": section["id"],
        "sectionType": _normalize_section_type(section.get("type")),
        "sectionStatusKey": f"{section['id']}#open",
        "sectionQueueStatusKey": f"{section['id']}#{queue_key}#open",
        "primaryFocusCategoryKey": (category or {}).get("categoryKey") or category_key,
        "topicScopeCategoryKeys": [value for value in [(category or {}).get("categoryKey") or category_key] if value],
        "createdBy": "papyrus",
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "assignment#open",
    }


def assignment_metadata(**kwargs: Any) -> dict[str, Any]:
    section = kwargs["section"]
    coverage_node = kwargs["coverage_node"]
    category = kwargs.get("category")
    category_set = kwargs.get("category_set")
    edition = kwargs["edition"]
    signal = kwargs.get("signal") or {}
    return {
        "kind": kwargs["kind"],
        "coverageThemeKind": "coverage_theme",
        "storyCycleRunId": kwargs["run_id"],
        "coverageThemeRunId": kwargs["run_id"],
        "coverageThemeLabel": kwargs["topic"],
        "storyCycleDate": kwargs["date"],
        "topic": kwargs["topic"],
        "corpusKey": kwargs["corpus_key"],
        "editionDate": kwargs["date"],
        "editionId": edition["id"],
        "editionLineageId": edition["lineageId"],
        "coverageConceptId": coverage_node["id"],
        "coverageConceptLineageId": coverage_node["lineageId"],
        "coverageConceptKey": coverage_node["nodeKey"],
        "coverageConceptTitle": coverage_node["displayName"],
        "categoryKey": (category or {}).get("categoryKey") or kwargs["category_key"],
        "focusCategoryKey": (category or {}).get("categoryKey") or kwargs["category_key"],
        "focusCategoryLineageId": (category or {}).get("lineageId"),
        "focusCategoryTitle": (category or {}).get("displayName") or (category or {}).get("shortTitle") or kwargs["category_key"],
        "categorySetId": (category_set or {}).get("id"),
        "classifierId": (category_set or {}).get("classifierId"),
        "sectionId": section["id"],
        "sectionKey": section["id"],
        "sectionTitle": section["title"],
        "sectionType": _normalize_section_type(section.get("type")),
        "sectionMission": section.get("editorialMission"),
        "sectionPolicies": [section["editorialPolicy"]] if section.get("editorialPolicy") else [],
        "assignmentGuidance": section.get("assignmentGuidance"),
        "killCriteria": section.get("killCriteria"),
        "visualGuidance": section.get("visualGuidance"),
        "contextProfile": kwargs["context_profile"],
        "contextSources": ["publication-doctrine", "section-doctrine", "assignment-brief", "accepted-knowledge-base-evidence", "recent-section-memory", "fresh-source-needs"],
        "researchMode": kwargs.get("research_mode"),
        "researchLens": kwargs.get("research_lens"),
        "sourceResearchAssignmentId": kwargs.get("source_research_assignment_id"),
        "slotTarget": kwargs.get("slot_target"),
        "angleDiversity": kwargs.get("angle_diversity"),
        "signalId": signal.get("signalId"),
        "signalRank": signal.get("rank"),
        "signalWhyNow": signal.get("whyNow"),
        "conceptHook": kwargs.get("concept_hook"),
        "expectedOutput": kwargs["expected_output"],
        "publicReaderVisible": False,
        "createdBy": "papyrus coverage-themes run",
    }


def assignment_event_record(assignment: dict[str, Any], now: str) -> dict[str, Any]:
    return {
        "id": f"assignment-event-{assignment['id']}-created",
        "assignmentId": assignment["id"],
        "assignmentTypeKey": assignment["assignmentTypeKey"],
        "queueKey": assignment["queueKey"],
        "eventType": "created",
        "fromStatus": None,
        "toStatus": "open",
        "actorSub": None,
        "actorLabel": "Papyrus newsroom CLI",
        "note": f"Created Coverage Theme {assignment['assignmentTypeKey']} assignment.",
        "createdAt": now,
    }


def packet_message(message_id: str, kind: str, summary: str, source: str, assignment: dict[str, Any], now: str) -> dict[str, Any]:
    return {
        "id": message_id,
        "messageKind": kind,
        "messageDomain": "assignment_work",
        "status": "active",
        "summary": summary,
        "source": source,
        "importRunId": assignment.get("importRunId"),
        "authorLabel": "papyrus",
        "newsroomFeedKey": f"message#{kind}",
        "createdAt": now,
        "updatedAt": now,
    }


def story_cycle_packet_message_id(assignment: dict[str, Any], message_kind: str) -> str:
    suffix = "research_packet" if message_kind == "research_packet" else "reporting_context_packet"
    return f"message-{message_kind.replace('_', '-')}-{_hash_short([assignment['id'], suffix])}"


def semantic_relation(
    *,
    predicate: str,
    subject_kind: str,
    subject_id: str,
    object_kind: str,
    object_id: str,
    subject_lineage_id: str | None = None,
    subject_version_number: int | None = None,
    object_lineage_id: str | None = None,
    object_version_number: int | None = None,
    score: float | None = None,
    confidence: float | None = None,
    rank: int | None = None,
    classifier_id: str | None = None,
    model_version: str | None = None,
    source_snapshot_id: str | None = None,
    import_run_id: str | None = None,
    now: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or _now_iso()
    subject_lineage_id = subject_lineage_id or subject_id
    object_lineage_id = object_lineage_id or object_id
    subject_state_key = semantic_state_key(subject_kind, subject_lineage_id)
    object_state_key = semantic_state_key(object_kind, object_lineage_id)
    subject_version_key = semantic_version_key(subject_kind, subject_id)
    object_version_key = semantic_version_key(object_kind, object_id)
    key = _normalize_relation_key(predicate)
    relation = {
        "id": f"semantic-relation-{_hash_short([subject_version_key, key, object_version_key, rank or '', classifier_id or '', model_version or ''])}",
        "relationState": "current",
        "predicate": key,
        "relationTypeId": f"semantic-relation-type-{_safe_id(key)}",
        "relationTypeKey": key,
        "relationDomain": RELATION_DOMAINS.get(key, "generic"),
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
        "predicateObjectStateKey": f"{key}#{object_state_key}",
        "subjectVersionKey": subject_version_key,
        "objectVersionKey": object_version_key,
        "score": score if score is not None else confidence if confidence is not None else 1,
        "confidence": confidence,
        "rank": rank,
        "classifierId": classifier_id,
        "modelVersion": model_version,
        "reviewRecommended": False,
        "sourceSnapshotId": source_snapshot_id,
        "importRunId": import_run_id,
        "importedAt": now,
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "semanticRelations",
        "metadata": metadata or {},
    }
    return {key: value for key, value in relation.items() if value is not None}


def apply_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    applied = []
    warnings = []
    for record in records:
        model_name = record["modelName"]
        action = record.get("action") or "upsert"
        input_payload = record.get("input") or {}
        try:
            if action == "noop":
                applied.append({"modelName": model_name, "action": "noop", "id": input_payload.get("id")})
                continue
            if model_name == "ModelAttachment":
                _upload_model_attachment(input_payload, str(record.get("body") or ""))
                applied.append({"modelName": model_name, "action": "upload", "id": input_payload.get("id")})
                continue
            if action == "create":
                _create_record(model_name, input_payload)
                applied.append({"modelName": model_name, "action": "create", "id": input_payload.get("id")})
            elif action == "update":
                _update_record(model_name, input_payload)
                applied.append({"modelName": model_name, "action": "update", "id": input_payload.get("id")})
            elif action == "upsert":
                if _record_exists(model_name, str(input_payload.get("id"))):
                    _update_record(model_name, input_payload)
                    applied.append({"modelName": model_name, "action": "update", "id": input_payload.get("id")})
                else:
                    _create_record(model_name, input_payload)
                    applied.append({"modelName": model_name, "action": "create", "id": input_payload.get("id")})
            else:
                raise ValueError(f"Unsupported action {action}")
        except Exception as exc:  # pragma: no cover - live GraphQL behavior varies by deployment
            warnings.append(f"{model_name} {input_payload.get('id')} failed: {exc}")
            raise
    return {"apply": True, "applied": applied, "warnings": warnings}


def load_live_state(*, models: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    model_names = models or list(LIST_FIELDS.keys())
    state: dict[str, list[dict[str, Any]]] = {}
    for model in model_names:
        state[_state_key(model)] = _list_records(model)
    return state


def load_story_budget_state(*, run_id: str = "") -> dict[str, list[dict[str, Any]]]:
    if not run_id:
        return load_live_state(models=["Edition", "Assignment", "AssignmentEvent", "Message", "SemanticRelation", "ModelAttachment", "Item", "EditionItem", "EditionSlot", "NewsroomSection"])
    assignments = _list_assignments_by_import_run(run_id)
    relations: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    messages_by_id: dict[str, dict[str, Any]] = {}
    attachments: list[dict[str, Any]] = []
    items_by_id: dict[str, dict[str, Any]] = {}
    slots_by_id: dict[str, dict[str, Any]] = {}
    for assignment in assignments:
        assignment_id = assignment.get("id")
        if not assignment_id:
            continue
        assignment_relations = _list_relations_by_subject("assignment", assignment_id)
        relations.extend(assignment_relations)
        events.extend(_list_assignment_events(assignment_id))
        for relation in assignment_relations:
            relation_type = relation.get("relationTypeKey") or relation.get("predicate")
            if relation_type != "produces":
                if relation_type == "targets_slot" and relation.get("objectKind") == "editionSlot":
                    slot = _get_record("EditionSlot", relation.get("objectId"))
                    if slot:
                        slots_by_id[slot["id"]] = slot
                continue
            if relation.get("objectKind") == "message":
                message = _get_record("Message", relation.get("objectId"))
                if message:
                    messages_by_id[message["id"]] = message
                    attachments.extend(_list_model_attachments_by_owner(message["id"]))
            elif relation.get("objectKind") == "item":
                item = _get_record("Item", relation.get("objectId"))
                if item:
                    items_by_id[item["id"]] = item
    return {
        "assignments": assignments,
        "semanticRelations": _dedupe_by_id(relations),
        "assignmentEvents": _dedupe_by_id(events),
        "messages": list(messages_by_id.values()),
        "modelAttachments": _dedupe_by_id(attachments),
        "items": list(items_by_id.values()),
        "editionItems": [],
        "editionSlots": list(slots_by_id.values()),
        "newsroomSections": [],
    }


def resolve_sections(section_keys: list[str], newsroom_sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {
        str(section.get("id")): section
        for section in newsroom_sections
        if section.get("enabled") is not False and section.get("enabledStatus") != "disabled"
    }
    sections = []
    for index, raw_key in enumerate(_resolve_section_keys(section_keys)):
        key = SECTION_ALIASES.get(raw_key, raw_key)
        section = by_id.get(key) or by_id.get(raw_key)
        if not section:
            section = synthetic_section(key, index)
        sections.append(_decode_record(section))
    return sections


def synthetic_section(key: str, index: int) -> dict[str, Any]:
    title = " ".join(part.capitalize() for part in re.split(r"[-_\s]+", key) if part) or key
    return {
        "id": key,
        "title": title,
        "shortTitle": title,
        "type": "canonical",
        "editorialMission": f"Cover {title}.",
        "editorialPolicy": f"Use the {title} section lens.",
        "assignmentGuidance": None,
        "killCriteria": None,
        "visualGuidance": None,
        "enabled": True,
        "sortOrder": index + 1,
        "defaultArticleTypes": ["article"],
        "defaultPageBudget": DEFAULT_SECTION_BUDGETS.get(key, 1),
    }


def find_category(category_key: str, categories: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not category_key:
        return None
    for category in categories:
        if category.get("versionState") not in {None, "current"} or category.get("status") in {"archived", "rejected"}:
            continue
        if category_key in {category.get("id"), category.get("lineageId"), category.get("categoryKey"), category.get("displayName")}:
            return _decode_record(category)
    return None


def find_category_set(category: dict[str, Any] | None, category_sets: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not category:
        return None
    category_set_id = category.get("categorySetId")
    for category_set in category_sets:
        if category_set.get("id") == category_set_id:
            return _decode_record(category_set)
    return None


def latest_reporting_decision(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    decision_events = [
        event for event in events
        if str(event.get("eventType") or "").startswith("reporting_")
    ]
    if not decision_events:
        return None
    latest = sorted(decision_events, key=lambda item: str(item.get("createdAt") or ""), reverse=True)[0]
    decision = str(latest.get("eventType") or "").replace("reporting_", "", 1)
    return {
        "eventId": latest.get("id"),
        "decision": decision,
        "note": latest.get("note"),
        "createdAt": latest.get("createdAt"),
    }


def normalize_through(value: str) -> str:
    normalized = str(value or "reporting").strip().lower().replace("-", "_")
    if normalized not in THROUGH_PHASES:
        raise ValueError(f"Invalid --through {value!r}. Expected plan, rotating_desk, research, or reporting.")
    return normalized


def partition_sections_for_dispatch(
    resolved_sections: list[dict[str, Any]],
    *,
    selected_optional_desk_key: str = "",
    include_optional_desks: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    core_sections: list[dict[str, Any]] = []
    optional_sections: list[dict[str, Any]] = []
    for section in resolved_sections:
        if _section_planning_role(section) == "optional_desk":
            optional_sections.append(section)
        else:
            core_sections.append(section)
    if include_optional_desks:
        return [*core_sections, *optional_sections], []
    dispatch_sections = list(core_sections)
    if selected_optional_desk_key:
        selected = next(
            (section for section in optional_sections if str(section.get("id") or "") == selected_optional_desk_key),
            None,
        )
        if selected and selected not in dispatch_sections:
            dispatch_sections.append(selected)
        provisional = [section for section in optional_sections if section is not selected]
        return dispatch_sections, provisional
    return dispatch_sections, optional_sections


def parse_section_budgets(value: str, sections: list[str] | None = None) -> dict[str, int]:
    result = {}
    for section in _resolve_section_keys(sections or []):
        result[SECTION_ALIASES.get(section, section)] = DEFAULT_SECTION_BUDGETS.get(section, 1)
    for part in str(value or "").split(","):
        if not part.strip():
            continue
        key, _, raw_slots = part.partition(":")
        section_key = SECTION_ALIASES.get(key.strip(), key.strip())
        try:
            slots = max(1, int(raw_slots.strip()))
        except ValueError as exc:
            raise ValueError(f"Invalid section budget {part!r}; expected section:slots.") from exc
        result[section_key] = slots
    return result


def parse_csv(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def load_json_file(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _signal_report_body(report: dict[str, Any]) -> str:
    lines = [
        f"Edition Signal Report: {report.get('date')}",
        f"Corpus: {report.get('corpusKey')}",
        "",
    ]
    for signal in report.get("signals") or []:
        lines.extend([
            f"{signal.get('rank')}. {signal.get('topic')} ({signal.get('coverageKey')})",
            f"Score: {signal.get('score')}",
            f"Why now: {signal.get('whyNow')}",
            f"Accepted references: {signal.get('acceptedEvidenceCount')}",
            "",
        ])
    return "\n".join(lines).strip() + "\n"


def _concept_report_body(report: dict[str, Any]) -> str:
    lines = [
        "Concept Analytics Report",
        f"Corpus: {report.get('corpusKey')}",
        f"Generated: {report.get('generatedAt')}",
        "",
    ]
    for report_section in report.get("reports") or []:
        lines.extend([
            str(report_section.get("title") or report_section.get("reportType") or "Report"),
            f"Metric: {report_section.get('primaryMetric')}",
            "",
        ])
        for concept in report_section.get("rankedConcepts") or []:
            lines.append(
                f"{concept.get('rank')}. {concept.get('displayName')} "
                f"({concept.get('conceptLineageId') or concept.get('conceptId')}) - "
                f"{concept.get('metric')}: {concept.get('score')}"
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _research_packet_body(packet: dict[str, Any]) -> str:
    return "\n".join([
        packet["summary"],
        "",
        f"Section: {packet.get('section_key')}",
        f"Coverage: {packet.get('coverage_key')}",
        f"Recommended angle: {packet.get('recommended_angle')}",
        "",
        "Open questions:",
        *[f"- {item}" for item in packet.get("open_questions") or []],
        "",
        "Coverage gaps:",
        *[f"- {item}" for item in packet.get("coverage_gaps") or []],
    ]).strip() + "\n"


def _reporting_packet_body(packet: dict[str, Any]) -> str:
    return "\n".join([
        packet["summary"],
        "",
        f"Section: {packet.get('section_key')}",
        f"Angle: {packet.get('recommended_angle')}",
        f"Recommendation: {packet.get('editor_recommendation')}",
        "",
        "Risk flags:",
        *[f"- {item}" for item in packet.get("risk_flags") or []],
        "",
        "Coverage gaps:",
        *[f"- {item}" for item in packet.get("coverage_gaps") or []],
        "",
        "Copywriter brief:",
        str(packet.get("copywriter_brief") or ""),
    ]).strip() + "\n"


def _packet_summary(messages: list[dict[str, Any]], attachments: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    if not messages:
        return {"packetAvailable": False}
    message = messages[0]
    packet = {}
    for attachment in attachments:
        if attachment.get("ownerId") == message.get("id") and attachment.get("role") == "metadata":
            try:
                metadata = _download_attachment_json(attachment["id"])
                packet = metadata.get(kind) or metadata.get("reporting") or metadata.get("research") or {}
            except Exception:
                packet = {}
            break
    return {
        "packetAvailable": True,
        "packetSummary": message.get("summary"),
        "editorRecommendation": packet.get("editor_recommendation") or packet.get("editorRecommendation"),
        "recommendedAngle": packet.get("recommended_angle") or packet.get("recommendedAngle"),
        "riskFlags": packet.get("risk_flags") or packet.get("riskFlags") or [],
        "coverageGaps": packet.get("coverage_gaps") or packet.get("coverageGaps") or [],
        "openQuestions": packet.get("open_questions") or packet.get("openQuestions") or [],
        "acceptedEvidenceCount": len(packet.get("accepted_reference_ids") or packet.get("acceptedReferenceIds") or []),
        "proposedReferenceCount": len(packet.get("proposed_references") or packet.get("proposedReferences") or []),
        "copywriterBrief": packet.get("copywriter_brief") or packet.get("copywriterBrief"),
        "degraded": bool(packet.get("degraded")),
        "fallbackReason": packet.get("fallbackReason") or packet.get("fallback_reason"),
    }


def _normalize_concept_report_type(value: str) -> str:
    normalized = str(value or "all").strip().lower().replace("-", "_")
    aliases = {
        "frequency": "popularity",
        "popular": "popularity",
        "trend": "trending",
        "page_rank": "pagerank",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"all", "popularity", "trending", "pagerank", "centrality"}:
        raise ValueError("report_type must be one of all, popularity, trending, pagerank, or centrality")
    return normalized


def _normalize_centrality_order(value: str) -> str:
    normalized = str(value or "most").strip().lower().replace("-", "_")
    aliases = {
        "top": "most",
        "central": "most",
        "descending": "most",
        "desc": "most",
        "bottom": "least",
        "periphery": "least",
        "peripheral": "least",
        "frontier": "least",
        "ascending": "least",
        "asc": "least",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"most", "least"}:
        raise ValueError("order must be one of most or least")
    return normalized


def _concept_report_context(
    *,
    references: list[dict[str, Any]],
    semantic_nodes: list[dict[str, Any]],
    semantic_relations: list[dict[str, Any]],
    corpus_key: str,
    node_kinds: list[str],
    now: str,
) -> dict[str, Any]:
    now_dt = _parse_datetime(now) or dt.datetime.now(dt.UTC)
    corpus_id = f"knowledge-corpus-{_safe_id(corpus_key)}"
    accepted = _accepted_references(references, corpus_key)
    references_by_key: dict[str, dict[str, Any]] = {}
    for ref in accepted:
        for key in (ref.get("id"), ref.get("lineageId")):
            if key:
                references_by_key[str(key)] = ref
    allowed_node_kinds = {str(kind).strip() for kind in node_kinds if str(kind).strip()}
    nodes_by_key: dict[str, dict[str, Any]] = {}
    for raw_node in semantic_nodes:
        node = _decode_record(raw_node)
        if node.get("versionState") not in {None, "current"}:
            continue
        if node.get("status") not in {None, "", "active", "accepted", "current"}:
            continue
        if allowed_node_kinds and str(node.get("nodeKind") or "") not in allowed_node_kinds:
            continue
        if corpus_key and node.get("corpusId") not in {None, "", corpus_id, corpus_key}:
            continue
        for key in (node.get("id"), node.get("lineageId")):
            if key:
                nodes_by_key[str(key)] = node
    mentions: list[dict[str, Any]] = []
    mentions_by_concept: dict[str, list[dict[str, Any]]] = {}
    concepts_by_id: dict[str, dict[str, Any]] = {}
    for raw_relation in semantic_relations:
        relation = _decode_record(raw_relation)
        relation_type = relation.get("relationTypeKey") or relation.get("predicate")
        if _normalize_relation_key(relation_type) != "mentions":
            continue
        if relation.get("relationState") not in {None, "current"}:
            continue
        if str(relation.get("subjectKind") or "") != "reference":
            continue
        if str(relation.get("objectKind") or "") != "semanticNode":
            continue
        reference = references_by_key.get(str(relation.get("subjectLineageId") or "")) or references_by_key.get(str(relation.get("subjectId") or ""))
        node = nodes_by_key.get(str(relation.get("objectLineageId") or "")) or nodes_by_key.get(str(relation.get("objectId") or ""))
        if not reference or not node:
            continue
        concept_id = str(node.get("id") or relation.get("objectId"))
        if not concept_id:
            continue
        concept_lineage_id = str(node.get("lineageId") or concept_id)
        reference_id = str(reference.get("id") or relation.get("subjectId"))
        reference_lineage_id = str(reference.get("lineageId") or reference_id)
        mention = {
            "id": relation.get("id") or _hash_short(relation),
            "conceptId": concept_id,
            "conceptLineageId": concept_lineage_id,
            "referenceId": reference_id,
            "referenceLineageId": reference_lineage_id,
            "weight": _relation_weight(relation),
            "datetime": _reference_datetime(reference) or _parse_datetime(relation.get("importedAt") or relation.get("createdAt") or relation.get("updatedAt")) or now_dt,
        }
        concepts_by_id[concept_id] = node
        mentions.append(mention)
        mentions_by_concept.setdefault(concept_id, []).append(mention)
    return {
        "now": now_dt,
        "references": accepted,
        "referencesByKey": references_by_key,
        "conceptsById": concepts_by_id,
        "mentions": mentions,
        "mentionsByConcept": mentions_by_concept,
    }


def _build_concept_popularity_report(context: dict[str, Any], limit: int) -> dict[str, Any]:
    ranked = []
    for concept_id, mentions in context["mentionsByConcept"].items():
        ranked.append(_concept_report_row(
            context=context,
            concept_id=concept_id,
            mentions=mentions,
            metric="distinctReferenceCount",
            score=len({mention["referenceLineageId"] for mention in mentions}),
        ))
    ranked.sort(key=lambda item: (-int(item["distinctReferenceCount"]), -float(item["weightedMentionScore"]), item["displayName"]))
    return _concept_report_section(
        report_type="popularity",
        title="Most Referenced Concepts",
        primary_metric="distinctReferenceCount",
        ranked=ranked[:limit],
    )


def _build_concept_trending_report(context: dict[str, Any], limit: int, trend_window_days: int) -> dict[str, Any]:
    window_days = max(1, int(trend_window_days or 1))
    now_dt = context["now"]
    recent_cutoff = now_dt - dt.timedelta(days=window_days)
    prior_cutoff = now_dt - dt.timedelta(days=window_days * 2)
    ranked = []
    for concept_id, mentions in context["mentionsByConcept"].items():
        recent_refs = {
            mention["referenceLineageId"]
            for mention in mentions
            if mention["datetime"] >= recent_cutoff
        }
        prior_refs = {
            mention["referenceLineageId"]
            for mention in mentions
            if prior_cutoff <= mention["datetime"] < recent_cutoff
        }
        recent_count = len(recent_refs)
        prior_count = len(prior_refs)
        delta = recent_count - prior_count
        growth = round(delta / max(prior_count, 1), 3)
        velocity_score = round(recent_count + max(delta, 0) + max(growth, 0), 3)
        if recent_count <= 0:
            continue
        row = _concept_report_row(
            context=context,
            concept_id=concept_id,
            mentions=mentions,
            metric="velocityScore",
            score=velocity_score,
        )
        row.update({
            "recentWindowDays": window_days,
            "recentDistinctReferenceCount": recent_count,
            "priorDistinctReferenceCount": prior_count,
            "delta": delta,
            "growthRate": growth,
        })
        ranked.append(row)
    ranked.sort(key=lambda item: (-float(item["score"]), -int(item["recentDistinctReferenceCount"]), item["displayName"]))
    return _concept_report_section(
        report_type="trending",
        title=f"Trending Concepts ({window_days}d)",
        primary_metric="velocityScore",
        ranked=ranked[:limit],
    )


def _build_concept_pagerank_report(
    context: dict[str, Any],
    limit: int,
    iterations: int,
    damping: float,
    max_nodes_per_reference: int,
) -> dict[str, Any]:
    graph = _concept_comention_graph(context, max_nodes_per_reference=max_nodes_per_reference)
    scores = _weighted_pagerank(graph, iterations=max(1, int(iterations or 1)), damping=float(damping or 0.85))
    if not scores:
        total_mentions = max(1, len(context["mentions"]))
        scores = {
            concept_id: len(mentions) / total_mentions
            for concept_id, mentions in context["mentionsByConcept"].items()
        }
    ranked = []
    for concept_id, score in scores.items():
        mentions = context["mentionsByConcept"].get(concept_id) or []
        if not mentions:
            continue
        ranked.append(_concept_report_row(
            context=context,
            concept_id=concept_id,
            mentions=mentions,
            metric="pagerankScore",
            score=round(float(score), 8),
        ))
    ranked.sort(key=lambda item: (-float(item["score"]), -int(item["distinctReferenceCount"]), item["displayName"]))
    return _concept_report_section(
        report_type="pagerank",
        title="Concept Graph Importance",
        primary_metric="pagerankScore",
        ranked=ranked[:limit],
    )


# Minimum corpus subgraph size for a meaningful centrality ranking. Below this,
# the centrality report fails closed instead of inventing scores.
CENTRALITY_MIN_NODES = 2


def _build_concept_centrality_report(
    *,
    context: dict[str, Any],
    references: list[dict[str, Any]],
    semantic_nodes: list[dict[str, Any]],
    semantic_relations: list[dict[str, Any]],
    corpus_key: str,
    node_kinds: list[str],
    limit: int,
    order: str,
    pagerank_iterations: int,
    pagerank_damping: float,
) -> dict[str, Any]:
    """Rank corpus concepts by graph centrality (weighted PageRank over the full
    SemanticNode/SemanticRelation subgraph), reusing the existing authority
    PageRank plumbing. ``order="most"`` returns the most-central concepts;
    ``order="least"`` returns the opposite end of the same ranking (the
    periphery). Fails closed with an empty list and a stability reason when the
    corpus subgraph is too sparse for a stable ranking. Creates no
    Reference/Item/EditionItem; it is a human-reviewable suggestion list only.
    """
    from papyrus_content.ontology_enrichment import build_state_indexes, rank_concepts

    corpus_id = f"knowledge-corpus-{_safe_id(corpus_key)}" if corpus_key else ""
    allowed_node_kinds = {str(kind).strip() for kind in (node_kinds or []) if str(kind).strip()}
    filtered_nodes = _centrality_filtered_nodes(semantic_nodes, corpus_id, allowed_node_kinds)
    accepted_refs = _accepted_references(references, corpus_key)
    allowed_endpoints = _centrality_allowed_endpoints(filtered_nodes, accepted_refs)
    filtered_relations = _centrality_filtered_relations(semantic_relations, allowed_endpoints)

    state = build_state_indexes(
        {
            "SemanticNode": filtered_nodes,
            "SemanticRelation": filtered_relations,
            "Reference": accepted_refs,
            "ModelAttachment": [],
            "SemanticRelationType": [],
        }
    )
    ranked_concepts = rank_concepts(
        state,
        include_operational=False,
        include_profile_status=False,
    )

    node_count = len(filtered_nodes)
    relation_count = len(filtered_relations)
    pagerank_values = [float(row.get("pageRank") or 0.0) for row in ranked_concepts]
    max_pr = max(pagerank_values) if pagerank_values else 0.0
    min_pr = min(pagerank_values) if pagerank_values else 0.0
    uniform = bool(pagerank_values) and max_pr <= min_pr
    stable = node_count >= CENTRALITY_MIN_NODES and not uniform

    if not stable:
        reason = (
            "no current semantic nodes in corpus"
            if node_count < CENTRALITY_MIN_NODES
            else "graph too sparse: no relations differentiate concept centrality"
        )
        return _concept_report_section(
            report_type="centrality",
            title="Concept Centrality" if order == "most" else "Concept Periphery (Least Central)",
            primary_metric="pagerankScore",
            ranked=[],
        ) | {
            "order": order,
            "stability": {
                "stable": False,
                "reason": reason,
                "nodeCount": node_count,
                "relationCount": relation_count,
                "minNodes": CENTRALITY_MIN_NODES,
            },
        }

    ranked = []
    for row in ranked_concepts:
        concept_id = str(row.get("id") or "")
        if not concept_id:
            continue
        mentions = context["mentionsByConcept"].get(concept_id) or []
        reference_lineage_ids = sorted({mention["referenceLineageId"] for mention in mentions})
        source_reference_ids = sorted({mention["referenceId"] for mention in mentions})
        source_domains = sorted(
            {
                _domain((context["referencesByKey"].get(ref_id) or {}).get("sourceUri"))
                for ref_id in reference_lineage_ids
                if _domain((context["referencesByKey"].get(ref_id) or {}).get("sourceUri"))
            }
        )
        ranked.append(
            {
                "conceptId": concept_id,
                "conceptLineageId": str(row.get("lineageId") or concept_id),
                "nodeKind": row.get("nodeKind"),
                "displayName": str(row.get("displayName") or row.get("nodeKey") or concept_id),
                "metric": "pagerankScore",
                "score": round(float(row.get("pageRank") or 0.0), 8),
                "mentionCount": len(mentions),
                "distinctReferenceCount": len(reference_lineage_ids),
                "weightedMentionScore": round(sum(float(m.get("weight") or 0) for m in mentions), 3),
                "sourceReferenceIds": source_reference_ids,
                "sourceReferenceLineageIds": reference_lineage_ids,
                "sourceDomains": source_domains,
                "mentionRelationIds": [str(m.get("id")) for m in mentions if m.get("id")],
            }
        )

    ranked.sort(
        key=lambda item: (
            -float(item["score"]),
            -int(item["distinctReferenceCount"]),
            str(item["conceptId"]),
        )
    )
    if order == "least":
        ranked.reverse()
    return _concept_report_section(
        report_type="centrality",
        title="Concept Centrality" if order == "most" else "Concept Periphery (Least Central)",
        primary_metric="pagerankScore",
        ranked=ranked[:limit],
    ) | {
        "order": order,
        "stability": {
            "stable": True,
            "reason": "",
            "nodeCount": node_count,
            "relationCount": relation_count,
            "minNodes": CENTRALITY_MIN_NODES,
        },
    }


def _centrality_filtered_nodes(
    semantic_nodes: list[dict[str, Any]],
    corpus_id: str,
    allowed_node_kinds: set[str],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for raw_node in semantic_nodes:
        node = _decode_record(raw_node)
        if node.get("versionState") not in {None, "current"}:
            continue
        if node.get("status") in {"deleted", "archived", "rejected"}:
            continue
        if allowed_node_kinds and str(node.get("nodeKind") or "") not in allowed_node_kinds:
            continue
        if corpus_id and node.get("corpusId") not in {None, "", corpus_id}:
            continue
        filtered.append(node)
    return filtered


def _centrality_allowed_endpoints(
    filtered_nodes: list[dict[str, Any]],
    accepted_refs: list[dict[str, Any]],
) -> set[str]:
    allowed: set[str] = set()
    for node in filtered_nodes:
        lineage_id = str(node.get("lineageId") or node.get("id") or "")
        if lineage_id:
            allowed.add(f"semanticNode#{lineage_id}")
    for ref in accepted_refs:
        for key in (ref.get("lineageId"), ref.get("id")):
            if key:
                allowed.add(f"reference#{key}")
    return allowed


def _centrality_filtered_relations(
    semantic_relations: list[dict[str, Any]],
    allowed_endpoints: set[str],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for raw_relation in semantic_relations:
        relation = _decode_record(raw_relation)
        if relation.get("relationState") not in {None, "", "current"}:
            continue
        subject_kind = str(relation.get("subjectKind") or "")
        object_kind = str(relation.get("objectKind") or "")
        if {subject_kind, object_kind} - {"semanticNode", "reference"}:
            continue
        subject_key = f"{subject_kind}#{relation.get('subjectLineageId') or relation.get('subjectId') or ''}"
        object_key = f"{object_kind}#{relation.get('objectLineageId') or relation.get('objectId') or ''}"
        if subject_key not in allowed_endpoints or object_key not in allowed_endpoints:
            continue
        filtered.append(relation)
    return filtered


def _concept_report_row(
    *,
    context: dict[str, Any],
    concept_id: str,
    mentions: list[dict[str, Any]],
    metric: str,
    score: float | int,
) -> dict[str, Any]:
    node = context["conceptsById"].get(concept_id) or {}
    reference_lineage_ids = sorted({mention["referenceLineageId"] for mention in mentions})
    source_reference_ids = sorted({mention["referenceId"] for mention in mentions})
    source_domains = sorted({
        _domain((context["referencesByKey"].get(reference_id) or {}).get("sourceUri"))
        for reference_id in reference_lineage_ids
        if _domain((context["referencesByKey"].get(reference_id) or {}).get("sourceUri"))
    })
    return {
        "conceptId": concept_id,
        "conceptLineageId": str(node.get("lineageId") or concept_id),
        "nodeKind": node.get("nodeKind"),
        "displayName": str(node.get("displayName") or node.get("nodeKey") or concept_id),
        "metric": metric,
        "score": score,
        "mentionCount": len(mentions),
        "distinctReferenceCount": len(reference_lineage_ids),
        "weightedMentionScore": round(sum(float(mention.get("weight") or 0) for mention in mentions), 3),
        "sourceReferenceIds": source_reference_ids,
        "sourceReferenceLineageIds": reference_lineage_ids,
        "sourceDomains": source_domains,
        "mentionRelationIds": [str(mention["id"]) for mention in mentions if mention.get("id")],
    }


def _concept_report_section(report_type: str, title: str, primary_metric: str, ranked: list[dict[str, Any]]) -> dict[str, Any]:
    ranked_with_rank = []
    for rank, concept in enumerate(ranked, start=1):
        ranked_with_rank.append({"rank": rank, **concept})
    return {
        "reportType": report_type,
        "title": title,
        "primaryMetric": primary_metric,
        "rankedConcepts": ranked_with_rank,
        "mentionRelationIds": sorted({
            relation_id
            for concept in ranked_with_rank
            for relation_id in concept.get("mentionRelationIds") or []
        }),
    }


def _concept_comention_graph(context: dict[str, Any], *, max_nodes_per_reference: int) -> dict[str, dict[str, float]]:
    concepts_by_reference: dict[str, dict[str, float]] = {}
    for mention in context["mentions"]:
        concepts_by_reference.setdefault(mention["referenceLineageId"], {})
        concept_weights = concepts_by_reference[mention["referenceLineageId"]]
        concept_weights[mention["conceptId"]] = concept_weights.get(mention["conceptId"], 0.0) + float(mention.get("weight") or 1.0)
    graph: dict[str, dict[str, float]] = {concept_id: {} for concept_id in context["mentionsByConcept"]}
    max_nodes = max(2, int(max_nodes_per_reference or 2))
    for concept_weights in concepts_by_reference.values():
        ordered = sorted(concept_weights.items(), key=lambda item: (-item[1], item[0]))[:max_nodes]
        if len(ordered) < 2:
            continue
        for index, (left, left_weight) in enumerate(ordered):
            for right, right_weight in ordered[index + 1:]:
                weight = math.sqrt(max(left_weight, 0.0) * max(right_weight, 0.0)) or 1.0
                graph.setdefault(left, {})[right] = graph.setdefault(left, {}).get(right, 0.0) + weight
                graph.setdefault(right, {})[left] = graph.setdefault(right, {}).get(left, 0.0) + weight
    return graph


def _weighted_pagerank(graph: dict[str, dict[str, float]], *, iterations: int, damping: float) -> dict[str, float]:
    nodes = sorted(graph)
    if not nodes:
        return {}
    damping = min(max(damping, 0.0), 1.0)
    count = len(nodes)
    scores = {node: 1.0 / count for node in nodes}
    base = (1.0 - damping) / count
    for _ in range(iterations):
        next_scores = {node: base for node in nodes}
        dangling = sum(scores[node] for node in nodes if not graph.get(node))
        dangling_share = damping * dangling / count
        for node in nodes:
            next_scores[node] += dangling_share
            neighbors = graph.get(node) or {}
            total_weight = sum(max(weight, 0.0) for weight in neighbors.values())
            if total_weight <= 0:
                continue
            for neighbor, weight in neighbors.items():
                next_scores[neighbor] += damping * scores[node] * (max(weight, 0.0) / total_weight)
        scores = next_scores
    return scores


def _relation_weight(relation: dict[str, Any]) -> float:
    for key in ("score", "confidence"):
        value = relation.get(key)
        if value is None:
            continue
        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            continue
    return 1.0


def _record(model_name: str, input_payload: dict[str, Any], action: str = "upsert") -> dict[str, Any]:
    return {"modelName": model_name, "action": action, "input": _clean_none(input_payload)}


def _attachment_record(owner_id: str, role: str, sort_key: str, filename: str, media_type: str, content: Any, import_run_id: str | None, now: str) -> dict[str, Any]:
    body = content if isinstance(content, str) else json.dumps(content, indent=2, sort_keys=True) + "\n"
    body_bytes = body.encode("utf-8")
    attachment = {
        "id": f"model-attachment-message-{_safe_id(owner_id)}-{_safe_id(role)}-{_safe_id(sort_key)}",
        "ownerKind": "message",
        "ownerId": owner_id,
        "ownerLineageId": owner_id,
        "ownerVersionNumber": None,
        "ownerVersionKey": None,
        "role": role,
        "sortKey": sort_key,
        "storagePath": f"newsroom/payloads/message/{_safe_id(owner_id)}/{_safe_id(role)}/{filename}",
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
    return {"modelName": "ModelAttachment", "action": "upload", "input": attachment, "body": body}


def _accepted_references(references: list[dict[str, Any]], corpus_key: str) -> list[dict[str, Any]]:
    corpus_id = f"knowledge-corpus-{_safe_id(corpus_key)}"
    accepted = []
    for ref in references:
        ref = _decode_record(ref)
        if ref.get("versionState") not in {None, "current"}:
            continue
        if str(ref.get("curationStatus") or "").lower() != "accepted":
            continue
        if corpus_key and ref.get("corpusId") not in {None, "", corpus_id, corpus_key}:
            continue
        accepted.append(ref)
    return accepted


def _terms(value: str) -> list[str]:
    seen = set()
    result = []
    for term in re.findall(r"[a-z0-9][a-z0-9-]{2,}", str(value or "").lower()):
        if term in STOPWORDS or term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result


def _matching_nodes(nodes: list[dict[str, Any]], topic: str, coverage_key: str) -> list[dict[str, Any]]:
    terms = _terms(topic)
    matches = []
    for node in nodes:
        haystack = " ".join([str(node.get("nodeKey") or ""), str(node.get("displayName") or ""), str(node.get("description") or "")]).lower()
        if coverage_key and node.get("nodeKey") == coverage_key:
            matches.append(node)
        elif terms and any(term in haystack for term in terms):
            matches.append(node)
    return matches


def _section_fit_scores(topic: str, refs: list[dict[str, Any]], sections: list[str]) -> dict[str, float]:
    text = " ".join([topic, *[str(ref.get("title") or "") for ref in refs]]).lower()
    scores = {}
    for section in sections:
        lens_terms = _terms(section_research_lens(section))
        if not lens_terms:
            scores[section] = 0.0
            continue
        score = sum(1 for term in lens_terms if term in text) / len(lens_terms)
        scores[section] = round(score, 3)
    return scores


def _why_now(topic: str, refs: list[dict[str, Any]], domains: list[str], since_days: int) -> str:
    if refs:
        return f"{len(refs)} accepted reference(s) in the last {since_days} day(s) mention {topic}; source domains include {', '.join(domains[:3]) or 'unknown'}."
    return f"{topic} is a candidate coverage gap; no accepted recent references matched the signal window."


def _coverage_gaps(topic: str, refs: list[dict[str, Any]]) -> list[str]:
    if not refs:
        return [f"No accepted recent references currently anchor {topic}."]
    if len({_domain(ref.get("sourceUri")) for ref in refs if _domain(ref.get("sourceUri"))}) < 2:
        return ["Source diversity needs review before publication."]
    return ["Confirm whether the signal is genuinely new or part of an existing desk thread."]


def _open_questions(topic: str, sections: list[str]) -> list[str]:
    if sections:
        return [f"What does {topic} mean for the {section} desk?" for section in sections[:3]]
    return [f"What is the most reportable angle on {topic}?"]


def _suggested_angles(topic: str, sections: list[str]) -> list[dict[str, str]]:
    angles = []
    for section in sections[:4]:
        angles.append({
            "sectionKey": section,
            "angle": f"{section_research_lens(section)}: {topic}",
        })
    return angles


def _recency_score(value: dt.datetime | None, now: dt.datetime, since_days: int) -> float:
    if not value:
        return 0.0
    age_days = max(0.0, (now - value).total_seconds() / 86400)
    return round(max(0.0, 1.0 - (age_days / max(since_days, 1))), 3)


def _reference_datetime(ref: dict[str, Any]) -> dt.datetime | None:
    for key in ("sourcePublishedAt", "sourceUpdatedAt", "retrievedAt", "importedAt", "updatedAt"):
        parsed = _parse_datetime(ref.get(key))
        if parsed:
            return parsed
    return None


def _domain(value: Any) -> str:
    parsed = urllib.parse.urlparse(str(value or ""))
    return parsed.netloc.lower().removeprefix("www.")


def _dedupe_by_id(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for record in records:
        key = record.get("id") or json.dumps(record, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for record in records:
        key = (record.get("modelName"), (record.get("input") or {}).get("id"), record.get("action"))
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _without_records(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if key != "records"}


def _relations_by_subject(relations: list[dict[str, Any]], predicate: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for relation in relations:
        if relation.get("relationState") != "current":
            continue
        if (relation.get("relationTypeKey") or relation.get("predicate")) != predicate:
            continue
        grouped.setdefault(relation.get("subjectId"), []).append(relation)
    return grouped


def _relations_by_assignment(relations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for relation in relations:
        if relation.get("relationState") != "current" or relation.get("subjectKind") != "assignment":
            continue
        grouped.setdefault(relation.get("subjectId"), []).append(relation)
    return grouped


def _assignment_graph_metadata(assignment: dict[str, Any], relations_by_assignment: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if assignment.get("importRunId"):
        metadata["coverageThemeRunId"] = assignment.get("importRunId")
        metadata["storyCycleRunId"] = assignment.get("importRunId")
        metadata["runId"] = assignment.get("importRunId")
    if assignment.get("sectionKey"):
        metadata["sectionKey"] = assignment.get("sectionKey")
    for relation in relations_by_assignment.get(assignment.get("id"), []):
        relation_type = relation.get("relationTypeKey") or relation.get("predicate")
        relation_metadata = _jsonish(relation.get("metadata")) or {}
        if relation_type == "planned_for_edition":
            metadata["editionId"] = relation.get("objectId")
            metadata["editionLineageId"] = relation.get("objectLineageId")
            if relation_metadata.get("editionDate"):
                metadata["editionDate"] = relation_metadata.get("editionDate")
        elif relation_type == "requests_work_on":
            metadata["coverageConceptId"] = relation.get("objectId")
            metadata["coverageConceptLineageId"] = relation.get("objectLineageId")
            if relation_metadata.get("coverageConceptKey"):
                metadata["coverageConceptKey"] = relation_metadata.get("coverageConceptKey")
            if relation_metadata.get("coverageConceptTitle"):
                metadata["coverageConceptTitle"] = relation_metadata.get("coverageConceptTitle")
        elif relation_type == "targets_section":
            metadata["sectionId"] = relation.get("objectId")
            metadata["sectionKey"] = relation_metadata.get("sectionKey") or relation.get("objectId")
            if relation_metadata.get("sectionTitle"):
                metadata["sectionTitle"] = relation_metadata.get("sectionTitle")
        elif relation_type == "targets_topic":
            metadata["focusCategoryLineageId"] = relation.get("objectLineageId")
            if relation_metadata.get("categoryKey"):
                metadata["categoryKey"] = relation_metadata.get("categoryKey")
                metadata["focusCategoryKey"] = relation_metadata.get("categoryKey")
        elif relation_type == "targets_lane":
            if relation_metadata.get("slotTarget"):
                metadata["slotTarget"] = relation_metadata.get("slotTarget")
            if relation_metadata.get("angleDiversity"):
                metadata["angleDiversity"] = relation_metadata.get("angleDiversity")
        elif relation_type == "targets_slot":
            slot_target = metadata.get("slotTarget") if isinstance(metadata.get("slotTarget"), dict) else {}
            metadata["slotTarget"] = {
                **slot_target,
                "slotId": relation.get("objectId"),
                "slotLineageId": relation.get("objectLineageId") or relation.get("objectId"),
                "slotRank": relation_metadata.get("slotRank"),
                "sectionKey": relation_metadata.get("sectionKey") or metadata.get("sectionKey"),
                "candidateRank": relation_metadata.get("candidateRank"),
                "dispatchCount": relation_metadata.get("dispatchCount"),
            }
        elif relation_type == "derived_from" and relation.get("objectKind") == "assignment":
            metadata["sourceResearchAssignmentId"] = relation.get("objectId")
    return metadata


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    metadata = _jsonish(record.get("metadata"))
    return metadata if isinstance(metadata, dict) else {}


def _decode_record(record: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(record or {})
    for key in ("metadata", "layoutPlan", "editorial"):
        if key in decoded:
            decoded[key] = _jsonish(decoded[key])
    return decoded


def _jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _clean_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def _prepare_input(model_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    prepared = _clean_none(input_payload)
    if model_name == "Assignment":
        for key in ("brief", "instructions", "metadata"):
            prepared.pop(key, None)
    if model_name == "Message":
        prepared.setdefault("responseTarget", "none")
        prepared.setdefault("responseStatus", "COMPLETED")
    for key in ("metadata", "layoutPlan", "editorial"):
        if key in prepared and not isinstance(prepared[key], str):
            prepared[key] = json.dumps(prepared[key], sort_keys=True)
    return prepared


def _list_records(model_name: str) -> list[dict[str, Any]]:
    field_name, fields = LIST_FIELDS[model_name]
    query = f"""
query List{model_name}s($limit: Int, $nextToken: String) {{
  {field_name}(limit: $limit, nextToken: $nextToken) {{
    items {{ {fields} }}
    nextToken
  }}
}}
"""
    records: list[dict[str, Any]] = []
    next_token = None
    while True:
        payload = _graphql(query, {"limit": 1000, "nextToken": next_token})
        connection = payload.get(field_name) or {}
        records.extend(_decode_record(item) for item in connection.get("items") or [] if item)
        next_token = connection.get("nextToken")
        if not next_token:
            return records


def _list_assignments_by_import_run(run_id: str) -> list[dict[str, Any]]:
    query = f"""
query ListAssignmentsByImportRun($importRunId: ID!, $limit: Int, $nextToken: String) {{
  listAssignmentsByImportRunAndCreatedAt(importRunId: $importRunId, limit: $limit, nextToken: $nextToken) {{
    items {{ {ASSIGNMENT_FIELDS} }}
    nextToken
  }}
}}
"""
    return _list_connection(query, {"importRunId": run_id}, "listAssignmentsByImportRunAndCreatedAt")


def _list_relations_by_subject(kind: str, lineage_id: str) -> list[dict[str, Any]]:
    query = f"""
query ListRelationsBySubject($subjectStateKey: String!, $limit: Int, $nextToken: String) {{
  listSemanticRelationsBySubjectState(subjectStateKey: $subjectStateKey, limit: $limit, nextToken: $nextToken) {{
    items {{ {SEMANTIC_RELATION_FIELDS} }}
    nextToken
  }}
}}
"""
    return _list_connection(query, {"subjectStateKey": semantic_state_key(kind, lineage_id)}, "listSemanticRelationsBySubjectState")


def _list_assignment_events(assignment_id: str) -> list[dict[str, Any]]:
    query = f"""
query ListAssignmentEventsByAssignment($assignmentId: ID!, $limit: Int, $nextToken: String) {{
  listAssignmentEventsByAssignmentAndCreatedAt(assignmentId: $assignmentId, limit: $limit, nextToken: $nextToken) {{
    items {{ {ASSIGNMENT_EVENT_FIELDS} }}
    nextToken
  }}
}}
"""
    return _list_connection(query, {"assignmentId": assignment_id}, "listAssignmentEventsByAssignmentAndCreatedAt")


def _list_model_attachments_by_owner(owner_id: str) -> list[dict[str, Any]]:
    query = f"""
query ListModelAttachmentsByOwner($ownerId: ID!, $limit: Int, $nextToken: String) {{
  listModelAttachmentsByOwnerRoleAndSortKey(ownerId: $ownerId, limit: $limit, nextToken: $nextToken) {{
    items {{ {MODEL_ATTACHMENT_FIELDS} }}
    nextToken
  }}
}}
"""
    return _list_connection(query, {"ownerId": owner_id}, "listModelAttachmentsByOwnerRoleAndSortKey")


def _list_connection(query: str, variables: dict[str, Any], field_name: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    next_token = None
    while True:
        payload = _graphql(query, {**variables, "limit": 1000, "nextToken": next_token})
        connection = payload.get(field_name) or {}
        records.extend(_decode_record(item) for item in connection.get("items") or [] if item)
        next_token = connection.get("nextToken")
        if not next_token:
            return records


def _get_record(model_name: str, record_id: Any) -> dict[str, Any] | None:
    if not record_id:
        return None
    field_name, fields = GET_FIELDS[model_name]
    query = f"""
query Get{model_name}($id: ID!) {{
  {field_name}(id: $id) {{ {fields} }}
}}
"""
    record = _graphql(query, {"id": record_id}).get(field_name)
    return _decode_record(record) if record else None


def _record_exists(model_name: str, record_id: str) -> bool:
    if not record_id:
        return False
    return bool(_get_record(model_name, record_id))


def _create_record(model_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    query = f"""
mutation Create{model_name}($input: Create{model_name}Input!) {{
  create{model_name}(input: $input) {{ id }}
}}
"""
    return _graphql(query, {"input": _prepare_input(model_name, input_payload)})


def _update_record(model_name: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    query = f"""
mutation Update{model_name}($input: Update{model_name}Input!) {{
  update{model_name}(input: $input) {{ id }}
}}
"""
    return _graphql(query, {"input": _prepare_input(model_name, input_payload)})


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
    slot = (_graphql(CREATE_MODEL_ATTACHMENT_UPLOAD_MUTATION, upload_args).get("createModelAttachmentUpload") or {})
    upload_url = slot.get("uploadUrl")
    if not upload_url:
        raise RuntimeError("createModelAttachmentUpload did not return uploadUrl")
    headers = _jsonish(slot.get("requiredHeaders")) or {}
    request = urllib.request.Request(upload_url, data=body_bytes, headers={str(key): str(value) for key, value in headers.items()}, method="PUT")
    with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310 - configured signed URL
        if response.status >= 400:
            raise RuntimeError(f"ModelAttachment upload failed with HTTP {response.status}")
    _graphql(COMPLETE_MODEL_ATTACHMENT_UPLOAD_MUTATION, {"uploadId": slot["uploadId"], **upload_args})


def _download_attachment_json(attachment_id: str) -> dict[str, Any]:
    slot = (_graphql(CREATE_MODEL_ATTACHMENT_DOWNLOAD_MUTATION, {"attachmentId": attachment_id}).get("createModelAttachmentDownload") or {})
    download_url = slot.get("downloadUrl")
    if not download_url:
        return {}
    request = urllib.request.Request(download_url, method="GET")
    with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310 - configured signed URL
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def _graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    from papyrus_content.graphql_http import execute_graphql

    return execute_graphql(query, variables, timeout=90, allow_knowledge_fallback=True)


def _resolve_section_keys(sections: list[str]) -> list[str]:
    source = sections or DEFAULT_SECTIONS
    result = []
    for section in source:
        key = str(section or "").strip()
        if not key:
            continue
        result.append(SECTION_ALIASES.get(key, key))
    return result


def section_research_lens(section_key: str) -> str:
    return SECTION_RESEARCH_LENSES.get(section_key, f"section-specific evidence, doctrine, and recent desk memory for {section_key}")


def semantic_state_key(kind: str, lineage_id: str) -> str:
    return f"{kind}#{lineage_id}#current"


def semantic_version_key(kind: str, object_id: str) -> str:
    return f"{kind}#{object_id}"


def _normalize_section_type(value: Any) -> str:
    text = str(value or "canonical").strip().lower()
    return "floating" if text == "rotating" else text


def _normalize_relation_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _safe_id(value: Any) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()))[:140] or _hash_short(value)


def _hash_stable(value: Any) -> str:
    return hashlib.sha256((value if isinstance(value, str) else json.dumps(value, sort_keys=True)).encode("utf-8")).hexdigest()


def _hash_short(value: Any) -> str:
    return _hash_stable(value)[:16]


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _date_from_iso(value: str) -> str:
    parsed = _parse_datetime(value)
    return parsed.date().isoformat() if parsed else dt.date.today().isoformat()


def _timestamp_for_path(value: str) -> str:
    return re.sub(r"[^0-9TZ]", "", str(value)).removesuffix("Z") + "Z"


def _parse_datetime(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def _state_key(model_name: str) -> str:
    irregular = {
        "Category": "categories",
        "NewsroomSection": "newsroomSections",
        "AssignmentEvent": "assignmentEvents",
        "SemanticNode": "semanticNodes",
        "SemanticRelation": "semanticRelations",
        "ModelAttachment": "modelAttachments",
        "EditionItem": "editionItems",
        "EditionSlot": "editionSlots",
    }
    if model_name in irregular:
        return irregular[model_name]
    key = model_name[:1].lower() + model_name[1:]
    return f"{key}s"
