"""Single-tool Tactus runtime for Papyrus newsroom agents."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import re
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from . import newsroom, reference_curation_signals
from papyrus_knowledge_query.engine import run_knowledge_query
from papyrus_knowledge_query.services import build_environment_services


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]

    items = None
    try:
        items = list(value.items())
    except Exception:
        items = None
    if items is not None:
        converted = {key: _jsonable(item) for key, item in items}
        keys = list(converted.keys())
        if keys and all(isinstance(key, int) for key in keys):
            ordered = sorted(keys)
            if ordered == list(range(1, len(ordered) + 1)):
                return [converted[index] for index in ordered]
        return {str(key): item for key, item in converted.items()}

    return str(value)


def _args(args: Any = None) -> dict[str, Any]:
    if args is None:
        return {}
    converted = _jsonable(args)
    if converted is None:
        return {}
    if not isinstance(converted, dict):
        raise ValueError("Papyrus runtime APIs require table/object arguments")
    return converted


def _structured_error(
    code: str,
    message: str,
    exc: BaseException | None = None,
    *,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if exc is not None:
        payload["type"] = exc.__class__.__name__
    if details:
        payload["details"] = _jsonable(details)
    return payload


_JS_SHAPE_API_CALL_RE = re.compile(
    r"\b(?:api_list|docs_list|docs_get|Assignment\.[A-Za-z_]\w*|papyrus\.[A-Za-z_][\w\.]*)\s*\(",
    re.IGNORECASE,
)
_EXECUTE_TACTUS_CONTRACT_VERSION = "execute_tactus_snippet_contract_v1"


def _normalize_tactus_whitespace(value: str) -> str:
    return " ".join(str(value or "").split())


def _normalize_tactus_identifier(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _collapse_newlines_in_lua_double_quoted_strings(snippet: str) -> str:
    out: list[str] = []
    index = 0
    length = len(snippet)
    while index < length:
        char = snippet[index]
        if char != '"':
            out.append(char)
            index += 1
            continue
        out.append('"')
        index += 1
        while index < length:
            current = snippet[index]
            if current == "\\" and index + 1 < length:
                out.append(current)
                out.append(snippet[index + 1])
                index += 2
                continue
            if current == '"':
                out.append('"')
                index += 1
                break
            if current in "\r\n":
                out.append(" ")
                while index < length and snippet[index] in "\r\n":
                    index += 1
                continue
            out.append(current)
            index += 1
    return "".join(out)


def _normalize_tactus_snippet(tactus: str) -> str:
    normalized = tactus.replace("\r\n", "\n").replace("\r", "\n")
    return _collapse_newlines_in_lua_double_quoted_strings(normalized)


def _unsupported_snippet_error(tactus: str) -> dict[str, Any] | None:
    snippet = tactus.strip()
    if not snippet:
        return None
    matched = _JS_SHAPE_API_CALL_RE.search(snippet)
    if not matched:
        return None
    excerpt = snippet.replace("\n", " ")
    if len(excerpt) > 240:
        excerpt = excerpt[:240] + "..."
    return _structured_error(
        "unsupported_snippet",
        "Snippet rejected: execute_tactus expects Tactus/Lua table-call syntax. "
        "You used JS/object-call syntax with parentheses.",
        retryable=True,
        details={
            "contractVersion": _EXECUTE_TACTUS_CONTRACT_VERSION,
            "rejectedSnippetExcerpt": excerpt,
            "acceptedExamples": [
                "return docs_get{ id = \"resources.Assignment\" }",
                "return Assignment.create{ type = \"research\", title = \"Live smoke assignment\", apply = true }",
                "return Reference.create{ url = \"https://example.com/article\", apply = true }",
            ],
            "guidance": {
                "do": [
                    "Use raw Lua/Tactus snippets in the tactus string.",
                    "Use table arguments with braces, e.g. docs_get{ id = \"...\" }.",
                    "Prefix the call with return when you want the tool value.",
                ],
                "dont": [
                    "Do not use JS/object-call syntax like docs_get({ id: \"...\" }).",
                    "Do not use markdown fences around the snippet.",
                    "Do not JSON-escape normal Lua quotes.",
                ],
            },
        },
    )


def _response_envelope(
    *,
    ok: bool,
    value: Any,
    trace_id: str,
    started_at: float,
    api_calls: list[str],
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_value = _normalize_known_empty_arrays(_jsonable(value))
    return {
        "ok": ok,
        "value": normalized_value,
        "error": error,
        "cost": {
            "usd": 0.0,
            "duration_ms": int(round((time.monotonic() - started_at) * 1000)),
            "tool_calls": len(api_calls),
        },
        "trace_id": trace_id,
        "partial": False,
        "api_calls": list(api_calls),
    }


_ARRAY_SHAPED_KEYS = {
    "contextSources",
    "coverageGaps",
    "evidenceItemIds",
    "openQuestions",
    "proposedReferences",
    "queries",
    "researchNotes",
    "rubricAssessments",
    "sourceSnapshots",
    "comparisonFindings",
    "acceptedReferenceIds",
    "confirmedFacts",
    "recentDeskMemoryUsed",
    "riskFlags",
    "sourceTrail",
    "sourceDiversityNotes",
    "verificationNeeds",
    "acceptedEvidenceIds",
    "knowledgeQueries",
    "papyrusUrisInspected",
    "unresolvedGaps",
    "webSearches",
    "context_sources",
    "coverage_gaps",
    "evidence_item_ids",
    "open_questions",
    "proposed_references",
    "research_notes",
    "rubric_assessments",
    "source_snapshots",
    "comparison_findings",
    "accepted_reference_ids",
    "confirmed_facts",
    "recent_desk_memory_used",
    "risk_flags",
    "source_trail",
    "source_diversity_notes",
    "verification_needs",
    "accepted_evidence_ids",
    "knowledge_queries",
    "papyrus_uris_inspected",
    "unresolved_gaps",
    "web_searches",
}


def _normalize_known_empty_arrays(value: Any, key: str | None = None) -> Any:
    if key in _ARRAY_SHAPED_KEYS and value == {}:
        return []
    if isinstance(value, dict):
        return {entry_key: _normalize_known_empty_arrays(entry_value, entry_key) for entry_key, entry_value in value.items()}
    if isinstance(value, list):
        return [_normalize_known_empty_arrays(item, key) for item in value]
    return value


class _Namespace:
    def __init__(
        self,
        dispatcher: Callable[[str, str, Any], Any],
        name: str,
        methods: set[str],
    ) -> None:
        self._dispatcher = dispatcher
        self._name = name
        for method_name in methods:
            setattr(self, method_name, self._make_call(method_name))

    def _make_call(self, method_name: str) -> Callable[[Any], Any]:
        def call(args: Any = None) -> Any:
            return self._dispatcher(self._name, method_name, args)

        return call


API_METHODS: dict[tuple[str, str], Callable[[dict[str, Any]], Any]] = {
    ("edition", "get"): lambda args: newsroom.papyrus_get_edition(args.get("id") or args.get("edition_id")),
    ("edition", "items"): lambda args: newsroom.papyrus_list_edition_items(
        args.get("id") or args.get("edition_id"),
        limit=args.get("limit", 100),
    ),
    ("edition_slot", "get"): lambda args: newsroom.papyrus_get_edition_slot(args.get("id") or args.get("slot_id")),
    ("edition_slot", "list"): lambda args: newsroom.papyrus_list_edition_slots(
        args.get("edition_id") or args.get("editionId"),
        section_key=args.get("section_key") or args.get("sectionKey") or "",
        limit=args.get("limit", 250),
    ),
    ("edition_slot", "update_status"): lambda args: newsroom.papyrus_update_edition_slot_status(
        slot_id=args.get("slot_id") or args.get("slotId") or args.get("id"),
        status=args.get("status") or "",
        selected_assignment_id=args.get("selected_assignment_id") or args.get("selectedAssignmentId") or "",
        actor_label=args.get("actor_label") or args.get("actorLabel") or "",
        note=args.get("note") or "",
    ),
    ("item", "get"): lambda args: newsroom.papyrus_get_item(args.get("id") or args.get("item_id")),
    ("item", "info"): lambda args: newsroom.papyrus_get_item(args.get("id") or args.get("item_id")),
    ("article", "recent_published"): lambda args: newsroom.papyrus_list_recent_published_articles(
        recent_days=args.get("recent_days") or args.get("recentDays") or 30,
        limit=args.get("limit", 25),
    ),
    ("assignment", "get"): lambda args: newsroom.papyrus_get_assignment(args.get("id") or args.get("assignment_id")),
    ("assignment", "context"): lambda args: newsroom.papyrus_get_assignment_context(
        args.get("id") or args.get("assignment_id")
    ),
    ("assignment", "agent_context"): lambda args: newsroom.papyrus_build_assignment_agent_context(
        assignment_id=args.get("id") or args.get("assignment_id"),
        context_profile=args.get("context_profile") or args.get("contextProfile") or "",
        max_tokens=args.get("max_tokens") or args.get("maxTokens") or 0,
        recent_days=args.get("recent_days") or args.get("recentDays") or 30,
    ),
    ("assignment", "context_to_item"): lambda args: newsroom.papyrus_assignment_context_to_item(
        assignment_context=args.get("assignment_context") or args.get("assignmentContext"),
        assignment_context_json=args.get("assignment_context_json") or args.get("assignmentContextJson") or "",
    ),
    ("track", "list"): lambda args: newsroom.papyrus_list_research_tracks(),
    ("track", "get"): lambda args: newsroom.papyrus_get_research_track(args.get("key") or args.get("track_key")),
    ("reference", "get"): lambda args: newsroom.papyrus_get_reference(args.get("id") or args.get("reference_id")),
    ("reference", "curation_review"): lambda args: newsroom.papyrus_reference_curation_review(
        reference_id=args.get("reference_id") or args.get("referenceId") or args.get("id"),
        action=args.get("action") or "",
        actor_label=args.get("actor_label") or args.get("actorLabel") or "",
        note=args.get("note") or "",
        reason_code=args.get("reason_code") or args.get("reasonCode") or "",
    ),
    ("reference", "list"): lambda args: reference_curation_signals.reference_list(
        corpus_key=args.get("corpus_key") or args.get("corpusKey") or "AI-ML-research",
        limit=args.get("limit") or 25,
        status=args.get("status") or "",
        order=args.get("order") or "newest",
        scan_limit=args.get("scan_limit") or args.get("scanLimit") or 1000,
    ),
    ("reference", "insight_create"): lambda args: newsroom.papyrus_reference_insight_create(
        reference_id=args.get("reference_id") or args.get("referenceId") or args.get("id"),
        summary=args.get("summary") or "",
        body=args.get("body") or "",
        actor_label=args.get("actor_label") or args.get("actorLabel") or "",
    ),
    ("reference", "insight_list"): lambda args: newsroom.papyrus_reference_insight_list(
        args.get("reference_lineage_id") or args.get("referenceLineageId") or args.get("lineage_id") or args.get("lineageId") or ""
    ),
    ("reference", "move_corpus"): lambda args: newsroom.papyrus_reference_move_corpus(
        reference_id=args.get("reference_id") or args.get("referenceId") or args.get("id"),
        corpus_id=args.get("corpus_id") or args.get("corpusId") or "",
        actor_label=args.get("actor_label") or args.get("actorLabel") or "",
        note=args.get("note") or "",
    ),
    ("reference", "curation_start"): lambda args: newsroom.papyrus_reference_curation_start(
        reference_id=args.get("reference_id") or args.get("referenceId") or args.get("id"),
        actor_label=args.get("actor_label") or args.get("actorLabel") or "",
        curation_policy=args.get("curation_policy") or args.get("curationPolicy"),
    ),
    ("reference", "curation_status"): lambda args: newsroom.papyrus_reference_curation_status(
        assignment_id=args.get("assignment_id") or args.get("assignmentId") or args.get("id"),
    ),
    ("reference", "web_search"): lambda args: reference_curation_signals.reference_web_search(
        query=args.get("query") or args.get("q") or "",
        max_results=args.get("max_results") or args.get("maxResults") or args.get("limit") or 20,
        model=args.get("model") or "gpt-5.4-mini",
        return_token_budget=args.get("return_token_budget") or args.get("returnTokenBudget") or "default",
        provider=args.get("provider") or args.get("web_search_provider") or args.get("webSearchProvider"),
    ),
    ("reference", "doi_backfill_plan"): lambda args: newsroom.papyrus_doi_backfill_plan(
        corpus_key=args.get("corpus_key") or args.get("corpusKey") or "AI-ML-research",
        max_count=args.get("max_count") or args.get("maxCount") or 0,
        use_llm=bool(args.get("use_llm") or args.get("useLlm") or False),
        llm_model=args.get("llm_model") or args.get("llmModel") or "",
        llm_reasoning_effort=args.get("llm_reasoning_effort") or args.get("llmReasoningEffort") or "",
        config_path=args.get("config_path") or args.get("configPath") or "",
    ),
    ("reference", "doi_backfill_run"): lambda args: newsroom.papyrus_doi_backfill_run(
        corpus_key=args.get("corpus_key") or args.get("corpusKey") or "AI-ML-research",
        max_count=args.get("max_count") or args.get("maxCount") or 0,
        use_llm=bool(args.get("use_llm") or args.get("useLlm") or False),
        llm_model=args.get("llm_model") or args.get("llmModel") or "",
        llm_reasoning_effort=args.get("llm_reasoning_effort") or args.get("llmReasoningEffort") or "",
        config_path=args.get("config_path") or args.get("configPath") or "",
    ),
    ("reference", "doi_backfill_manifest"): lambda args: newsroom.papyrus_doi_backfill_manifest(
        run_id=args.get("run_id") or args.get("runId") or "",
        manifest_path=args.get("manifest_path") or args.get("manifestPath") or "",
    ),
    ("reference", "fetch_url_text"): lambda args: newsroom.papyrus_reference_fetch_url_text(
        reference_id=args.get("reference_id") or args.get("referenceId") or args.get("id") or "",
        external_item_id=args.get("external_item_id") or args.get("externalItemId") or "",
        corpus_key=args.get("corpus_key") or args.get("corpusKey") or "AI-ML-research",
        apply=not (args.get("apply") is False),
        force=bool(args.get("force") or False),
        config_path=args.get("config_path") or args.get("configPath") or "",
        max_count=args.get("max_count") or args.get("maxCount") or 0,
    ),
    ("reference", "filter_extracted_text"): lambda args: newsroom.papyrus_reference_filter_extracted_text(
        reference_id=args.get("reference_id") or args.get("referenceId") or args.get("id") or "",
        external_item_id=args.get("external_item_id") or args.get("externalItemId") or "",
        corpus_key=args.get("corpus_key") or args.get("corpusKey") or "AI-ML-research",
        apply=not (args.get("apply") is False),
        force=not (args.get("force") is False),
        config_path=args.get("config_path") or args.get("configPath") or "",
        max_count=args.get("max_count") or args.get("maxCount") or 0,
        model=args.get("model") or "gpt-5.4-nano",
        metadata_from_text=not (args.get("metadata_from_text") is False or args.get("metadataFromText") is False),
        metadata_model=args.get("metadata_model") or args.get("metadataModel") or "gpt-5.4-nano",
    ),
    ("reference", "generate_metadata_from_text"): lambda args: newsroom.papyrus_reference_generate_metadata_from_text(
        reference_id=args.get("reference_id") or args.get("referenceId") or args.get("id") or "",
        external_item_id=args.get("external_item_id") or args.get("externalItemId") or "",
        corpus_key=args.get("corpus_key") or args.get("corpusKey") or "AI-ML-research",
        apply=not (args.get("apply") is False),
        config_path=args.get("config_path") or args.get("configPath") or "",
        max_count=args.get("max_count") or args.get("maxCount") or 0,
        model=args.get("model") or "gpt-5.4-nano",
    ),
    ("reference", "quality_get"): lambda args: reference_curation_signals.reference_quality_get(
        reference_id=args.get("reference") or args.get("reference_id") or args.get("referenceId") or args.get("id"),
    ),
    ("reference", "quality_rate"): lambda args: newsroom.papyrus_reference_quality_rate(
        reference_id=args.get("reference") or args.get("reference_id") or args.get("referenceId") or args.get("id"),
        rating=args.get("rating") or 0,
        note=args.get("note") or "",
        actor_label=args.get("actor_label") or args.get("actorLabel") or "papyrus-tactus",
    ),
    ("reference", "quality_assess"): lambda args: reference_curation_signals.reference_quality_assess(
        reference_id=args.get("reference") or args.get("reference_id") or args.get("referenceId") or args.get("id"),
        model=args.get("model") or "gpt-5.4-mini",
        apply=bool(args.get("apply") or False),
        refresh=bool(args.get("refresh") or False),
        persist_local_metadata=not (args.get("persist_local_metadata") is False or args.get("persistLocalMetadata") is False),
        source_text=args.get("source_text") or args.get("sourceText") or "",
        source_text_file=args.get("source_text_file") or args.get("sourceTextFile") or "",
    ),
    ("reference", "summarize"): lambda args: reference_curation_signals.reference_summarize(
        reference_id=args.get("reference") or args.get("reference_id") or args.get("referenceId") or args.get("id"),
        max_tokens=args.get("max_tokens") or args.get("maxTokens"),
        summary_text=args.get("summary_text") or args.get("summaryText") or "",
        source_text=args.get("source_text") or args.get("sourceText") or "",
        source_text_file=args.get("source_text_file") or args.get("sourceTextFile") or "",
        model=args.get("model") or "gpt-5.4-mini",
        apply=bool(args.get("apply") or False),
        refresh=bool(args.get("refresh") or False),
    ),
    ("reference", "summaries"): lambda args: reference_curation_signals.reference_summaries(
        reference_id=args.get("reference") or args.get("reference_id") or args.get("referenceId") or args.get("id"),
        max_tokens=args.get("max_tokens") or args.get("maxTokens"),
    ),
    ("knowledge", "query"): lambda args: run_knowledge_query(_knowledge_query_input(args), build_environment_services()),
    ("papyrus", "resolve_uri"): lambda args: newsroom.papyrus_resolve_uri(args.get("uri") or args.get("objectUri")),
    ("semantic", "object"): lambda args: newsroom.papyrus_get_semantic_object(
        kind=args.get("kind"),
        object_id=args.get("id") or args.get("object_id"),
    ),
    ("semantic", "search_nodes"): lambda args: newsroom.papyrus_search_semantic_nodes(
        query=args.get("query") or args.get("q") or "",
        limit=args.get("limit", 10),
        category_set_id=args.get("category_set_id") or args.get("categorySetId") or "",
    ),
    ("biblicus", "steering_artifacts"): lambda args: newsroom.biblicus_steering_artifacts(
        corpus_key=args.get("corpus_key") or args.get("corpusKey"),
        config_path=args.get("config_path") or args.get("configPath") or "",
    ),
    ("biblicus", "topic_context"): lambda args: newsroom.biblicus_topic_context(**args),
    ("biblicus", "topic_trends"): lambda args: newsroom.biblicus_topic_trends(**args),
    ("biblicus", "query"): lambda args: newsroom.biblicus_query(**args),
    ("plan", "assignment_record"): lambda args: newsroom.build_assignment_record_plan(**args),
    ("plan", "assignment_dispatch"): lambda args: newsroom.build_assignment_dispatch_plan(**args),
    ("plan", "research_update"): lambda args: newsroom.build_research_update_plan(**args),
    ("plan", "assignment_research_packet"): lambda args: newsroom.build_assignment_research_packet_plan(**args),
    ("plan", "assignment_reporting_context_packet"): lambda args: newsroom.build_assignment_reporting_context_packet_plan(**args),
    ("plan", "draft_update"): lambda args: newsroom.build_draft_update_plan(**args),
    ("email_submission", "process"): lambda args: newsroom.papyrus_email_submission_process(
        message_id=args.get("message_id") or args.get("messageId") or args.get("id") or "",
        corpus_key=args.get("corpus_key") or args.get("corpusKey") or "AI-ML-research",
        apply=bool(args.get("apply", True)),
    ),
}


def _reference_list_resource(args: dict[str, Any]) -> Any:
    result = reference_curation_signals.reference_list(
        corpus_key=args.get("corpusKey") or args.get("corpus_key") or "AI-ML-research",
        limit=args.get("limit") or 25,
        status=args.get("status") or "",
        order=args.get("order") or "newest",
        scan_limit=args.get("scanLimit") or args.get("scan_limit") or 1000,
    )

    items = list(result.get("items") or [])
    lines: list[str] = []
    if items:
        lines.append("## Recent References")
        for index, item in enumerate(items, 1):
            title = str(item.get("title") or "(untitled reference)").strip()
            reference_id = str(item.get("id") or "").strip()
            corpus_id = str(item.get("corpusId") or "").strip()
            status = str(item.get("curationStatus") or "").strip()
            imported_at = str(item.get("importedAt") or "").strip()
            updated_at = str(item.get("updatedAt") or item.get("createdAt") or "").strip()
            published_at = str(item.get("sourcePublishedAt") or "").strip()
            lines.append(f"{index}. **{title}**")
            if reference_id:
                lines.append(f"   - id: `{reference_id}`")
            if imported_at:
                lines.append(f"   - imported: `{imported_at}`")
            if published_at:
                lines.append(f"   - published: `{published_at}`")
            if updated_at:
                lines.append(f"   - updated: `{updated_at}`")
            if corpus_id:
                lines.append(f"   - corpus: `{corpus_id}`")
            if status:
                lines.append(f"   - status: `{status}`")
    else:
        lines.append("No references found for the current filter.")
    return "\n".join(lines)


RESOURCE_METHODS: dict[tuple[str, str], Callable[[dict[str, Any]], Any]] = {
    ("Assignment", "create"): lambda args: newsroom.papyrus_assignment_create(args),
    ("Assignment", "get"): lambda args: newsroom.papyrus_get_assignment(args.get("id") or args.get("assignmentId") or args.get("assignment_id")),
    ("Assignment", "list"): lambda args: newsroom.papyrus_list_assignments(
        limit=args.get("limit", 25),
        status=args.get("status") or "",
        type=args.get("type") or "",
        section_key=args.get("sectionKey") or args.get("section_key") or "",
        import_run_id=args.get("importRunId") or args.get("import_run_id") or "",
    ),
    ("Assignment", "update"): lambda args: newsroom.papyrus_assignment_update(args),
    ("EditionSlot", "get"): lambda args: newsroom.papyrus_get_edition_slot(args.get("id") or args.get("slotId") or args.get("slot_id")),
    ("EditionSlot", "list"): lambda args: newsroom.papyrus_list_edition_slots(
        args.get("editionId") or args.get("edition_id"),
        section_key=args.get("sectionKey") or args.get("section_key") or "",
        limit=args.get("limit", 250),
    ),
    ("EditionSlot", "update"): lambda args: newsroom.papyrus_update_edition_slot_status(
        slot_id=args.get("id") or args.get("slotId") or args.get("slot_id"),
        status=args.get("status") or "",
        selected_assignment_id=args.get("selectedAssignmentId") or args.get("selected_assignment_id") or "",
        actor_label=args.get("actorLabel") or args.get("actor_label") or "",
        note=args.get("note") or "",
    ),
    ("MessageThread", "get"): lambda args: newsroom.papyrus_get_message_thread(args.get("id") or args.get("threadId") or args.get("thread_id")),
    ("MessageThread", "list"): lambda args: newsroom.papyrus_list_forum_threads(
        edition_id=args.get("editionId") or args.get("edition_id"),
        section_id=args.get("sectionId") or args.get("section_id") or "",
        section_key=args.get("sectionKey") or args.get("section_key") or "",
        include_messages=bool(args.get("includeMessages") or args.get("include_messages")),
        status=args.get("status") or "active",
        limit=args.get("limit", 200),
    ),
    ("MessageThread", "create"): lambda args: (
        newsroom.papyrus_create_section_forum_thread(
            edition_id=args.get("editionId") or args.get("edition_id"),
            section_id=args.get("sectionId") or args.get("section_id") or args.get("sectionKey") or args.get("section_key"),
            section_key=args.get("sectionKey") or args.get("section_key") or "",
            section_title=args.get("sectionTitle") or args.get("section_title") or "",
            title=args.get("title") or "",
            summary=args.get("summary") or "",
            actor_label=args.get("actorLabel") or args.get("actor_label") or "",
            metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else None,
        )
        if (args.get("sectionId") or args.get("section_id") or args.get("sectionKey") or args.get("section_key"))
        else newsroom.papyrus_ensure_edition_forum_thread(
            edition_id=args.get("editionId") or args.get("edition_id"),
            title=args.get("title") or "",
            summary=args.get("summary") or "",
            actor_label=args.get("actorLabel") or args.get("actor_label") or "",
            metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else None,
        )
    ),
    ("MessageThread", "append"): lambda args: newsroom.papyrus_append_forum_message(
        thread_id=args.get("id") or args.get("threadId") or args.get("thread_id"),
        summary=args.get("summary") or "",
        content=args.get("content") or "",
        role=args.get("role") or "editor",
        actor_label=args.get("actorLabel") or args.get("actor_label") or "",
        parent_message_id=args.get("parentMessageId") or args.get("parent_message_id") or "",
        metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else None,
    ),
    ("Reference", "create"): lambda args: newsroom.papyrus_reference_create(args),
    ("Reference", "get"): lambda args: newsroom.papyrus_get_reference(args.get("id") or args.get("referenceId") or args.get("reference_id")),
    ("Reference", "list"): _reference_list_resource,
}


RESOURCE_API_SCHEMA: dict[str, Any] = {
    "resources": {
        "Assignment": {
            "verbs": ["create", "get", "list", "update"],
            "description": "Private newsroom work records for research, reporting, copywriting, analysis, and future assignment types.",
            "create": {
                "supportedTypes": ["research"],
                "required": ["type", "title"],
                "optional": [
                    "summary",
                    "sectionKey",
                    "instructions",
                    "corpusKey",
                    "researchMode",
                    "priority",
                    "status",
                    "importRunId",
                    "actorLabel",
                    "apply",
                ],
                "writes": ["Assignment", "AssignmentEvent"],
                "applyDefault": False,
            },
            "get": {"required": ["id"]},
            "list": {"optional": ["limit", "status", "type", "sectionKey", "importRunId"]},
            "update": {
                "required": ["id", "status"],
                "optional": ["note", "actorLabel", "apply"],
                "writes": ["Assignment", "AssignmentEvent"],
                "applyDefault": True,
            },
        },
        "AssignmentEvent": {"verbs": ["get", "list"], "description": "Audit events for Assignment lifecycle changes. Writes happen through Assignment verbs in v1."},
        "Message": {"verbs": ["get", "list"], "description": "Private work-product and console-message records."},
        "MessageThread": {"verbs": ["get", "list", "create", "append"], "description": "Edition/section forum coordination threads and replies."},
        "Reference": {
            "verbs": ["create", "get", "list"],
            "description": "Knowledge-base source material prospects and accepted references.",
            "create": {
                "required": ["url"],
                "optional": [
                    "title",
                    "corpusKey",
                    "ingestionRationale",
                    "actorLabel",
                    "apply",
                    "enrich",
                    "skipExisting",
                    "createCurationAssignment",
                    "note",
                ],
                "writes": ["Reference", "KnowledgeImportRun", "Assignment", "Message"],
                "applyDefault": False,
            },
        },
        "Item": {"verbs": ["get", "list"], "description": "Reader-facing publication items. Assignments are not Items."},
        "Edition": {"verbs": ["get", "list"], "description": "Dated private or published edition records."},
        "EditionSlot": {"verbs": ["get", "list", "update"], "description": "Edition planning slots that bind reporting candidates and selected outcomes."},
        "NewsroomSection": {"verbs": ["get", "list"], "description": "Operational desk sections with mission, policies, guidance, and budgets."},
    },
    "docs": {"verbs": ["list", "get"], "namespaces": ["mcp", "resources", "newsroom"]},
}


def _knowledge_query_input(args: dict[str, Any]) -> dict[str, Any]:
    payload = args.get("input")
    if isinstance(payload, dict):
        return payload

    scope = dict(args.get("scope")) if isinstance(args.get("scope"), dict) else {}
    output = dict(args.get("output")) if isinstance(args.get("output"), dict) else {}
    if args.get("depth") is not None:
        scope["depth"] = args.get("depth")
    top_k = args.get("top_k") if args.get("top_k") is not None else args.get("topK")
    if top_k is not None:
        scope["topK"] = top_k
    max_tokens = args.get("max_tokens") if args.get("max_tokens") is not None else args.get("maxTokens")
    if max_tokens is not None:
        output["maxTokens"] = max_tokens
    if args.get("format") and not output.get("format"):
        output["format"] = args.get("format")

    anchors = args.get("anchors") or []
    if args.get("uri") or args.get("objectUri"):
        anchors = [{"uri": args.get("uri") or args.get("objectUri")}]

    return {
        "anchors": anchors,
        "semanticQuery": args.get("query") or args.get("semantic_query") or args.get("semanticQuery") or "",
        "scope": scope,
        "profile": args.get("profile") or "researcher",
        "output": output or {"format": "structured"},
    }


DOCS: dict[str, dict[str, Any]] = {
    "mcp.execute-tactus-overview": {
        "id": "mcp.execute-tactus-overview",
        "title": "execute_tactus Overview",
        "summary": "How Papyrus agents use one Tactus execution tool.",
        "namespace": "mcp",
        "status": "stable",
        "tags": ["mcp", "tactus", "newsroom"],
        "content": (
            "Papyrus agents should call execute_tactus with a short Tactus snippet. "
            "The canonical write surface is resource-oriented: GraphQL-model-style "
            "resources such as Assignment expose consistent verbs such as create, "
            "get, and list. For example:\n\n"
            "return Assignment.create{\n"
            "  type = \"research\",\n"
            "  title = \"Research recent AI newsroom reliability metrics\",\n"
            "  summary = \"Find evidence and angles for an edition-candidate story.\",\n"
            "  sectionKey = \"technology\",\n"
            "  researchMode = \"source_discovery\",\n"
            "  apply = true,\n"
            "}\n\n"
            "return Reference.create{\n"
            "  url = \"https://example.com/article\",\n"
            "  title = \"Optional display title\",\n"
            "  apply = true,\n"
            "}\n\n"
            "Use api_list{} to inspect the resource/verb schema. Use docs_list{ namespace = \"resources\" } "
            "before non-trivial writes, then load focused documentation with "
            "docs_get{ id = \"resources.Assignment\" } or docs_get{ id = \"resources.Reference\" }."
        ),
    },
    "resources.Reference": {
        "id": "resources.Reference",
        "title": "Reference Resource",
        "summary": "Register URL source material and read/list references in the knowledge corpus.",
        "namespace": "resources",
        "status": "stable",
        "tags": ["reference", "resource-api", "writes", "intake"],
        "content": (
            "Reference is scholarly/source material in a knowledge corpus. Use PascalCase "
            "resource verbs; do not invent papyrus.reference.create or Reference.register.\n\n"
            "Reference.create{ url = \"https://...\", apply = true } registers a pending "
            "reference prospect (same catalog path as inbound email citation intake), creates "
            "curation intake wiring, and by default runs URL text extraction plus metadata "
            "generation when apply = true.\n\n"
            "Required: url (http/https). Optional: title, corpusKey (default AI-ML-research), "
            "ingestionRationale, actorLabel, apply (default false dry-run), enrich (default true "
            "when apply), skipExisting (default true), createCurationAssignment (default true), "
            "note.\n\n"
            "Example:\n"
            "return Reference.create{\n"
            "  url = \"https://newsletter.example.com/p/article-slug\",\n"
            "  title = \"A visual guide to Gemma\",\n"
            "  apply = true,\n"
            "}\n\n"
            "Use Reference.get{ id = \"reference-id\" } and Reference.list{ limit = 10, order = \"newest\" } "
            "for discovery. When the user pastes a URL and asks to add/register/file a reference, "
            "call Reference.create immediately with apply = true unless they asked for a dry-run."
        ),
    },
    "resources.Assignment": {
        "id": "resources.Assignment",
        "title": "Assignment Resource",
        "summary": "Create, read, and list first-class private newsroom Assignment records.",
        "namespace": "resources",
        "status": "stable",
        "tags": ["assignment", "resource-api", "writes"],
        "content": (
            "Assignment is the first-class private newsroom work record. Use the "
            "PascalCase resource table and consistent verbs; do not invent helper "
            "names like createResearchAssignment. The v1 write path supports "
            "Assignment.create{ type = \"research\", title = ..., apply = ... }.\n\n"
            "Required for create: type, title. Supported type: research. Optional: "
            "summary, sectionKey, instructions, corpusKey, researchMode, priority, "
            "status, importRunId, actorLabel, apply. apply = false returns a dry-run "
            "plan. apply = true writes one Assignment and one AssignmentEvent through "
            "the Papyrus GraphQL authoring lane.\n\n"
            "Example:\n"
            "return Assignment.create{\n"
            "  type = \"research\",\n"
            "  title = \"Research recent AI newsroom reliability metrics\",\n"
            "  summary = \"Find evidence and angles for an edition-candidate story.\",\n"
            "  sectionKey = \"technology\",\n"
            "  researchMode = \"source_discovery\",\n"
            "  apply = true,\n"
            "}\n\n"
            "Use Assignment.get{ id = \"assignment-id\" } to read one assignment. "
            "Use Assignment.list{ type = \"research\", status = \"open\", limit = 10 } "
            "for discovery. Use Assignment.update{ id = \"assignment-id\", status = \"claimed\", apply = true } "
            "to change lifecycle status and append an AssignmentEvent. "
            "For writes beyond simple research assignment creation, "
            "load the relevant resource docs first."
        ),
    },
    "newsroom.assignment-context": {
        "id": "newsroom.assignment-context",
        "title": "Assignment Context",
        "summary": "Read live Assignment context and build budgeted agent context packs.",
        "namespace": "newsroom",
        "status": "stable",
        "tags": ["assignment", "context", "desk-memory"],
        "content": (
            "For live queue work, call assignment_context{ id = ... }, then "
            "assignment_agent_context{ id = ..., context_profile = ... }, then "
            "assignment_context_to_item{ assignment_context = context.assignment_context }. "
            "The normalized item is the dry-run compatibility shape used by plan builders."
        ),
    },
    "newsroom.record-plans": {
        "id": "newsroom.record-plans",
        "title": "Dry-Run Record Plans",
        "summary": "Build dry-run assignment, research, and draft record plans.",
        "namespace": "newsroom",
        "status": "stable",
        "tags": ["plans", "dry-run"],
        "content": (
            "Use papyrus.plan.assignment_dispatch, papyrus.plan.research_update, "
            "papyrus.plan.assignment_research_packet, "
            "papyrus.plan.assignment_reporting_context_packet, and papyrus.plan.draft_update "
            "to build inspectable dry-run mutation plans. "
            "These helpers do not write GraphQL records."
        ),
    },
    "newsroom.biblicus-evidence": {
        "id": "newsroom.biblicus-evidence",
        "title": "Biblicus Evidence",
        "summary": "Use configured Biblicus corpus tools from Papyrus Tactus snippets.",
        "namespace": "newsroom",
        "status": "stable",
        "tags": ["biblicus", "evidence"],
        "content": (
            "Use biblicus_steering_artifacts, biblicus_query, biblicus_topic_context, "
            "and biblicus_topic_trends for evidence gathering. Keep returned evidence "
            "ids in research packets and draft plans. Papyrus context and planning "
            "helpers treat only current accepted references as evidence-eligible."
        ),
    },
    "newsroom.reference-intake": {
        "id": "newsroom.reference-intake",
        "title": "Reference Intake",
        "summary": "Use consistent reference-intake vocabulary and ingestion rationales.",
        "namespace": "newsroom",
        "status": "stable",
        "tags": ["references", "curation", "scope-memory"],
        "content": (
            "New source material becomes a reference prospect until accepted. "
            "When proposing ingestion, include an ingestion rationale with a brief "
            "summary, the link to the current research focus, and the fit with the "
            "publication mission. Rejected references are scope memory, not "
            "publishable evidence."
        ),
    },
    "newsroom.doi-backfill": {
        "id": "newsroom.doi-backfill",
        "title": "DOI Backfill",
        "summary": "Assignment-first DOI resolution and identifier linking workflow.",
        "namespace": "newsroom",
        "status": "stable",
        "tags": ["references", "doi", "identifiers"],
        "content": (
            "Use reference_doi_backfill_plan for canonical commands, then run "
            "reference_doi_backfill_run for immediate mode or process queue claims "
            "for assignment mode. The workflow resolves DOI deterministically first, "
            "uses LLM adjudication only when configured, writes "
            "digital_object_identifier_is relations, and persists DOI metadata."
        ),
    },
    "newsroom.web-ui": {
        "id": "newsroom.web-ui",
        "title": "Web UI Locations",
        "summary": "Read the editor's current page and navigate the web app via papyrus:// URIs.",
        "namespace": "newsroom",
        "status": "stable",
        "tags": ["web", "console", "navigation"],
        "content": (
            "Console chat agents receive the user's current web UI state as pedantic "
            "papyrus:// location URIs. Object detail pages use object URIs such as "
            "papyrus://reference/<lineage-id>. Newsroom desk tabs use "
            "papyrus://newsroom/<tab>, for example papyrus://newsroom/references.\n\n"
            "Use papyrus.web.current_location{} to read the latest UI snapshot injected "
            "by the web chat harness. Use papyrus.web.navigate{ uri = "
            "\"papyrus://reference/<lineage-id>\" } to request in-browser navigation; "
            "the web client maps the URI back to the concrete Next.js route."
        ),
    },
    "newsroom.web-research": {
        "id": "newsroom.web-research",
        "title": "Web Research",
        "summary": "Use web_search helper or papyrus.reference.web_search for fresh external evidence (Tavily by default).",
        "namespace": "newsroom",
        "status": "stable",
        "tags": ["web", "evidence", "tactus"],
        "content": (
            "Inside research harness snippets, use web_search(query) directly. "
            "Outside that harness, call papyrus.reference.web_search{ query = ..., "
            "max_results = ..., provider = ... }. Tavily is the default provider "
            "(WEB_SEARCH_PROVIDER=tavily); set provider=\"openai\" to use OpenAI web search. "
            "The harness first tries Tactus "
            "stdlib web.search and falls back to papyrus.reference.web_search when "
            "tactus.web is unavailable. Keep web discoveries as reference prospects "
            "until intake accepts them; do not write GraphQL records from search "
            "results alone."
        ),
    },
}


HELPER_BINDINGS: tuple[tuple[str, str, str], ...] = (
    ("edition_get", "edition", "get"),
    ("edition_items", "edition", "items"),
    ("item_get", "item", "get"),
    ("assignment_get", "assignment", "get"),
    ("assignment_context", "assignment", "context"),
    ("assignment_agent_context", "assignment", "agent_context"),
    ("assignment_context_to_item", "assignment", "context_to_item"),
    ("reference_doi_backfill_plan", "reference", "doi_backfill_plan"),
    ("reference_doi_backfill_run", "reference", "doi_backfill_run"),
    ("reference_doi_backfill_manifest", "reference", "doi_backfill_manifest"),
    ("reference_fetch_url_text", "reference", "fetch_url_text"),
    ("reference_filter_extracted_text", "reference", "filter_extracted_text"),
    ("reference_generate_metadata_from_text", "reference", "generate_metadata_from_text"),
    ("reference_web_search", "reference", "web_search"),
    ("knowledge_query", "knowledge", "query"),
    ("resolve_papyrus_uri", "papyrus", "resolve_uri"),
    ("web_current_location", "web", "current_location"),
    ("web_navigate", "web", "navigate"),
    ("web_set_index_filters", "web", "set_index_filters"),
    ("recent_published_articles", "article", "recent_published"),
    ("biblicus_steering_artifacts", "biblicus", "steering_artifacts"),
    ("biblicus_topic_context", "biblicus", "topic_context"),
    ("biblicus_topic_trends", "biblicus", "topic_trends"),
    ("biblicus_query", "biblicus", "query"),
    ("semantic_search_nodes", "semantic", "search_nodes"),
    ("plan_assignment_dispatch", "plan", "assignment_dispatch"),
    ("plan_research_update", "plan", "research_update"),
    ("plan_assignment_research_packet", "plan", "assignment_research_packet"),
    ("plan_assignment_reporting_context_packet", "plan", "assignment_reporting_context_packet"),
    ("plan_draft_update", "plan", "draft_update"),
    ("papyrus_email_submission_process", "email_submission", "process"),
    ("docs_list", "docs", "list"),
    ("docs_get", "docs", "get"),
    ("api_list", "api", "list"),
)


class PapyrusRuntimeModule:
    """Tactus host module exposing curated Papyrus newsroom namespaces."""

    def __init__(self, web_ui_context: dict[str, Any] | None = None) -> None:
        self._api_calls: list[str] = []
        self._web_ui_context = dict(web_ui_context or {})
        methods_by_namespace: dict[str, set[str]] = {}
        for namespace, method in API_METHODS:
            methods_by_namespace.setdefault(namespace, set()).add(method)
        methods_by_namespace.setdefault("web", set()).update({"current_location", "navigate", "set_index_filters"})
        for namespace, methods in methods_by_namespace.items():
            if namespace != "papyrus":
                setattr(self, namespace, _Namespace(self._call, namespace, methods))
        resource_methods: dict[str, set[str]] = {}
        for resource, method in RESOURCE_METHODS:
            resource_methods.setdefault(resource, set()).add(method)
        for resource, methods in resource_methods.items():
            setattr(self, resource, _Namespace(self._call_resource, resource, methods))
        self.resolve_uri = self._make_root_call("resolve_uri")
        self.docs = _Namespace(self._call_docs, "docs", {"list", "get"})
        self.api = _Namespace(self._call_api, "api", {"list"})

    @property
    def api_calls(self) -> list[str]:
        return list(self._api_calls)

    def _record_api_call(self, namespace: str, method: str) -> None:
        if namespace == "papyrus":
            self._api_calls.append(f"papyrus.{method}")
        else:
            self._api_calls.append(f"papyrus.{namespace}.{method}")

    def _call(self, namespace: str, method: str, args: Any = None) -> Any:
        parsed = _args(args)
        if namespace == "web":
            self._record_api_call(namespace, method)
            return self._call_web(method, parsed)
        handler = API_METHODS.get((namespace, method))
        if handler is None:
            raise ValueError(f"Unsupported Papyrus runtime API: papyrus.{namespace}.{method}")
        self._record_api_call(namespace, method)
        return handler(parsed)

    def _call_web(self, method: str, args: dict[str, Any]) -> Any:
        from papyrus_web.locations import papyrus_uri_to_web_path

        if method == "current_location":
            location = dict(self._web_ui_context)
            if not location:
                return {"location": {}, "available": False}
            return {"location": location, "available": True}
        if method == "navigate":
            uri = str(args.get("uri") or args.get("papyrusUri") or args.get("papyrus_uri") or "").strip()
            if not uri:
                raise ValueError("papyrus.web.navigate requires uri")
            mapped = papyrus_uri_to_web_path(uri)
            replace = bool(args.get("replace") or args.get("replaceHistory") or False)
            return {
                "ok": True,
                "navigation": {
                    "papyrusLocationUri": mapped["papyrusLocationUri"],
                    "webPath": mapped["webPath"],
                    "replace": replace,
                },
                "previousLocation": dict(self._web_ui_context),
                "requestedUri": uri,
            }
        if method == "set_index_filters":
            from papyrus_web.locations import _build_index_location_uri, _effective_index_filters

            tab = str(args.get("tab") or args.get("desk") or "").strip()
            if tab not in {"references", "messages", "assignments"}:
                raise ValueError("papyrus.web.set_index_filters requires tab = references|messages|assignments")
            filters = _effective_index_filters(
                tab,
                {
                    "status": str(args.get("status") or ""),
                    "processing": str(args.get("processing") or ""),
                    "order": str(args.get("order") or ""),
                    "kind": str(args.get("kind") or ""),
                    "domain": str(args.get("domain") or ""),
                    "type": str(args.get("type") or ""),
                    "view": str(args.get("view") or ""),
                },
            )
            uri = _build_index_location_uri(tab, filters)
            mapped = papyrus_uri_to_web_path(uri)
            replace = bool(args.get("replace") or args.get("replaceHistory") or False)
            return {
                "ok": True,
                "navigation": {
                    "papyrusLocationUri": mapped["papyrusLocationUri"],
                    "webPath": mapped["webPath"],
                    "replace": replace,
                },
                "indexFilters": filters,
                "previousLocation": dict(self._web_ui_context),
                "requestedUri": uri,
            }
        raise ValueError(f"Unsupported Papyrus runtime API: papyrus.web.{method}")

    def _call_resource(self, resource: str, method: str, args: Any = None) -> Any:
        handler = RESOURCE_METHODS.get((resource, method))
        if handler is None:
            raise ValueError(f"Unsupported Papyrus resource API: {resource}.{method}")
        parsed = _args(args)
        self._api_calls.append(f"papyrus.{resource}.{method}")
        return handler(parsed)

    def _make_root_call(self, method: str) -> Callable[[Any], Any]:
        def call(args: Any = None) -> Any:
            return self._call("papyrus", method, args)

        return call

    def _call_docs(self, namespace: str, method: str, args: Any = None) -> Any:
        parsed = _args(args)
        if method == "list":
            namespace_filter = parsed.get("namespace")
            self._record_api_call("docs", "list")
            entries = []
            for doc in DOCS.values():
                if namespace_filter and doc.get("namespace") != namespace_filter:
                    continue
                entries.append(
                    {
                        key: doc[key]
                        for key in ("id", "title", "summary", "namespace", "status", "tags")
                    }
                )
            return entries
        if method == "get":
            doc_id = parsed.get("id") or parsed.get("key") or parsed.get("name")
            if not doc_id:
                raise ValueError("papyrus.docs.get requires id, key, or name")
            doc = DOCS.get(str(doc_id))
            if doc is None:
                raise FileNotFoundError(f"Unknown Papyrus documentation id: {doc_id}")
            self._record_api_call("docs", "get")
            return {"id": doc["id"], "metadata": {k: v for k, v in doc.items() if k != "content"}, "content": doc["content"]}
        raise ValueError(f"Unsupported Papyrus runtime API: papyrus.docs.{method}")

    def _call_api(self, namespace: str, method: str, args: Any = None) -> Any:
        if method != "list":
            raise ValueError(f"Unsupported Papyrus runtime API: papyrus.api.{method}")
        self._record_api_call("api", "list")
        return RESOURCE_API_SCHEMA


def _wrap_tactus_snippet(tactus: str) -> str:
    helper_lines = [
        "local papyrus = papyrus",
        "if papyrus == nil then",
        '  error("papyrus runtime module unavailable")',
        "end",
        "local __papyrus_last_result = nil",
        "local function __papyrus_capture(value)",
        "  __papyrus_last_result = value",
        "  return value",
        "end",
    ]
    for helper_name, namespace, method in HELPER_BINDINGS:
        call_expression = f"papyrus.{method}(args)" if namespace == "papyrus" else f"papyrus.{namespace}.{method}(args)"
        helper_lines.extend(
            [
                f"function {helper_name}(args)",
                f"  return __papyrus_capture({call_expression})",
                "end",
            ]
        )
    resource_methods: dict[str, list[str]] = {}
    for resource, method in RESOURCE_METHODS:
        resource_methods.setdefault(resource, []).append(method)
    for resource, methods in sorted(resource_methods.items()):
        helper_lines.append(f"{resource} = {{}}")
        for method in sorted(methods):
            helper_lines.extend(
                [
                    f"function {resource}.{method}(args)",
                    f"  return __papyrus_capture(papyrus.{resource}.{method}(args))",
                    "end",
                ]
            )
    return "\n".join(
        [
            *helper_lines,
            "local function __execute_tactus_user_snippet()",
            tactus,
            "end",
            "local __papyrus_explicit_result = __execute_tactus_user_snippet()",
            "if __papyrus_explicit_result ~= nil then",
            "  return __papyrus_explicit_result",
            "end",
            "return __papyrus_last_result",
            "",
        ]
    )


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            error["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error["error"]
    return result.get("value")


def _bind_papyrus_runtime(runtime: Any, papyrus: Any) -> None:
    original_create_execution_context = getattr(runtime, "_create_execution_context", None)
    if not callable(original_create_execution_context):
        raise RuntimeError("execute_tactus requires TactusRuntime._create_execution_context support.")

    def _wrapped_create_execution_context(strict_determinism: bool) -> Any:
        context = original_create_execution_context(strict_determinism)
        sandbox = getattr(runtime, "lua_sandbox", None)
        inject_primitive = getattr(sandbox, "inject_primitive", None)
        if not callable(inject_primitive):
            raise RuntimeError("execute_tactus requires Lua sandbox inject_primitive support.")
        inject_primitive("papyrus", papyrus)
        return context

    runtime._create_execution_context = _wrapped_create_execution_context


def _lua_string(value: str) -> str:
    return json.dumps(str(value))


def _research_harness(
    *,
    body: str,
    assignment_id: str,
    assignment_item_json: str,
    corpus_key: str,
    max_evidence_items: int,
    research_mode: str = "",
    knowledge_query_scope: dict[str, Any] | None = None,
    disable_tactus_web: bool = False,
) -> str:
    assignment_json = assignment_item_json or "{}"
    evidence_limit = max(int(max_evidence_items or 1), 1)
    assignment_loader = (
        f'local assignment = assignment_get{{ id = {_lua_string(assignment_id)} }}.assignment\nlocal assignment_is_live = true'
        if assignment_id and not assignment_item_json
        else f'local assignment = json.decode({_lua_string(assignment_json)})\nlocal assignment_is_live = assignment.assignmentTypeKey ~= nil and assignment.type == nil'
    )
    return f"""
	local json = require("tactus.io.json")
	{assignment_loader}
