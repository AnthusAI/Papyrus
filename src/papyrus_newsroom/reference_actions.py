from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import uuid
from typing import Any, Callable


GraphqlInvoker = Callable[[str, dict[str, Any]], dict[str, Any]]

GET_REFERENCE_QUERY = """
query GetReference($id: ID!) {
  getReference(id: $id) {
    id
    lineageId
    versionNumber
    corpusId
    title
    externalItemId
    curationStatus
    newsroomFeedKey
  }
}
"""

UPDATE_REFERENCE_MUTATION = """
mutation UpdateReference($input: UpdateReferenceInput!) {
  updateReference(input: $input) {
    id
    lineageId
    curationStatus
    curationStatusKey
    curationStatusUpdatedAt
    curationStatusUpdatedBy
    curationStatusReason
    updatedAt
  }
}
"""

CREATE_MESSAGE_MUTATION = """
mutation CreateMessage($input: CreateMessageInput!) {
  createMessage(input: $input) {
    id
    messageKind
    messageDomain
    status
    summary
    source
    authorLabel
    responseTarget
    responseStatus
    responseOwner
    createdAt
    updatedAt
  }
}
"""

CREATE_SEMANTIC_RELATION_MUTATION = """
mutation CreateSemanticRelation($input: CreateSemanticRelationInput!) {
  createSemanticRelation(input: $input) {
    id
    relationState
    predicate
    relationTypeKey
    relationDomain
    subjectKind
    subjectId
    objectKind
    objectId
    createdAt
    updatedAt
  }
}
"""

REFERENCE_CURATION_ACTIONS = {"accept", "reject", "reopen", "archive"}
REFERENCE_CURATION_STATUSES = {
    "accept": "accepted",
    "reject": "rejected",
    "reopen": "pending",
    "archive": "archived",
}
RELATION_TYPE_FIELDS = {
    "comment": {
        "relationTypeId": "semantic-relation-type-comment",
        "relationTypeKey": "comment",
        "relationDomain": "commentary",
    },
    "note_about": {
        "relationTypeId": "semantic-relation-type-note-about",
        "relationTypeKey": "note_about",
        "relationDomain": "knowledge",
    },
}


SET_REFERENCE_QUALITY_RATING_MUTATION = """
mutation SetReferenceQualityRating($referenceId: ID!, $rating: Int!, $actorLabel: String, $note: String) {
  setReferenceQualityRating(
    referenceId: $referenceId
    rating: $rating
    actorLabel: $actorLabel
    note: $note
  ) {
    ok
    referenceId
    rating
    status
    relationId
  }
}
"""

MOVE_REFERENCE_CORPUS_MUTATION = """
mutation MoveReferenceCorpus($referenceId: ID!, $corpusId: ID!, $actorLabel: String, $note: String) {
  moveReferenceCorpus(
    referenceId: $referenceId
    corpusId: $corpusId
    actorLabel: $actorLabel
    note: $note
  ) {
    ok
    referenceId
    referenceLineageId
    previousReferenceId
    previousCorpusId
    corpusId
    status
  }
}
"""

START_REFERENCE_CURATION_MUTATION = """
mutation StartReferenceCuration($referenceId: ID!, $actorLabel: String, $curationPolicy: AWSJSON) {
  startReferenceCuration(
    referenceId: $referenceId
    actorLabel: $actorLabel
    curationPolicy: $curationPolicy
  ) {
    ok
    referenceId
    assignmentId
    status
    runId
  }
}
"""

GET_REFERENCE_CURATION_STATUS_QUERY = """
query GetReferenceCurationStatus($assignmentId: ID!) {
  getReferenceCurationStatus(assignmentId: $assignmentId) {
    ok
    referenceId
    assignmentId
    status
    runId
    lifecycleStatus
    stageStatuses
    changedOutputs
    error
  }
}
"""


