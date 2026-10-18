from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from .accession import execute_reference_accession_assignment
from .assignments import apply_assignment_action, assignment_metadata
from .catalog import message_record, semantic_relation_record
from .content_item_lifecycle import (
    content_item_lineage_for_new_assignment,
    plan_content_item_backfill,
    plan_undrafted_backfill_story_demotion,
    require_assignment_content_item_lineage_id,
)
from .copywriting import COPYWRITING_ASSIGNMENT_TYPES, build_copywriting_run_plan
from .env import PAPYRUS_ROOT
from .graphql_authoring import PapyrusGraphQLAuthoringClient
from .ids import hash_short, knowledge_corpus_id, safe_id
from .model_defaults import DEFAULT_REFERENCE_SUMMARY_MODEL
from .model_attachments import download_attachment_buffer, parse_jsonish
from .newsroom_summary import (
    update_newsroom_summary_after_assignment_creates,
    update_newsroom_summary_after_extracted_text_attachments,
    update_newsroom_summary_after_reference_registration,
)
from .options import (
    normalize_non_negative_integer,
    normalize_positive_integer,
    normalize_string,
    parse_boolean_option,
    parse_comma_list,
    parse_options,
    resolve_mutation_apply,
)
from .records import apply_record_changes, build_record_changes, build_record_changes_tolerating_optional_models
from .reference_policy import normalize_reference_curation_status
from .reference_url_text import run_reference_url_text_extraction
from .reference_metadata_generation import run_reference_metadata_generation_from_extracted_text
from .reporting_packet_review import build_reporting_packet_review_plan
from .steering import default_corpus_key

RESEARCH_MODES = frozenset({"internal_brief", "source_discovery", "full_research"})
REPORTING_RECOMMENDATIONS = frozenset({"select", "merge", "brief", "hold", "kill"})
ASSIGNMENT_RUN_DEFAULT_KNOWLEDGE_INCLUDE_KINDS = (
    "reference",
    "item",
    "category",
    "semanticNode",
    "newsroomSection",
    "assignment",
    "message",
)
ASSIGNMENT_RUN_DEFAULT_KNOWLEDGE_INCLUDE_MESSAGE_KINDS = ("insight",)
ASSIGNMENT_RUN_DEFAULT_KNOWLEDGE_INCLUDE_ASSIGNMENT_TYPES = ("research.*", "reporting.*")


def normalize_research_mode(value: Any) -> str:
    normalized = (normalize_string(value) or "source_discovery").replace("-", "_")
    if normalized not in RESEARCH_MODES:
        raise ValueError(
            f"Invalid --research-mode {value}. Expected one of: internal_brief, source_discovery, full_research."
        )
    return normalized


def assignment_run_knowledge_scope(options: dict[str, Any]) -> dict[str, Any]:
    include_kinds = parse_comma_list(options.get("knowledge-include-kinds")) or list(
        ASSIGNMENT_RUN_DEFAULT_KNOWLEDGE_INCLUDE_KINDS
    )
    exclude_kinds = parse_comma_list(options.get("knowledge-exclude-kinds")) or []
    include_message_kinds = parse_comma_list(options.get("knowledge-include-message-kinds")) or list(
        ASSIGNMENT_RUN_DEFAULT_KNOWLEDGE_INCLUDE_MESSAGE_KINDS
    )
    exclude_message_kinds = parse_comma_list(options.get("knowledge-exclude-message-kinds")) or []
    include_assignment_types = parse_comma_list(options.get("knowledge-include-assignment-types")) or list(
        ASSIGNMENT_RUN_DEFAULT_KNOWLEDGE_INCLUDE_ASSIGNMENT_TYPES
    )
    exclude_assignment_types = parse_comma_list(options.get("knowledge-exclude-assignment-types")) or []
    return {
        "includeObjectKinds": include_kinds,
        "excludeObjectKinds": exclude_kinds,
        "includeMessageKinds": include_message_kinds,
        "excludeMessageKinds": exclude_message_kinds,
        "includeAssignmentTypeKeys": include_assignment_types,
        "excludeAssignmentTypeKeys": exclude_assignment_types,
    }


def semantic_state_key(kind: str, lineage_id: str) -> str:
    return f"{kind}#{lineage_id}#current"


def assignment_section_key(assignment: dict[str, Any]) -> str | None:
    return normalize_string(assignment.get("sectionKey")) or normalize_string(assignment.get("sectionId"))


def assignment_sort_key(assignment: dict[str, Any]) -> str:
    priority = str(assignment.get("priority") if assignment.get("priority") is not None else 999999).zfill(6)
    created_at = assignment.get("createdAt") or ""
    record_id = assignment.get("id") or ""
    return f"{priority}#{created_at}#{record_id}"


def run_papyrus_cli_json(args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        ["poetry", "run", "papyrus", *args],
        cwd=PAPYRUS_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "papyrus command failed")
    return json.loads(completed.stdout)


