from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .catalog import semantic_relation_record
from .content_item_lifecycle import require_assignment_content_item_lineage_id
from .ids import hash_short, hash_stable, safe_id
from .model_attachments import attachment_record, build_json_model_payload_attachment
from .reporting_packet_review import REPORTING_PACKET_KIND

COPYWRITING_ARTICLE_ASSIGNMENT_TYPE = "copywriting.article-draft"
COPYWRITING_BRIEF_ASSIGNMENT_TYPE = "copywriting.brief-draft"
COPYWRITING_ASSIGNMENT_TYPES = frozenset(
    {COPYWRITING_ARTICLE_ASSIGNMENT_TYPE, COPYWRITING_BRIEF_ASSIGNMENT_TYPE}
)


def build_copywriting_run_plan(
    *,
    assignment: dict[str, Any],
    assignment_metadata: dict[str, Any] | None = None,
    reporting_packet_message: dict[str, Any],
    reporting_packet_payload: dict[str, Any] | None = None,
    existing_items: list[dict[str, Any]] | None = None,
    actor_label: str = "papyrus-cli",
    actor_sub: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or _utc_now()
    if not assignment.get("id"):
        raise ValueError("Copywriting requires an Assignment record.")
    if assignment.get("assignmentTypeKey") not in COPYWRITING_ASSIGNMENT_TYPES:
        raise ValueError(
            f"Assignment {assignment['id']} must be copywriting.article-draft or copywriting.brief-draft."
        )
    metadata = assignment_metadata or _assignment_metadata(assignment)
    if not reporting_packet_message.get("id"):
        raise ValueError("Copywriting requires a linked reporting packet Message.")
    if reporting_packet_message.get("messageKind") != REPORTING_PACKET_KIND:
        raise ValueError(f"Message {reporting_packet_message['id']} must be {REPORTING_PACKET_KIND}.")
    packet = _normalize_reporting_packet(reporting_packet_payload or reporting_packet_message.get("metadata"))
    target_item_type = _normalize_target_item_type(metadata.get("targetItemType")) or (
        "brief" if assignment.get("assignmentTypeKey") == COPYWRITING_BRIEF_ASSIGNMENT_TYPE else "article"
    )
    item_version = _draft_item_for_copywriting(
        assignment=assignment,
        metadata=metadata,
        packet=packet,
        target_item_type=target_item_type,
        existing_items=existing_items or [],
        actor_label=actor_label,
        now=now,
    )
    private_editorial_metadata = _private_editorial_metadata_for_copywriting(
        assignment=assignment,
        metadata=metadata,
        packet=packet,
        reporting_packet_message=reporting_packet_message,
    )
    event = _assignment_event_for_copywriting(
        assignment=assignment,
        event_type="copywriting_drafted",
        note=f"Created draft {target_item_type} Item {item_version['id']} from selected reporting packet.",
        now=now,
        actor_label=actor_label,
        actor_sub=actor_sub,
    )
    event_metadata = {
        "kind": "copywriting.draft_created",
        "source": "content-cli",
        "assignmentId": assignment["id"],
        "assignmentTypeKey": assignment["assignmentTypeKey"],
        "sourceReportingAssignmentId": metadata.get("sourceReportingAssignmentId"),
        "sourceReportingPacketMessageId": reporting_packet_message["id"],
        "targetItemType": target_item_type,
        "draftItemId": item_version["id"],
        "draftItemLineageId": item_version["lineageId"],
        "versionNumber": item_version["versionNumber"],
        "previousVersionId": item_version.get("previousVersionId"),
        "createsEditionItem": False,
        "privateEditorialMetadata": private_editorial_metadata,
    }
    metadata_attachment = attachment_record(
        build_json_model_payload_attachment(
            {
                "ownerKind": "assignmentEvent",
                "ownerId": event["id"],
                "ownerLineageId": event["id"],
                "role": "metadata",
                "sortKey": "metadata",
                "filename": "metadata.json",
                "content": event_metadata,
                "now": now,
            }
        )
    )
    produces_relation = semantic_relation_record(
        {
            "predicate": "produces",
            "subjectKind": "assignment",
            "subjectId": assignment["id"],
            "subjectLineageId": assignment["id"],
            "objectKind": "item",
            "objectId": item_version["id"],
            "objectLineageId": item_version["lineageId"],
            "objectVersionNumber": item_version["versionNumber"],
            "rank": item_version["versionNumber"],
            "classifierId": assignment.get("classifierId"),
            "importedAt": now,
            "metadata": {
                "lifecycle": "copywriting",
                "workProductKind": "draft_item",
                "assignmentId": assignment["id"],
                "sourceReportingAssignmentId": metadata.get("sourceReportingAssignmentId"),
                "sourceReportingPacketMessageId": reporting_packet_message["id"],
                "targetItemType": target_item_type,
                "draftItemId": item_version["id"],
                "draftItemLineageId": item_version["lineageId"],
                "versionNumber": item_version["versionNumber"],
                "createsEditionItem": False,
                "privateEditorialMetadata": private_editorial_metadata,
            },
        }
    )
    records = [
        {"modelName": "Item", "expected": item_version},
        produces_relation,
        {"modelName": "AssignmentEvent", "expected": event},
        metadata_attachment,
    ]
    return {
        "dryRun": True,
        "lifecycle": "copywriting",
        "assignmentId": assignment["id"],
        "sourceReportingPacketMessageId": reporting_packet_message["id"],
        "targetItemType": target_item_type,
        "draftItem": item_version,
        "event": event,
        "metadata": event_metadata,
        "metadataAttachment": metadata_attachment,
        "records": records,
        "summary": {
            "assignmentId": assignment["id"],
            "sourceReportingAssignmentId": metadata.get("sourceReportingAssignmentId"),
            "sourceReportingPacketMessageId": reporting_packet_message["id"],
            "targetItemType": target_item_type,
            "draftItemId": item_version["id"],
            "draftItemLineageId": item_version["lineageId"],
            "versionNumber": item_version["versionNumber"],
            "previousVersionId": item_version.get("previousVersionId"),
            "createsDraftItem": True,
            "createsEditionItem": False,
            "recordCount": len(records),
        },
    }


def _draft_item_for_copywriting(
    *,
    assignment: dict[str, Any],
    metadata: dict[str, Any],
    packet: dict[str, Any],
    target_item_type: str,
    existing_items: list[dict[str, Any]],
    actor_label: str,
    now: str,
) -> dict[str, Any]:
    lineage_id = require_assignment_content_item_lineage_id(assignment)
    versions = sorted(
        [item for item in existing_items if item.get("lineageId") == lineage_id],
        key=lambda item: int(item.get("versionNumber") or 0),
        reverse=True,
    )
    previous = versions[0] if versions else None
    version_number = int(previous.get("versionNumber") or 0) + 1 if previous else 1
    record_id = f"{lineage_id}-v{version_number}"
    section = (
        _clean_string(metadata.get("sectionKey"))
        or assignment.get("sectionKey")
        or assignment.get("sectionId")
        or packet.get("sectionKey")
        or "unsectioned"
    )
    headline = (
        _clean_string(packet.get("recommendedAngle"))
        or _clean_string(packet.get("nutGrafCandidate"))
        or _clean_string(assignment.get("title"))
        or f"{_title_case(target_item_type)} draft"
    )
    title = f"Brief: {headline}" if target_item_type == "brief" else headline
    deck = (
        _clean_string(packet.get("summary"))
        or _clean_string(packet.get("whyNow"))
        or _clean_string(assignment.get("summary"))
        or "Draft created from a selected private reporting packet."
    )
    body = _reader_facing_body(packet=packet, assignment=assignment, target_item_type=target_item_type)
    edition_date = (
        _clean_string(metadata.get("editionDate") or metadata.get("storyCycleDate"))
        or _clean_string(packet.get("editionDate"))
        or _date_from_id(metadata.get("editionId") or packet.get("editionId"))
    )
    record = {
        "id": record_id,
        "lineageId": lineage_id,
        "versionNumber": version_number,
        "previousVersionId": previous.get("id") if previous else None,
        "versionState": "draft",
        "versionCreatedAt": now,
        "versionCreatedBy": actor_label,
        "changeReason": "copywriting-assignment-run",
        "contentHash": "",
        "type": target_item_type,
        "status": "draft",
        "typeStatus": f"{target_item_type}#draft",
        "stage": "copywriting",
        "slug": f"draft-{safe_id(section)}-{hash_short([lineage_id, version_number, title])}",
        "shortSlug": None,
        "section": section,
        "sectionStatus": f"{section}#draft",
        "title": title,
        "headline": headline,
        "deck": deck,
        "body": body,
        "byline": None,
        "dateline": None,
        "editionDate": edition_date,
        "sortTitle": title,
        "pullQuotes": [],
        "layout": None,
        "updatedAt": now,
    }
    record["contentHash"] = hash_stable(
        {
            "type": record["type"],
            "status": record["status"],
            "slug": record["slug"],
            "section": record["section"],
            "title": record["title"],
            "headline": record["headline"],
            "deck": record["deck"],
            "body": record["body"],
        }
    )
    return record


def _private_editorial_metadata_for_copywriting(
    *,
    assignment: dict[str, Any],
    metadata: dict[str, Any],
    packet: dict[str, Any],
    reporting_packet_message: dict[str, Any],
) -> dict[str, Any]:
    return {
        "createdFrom": "copywriting_assignment",
        "copywritingAssignmentId": assignment["id"],
        "sourceReportingAssignmentId": metadata.get("sourceReportingAssignmentId"),
        "reportingPacketMessageId": reporting_packet_message.get("id")
        or metadata.get("sourceReportingPacketMessageId")
        or packet.get("messageId"),
        "privateSource": True,
        "acceptedReferenceIds": metadata.get("acceptedReferenceIds") or packet.get("acceptedReferenceIds") or [],
        "proposedReferences": metadata.get("proposedReferences") or packet.get("proposedReferences") or [],
        "unresolvedProposedReferencesStayPrivate": True,
        "storyCycleRunId": metadata.get("storyCycleRunId")
        or metadata.get("coverageThemeRunId")
        or metadata.get("runId")
        or packet.get("storyCycleRunId")
        or assignment.get("importRunId"),
        "coverageConceptKey": metadata.get("coverageConceptKey")
        or metadata.get("coverageKey")
        or packet.get("coverageConceptKey")
        or packet.get("coverageKey"),
    }


def _reader_facing_body(*, packet: dict[str, Any], assignment: dict[str, Any], target_item_type: str) -> str:
    paragraphs: list[str] = []
    nut_graf = _clean_string(packet.get("nutGrafCandidate")) or _clean_string(packet.get("summary"))
    if nut_graf:
        paragraphs.append(nut_graf)
    for fact in [
        _clean_string(entry)
        for entry in (packet.get("confirmedFacts") or [])
        if _clean_string(entry)
    ][: 2 if target_item_type == "brief" else 5]:
        paragraphs.append(fact)
    why_now = _clean_string(packet.get("whyNow"))
    angle = _clean_string(packet.get("recommendedAngle"))
    if why_now and why_now != nut_graf:
        paragraphs.append(why_now)
    if angle and not any(angle in paragraph for paragraph in paragraphs):
        paragraphs.append(f"The working angle is {angle}.")
    if not paragraphs:
        paragraphs.append(
            _clean_string(assignment.get("brief"))
            or _clean_string(assignment.get("summary"))
            or "This draft is based on a selected private reporting packet and needs editor review before publication."
        )
    return "\n\n".join(paragraphs)


def _assignment_event_for_copywriting(
    *,
    assignment: dict[str, Any],
    event_type: str,
    note: str,
    now: str,
    actor_label: str,
    actor_sub: str | None,
) -> dict[str, Any]:
    return {
        "id": f"assignment-event-{safe_id(assignment['id'])}-{safe_id(event_type)}-{_timestamp_id(now)}",
        "assignmentId": assignment["id"],
        "assignmentTypeKey": assignment["assignmentTypeKey"],
        "queueKey": assignment["queueKey"],
        "eventType": event_type,
        "fromStatus": assignment.get("status"),
        "toStatus": assignment.get("status"),
        "actorSub": actor_sub,
        "actorLabel": actor_label,
        "note": _clean_string(note),
        "createdAt": now,
    }


def _normalize_reporting_packet(payload: Any) -> dict[str, Any]:
    parsed = _object_value(payload) or {}
    reporting = _object_value(parsed.get("reporting")) or parsed
    return {
        "messageId": _clean_string(parsed.get("messageId")),
        "summary": _clean_string(reporting.get("summary")),
        "sectionKey": _clean_string(reporting.get("sectionKey") or reporting.get("section_key")),
        "editionId": _clean_string(reporting.get("editionId") or reporting.get("edition_id")),
        "editionDate": _clean_string(reporting.get("editionDate") or reporting.get("edition_date")),
        "storyCycleRunId": _clean_string(
            reporting.get("storyCycleRunId")
            or reporting.get("story_cycle_run_id")
            or reporting.get("coverageThemeRunId")
            or reporting.get("coverage_theme_run_id")
        ),
        "coverageConceptKey": _clean_string(
            reporting.get("coverageConceptKey")
            or reporting.get("coverage_concept_key")
            or reporting.get("coverageKey")
            or reporting.get("coverage_key")
        ),
        "whyNow": _clean_string(reporting.get("whyNow") or reporting.get("why_now")),
        "nutGrafCandidate": _clean_string(reporting.get("nutGrafCandidate") or reporting.get("nut_graf_candidate")),
        "recommendedAngle": _clean_string(reporting.get("recommendedAngle") or reporting.get("recommended_angle")),
        "confirmedFacts": reporting.get("confirmedFacts") or reporting.get("confirmed_facts") or [],
        "acceptedReferenceIds": reporting.get("acceptedReferenceIds") or reporting.get("accepted_reference_ids") or [],
        "proposedReferences": reporting.get("proposedReferences") or reporting.get("proposed_references") or [],
        "copywriterBrief": _clean_string(reporting.get("copywriterBrief") or reporting.get("copywriter_brief")),
    }


def _object_value(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _normalize_target_item_type(value: Any) -> str | None:
    normalized = _clean_string(value)
    return normalized if normalized in {"article", "brief"} else None


def _assignment_metadata(assignment: dict[str, Any]) -> dict[str, Any]:
    metadata = assignment.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _clean_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _title_case(value: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_\s]+", value) if part)


def _date_from_id(value: Any) -> str | None:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else None


def _timestamp_id(value: str) -> str:
    return re.sub(r"[^0-9TZ]", "", value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
