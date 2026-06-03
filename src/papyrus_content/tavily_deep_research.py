"""Tavily deep research assignments (research.tavily-deep)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from papyrus_newsroom import tavily_research
from papyrus_newsroom.tavily_research import (
    TavilyResearchFailed,
    TavilyResearchTimeout,
)

from .assignments import assignment_metadata
from .catalog import message_record, semantic_relation_record
from .ids import hash_short, knowledge_corpus_id, safe_id
from .model_attachments import parse_jsonish
from .options import (
    normalize_non_negative_integer,
    normalize_string,
    parse_boolean_option,
    parse_comma_list,
    parse_options,
    resolve_mutation_apply,
)
from .records import apply_record_changes, build_record_changes
from .graphql_authoring import PapyrusGraphQLAuthoringClient

from .assignments_workflow import (
    _utc_now,
    apply_research_packet,
    intake_research_packet_proposals,
    is_assignment_packet_relation,
    load_assignment_research_packet_entries,
    load_message_metadata_payload,
    normalize_proposal_url,
    normalize_research_mode,
    semantic_state_key,
    timestamp_for_path,
    update_newsroom_summary_after_research_packet_creates,
)
from .insight_forum import (
    derive_insight_forum_title,
    derive_insight_packet_lede,
    format_tavily_insight_message_body,
)

TAVILY_DEEP_ASSIGNMENT_TYPE = "research.tavily-deep"
TAVILY_TASK_MESSAGE_KIND = "tavily_research_task"
TAVILY_ERROR_MESSAGE_KIND = "tavily_research_error"
DEFAULT_TAVILY_MODEL = "auto"


def is_tavily_deep_assignment(assignment: dict[str, Any], assignment_meta: dict[str, Any] | None = None) -> bool:
    assignment_type = normalize_string(assignment.get("assignmentTypeKey")) or ""
    if assignment_type == TAVILY_DEEP_ASSIGNMENT_TYPE:
        return True
    meta = assignment_meta if assignment_meta is not None else {}
    return normalize_string(meta.get("researchBackend")) == "tavily_deep"


def tavily_deep_next_command(*, assignment_id: str, corpus_key: str) -> str:
    return (
        f"poetry run papyrus assignments run-tavily-deep-research --assignment {assignment_id} "
        f"--corpus-key {corpus_key}"
    )


def tavily_research_input_for_assignment(
    assignment: dict[str, Any],
    assignment_meta: dict[str, Any],
    *,
    override: str = "",
) -> str:
    explicit = normalize_string(override)
    if explicit:
        return explicit
    for candidate in (
        assignment.get("instructions"),
        assignment.get("brief"),
        assignment.get("summary"),
        assignment.get("title"),
    ):
        text = normalize_string(candidate)
        if text:
            return text
    focus = normalize_string(assignment_meta.get("primaryFocusCategoryKey"))
    if focus:
        return focus
    return normalize_string(assignment.get("title")) or "Research assignment"


def load_tavily_task_message(
    client: PapyrusGraphQLAuthoringClient,
    assignment_id: str,
) -> dict[str, Any] | None:
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
    tasks: list[dict[str, Any]] = []
    for message in message_by_id.values():
        if message.get("messageKind") != TAVILY_TASK_MESSAGE_KIND:
            continue
        metadata = load_message_metadata_payload(client, message)
        tasks.append({**message, "_metadata": metadata})
    if not tasks:
        return None
    tasks.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
    return tasks[0]


def _assignment_event_record(
    *,
    assignment: dict[str, Any],
    event_type: str,
    note: str,
    actor_label: str,
    now: str,
) -> dict[str, Any]:
    assignment_id = str(assignment["id"])
    return {
        "modelName": "AssignmentEvent",
        "expected": {
            "id": f"assignment-event-{safe_id(assignment_id)}-{event_type}-{timestamp_for_path(now)}",
            "assignmentId": assignment_id,
            "assignmentTypeKey": assignment.get("assignmentTypeKey"),
            "queueKey": assignment.get("queueKey"),
            "eventType": event_type,
            "fromStatus": assignment.get("status"),
            "toStatus": assignment.get("status"),
            "actorLabel": actor_label,
            "note": note,
            "createdAt": now,
        },
    }


def _produces_assignment_message_relation(
    *,
    assignment: dict[str, Any],
    message_id: str,
    now: str,
    lifecycle: str,
    message_kind: str,
    metadata_kind: str,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assignment_id = str(assignment["id"])
    metadata = {
        "lifecycle": lifecycle,
        "messageKind": message_kind,
        "metadataKind": metadata_kind,
        "assignmentTypeKey": assignment.get("assignmentTypeKey"),
        "queueKey": assignment.get("queueKey"),
        "workProductKind": message_kind,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return semantic_relation_record(
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
            "metadata": metadata,
        }
    )


def create_tavily_task_message_records(
    *,
    assignment: dict[str, Any],
    task_payload: dict[str, Any],
    actor_label: str,
    now: str,
) -> list[dict[str, Any]]:
    request_id = str(task_payload.get("request_id") or task_payload.get("requestId") or "")
    message_id = normalize_string(task_payload.get("messageId")) or (
        f"message-tavily-research-task-{hash_short([assignment['id'], request_id])}"
    )
    input_text = str(task_payload.get("input") or "")
    model = str(task_payload.get("model") or DEFAULT_TAVILY_MODEL)
    status = str(task_payload.get("status") or "pending")
    message = message_record(
        {
            "id": message_id,
            "messageKind": TAVILY_TASK_MESSAGE_KIND,
            "messageDomain": "assignment_work",
            "status": "active",
            "summary": f"Tavily deep research ({status})",
            "body": input_text,
            "metadata": {
                "kind": "research.tavily.task.created",
                "assignmentId": assignment["id"],
                "assignmentTypeKey": assignment.get("assignmentTypeKey"),
                "queueKey": assignment.get("queueKey"),
                "tavilyRequestId": request_id,
                "tavilyStatus": status,
                "tavilyModel": model,
                "tavilyInput": input_text,
                "researchBackend": "tavily_deep",
            },
            "source": "assignments run-tavily-deep-research",
            "importRunId": assignment.get("importRunId"),
            "authorLabel": actor_label,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    return [
        message,
        _produces_assignment_message_relation(
            assignment=assignment,
            message_id=message["expected"]["id"],
            now=now,
            lifecycle="assignment-tavily-research-task",
            message_kind=TAVILY_TASK_MESSAGE_KIND,
            metadata_kind="research.tavily.task.created",
        ),
    ]


def create_tavily_error_message_records(
    *,
    assignment: dict[str, Any],
    request_id: str,
    error: str,
    task_message_id: str,
    actor_label: str,
    now: str,
) -> list[dict[str, Any]]:
    message_id = f"message-tavily-research-error-{hash_short([assignment['id'], request_id, error])}"
    message = message_record(
        {
            "id": message_id,
            "messageKind": TAVILY_ERROR_MESSAGE_KIND,
            "messageDomain": "assignment_work",
            "status": "active",
            "summary": "Tavily deep research failed",
            "body": error,
            "metadata": {
                "kind": "research.tavily.task.failed",
                "assignmentId": assignment["id"],
                "tavilyRequestId": request_id,
                "taskMessageId": task_message_id,
                "researchBackend": "tavily_deep",
            },
            "source": "assignments run-tavily-deep-research",
            "importRunId": assignment.get("importRunId"),
            "authorLabel": actor_label,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    records = [
        message,
        _produces_assignment_message_relation(
            assignment=assignment,
            message_id=message_id,
            now=now,
            lifecycle="assignment-tavily-research-error",
            message_kind=TAVILY_ERROR_MESSAGE_KIND,
            metadata_kind="research.tavily.task.failed",
        ),
        semantic_relation_record(
            {
                "predicate": "derived_from",
                "subjectKind": "message",
                "subjectId": message_id,
                "subjectLineageId": message_id,
                "objectKind": "message",
                "objectId": task_message_id,
                "objectLineageId": task_message_id,
                "rank": 1,
                "confidence": 1,
                "reviewRecommended": False,
                "importRunId": assignment.get("importRunId"),
                "importedAt": now,
                "metadata": {
                    "lifecycle": "assignment-tavily-research-error",
                    "sourceKind": "tavily_research_task",
                },
            }
        ),
    ]
    return records


def _tavily_completed_report_content(completed: dict[str, Any]) -> tuple[str, str]:
    content = completed.get("content")
    if content is None:
        for key in ("report", "output", "result"):
            candidate = completed.get(key)
            if candidate is not None:
                content = candidate
                break
    if isinstance(content, dict):
        report_markdown = json.dumps(content, indent=2, sort_keys=True)
        structured_summary = normalize_string(content.get("summary")) or ""
        return report_markdown, structured_summary
    report_markdown = str(content or "").strip()
    return report_markdown, ""


def _tavily_completed_report_markdown(completed: dict[str, Any]) -> tuple[str, str]:
    report_markdown, structured_summary = _tavily_completed_report_content(completed)
    lede = derive_insight_packet_lede(report_markdown=report_markdown, structured_summary=structured_summary)
    return report_markdown, lede


def build_research_packet_from_tavily_completed(
    *,
    assignment: dict[str, Any],
    assignment_meta: dict[str, Any],
    completed: dict[str, Any],
    research_mode: str,
) -> dict[str, Any]:
    sources = completed.get("sources") if isinstance(completed.get("sources"), list) else []
    input_text = str(completed.get("input") or "")
    report_markdown, structured_summary = _tavily_completed_report_content(completed)
    packet_lede = derive_insight_packet_lede(
        report_markdown=report_markdown,
        structured_summary=structured_summary,
    )
    forum_title = derive_insight_forum_title(
        report_markdown=report_markdown,
        assignment_title=str(assignment.get("title") or ""),
        research_question=input_text,
        structured_summary=structured_summary,
    )

    source_snapshots: list[dict[str, Any]] = []
    proposed_references: list[dict[str, Any]] = []
    for rank, row in enumerate(sources, start=1):
        if not isinstance(row, dict):
            continue
        url = normalize_proposal_url(row.get("url"))
        if not url:
            continue
        title = normalize_string(row.get("title")) or url
        parsed = urlparse(url)
        snapshot = {
            "rank": rank,
            "url": url,
            "title": title,
            "source_domain": (parsed.netloc or "").lower(),
            "evidence_candidate_id": f"evidence-candidate-{hash_short([input_text, url, rank])}",
            "discovery_backend": "tavily_research",
        }
        source_snapshots.append(snapshot)
        proposed_references.append({**snapshot, "ingestion_rationale": f"Tavily deep research source #{rank}: {title}"})

    return {
        "research_mode": research_mode,
        "summary": packet_lede,
        "recommended_angle": normalize_string(assignment_meta.get("recommendedAngle")) or packet_lede[:200],
        "source_snapshots": source_snapshots,
        "proposed_references": proposed_references,
        "evidence_item_ids": [],
        "researchTrace": {
            "webSearches": [input_text] if input_text else [],
            "discoveryBoundary": {
                "webSearchPath": "tavily.research",
                "searchResultCount": len(source_snapshots),
                "searchMetadataShapeOk": True,
                "discoveryAttemptsTotal": 1,
                "discoveryQueriesTried": [input_text] if input_text else [],
                "discoveryResultCounts": [len(source_snapshots)],
                "discoveryTerminalState": "succeeded" if source_snapshots else "exhausted",
                "tavilyRequestId": completed.get("request_id") or completed.get("requestId"),
            },
        },
        "synthesis": {
            "summary": packet_lede,
            "recommendedAngle": normalize_string(assignment_meta.get("recommendedAngle")) or "",
        },
        "_report_markdown": report_markdown,
        "_forum_title": forum_title,
        "_tavily_request_id": completed.get("request_id") or completed.get("requestId"),
    }


def create_assignment_insight_records(
    *,
    assignment: dict[str, Any],
    summary: str,
    body: str,
    forum_title: str | None = None,
    research_question: str = "",
    tavily_model: str = "",
    source_count: int = 0,
    task_message_id: str,
    research_packet_message_id: str,
    tavily_request_id: str,
    reference_ids: list[str],
    actor_label: str,
    now: str,
) -> list[dict[str, Any]]:
    title = normalize_string(forum_title) or normalize_string(summary) or "Tavily deep research insight"
    message_id = f"message-assignment-insight-{hash_short([assignment['id'], tavily_request_id, title])}"
    message = message_record(
        {
            "id": message_id,
            "messageKind": "insight",
            "messageDomain": "assignment_work",
            "status": "active",
            "summary": title[:500],
            "body": body,
            "threadId": message_id,
            "sequenceNumber": 1,
            "metadata": {
                "kind": "research.tavily.insight",
                "insightTitle": title,
                "assignmentId": assignment["id"],
                "assignmentTypeKey": assignment.get("assignmentTypeKey"),
                "queueKey": assignment.get("queueKey"),
                "tavilyRequestId": tavily_request_id,
                "tavilyInput": normalize_string(research_question) or None,
                "tavilyModel": normalize_string(tavily_model) or None,
                "tavilySourceCount": source_count or None,
                "taskMessageId": task_message_id,
                "researchPacketMessageId": research_packet_message_id,
                "researchBackend": "tavily_deep",
            },
            "source": "assignments run-tavily-deep-research",
            "importRunId": assignment.get("importRunId"),
            "authorLabel": actor_label,
            "createdAt": now,
            "updatedAt": now,
        }
    )
    records: list[dict[str, Any]] = [
        message,
        _produces_assignment_message_relation(
            assignment=assignment,
            message_id=message_id,
            now=now,
            lifecycle="assignment-tavily-insight",
            message_kind="insight",
            metadata_kind="research.tavily.insight",
        ),
        semantic_relation_record(
            {
                "predicate": "derived_from",
                "subjectKind": "message",
                "subjectId": message_id,
                "subjectLineageId": message_id,
                "objectKind": "message",
                "objectId": task_message_id,
                "objectLineageId": task_message_id,
                "rank": 1,
                "confidence": 1,
                "reviewRecommended": False,
                "importRunId": assignment.get("importRunId"),
                "importedAt": now,
                "metadata": {"lifecycle": "assignment-tavily-insight", "sourceKind": "tavily_research_task"},
            }
        ),
        semantic_relation_record(
            {
                "predicate": "derived_from",
                "subjectKind": "message",
                "subjectId": message_id,
                "subjectLineageId": message_id,
                "objectKind": "message",
                "objectId": research_packet_message_id,
                "objectLineageId": research_packet_message_id,
                "rank": 2,
                "confidence": 1,
                "reviewRecommended": False,
                "importRunId": assignment.get("importRunId"),
                "importedAt": now,
                "metadata": {"lifecycle": "assignment-tavily-insight", "sourceKind": "research_packet"},
            }
        ),
    ]
    for rank, reference_id in enumerate(reference_ids, start=1):
        if not reference_id:
            continue
        records.append(
            semantic_relation_record(
                {
                    "predicate": "insight_about",
                    "subjectKind": "message",
                    "subjectId": message_id,
                    "subjectLineageId": message_id,
                    "objectKind": "reference",
                    "objectId": reference_id,
                    "objectLineageId": reference_id,
                    "rank": rank,
                    "confidence": 1,
                    "reviewRecommended": False,
                    "importRunId": assignment.get("importRunId"),
                    "importedAt": now,
                    "metadata": {
                        "kind": "research.tavily.insight",
                        "lifecycle": "assignment-tavily-insight",
                        "tavilyRequestId": tavily_request_id,
                    },
                }
            )
        )
    return records


def finalize_tavily_deep_research(
    client: PapyrusGraphQLAuthoringClient,
    *,
    assignment: dict[str, Any],
    assignment_meta: dict[str, Any],
    completed: dict[str, Any],
    task_message_id: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    research_mode = normalize_research_mode(
        options.get("research-mode") or assignment_meta.get("researchMode") or "source_discovery"
    )
    corpus_key = normalize_string(options.get("corpus-key")) or normalize_string(assignment_meta.get("corpusKey")) or "AI-ML-research"
    actor_label = normalize_string(options.get("actor-label")) or "Papyrus content CLI"
    assignment_id = str(assignment["id"])
    now = _utc_now()

    raw_packet = build_research_packet_from_tavily_completed(
        assignment=assignment,
        assignment_meta=assignment_meta,
        completed=completed,
        research_mode=research_mode,
    )
    report_markdown = str(raw_packet.pop("_report_markdown", "") or "")
    forum_title = normalize_string(raw_packet.pop("_forum_title", "")) or ""
    tavily_request_id = str(raw_packet.pop("_tavily_request_id", "") or "")

    apply_research_packet(
        client,
        {
            "assignment": assignment_id,
            "research-json": json.dumps(raw_packet),
            "research-mode": research_mode,
        },
    )

    intake_result: dict[str, Any] | None = None
    reference_ids: list[str] = []
    if parse_boolean_option(options.get("intake-proposals"), True, "--intake-proposals"):
        steering_config = normalize_string(options.get("config")) or "corpora/papyrus-steering.yml"
        intake_result = intake_research_packet_proposals(
            client,
            {
                "assignment": assignment_id,
                "config": steering_config,
                "corpus-key": corpus_key,
                "status": options.get("status") or "pending",
                "url-text": options.get("url-text", "false"),
                "metadata-from-text": options.get("metadata-from-text", "false"),
                "actor-label": actor_label,
            },
        )
        for row in intake_result.get("references") or []:
            if isinstance(row, dict) and row.get("referenceId"):
                reference_ids.append(str(row["referenceId"]))

    packet_entries = load_assignment_research_packet_entries(client, assignment_id)
    research_packet_message_id = packet_entries[0]["message"]["id"] if packet_entries else ""

    research_question = str(completed.get("input") or "").strip() or tavily_research_input_for_assignment(
        assignment,
        assignment_meta,
    )
    tavily_model = (
        normalize_string(completed.get("model"))
        or normalize_string(assignment_meta.get("tavilyModel"))
        or ""
    )
    source_count = len(raw_packet.get("source_snapshots") or [])
    if not forum_title:
        forum_title = derive_insight_forum_title(
            report_markdown=report_markdown,
            assignment_title=str(assignment.get("title") or ""),
            research_question=research_question,
            structured_summary=str(raw_packet.get("summary") or ""),
        )
    insight_body = format_tavily_insight_message_body(
        report_markdown=report_markdown,
        research_question=research_question,
        assignment_title=str(assignment.get("title") or ""),
        tavily_request_id=tavily_request_id,
        tavily_model=tavily_model,
        tavily_status=str(completed.get("status") or "completed"),
        source_count=source_count,
        task_message_id=task_message_id,
    )
    insight_records = create_assignment_insight_records(
        assignment=assignment,
        summary=forum_title,
        body=insight_body,
        forum_title=forum_title,
        research_question=research_question,
        tavily_model=tavily_model,
        source_count=source_count,
        task_message_id=task_message_id,
        research_packet_message_id=research_packet_message_id,
        tavily_request_id=tavily_request_id,
        reference_ids=reference_ids,
        actor_label=actor_label,
        now=now,
    )
    event = _assignment_event_record(
        assignment=assignment,
        event_type="research.tavily.completed",
        note=f"Tavily deep research completed ({tavily_request_id}).",
        actor_label=actor_label,
        now=now,
    )
    changes = build_record_changes(client, [*insight_records, event])
    apply_record_changes(client, changes)
    update_newsroom_summary_after_research_packet_creates(
        client,
        changes,
        actor_label=actor_label,
        reason=f"assignments run-tavily-deep-research finalize {assignment_id}",
    )

    return {
        "assignmentId": assignment_id,
        "tavilyRequestId": tavily_request_id,
        "taskMessageId": task_message_id,
        "researchPacketMessageId": research_packet_message_id,
        "insightMessageId": insight_records[0]["expected"]["id"],
        "registeredReferenceCount": (intake_result or {}).get("registeredReferenceCount", 0),
        "intake": intake_result,
    }


def start_tavily_deep_research(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> dict[str, Any]:
    apply = resolve_mutation_apply(options, "assignments run-tavily-deep-research")
    assignment_id = normalize_string(options.get("assignment"))
    if not assignment_id:
        raise ValueError("assignments run-tavily-deep-research requires --assignment <id>.")
    assignment = client.get_record("Assignment", assignment_id)
    if not assignment:
        raise ValueError(f"Assignment not found: {assignment_id}.")
    assignment_meta = assignment_metadata(client, assignment)
    if not is_tavily_deep_assignment(assignment, assignment_meta):
        raise ValueError(
            f"Assignment {assignment_id} is not {TAVILY_DEEP_ASSIGNMENT_TYPE}. "
            f"Create one with: poetry run papyrus assignments create-research --type {TAVILY_DEEP_ASSIGNMENT_TYPE} ..."
        )

    actor_label = normalize_string(options.get("actor-label")) or "Papyrus content CLI"
    now = _utc_now()
    existing = load_tavily_task_message(client, assignment_id)
    if existing:
        metadata = existing.get("_metadata") or {}
        request_id = normalize_string(metadata.get("tavilyRequestId"))
        status = normalize_string(metadata.get("tavilyStatus")) or "pending"
        if request_id and status not in {"completed", "failed"}:
            if parse_boolean_option(options.get("wait"), False, "--wait"):
                return poll_tavily_deep_research(
                    client,
                    {**options, "request-id": request_id, "task-message-id": existing["id"]},
                )
            return {
                "action": "existing",
                "assignmentId": assignment_id,
                "tavilyRequestId": request_id,
                "taskMessageId": existing["id"],
                "tavilyStatus": status,
                "next": f"poetry run papyrus assignments poll-tavily-deep-research --assignment {assignment_id}",
            }

    input_text = tavily_research_input_for_assignment(
        assignment,
        assignment_meta,
        override=normalize_string(options.get("input") or options.get("research-questions")),
    )
    model = normalize_string(options.get("tavily-model")) or normalize_string(assignment_meta.get("tavilyModel")) or DEFAULT_TAVILY_MODEL
    output_length = normalize_string(options.get("tavily-output-length")) or "standard"
    include_domains = parse_comma_list(options.get("tavily-include-domains"))
    exclude_domains = parse_comma_list(options.get("tavily-exclude-domains"))

    if not apply:
        return {
            "action": "dry-run",
            "assignmentId": assignment_id,
            "input": input_text,
            "tavilyModel": model,
            "tavilyOutputLength": output_length,
        }

    task_payload = tavily_research.create_tavily_research_task(
        input_text=input_text,
        model=model,
        output_length=output_length,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
    )
    records = create_tavily_task_message_records(
        assignment=assignment,
        task_payload=task_payload,
        actor_label=actor_label,
        now=now,
    )
    event = _assignment_event_record(
        assignment=assignment,
        event_type="research.tavily.started",
        note=f"Tavily deep research started ({task_payload.get('request_id')}).",
        actor_label=actor_label,
        now=now,
    )
    changes = build_record_changes(client, [*records, event])
    apply_record_changes(client, changes)
    update_newsroom_summary_after_research_packet_creates(
        client,
        changes,
        actor_label=actor_label,
        reason=f"assignments run-tavily-deep-research start {assignment_id}",
    )

    request_id = str(task_payload.get("request_id") or "")
    task_message_id = records[0]["expected"]["id"]
    result = {
        "action": "started",
        "assignmentId": assignment_id,
        "tavilyRequestId": request_id,
        "taskMessageId": task_message_id,
        "tavilyStatus": task_payload.get("status") or "pending",
    }
    if parse_boolean_option(options.get("wait"), False, "--wait"):
        return poll_tavily_deep_research(
            client,
            {**options, "request-id": request_id, "task-message-id": task_message_id},
        )
    result["next"] = f"poetry run papyrus assignments poll-tavily-deep-research --assignment {assignment_id}"
    return result


def poll_tavily_deep_research(client: PapyrusGraphQLAuthoringClient, options: dict[str, Any]) -> dict[str, Any]:
    apply = resolve_mutation_apply(options, "assignments poll-tavily-deep-research")
    assignment_id = normalize_string(options.get("assignment"))
    if not assignment_id:
        raise ValueError("assignments poll-tavily-deep-research requires --assignment <id>.")
    assignment = client.get_record("Assignment", assignment_id)
    if not assignment:
        raise ValueError(f"Assignment not found: {assignment_id}.")
    assignment_meta = assignment_metadata(client, assignment)
    if not is_tavily_deep_assignment(assignment, assignment_meta):
        raise ValueError(f"Assignment {assignment_id} is not {TAVILY_DEEP_ASSIGNMENT_TYPE}.")

    task_message = load_tavily_task_message(client, assignment_id)
    if not task_message:
        raise ValueError(f"No Tavily task message is linked to assignment {assignment_id}.")
    metadata = task_message.get("_metadata") or {}
    request_id = normalize_string(options.get("request-id")) or normalize_string(metadata.get("tavilyRequestId"))
    if not request_id:
        raise ValueError(f"Tavily task message {task_message['id']} is missing tavilyRequestId metadata.")
    task_message_id = normalize_string(options.get("task-message-id")) or str(task_message["id"])

    max_wait = normalize_non_negative_integer(options.get("max-wait-seconds"), "--max-wait-seconds") or 1800
    actor_label = normalize_string(options.get("actor-label")) or "Papyrus content CLI"

    if not apply:
        return {
            "action": "dry-run",
            "assignmentId": assignment_id,
            "tavilyRequestId": request_id,
            "taskMessageId": task_message_id,
        }

    try:
        completed = tavily_research.poll_tavily_research_task(request_id, max_wait_seconds=max_wait)
    except TavilyResearchTimeout as error:
        event = _assignment_event_record(
            assignment=assignment,
            event_type="research.tavily.timeout",
            note=str(error),
            actor_label=actor_label,
            now=_utc_now(),
        )
        apply_record_changes(client, build_record_changes(client, [event]))
        raise
    except TavilyResearchFailed as error:
        now = _utc_now()
        error_records = create_tavily_error_message_records(
            assignment=assignment,
            request_id=request_id,
            error=str(error),
            task_message_id=task_message_id,
            actor_label=actor_label,
            now=now,
        )
        event = _assignment_event_record(
            assignment=assignment,
            event_type="research.tavily.failed",
            note=str(error),
            actor_label=actor_label,
            now=now,
        )
        apply_record_changes(client, build_record_changes(client, [*error_records, event]))
        return {
            "action": "failed",
            "assignmentId": assignment_id,
            "tavilyRequestId": request_id,
            "error": str(error),
        }

    finalize = finalize_tavily_deep_research(
        client,
        assignment=assignment,
        assignment_meta=assignment_meta,
        completed=completed,
        task_message_id=task_message_id,
        options=options,
    )
    return {"action": "completed", **finalize}


def run_tavily_deep_research(flags: list[str]) -> None:
    from .graphql_authoring import create_authoring_client

    options = parse_options(flags)
    client, _ = create_authoring_client()
    result = start_tavily_deep_research(client, options)
    if options.get("json"):
        import json as json_module

        print(json_module.dumps({"ok": True, **result}, indent=2))
        return
    print(f"assignments\ttavily-deep\taction\t{result.get('action')}")
    print(f"assignments\ttavily-deep\tassignment\t{result.get('assignmentId')}")
    if result.get("tavilyRequestId"):
        print(f"assignments\ttavily-deep\ttavily-request-id\t{result.get('tavilyRequestId')}")
    if result.get("next"):
        print(f"assignments\ttavily-deep\tnext\t{result.get('next')}")


def poll_tavily_deep_research_command(flags: list[str]) -> None:
    from .graphql_authoring import create_authoring_client

    options = parse_options(flags)
    client, _ = create_authoring_client()
    result = poll_tavily_deep_research(client, options)
    if options.get("json"):
        import json as json_module

        print(json_module.dumps({"ok": True, **result}, indent=2))
        return
    print(f"assignments\ttavily-deep\taction\t{result.get('action')}")
    print(f"assignments\ttavily-deep\tassignment\t{result.get('assignmentId')}")
    if result.get("tavilyRequestId"):
        print(f"assignments\ttavily-deep\ttavily-request-id\t{result.get('tavilyRequestId')}")
    if result.get("insightMessageId"):
        print(f"assignments\ttavily-deep\tinsight\t{result.get('insightMessageId')}")