local corpus_key = {_lua_string(corpus_key or "")}
local max_evidence_items = {evidence_limit}
local requested_research_mode = {_lua_string(research_mode or "")}
local requested_knowledge_query_scope_json = {_lua_string(json.dumps(knowledge_query_scope or {}, sort_keys=True))}

if assignment_is_live and (assignment.queueKey == nil or assignment.queueKey == "") then
    error("live assignment research packets require assignment.queueKey")
end

local function trim_results(results)
    local trimmed = {{}}
    if not results then return trimmed end
    local function safe_index(list_like, idx)
        local ok, value = pcall(function()
            return list_like[idx]
        end)
        if not ok and idx > 0 then
            ok, value = pcall(function()
                return list_like[idx - 1]
            end)
        end
        if ok then
            return value
        end
        return nil
    end
    local index = 1
    local value = safe_index(results, index)
    while value and index <= max_evidence_items do
        trimmed[index] = value
        index = index + 1
        value = safe_index(results, index)
    end
    return trimmed
end

local function normalize_research_mode(value)
    local mode = tostring(value or "")
    mode = string.gsub(string.lower(mode), "%-", "_")
    if mode == "internal_brief" or mode == "source_discovery" or mode == "full_research" then
        return mode
    end
    return "source_discovery"
end