def create_research_assignment(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> dict[str, Any]:
    apply = resolve_mutation_apply(options, "assignments create-research")
    title = normalize_string(options.get("title"))
    if not title:
        raise ValueError("assignments create-research requires --title <text>.")
    section_key = normalize_string(options.get("section"))
    corpus_key = normalize_string(options.get("corpus-key")) or default_corpus_key()
    research_mode = normalize_research_mode(options.get("research-mode") or options.get("researchMode"))
    now = _utc_now()
    assignment_type_key = normalize_string(options.get("type")) or "research.edition-candidate"
    tavily_deep = assignment_type_key == "research.tavily-deep"
    status = normalize_string(options.get("status")) or "open"
    priority = normalize_non_negative_integer(options.get("priority"), "--priority") or 50
    queue_key = normalize_string(options.get("queue")) or f"research:{section_key or 'unsectioned'}:exploratory"
    summary = normalize_string(options.get("summary")) or normalize_string(options.get("brief")) or title
    brief = normalize_string(options.get("brief")) or summary
    instructions = normalize_string(options.get("instructions")) or normalize_string(options.get("research-questions")) or ""
    topic_scope = parse_comma_list(options.get("topic-scope") or options.get("topic-scope-category-keys")) or []
    primary_focus = normalize_string(options.get("primary-focus-category-key")) or normalize_string(
        options.get("primary-focus")
    )
    section = client.get_record("NewsroomSection", section_key) if section_key else None
    if section_key and not section:
        raise ValueError(
            f"Unknown NewsroomSection for --section {section_key}. "
            "Run: poetry run papyrus sections import --config corpora/papyrus-newsroom-sections.yml"
        )
    assignment_id = normalize_string(options.get("id")) or (
        f"assignment-research-{safe_id(title)[:80]}-{timestamp_for_path(now)}"
    )
    content_item_lineage_id, new_content_item_version = content_item_lineage_for_new_assignment(
        requested_lineage_id=normalize_string(options.get("content-item")),
        assignment_id=assignment_id,
        title=title,
        summary=summary,
        section_key=section_key,
        stage="research",
        actor_label=normalize_string(options.get("actor-label")) or "papyrus-cli",
        now=now,
    )
    assignment = {
        "id": assignment_id,
        "assignmentTypeKey": assignment_type_key,
        "queueKey": queue_key,
        "queueStatusKey": f"{queue_key}#{status}",
        "status": status,
        "priority": priority,
        "title": title,
        "summary": summary,
        "brief": brief,
        "instructions": instructions,
        "metadata": json.dumps(
            {
                "kind": "research.assignment.created",
                "researchMode": research_mode,
                "corpusKey": corpus_key,
                "sectionKey": section_key,
                "sectionTitle": (section or {}).get("title") or (section or {}).get("displayName") or section_key,
                "sectionType": _normalize_section_type((section or {}).get("type") or options.get("section-type")),
                "topicScopeCategoryKeys": topic_scope,
                "primaryFocusCategoryKey": primary_focus,
                "contextProfile": "researcher",
                "createdBy": "assignments create-research",
                **(
                    {
                        "researchBackend": "tavily_deep",
                        "tavilyModel": normalize_string(options.get("tavily-model")) or "auto",
                    }
                    if tavily_deep
                    else {}
                ),
            }
        ),
        "corpusId": normalize_string(options.get("corpus-id")) or knowledge_corpus_id({"key": corpus_key}),
        "categorySetId": normalize_string(options.get("category-set")),
        "sectionId": (section or {}).get("id") or section_key,
        "sectionKey": section_key,
        "sectionType": _normalize_section_type((section or {}).get("type") or options.get("section-type")),
        "sectionStatusKey": f"{section_key}#{status}" if section_key else None,
        "sectionQueueStatusKey": f"{section_key}#{queue_key}#{status}" if section_key else None,
        "primaryFocusCategoryKey": primary_focus,
        "topicScopeCategoryKeys": topic_scope,
        "createdBy": normalize_string(options.get("actor-label")) or "papyrus-cli",
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": f"assignment#{status}",
        "itemLineageId": content_item_lineage_id,
    }
    event = {
        "id": f"assignment-event-{assignment_id}-created",
        "assignmentId": assignment_id,
        "assignmentTypeKey": assignment_type_key,
        "queueKey": queue_key,
        "eventType": "created",
        "fromStatus": None,
        "toStatus": status,
        "actorSub": normalize_string(options.get("actor-sub")),
        "actorLabel": normalize_string(options.get("actor-label")) or "Papyrus content CLI",
        "note": normalize_string(options.get("note")) or f"Created research assignment: {title}",
        "createdAt": now,
    }
    records = [
        {"modelName": "Assignment", "expected": assignment},
        {"modelName": "AssignmentEvent", "expected": event},
    ]
    if new_content_item_version:
        records.append({"modelName": "Item", "expected": new_content_item_version})
    changes = build_record_changes(client, records)
    result = {
        "assignmentId": assignment_id,
        "assignmentTypeKey": assignment_type_key,
        "contentItemLineageId": content_item_lineage_id,
        "status": status,
        "sectionKey": section_key,
        "queueKey": queue_key,
        "researchMode": research_mode,
        "changes": _count_delta(changes, "action"),
        "next": (
            (
                f"poetry run papyrus assignments run-tavily-deep-research --assignment {assignment_id} "
                f"--corpus-key {corpus_key} --wait"
                if tavily_deep
                else f"poetry run papyrus assignments run-research --assignment {assignment_id} "
                f"--corpus-key {corpus_key} --research-mode {research_mode}"
            )
            if apply
            else f"poetry run papyrus assignments create-research --title {json.dumps(title)} "
            f"--type {assignment_type_key} "
            f"--section {section_key or '<section-key>'} --corpus-key {corpus_key} "
            f"--research-mode {research_mode}"
        ),
    }
    if not apply:
        _print_create_research_summary("dry-run", result, changes)
        print("assignments\tcreate-research\tapply\tskipped\tuse --dry-run to preview without writes")
        print(f"assignments\tcreate-research\tnext\t{result['next']}")
        return result
    apply_record_changes(client, changes)
    update_newsroom_summary_after_assignment_creates(
        client,
        changes,
        actor_label=event["actorLabel"],
        reason=f"assignments create-research {assignment_id}",
    )
    _print_create_research_summary("apply", result, changes)
    print(f"assignments\tcreate-research\tnext\t{result['next']}")
    return result


def create_reporting_assignment(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> dict[str, Any]:
    apply = resolve_mutation_apply(options, "assignments create-reporting")
    title = normalize_string(options.get("title"))
    if not title:
        raise ValueError("assignments create-reporting requires --title <text>.")
    section_key = normalize_string(options.get("section"))
    corpus_key = normalize_string(options.get("corpus-key")) or default_corpus_key()
    now = _utc_now()
    assignment_type_key = normalize_string(options.get("type")) or "reporting.edition-candidate"
    if assignment_type_key != "reporting.edition-candidate":
        raise ValueError("assignments create-reporting only supports --type reporting.edition-candidate.")
    status = normalize_string(options.get("status")) or "open"
    priority = normalize_non_negative_integer(options.get("priority"), "--priority") or 50
    queue_key = normalize_string(options.get("queue")) or f"reporting:{section_key or 'unsectioned'}:exploratory"
    summary = normalize_string(options.get("summary")) or normalize_string(options.get("brief")) or title
    brief = normalize_string(options.get("brief")) or summary
    instructions = normalize_string(options.get("instructions")) or "Build a private reporting_context_packet only."
    topic_scope = parse_comma_list(options.get("topic-scope") or options.get("topic-scope-category-keys")) or []
    primary_focus = normalize_string(options.get("primary-focus-category-key")) or normalize_string(
        options.get("primary-focus")
    )
    section = client.get_record("NewsroomSection", section_key) if section_key else None
    if section_key and not section:
        raise ValueError(
            f"Unknown NewsroomSection for --section {section_key}. "
            "Run: poetry run papyrus sections import --config corpora/papyrus-newsroom-sections.yml"
        )
    assignment_id = normalize_string(options.get("id")) or (
        f"assignment-reporting-{safe_id(title)[:80]}-{timestamp_for_path(now)}"
    )
    content_item_lineage_id, new_content_item_version = content_item_lineage_for_new_assignment(
        requested_lineage_id=normalize_string(options.get("content-item")),
        assignment_id=assignment_id,
        title=title,
        summary=summary,
        section_key=section_key,
        stage="report",
        actor_label=normalize_string(options.get("actor-label")) or "papyrus-cli",
        now=now,
    )
    assignment = {
        "id": assignment_id,
        "assignmentTypeKey": assignment_type_key,
        "queueKey": queue_key,
        "queueStatusKey": f"{queue_key}#{status}",
        "status": status,
        "priority": priority,
        "title": title,
        "summary": summary,
        "brief": brief,
        "instructions": instructions,
        "metadata": json.dumps(
            {
                "kind": "reporting.assignment.created",
                "corpusKey": corpus_key,
                "sectionKey": section_key,
                "sectionTitle": (section or {}).get("title") or (section or {}).get("displayName") or section_key,
                "sectionType": _normalize_section_type((section or {}).get("type") or options.get("section-type")),
                "topicScopeCategoryKeys": topic_scope,
                "primaryFocusCategoryKey": primary_focus,
                "contextProfile": "reporting",
                "createdBy": "assignments create-reporting",
            }
        ),
        "corpusId": normalize_string(options.get("corpus-id")) or knowledge_corpus_id({"key": corpus_key}),
        "categorySetId": normalize_string(options.get("category-set")),
        "sectionId": (section or {}).get("id") or section_key,
        "sectionKey": section_key,
        "sectionType": _normalize_section_type((section or {}).get("type") or options.get("section-type")),
        "sectionStatusKey": f"{section_key}#{status}" if section_key else None,
        "sectionQueueStatusKey": f"{section_key}#{queue_key}#{status}" if section_key else None,
        "primaryFocusCategoryKey": primary_focus,
        "topicScopeCategoryKeys": topic_scope,
        "createdBy": normalize_string(options.get("actor-label")) or "papyrus-cli",
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": f"assignment#{status}",
        "itemLineageId": content_item_lineage_id,
    }
    event = {
        "id": f"assignment-event-{assignment_id}-created",
        "assignmentId": assignment_id,
        "assignmentTypeKey": assignment_type_key,
        "queueKey": queue_key,
        "eventType": "created",
        "fromStatus": None,
        "toStatus": status,
        "actorSub": normalize_string(options.get("actor-sub")),
        "actorLabel": normalize_string(options.get("actor-label")) or "Papyrus content CLI",
        "note": normalize_string(options.get("note")) or f"Created reporting assignment: {title}",
        "createdAt": now,
    }
    records = [
        {"modelName": "Assignment", "expected": assignment},
        {"modelName": "AssignmentEvent", "expected": event},
    ]
    if new_content_item_version:
        records.append({"modelName": "Item", "expected": new_content_item_version})
    changes = build_record_changes(client, records)
    result = {
        "assignmentId": assignment_id,
        "assignmentTypeKey": assignment_type_key,
        "contentItemLineageId": content_item_lineage_id,
        "status": status,
        "sectionKey": section_key,
        "queueKey": queue_key,
        "corpusKey": corpus_key,
        "changes": _count_delta(changes, "action"),
        "next": (
            f"poetry run papyrus assignments run-reporting --assignment {assignment_id} "
            f"--corpus-key {corpus_key}"
            if apply
            else f"poetry run papyrus assignments create-reporting --title {json.dumps(title)} "
            f"--section {section_key or '<section-key>'} --corpus-key {corpus_key}"
        ),
    }
    if not apply:
        _print_create_reporting_summary("dry-run", result, changes)
        print("assignments\tcreate-reporting\tapply\tskipped\tuse --dry-run to preview without writes")
        print(f"assignments\tcreate-reporting\tnext\t{result['next']}")
        return result
    apply_record_changes(client, changes)
    update_newsroom_summary_after_assignment_creates(
        client,
        changes,
        actor_label=event["actorLabel"],
        reason=f"assignments create-reporting {assignment_id}",
    )
    _print_create_reporting_summary("apply", result, changes)
    print(f"assignments\tcreate-reporting\tnext\t{result['next']}")
    return result


def run_research_assignment(flags: list[str]) -> None:
    from .cloud_procedures import start_cloud_procedure_run
    from .graphql_authoring import create_authoring_client
    from .ids import safe_id

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "assignments run-research")
    assignment_id = normalize_string(options.get("assignment"))
    if not assignment_id:
        raise ValueError("assignments run-research requires --assignment <id>.")
    corpus_key = normalize_string(options.get("corpus-key")) or default_corpus_key()
    research_mode = normalize_research_mode(
        options.get("research-mode") or options.get("researchMode") or "source_discovery"
    )
    run_id = normalize_string(options.get("run-id")) or (
        f"research-{safe_id(assignment_id)[:60]}-{timestamp_for_path()}"
    )
    run_dir = PAPYRUS_ROOT / ".papyrus-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    result_path = run_dir / "research-result.json"
    source_path = run_dir / "research.cloud.tac"
    stdout_path = run_dir / "research.stdout.log"
    stderr_path = run_dir / "research.stderr.log"
    question = normalize_string(options.get("research-questions") or options.get("question")) or ""
    context_profile = normalize_string(options.get("context-profile")) or "researcher"
    max_evidence_items = normalize_non_negative_integer(options.get("max-evidence-items"), "--max-evidence-items") or 20
    knowledge_query_scope = assignment_run_knowledge_scope(options)
    started_at = _utc_now()
    client, _ = create_authoring_client()
    run = start_cloud_procedure_run(
        client=client,
        alias="assignments.run-research",
        actor_label=normalize_string(options.get("actor")) or "papyrus-cli",
        title=f"Run research assignment {assignment_id}",
        summary="Triggered by assignments run-research via cloud procedure dispatch.",
        input_payload={
            "assignment_item_id": assignment_id,
            "corpus_key": corpus_key,
            "context_profile": context_profile,
            "research_mode": research_mode,
            "research_questions": question,
            "max_evidence_items": max_evidence_items,
            "knowledge_query_scope": knowledge_query_scope,
        },
        run_dir=run_dir,
        source_path=source_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    finished_at = _utc_now()
    parsed = run.get("output")
    if not isinstance(parsed, dict):
        raise ValueError(
            f"Cloud procedure output for assignment {assignment_id} did not return a JSON object payload."
        )
    research = research_packet_from_procedure_output(parsed)
    if not research:
        research = parsed.get("research_packet") or parsed.get("researchPacket")
    if not research:
        raise ValueError(
            f"Cloud procedure output for assignment {assignment_id} is missing research_packet. "
            "Run poetry run papyrus procedures seed-required if procedure seeds are stale."
        )
    packet = normalize_research_packet_bundle(
        research,
        assignment={
            "id": assignment_id,
            "assignmentTypeKey": "research.edition-candidate",
            "queueKey": "",
        },
        assignment_meta={"researchMode": research_mode, "corpusKey": corpus_key},
        research_mode=research_mode,
    )
    validate_research_packet_mode(packet)
    trace = packet.get("researchTrace") or {}
    discovery_boundary = _parse_object(trace.get("discoveryBoundary") or trace.get("discovery_boundary"))
    retry_count_raw = parsed.get("retry_count") or parsed.get("retryCount") or trace.get("retryCount") or trace.get("retry_count") or 0
    try:
        retry_count = max(0, int(retry_count_raw))
    except (TypeError, ValueError):
        retry_count = 0
    validation_failures_raw = (
        parsed.get("validation_failures")
        or parsed.get("validationFailures")
        or trace.get("validationFailures")
        or trace.get("validation_failures")
    )
    validation_failures = (
        [str(entry) for entry in validation_failures_raw]
        if isinstance(validation_failures_raw, list)
        else []
    )
    result = {
        "ok": True,
        "command": "assignments run-research",
        "action": "apply" if apply else "dry-run",
        "runId": run_id,
        "assignmentId": assignment_id,
        "researchMode": research_mode,
        "corpusKey": corpus_key,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "exitStatus": 0,
        "signal": None,
        "stdoutPath": str(stdout_path),
        "stderrPath": str(stderr_path),
        "fallback": None,
        "resultPath": str(result_path),
        "llmContextSummaryPath": run.get("llmContextSummaryPath"),
        "llmContextCallsPath": run.get("llmContextCallsPath"),
        "llmContextCallCount": run.get("llmContextCallCount"),
        "llmContextLlmCallsPath": run.get("llmContextLlmCallsPath"),
        "llmContextLlmCallCount": run.get("llmContextLlmCallCount"),
        "parsed": True,
        "packet": {
            "summary": packet.get("summary"),
            "proposedReferenceCount": len(packet.get("proposedReferences") or []),
            "sourceSnapshotCount": len(packet.get("sourceSnapshots") or []),
            "evidenceItemCount": len(packet.get("evidenceItemIds") or []),
            "blockedReason": (packet.get("sourceDiscovery") or {}).get("blockedReason"),
            "webSearchPath": normalize_string(discovery_boundary.get("webSearchPath") or discovery_boundary.get("web_search_path")),
            "searchResultCount": discovery_boundary.get("searchResultCount"),
            "searchMetadataShapeOk": discovery_boundary.get("searchMetadataShapeOk"),
            "discoveryAttemptsTotal": discovery_boundary.get("discoveryAttemptsTotal"),
            "discoveryQueriesTried": _parse_array(
                discovery_boundary.get("discoveryQueriesTried") or discovery_boundary.get("discovery_queries_tried")
            ),
            "discoveryResultCounts": _parse_array(
                discovery_boundary.get("discoveryResultCounts") or discovery_boundary.get("discovery_result_counts")
            ),
            "discoveryTerminalState": normalize_string(
                discovery_boundary.get("discoveryTerminalState") or discovery_boundary.get("discovery_terminal_state")
            ),
            "discoveryBlockedReason": normalize_string(
                discovery_boundary.get("blockedReason") or discovery_boundary.get("blocked_reason")
            ),
            "firstProposalUrl": ((packet.get("proposedReferences") or [{}])[0] or {}).get("url"),
            "attempts": retry_count + 1,
            "knowledgeScopeIncludeKinds": knowledge_query_scope.get("includeObjectKinds") or [],
            "knowledgeScopeIncludeMessageKinds": knowledge_query_scope.get("includeMessageKinds") or [],
            "knowledgeScopeIncludeAssignmentTypes": knowledge_query_scope.get("includeAssignmentTypeKeys") or [],
            "recoveryPath": normalize_string(
                parsed.get("recovery_path") or parsed.get("recoveryPath") or trace.get("recoveryPath") or trace.get("recovery_path")
            ),
            "firstValidationError": validation_failures[0] if validation_failures else None,
            "lastValidationError": validation_failures[-1] if validation_failures else None,
        },
        "next": None,
    }
    if not apply:
        result["next"] = (
            f"poetry run papyrus assignments apply-research-packet "
            f"--assignment {assignment_id} --research-json {result_path}"
        )
    result_path.write_text(
        json.dumps(
            {
                **result,
                "cloudProcedure": {
                    "runId": run.get("id"),
                    "procedureKey": run.get("procedureKey"),
                    "procedureVersionId": run.get("procedureVersionId"),
                    "procedureVersionNumber": run.get("procedureVersionNumber"),
                    "runStatus": run.get("runStatus"),
                    "sourcePath": run.get("sourcePath"),
                },
                "commandLine": run.get("commandLine"),
                "value": parsed,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if apply:
        apply_research_packet(
            client,
            {
                "assignment": assignment_id,
                "research-json": json.dumps(research),
                "research-mode": research_mode,
                **({"json": True} if options.get("json") else {}),
            },
        )
        return
    if options.get("json"):
        print(json.dumps(result, indent=2))
        return
    _print_research_run_summary(result)


def run_reporting_assignment(flags: list[str]) -> None:
    from .cloud_procedures import start_cloud_procedure_run
    from .graphql_authoring import create_authoring_client
    from .ids import safe_id

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "assignments run-reporting")
    assignment_id = normalize_string(options.get("assignment"))
    if not assignment_id:
        raise ValueError("assignments run-reporting requires --assignment <id>.")
    corpus_key = normalize_string(options.get("corpus-key")) or default_corpus_key()
    run_id = normalize_string(options.get("run-id")) or (
        f"reporting-{safe_id(assignment_id)[:60]}-{timestamp_for_path()}"
    )
    run_dir = PAPYRUS_ROOT / ".papyrus-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    result_path = run_dir / "reporting-result.json"
    source_path = run_dir / "reporting.cloud.tac"
    stdout_path = run_dir / "reporting.stdout.log"
    stderr_path = run_dir / "reporting.stderr.log"
    context_profile = normalize_string(options.get("context-profile")) or "reporting"
    knowledge_query_scope = assignment_run_knowledge_scope(options)
    started_at = _utc_now()
    client, _ = create_authoring_client()
    assignment = client.get_record("Assignment", assignment_id)
    if not assignment:
        raise ValueError(f"Assignment not found: {assignment_id}.")
    assignment_meta = assignment_metadata(client, assignment)
    run = start_cloud_procedure_run(
        client=client,
        alias="assignments.run-reporting",
        actor_label=normalize_string(options.get("actor")) or "papyrus-cli",
        title=f"Run reporting assignment {assignment_id}",
        summary="Triggered by assignments run-reporting via cloud procedure dispatch.",
        input_payload={
            "assignment_item_id": assignment_id,
            "corpus_key": corpus_key,
            "context_profile": context_profile,
            "knowledge_query_scope": knowledge_query_scope,
            "source_research_assignment_id": normalize_string(options.get("source-research-assignment-id"))
            or normalize_string(assignment_meta.get("sourceResearchAssignmentId"))
            or None,
            "source_research_packet_id": normalize_string(options.get("source-research-packet-id"))
            or normalize_string(assignment_meta.get("sourceResearchPacketId"))
            or None,
        },
        run_dir=run_dir,
        source_path=source_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    finished_at = _utc_now()
    parsed = run.get("output")
    if not isinstance(parsed, dict):
        raise ValueError(
            f"Cloud procedure output for assignment {assignment_id} did not return a JSON object payload."
        )
    reporting = parsed.get("reporting_context_packet") or parsed.get("reportingContextPacket")
    if not reporting:
        raise ValueError(
            f"Cloud procedure output for assignment {assignment_id} is missing reporting_context_packet. "
            "Run poetry run papyrus procedures seed-required if procedure seeds are stale."
        )
    packet = normalize_reporting_packet_bundle(
        reporting,
        assignment=assignment,
        assignment_meta=assignment_meta,
    )
    validate_reporting_packet(packet)
    retry_count_raw = parsed.get("retry_count") or parsed.get("retryCount") or 0
    try:
        retry_count = max(0, int(retry_count_raw))
    except (TypeError, ValueError):
        retry_count = 0
    validation_failures_raw = parsed.get("validation_failures") or parsed.get("validationFailures")
    validation_failures = [str(entry) for entry in validation_failures_raw] if isinstance(validation_failures_raw, list) else []
    result = {
        "ok": True,
        "command": "assignments run-reporting",
        "action": "apply" if apply else "dry-run",
        "runId": run_id,
        "assignmentId": assignment_id,
        "corpusKey": corpus_key,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "exitStatus": 0,
        "stdoutPath": str(stdout_path),
        "stderrPath": str(stderr_path),
        "resultPath": str(result_path),
        "llmContextSummaryPath": run.get("llmContextSummaryPath"),
        "llmContextCallsPath": run.get("llmContextCallsPath"),
        "llmContextCallCount": run.get("llmContextCallCount"),
        "llmContextLlmCallsPath": run.get("llmContextLlmCallsPath"),
        "llmContextLlmCallCount": run.get("llmContextLlmCallCount"),
        "parsed": True,
        "packet": {
            "summary": packet.get("summary"),
            "editorRecommendation": packet.get("editorRecommendation"),
            "acceptedReferenceCount": len(packet.get("acceptedReferenceIds") or []),
            "proposedReferenceCount": len(packet.get("proposedReferences") or []),
            "sourceTrailCount": len(packet.get("sourceTrail") or []),
            "knowledgeQueryCount": len(packet.get("knowledgeQueries") or []),
            "papyrusUriCount": len(packet.get("papyrusUrisInspected") or []),
            "knowledgeBlockedReason": packet.get("knowledgeBlockedReason"),
            "knowledgeOrientationAttempted": packet.get("knowledgeOrientationAttempted"),
            "knowledgeOrientationCompleted": packet.get("knowledgeOrientationCompleted"),
            "reportingPathMode": packet.get("reportingPathMode"),
            "verificationNeedCount": len(packet.get("verificationNeeds") or []),
            "firstProposalUrl": ((packet.get("proposedReferences") or [{}])[0] or {}).get("url"),
            "attempts": retry_count + 1,
            "knowledgeScopeIncludeKinds": knowledge_query_scope.get("includeObjectKinds") or [],
            "knowledgeScopeIncludeMessageKinds": knowledge_query_scope.get("includeMessageKinds") or [],
            "knowledgeScopeIncludeAssignmentTypes": knowledge_query_scope.get("includeAssignmentTypeKeys") or [],
            "firstValidationError": validation_failures[0] if validation_failures else None,
            "lastValidationError": validation_failures[-1] if validation_failures else None,
        },
        "next": None,
    }
    if not apply:
        result["next"] = (
            f"poetry run papyrus assignments apply-reporting-packet "
            f"--assignment {assignment_id} --reporting-json {result_path}"
        )
    result_path.write_text(
        json.dumps(
            {
                **result,
                "cloudProcedure": {
                    "runId": run.get("id"),
                    "procedureKey": run.get("procedureKey"),
                    "procedureVersionId": run.get("procedureVersionId"),
                    "procedureVersionNumber": run.get("procedureVersionNumber"),
                    "runStatus": run.get("runStatus"),
                    "sourcePath": run.get("sourcePath"),
                },
                "commandLine": run.get("commandLine"),
                "value": parsed,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if apply:
        apply_reporting_packet(
            client,
            {
                "assignment": assignment_id,
                "reporting-json": json.dumps(reporting),
            },
        )
        return
    if options.get("json"):
        print(json.dumps(result, indent=2))
        return
    _print_reporting_run_summary(result)


def _print_research_run_summary(result: dict[str, Any]) -> None:
    print(f"assignments\trun-research\taction\t{result.get('action')}")
    print(f"assignments\trun-research\trun\t{result.get('runId')}")
    print(f"assignments\trun-research\tassignment\t{result.get('assignmentId')}")
    print(f"assignments\trun-research\tstatus\t{result.get('exitStatus') or ''}")
    print(f"assignments\trun-research\tparsed\t{result.get('parsed')}")
    packet = result.get("packet") or {}
    if packet:
        print(
            f"assignments\trun-research\tcounts\tevidence={packet.get('evidenceItemCount')}\t"
            f"sources={packet.get('sourceSnapshotCount')}\tproposals={packet.get('proposedReferenceCount')}"
        )
        print(f"assignments\trun-research\tattempts\t{packet.get('attempts')}")
        if packet.get("recoveryPath"):
            print(f"assignments\trun-research\trecovery\t{packet.get('recoveryPath')}")
        if packet.get("firstValidationError"):
            print(f"assignments\trun-research\tfirst-validation-error\t{packet.get('firstValidationError')}")
        if packet.get("lastValidationError"):
            print(f"assignments\trun-research\tlast-validation-error\t{packet.get('lastValidationError')}")
        if packet.get("firstProposalUrl"):
            print(f"assignments\trun-research\tfirst-proposal\t{packet.get('firstProposalUrl')}")
        if packet.get("blockedReason"):
            print(f"assignments\trun-research\tblocked\t{packet.get('blockedReason')}")
        if packet.get("webSearchPath"):
            print(f"assignments\trun-research\tweb-search-path\t{packet.get('webSearchPath')}")
        if packet.get("searchResultCount") is not None:
            print(f"assignments\trun-research\tsearch-result-count\t{packet.get('searchResultCount')}")
        if packet.get("searchMetadataShapeOk") is not None:
            print(f"assignments\trun-research\tsearch-metadata-shape-ok\t{packet.get('searchMetadataShapeOk')}")
        if packet.get("discoveryAttemptsTotal") is not None:
            print(f"assignments\trun-research\tdiscovery-attempts-total\t{packet.get('discoveryAttemptsTotal')}")
        if packet.get("discoveryQueriesTried"):
            print(
                "assignments\trun-research\tdiscovery-queries-tried\t"
                + ",".join(str(value) for value in packet.get("discoveryQueriesTried") or [])
            )
        if packet.get("discoveryResultCounts"):
            print(
                "assignments\trun-research\tdiscovery-result-counts\t"
                + ",".join(str(value) for value in packet.get("discoveryResultCounts") or [])
            )
        if packet.get("discoveryTerminalState"):
            print(f"assignments\trun-research\tdiscovery-terminal-state\t{packet.get('discoveryTerminalState')}")
        if packet.get("discoveryBlockedReason"):
            print(f"assignments\trun-research\tdiscovery-blocked\t{packet.get('discoveryBlockedReason')}")
        if packet.get("knowledgeScopeIncludeKinds"):
            print(
                "assignments\trun-research\tknowledge-scope-kinds\t"
                + ",".join(str(value) for value in packet.get("knowledgeScopeIncludeKinds") or [])
            )
        if packet.get("knowledgeScopeIncludeMessageKinds"):
            print(
                "assignments\trun-research\tknowledge-scope-message-kinds\t"
                + ",".join(str(value) for value in packet.get("knowledgeScopeIncludeMessageKinds") or [])
            )
        if packet.get("knowledgeScopeIncludeAssignmentTypes"):
            print(
                "assignments\trun-research\tknowledge-scope-assignment-types\t"
                + ",".join(str(value) for value in packet.get("knowledgeScopeIncludeAssignmentTypes") or [])
            )
    print(f"assignments\trun-research\tresult\t{result.get('resultPath')}")
    print(f"assignments\trun-research\tstdout\t{result.get('stdoutPath')}")
    print(f"assignments\trun-research\tstderr\t{result.get('stderrPath')}")
    if result.get("llmContextSummaryPath"):
        print(f"assignments\trun-research\tllm-context-summary\t{result.get('llmContextSummaryPath')}")
    if result.get("llmContextCallsPath"):
        print(f"assignments\trun-research\tllm-context-calls\t{result.get('llmContextCallsPath')}")
    if result.get("llmContextCallCount") is not None:
        print(f"assignments\trun-research\tllm-context-call-count\t{result.get('llmContextCallCount')}")
    if result.get("llmContextLlmCallsPath"):
        print(f"assignments\trun-research\tllm-context-llm-calls\t{result.get('llmContextLlmCallsPath')}")
    if result.get("llmContextLlmCallCount") is not None:
        print(f"assignments\trun-research\tllm-context-llm-call-count\t{result.get('llmContextLlmCallCount')}")
    if result.get("next"):
        print(f"assignments\trun-research\tnext\t{result.get('next')}")


def _print_reporting_run_summary(result: dict[str, Any]) -> None:
    print(f"assignments\trun-reporting\taction\t{result.get('action')}")
    print(f"assignments\trun-reporting\trun\t{result.get('runId')}")
    print(f"assignments\trun-reporting\tassignment\t{result.get('assignmentId')}")
    print(f"assignments\trun-reporting\tstatus\t{result.get('exitStatus') or ''}")
    print(f"assignments\trun-reporting\tparsed\t{result.get('parsed')}")
    packet = result.get("packet") or {}
    if packet:
        print(
            f"assignments\trun-reporting\tcounts\taccepted={packet.get('acceptedReferenceCount')}\t"
            f"sources={packet.get('sourceTrailCount')}\tproposals={packet.get('proposedReferenceCount')}\t"
            f"verification={packet.get('verificationNeedCount')}"
        )
        print(
            f"assignments\trun-reporting\tknowledge\tqueries={packet.get('knowledgeQueryCount')}\t"
            f"uris={packet.get('papyrusUriCount')}"
        )
        print(f"assignments\trun-reporting\trecommendation\t{packet.get('editorRecommendation')}")
        print(f"assignments\trun-reporting\tattempts\t{packet.get('attempts')}")
        if packet.get("reportingPathMode"):
            print(f"assignments\trun-reporting\treporting-path-mode\t{packet.get('reportingPathMode')}")
        if packet.get("knowledgeOrientationAttempted") is not None:
            print(
                "assignments\trun-reporting\tknowledge-orientation-attempted\t"
                f"{packet.get('knowledgeOrientationAttempted')}"
            )
        if packet.get("knowledgeOrientationCompleted") is not None:
            print(
                "assignments\trun-reporting\tknowledge-orientation-completed\t"
                f"{packet.get('knowledgeOrientationCompleted')}"
            )
        if packet.get("knowledgeBlockedReason"):
            print(f"assignments\trun-reporting\tknowledge-blocked\t{packet.get('knowledgeBlockedReason')}")
        if packet.get("firstValidationError"):
            print(f"assignments\trun-reporting\tfirst-validation-error\t{packet.get('firstValidationError')}")
        if packet.get("lastValidationError"):
            print(f"assignments\trun-reporting\tlast-validation-error\t{packet.get('lastValidationError')}")
        if packet.get("firstProposalUrl"):
            print(f"assignments\trun-reporting\tfirst-proposal\t{packet.get('firstProposalUrl')}")
        if packet.get("knowledgeScopeIncludeKinds"):
            print(
                "assignments\trun-reporting\tknowledge-scope-kinds\t"
                + ",".join(str(value) for value in packet.get("knowledgeScopeIncludeKinds") or [])
            )
        if packet.get("knowledgeScopeIncludeMessageKinds"):
            print(
                "assignments\trun-reporting\tknowledge-scope-message-kinds\t"
                + ",".join(str(value) for value in packet.get("knowledgeScopeIncludeMessageKinds") or [])
            )
        if packet.get("knowledgeScopeIncludeAssignmentTypes"):
            print(
                "assignments\trun-reporting\tknowledge-scope-assignment-types\t"
                + ",".join(str(value) for value in packet.get("knowledgeScopeIncludeAssignmentTypes") or [])
            )
    print(f"assignments\trun-reporting\tresult\t{result.get('resultPath')}")
    print(f"assignments\trun-reporting\tstdout\t{result.get('stdoutPath')}")
    print(f"assignments\trun-reporting\tstderr\t{result.get('stderrPath')}")
    if result.get("llmContextSummaryPath"):
        print(f"assignments\trun-reporting\tllm-context-summary\t{result.get('llmContextSummaryPath')}")
    if result.get("llmContextCallsPath"):
        print(f"assignments\trun-reporting\tllm-context-calls\t{result.get('llmContextCallsPath')}")
    if result.get("llmContextCallCount") is not None:
        print(f"assignments\trun-reporting\tllm-context-call-count\t{result.get('llmContextCallCount')}")
    if result.get("llmContextLlmCallsPath"):
        print(f"assignments\trun-reporting\tllm-context-llm-calls\t{result.get('llmContextLlmCallsPath')}")
    if result.get("llmContextLlmCallCount") is not None:
        print(f"assignments\trun-reporting\tllm-context-llm-call-count\t{result.get('llmContextLlmCallCount')}")
    if result.get("next"):
        print(f"assignments\trun-reporting\tnext\t{result.get('next')}")


def apply_research_packet(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> dict[str, Any]:
    apply = resolve_mutation_apply(options, "assignments apply-research-packet")
    assignment_id = normalize_string(options.get("assignment"))
    if not assignment_id:
        raise ValueError("assignments apply-research-packet requires --assignment <id>.")
    research = read_research_packet_input(options)
    assignment = client.get_record("Assignment", assignment_id)
    if not assignment:
        raise ValueError(f"Assignment not found: {assignment_id}.")
    assignment_meta = assignment_metadata(client, assignment)
    now = _utc_now()
    research_mode = normalize_research_mode(
        research.get("research_mode")
        or research.get("researchMode")
        or assignment_meta.get("researchMode")
        or options.get("research-mode")
    )
    packet = normalize_research_packet_bundle(
        research,
        assignment=assignment,
        assignment_meta=assignment_meta,
        research_mode=research_mode,
    )
    summary = normalize_string(packet.get("summary") or (packet.get("synthesis") or {}).get("summary"))
    if not summary:
        raise ValueError("assignments apply-research-packet requires research.summary.")
    validate_research_packet_mode(packet)
    packet_hash = research_packet_hash(assignment_id=assignment_id, research_mode=research_mode, packet=packet)
    message_id = normalize_string(options.get("id")) or f"message-research-packet-{packet_hash}"
    message = message_record(
        {
            "id": message_id,
            "messageKind": "research_packet",
            "messageDomain": "assignment_work",
            "status": "active",
            "summary": summary,
            "body": research_packet_body(packet),
            "metadata": {
                "kind": "research.packet.created",
                "assignmentId": assignment_id,
                "assignmentTypeKey": assignment["assignmentTypeKey"],
                "queueKey": assignment["queueKey"],
                "research": packet,
            },
            "source": "assignments apply-research-packet",
            "importRunId": assignment.get("importRunId"),
            "authorLabel": normalize_string(options.get("actor-label")) or "Papyrus content CLI",
            "createdAt": now,
            "updatedAt": now,
        }
    )["expected"]
    relation = semantic_relation_record(
        {
            "predicate": "produces",
            "subjectKind": "assignment",
            "subjectId": assignment_id,
            "subjectLineageId": assignment_id,
            "objectKind": "message",
            "objectId": message_id,
            "objectLineageId": message_id,
            "rank": 1,
            "confidence": 1,
            "reviewRecommended": False,
            "importRunId": assignment.get("importRunId"),
            "importedAt": now,
            "metadata": {
                "lifecycle": "assignment-research-packet",
                "messageKind": "research_packet",
                "metadataKind": "research.packet.created",
                "assignmentTypeKey": assignment["assignmentTypeKey"],
                "queueKey": assignment["queueKey"],
                "researchMode": research_mode,
                "workProductKind": "research_packet",
            },
        }
    )
    changes = build_record_changes(client, [{"modelName": "Message", "expected": message}, relation])
    result = {
        "assignmentId": assignment_id,
        "messageId": message_id,
        "researchMode": research_mode,
        "proposedReferenceCount": len(packet.get("proposedReferences") or []),
        "sourceSnapshotCount": len(packet.get("sourceSnapshots") or []),
        "evidenceItemCount": len(packet.get("evidenceItemIds") or []),
    }
    if not apply:
        _print_apply_research_packet_summary("dry-run", result)
        print("assignments\tapply-research-packet\tapply\tskipped\tuse --dry-run to preview without writes")
        return result
    apply_record_changes(client, changes)
    update_newsroom_summary_after_research_packet_creates(
        client,
        changes,
        actor_label=message["authorLabel"],
        reason=f"assignments apply-research-packet {assignment_id}",
    )
    _print_apply_research_packet_summary("apply", result)
    return result


def apply_reporting_packet(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> dict[str, Any]:
    apply = resolve_mutation_apply(options, "assignments apply-reporting-packet")
    assignment_id = normalize_string(options.get("assignment"))
    if not assignment_id:
        raise ValueError("assignments apply-reporting-packet requires --assignment <id>.")
    reporting = read_reporting_packet_input(options)
    summary = normalize_string(reporting.get("summary"))
    if not summary:
        raise ValueError("assignments apply-reporting-packet requires reporting.summary.")
    assignment = client.get_record("Assignment", assignment_id)
    if not assignment:
        raise ValueError(f"Assignment not found: {assignment_id}.")
    assignment_meta = assignment_metadata(client, assignment)
    now = _utc_now()
    packet = normalize_reporting_packet_bundle(
        reporting,
        assignment=assignment,
        assignment_meta=assignment_meta,
    )
    validate_reporting_packet(packet)
    message_id = normalize_string(options.get("id")) or reporting_packet_message_id(
        assignment_id,
        created_at=now,
        summary=packet.get("summary"),
    )
    message = message_record(
        {
            "id": message_id,
            "messageKind": "reporting_context_packet",
            "messageDomain": "assignment_work",
            "status": "active",
            "summary": packet.get("summary"),
            "body": reporting_packet_body(packet),
            "metadata": {
                "kind": "reporting.context_packet.created",
                "assignmentId": assignment_id,
                "assignmentTypeKey": assignment["assignmentTypeKey"],
                "queueKey": assignment["queueKey"],
                "reporting": packet,
            },
            "source": "assignments apply-reporting-packet",
            "importRunId": assignment.get("importRunId"),
            "authorLabel": normalize_string(options.get("actor-label")) or "Papyrus content CLI",
            "createdAt": now,
            "updatedAt": now,
        }
    )["expected"]
    records: list[dict[str, Any]] = [
        {"modelName": "Message", "expected": message},
        semantic_relation_record(
            {
                "predicate": "produces",
                "subjectKind": "assignment",
                "subjectId": assignment_id,
                "subjectLineageId": assignment_id,
                "objectKind": "message",
                "objectId": message_id,
                "objectLineageId": message_id,
                "rank": 1,
                "confidence": 1,
                "reviewRecommended": False,
                "importRunId": assignment.get("importRunId"),
                "importedAt": now,
                "metadata": {
                    "lifecycle": "assignment-reporting-context-packet",
                    "messageKind": "reporting_context_packet",
                    "metadataKind": "reporting.context_packet.created",
                    "assignmentTypeKey": assignment["assignmentTypeKey"],
                    "queueKey": assignment["queueKey"],
                    "editorRecommendation": packet.get("editorRecommendation"),
                    "workProductKind": "reporting_context_packet",
                },
            }
        ),
    ]
    if packet.get("sourceResearchPacketId"):
        records.append(
            semantic_relation_record(
                {
                    "predicate": "derived_from",
                    "subjectKind": "assignment",
                    "subjectId": assignment_id,
                    "subjectLineageId": assignment_id,
                    "objectKind": "message",
                    "objectId": packet["sourceResearchPacketId"],
                    "objectLineageId": packet["sourceResearchPacketId"],
                    "rank": 1,
                    "confidence": 1,
                    "reviewRecommended": False,
                    "importRunId": assignment.get("importRunId"),
                    "importedAt": now,
                    "metadata": {
                        "lifecycle": "assignment-reporting-context-packet",
                        "sourceKind": "source_research_packet",
                        "assignmentTypeKey": assignment["assignmentTypeKey"],
                        "queueKey": assignment["queueKey"],
                        "workProductKind": "reporting_context_packet",
                    },
                }
            )
        )
    if packet.get("sourceResearchAssignmentId"):
        records.append(
            semantic_relation_record(
                {
                    "predicate": "derived_from",
                    "subjectKind": "assignment",
                    "subjectId": assignment_id,
                    "subjectLineageId": assignment_id,
                    "objectKind": "assignment",
                    "objectId": packet["sourceResearchAssignmentId"],
                    "objectLineageId": packet["sourceResearchAssignmentId"],
                    "rank": 2,
                    "confidence": 1,
                    "reviewRecommended": False,
                    "importRunId": assignment.get("importRunId"),
                    "importedAt": now,
                    "metadata": {
                        "lifecycle": "assignment-reporting-context-packet",
                        "sourceKind": "source_research_assignment",
                        "assignmentTypeKey": assignment["assignmentTypeKey"],
                        "queueKey": assignment["queueKey"],
                        "workProductKind": "reporting_context_packet",
                    },
                }
            )
        )
    changes = build_record_changes(client, records)
    result = {
        "assignmentId": assignment_id,
        "messageId": message_id,
        "canonicalPolicy": "latest_successful_packet",
        "editorRecommendation": packet.get("editorRecommendation"),
        "acceptedReferenceCount": len(packet.get("acceptedReferenceIds") or []),
        "proposedReferenceCount": len(packet.get("proposedReferences") or []),
        "sourceTrailCount": len(packet.get("sourceTrail") or []),
        "knowledgeQueryCount": len(packet.get("knowledgeQueries") or []),
        "papyrusUriCount": len(packet.get("papyrusUrisInspected") or []),
        "knowledgeBlockedReason": packet.get("knowledgeBlockedReason"),
        "verificationNeedCount": len(packet.get("verificationNeeds") or []),
    }
    if not apply:
        _print_apply_reporting_packet_summary("dry-run", result)
        print("assignments\tapply-reporting-packet\tapply\tskipped\tuse --dry-run to preview without writes")
        return result
    apply_record_changes(client, changes)
    update_newsroom_summary_after_research_packet_creates(
        client,
        changes,
        actor_label=message["authorLabel"],
        reason=f"assignments apply-reporting-packet {assignment_id}",
    )
    _print_apply_reporting_packet_summary("apply", result)
    return result


def _references_for_changed_ids(
    client: PapyrusGraphQLAuthoringClient,
    reference_ids: set[str],
) -> list[dict[str, Any]]:
    if not reference_ids:
        return []
    by_id = client.get_records_by_id("Reference", sorted(reference_ids))
    return list(by_id.values())


def intake_research_packet_proposals(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> dict[str, Any]:
    from .catalog import assert_reference_catalog_plan_safety, build_reference_catalog_registration_records
    from .ids import knowledge_corpus_id
    from .steering import load_steering_config, require_corpus_config, resolve_classifier_for_corpus

    apply = resolve_mutation_apply(options, "assignments process-proposals")
    assignment_id = normalize_string(options.get("assignment"))
    if not assignment_id:
        raise ValueError("assignments process-proposals requires --assignment <id>.")
    if not options.get("config"):
        raise ValueError("assignments process-proposals requires --config <steering.yml>.")
    corpus_key = normalize_string(options.get("corpus-key"))
    if not corpus_key:
        raise ValueError("assignments process-proposals requires --corpus-key <key>.")
    entries = load_assignment_research_packet_entries(client, assignment_id)
    message_id = normalize_string(options.get("message"))
    selected = next((entry for entry in entries if entry["message"]["id"] == message_id), None) if message_id else (
        entries[0] if entries else None
    )
    if not selected:
        raise ValueError(
            f"Research packet message {message_id} is not linked to assignment {assignment_id}."
            if message_id
            else f"No persisted research_packet message is linked to assignment {assignment_id}."
        )
    run_id = normalize_string(options.get("run-id")) or (
        f"research-proposals-{safe_id(assignment_id)[:60]}-{timestamp_for_path()}"
    )
    run_dir = PAPYRUS_ROOT / ".papyrus-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = run_dir / "research-proposals-catalog.json"
    proposals = extract_research_packet_proposals(selected["packet"])
    catalog_items = build_research_proposal_catalog_items(
        proposals,
        assignment=selected["assignment"],
        message=selected["message"],
        packet=selected["packet"],
    )
    blocked_reason = normalize_string((selected["packet"].get("sourceDiscovery") or {}).get("blockedReason"))
    catalog = {
        "schema_version": 1,
        "catalog_kind": "papyrus-research-proposed-references",
        "generated_at": selected["message"].get("createdAt") or now_iso(),
        "assignment_id": assignment_id,
        "research_packet_message_id": selected["message"]["id"],
        "research_mode": selected["packet"].get("researchMode"),
        "blocked_reason": blocked_reason,
        "items": catalog_items,
    }
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    if not catalog_items:
        return {
            "assignmentId": assignment_id,
            "messageId": selected["message"]["id"],
            "catalogPath": str(catalog_path),
            "proposedReferenceCount": len(proposals),
            "registeredReferenceCount": 0,
            "skippedDuplicateCount": 0,
            "curationAssignmentCount": 0,
            "blockedReason": blocked_reason,
            "next": f"Review blocked reason on research packet {selected['message']['id']}"
            if blocked_reason
            else f"poetry run papyrus assignments run-research --assignment {assignment_id} --research-mode source_discovery --max-evidence-items 20",
        }
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key")
    catalog_payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    plan_options = {
        "corpusConfig": corpus_config,
        "corpusId": knowledge_corpus_id(corpus_config),
        "classifierId": resolve_classifier_for_corpus(steering_config, corpus_config, None),
        "status": _normalize_proposal_intake_status(options.get("status")),
        "reasonCode": options.get("reason-code"),
        "note": options.get("note"),
        "actor": options.get("actor") or "Papyrus content CLI",
    }
    plan = build_reference_catalog_registration_records(catalog_payload, plan_options)
    assert_reference_catalog_plan_safety(plan)
    changes = build_record_changes(client, plan["records"])
    registration = {"plan": plan, "changes": changes}
    url_text_result: dict[str, Any] | None = None
    metadata_generation_result: dict[str, Any] | None = None
    if apply:
        apply_record_changes(client, registration["changes"])
        update_newsroom_summary_after_reference_registration(client, registration["changes"], registration["plan"])
        changed_reference_ids = {
            str(change["expected"].get("id") or "")
            for change in registration["changes"]
            if change.get("modelName") == "Reference" and change.get("action") in {"create", "update"}
        }
        if parse_boolean_option(options.get("url-text"), True, "--url-text"):
            if changed_reference_ids:
                refreshed_references = _references_for_changed_ids(client, changed_reference_ids)
                # Fresh research-proposal references have no attachments or citation graph yet.
                refreshed_attachments: list[dict[str, Any]] = []
                refreshed_semantic_relations: list[dict[str, Any]] = []
                max_count = normalize_non_negative_integer(options.get("url-text-max-count"), "--url-text-max-count")
                force = parse_boolean_option(options.get("url-text-force"), False, "--url-text-force")
                corpus_id = knowledge_corpus_id(corpus_config)
                url_text_result = run_reference_url_text_extraction(
                    client=client,
                    references=refreshed_references,
                    attachments=refreshed_attachments,
                    semantic_relations=refreshed_semantic_relations,
                    corpus_key_by_id={corpus_id: str(corpus_config.get("key") or "")},
                    corpus_id=corpus_id,
                    reference_ids=changed_reference_ids,
                    curation_status="all",
                    max_count=max_count,
                    force=force,
                    apply=True,
                    bucket=normalize_string(options.get("bucket")),
                )
                update_newsroom_summary_after_extracted_text_attachments(
                    client,
                    url_text_result["changes"],
                    actor_label=options.get("actor") or "Papyrus content CLI",
                    reason=f"assignments process-proposals process-fetch-url-text {assignment_id}",
                )
        if parse_boolean_option(options.get("metadata-from-text"), True, "--metadata-from-text"):
            if changed_reference_ids:
                refreshed_references = _references_for_changed_ids(client, changed_reference_ids)
                refreshed_attachments: list[dict[str, Any]] = []
                corpus_id = knowledge_corpus_id(corpus_config)
                metadata_generation_result = run_reference_metadata_generation_from_extracted_text(
                    references=refreshed_references,
                    attachments=refreshed_attachments,
                    corpus_id=corpus_id,
                    reference_ids=changed_reference_ids,
                    curation_status="all",
                    max_count=normalize_non_negative_integer(options.get("metadata-max-count"), "--metadata-max-count"),
                    model=normalize_string(options.get("metadata-model")) or DEFAULT_REFERENCE_SUMMARY_MODEL,
                    apply=True,
                    bucket=normalize_string(options.get("bucket")),
                )
    references = _research_proposal_intake_reference_rows(registration["changes"])
    changed_refs = sum(
        1 for change in registration["changes"] if change.get("modelName") == "Reference" and change.get("action") != "noop"
    )
    changed_assignments = sum(
        1 for change in registration["changes"] if change.get("modelName") == "Assignment" and change.get("action") != "noop"
    )
    duplicate_noops = sum(
        1 for change in registration["changes"] if change.get("modelName") == "Reference" and change.get("action") == "noop"
    )
    return {
        "assignmentId": assignment_id,
        "messageId": selected["message"]["id"],
        "catalogPath": str(catalog_path),
        "proposedReferenceCount": len(proposals),
        "dedupedProposalCount": len(catalog_items),
        "registeredReferenceCount": changed_refs,
        "skippedDuplicateCount": duplicate_noops,
        "curationAssignmentCount": changed_assignments,
        "importRunId": registration["plan"]["importRunId"],
        "references": references,
        "blockedReason": blocked_reason,
        "next": (
            f"poetry run papyrus references process-status --config {options.get('config')} "
            f"--corpus-key {corpus_key} --status "
            f"{normalize_reference_curation_status(options.get('status'), 'pending')}"
        ),
        "urlText": {
            "eligible": url_text_result.get("eligibleCount", 0),
            "planned": url_text_result.get("plannedCount", 0),
            "changes": url_text_result.get("changeCount", 0),
            "failures": len(url_text_result.get("failures", [])),
        }
        if url_text_result
        else None,
        "metadataGeneration": {
            "attempted": metadata_generation_result.get("attemptedCount", 0),
            "generated": metadata_generation_result.get("generatedCount", 0),
            "skippedMissingText": metadata_generation_result.get("skippedMissingTextCount", 0),
            "generationFailures": metadata_generation_result.get("generationFailureCount", 0),
        }
        if metadata_generation_result
        else None,
    }


def load_assignment_research_packet_entries(
    client: PapyrusGraphQLAuthoringClient,
    assignment_id: str,
) -> list[dict[str, Any]]:
    assignment = client.get_record("Assignment", assignment_id)
    if not assignment:
        raise ValueError(f"Assignment not found: {assignment_id}.")
    assignment_meta = assignment_metadata(client, assignment)
    subject_state = semantic_state_key("assignment", assignment_id)
    incoming = client.list_semantic_relations_by_object_state(subject_state)
    outgoing = client.list_semantic_relations_by_subject_state(subject_state)
    relations = [
        relation
        for relation in [*incoming, *outgoing]
        if relation.get("relationState") == "current" and is_assignment_packet_relation(relation, assignment_id)
    ]
    message_ids = [
        relation["objectId"] if relation.get("objectKind") == "message" else relation["subjectId"]
        for relation in relations
    ]
    message_by_id = client.get_records_by_id("Message", message_ids)
    entries: list[dict[str, Any]] = []
    for relation in relations:
        message_id = relation["objectId"] if relation.get("objectKind") == "message" else relation["subjectId"]
        message = message_by_id.get(message_id)
        if not message or message.get("messageKind") != "research_packet":
            continue
        metadata = load_message_metadata_payload(client, message)
        research = parse_jsonish(metadata.get("research")) or metadata
        research_mode = normalize_research_mode(
            research.get("researchMode")
            or research.get("research_mode")
            or metadata.get("researchMode")
            or assignment_meta.get("researchMode")
        )
        packet = normalize_research_packet_bundle(
            research,
            assignment=assignment,
            assignment_meta=assignment_meta,
            research_mode=research_mode,
        )
        entries.append({"assignment": assignment, "message": message, "metadata": metadata, "relation": relation, "packet": packet})
    entries.sort(key=lambda entry: str(entry["message"].get("createdAt") or ""), reverse=True)
    return entries


def load_message_metadata_payload(
    client: PapyrusGraphQLAuthoringClient,
    message: dict[str, Any],
) -> dict[str, Any]:
    metadata = parse_jsonish(message.get("metadata"))
    if isinstance(metadata, dict) and metadata:
        return metadata
    message_id = normalize_string(message.get("id"))
    if not message_id:
        return {}
    attachments = client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", message_id, limit=20)
    if not attachments:
        return {}
    metadata_attachments = [
        entry
        for entry in attachments
        if normalize_string(entry.get("role")) == "metadata"
        and normalize_string(entry.get("status")) != "deleted"
    ]
    metadata_attachments.sort(key=lambda entry: str(entry.get("updatedAt") or ""), reverse=True)
    metadata_attachments.sort(key=lambda entry: 0 if normalize_string(entry.get("status")) == "active" else 1)
    for attachment in metadata_attachments:
        try:
            payload = parse_jsonish(download_attachment_buffer(client, attachment).decode("utf-8", errors="replace"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def research_packet_from_procedure_output(parsed: dict[str, Any]) -> dict[str, Any]:
    value = parsed.get("value") or parsed
    packet = value.get("research_packet") or value.get("researchPacket") or value.get("research") or value
    if not isinstance(packet, dict):
        return {}
    packet = dict(packet)
    if not normalize_string(packet.get("summary")):
        top_level_summary = normalize_string(
            value.get("summary") or value.get("research_summary") or value.get("researchSummary")
        )
        if top_level_summary:
            packet["summary"] = top_level_summary
    synthesis = packet.get("synthesis")
    if not normalize_string(packet.get("summary")) and isinstance(synthesis, dict):
        synthesis_summary = normalize_string(synthesis.get("summary"))
        if synthesis_summary:
            packet["summary"] = synthesis_summary
    source_discovery = packet.get("sourceDiscovery") or packet.get("source_discovery")
    if isinstance(source_discovery, dict):
        if not _parse_array(packet.get("proposed_references") or packet.get("proposedReferences")):
            discovered_refs = source_discovery.get("proposedReferences") or source_discovery.get("proposed_references")
            if discovered_refs:
                packet["proposed_references"] = discovered_refs
        if not _parse_array(packet.get("source_snapshots") or packet.get("sourceSnapshots")):
            discovered_snapshots = source_discovery.get("sourceSnapshots") or source_discovery.get("source_snapshots")
            if discovered_snapshots:
                packet["source_snapshots"] = discovered_snapshots
    return packet


def read_research_packet_input(options: dict[str, Any]) -> dict[str, Any]:
    raw = options.get("research-json")
    if not raw:
        raise ValueError("assignments apply-research-packet requires --research-json <path-or-json>.")
    raw_text = str(raw)
    candidate = raw_text.lstrip()
    if candidate.startswith("{") or candidate.startswith("["):
        text = raw_text
    else:
        path = Path(raw_text)
        try:
            text = path.read_text(encoding="utf-8") if path.exists() else raw_text
        except OSError:
            text = raw_text
    parsed = json.loads(text)
    return research_packet_from_procedure_output(parsed)


def read_reporting_packet_input(options: dict[str, Any]) -> dict[str, Any]:
    raw = options.get("reporting-json")
    if not raw:
        raise ValueError("assignments apply-reporting-packet requires --reporting-json <path-or-json>.")
    raw_text = str(raw)
    candidate = raw_text.lstrip()
    if candidate.startswith("{") or candidate.startswith("["):
        text = raw_text
    else:
        path = Path(raw_text)
        try:
            text = path.read_text(encoding="utf-8") if path.exists() else raw_text
        except OSError:
            text = raw_text
    parsed = json.loads(text)
    value = parsed.get("value") or parsed
    return value.get("reporting_context_packet") or value.get("reportingContextPacket") or value.get("reporting") or value


def normalize_research_packet_bundle(
    research: dict[str, Any],
    *,
    assignment: dict[str, Any],
    assignment_meta: dict[str, Any],
    research_mode: str,
) -> dict[str, Any]:
    evidence_item_ids = _parse_string_array(research.get("evidence_item_ids") or research.get("evidenceItemIds"))
    queries = _parse_array(research.get("queries"))
    source_snapshots = _parse_array(research.get("source_snapshots") or research.get("sourceSnapshots"))
    proposed_references = _parse_array(research.get("proposed_references") or research.get("proposedReferences"))
    trace = dict(_parse_object(research.get("researchTrace") or research.get("research_trace")))
    internal_findings = dict(_parse_object(research.get("internalFindings") or research.get("internal_findings")))
    source_discovery = dict(_parse_object(research.get("sourceDiscovery") or research.get("source_discovery")))
    synthesis = dict(_parse_object(research.get("synthesis")))
    summary = normalize_string(research.get("summary") or synthesis.get("summary")) or ""
    recommended_angle = normalize_string(
        research.get("recommended_angle")
        or research.get("recommendedAngle")
        or synthesis.get("recommendedAngle")
        or synthesis.get("recommended_angle")
    ) or ""
    open_questions = _parse_array(
        research.get("open_questions") or research.get("openQuestions") or synthesis.get("openQuestions")
    )
    coverage_gaps = _parse_array(
        research.get("coverage_gaps") or research.get("coverageGaps") or synthesis.get("coverageGaps")
    )
    source_discovery_web_searches = _parse_array(source_discovery.get("webSearches") or source_discovery.get("web_searches"))
    trace_web_searches = _parse_array(trace.get("webSearches") or trace.get("web_searches"))
    blocked_reason = normalize_string(
        source_discovery.get("blockedReason")
        or source_discovery.get("blocked_reason")
        or research.get("blockedReason")
        or research.get("blocked_reason")
    )
    if (
        not blocked_reason
        and research_mode != "internal_brief"
        and not source_snapshots
        and not proposed_references
    ):
        blocked_reason = "web_discovery_exhausted_zero_results"
    discovery_boundary = _parse_object(trace.get("discoveryBoundary") or trace.get("discovery_boundary"))
    if (
        not discovery_boundary
        and (trace_web_searches or source_discovery_web_searches)
        and research_mode != "internal_brief"
    ):
        local_attempts = len(trace_web_searches) if trace_web_searches else len(source_discovery_web_searches)
        if local_attempts <= 0:
            local_attempts = 1
        discovery_boundary = {
            "webSearchPath": "papyrus.reference.web_search",
            "searchResultCount": len(source_snapshots),
            "searchMetadataShapeOk": True,
            "discoveryAttemptsTotal": local_attempts,
            "discoveryQueriesTried": trace_web_searches or source_discovery_web_searches,
            "discoveryResultCounts": [len(source_snapshots)],
            "discoveryTerminalState": "succeeded" if source_snapshots else "exhausted",
        }
        if blocked_reason:
            discovery_boundary["blockedReason"] = blocked_reason
    if discovery_boundary:
        if discovery_boundary.get("discoveryAttemptsTotal") is None:
            attempts = len(_parse_array(trace_web_searches or source_discovery_web_searches))
            discovery_boundary["discoveryAttemptsTotal"] = attempts if attempts > 0 else 1
        if not _parse_array(discovery_boundary.get("discoveryQueriesTried") or discovery_boundary.get("discovery_queries_tried")):
            discovery_boundary["discoveryQueriesTried"] = trace_web_searches or source_discovery_web_searches
        if not _parse_array(discovery_boundary.get("discoveryResultCounts") or discovery_boundary.get("discovery_result_counts")):
            discovery_boundary["discoveryResultCounts"] = [len(source_snapshots)]
        if not normalize_string(discovery_boundary.get("discoveryTerminalState") or discovery_boundary.get("discovery_terminal_state")):
            discovery_boundary["discoveryTerminalState"] = "succeeded" if source_snapshots else "exhausted"
        if blocked_reason and not normalize_string(discovery_boundary.get("blockedReason") or discovery_boundary.get("blocked_reason")):
            discovery_boundary["blockedReason"] = blocked_reason
        trace["discoveryBoundary"] = discovery_boundary
    return {
        "researchMode": research_mode,
        "status": "researched",
        "summary": summary,
        "corpusKey": research.get("corpus_key")
        or research.get("corpusKey")
        or assignment_meta.get("corpusKey")
        or assignment.get("corpusId"),
        "categoryKey": research.get("category_key")
        or research.get("categoryKey")
        or assignment_meta.get("focusCategoryKey")
        or assignment_meta.get("deskCategoryKey"),
        "evidenceItemIds": evidence_item_ids,
        "queries": queries,
        "sourceSnapshots": source_snapshots,
        "proposedReferences": proposed_references,
        "internalFindings": {
            "summary": internal_findings.get("summary") or research.get("internalSummary") or summary,
            "evidenceItemIds": _parse_string_array(
                internal_findings.get("evidenceItemIds") or internal_findings.get("evidence_item_ids") or evidence_item_ids
            ),
            "queries": _parse_array(internal_findings.get("queries") or queries),
            "papyrusUrisInspected": _parse_array(
                internal_findings.get("papyrusUrisInspected") or internal_findings.get("papyrus_uris_inspected")
            ),
        },
        "sourceDiscovery": {
            "webSearches": source_discovery_web_searches,
            "sourceSnapshots": _parse_array(
                source_discovery.get("sourceSnapshots") or source_discovery.get("source_snapshots") or source_snapshots
            ),
            "proposedReferences": _parse_array(
                source_discovery.get("proposedReferences")
                or source_discovery.get("proposed_references")
                or proposed_references
            ),
            "blockedReason": blocked_reason or None,
        },
        "synthesis": {
            "summary": summary,
            "recommendedAngle": recommended_angle,
            "openQuestions": open_questions,
            "coverageGaps": coverage_gaps,
        },
        "researchTrace": trace,
        "openQuestions": open_questions,
        "coverageGaps": coverage_gaps,
        "recommendedAngle": recommended_angle,
    }


def normalize_reporting_packet_bundle(
    reporting: dict[str, Any],
    *,
    assignment: dict[str, Any],
    assignment_meta: dict[str, Any],
) -> dict[str, Any]:
    packet = reporting.get("reporting") if isinstance(reporting.get("reporting"), dict) else reporting
    section_key = normalize_string(
        packet.get("section_key")
        or packet.get("sectionKey")
        or assignment.get("sectionKey")
        or assignment.get("sectionId")
        or assignment_meta.get("sectionKey")
        or assignment_meta.get("sectionId")
    )
    edition_id = normalize_string(
        packet.get("edition_id")
        or packet.get("editionId")
        or assignment_meta.get("editionId")
    )
    recommendation = normalize_reporting_recommendation(
        packet.get("editor_recommendation")
        or packet.get("editorRecommendation")
        or assignment_meta.get("editorRecommendation")
    )
    knowledge_queries = _parse_array(
        packet.get("knowledge_queries")
        or packet.get("knowledgeQueries")
    )
    papyrus_uris_inspected = _parse_array(
        packet.get("papyrus_uris_inspected")
        or packet.get("papyrusUrisInspected")
    )
    knowledge_blocked_reason = normalize_string(
        packet.get("knowledge_blocked_reason")
        or packet.get("knowledgeBlockedReason")
        or packet.get("knowledge_orientation_blocked_reason")
        or packet.get("knowledgeOrientationBlockedReason")
    )
    knowledge_orientation_attempted = packet.get("knowledge_orientation_attempted")
    if knowledge_orientation_attempted is None:
        knowledge_orientation_attempted = packet.get("knowledgeOrientationAttempted")
    if knowledge_orientation_attempted is None:
        knowledge_orientation_attempted = bool(
            knowledge_queries
            or papyrus_uris_inspected
            or _parse_array(packet.get("source_trail") or packet.get("sourceTrail"))
            or knowledge_blocked_reason
        )
    knowledge_orientation_completed = packet.get("knowledge_orientation_completed")
    if knowledge_orientation_completed is None:
        knowledge_orientation_completed = packet.get("knowledgeOrientationCompleted")
    if knowledge_orientation_completed is None:
        knowledge_orientation_completed = bool(knowledge_orientation_attempted and not knowledge_blocked_reason)
    reporting_path_mode = normalize_string(packet.get("reporting_path_mode") or packet.get("reportingPathMode")) or "strict_single_path"
    proposed_references = _parse_array(packet.get("proposed_references") or packet.get("proposedReferences"))
    verification_needs = _parse_array(packet.get("verification_needs") or packet.get("verificationNeeds"))
    if proposed_references and not verification_needs:
        verification_needs = [
            "Verify each proposed reference before editor selection or copywriting intake.",
        ]
    recommended_angle = normalize_string(packet.get("recommended_angle") or packet.get("recommendedAngle"))
    copywriter_brief = normalize_string(packet.get("copywriter_brief") or packet.get("copywriterBrief"))
    if not recommended_angle:
        recommended_angle = (
            "Hold for additional reporting context and verification before selecting a publishable angle."
        )
    if not copywriter_brief:
        copywriter_brief = (
            "Hold for editor review; refresh reporting context and verification evidence before copywriting intake."
        )
    return {
        "status": "reported",
        "summary": normalize_string(packet.get("summary")),
        "sectionKey": section_key,
        "editionId": edition_id,
        "candidateRank": packet.get("candidate_rank")
        or packet.get("candidateRank")
        or assignment_meta.get("candidateRank"),
        "slotTarget": _parse_object(packet.get("slot_target") or packet.get("slotTarget") or assignment_meta.get("slotTarget")),
        "whyNow": normalize_string(packet.get("why_now") or packet.get("whyNow")),
        "nutGrafCandidate": normalize_string(packet.get("nut_graf_candidate") or packet.get("nutGrafCandidate")),
        "recommendedAngle": recommended_angle,
        "confirmedFacts": _parse_array(packet.get("confirmed_facts") or packet.get("confirmedFacts")),
        "sourceTrail": _parse_array(packet.get("source_trail") or packet.get("sourceTrail")),
        "knowledgeQueries": knowledge_queries,
        "papyrusUrisInspected": papyrus_uris_inspected,
        "knowledgeBlockedReason": knowledge_blocked_reason,
        "knowledgeOrientationAttempted": bool(knowledge_orientation_attempted),
        "knowledgeOrientationCompleted": bool(knowledge_orientation_completed),
        "reportingPathMode": reporting_path_mode,
        "acceptedReferenceIds": _parse_string_array(packet.get("accepted_reference_ids") or packet.get("acceptedReferenceIds")),
        "proposedReferences": proposed_references,
        "recentDeskMemoryUsed": _parse_array(packet.get("recent_desk_memory_used") or packet.get("recentDeskMemoryUsed")),
        "coverageConceptId": packet.get("coverage_concept_id") or packet.get("coverageConceptId") or assignment_meta.get("coverageConceptId"),
        "coverageConceptLineageId": packet.get("coverage_concept_lineage_id") or packet.get("coverageConceptLineageId") or assignment_meta.get("coverageConceptLineageId"),
        "coverageConceptKey": packet.get("coverage_concept_key") or packet.get("coverageConceptKey") or assignment_meta.get("coverageConceptKey"),
        "coverageConceptTitle": packet.get("coverage_concept_title") or packet.get("coverageConceptTitle") or assignment_meta.get("coverageConceptTitle"),
        "sourceResearchPacketId": normalize_string(
            packet.get("source_research_packet_id")
            or packet.get("sourceResearchPacketId")
            or assignment_meta.get("sourceResearchPacketId")
        ),
        "sourceResearchAssignmentId": normalize_string(
            packet.get("source_research_assignment_id")
            or packet.get("sourceResearchAssignmentId")
            or assignment_meta.get("sourceResearchAssignmentId")
        ),
        "coverageGaps": _parse_array(packet.get("coverage_gaps") or packet.get("coverageGaps")),
        "openQuestions": _parse_array(packet.get("open_questions") or packet.get("openQuestions")),
        "riskFlags": _parse_array(packet.get("risk_flags") or packet.get("riskFlags")),
        "verificationNeeds": verification_needs,
        "sourceDiversityNotes": _parse_array(packet.get("source_diversity_notes") or packet.get("sourceDiversityNotes")),
        "copywriterBrief": copywriter_brief,
        "editorRecommendation": recommendation,
        "doctrineContext": _parse_object(packet.get("doctrine_context") or packet.get("doctrineContext")),
        "contextOrder": _parse_array(assignment_meta.get("reportingContextOrder")),
        "privateUseOnly": True,
    }


def validate_research_packet_mode(packet: dict[str, Any]) -> None:
    if packet.get("researchMode") == "internal_brief":
        return
    source_discovery = packet.get("sourceDiscovery") or {}
    research_trace = packet.get("researchTrace") or {}
    has_web = bool(_parse_array(source_discovery.get("webSearches")))
    if not has_web:
        has_web = bool(_parse_array(research_trace.get("webSearches") or research_trace.get("web_searches")))
    has_snapshots = bool(_parse_array(source_discovery.get("sourceSnapshots")) or packet.get("sourceSnapshots"))
    has_proposals = bool(_parse_array(source_discovery.get("proposedReferences")) or packet.get("proposedReferences"))
    blocked = normalize_string(source_discovery.get("blockedReason") or packet.get("blockedReason"))
    if not has_web and not has_snapshots and not has_proposals and not blocked:
        raise ValueError(
            f"research mode {packet.get('researchMode')} requires web discovery fields or blockedReason before persistence."
        )


def validate_reporting_packet(packet: dict[str, Any]) -> None:
    required_strings = {
        "reporting.summary": packet.get("summary"),
        "reporting.section_key": packet.get("sectionKey"),
        "reporting.recommended_angle": packet.get("recommendedAngle"),
        "reporting.copywriter_brief": packet.get("copywriterBrief"),
        "reporting.editor_recommendation": packet.get("editorRecommendation"),
    }
    for field_name, value in required_strings.items():
        if not normalize_string(value):
            raise ValueError(f"{field_name} is required before persistence.")
    recommendation = normalize_reporting_recommendation(packet.get("editorRecommendation"))
    accepted = _parse_string_array(packet.get("acceptedReferenceIds"))
    verification_needs = _parse_array(packet.get("verificationNeeds"))
    if recommendation in {"select", "brief"} and not accepted and not verification_needs:
        raise ValueError(
            "reporting editor_recommendation select/brief requires accepted_reference_ids or verification_needs."
        )
    if packet.get("proposedReferences") and not verification_needs:
        raise ValueError("reporting proposed_references require verification_needs before persistence.")
    if not _has_reporting_knowledge_orientation_trace(packet):
        blocked_reason = normalize_string(packet.get("knowledgeBlockedReason"))
        if blocked_reason:
            return
        raise ValueError(
            "reporting packets require knowledge-orientation trace in source_trail or related metadata "
            "(knowledge_queries/papyrus_uris_inspected), unless knowledge_blocked_reason is provided."
        )


def normalize_reporting_recommendation(value: Any) -> str:
    recommendation = normalize_string(value).replace("-", "_").lower() or "hold"
    if recommendation not in REPORTING_RECOMMENDATIONS:
        raise ValueError(
            f"Invalid reporting editor recommendation {value}. Expected one of: select, merge, brief, hold, kill."
        )
    return recommendation


def research_packet_hash(*, assignment_id: str, research_mode: str, packet: dict[str, Any]) -> str:
    return hash_short({"assignmentId": assignment_id, "researchMode": research_mode, "packet": packet})


def research_packet_body(packet: dict[str, Any]) -> str:
    lines = [packet.get("summary") or ""]
    for label, value in (
        ("Research mode", packet.get("researchMode")),
        ("Recommended angle", packet.get("recommendedAngle")),
    ):
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(line for line in lines if line)


def reporting_packet_body(packet: dict[str, Any]) -> str:
    lines = [
        packet.get("summary") or "",
        "",
        f"Section: {packet.get('sectionKey') or 'unknown'}",
        f"Editor recommendation: {packet.get('editorRecommendation') or 'hold'}",
        f"Why now: {packet.get('whyNow') or ''}",
        f"Recommended angle: {packet.get('recommendedAngle') or ''}",
        f"Nut graf candidate: {packet.get('nutGrafCandidate') or ''}",
        "",
        "Copywriter brief:",
        packet.get("copywriterBrief") or "",
    ]
    for label, values in (
        ("Confirmed facts", packet.get("confirmedFacts")),
        ("Accepted references", packet.get("acceptedReferenceIds")),
        ("Verification needs", packet.get("verificationNeeds")),
        ("Open questions", packet.get("openQuestions")),
        ("Coverage gaps", packet.get("coverageGaps")),
    ):
        entries = _parse_array(values)
        if not entries:
            continue
        lines.append("")
        lines.append(f"{label}:")
        for entry in entries:
            lines.append(f"- {entry if isinstance(entry, str) else json.dumps(entry, sort_keys=True)}")
    return "\n".join(line for line in lines if line is not None)


def reporting_packet_message_id(assignment_id: str, *, created_at: str, summary: str = "") -> str:
    timestamp = timestamp_for_path(created_at)
    suffix = hash_short([assignment_id, summary, created_at, "reporting_context_packet"])
    return f"message-reporting-context-packet-{safe_id(assignment_id)[:48]}-{timestamp}-{suffix}"


def _has_reporting_knowledge_orientation_trace(packet: dict[str, Any]) -> bool:
    if _parse_array(packet.get("knowledgeQueries")):
        return True
    if _parse_array(packet.get("papyrusUrisInspected")):
        return True
    if _parse_string_array(packet.get("acceptedReferenceIds")):
        return True
    for entry in _parse_array(packet.get("sourceTrail")):
        if not isinstance(entry, dict):
            continue
        source_kind = normalize_string(entry.get("source_kind") or entry.get("sourceKind") or entry.get("kind") or entry.get("type")).lower()
        source_uri = normalize_string(entry.get("uri") or entry.get("source_uri") or entry.get("sourceUri")).lower()
        reference_id = normalize_string(entry.get("reference_id") or entry.get("referenceId"))
        if reference_id:
            return True
        if source_uri.startswith("papyrus://"):
            return True
        if any(token in source_kind for token in ("knowledge", "papyrus", "accepted_reference", "desk_memory")):
            return True
    return False


def is_assignment_packet_relation(relation: dict[str, Any], assignment_id: str, message_id: str | None = None) -> bool:
    if relation.get("relationState") == "superseded":
        return False
    relation_type = relation.get("relationTypeKey") or relation.get("predicate")
    produces = (
        relation_type == "produces"
        and relation.get("subjectKind") == "assignment"
        and relation.get("subjectId") == assignment_id
        and relation.get("objectKind") == "message"
        and (message_id is None or relation.get("objectId") == message_id)
    )
    comment = (
        relation_type == "comment"
        and relation.get("subjectKind") == "message"
        and (message_id is None or relation.get("subjectId") == message_id)
        and relation.get("objectKind") == "assignment"
        and relation.get("objectId") == assignment_id
    )
    return produces or comment


def extract_research_packet_proposals(packet: dict[str, Any]) -> list[dict[str, Any]]:
    proposals = [
        *_parse_array(packet.get("proposedReferences")),
        *_parse_array((packet.get("sourceDiscovery") or {}).get("proposedReferences")),
    ]
    by_url: dict[str, dict[str, Any]] = {}
    for proposal in proposals:
        url = normalize_proposal_url(
            proposal.get("url") or proposal.get("source_uri") or proposal.get("sourceUri") or proposal.get("uri")
        )
        if url and url not in by_url:
            by_url[url] = {**proposal, "url": url}
    return list(by_url.values())


def build_research_proposal_catalog_items(
    proposals: list[dict[str, Any]],
    *,
    assignment: dict[str, Any],
    message: dict[str, Any],
    packet: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for proposal in proposals:
        url = normalize_proposal_url(proposal.get("url"))
        if not url:
            continue
        title = normalize_string(proposal.get("title") or proposal.get("name"))
        item_id = f"research-proposal-{hash_short(url)}"
        items.append(
            {
                "id": item_id,
                "item_id": item_id,
                "title": title,
                "source_uri": url,
                "media_type": normalize_string(proposal.get("media_type") or proposal.get("mediaType")) or "text/html",
                "ingestion_rationale": normalize_string(
                    proposal.get("ingestion_rationale")
                    or proposal.get("ingestionRationale")
                    or proposal.get("rationale")
                )
                or f"{title or 'This source'} was proposed by research assignment {assignment.get('title') or assignment['id']}.",
                "metadata": {
                    "research_assignment_id": assignment["id"],
                    "research_packet_message_id": message.get("id"),
                    "research_mode": packet.get("researchMode"),
                },
            }
        )
    return items


def normalize_proposal_url(value: Any) -> str | None:
    text = normalize_string(value)
    if not text:
        return None
    try:
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        netloc = (parsed.netloc or "").lower()
        path = parsed.path or ""
        if path and path != "/":
            path = path.rstrip("/")
        normalized = urlunparse((parsed.scheme.lower(), netloc, path, parsed.params, parsed.query, ""))
        return normalized
    except ValueError:
        return None


def update_newsroom_summary_after_research_packet_creates(
    client: PapyrusGraphQLAuthoringClient,
    changes: list[dict[str, Any]],
    *,
    actor_label: str,
    reason: str,
) -> None:
    created_messages = [change["expected"] for change in changes if change.get("modelName") == "Message" and change.get("action") == "create"]
    created_attachments = [
        change["expected"] for change in changes if change.get("modelName") == "ModelAttachment" and change.get("action") == "create"
    ]
    created_relations = [
        change["expected"] for change in changes if change.get("modelName") == "SemanticRelation" and change.get("action") == "create"
    ]
    if not created_messages and not created_attachments and not created_relations:
        return
    client.update_newsroom_summary(
        {
            "source": "incremental",
            "countDeltas": {
                "messages": len(created_messages),
                "modelAttachments": len(created_attachments),
                "semanticRelations": len(created_relations),
            },
        },
        actor_label=actor_label,
        reason=reason,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def now_iso() -> str:
    return _utc_now()


def timestamp_for_path(value: str | None = None) -> str:
    return "".join(ch for ch in (value or _utc_now()) if ch.isdigit() or ch in {"T", "Z"})


def _normalize_section_type(value: Any) -> str | None:
    normalized = normalize_string(value)
    if normalized and normalized.lower() == "rotating":
        return "floating"
    return normalized.lower() if normalized else None


def _normalize_proposal_intake_status(value: Any) -> str:
    status = normalize_reference_curation_status(value, "pending")
    if status not in {"pending", "rejected"}:
        raise ValueError(f"Research proposal intake supports --status pending|rejected, not {status}.")
    return status


def _parse_array(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _parse_object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _parse_string_array(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(entry) for entry in value if entry is not None]


def _count_delta(changes: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for change in changes:
        key = str(change.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _print_create_research_summary(action: str, result: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    print(f"assignments\tcreate-research\taction\t{action}")
    print(f"assignments\tcreate-research\tassignment\t{result['assignmentId']}")
    print(f"assignments\tcreate-research\tstatus\t{result['status']}")
    print(f"assignments\tcreate-research\ttype\t{result['assignmentTypeKey']}")
    print(f"assignments\tcreate-research\tresearch-mode\t{result['researchMode']}")
    print(f"assignments\tcreate-research\tsection\t{result.get('sectionKey') or ''}")
    print(f"assignments\tcreate-research\tqueue\t{result['queueKey']}")
    action_counts = _count_delta(changes, "action")
    print(
        f"assignments\tcreate-research\tchanges\tcreate={action_counts.get('create', 0)}\t"
        f"update={action_counts.get('update', 0)}\tnoop={action_counts.get('noop', 0)}"
    )


def _print_create_reporting_summary(action: str, result: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    print(f"assignments\tcreate-reporting\taction\t{action}")
    print(f"assignments\tcreate-reporting\tassignment\t{result['assignmentId']}")
    print(f"assignments\tcreate-reporting\tstatus\t{result['status']}")
    print(f"assignments\tcreate-reporting\ttype\t{result['assignmentTypeKey']}")
    print(f"assignments\tcreate-reporting\tsection\t{result.get('sectionKey') or ''}")
    print(f"assignments\tcreate-reporting\tqueue\t{result['queueKey']}")
    action_counts = _count_delta(changes, "action")
    print(
        f"assignments\tcreate-reporting\tchanges\tcreate={action_counts.get('create', 0)}\t"
        f"update={action_counts.get('update', 0)}\tnoop={action_counts.get('noop', 0)}"
    )


def _print_apply_research_packet_summary(action: str, result: dict[str, Any]) -> None:
    print(f"assignments\tapply-research-packet\taction\t{action}")
    print(f"assignments\tapply-research-packet\tassignment\t{result['assignmentId']}")
    print(f"assignments\tapply-research-packet\tmessage\t{result['messageId']}")
    print(f"assignments\tapply-research-packet\tresearch-mode\t{result['researchMode']}")
    print(
        f"assignments\tapply-research-packet\tcounts\tevidence={result['evidenceItemCount']}\t"
        f"sources={result['sourceSnapshotCount']}\tproposals={result['proposedReferenceCount']}"
    )


def _print_apply_reporting_packet_summary(action: str, result: dict[str, Any]) -> None:
    print(f"assignments\tapply-reporting-packet\taction\t{action}")
    print(f"assignments\tapply-reporting-packet\tassignment\t{result['assignmentId']}")
    print(f"assignments\tapply-reporting-packet\tmessage\t{result['messageId']}")
    print(f"assignments\tapply-reporting-packet\tcanonical-policy\t{result['canonicalPolicy']}")
    print(f"assignments\tapply-reporting-packet\trecommendation\t{result['editorRecommendation']}")
    print(
        f"assignments\tapply-reporting-packet\tcounts\taccepted={result['acceptedReferenceCount']}\t"
        f"sources={result['sourceTrailCount']}\tproposals={result['proposedReferenceCount']}\t"
        f"verification={result['verificationNeedCount']}"
    )
    print(
        f"assignments\tapply-reporting-packet\tknowledge\tqueries={result['knowledgeQueryCount']}\t"
        f"uris={result['papyrusUriCount']}"
    )
    if result.get("knowledgeBlockedReason"):
        print(f"assignments\tapply-reporting-packet\tknowledge-blocked\t{result.get('knowledgeBlockedReason')}")


def _research_proposal_intake_reference_rows(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    references = [
        change for change in changes if change.get("modelName") == "Reference" and change.get("expected")
    ]
    rows = []
    for change in references:
        reference = change["expected"]
        rows.append(
            {
                "referenceId": reference.get("id"),
                "title": reference.get("title"),
                "url": reference.get("sourceUri"),
                "status": reference.get("curationStatus"),
                "action": change.get("action"),
            }
        )
    return rows


def run_story_cycle(flags: list[str]) -> None:
    options = parse_options(flags)
    args = _coverage_theme_run_args(options)
    payload = run_papyrus_cli_json(["assignments", "run-story-cycle", *args])
    payload["command"] = "assignments run-story-cycle"
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    print(f"assignments\trun-story-cycle\taction\t{'apply' if options.get('apply') else 'dry-run'}")
    print(f"assignments\trun-story-cycle\trun\t{payload.get('runId')}")
    print(f"assignments\trun-story-cycle\ttopic\t{payload.get('topic')}")
    if payload.get("next"):
        print(f"assignments\trun-story-cycle\tnext\t{payload['next']}")


def story_cycle_output(flags: list[str]) -> None:
    options = parse_options(flags)
    args = []
    for key in ("run-id", "edition", "coverage-key", "section"):
        if options.get(key):
            args.extend([f"--{key}", str(options[key])])
    if options.get("json"):
        args.append("--json")
    payload = run_papyrus_cli_json(["assignments", "story-cycle-output", *args])
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    for section in payload.get("sections") or []:
        print(
            f"section\t{section.get('sectionKey')}\t{section.get('sectionTitle')}\t"
            f"research={len(section.get('researchPackets') or [])}\t"
            f"reporting={len(section.get('reportingPackets') or [])}"
        )


def orphan_research_packets(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> None:
    messages = client.list_records("Message")
    relations = client.list_records("SemanticRelation")
    linked = {
        relation["objectId"] if relation.get("objectKind") == "message" else relation["subjectId"]
        for relation in relations
        if relation.get("relationState") == "current"
        and (relation.get("relationTypeKey") or relation.get("predicate")) in {"comment", "produces"}
    }
    orphans = [
        message
        for message in messages
        if message.get("messageKind") == "research_packet" and message.get("id") not in linked
    ]
    orphans.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
    if options.get("json"):
        print(json.dumps({"ok": True, "count": len(orphans), "orphans": orphans}, indent=2))
        return
    if not orphans:
        print("assignment-research-packet-orphans\t0")
        return
    for row in orphans:
        print("\t".join([row.get("createdAt") or "-", row["id"], row.get("status") or "-", row.get("summary") or "Stored research packet"]))


def backfill_section_indexes(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> None:
    apply = resolve_mutation_apply(options, "assignments backfill-section-indexes")
    target_section = normalize_string(options.get("section"))
    valid_sections = {
        key
        for section in client.safe_list_records("NewsroomSection")
        if section.get("enabled") is not False and section.get("enabledStatus") != "disabled"
        for key in (normalize_string(section.get("id")), normalize_string(section.get("sectionKey")))
        if key
    }
    changes: list[dict[str, Any]] = []
    skipped_invalid = 0
    for assignment in client.list_records("Assignment"):
        raw_section = assignment_section_key(assignment)
        patch = _assignment_section_index_patch(assignment, valid_section_keys=valid_sections)
        if raw_section and raw_section not in valid_sections:
            skipped_invalid += 1
        if target_section and patch.get("sectionKey") != target_section:
            continue
        expected = {**assignment, **patch}
        if expected == assignment:
            continue
        changes.append({"current": assignment, "expected": expected})
    print(f"assignments\tbackfill-section-indexes\tplanned\t{len(changes)}")
    if target_section:
        print(f"assignments\tbackfill-section-indexes\tsection\t{target_section}")
    if skipped_invalid:
        print(f"assignments\tbackfill-section-indexes\tskipped-invalid-section-keys\t{skipped_invalid}")
    for change in changes[:25]:
        expected = change["expected"]
        print(
            "\t".join(
                [
                    "assignment-section-index",
                    expected["id"],
                    expected.get("status") or "",
                    f"section={expected.get('sectionKey') or ''}",
                    f"sectionStatusKey={expected.get('sectionStatusKey') or ''}",
                    f"sectionQueueStatusKey={expected.get('sectionQueueStatusKey') or ''}",
                ]
            )
        )
    if len(changes) > 25:
        print(f"assignments\tbackfill-section-indexes\tpreview-truncated\t{len(changes) - 25} more")
    if not apply:
        print("assignments\tbackfill-section-indexes\tapply\tskipped\tuse --dry-run to preview without writes")
        print("assignments\tbackfill-section-indexes\tnext\tpoetry run papyrus sections recount-summary")
        return
    for index, change in enumerate(changes, start=1):
        client.upsert("Assignment", change["expected"])
        if index == len(changes) or index % 100 == 0:
            print(f"assignments\tbackfill-section-indexes\tprogress\t{index}/{len(changes)}", flush=True)
    print(f"assignments\tbackfill-section-indexes\tupdated\t{len(changes)}")
    print("assignments\tbackfill-section-indexes\tnext\tpoetry run papyrus sections recount-summary")


def backfill_content_items(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> None:
    apply = resolve_mutation_apply(options, "assignments backfill-content-items")
    items = client.list_records("Item")
    lineage_id_by_item_id = {item["id"]: item.get("lineageId") or item["id"] for item in items if item.get("id")}
    assignments = client.list_records("Assignment")
    reporting_assignments = [
        assignment for assignment in assignments if str(assignment.get("assignmentTypeKey") or "").startswith("reporting.")
    ]
    copywriting_work = []
    for assignment in assignments:
        if assignment.get("assignmentTypeKey") not in COPYWRITING_ASSIGNMENT_TYPES or assignment.get("itemLineageId"):
            continue
        relations = client.list_semantic_relations_by_subject_state(semantic_state_key("assignment", assignment["id"]))
        copywriting_work.append(
            {
                "assignment": assignment,
                "sourceReportingAssignmentId": assignment_metadata(client, assignment).get("sourceReportingAssignmentId"),
                "producedItemLineageIds": [
                    lineage_id_by_item_id.get(item_id, item_id) for item_id in _produced_item_ids_from_relations(relations)
                ],
            }
        )
    plan = plan_content_item_backfill(
        items=items,
        reporting_assignments=reporting_assignments,
        copywriting_work=copywriting_work,
        actor_label=normalize_string(options.get("actor")) or "papyrus-content-item-backfill",
        now=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    changes = plan["changes"]
    print(f"assignments\tbackfill-content-items\tplanned\t{len(changes)}")
    for warning in plan["warnings"]:
        print(f"assignments\tbackfill-content-items\twarning\t{warning}")
    for change in changes[:25]:
        expected = change["expected"]
        print(
            "\t".join(
                [
                    "content-item-backfill",
                    change["modelName"],
                    "create" if change["current"] is None else "update",
                    expected["id"],
                    f"lineage={expected.get('itemLineageId') or expected.get('lineageId') or ''}",
                    f"stage={expected.get('stage') or ''}",
                ]
            )
        )
    if len(changes) > 25:
        print(f"assignments\tbackfill-content-items\tpreview-truncated\t{len(changes) - 25} more")
    if not apply:
        print("assignments\tbackfill-content-items\tapply\tskipped\tdry run; rerun without --dry-run to write")
        return
    for index, change in enumerate(changes, start=1):
        client.upsert(change["modelName"], change["expected"])
        if index == len(changes) or index % 100 == 0:
            print(f"assignments\tbackfill-content-items\tprogress\t{index}/{len(changes)}", flush=True)
    print(f"assignments\tbackfill-content-items\tupdated\t{len(changes)}")


def demote_undrafted_content_items(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> None:
    apply = resolve_mutation_apply(options, "assignments demote-undrafted-content-items")
    items = client.list_records("Item")
    reporting_assignments = [
        assignment
        for assignment in client.list_records("Assignment")
        if str(assignment.get("assignmentTypeKey") or "").startswith("reporting.")
    ]
    changes = plan_undrafted_backfill_story_demotion(items=items, reporting_assignments=reporting_assignments)
    print(f"assignments\tdemote-undrafted-content-items\tplanned\t{len(changes)}")
    for change in changes:
        expected = change["expected"]
        print(
            "\t".join(
                [
                    "content-item-demotion",
                    expected["id"],
                    f"from={change['current'].get('stage')}",
                    "to=assignment",
                    f"title={expected.get('title') or ''}",
                ]
            )
        )
    if not apply:
        print("assignments\tdemote-undrafted-content-items\tapply\tskipped\tdry run; rerun without --dry-run to write")
        return
    for change in changes:
        client.upsert("Item", change["expected"])
    print(f"assignments\tdemote-undrafted-content-items\tupdated\t{len(changes)}")


def list_assignments_for_object(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> None:
    kind = options.get("kind")
    lineage = options.get("lineage")
    if not kind or not lineage:
        raise ValueError("assignments for-object requires --kind and --lineage.")
    state_key = f"{kind}#{lineage}#current"
    relations = [
        relation
        for relation in client.list_records("SemanticRelation")
        if relation.get("relationState") == "current"
        and relation.get("objectStateKey") == state_key
        and relation.get("subjectKind") == "assignment"
        and (relation.get("relationTypeKey") or relation.get("predicate")) == "requests_work_on"
    ]
    assignment_ids = {relation["subjectId"] for relation in relations}
    assignments = [row for row in client.list_records("Assignment") if row.get("id") in assignment_ids]
    assignments.sort(key=assignment_sort_key)
    for assignment in assignments:
        print(f"{assignment.get('status')}\t{assignment.get('id')}\t{assignment.get('assignmentTypeKey')}\t{assignment.get('title')}")


def build_assignment_context(flags: list[str]) -> None:
    options = parse_options(flags)
    assignment_id = options.get("assignment")
    if not assignment_id:
        raise ValueError("assignments build-context requires --assignment.")
    output_path = options.get("output") or str(
        PAPYRUS_ROOT / ".papyrus-runs" / timestamp_for_path() / f"assignment-context-{assignment_id}.json"
    )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    payload = run_papyrus_cli_json(
        [
            "assignments",
            "build-assignment-agent-context",
            "--assignment-id",
            assignment_id,
            "--context-profile",
            str(options.get("context-profile") or ""),
            "--max-tokens",
            str(options.get("max-tokens") or 0),
            "--recent-days",
            str(options.get("recent-days") or 30),
        ]
    )
    Path(output_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    context = payload.get("assignment_agent_context") or {}
    print(f"assignment-context\tassignment\t{assignment_id}")
    print(
        f"assignment-context\tprofile\t{context.get('contextProfile') or 'unknown'}\t"
        f"budget={context.get('contextTokenBudget') or 0}"
    )
    print(f"assignment-context\toutput\t{output_path}")


def list_assignment_research_packets(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> None:
    assignment_id = options.get("assignment")
    if not assignment_id:
        raise ValueError("assignments research-packets requires --assignment.")
    packets = load_assignment_research_packet_entries(client, assignment_id)
    if options.get("json"):
        print(
            json.dumps(
                {
                    "ok": True,
                    "assignmentId": assignment_id,
                    "count": len(packets),
                    "packets": [
                        {
                            "messageId": entry["message"]["id"],
                            "createdAt": entry["message"].get("createdAt"),
                            "summary": entry["message"].get("summary"),
                            "proposedReferenceCount": len(entry["packet"].get("proposedReferences") or []),
                        }
                        for entry in packets
                    ],
                },
                indent=2,
            )
        )
        return
    for entry in packets:
        message = entry["message"]
        packet = entry["packet"]
        print(
            "\t".join(
                [
                    str(message.get("createdAt") or ""),
                    message["id"],
                    str(len(packet.get("proposedReferences") or [])),
                    str(len(packet.get("sourceSnapshots") or [])),
                    message.get("summary") or "Stored research packet",
                ]
            )
        )
    if not packets:
        print(f"assignment-research-packets\t{assignment_id}\t0")


def review_reporting_packet(
    client: PapyrusGraphQLAuthoringClient,
    auth_claims: dict[str, Any],
    options: dict[str, Any],
) -> None:
    assignment_id = normalize_string(options.get("assignment"))
    message_id = normalize_string(options.get("message"))
    if not assignment_id:
        raise ValueError("assignments review-reporting-packet requires --assignment.")
    if not message_id:
        raise ValueError("assignments review-reporting-packet requires --message.")
    assignment = client.get_record("Assignment", assignment_id)
    message = client.get_record("Message", message_id)
    if not assignment:
        raise ValueError(f"Assignment {assignment_id} was not found.")
    if not message:
        raise ValueError(f"Message {message_id} was not found.")
    target_item_id = normalize_string(options.get("target-item"))
    target_item = client.get_record("Item", target_item_id) if target_item_id else None
    if target_item_id and not target_item:
        raise ValueError(f"Target Item {target_item_id} was not found.")
    relations = _load_reporting_packet_review_relations(client, assignment_id=assignment_id, message_id=message_id)
    actor_label = (
        normalize_string(options.get("actor-label"))
        or normalize_string(auth_claims.get("email"))
        or normalize_string(auth_claims.get("sub"))
        or "papyrus-cli"
    )
    plan = build_reporting_packet_review_plan(
        assignment=assignment,
        message={**message, "metadata": load_message_metadata_payload(client, message)},
        decision=str(options.get("decision") or ""),
        note=str(options.get("note") or ""),
        target_item=target_item,
        actor_label=actor_label,
        actor_sub=auth_claims.get("sub"),
        semantic_relations=relations,
    )
    changes = build_record_changes_tolerating_optional_models(client, plan["records"])
    apply = resolve_mutation_apply(options, "assignments review-reporting-packet")
    if apply:
        apply_record_changes(client, changes)
        update_newsroom_summary_after_assignment_creates(
            client,
            changes,
            actor_label=actor_label,
            reason=f"assignments review-reporting-packet {assignment_id}",
        )
    print(f"reporting-packet-review\tmode\t{'apply' if apply else 'dry-run'}")
    print(f"reporting-packet-review\tassignment\t{assignment_id}")
    print(f"reporting-packet-review\tmessage\t{message_id}")
    print(f"reporting-packet-review\tdecision\t{plan['decision']}")
    if not apply:
        print("reporting-packet-review\tapply\tskipped\tuse --dry-run to preview without writes")


def run_copywriting_assignment(
    client: PapyrusGraphQLAuthoringClient,
    auth_claims: dict[str, Any],
    options: dict[str, Any],
) -> None:
    assignment_id = normalize_string(options.get("assignment"))
    if not assignment_id:
        raise ValueError("assignments run-copywriting requires --assignment.")
    assignment = client.get_record("Assignment", assignment_id)
    if not assignment:
        raise ValueError(f"Assignment {assignment_id} was not found.")
    meta = assignment_metadata(client, assignment)
    relations = client.list_semantic_relations_by_subject_state(semantic_state_key("assignment", assignment_id))
    content_item_versions = client.list_by_index(
        "itemsByLineageAndVersion", require_assignment_content_item_lineage_id(assignment)
    )
    packet_message_id = (
        normalize_string(options.get("message"))
        or normalize_string(meta.get("sourceReportingPacketMessageId"))
        or _find_source_reporting_packet_message_id(relations, assignment_id)
    )
    if not packet_message_id:
        raise ValueError(f"Copywriting Assignment {assignment_id} is missing a source reporting packet Message.")
    reporting_message = client.get_record("Message", packet_message_id)
    if not reporting_message:
        raise ValueError(f"Reporting packet Message {packet_message_id} was not found.")
    actor_label = (
        normalize_string(options.get("actor-label"))
        or normalize_string(auth_claims.get("email"))
        or normalize_string(auth_claims.get("sub"))
        or "papyrus-cli"
    )
    plan = build_copywriting_run_plan(
        assignment=assignment,
        assignment_metadata=meta,
        reporting_packet_message=reporting_message,
        reporting_packet_payload=load_message_metadata_payload(client, reporting_message),
        existing_items=content_item_versions,
        actor_label=actor_label,
        actor_sub=auth_claims.get("sub"),
    )
    changes = build_record_changes_tolerating_optional_models(client, plan["records"])
    apply = resolve_mutation_apply(options, "assignments run-copywriting")
    if apply:
        apply_record_changes(client, changes)
    print(f"copywriting\tmode\t{'apply' if apply else 'dry-run'}")
    print(f"copywriting\tassignment\t{assignment_id}")
    print(f"copywriting\tdraft-item\t{plan['summary']['draftItemId']}")
    if not apply:
        print("copywriting\tapply\tskipped\tuse --dry-run to preview without writes")


def copywriting_output(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> None:
    requested_id = normalize_string(options.get("assignment"))
    rows = []
    if requested_id:
        assignment = client.get_record("Assignment", requested_id)
        if assignment and assignment.get("assignmentTypeKey") in COPYWRITING_ASSIGNMENT_TYPES:
            rows = [_copywriting_output_row(client, assignment)]
    else:
        assignments = _load_copywriting_assignments(client)
        rows = [_copywriting_output_row(client, assignment) for assignment in assignments]
    if options.get("json"):
        print(json.dumps({"ok": True, "count": len(rows), "copywritingAssignments": rows}, indent=2))
        return
    for row in rows:
        print(
            "\t".join(
                [
                    row.get("storyCycleRunId") or "-",
                    row.get("sectionKey") or "-",
                    row["assignmentId"],
                    row.get("status") or "-",
                    row.get("targetItemType") or "-",
                    row.get("sourceReportingPacketMessageId") or "-",
                    row.get("draftItemId") or "-",
                    str(row.get("draftVersionNumber") or "-"),
                ]
            )
        )
    print(f"assignments\tcopywriting-output\t{len(rows)}")


def list_assignment_events(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> None:
    assignment_id = options.get("assignment")
    if not assignment_id:
        raise ValueError("assignments events requires --assignment.")
    events = [
        event
        for event in client.list_records("AssignmentEvent")
        if event.get("assignmentId") == assignment_id
    ]
    events.sort(key=lambda event: str(event.get("createdAt") or ""))
    for event in events:
        print(
            "\t".join(
                [
                    str(event.get("createdAt") or ""),
                    event.get("eventType") or "",
                    f"{event.get('fromStatus') or ''}->{event.get('toStatus') or ''}",
                    event.get("note") or "",
                ]
            )
        )
    print(f"assignments\tevents\t{assignment_id}\t{len(events)}")


def process_assignment_queue(
    client: PapyrusGraphQLAuthoringClient,
    auth_claims: dict[str, Any],
    options: dict[str, Any],
) -> None:
    assignment_type_key = normalize_string(options.get("type"))
    if not assignment_type_key:
        raise ValueError("assignments process-queue requires --type <assignment-type-key>.")
    queue_key = normalize_string(options.get("queue"))
    section_key = normalize_string(options.get("section"))
    target_status = normalize_string(options.get("status")) or "open"
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count") or 10
    dry_run = parse_boolean_option(options.get("dry-run"), False, "--dry-run")
    actor_label = (
        normalize_string(options.get("assignee-key"))
        or normalize_string(options.get("assignee"))
        or normalize_string(options.get("actor"))
        or normalize_string(auth_claims.get("email"))
        or normalize_string(auth_claims.get("sub"))
        or "papyrus-cli"
    )
    query_plan = _assignment_queue_query_plan(
        assignment_type_key=assignment_type_key,
        queue_key=queue_key,
        section_key=section_key,
        status=target_status,
    )
    fetched = query_plan["execute"](client)
    candidates = [
        assignment
        for assignment in fetched
        if assignment.get("assignmentTypeKey") == assignment_type_key
        and (not queue_key or assignment.get("queueKey") == queue_key)
        and (not section_key or assignment_section_key(assignment) == section_key)
        and assignment.get("status") == target_status
    ]
    candidates.sort(key=assignment_sort_key)
    selected = candidates[:max_count]
    if dry_run:
        print("assignment-process-queue\tdry-run\ttrue")
        print(f"assignment-process-queue\tindex\t{query_plan['indexName']}\t{query_plan['key']}")
        print(f"assignment-process-queue\tcandidates\t{len(candidates)}")
        print(f"assignment-process-queue\tselected\t{len(selected)}")
        return
    for assignment in selected:
        try:
            apply_assignment_action(
                client,
                auth_claims=auth_claims,
                action="claim",
                assignment_id=assignment["id"],
                options=options,
                actor_label=actor_label,
            )
            _execute_assignment_by_type(client, assignment["id"], options)
            apply_assignment_action(
                client,
                auth_claims=auth_claims,
                action="complete",
                assignment_id=assignment["id"],
                options=options,
                actor_label=actor_label,
            )
            print(f"assignment-process-result\t{assignment['id']}\tcompleted")
        except Exception as error:
            print(f"assignment-process-result\t{assignment['id']}\tfailed\t{error}")
            if parse_boolean_option(options.get("stop-on-error"), True, "--stop-on-error"):
                break


def mutate_assignment(
    client: PapyrusGraphQLAuthoringClient,
    auth_claims: dict[str, Any],
    action: str,
    options: dict[str, Any],
) -> None:
    assignment_id = options.get("assignment")
    if not assignment_id:
        raise ValueError(f"assignments {action} requires --assignment.")
    before = client.get_record("Assignment", assignment_id)
    apply_assignment_action(
        client,
        auth_claims=auth_claims,
        action=action,
        assignment_id=assignment_id,
        options=options,
    )
    after = client.get_record("Assignment", assignment_id)
    if options.get("json"):
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": f"assignments {action}",
                    "assignmentId": assignment_id,
                    "previousStatus": (before or {}).get("status"),
                    "status": (after or {}).get("status"),
                },
                indent=2,
            )
        )
        return
    print(f"assignment\t{action}\t{assignment_id}\t{(before or {}).get('status')}->{(after or {}).get('status')}")


def _coverage_theme_run_args(options: dict[str, Any]) -> list[str]:
    args: list[str] = []
    mapping = {
        "date": "--date",
        "topic": "--topic",
        "category": "--category",
        "corpus-key": "--corpus-key",
        "coverage-key": "--coverage-key",
        "sections": "--sections",
        "section-budgets": "--section-budgets",
        "run-id": "--run-id",
        "through": "--through",
        "research-mode": "--research-mode",
    }
    for key, flag in mapping.items():
        if options.get(key) not in (None, True):
            args.extend([flag, str(options[key])])
    if parse_boolean_option(options.get("dry-run"), False, "--dry-run"):
        args.append("--dry-run")
    if options.get("json"):
        args.append("--json")
    if options.get("allow-fallback"):
        args.append("--allow-fallback")
    if options.get("require-agent-success"):
        args.append("--require-agent-success")
    if options.get("refresh-packets"):
        args.append("--refresh-packets")
    return args


def _assignment_section_index_patch(
    assignment: dict[str, Any],
    *,
    valid_section_keys: set[str],
) -> dict[str, Any]:
    section_key = assignment_section_key(assignment)
    status = assignment.get("status") or "open"
    queue_key = assignment.get("queueKey")
    patch = {
        "sectionKey": section_key if section_key in valid_section_keys else section_key,
        "sectionId": assignment.get("sectionId") or section_key,
        "sectionStatusKey": f"{section_key}#{status}" if section_key else None,
        "sectionQueueStatusKey": f"{section_key}#{queue_key}#{status}" if section_key and queue_key else None,
    }
    return patch


def _load_reporting_packet_review_relations(
    client: PapyrusGraphQLAuthoringClient,
    *,
    assignment_id: str,
    message_id: str,
) -> list[dict[str, Any]]:
    assignment_relations = client.list_semantic_relations_by_subject_state(semantic_state_key("assignment", assignment_id))
    message_relations = client.list_semantic_relations_by_subject_state(semantic_state_key("message", message_id))
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for relation in [*assignment_relations, *message_relations]:
        key = relation.get("id") or json.dumps(relation, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        merged.append(relation)
    return merged


def _produced_item_ids_from_relations(relations: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            relation["objectId"]
            for relation in relations
            if relation.get("relationState") != "superseded"
            and relation.get("objectKind") == "item"
            and (relation.get("relationTypeKey") or relation.get("predicate")) == "produces"
            and relation.get("objectId")
        }
    )


def _find_source_reporting_packet_message_id(relations: list[dict[str, Any]], assignment_id: str) -> str | None:
    for relation in relations:
        if (
            relation.get("relationState") != "superseded"
            and relation.get("subjectKind") == "assignment"
            and relation.get("subjectId") == assignment_id
            and relation.get("objectKind") == "message"
            and (relation.get("relationTypeKey") or relation.get("predicate")) == "derived_from"
        ):
            return normalize_string(relation.get("objectId"))
    return None


def _load_copywriting_assignments(client: PapyrusGraphQLAuthoringClient) -> list[dict[str, Any]]:
    groups = []
    for assignment_type in COPYWRITING_ASSIGNMENT_TYPES:
        try:
            groups.extend(client.list_assignments_by_type_status_and_created_at(assignment_type))
        except RuntimeError:
            continue
    by_id = {row["id"]: row for row in groups if row.get("id")}
    if by_id:
        return list(by_id.values())
    return [row for row in client.list_records("Assignment") if row.get("assignmentTypeKey") in COPYWRITING_ASSIGNMENT_TYPES]


def _copywriting_output_row(client: PapyrusGraphQLAuthoringClient, assignment: dict[str, Any]) -> dict[str, Any]:
    meta = assignment_metadata(client, assignment)
    relations = client.list_semantic_relations_by_subject_state(semantic_state_key("assignment", assignment["id"]))
    item_by_id = client.get_records_by_id("Item", _produced_item_ids_from_relations(relations))
    produced = sorted(item_by_id.values(), key=lambda item: int(item.get("versionNumber") or 0), reverse=True)
    draft = produced[0] if produced else None
    return {
        "assignmentId": assignment["id"],
        "assignmentTypeKey": assignment.get("assignmentTypeKey"),
        "status": assignment.get("status"),
        "sectionKey": assignment.get("sectionKey") or meta.get("sectionKey"),
        "storyCycleRunId": meta.get("storyCycleRunId") or meta.get("coverageThemeRunId") or meta.get("runId"),
        "sourceReportingPacketMessageId": meta.get("sourceReportingPacketMessageId"),
        "targetItemType": meta.get("targetItemType")
        or ("brief" if assignment.get("assignmentTypeKey") == "copywriting.brief-draft" else "article"),
        "draftItemId": draft.get("id") if draft else None,
        "draftVersionNumber": draft.get("versionNumber") if draft else None,
    }


def _assignment_queue_query_plan(
    *,
    assignment_type_key: str,
    queue_key: str | None,
    section_key: str | None,
    status: str,
) -> dict[str, Any]:
    if queue_key:
        key = f"{queue_key}#{status}"
        return {
            "indexName": "listAssignmentsByQueueStatusAndPriority",
            "key": key,
            "execute": lambda client: client.list_assignments_by_queue_status_and_priority(key),
        }
    return {
        "indexName": "listAssignmentsByTypeStatusAndCreatedAt",
        "key": assignment_type_key,
        "execute": lambda client: client.list_assignments_by_type_status_and_created_at(assignment_type_key),
    }


def _execute_assignment_by_type(
    client: PapyrusGraphQLAuthoringClient,
    assignment_id: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    from .assignment_executors import execute_assignment_by_type

    return execute_assignment_by_type(client, assignment_id, options)