def review_reference_curation(
    graphql: GraphqlInvoker,
    *,
    reference_id: str,
    action: str,
    actor_label: str = "",
    note: str = "",
    reason_code: str = "",
) -> dict[str, Any]:
    resolved_reference_id = _required(reference_id, "reference_id")
    resolved_action = _normalize_curation_action(action)
    next_status = REFERENCE_CURATION_STATUSES[resolved_action]
    actor = _optional(actor_label) or "Papyrus newsroom"
    user_note = _optional(note)
    now = _now_iso()
    reference = _get_required_reference(graphql, resolved_reference_id)
    reference_lineage_id = _optional(reference.get("lineageId")) or resolved_reference_id
    reference_title = _reference_title(reference)
    message_id = (
        f"message-reference-curation-{_safe_id(reference_lineage_id)}-{_safe_id(resolved_action)}-"
        f"{now.replace(':', '').replace('-', '')[:15]}-{uuid.uuid4().hex[:8]}"
    )
    relation_id = "semantic-relation-" + _hash_short(
        [
            _semantic_version_key("message", message_id),
            "comment",
            _semantic_version_key("reference", resolved_reference_id),
            resolved_action,
        ]
    )

    _call(
        graphql,
        UPDATE_REFERENCE_MUTATION,
        "updateReference",
        {
            "input": {
                "id": resolved_reference_id,
                "curationStatus": next_status,
                "curationStatusKey": f"{_required(reference.get('corpusId'), 'reference.corpusId')}#{next_status}",
                "curationStatusUpdatedAt": now,
                "curationStatusUpdatedBy": actor,
                "curationStatusReason": user_note,
                "newsroomFeedKey": _optional(reference.get("newsroomFeedKey")) or "references",
                "updatedAt": now,
            }
        },
    )
    _create_message(
        graphql,
        message_id=message_id,
        message_kind="reference_curation",
        message_domain="commentary",
        summary=f"{reference_title}: {next_status}",
        body=user_note or f"{actor} marked this reference {next_status}.",
        actor_label=actor,
        now=now,
        metadata={
            "action": resolved_action,
            "curationStatus": next_status,
            "reasonCode": _optional(reason_code),
            "referenceId": resolved_reference_id,
            "referenceLineageId": reference_lineage_id,
        },
    )
    _create_semantic_relation(
        graphql,
        relation_id=relation_id,
        predicate="comment",
        subject_kind="message",
        subject_id=message_id,
        subject_lineage_id=message_id,
        subject_version_number=1,
        object_kind="reference",
        object_id=resolved_reference_id,
        object_lineage_id=reference_lineage_id,
        object_version_number=_optional_int(reference.get("versionNumber")),
        metadata={
            "action": resolved_action,
            "curationStatus": next_status,
            "reasonCode": _optional(reason_code),
            "messageKind": "reference_curation",
        },
        now=now,
    )
    return {
        "ok": True,
        "action": resolved_action,
        "referenceId": resolved_reference_id,
        "status": next_status,
        "reasonCode": _optional(reason_code),
        "messageId": message_id,
        "relationId": relation_id,
    }


def set_reference_quality_rating(
    graphql: GraphqlInvoker,
    *,
    reference_id: str,
    rating: int,
    actor_label: str = "",
    note: str = "",
) -> dict[str, Any]:
    return _call(
        graphql,
        SET_REFERENCE_QUALITY_RATING_MUTATION,
        "setReferenceQualityRating",
        {
            "referenceId": _required(reference_id, "reference_id"),
            "rating": int(rating),
            "actorLabel": actor_label or None,
            "note": note or None,
        },
    )


def create_reference_note(
    graphql: GraphqlInvoker,
    *,
    reference_id: str,
    summary: str,
    body: str,
    actor_label: str = "",
) -> dict[str, Any]:
    resolved_reference_id = _required(reference_id, "reference_id")
    resolved_summary = _required(summary, "summary")
    resolved_body = _required(body, "body")
    actor = _optional(actor_label) or "Papyrus newsroom"
    now = _now_iso()
    reference = _get_required_reference(graphql, resolved_reference_id)
    reference_lineage_id = _optional(reference.get("lineageId")) or resolved_reference_id
    message_id = (
        f"message-reference-note-{_safe_id(reference_lineage_id)}-"
        f"{now.replace(':', '').replace('-', '')[:15]}-{uuid.uuid4().hex[:8]}"
    )
    relation_id = "semantic-relation-" + _hash_short(
        [
            _semantic_version_key("message", message_id),
            "note_about",
            _semantic_version_key("reference", resolved_reference_id),
        ]
    )
    _create_message(
        graphql,
        message_id=message_id,
        message_kind="note",
        message_domain="knowledge",
        summary=resolved_summary,
        body=resolved_body,
        actor_label=actor,
        now=now,
        metadata={
            "kind": "reference.note.created",
            "targetKind": "reference",
            "targetId": resolved_reference_id,
            "targetLineageId": reference_lineage_id,
        },
    )
    _create_semantic_relation(
        graphql,
        relation_id=relation_id,
        predicate="note_about",
        subject_kind="message",
        subject_id=message_id,
        subject_lineage_id=message_id,
        subject_version_number=1,
        object_kind="reference",
        object_id=resolved_reference_id,
        object_lineage_id=reference_lineage_id,
        object_version_number=_optional_int(reference.get("versionNumber")),
        metadata={
            "kind": "reference.note",
            "summary": resolved_summary,
            "actor": actor,
        },
        now=now,
    )
    return {
        "ok": True,
        "referenceId": resolved_reference_id,
        "messageId": message_id,
        "relationId": relation_id,
        "status": "created",
    }


def move_reference_corpus(
    graphql: GraphqlInvoker,
    *,
    reference_id: str,
    corpus_id: str,
    actor_label: str = "",
    note: str = "",
) -> dict[str, Any]:
    return _call(
        graphql,
        MOVE_REFERENCE_CORPUS_MUTATION,
        "moveReferenceCorpus",
        {
            "referenceId": _required(reference_id, "reference_id"),
            "corpusId": _required(corpus_id, "corpus_id"),
            "actorLabel": actor_label or None,
            "note": note or None,
        },
    )


