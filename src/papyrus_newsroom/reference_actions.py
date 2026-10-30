from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from papyrus_content.reference_vote import AGENT, vote_fields


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
    curationReasonCode
    curationActorKind
    curationSectionId
    curationShareable
    curationDelegation
    curationDecisionRelationId
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


RECORD_DELEGATED_CURATION_MUTATION = """
mutation RecordDelegatedCuration(
  $referenceId: ID!, $action: String!, $delegationId: ID!, $delegationToken: String!, $agentLabel: String!,
  $onBehalfOf: String!, $instruction: String!, $note: String, $reasonCode: String, $decisionRelationId: ID, $shareable: Boolean, $sectionId: ID
) {
  recordDelegatedCuration(
    referenceId: $referenceId, action: $action, delegationId: $delegationId, delegationToken: $delegationToken,
    agentLabel: $agentLabel, onBehalfOf: $onBehalfOf, instruction: $instruction, note: $note, reasonCode: $reasonCode,
    decisionRelationId: $decisionRelationId, shareable: $shareable, sectionId: $sectionId
  ) {
    ok
    action
    referenceId
    status
    reasonCode
    messageId
    relationId
  }
}
"""


GET_NEWSROOM_SECTION_QUERY = """
query GetNewsroomSection($id: ID!) {
  getNewsroomSection(id: $id) {
    id
    enabled
    enabledStatus
  }
}
"""


REQUEST_CURATION_DELEGATION_MUTATION = """
mutation RequestCurationDelegation($delegationId: ID!, $tokenHash: String!, $agentLabel: String!, $hours: Int) {
  requestCurationDelegation(delegationId: $delegationId, tokenHash: $tokenHash, agentLabel: $agentLabel, hours: $hours) {
    ok
    delegationId
    userCode
    pendingExpiresAt
    requestedHours
  }
}
"""


GET_CURATION_DELEGATION_STATUS_QUERY = """
query GetCurationDelegationStatus($delegationId: ID!) {
  getCurationDelegationStatus(delegationId: $delegationId) {
    delegationId
    state
    expiresAt
    grantorLabel
  }
}
"""

DELEGATION_TERMINAL_STATES = ("approved", "denied", "expired", "revoked")


def new_delegation_token() -> str:
    """Make a delegation token whose secret half exists only on the machine that made it."""
    return f"curation-delegation-{uuid.uuid4()}~{secrets.token_urlsafe(24)}"


def hash_delegation_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def read_delegation_token_file(path: str | Path) -> str:
    token = Path(path).expanduser().read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("The delegation file is empty.")
    return token


def request_curation_delegation(
    graphql: GraphqlInvoker,
    *,
    delegation_token: str,
    agent_label: str,
    hours: int | None = None,
) -> dict[str, Any]:
    """Ask for a delegation. Only the hash of the token leaves this machine; a person approves the returned code."""
    return _call(
        graphql,
        REQUEST_CURATION_DELEGATION_MUTATION,
        "requestCurationDelegation",
        {
            "delegationId": delegation_id_from_token(_required(delegation_token, "delegation_token")),
            "tokenHash": hash_delegation_token(delegation_token),
            "agentLabel": _required(agent_label, "agent_label"),
            "hours": hours,
        },
    )


def get_curation_delegation_status(graphql: GraphqlInvoker, *, delegation_id: str) -> dict[str, Any]:
    return _call(
        graphql,
        GET_CURATION_DELEGATION_STATUS_QUERY,
        "getCurationDelegationStatus",
        {"delegationId": _required(delegation_id, "delegation_id")},
    )


