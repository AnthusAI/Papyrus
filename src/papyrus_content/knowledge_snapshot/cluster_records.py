"""Topic clusters as ``SteeringProposal`` rows (proposalKind ``topic_cluster``).

The proposal model has no field for the run's figures, so they ride in ``summary`` as one JSON object with a marker
(``METADATA_MARKER``); ``description`` carries the readable sentence a desk reviewer sees. A continued cluster has the
same ``clusterUid``, so it maps to the same proposal id: the run updates the figures and keeps the desk's status,
name and review fields.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..ids import hash_short, safe_id
from .keys import slug
from .model import Cluster
from .run_input import ClusterEntry, ClusterRun

CLUSTER_KIND = "topic_cluster"
CLUSTER_DOMAIN = "topics"
METADATA_MARKER = "papyrus-knowledge-cluster@1"
STATUS_PROPOSED = "proposed"
STATUS_ACCEPTED = "accepted"
TITLE_TERMS = 3


def cluster_proposal_id(uid: str) -> str:
    return f"steering-proposal-cluster-{safe_id(uid)}-{hash_short(uid)[:6]}"


def cluster_category_key(uid: str) -> str:
    return f"cluster-{slug(uid) or hash_short(uid)}"


def metadata_json(entry: ClusterEntry, run: ClusterRun) -> str:
    return json.dumps(
        {
            "kind": METADATA_MARKER,
            "clusterUid": entry.uid,
            "event": entry.event,
            "predecessorUids": list(entry.predecessor_uids),
            "topTerms": list(entry.top_terms),
            "weeklySeries": dict(sorted(entry.weekly_series.items())),
            "firstSeen": entry.first_seen.isoformat() if entry.first_seen else None,
            "memberCount": entry.member_count,
            "runId": run.run_id,
            "runAsOf": run.as_of.isoformat() if run.as_of else None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def decode_metadata(summary: Any) -> dict | None:
    if not isinstance(summary, str) or not summary.lstrip().startswith("{"):
        return None
    try:
        parsed = json.loads(summary)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) and parsed.get("kind") == METADATA_MARKER else None


def readable_title(entry: ClusterEntry) -> str:
    return ", ".join(entry.top_terms[:TITLE_TERMS]) or entry.uid


def readable_description(entry: ClusterEntry) -> str:
    count = len(entry.member_item_ids) or entry.member_count
    terms = ", ".join(entry.top_terms)
    return f"Cluster of {count} items" + (f" about {terms}." if terms else ".")


def proposal_record(
    entry: ClusterEntry,
    run: ClusterRun,
    existing: Mapping[str, Any] | None,
    *,
    corpus_id: str,
    category_set_id: str | None,
    import_run_id: str,
    now: str,
) -> dict[str, Any]:
    """The proposal for one cluster of a run. Status, name, review fields and category key of an existing proposal stay."""
    kept = dict(existing or {})
    record = {
        "id": cluster_proposal_id(entry.uid),
        "categorySetId": kept.get("categorySetId") or category_set_id,
        "corpusId": corpus_id,
        "importRunId": import_run_id,
        "proposalKind": CLUSTER_KIND,
        "steeringDomain": CLUSTER_DOMAIN,
        "status": kept.get("status") or STATUS_PROPOSED,
        "title": kept.get("title") if kept.get("status") not in (None, STATUS_PROPOSED) else readable_title(entry),
        "summary": metadata_json(entry, run),
        "categoryKey": kept.get("categoryKey") or cluster_category_key(entry.uid),
        "graphEntityId": entry.uid,
        "displayName": kept.get("displayName"),
        "description": readable_description(entry),
        "evidenceItemIds": list(entry.member_item_ids),
        "sourceSnapshotId": run.run_id,
        "proposedAt": kept.get("proposedAt") or now,
        "reviewedAt": kept.get("reviewedAt"),
        "reviewedBy": kept.get("reviewedBy"),
        "updatedAt": now,
    }
    return {key: value for key, value in record.items() if value is not None or key in ("displayName", "reviewedAt", "reviewedBy")}


def cluster_from_proposal(proposal: Mapping[str, Any], category_names: Mapping[tuple[str, str], str]) -> Cluster | None:
    """The cluster a proposal row describes, or ``None`` for another kind, a rejected cluster or foreign figures."""
    if proposal.get("proposalKind") != CLUSTER_KIND or proposal.get("status") not in (STATUS_PROPOSED, STATUS_ACCEPTED):
        return None
    metadata = decode_metadata(proposal.get("summary"))
    if metadata is None:
        return None
    accepted = proposal.get("status") == STATUS_ACCEPTED
    name = None
    if accepted:
        name = category_names.get((str(proposal.get("categorySetId") or ""), str(proposal.get("categoryKey") or ""))) or proposal.get("displayName")
    series = metadata.get("weeklySeries")
    return Cluster(
        uid=str(metadata.get("clusterUid") or proposal.get("graphEntityId") or proposal["id"]),
        accepted=accepted,
        name=str(name).strip() if name and str(name).strip() else None,
        event=metadata.get("event"),
        top_terms=tuple(str(term) for term in metadata.get("topTerms") or ()),
        weekly_series={str(week): int(count) for week, count in series.items()} if isinstance(series, dict) else {},
        first_seen=metadata.get("firstSeen"),
        member_item_keys=tuple(str(item) for item in proposal.get("evidenceItemIds") or ()),
        member_count=int(metadata.get("memberCount") or 0),
        run_id=metadata.get("runId"),
        run_as_of=metadata.get("runAsOf"),
        category_key=proposal.get("categoryKey"),
    )
