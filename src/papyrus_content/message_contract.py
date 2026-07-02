from __future__ import annotations

import json
from typing import Any


def build_canonical_message_expected(
    payload: dict[str, Any],
    *,
    default_source: str,
    default_author_label: str,
    default_response_owner: str,
) -> dict[str, Any]:
    created_at = _string(payload.get("createdAt"))
    if not created_at:
        raise ValueError("Message.createdAt is required.")
    source = _string(payload.get("source")) or default_source
    summary = _string(payload.get("summary")) or _default_summary(payload)
    author_label = _string(payload.get("authorLabel")) or default_author_label

    metadata_value = payload.get("metadata")
    if isinstance(metadata_value, str):
        metadata_json = metadata_value
    else:
        metadata_json = json.dumps(metadata_value or {}, sort_keys=True)

    expected = {
        "id": _string(payload.get("id")) or "",
        "messageKind": _string(payload.get("messageKind")) or "comment",
        "messageDomain": _string(payload.get("messageDomain")) or "commentary",
        "status": _string(payload.get("status")) or "active",
        "summary": summary,
        "source": source,
        "importRunId": payload.get("importRunId"),
        "authorSub": payload.get("authorSub"),
        "authorUserProfileId": payload.get("authorUserProfileId"),
        "authorLabel": author_label,
        "threadId": payload.get("threadId"),
        "parentMessageId": payload.get("parentMessageId"),
        "sequenceNumber": payload.get("sequenceNumber"),
        "role": payload.get("role"),
        "messageType": payload.get("messageType"),
        "semanticLayer": payload.get("semanticLayer"),
        "searchVisibility": payload.get("searchVisibility"),
        "responseTarget": _string(payload.get("responseTarget")) or "none",
        "responseStatus": _string(payload.get("responseStatus")) or "COMPLETED",
        "responseOwner": _string(payload.get("responseOwner")) or default_response_owner,
        "responseStartedAt": _string(payload.get("responseStartedAt")) or created_at,
        "responseCompletedAt": _string(payload.get("responseCompletedAt")) or created_at,
        "responseError": _string(payload.get("responseError")) or None,
        "metadata": metadata_json,
        "createdAt": created_at,
        "updatedAt": _string(payload.get("updatedAt")) or created_at,
        "newsroomFeedKey": _string(payload.get("newsroomFeedKey")) or "messages",
    }
    return {key: value for key, value in expected.items() if value is not None}


def _default_summary(payload: dict[str, Any]) -> str:
    body = _string(payload.get("body"))
    if body:
        return body if len(body) <= 200 else f"{body[:197]}..."
    return _string(payload.get("messageKind")) or "message"


def _string(value: Any) -> str:
    return str(value).strip() if value is not None else ""