def wait_for_curation_delegation(
    graphql: GraphqlInvoker,
    *,
    delegation_id: str,
    poll_interval_seconds: float = 5.0,
    timeout_seconds: float = 660.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll until a person approves or denies the request, or it expires, or the timeout passes."""
    deadline = monotonic() + timeout_seconds
    while True:
        status = get_curation_delegation_status(graphql, delegation_id=delegation_id)
        if status.get("state") in DELEGATION_TERMINAL_STATES:
            return status
        if monotonic() >= deadline:
            return {**status, "state": status.get("state") or "pending", "timedOut": True}
        sleep(poll_interval_seconds)


def delegation_id_from_token(token: str) -> str:
    delegation_id, separator, _ = token.partition("~")
    if not separator or not delegation_id:
        raise ValueError("That is not a delegation token. Ask the person to create one in the Newsroom.")
    return delegation_id


def record_delegated_curation(
    graphql: GraphqlInvoker,
    *,
    reference_id: str,
    action: str,
    delegation_token: str,
    agent_label: str,
    on_behalf_of: str,
    instruction: str,
    note: str = "",
    reason_code: str = "",
    section_id: str = "",
) -> dict[str, Any]:
    """Record a person's decision, relayed by an agent, with the delegation the person granted it."""
    resolved_action = _normalize_curation_action(action)
    if resolved_action not in ("accept", "reject"):
        raise ValueError("A delegation can record only accept or reject.")
    return _call(
        graphql,
        RECORD_DELEGATED_CURATION_MUTATION,
        "recordDelegatedCuration",
        {
            "referenceId": _required(reference_id, "reference_id"),
            "action": resolved_action,
            "delegationId": delegation_id_from_token(_required(delegation_token, "delegation_token")),
            "delegationToken": delegation_token,
            "agentLabel": _required(agent_label, "agent_label"),
            "onBehalfOf": _required(on_behalf_of, "on_behalf_of"),
            "instruction": _required(instruction, "instruction"),
            "note": _optional(note) or None,
            "reasonCode": _optional(reason_code) or None,
            "sectionId": _optional(section_id) or None,
        },
    )


def review_reference_curation(
    graphql: GraphqlInvoker,
    *,
    reference_id: str,
    action: str,
    actor_label: str = "",
    note: str = "",
    reason_code: str = "",
    section_id: str = "",
) -> dict[str, Any]:
    resolved_reference_id = _required(reference_id, "reference_id")
    resolved_action = _normalize_curation_action(action)
    next_status = REFERENCE_CURATION_STATUSES[resolved_action]
    actor = _optional(actor_label) or "Papyrus newsroom"
    user_note = _optional(note)
    now = _now_iso()
    reference = _get_required_reference(graphql, resolved_reference_id)
    resolved_section_id = _validated_section_id(graphql, section_id, resolved_action)
    reasoning = _optional(reason_code)
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
                # The vote's details live on the Reference: Messages come only from people, so no Message is written.
                **vote_fields(AGENT, reason_code=reasoning, section_id=resolved_section_id),
                "newsroomFeedKey": _optional(reference.get("newsroomFeedKey")) or "references",
                "updatedAt": now,
            }
        },
    )
    return {
        "ok": True,
        "action": resolved_action,
        "referenceId": resolved_reference_id,
        "status": next_status,
        "reasonCode": reasoning,
        "sectionId": resolved_section_id,
    }


def _validated_section_id(graphql: GraphqlInvoker, section_id: str, action: str) -> str | None:
    requested_section_id = _optional(section_id)
    if not requested_section_id:
        return None
    if action != "accept":
        raise ValueError("A section can be recorded only when accepting a reference.")
    section = _call(graphql, GET_NEWSROOM_SECTION_QUERY, "getNewsroomSection", {"id": requested_section_id})
    if not section:
        raise ValueError(f"Newsroom section {requested_section_id} was not found.")
    if section.get("enabled") is False or section.get("enabledStatus") == "disabled":
        raise ValueError(f"Newsroom section {requested_section_id} is disabled.")
    return requested_section_id


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


def _normalize_curation_action(action: Any) -> str:
    normalized = _required(action, "action").strip().lower().replace("-", "_")
    if normalized not in REFERENCE_CURATION_ACTIONS:
        raise ValueError(f"Unsupported curation action: {normalized}")
    return normalized


def _optional(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _required(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Missing required value: {name}")
    return text
