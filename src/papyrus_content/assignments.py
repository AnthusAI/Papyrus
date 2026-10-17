from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .graphql_authoring import PapyrusGraphQLAuthoringClient
from .model_attachments import (
    build_json_model_payload_attachment,
    download_attachment_buffer,
    parse_jsonish,
    upload_attachment_body,
)
from .options import normalize_string


def assignment_metadata(client: PapyrusGraphQLAuthoringClient, assignment: dict[str, Any]) -> dict[str, Any]:
    if isinstance(assignment.get("metadata"), str):
        try:
            parsed = json.loads(assignment["metadata"])
            if isinstance(parsed, dict) and parsed:
                return parsed
        except json.JSONDecodeError:
            pass
    elif isinstance(assignment.get("metadata"), dict) and assignment.get("metadata"):
        return assignment["metadata"]

    assignment_id = normalize_string(assignment.get("id"))
    if not assignment_id:
        return {}

    attachments = client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", assignment_id, limit=20)
    metadata_attachments = [
        entry
        for entry in attachments
        if normalize_string(entry.get("role")) == "metadata"
        and normalize_string(entry.get("status")) != "deleted"
    ]
    metadata_attachments.sort(key=lambda entry: str(entry.get("updatedAt") or ""), reverse=True)
    metadata_attachments.sort(key=lambda entry: 0 if normalize_string(entry.get("sortKey")) == "metadata" else 1)
    for attachment in metadata_attachments:
        try:
            payload = parse_jsonish(download_attachment_buffer(client, attachment).decode("utf-8", errors="replace"))
        except Exception:
            continue
        if isinstance(payload, dict) and payload:
            return payload
    return {}


def apply_assignment_action(
    client: PapyrusGraphQLAuthoringClient,
    *,
    auth_claims: dict[str, Any],
    action: str,
    assignment_id: str,
    options: dict[str, Any] | None = None,
    actor_label: str | None = None,
) -> None:
    options = options or {}
    current = client.get_record("Assignment", assignment_id)
    if not current:
        raise ValueError(f"Assignment {assignment_id} was not found.")
    now = _utc_now()
    next_status = assignment_status_for_action(action, current.get("status"))
    current_metadata = assignment_metadata(client, current)
    update = {
        "id": assignment_id,
        "assignmentTypeKey": current["assignmentTypeKey"],
        "queueKey": current["queueKey"],
        "status": next_status,
        "queueStatusKey": f"{current['queueKey']}#{next_status}",
        "sectionId": current.get("sectionId") or current_metadata.get("sectionId"),
        "sectionKey": current.get("sectionKey"),
        "sectionType": current.get("sectionType") or current_metadata.get("sectionType"),
        "primaryFocusCategoryKey": current.get("primaryFocusCategoryKey")
        or current_metadata.get("primaryFocusCategoryKey"),
        "topicScopeCategoryKeys": current.get("topicScopeCategoryKeys")
        or current_metadata.get("topicScopeCategoryKeys")
        or [],
        "createdAt": current.get("createdAt"),
        "updatedAt": now,
        "newsroomFeedKey": current.get("newsroomFeedKey") or "assignments",
    }
    if current.get("priority") is not None:
        update["priority"] = current["priority"]
    if action == "claim":
        claim_identity = resolve_cli_claim_identity(options, auth_claims)
        if active_claim_held_by_different_assignee(current, claim_identity["assigneeKey"], now):
            raise ValueError(f"Assignment {assignment_id} is already claimed by {current.get('assigneeKey')}.")
        update.update(
            {
                "assigneeType": claim_identity["assigneeType"],
                "assigneeId": claim_identity["assigneeId"],
                "assigneeKey": claim_identity["assigneeKey"],
                "claimedAt": current.get("claimedAt") if current.get("assigneeKey") == claim_identity["assigneeKey"] else now,
                "claimExpiresAt": resolve_cli_claim_expires_at(options, now),
            }
        )
    if action == "release":
        update.update(
            {
                "assigneeType": None,
                "assigneeId": None,
                "assigneeKey": None,
                "claimedAt": None,
                "claimExpiresAt": None,
            }
        )
    if action == "complete":
        update["completedAt"] = now
    if action == "cancel":
        update["canceledAt"] = now
    if action == "reopen":
        update["completedAt"] = None
        update["canceledAt"] = None
    client.upsert("Assignment", update)
    event_id = f"assignment-event-{assignment_id}-{now.replace('-', '').replace(':', '')[:15]}"
    client.upsert(
        "AssignmentEvent",
        {
            "id": event_id,
            "assignmentId": assignment_id,
            "assignmentTypeKey": current["assignmentTypeKey"],
            "queueKey": current["queueKey"],
            "eventType": action,
            "fromStatus": current.get("status"),
            "toStatus": next_status,
            "actorSub": auth_claims.get("sub"),
            "actorLabel": actor_label
            or options.get("assignee-key")
            or options.get("assignee")
            or auth_claims.get("email")
            or auth_claims.get("sub")
            or "authoring-cli",
            "note": options.get("note"),
            "createdAt": now,
        },
    )
    attachment = build_json_model_payload_attachment(
        {
            "ownerKind": "assignmentEvent",
            "ownerId": event_id,
            "ownerLineageId": event_id,
            "role": "metadata",
            "sortKey": "metadata",
            "content": {
                "source": "papyrus-cli",
                "kind": f"assignment.action.{action}",
            },
            "now": now,
        }
    )
    upload_attachment_body(client, attachment["attachment"], attachment["body"])
    client.upsert("ModelAttachment", attachment["attachment"])


def assignment_status_for_action(action: str, current_status: str | None) -> str:
    if action == "claim":
        return "claimed"
    if action == "release":
        return "open"
    if action == "complete":
        return "completed"
    if action == "cancel":
        return "canceled"
    if action == "reopen":
        return "open"
    raise ValueError(f"Unsupported assignment action: {action}")


def resolve_cli_claim_identity(options: dict[str, Any], auth_claims: dict[str, Any]) -> dict[str, str]:
    assignee_key = (
        normalize_string(options.get("assignee-key"))
        or normalize_string(options.get("assignee"))
        or normalize_string(options.get("actor"))
        or normalize_string(auth_claims.get("email"))
        or normalize_string(auth_claims.get("sub"))
        or "papyrus-cli"
    )
    return {
        "assigneeType": "agent",
        "assigneeId": assignee_key,
        "assigneeKey": assignee_key,
    }


def resolve_cli_claim_expires_at(options: dict[str, Any], now: str) -> str | None:
    ttl = options.get("claim-ttl-seconds")
    if ttl is True or ttl is None:
        return None
    seconds = int(str(ttl))
    current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    return (current + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def active_claim_held_by_different_assignee(assignment: dict[str, Any], assignee_key: str, now: str) -> bool:
    if assignment.get("status") != "claimed":
        return False
    if not assignment.get("assigneeKey") or assignment.get("assigneeKey") == assignee_key:
        return False
    expires = assignment.get("claimExpiresAt")
    if expires and expires < now:
        return False
    return True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
