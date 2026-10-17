from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .catalog import semantic_relation_record
from .content_item_lifecycle import require_assignment_content_item_lineage_id
from .ids import hash_short, safe_id
from .model_attachments import attachment_record, build_json_model_payload_attachment
from .options import normalize_string

REPORTING_ASSIGNMENT_TYPE = "reporting.edition-candidate"
REPORTING_PACKET_KIND = "reporting_context_packet"
REPORTING_REVIEW_DECISIONS = frozenset({"select", "merge", "brief", "hold", "kill"})
COPYWRITING_ARTICLE_ASSIGNMENT_TYPE = "copywriting.article-draft"
COPYWRITING_BRIEF_ASSIGNMENT_TYPE = "copywriting.brief-draft"


def normalize_reporting_review_decision(value: Any) -> str:
    normalized = re.sub(r"^reporting_", "", str(value or "").strip().lower())
    if normalized not in REPORTING_REVIEW_DECISIONS:
        raise ValueError("Reporting packet review decision must be select, merge, brief, hold, or kill.")
    return normalized


def build_reporting_packet_review_plan(
    *,
    assignment: dict[str, Any],
    message: dict[str, Any],
    decision: str,
    note: str = "",
    target_item: dict[str, Any] | None = None,
    actor_label: str = "papyrus-cli",
    actor_sub: str | None = None,
    now: str | None = None,
    semantic_relations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = now or _utc_now()
    if not assignment.get("id"):
        raise ValueError("Reporting packet review requires an Assignment record.")
    if assignment.get("assignmentTypeKey") != REPORTING_ASSIGNMENT_TYPE:
        raise ValueError(f"Assignment {assignment['id']} must be {REPORTING_ASSIGNMENT_TYPE}.")
    if not message.get("id"):
        raise ValueError("Reporting packet review requires a Message record.")
    if message.get("messageKind") != REPORTING_PACKET_KIND:
        raise ValueError(f"Message {message['id']} must be {REPORTING_PACKET_KIND}.")
    if semantic_relations is not None and not _has_packet_assignment_link(
        semantic_relations, message["id"], assignment["id"]
    ):
        raise ValueError(
            f"Message {message['id']} is not linked to Assignment {assignment['id']} by a packet relation."
        )
    normalized_decision = normalize_reporting_review_decision(decision)
    if normalized_decision == "merge" and not target_item:
        raise ValueError("Reporting packet merge decisions require --target-item.")

    event_type = f"reporting_{normalized_decision}"
    copywriting_assignment = (
        _copywriting_assignment_for_reporting_packet(
            assignment=assignment,
            message=message,
            decision=normalized_decision,
            actor_label=actor_label,
            now=now,
        )
        if normalized_decision in {"select", "brief"}
        else None
    )
    copywriting_metadata_attachment = None
    if copywriting_assignment:
        copywriting_metadata = _assignment_metadata(copywriting_assignment)
        copywriting_metadata_attachment = attachment_record(
            build_json_model_payload_attachment(
                {
                    "ownerKind": "assignment",
                    "ownerId": copywriting_assignment["id"],
                    "ownerLineageId": copywriting_assignment["id"],
                    "role": "metadata",
                    "sortKey": "metadata",
                    "filename": "metadata.json",
                    "content": copywriting_metadata,
                    "now": now,
                }
            )
        )
    produced_item = target_item if normalized_decision == "merge" else None
    metadata = _reporting_review_metadata(
        assignment=assignment,
        message=message,
        decision=normalized_decision,
        copywriting_assignment=copywriting_assignment,
        target_item=target_item,
        semantic_relations=semantic_relations or [],
    )
    event = _assignment_event_for_reporting_review(
        assignment=assignment,
        event_type=event_type,
        note=note,
        now=now,
        actor_label=actor_label,
        actor_sub=actor_sub,
    )
    metadata_attachment = attachment_record(
        build_json_model_payload_attachment(
            {
                "ownerKind": "assignmentEvent",
                "ownerId": event["id"],
                "ownerLineageId": event["id"],
                "role": "metadata",
                "sortKey": "metadata",
                "filename": "metadata.json",
                "content": metadata,
                "now": now,
            }
        )
    )
    records: list[dict[str, Any]] = [
        {"modelName": "AssignmentEvent", "expected": event},
        metadata_attachment,
    ]
    slot_binding = _reporting_assignment_slot_binding(assignment=assignment, semantic_relations=semantic_relations or [])
    slot_update = _edition_slot_update_for_decision(
        slot_binding=slot_binding,
        decision=normalized_decision,
        assignment_id=assignment["id"],
        now=now,
    )
    if slot_update:
        records.append({"modelName": "EditionSlot", "expected": slot_update})
    slot_selection_relation = _slot_selection_relation(
        slot_binding=slot_binding,
        decision=normalized_decision,
        assignment=assignment,
        now=now,
    )
    if slot_selection_relation:
        records.append(slot_selection_relation)
    if copywriting_assignment:
        records.append({"modelName": "Assignment", "expected": copywriting_assignment})
        records.append(copywriting_metadata_attachment)
        records.extend(
            [
                semantic_relation_record(
                    {
                        "predicate": "derived_from",
                        "subjectKind": "assignment",
                        "subjectId": copywriting_assignment["id"],
                        "subjectLineageId": copywriting_assignment["id"],
                        "objectKind": "assignment",
                        "objectId": assignment["id"],
                        "objectLineageId": assignment["id"],
                        "rank": 1,
                        "classifierId": assignment.get("classifierId"),
                        "importedAt": now,
                        "metadata": {
                            "lifecycle": "reporting-packet-review",
                            "sourceKind": "reporting_assignment",
                            "decision": normalized_decision,
                            "reportingAssignmentId": assignment["id"],
                            "reportingPacketMessageId": message["id"],
                            "copywritingAssignmentId": copywriting_assignment["id"],
                        },
                    }
                ),
                semantic_relation_record(
                    {
                        "predicate": "derived_from",
                        "subjectKind": "assignment",
                        "subjectId": copywriting_assignment["id"],
                        "subjectLineageId": copywriting_assignment["id"],
                        "objectKind": "message",
                        "objectId": message["id"],
                        "objectLineageId": message["id"],
                        "rank": 2,
                        "classifierId": assignment.get("classifierId"),
                        "importedAt": now,
                        "metadata": {
                            "lifecycle": "reporting-packet-review",
                            "sourceKind": "reporting_context_packet",
                            "decision": normalized_decision,
                            "reportingAssignmentId": assignment["id"],
                            "reportingPacketMessageId": message["id"],
                            "copywritingAssignmentId": copywriting_assignment["id"],
                        },
                    }
                ),
            ]
        )
    if produced_item:
        records.append(
            semantic_relation_record(
                {
                    "predicate": "produces",
                    "subjectKind": "assignment",
                    "subjectId": assignment["id"],
                    "subjectLineageId": assignment["id"],
                    "objectKind": "item",
                    "objectId": produced_item["id"],
                    "objectLineageId": produced_item.get("lineageId") or produced_item["id"],
                    "objectVersionNumber": produced_item.get("versionNumber"),
                    "rank": 1,
                    "classifierId": assignment.get("classifierId"),
                    "importedAt": now,
                    "metadata": {
                        "lifecycle": "reporting-packet-review",
                        "decision": normalized_decision,
                        "assignmentId": assignment["id"],
                        "messageId": message["id"],
                        "copywritingAssignmentId": None,
                        "targetItemId": target_item.get("id") if target_item else None,
                    },
                }
            )
        )
    return {
        "dryRun": True,
        "lifecycle": "reporting-packet-review",
        "assignmentId": assignment["id"],
        "messageId": message["id"],
        "decision": normalized_decision,
        "event": event,
        "metadata": metadata,
        "metadataAttachment": metadata_attachment,
        "copywritingAssignment": copywriting_assignment,
        "copywritingAssignmentMetadataAttachment": copywriting_metadata_attachment,
        "targetItemId": target_item.get("id") if target_item else None,
        "slotId": slot_binding.get("slotId"),
        "slotRank": slot_binding.get("slotRank"),
        "slotStatus": slot_update.get("status") if slot_update else None,
        "records": records,
        "summary": {
            "assignmentId": assignment["id"],
            "messageId": message["id"],
            "decision": normalized_decision,
            "eventId": event["id"],
            "metadataAttachmentId": metadata_attachment["expected"]["id"],
            "copywritingAssignmentId": copywriting_assignment.get("id") if copywriting_assignment else None,
            "draftItemId": None,
            "targetItemId": target_item.get("id") if target_item else None,
            "slotId": slot_binding.get("slotId"),
            "slotRank": slot_binding.get("slotRank"),
            "slotStatus": slot_update.get("status") if slot_update else None,
            "createsCopywritingAssignment": bool(copywriting_assignment),
            "createsDraftItem": False,
            "createsEditionItem": False,
            "recordCount": len(records),
        },
    }


def _has_packet_assignment_link(relations: list[dict[str, Any]], message_id: str, assignment_id: str) -> bool:
    for relation in relations:
        if relation.get("relationState") == "superseded":
            continue
        relation_type = relation.get("relationTypeKey") or relation.get("predicate")
        if (
            relation.get("subjectKind") == "assignment"
            and relation.get("subjectId") == assignment_id
            and relation.get("objectKind") == "message"
            and relation.get("objectId") == message_id
            and relation_type == "produces"
        ):
            return True
        if (
            relation.get("subjectKind") == "message"
            and relation.get("subjectId") == message_id
            and relation.get("objectKind") == "assignment"
            and relation.get("objectId") == assignment_id
            and relation_type == "comment"
        ):
            return True
    return False


def _reporting_review_metadata(
    *,
    assignment: dict[str, Any],
    message: dict[str, Any],
    decision: str,
    copywriting_assignment: dict[str, Any] | None,
    target_item: dict[str, Any] | None,
    semantic_relations: list[dict[str, Any]],
) -> dict[str, Any]:
    slot_binding = _reporting_assignment_slot_binding(assignment=assignment, semantic_relations=semantic_relations)
    return {
        "kind": "reporting.packet_review",
        "source": "content-cli",
        "assignmentId": assignment["id"],
        "messageId": message["id"],
        "decision": decision,
        "targetItemId": target_item.get("id") if target_item else None,
        "copywritingAssignmentId": copywriting_assignment.get("id") if copywriting_assignment else None,
        "slotId": slot_binding.get("slotId"),
        "slotRank": slot_binding.get("slotRank"),
        "slotLineageId": slot_binding.get("slotLineageId"),
        "targetItemType": _copywriting_target_item_type(copywriting_assignment["assignmentTypeKey"])
        if copywriting_assignment
        else None,
        "createsCopywritingAssignment": bool(copywriting_assignment),
        "createsDraftItem": False,
        "privatePacketMessageKind": REPORTING_PACKET_KIND,
        "createsEditionItem": False,
    }


def _reporting_assignment_slot_binding(
    *,
    assignment: dict[str, Any],
    semantic_relations: list[dict[str, Any]],
) -> dict[str, Any]:
    assignment_meta = _assignment_metadata(assignment)
    slot_target = assignment_meta.get("slotTarget") if isinstance(assignment_meta.get("slotTarget"), dict) else {}
    relation = next(
        (
            row for row in semantic_relations
            if row.get("subjectKind") == "assignment"
            and row.get("subjectId") == assignment.get("id")
            and row.get("objectKind") == "editionSlot"
            and (row.get("relationTypeKey") or row.get("predicate")) == "targets_slot"
            and row.get("relationState") != "superseded"
        ),
        None,
    )
    relation_metadata = _assignment_metadata({"metadata": relation.get("metadata") if relation else {}})
    slot_id = (
        _clean_string(slot_target.get("slotId"))
        or _clean_string((relation or {}).get("objectId"))
        or _clean_string((relation or {}).get("objectLineageId"))
    )
    slot_lineage_id = (
        _clean_string(slot_target.get("slotLineageId"))
        or _clean_string((relation or {}).get("objectLineageId"))
        or slot_id
    )
    slot_rank = slot_target.get("slotRank") if slot_target.get("slotRank") is not None else relation_metadata.get("slotRank")
    return {
        "slotId": slot_id,
        "slotLineageId": slot_lineage_id,
        "slotRank": slot_rank,
        "sectionKey": _clean_string(slot_target.get("sectionKey")) or _clean_string(relation_metadata.get("sectionKey")) or assignment.get("sectionKey"),
    }


def _edition_slot_update_for_decision(
    *,
    slot_binding: dict[str, Any],
    decision: str,
    assignment_id: str,
    now: str,
) -> dict[str, Any] | None:
    slot_id = _clean_string(slot_binding.get("slotId"))
    if not slot_id:
        return None
    if decision == "select":
        return {"id": slot_id, "status": "selected", "selectedAssignmentId": assignment_id, "updatedAt": now}
    if decision == "brief":
        return {"id": slot_id, "status": "briefed", "selectedAssignmentId": assignment_id, "updatedAt": now}
    if decision in {"hold", "kill"}:
        return {"id": slot_id, "status": "open", "selectedAssignmentId": None, "updatedAt": now}
    return None


def _slot_selection_relation(
    *,
    slot_binding: dict[str, Any],
    decision: str,
    assignment: dict[str, Any],
    now: str,
) -> dict[str, Any] | None:
    slot_id = _clean_string(slot_binding.get("slotId"))
    if not slot_id or decision not in {"select", "brief"}:
        return None
    return semantic_relation_record(
        {
            "predicate": "selected_by",
            "subjectKind": "editionSlot",
            "subjectId": slot_id,
            "subjectLineageId": slot_binding.get("slotLineageId") or slot_id,
            "objectKind": "assignment",
            "objectId": assignment["id"],
            "objectLineageId": assignment["id"],
            "rank": 1,
            "classifierId": assignment.get("classifierId"),
            "importedAt": now,
            "metadata": {
                "lifecycle": "reporting-packet-review",
                "decision": decision,
                "slotId": slot_id,
                "slotRank": slot_binding.get("slotRank"),
                "sectionKey": slot_binding.get("sectionKey"),
            },
        }
    )


def _assignment_event_for_reporting_review(
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
        "note": normalize_string(note),
        "createdAt": now,
    }


def _copywriting_assignment_for_reporting_packet(
    *,
    assignment: dict[str, Any],
    message: dict[str, Any],
    decision: str,
    actor_label: str,
    now: str,
) -> dict[str, Any]:
    content_item_lineage_id = require_assignment_content_item_lineage_id(assignment)
    target_item_type = "brief" if decision == "brief" else "article"
    assignment_type_key = (
        COPYWRITING_BRIEF_ASSIGNMENT_TYPE if target_item_type == "brief" else COPYWRITING_ARTICLE_ASSIGNMENT_TYPE
    )
    section = assignment.get("sectionKey") or assignment.get("sectionId") or "unsectioned"
    metadata = _assignment_metadata(assignment)
    packet = _reporting_packet_fields(message.get("metadata"))
    coverage_concept_key = (
        packet.get("coverageConceptKey")
        or packet.get("coverageKey")
        or metadata.get("coverageConceptKey")
        or metadata.get("coverageKey")
    )
    edition_id = packet.get("editionId") or metadata.get("editionId") or (
        f"edition-{metadata['storyCycleDate']}" if metadata.get("storyCycleDate") else None
    )
    edition_date = (
        metadata.get("editionDate")
        or metadata.get("storyCycleDate")
        or packet.get("editionDate")
        or _date_from_id(edition_id)
    )
    story_cycle_run_id = (
        metadata.get("storyCycleRunId")
        or metadata.get("coverageThemeRunId")
        or metadata.get("runId")
        or packet.get("storyCycleRunId")
        or message.get("importRunId")
    )
    record_id = f"assignment-copywriting-{safe_id(target_item_type)}-{hash_short([assignment['id'], message['id'], decision])}"
    queue_key = f"copywriting:{edition_id or 'unplanned'}:section:{section}:type:{target_item_type}"
    copywriter_brief = (
        packet.get("copywriterBrief")
        or message.get("summary")
        or f"Draft a reader-facing {target_item_type} from the selected private reporting packet."
    )
    copywriting_metadata = {
        "kind": "copywriting.assignment",
        "createdFrom": "reporting_packet_selection",
        "sourceReportingAssignmentId": assignment["id"],
        "sourceReportingPacketMessageId": message["id"],
        "sourceReportingPacketKind": REPORTING_PACKET_KIND,
        "decision": decision,
        "targetItemType": target_item_type,
        "sectionKey": section,
        "editionId": edition_id,
        "editionDate": edition_date,
        "storyCycleDate": edition_date,
        "coverageConceptKey": coverage_concept_key,
        "topic": packet.get("topic") or metadata.get("topic"),
        "acceptedReferenceIds": packet.get("acceptedReferenceIds") or [],
        "proposedReferences": packet.get("proposedReferences") or [],
        "storyCycleRunId": story_cycle_run_id,
        "recommendedAngle": packet.get("recommendedAngle"),
        "editorRecommendation": packet.get("editorRecommendation"),
        "reportingPacketSummary": packet.get("summary") or message.get("summary"),
    }
    return {
        "id": record_id,
        "assignmentTypeKey": assignment_type_key,
        "queueKey": queue_key,
        "queueStatusKey": f"{queue_key}#open",
        "status": "open",
        "priority": (int(assignment.get("priority") or 100)) + 1,
        "title": (
            f"{'Write brief' if target_item_type == 'brief' else 'Write article'} from "
            f"{assignment.get('title') or 'selected reporting packet'}"
        ),
        "summary": (
            f"Copywriting handoff for selected {target_item_type} packet from "
            f"{assignment.get('title') or assignment['id']}."
        ),
        "brief": copywriter_brief,
        "instructions": "\n".join(
            [
                "Consume the private reporting_context_packet and copywriter brief.",
                "Create a complete reader-facing draft Item for editor review.",
                "Do not publish the Item and do not create EditionItem placement.",
                "Do not copy internal doctrine, desk memory, private source notes, or unresolved proposed references into reader-facing fields.",
            ]
        ),
        "metadata": json.dumps(copywriting_metadata),
        "corpusId": assignment.get("corpusId"),
        "categorySetId": assignment.get("categorySetId"),
        "classifierId": assignment.get("classifierId"),
        "sourceSnapshotId": assignment.get("sourceSnapshotId"),
        "importRunId": assignment.get("importRunId"),
        "sectionId": assignment.get("sectionId") or section,
        "sectionKey": section,
        "sectionType": assignment.get("sectionType"),
        "sectionStatusKey": f"{section}#open",
        "sectionQueueStatusKey": f"{section}#{queue_key}#open",
        "primaryFocusCategoryKey": assignment.get("primaryFocusCategoryKey") or metadata.get("categoryKey"),
        "topicScopeCategoryKeys": assignment.get("topicScopeCategoryKeys")
        or [metadata.get("categoryKey") or assignment.get("primaryFocusCategoryKey")],
        "createdBy": actor_label,
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "assignment#open",
        "itemLineageId": content_item_lineage_id,
    }


def _copywriting_target_item_type(assignment_type_key: str) -> str:
    return "brief" if assignment_type_key == COPYWRITING_BRIEF_ASSIGNMENT_TYPE else "article"


def _reporting_packet_fields(value: Any) -> dict[str, Any]:
    metadata = _assignment_metadata({"metadata": value})
    reporting = metadata.get("reporting") if isinstance(metadata.get("reporting"), dict) else metadata
    coverage_concept = reporting.get("coverageConcept") if isinstance(reporting.get("coverageConcept"), dict) else {}
    return {
        "summary": _clean_string(reporting.get("summary")),
        "topic": _clean_string(reporting.get("topic")),
        "sectionKey": _clean_string(reporting.get("sectionKey") or reporting.get("section_key")),
        "editionId": _clean_string(reporting.get("editionId") or reporting.get("edition_id")),
        "editionDate": _clean_string(reporting.get("editionDate") or reporting.get("edition_date")),
        "storyCycleRunId": _clean_string(
            reporting.get("storyCycleRunId")
            or reporting.get("story_cycle_run_id")
            or reporting.get("coverageThemeRunId")
            or reporting.get("coverage_theme_run_id")
        ),
        "coverageKey": _clean_string(reporting.get("coverageKey") or reporting.get("coverage_key")),
        "coverageConceptKey": _clean_string(
            reporting.get("coverageConceptKey")
            or reporting.get("coverage_concept_key")
            or reporting.get("coverageKey")
            or reporting.get("coverage_key")
            or coverage_concept.get("key")
        ),
        "editorRecommendation": _clean_string(reporting.get("editorRecommendation") or reporting.get("editor_recommendation")),
        "recommendedAngle": _clean_string(reporting.get("recommendedAngle") or reporting.get("recommended_angle")),
        "copywriterBrief": _clean_string(reporting.get("copywriterBrief") or reporting.get("copywriter_brief")),
        "acceptedReferenceIds": reporting.get("acceptedReferenceIds") or reporting.get("accepted_reference_ids") or [],
        "proposedReferences": reporting.get("proposedReferences") or reporting.get("proposed_references") or [],
    }


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


def _date_from_id(value: Any) -> str | None:
    match = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else None


def _timestamp_id(value: str) -> str:
    return re.sub(r"[^0-9TZ]", "", value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