local function assignment_metadata()
    local metadata = nil
    local ok, value = pcall(function()
        return assignment.metadata
    end)
    if ok then
        metadata = value
    else
        metadata = {{}}
    end
    if metadata == nil then
        metadata = {{}}
    end
    if type(metadata) == "string" then
        local ok, decoded = pcall(json.decode, metadata)
        if ok and type(decoded) == "table" then
            metadata = decoded
        else
            metadata = {{}}
        end
    end
    if type(metadata) ~= "table" then
        metadata = {{}}
    end
    return metadata
end

local __metadata = assignment_metadata()
local research_mode = normalize_research_mode(
    requested_research_mode ~= "" and requested_research_mode or (__metadata.researchMode or __metadata.research_mode)
)
local __web_searches = {{}}
local __default_discovery_retry_budget = tonumber(
    __metadata.webDiscoveryRetryBudget
    or __metadata.discoveryRetryBudget
    or __metadata.web_discovery_retry_budget
    or __metadata.discovery_retry_budget
    or 4
) or 4
if __default_discovery_retry_budget < 1 then
    __default_discovery_retry_budget = 1
end
if __default_discovery_retry_budget > 8 then
    __default_discovery_retry_budget = 8
end
local function normalize_string_list(value)
    local normalized = {{}}
    local seen = {{}}
    if type(value) ~= "table" and type(value) ~= "userdata" then
        return normalized
    end
    local index = 1
    local function safe_index(list_like, idx)
        local ok, entry = pcall(function()
            return list_like[idx]
        end)
        if not ok and idx > 0 then
            ok, entry = pcall(function()
                return list_like[idx - 1]
            end)
        end
        if ok then
            return entry
        end
        return nil
    end
    local entry = safe_index(value, index)
    while entry do
        local text = tostring(entry or "")
        text = string.gsub(text, "^%s+", "")
        text = string.gsub(text, "%s+$", "")
        if text ~= "" and not seen[text] then
            normalized[#normalized + 1] = text
            seen[text] = true
        end
        index = index + 1
        entry = safe_index(value, index)
    end
    return normalized
end

local function parse_requested_knowledge_scope()
    local scope = {{}}
    local ok, decoded = pcall(json.decode, requested_knowledge_query_scope_json)
    if ok and (type(decoded) == "table" or type(decoded) == "userdata") then
        scope = decoded
    end
    local include_default_kinds = {{
        "reference",
        "item",
        "category",
        "semanticNode",
        "newsroomSection",
        "assignment",
        "message",
    }}
    local include_default_message_kinds = {{ "insight" }}
    local include_default_assignment_types = {{ "research.*", "reporting.*" }}
    local include_kinds = normalize_string_list(scope.includeObjectKinds or scope.include_object_kinds or include_default_kinds)
    if include_kinds[1] == nil then include_kinds = include_default_kinds end
    local include_message_kinds = normalize_string_list(
        scope.includeMessageKinds or scope.include_message_kinds or include_default_message_kinds
    )
    if include_message_kinds[1] == nil then include_message_kinds = include_default_message_kinds end
    local include_assignment_types = normalize_string_list(
        scope.includeAssignmentTypeKeys or scope.include_assignment_type_keys or include_default_assignment_types
    )
    if include_assignment_types[1] == nil then include_assignment_types = include_default_assignment_types end
    return {{
        includeObjectKinds = include_kinds,
        excludeObjectKinds = normalize_string_list(scope.excludeObjectKinds or scope.exclude_object_kinds or {{}}),
        includeMessageKinds = include_message_kinds,
        excludeMessageKinds = normalize_string_list(scope.excludeMessageKinds or scope.exclude_message_kinds or {{}}),
        includeAssignmentTypeKeys = include_assignment_types,
        excludeAssignmentTypeKeys = normalize_string_list(
            scope.excludeAssignmentTypeKeys or scope.exclude_assignment_type_keys or {{}}
        ),
    }}
end

local __knowledge_query_scope_defaults = parse_requested_knowledge_scope()

local function result_count(results)
    local count = 0
    if not results then return count end
    local function safe_index(list_like, idx)
        local ok, value = pcall(function()
            return list_like[idx]
        end)
        if not ok and idx > 0 then
            ok, value = pcall(function()
                return list_like[idx - 1]
            end)
        end
        if ok then
            return value
        end
        return nil
    end
    while safe_index(results, count + 1) do
        count = count + 1
    end
    return count
end

local function safe_lookup(map_like, key)
    local ok, value = pcall(function()
        return map_like[key]
    end)
    if ok then
        return value, true
    end
    return nil, false
end

local function normalize_search_result(search, query)
    local shape_ok = true
    local normalized = {{}}
    local search_type = type(search)
    if search_type ~= "table" and search_type ~= "userdata" then
        search = {{}}
        shape_ok = false
    end

    local search_query = nil
    if search_type == "userdata" then
        local ok = false
        search_query, ok = safe_lookup(search, "query")
        if not ok then
            shape_ok = false
        end
    else
        search_query = search.query
    end

    local normalized_query = ""
    if type(search_query) == "string" and search_query ~= "" then
        normalized_query = search_query
    else
        normalized_query = tostring(query or "")
        if search_query ~= nil then
            shape_ok = false
        end
    end

    local raw_results = nil
    if search_type == "userdata" then
        local ok = false
        raw_results, ok = safe_lookup(search, "results")
        if not ok then
            shape_ok = false
        end
    else
        raw_results = search.results
    end
    local raw_results_type = type(raw_results)
    if raw_results_type ~= "table" and raw_results_type ~= "userdata" then
        raw_results = {{}}
        shape_ok = false
    end
    local function safe_index(list_like, idx)
        local ok, value = pcall(function()
            return list_like[idx]
        end)
        if not ok and idx > 0 then
            ok, value = pcall(function()
                return list_like[idx - 1]
            end)
        end
        if ok then
            return value
        end
        return nil
    end
    local normalized_results = {{}}
    local index = 1
    local source = safe_index(raw_results, index)
    while source and index <= max_evidence_items do
        local source_type = type(source)
        if source_type ~= "table" and source_type ~= "userdata" then
            source = {{}}
            shape_ok = false
        end
        normalized_results[index] = source
        index = index + 1
        source = safe_index(raw_results, index)
    end

    local metadata = nil
    if search_type == "userdata" then
        local ok = false
        metadata, ok = safe_lookup(search, "metadata")
        if not ok then
            shape_ok = false
        end
    else
        metadata = search.metadata
    end
    local metadata_type = type(metadata)
    if metadata_type ~= "table" and metadata_type ~= "userdata" then
        metadata = {{}}
        shape_ok = false
    end
    local metadata_answer = nil
    if type(metadata) == "userdata" then
        local ok = false
        metadata_answer, ok = safe_lookup(metadata, "answer")
        if not ok then
            metadata = {{}}
            shape_ok = false
            metadata_answer = nil
        end
    else
        metadata_answer = metadata.answer
    end
    local normalized_metadata = {{}}
    if type(metadata_answer) ~= "string" then
        if metadata_answer ~= nil then
            shape_ok = false
        end
        normalized_metadata.answer = ""
    else
        normalized_metadata.answer = metadata_answer
    end
    if type(metadata) == "userdata" then
        local value = select(1, safe_lookup(metadata, "blocked_reason"))
        if type(value) == "string" and value ~= "" then
            normalized_metadata.blocked_reason = value
        end
        local path = select(1, safe_lookup(metadata, "web_search_path"))
        if type(path) == "string" and path ~= "" then
            normalized_metadata.web_search_path = path
        end
        local provider = select(1, safe_lookup(metadata, "web_search_provider"))
        if type(provider) == "string" and provider ~= "" then
            normalized_metadata.web_search_provider = provider
        end
        local count = select(1, safe_lookup(metadata, "search_result_count"))
        if type(count) == "number" then
            normalized_metadata.search_result_count = count
        end
        local attempts = select(1, safe_lookup(metadata, "discovery_attempts_total"))
        if type(attempts) == "number" then
            normalized_metadata.discovery_attempts_total = attempts
        end
        local queries_tried = select(1, safe_lookup(metadata, "discovery_queries_tried"))
        if type(queries_tried) == "table" or type(queries_tried) == "userdata" then
            normalized_metadata.discovery_queries_tried = normalize_string_list(queries_tried)
        end
        local counts = select(1, safe_lookup(metadata, "discovery_result_counts"))
        if type(counts) == "table" or type(counts) == "userdata" then
            normalized_metadata.discovery_result_counts = counts
        end
        local terminal_state = select(1, safe_lookup(metadata, "discovery_terminal_state"))
        if type(terminal_state) == "string" and terminal_state ~= "" then
            normalized_metadata.discovery_terminal_state = terminal_state
        end
    elseif type(metadata) == "table" then
        if type(metadata.blocked_reason) == "string" and metadata.blocked_reason ~= "" then
            normalized_metadata.blocked_reason = metadata.blocked_reason
        end
        if type(metadata.web_search_path) == "string" and metadata.web_search_path ~= "" then
            normalized_metadata.web_search_path = metadata.web_search_path
        end
        if type(metadata.web_search_provider) == "string" and metadata.web_search_provider ~= "" then
            normalized_metadata.web_search_provider = metadata.web_search_provider
        end
        if type(metadata.search_result_count) == "number" then
            normalized_metadata.search_result_count = metadata.search_result_count
        end
        if type(metadata.discovery_attempts_total) == "number" then
            normalized_metadata.discovery_attempts_total = metadata.discovery_attempts_total
        end
        if type(metadata.discovery_queries_tried) == "table" then
            normalized_metadata.discovery_queries_tried = normalize_string_list(metadata.discovery_queries_tried)
        end
        if type(metadata.discovery_result_counts) == "table" then
            normalized_metadata.discovery_result_counts = metadata.discovery_result_counts
        end
        if type(metadata.discovery_terminal_state) == "string" and metadata.discovery_terminal_state ~= "" then
            normalized_metadata.discovery_terminal_state = metadata.discovery_terminal_state
        end
    end
    normalized_metadata.search_metadata_shape_ok = shape_ok

    normalized.query = normalized_query
    normalized.results = trim_results(normalized_results)
    normalized.metadata = normalized_metadata
    if type(normalized_metadata.web_search_provider) == "string" and normalized_metadata.web_search_provider ~= "" then
        normalized.provider = normalized_metadata.web_search_provider
    end
    return normalized
end

    local function build_discovery_query(query, attempt)
        local base = tostring(query or "")
        base = string.gsub(base, "^%s+", "")
        base = string.gsub(base, "%s+$", "")
        if attempt <= 1 then
            return base
        end
        if attempt == 2 then
            return base .. " survey review explainer standards specification interoperability"
        end
        if attempt == 3 then
            return '"' .. base .. '" protocol taxonomy comparison'
        end
        local domain_queries = {{
            "site:arxiv.org " .. base .. " survey",
            "site:openai.com " .. base,
            "site:anthropic.com " .. base,
            "site:microsoft.com " .. base,
            "site:ai.google.dev " .. base,
        }}
        local domain_index = ((attempt - 4) % #domain_queries) + 1
        return domain_queries[domain_index]
    end

	local function web_search(query, options)
    options = options or {{}}
    local retry_budget = tonumber(options.retry_budget or options.retryBudget or __default_discovery_retry_budget) or __default_discovery_retry_budget
    if retry_budget < 1 then retry_budget = 1 end
    if retry_budget > 8 then retry_budget = 8 end
    local attempts = {{}}
    local queries_tried = {{}}
    local result_counts = {{}}
    local shape_ok = true
    local terminal_state = "exhausted"
    local selected = nil
    local blocked_reason = nil
    local first_error = nil

    local attempt_index = 1
    while attempt_index <= retry_budget do
        local attempt_query = build_discovery_query(query, attempt_index)
        queries_tried[attempt_index] = attempt_query
        __web_searches[#__web_searches + 1] = attempt_query
        local ok, fetched = pcall(function()
            return papyrus.reference.web_search{{
                query = attempt_query,
                max_results = max_evidence_items,
                model = "gpt-5.4-mini",
                return_token_budget = "default",
            }}
        end)
        local fetched_type = type(fetched)
        local raw = {{}}
        if ok and (fetched_type == "table" or fetched_type == "userdata") then
            raw = fetched
        else
            local reason = "papyrus.reference.web_search failed: " .. tostring(fetched or "unknown error")
            if type(first_error) ~= "string" or first_error == "" then
                first_error = reason
            end
            blocked_reason = reason
        end
        local normalized_attempt = normalize_search_result(raw, attempt_query)
        attempts[attempt_index] = normalized_attempt
        local count = result_count(normalized_attempt.results)
        result_counts[attempt_index] = count
        if normalized_attempt.metadata.search_metadata_shape_ok ~= true then
            shape_ok = false
        end
        if count > 0 then
            selected = normalized_attempt
            terminal_state = "succeeded"
            blocked_reason = nil
            break
        end
        attempt_index = attempt_index + 1
    end

    if selected == nil then
        selected = normalize_search_result({{}}, tostring(query or ""))
        selected.results = {{}}
        selected.query = tostring(query or "")
        selected.metadata.answer = ""
        if type(first_error) == "string" and first_error ~= "" then
            blocked_reason = first_error
        else
            blocked_reason = "web_discovery_exhausted_zero_results"
        end
    end

    selected.metadata.web_search_path = "papyrus.reference.web_search"
    if type(selected.metadata.web_search_provider) ~= "string" or selected.metadata.web_search_provider == "" then
        selected.metadata.web_search_provider = "tavily"
    end
    if type(selected.provider) ~= "string" or selected.provider == "" then
        selected.provider = selected.metadata.web_search_provider
    end
    selected.metadata.search_result_count = result_count(selected.results)
    selected.metadata.search_metadata_shape_ok = shape_ok
    selected.metadata.discovery_attempts_total = #queries_tried
    selected.metadata.discovery_queries_tried = queries_tried
    selected.metadata.discovery_result_counts = result_counts
    selected.metadata.discovery_terminal_state = terminal_state
    if type(blocked_reason) == "string" and blocked_reason ~= "" then
        selected.metadata.blocked_reason = blocked_reason
    end
    return selected
end

		local function knowledge_search(query, options)
		    options = options or {{}}
            local scope = {{
                depth = options.depth or 1,
                topK = options.top_k or options.topK or max_evidence_items,
                includeObjectKinds = options.includeObjectKinds or options.include_object_kinds or __knowledge_query_scope_defaults.includeObjectKinds,
                excludeObjectKinds = options.excludeObjectKinds or options.exclude_object_kinds or __knowledge_query_scope_defaults.excludeObjectKinds,
                includeMessageKinds = options.includeMessageKinds or options.include_message_kinds or __knowledge_query_scope_defaults.includeMessageKinds,
                excludeMessageKinds = options.excludeMessageKinds or options.exclude_message_kinds or __knowledge_query_scope_defaults.excludeMessageKinds,
                includeAssignmentTypeKeys = options.includeAssignmentTypeKeys or options.include_assignment_type_keys or __knowledge_query_scope_defaults.includeAssignmentTypeKeys,
                excludeAssignmentTypeKeys = options.excludeAssignmentTypeKeys or options.exclude_assignment_type_keys or __knowledge_query_scope_defaults.excludeAssignmentTypeKeys,
            }}
		    return knowledge_query{{
		        query = query,
	        profile = options.profile or "researcher",
	        format = options.format or "both",
	        max_tokens = options.max_tokens or options.maxTokens or 1200,
	        scope = scope,
		        anchors = options.anchors or {{}},
		    }}
		end

	local function resolve_papyrus_uri(uri)
	    return papyrus.resolve_uri{{ uri = uri }}
	end

		local function knowledge_search_uri(uri, options)
		    options = options or {{}}
		    local anchors = options.anchors or {{ {{ uri = uri }} }}
            local scope = {{
                depth = options.depth or 1,
                topK = options.top_k or options.topK or max_evidence_items,
                includeObjectKinds = options.includeObjectKinds or options.include_object_kinds or __knowledge_query_scope_defaults.includeObjectKinds,
                excludeObjectKinds = options.excludeObjectKinds or options.exclude_object_kinds or __knowledge_query_scope_defaults.excludeObjectKinds,
                includeMessageKinds = options.includeMessageKinds or options.include_message_kinds or __knowledge_query_scope_defaults.includeMessageKinds,
                excludeMessageKinds = options.excludeMessageKinds or options.exclude_message_kinds or __knowledge_query_scope_defaults.excludeMessageKinds,
                includeAssignmentTypeKeys = options.includeAssignmentTypeKeys or options.include_assignment_type_keys or __knowledge_query_scope_defaults.includeAssignmentTypeKeys,
                excludeAssignmentTypeKeys = options.excludeAssignmentTypeKeys or options.exclude_assignment_type_keys or __knowledge_query_scope_defaults.excludeAssignmentTypeKeys,
            }}
		    return knowledge_query{{
		        query = options.query or options.semantic_query or options.semanticQuery or "",
		        profile = options.profile or "researcher",
		        format = options.format or "both",
		        max_tokens = options.max_tokens or options.maxTokens or 1000,
		        scope = scope,
		        anchors = anchors,
		    }}
		end

local function evidence_item_ids_from_knowledge(knowledge)
	    local ids = {{}}
	    local seen = {{}}
	    local structured = knowledge and knowledge.structured or {{}}
	    local function safe_field(record, key)
	        local ok, value = pcall(function()
	            return record[key]
	        end)
	        if ok then
	            return value
	        end
	        return nil
	    end
	    local collections = {{
	        safe_field(structured, "semanticMatches") or {{}},
	        safe_field(structured, "relatedRecords") or {{}},
	        safe_field(structured, "expandedObjects") or {{}},
	        safe_field(structured, "anchors") or {{}},
	    }}
	    local function record_field(record, key)
	        if record == nil then
	            return nil
	        end
	        if type(record) == "userdata" then
	            return select(1, safe_lookup(record, key))
	        end
	        if type(record) == "table" then
	            return record[key]
	        end
	        local ok, value = pcall(function()
	            return record[key]
	        end)
	        if ok then
	            return value
	        end
	        return nil
	    end
	    local function safe_index(list_like, idx)
	        local ok, value = pcall(function()
	            return list_like[idx]
	        end)
	        if not ok and idx > 0 then
	            ok, value = pcall(function()
	                return list_like[idx - 1]
	            end)
	        end
	        if ok then
	            return value
	        end
	        return nil
	    end
	    local out_index = 1
	    local collection_index = 1
	    local records = safe_index(collections, collection_index)
	    while records and out_index <= max_evidence_items do
	        local index = 1
	        local record = safe_index(records, index)
	        while record and out_index <= max_evidence_items do
	            local record_id = record_field(record, "id")
	            if record_field(record, "kind") == "reference"
	                and record_id
	                and record_field(record, "curationStatus") == "accepted"
	                and not seen[record_id] then
	                ids[out_index] = record_id
	                seen[record_id] = true
	                out_index = out_index + 1
	            end
	            index = index + 1
	            record = safe_index(records, index)
	        end
	        collection_index = collection_index + 1
	        records = safe_index(collections, collection_index)
	    end
	    return ids
	end

local function compact_record_plan(plan)
    return {{
        message_persistence = "outer_cli_layer",
        attachment_persistence = "outer_cli_layer",
        semantic_relation_persistence = "outer_cli_layer",
        note = "Dry-run packet only; no persistence performed by this tool call.",
    }}
end

local function finish_research(research)
    research.research_mode = normalize_research_mode(research.research_mode or research.researchMode or research_mode)
    research.corpus_key = research.corpus_key or corpus_key
    research.evidence_item_ids = research.evidence_item_ids or {{}}
    research.researchTrace = research.researchTrace or {{}}
    research.researchTrace.webSearches = research.researchTrace.webSearches or __web_searches
    research.researchTrace.acceptedEvidenceIds = research.researchTrace.acceptedEvidenceIds or research.evidence_item_ids
    local blocked_reason = research.blocked_reason or research.blockedReason
    local has_web_search_trace = research.researchTrace.webSearches and research.researchTrace.webSearches[1] ~= nil
    if has_web_search_trace and type(research.researchTrace.discoveryBoundary) ~= "table" then
        local discovery_sources = research.source_snapshots or research.sourceSnapshots
        if type(discovery_sources) ~= "table" then
            discovery_sources = {{}}
        end
        research.researchTrace.discoveryBoundary = {{
            webSearchPath = "papyrus.reference.web_search",
            searchResultCount = result_count(discovery_sources),
            searchMetadataShapeOk = true,
            discoveryAttemptsTotal = #(__web_searches or {{}}),
            discoveryQueriesTried = __web_searches or {{}},
            discoveryResultCounts = {{}},
            discoveryTerminalState = result_count(discovery_sources) > 0 and "succeeded" or "exhausted",
        }}
    end
    if blocked_reason and type(research.researchTrace.discoveryBoundary) == "table" then
        research.researchTrace.discoveryBoundary.blockedReason =
            research.researchTrace.discoveryBoundary.blockedReason or blocked_reason
    end
    research.internalFindings = research.internalFindings or {{
        summary = research.internal_summary or research.summary or "",
        evidenceItemIds = research.evidence_item_ids,
        queries = research.queries or {{}},
        papyrusUrisInspected = research.researchTrace.papyrusUrisInspected or {{}},
    }}
    research.sourceDiscovery = research.sourceDiscovery or {{
        webSearches = research.researchTrace.webSearches or {{}},
        sourceSnapshots = research.source_snapshots or research.sourceSnapshots or {{}},
        proposedReferences = research.proposed_references or research.proposedReferences or {{}},
        blockedReason = research.blocked_reason or research.blockedReason,
    }}
    research.synthesis = research.synthesis or {{
        summary = research.summary or "",
        recommendedAngle = research.recommended_angle or research.recommendedAngle or "",
        openQuestions = research.open_questions or research.openQuestions or {{}},
        coverageGaps = research.coverage_gaps or research.coverageGaps or {{}},
    }}
    if research.research_mode ~= "internal_brief" then
        local has_web_search = research.researchTrace.webSearches and research.researchTrace.webSearches[1] ~= nil
        local has_source_snapshot = (research.source_snapshots and research.source_snapshots[1] ~= nil)
            or (research.sourceSnapshots and research.sourceSnapshots[1] ~= nil)
            or (research.sourceDiscovery and research.sourceDiscovery.sourceSnapshots and research.sourceDiscovery.sourceSnapshots[1] ~= nil)
        local has_proposed_reference = (research.proposed_references and research.proposed_references[1] ~= nil)
            or (research.proposedReferences and research.proposedReferences[1] ~= nil)
            or (research.sourceDiscovery and research.sourceDiscovery.proposedReferences and research.sourceDiscovery.proposedReferences[1] ~= nil)
        blocked_reason = blocked_reason
            or (research.sourceDiscovery and (research.sourceDiscovery.blockedReason or research.sourceDiscovery.blocked_reason))
        if not has_web_search and not has_source_snapshot and not has_proposed_reference and not blocked_reason then
            error("research mode " .. research.research_mode .. " requires web discovery or blockedReason")
        end
    end
    local plan = nil
    if assignment_is_live then
        plan = plan_assignment_research_packet{{
            assignment = assignment,
            research = research,
        }}
    else
        plan = plan_research_update{{
            assignment_item = assignment,
            research = research,
        }}
    end
    return {{
        assignment_item_id = assignment.id,
        corpus_key = corpus_key,
        dry_run = true,
        item_status = "researched",
        research_packet = research,
        research_record_plan = compact_record_plan(plan),
        summary = research.summary or "Created dry-run research packet.",
    }}
end

local function source_title(source)
    if not source then return "Candidate source" end
    return source.title or source.url or source.source_domain or "Candidate source"
end

local function default_ingestion_rationale(source, query, answer)
    local title = source_title(source)
    local focus = assignment.summary or assignment.title or "the current research focus"
    focus = tostring(focus)
    focus = string.gsub(focus, "%s+", " ")
    focus = string.gsub(focus, "[%.%s]+$", "")
    return table.concat({{
        title,
        " was returned by web search for ",
        query or "the research query",
        ". The source should be reviewed as a reference prospect because it may provide current context for ",
        focus,
        ". Its fit with the publication mission should be judged during reference intake before it is treated as accepted evidence.",
    }})
end

local function proposed_references_from_search(search)
    local proposals = {{}}
    local results = search.results or {{}}
    local answer = ""
    if search.metadata and search.metadata.answer then
        answer = search.metadata.answer
    end
    local function safe_index(list_like, idx)
        local ok, value = pcall(function()
            return list_like[idx]
        end)
        if not ok and idx > 0 then
            ok, value = pcall(function()
                return list_like[idx - 1]
            end)
        end
        if ok then
            return value
        end
        return nil
    end
    local index = 1
    local source = safe_index(results, index)
    while source do
        proposals[index] = {{
            title = source_title(source),
            url = source.url,
            source_domain = source.source_domain,
            evidence_candidate_id = source.evidence_candidate_id,
            ingestion_rationale = default_ingestion_rationale(source, search.query, answer),
        }}
        index = index + 1
        source = safe_index(results, index)
    end
    return proposals
end

local function search_summary(search)
    local first = nil
    if search.results then
        local ok, value = pcall(function()
            return search.results[1]
        end)
        if ok then
            first = value
        end
    end
    if first then
        return table.concat({{
            "Found ",
            tostring(result_count(search.results)),
            " current reference prospect(s) for ",
            search.query or "the research query",
            "; first source: ",
            first.source_domain or first.url or "web search",
            ". Treat these as reference prospects until reference intake review.",
        }})
    end
    return "No current web reference prospect was returned for " .. (search.query or "the research query") .. "."
end

local function resolve_finish_research_from_search_args(search_or_options, options)
    if options ~= nil then
        return search_or_options, options
    end
    if type(search_or_options) ~= "table" then
        return search_or_options, {{}}
    end
    local candidate = search_or_options
    local has_research_mode = candidate.research_mode ~= nil or candidate.researchMode ~= nil
    local looks_like_search = candidate.query ~= nil and candidate.results ~= nil
    if has_research_mode and not looks_like_search then
        local resolved_options = candidate
        local query = ""
        if resolved_options.queries then
            local ok, first = pcall(function()
                return resolved_options.queries[1]
            end)
            if ok and first ~= nil then
                query = tostring(first)
            end
        end
        if query == "" and __web_searches and __web_searches[#__web_searches] then
            query = tostring(__web_searches[#__web_searches])
        end
        local resolved_search = resolved_options.search
        if resolved_search == nil then
            resolved_search = normalize_search_result({{
                query = query,
                results = resolved_options.source_snapshots or resolved_options.sourceSnapshots or {{}},
                metadata = resolved_options.metadata or {{}},
            }}, query)
        else
            resolved_search = normalize_search_result(resolved_search, query)
        end
        return resolved_search, resolved_options
    end
    return search_or_options, {{}}
end

local function finish_research_from_search(search_or_options, options)
    local search
    search, options = resolve_finish_research_from_search_args(search_or_options, options)
    options = options or {{}}
    search = normalize_search_result(search, options.query or "")
    local metadata = search.metadata or {{}}
    local metadata_blocked_reason = nil
    if type(metadata) == "userdata" then
        metadata_blocked_reason = select(1, safe_lookup(metadata, "blocked_reason"))
    else
        metadata_blocked_reason = metadata.blocked_reason
    end
    local blocked_reason = options.blocked_reason or options.blockedReason or metadata_blocked_reason
    if type(blocked_reason) ~= "string" then
        blocked_reason = ""
    end
    local discovery_trace = {{
        webSearchPath = (type(metadata) == "userdata" and select(1, safe_lookup(metadata, "web_search_path")) or metadata.web_search_path)
            or "papyrus.reference.web_search",
        searchResultCount = (type(metadata) == "userdata" and select(1, safe_lookup(metadata, "search_result_count")) or metadata.search_result_count)
            or result_count(search.results),
        searchMetadataShapeOk = (
            (type(metadata) == "userdata" and select(1, safe_lookup(metadata, "search_metadata_shape_ok")) or metadata.search_metadata_shape_ok)
            == true
        ),
        discoveryAttemptsTotal = (type(metadata) == "userdata" and select(1, safe_lookup(metadata, "discovery_attempts_total")) or metadata.discovery_attempts_total) or 1,
        discoveryQueriesTried = (type(metadata) == "userdata" and select(1, safe_lookup(metadata, "discovery_queries_tried")) or metadata.discovery_queries_tried) or {{ search.query }},
        discoveryResultCounts = (type(metadata) == "userdata" and select(1, safe_lookup(metadata, "discovery_result_counts")) or metadata.discovery_result_counts) or {{ result_count(search.results) }},
        discoveryTerminalState = (type(metadata) == "userdata" and select(1, safe_lookup(metadata, "discovery_terminal_state")) or metadata.discovery_terminal_state)
            or (result_count(search.results) > 0 and "succeeded" or "exhausted"),
    }}
    if blocked_reason ~= "" then
        discovery_trace.blockedReason = blocked_reason
    end
    local trace = options.researchTrace or options.research_trace or {{}}
    if type(trace) ~= "table" then
        trace = {{}}
    end
    trace.discoveryBoundary = discovery_trace
    return finish_research{{
        research_mode = options.research_mode or options.researchMode,
        summary = options.summary or search_summary(search),
        queries = {{ search.query }},
        source_snapshots = search.results or {{}},
        proposed_references = options.proposed_references or proposed_references_from_search(search),
        evidence_item_ids = options.evidence_item_ids or options.evidenceItemIds or {{}},
        recommended_angle = options.recommended_angle or "Assess the source as a reference prospect before using it as evidence.",
        open_questions = options.open_questions or {{}},
        coverage_gaps = options.coverage_gaps or {{}},
        comparison_findings = options.comparison_findings or {{}},
        rubric_assessments = options.rubric_assessments or {{}},
        blocked_reason = blocked_reason ~= "" and blocked_reason or nil,
        researchTrace = trace,
    }}
end

{body}
"""


def execute_tactus_harnessed(
    tactus: str,
    *,
    harness: str = "raw",
    assignment_id: str = "",
    assignment_item_json: str = "",
    corpus_key: str = "",
    max_evidence_items: int = 20,
    research_mode: str = "",
    knowledge_query_scope: dict[str, Any] | None = None,
    disable_tactus_web: bool = False,
    web_ui_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tactus = _normalize_tactus_snippet(tactus)
    assignment_id = _normalize_tactus_identifier(assignment_id)
    if harness == "raw":
        return execute_tactus(tactus, web_ui_context=web_ui_context)
    if harness == "research":
        snippet = _research_harness(
            body=tactus,
            assignment_id=assignment_id,
            assignment_item_json=assignment_item_json,
            corpus_key=corpus_key,
            max_evidence_items=max_evidence_items,
            research_mode=research_mode,
            knowledge_query_scope=knowledge_query_scope,
            disable_tactus_web=disable_tactus_web,
        )
        return execute_tactus(snippet, web_ui_context=web_ui_context)
    return _response_envelope(
        ok=False,
        value=None,
        trace_id=str(uuid.uuid4()),
        started_at=time.monotonic(),
        api_calls=[],
        error=_structured_error("invalid_request", f"unknown harness: {harness}"),
    )


def execute_tactus(tactus: str, *, web_ui_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a short Papyrus Tactus snippet and return a structured envelope.

    This is the single Papyrus newsroom agent tool. The snippet receives a
    global ``papyrus`` host module plus helper aliases such as ``api_list``,
    ``docs_list``, ``assignment_context``, ``assignment_agent_context``,
    ``biblicus_query``, ``plan_research_update``, and ``plan_draft_update``.
    """
    from papyrus_content.env import load_dotenv

    load_dotenv()

    started = time.monotonic()
    trace_id = str(uuid.uuid4())
    if not isinstance(tactus, str) or not tactus.strip():
        return _response_envelope(
            ok=False,
            value=None,
            trace_id=trace_id,
            started_at=started,
            api_calls=[],
            error=_structured_error("invalid_request", "tactus must be a non-empty string"),
        )
    tactus = _normalize_tactus_snippet(tactus)
    if not tactus.strip():
        return _response_envelope(
            ok=False,
            value=None,
            trace_id=trace_id,
            started_at=started,
            api_calls=[],
            error=_structured_error("invalid_request", "tactus must be a non-empty string"),
        )

    unsupported_error = _unsupported_snippet_error(tactus)
    if unsupported_error is not None:
        return _response_envelope(
            ok=False,
            value=None,
            trace_id=trace_id,
            started_at=started,
            api_calls=[],
            error=unsupported_error,
        )

    papyrus = PapyrusRuntimeModule(web_ui_context=web_ui_context)
    try:
        from tactus.adapters.memory import MemoryStorage
        from tactus.core import TactusRuntime

        async def run() -> Any:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                runtime = TactusRuntime(
                    procedure_id=f"papyrus_execute_tactus_{trace_id}",
                    storage_backend=MemoryStorage(),
                    run_id=trace_id,
                    source_file_path="<papyrus execute_tactus>",
                )
                _bind_papyrus_runtime(runtime, papyrus)
                return await runtime.execute(_wrap_tactus_snippet(tactus), context={}, format="lua")

        runtime_result = _run_async(run())
        if not isinstance(runtime_result, dict):
            return _response_envelope(
                ok=True,
                value=runtime_result,
                trace_id=trace_id,
                started_at=started,
                api_calls=papyrus.api_calls,
            )

        ok = bool(runtime_result.get("success"))
        value = runtime_result.get("result")
        return _response_envelope(
            ok=ok,
            value=value,
            trace_id=trace_id,
            started_at=started,
            api_calls=papyrus.api_calls,
            error=None if ok else _structured_error("tactus_execution_failed", str(runtime_result.get("error") or "Tactus execution failed")),
        )
    except Exception as exc:  # noqa: BLE001
        return _response_envelope(
            ok=False,
            value=None,
            trace_id=trace_id,
            started_at=started,
            api_calls=papyrus.api_calls,
            error=_structured_error("runtime_error", str(exc), exc),
        )


EXECUTE_TACTUS_DESCRIPTION = """Execute a short Tactus snippet inside the Papyrus newsroom runtime.

Use this as the only tool for Papyrus newsroom agent work. The runtime injects a
global `papyrus` host module and canonical PascalCase resource tables such as
`Assignment`.

Ground rules:
- `papyrus` is already available; do not require arbitrary Python modules.
- Prefer canonical resources for writes: `Reference.create{ url = "https://...", apply = true }`
  and `Assignment.create{ type = "research", title = "...", apply = true }`.
- Use table arguments: `Reference.get{ id = "..." }`, `Assignment.get{ id = "assignment-123" }`.
- The runtime returns the last Papyrus operation if your snippet does not return
  explicitly.
- Use `api_list{}` and `docs_list{}` for discovery instead of guessing.
- Load `docs_get{ id = "resources.Reference" }` or `docs_get{ id = "resources.Assignment" }`
  before non-trivial writes.
- Record-plan helpers are dry-run builders; they do not write GraphQL records.

Example:
```tactus
return Assignment.create{
  type = "research",
  title = "Research recent AI newsroom reliability metrics",
  summary = "Find evidence and angles for an edition-candidate story.",
  sectionKey = "technology",
  researchMode = "source_discovery",
  apply = true,
}
```
"""