def start_reference_curation(
    graphql: GraphqlInvoker,
    *,
    reference_id: str,
    actor_label: str = "",
    curation_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = curation_policy or None
    return _call(
        graphql,
        START_REFERENCE_CURATION_MUTATION,
        "startReferenceCuration",
        {
            "referenceId": _required(reference_id, "reference_id"),
            "actorLabel": actor_label or None,
            "curationPolicy": json.dumps(policy) if policy is not None else None,
        },
    )


def get_reference_curation_status(
    graphql: GraphqlInvoker,
    *,
    assignment_id: str,
) -> dict[str, Any]:
    return _call(
        graphql,
        GET_REFERENCE_CURATION_STATUS_QUERY,
        "getReferenceCurationStatus",
        {"assignmentId": _required(assignment_id, "assignment_id")},
    )


def _call(
    graphql: GraphqlInvoker,
    query: str,
    field_name: str,
    variables: dict[str, Any],
) -> dict[str, Any]:
    data = graphql(query, variables)
    value = data.get(field_name)
    return value if isinstance(value, dict) else {}


def _get_required_reference(graphql: GraphqlInvoker, reference_id: str) -> dict[str, Any]:
    reference_data = _call(graphql, GET_REFERENCE_QUERY, "getReference", {"id": reference_id})
    if not reference_data:
        raise ValueError(f"Reference not found: {reference_id}")
    return reference_data


def _create_message(
    graphql: GraphqlInvoker,
    *,
    message_id: str,
    message_kind: str,
    message_domain: str,
    summary: str,
    body: str,
    actor_label: str,
    now: str,
    metadata: dict[str, Any],
) -> None:
    _call(
        graphql,
        CREATE_MESSAGE_MUTATION,
        "createMessage",
        {
            "input": {
                "id": message_id,
                "messageKind": message_kind,
                "messageDomain": message_domain,
                "status": "active",
                "summary": summary,
                "source": "newsroom",
                "authorLabel": actor_label,
                "content": body,
                "responseTarget": "none",
                "responseStatus": "COMPLETED",
                "responseOwner": "papyrus-reference-actions",
                "responseStartedAt": now,
                "responseCompletedAt": now,
                "responseError": None,
                "metadata": json.dumps(metadata, sort_keys=True),
                "createdAt": now,
                "updatedAt": now,
                "newsroomFeedKey": "messages",
            }
        },
    )


def _create_semantic_relation(
    graphql: GraphqlInvoker,
    *,
    relation_id: str,
    predicate: str,
    subject_kind: str,
    subject_id: str,
    subject_lineage_id: str,
    subject_version_number: int | None,
    object_kind: str,
    object_id: str,
    object_lineage_id: str,
    object_version_number: int | None,
    metadata: dict[str, Any],
    now: str,
) -> None:
    relation_type = RELATION_TYPE_FIELDS.get(predicate)
    if relation_type is None:
        raise ValueError(f"Unsupported relation predicate: {predicate}")
    subject_state_key = _semantic_state_key(subject_kind, subject_lineage_id)
    object_state_key = _semantic_state_key(object_kind, object_lineage_id)
    _call(
        graphql,
        CREATE_SEMANTIC_RELATION_MUTATION,
        "createSemanticRelation",
        {
            "input": {
                "id": relation_id,
                "relationState": "current",
                "predicate": predicate,
                **relation_type,
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
                "subjectVersionKey": _semantic_version_key(subject_kind, subject_id),
                "objectVersionKey": _semantic_version_key(object_kind, object_id),
                "score": 1,
                "rank": 1,
                "reviewRecommended": False,
                "importedAt": now,
                "createdAt": now,
                "updatedAt": now,
                "newsroomFeedKey": "semanticRelations",
                "metadata": json.dumps(metadata, sort_keys=True),
            }
        },
    )


def _reference_title(reference: dict[str, Any]) -> str:
    return _optional(reference.get("title")) or _optional(reference.get("externalItemId")) or _required(reference.get("id"), "reference.id")


def _normalize_curation_action(action: Any) -> str:
    normalized = _required(action, "action").strip().lower().replace("-", "_")
    if normalized not in REFERENCE_CURATION_ACTIONS:
        raise ValueError(f"Unsupported curation action: {normalized}")
    return normalized


def _optional(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    numeric = int(value)
    return numeric if numeric > 0 else None


def _semantic_state_key(kind: str, lineage_id: str) -> str:
    return f"{kind}#{lineage_id}#current"


def _semantic_version_key(kind: str, version_id: str) -> str:
    return f"{kind}#{version_id}"


def _safe_id(value: Any) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return cleaned[:80] or "id"


def _hash_short(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _required(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Missing required value: {name}")
    return text
