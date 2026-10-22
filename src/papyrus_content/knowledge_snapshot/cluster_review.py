"""Review of topic clusters: the partial updates behind ``papyrus knowledge clusters accept|name|reject``.

A cluster is a ``topic_cluster`` ``SteeringProposal``. Accepting it names it and records who accepted it in the
``acceptedBy`` of its summary object; the run that imports the next version of the cluster keeps all of it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .actors import Actor
from .cluster_records import CLUSTER_KIND, STATUS_ACCEPTED, STATUS_PROPOSED, decode_metadata
from .keys import contains_email

STATUS_REJECTED = "rejected"


class ClusterReviewError(ValueError):
    pass


def find_cluster(rows: Iterable[Mapping[str, Any]], identifier: str) -> dict:
    """The one ``topic_cluster`` proposal whose cluster uid or proposal id is ``identifier``."""
    wanted = identifier.strip()
    matches = []
    for row in rows:
        if row.get("proposalKind") != CLUSTER_KIND:
            continue
        metadata = decode_metadata(row.get("summary")) or {}
        if wanted in (row.get("id"), row.get("graphEntityId"), metadata.get("clusterUid")):
            matches.append(dict(row))
    if not matches:
        raise ClusterReviewError(f"No cluster {identifier!r} (give a cluster uid or a proposal id).")
    if len(matches) > 1:
        raise ClusterReviewError(f"{identifier!r} names {len(matches)} clusters: " + ", ".join(sorted(row["id"] for row in matches)))
    return matches[0]


def clean_cluster_name(value: str | None) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise ClusterReviewError("A cluster name is needed.")
    if contains_email(name):
        raise ClusterReviewError("A cluster name must not hold an email address.")
    return name


def reviewer_label(actor: Actor) -> str:
    return f"{actor.actor}:{actor.name}" if actor.name else actor.actor


def _summary_with(proposal: Mapping[str, Any], accepted_by: Actor | None) -> str:
    metadata = decode_metadata(proposal.get("summary"))
    if metadata is None:
        raise ClusterReviewError(f"{proposal['id']} does not carry the figures of a knowledge cluster; import it with publish-run first.")
    return json.dumps({**metadata, "acceptedBy": accepted_by.to_dict()} if accepted_by else metadata, sort_keys=True, separators=(",", ":"))


def accept_cluster_patches(proposal: Mapping[str, Any], name: str | None, actor: Actor, *, now: str) -> list[dict]:
    if proposal.get("status") == STATUS_ACCEPTED and not name:
        return []
    if proposal.get("status") not in (STATUS_PROPOSED, STATUS_ACCEPTED):
        raise ClusterReviewError(f"{proposal['id']} is {proposal.get('status')}; only a proposed cluster can be accepted.")
    chosen = clean_cluster_name(name or proposal.get("displayName"))
    expected: dict[str, Any] = {"id": proposal["id"], "displayName": chosen, "updatedAt": now}
    if proposal.get("status") != STATUS_ACCEPTED:
        expected.update(
            status=STATUS_ACCEPTED,
            reviewedAt=now,
            reviewedBy=reviewer_label(actor),
            summary=_summary_with(proposal, actor),
        )
    return [{"modelName": "SteeringProposal", "expected": expected}]


def name_cluster_patches(proposal: Mapping[str, Any], name: str, *, now: str) -> list[dict]:
    chosen = clean_cluster_name(name)
    if chosen == proposal.get("displayName"):
        return []
    return [{"modelName": "SteeringProposal", "expected": {"id": proposal["id"], "displayName": chosen, "updatedAt": now}}]


def reject_cluster_patches(proposal: Mapping[str, Any], actor: Actor, *, now: str) -> list[dict]:
    if proposal.get("status") == STATUS_REJECTED:
        return []
    return [
        {
            "modelName": "SteeringProposal",
            "expected": {"id": proposal["id"], "status": STATUS_REJECTED, "reviewedAt": now, "reviewedBy": reviewer_label(actor), "updatedAt": now},
        }
    ]
