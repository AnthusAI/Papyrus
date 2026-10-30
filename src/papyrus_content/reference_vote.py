"""A Reference keeps its latest vote on itself.

Messages come only from people, so a vote (an accept, reject, archive or reopen) is no longer a
``reference_curation`` Message with a ``comment`` relation. The Reference already holds the status, who set it,
when and the note (``curationStatus``, ``curationStatusUpdatedBy``, ``curationStatusUpdatedAt``,
``curationStatusReason``). The rest of a vote's details sit beside them:

* ``curationActorKind``: ``human``, ``agent``, ``cyclotron``, ``rule`` or ``catalog``. Only ``human`` ever trains the Cyclotron.
* ``curationReasonCode``, ``curationSectionId``, ``curationShareable``, ``curationDecisionRelationId``;
* ``curationDelegation``: the JSON ``{delegationId, relayedBy, instruction}`` of a delegated vote.

A Reference keeps only its latest vote; the history of earlier votes lives in the Cyclotron's feedback. A Reference no
one has voted on has no ``curationActorKind``. Readers use ``latest_vote``; writers spread ``vote_fields`` into their update.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from .ids import hash_short, safe_id

HUMAN = "human"
AGENT = "agent"
CYCLOTRON = "cyclotron"
RULE = "rule"
CATALOG = "catalog"
ACTOR_KINDS = (HUMAN, AGENT, CYCLOTRON, RULE, CATALOG)

ACTION_FOR_STATUS = {"accepted": "accept", "rejected": "reject", "archived": "archive", "pending": "reopen"}


def vote_fields(actor_kind: str, *, reason_code: str | None = None, section_id: str | None = None,
                shareable: bool | None = None, delegation: Mapping[str, Any] | None = None,
                decision_relation_id: str | None = None) -> dict[str, Any]:
    """The Reference fields a vote sets. Every field is always present, so a new vote clears what the last one carried."""
    if actor_kind not in ACTOR_KINDS:
        raise ValueError(f"A vote's actor kind must be one of {', '.join(ACTOR_KINDS)}, not {actor_kind!r}.")
    return {
        "curationActorKind": actor_kind,
        "curationReasonCode": (reason_code or "").strip() or None,
        "curationSectionId": (section_id or "").strip() or None,
        "curationShareable": shareable,
        "curationDelegation": json.dumps(dict(delegation), sort_keys=True) if delegation else None,
        "curationDecisionRelationId": (decision_relation_id or "").strip() or None,
    }


def _delegation_of(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str) and value.strip():
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return dict(value) if isinstance(value, Mapping) and value else None


def latest_vote(reference: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The Reference's latest vote, or None when no one has voted on it.

    ``id`` names the vote for idempotent hand-offs (the Cyclotron's review id): it changes only when the vote does.
    """
    if not reference or not str(reference.get("curationActorKind") or "").strip():
        return None
    status = str(reference.get("curationStatus") or "pending")
    lineage_id = str(reference.get("lineageId") or reference.get("id") or "")
    updated_at = str(reference.get("curationStatusUpdatedAt") or "")
    updated_by = str(reference.get("curationStatusUpdatedBy") or "")
    return {
        "id": f"vote-{safe_id(lineage_id)}-{hash_short([reference.get('id'), updated_at, status, updated_by])}",
        "actorKind": str(reference["curationActorKind"]),
        "authorLabel": updated_by or None,
        "createdAt": updated_at or None,
        "action": ACTION_FOR_STATUS.get(status, "reopen"),
        "curationStatus": status,
        "note": reference.get("curationStatusReason"),
        "reasonCode": reference.get("curationReasonCode") or None,
        "sectionId": reference.get("curationSectionId") or None,
        "shareable": reference.get("curationShareable"),
        "delegation": _delegation_of(reference.get("curationDelegation")),
        "decisionRelationId": reference.get("curationDecisionRelationId") or None,
    }
