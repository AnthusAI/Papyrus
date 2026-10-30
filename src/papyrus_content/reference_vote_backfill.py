"""Copy each Reference's latest vote from its old ``reference_curation`` Message onto the Reference.

Before "Messages come only from people", every vote wrote a ``reference_curation`` Message with a ``comment`` relation to
the Reference; the details (actor kind, reason code, Section, shareable flag, delegation, decision relation) lived in the
Message's metadata. A Reference now keeps its latest vote on itself (``curationActorKind``, ``curationReasonCode``,
``curationSectionId``, ``curationShareable``, ``curationDelegation``, ``curationDecisionRelationId``; see ``reference_vote``).

This one-time backfill reads the newest curation Message of each current Reference that has no ``curationActorKind`` yet and
copies those details across. The old kinds map as follows: ``human``, ``cyclotron`` and ``rule`` stay; ``service`` and a
missing kind become ``agent`` (an unknown actor never trains the Cyclotron), unless ``--human-authors`` names the author
label of a person, in which case the vote is stamped ``human``. Only a person can say which author labels were people.

Writes by default; ``--dry-run`` prints the counts and writes nothing. Never run it without reading the dry-run counts first.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .model_attachments import download_attachment_buffer, parse_jsonish
from .reference_vote import ACTOR_KINDS, AGENT, HUMAN, vote_fields

CURATION_KIND = "reference_curation"


def message_metadata(client: Any, message: Mapping[str, Any]) -> dict[str, Any]:
    """A Message's metadata: its inline JSON, else its ``metadata`` attachment."""
    inline = parse_jsonish(message.get("metadata"))
    if isinstance(inline, dict) and inline:
        return inline
    for attachment in client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", message["id"]):
        if attachment.get("role") == "metadata":
            payload = parse_jsonish((download_attachment_buffer(client, attachment) or b"").decode("utf-8", "replace"))
            if isinstance(payload, dict):
                return payload
    return {}


def newest_curation_message(client: Any, lineage_id: str) -> tuple[Mapping[str, Any], dict[str, Any]] | None:
    """The reference's newest ``reference_curation`` Message and its metadata, or None."""
    found = []
    for relation in client.list_by_index("semanticRelationsByObjectState", f"reference#{lineage_id}#current"):
        if relation.get("predicate") != "comment" or relation.get("subjectKind") != "message" or relation.get("relationState") != "current":
            continue
        message = client.get_record("Message", relation["subjectId"])
        if message and message.get("messageKind") == CURATION_KIND:
            found.append((str(message.get("createdAt") or ""), message))
    if not found:
        return None
    message = max(found, key=lambda entry: entry[0])[1]
    return message, message_metadata(client, message)


def actor_kind_of(message: Mapping[str, Any], metadata: Mapping[str, Any], human_authors: Iterable[str]) -> str:
    kind = str(metadata.get("actorKind") or "").strip()
    if kind in ACTOR_KINDS and kind != AGENT:
        return kind
    if kind in ("", "service") and str(message.get("authorLabel") or "") in set(human_authors):
        return HUMAN
    return AGENT


def delegation_of(metadata: Mapping[str, Any]) -> dict[str, Any] | None:
    if metadata.get("attestation") != "delegated":
        return None
    return {"delegationId": metadata.get("delegationId"), "relayedBy": metadata.get("relayedBy"), "instruction": metadata.get("instruction")}


def plan_reference_update(reference: Mapping[str, Any], message: Mapping[str, Any], metadata: Mapping[str, Any],
                          human_authors: Sequence[str] = ()) -> dict[str, Any]:
    """The fields to write on a Reference that has no recorded vote, from the Message that recorded its latest one."""
    shareable = metadata.get("shareable")
    return {
        "id": reference["id"],
        **vote_fields(
            actor_kind_of(message, metadata, human_authors),
            reason_code=metadata.get("reasonCode") or metadata.get("curationReasonCode"),
            section_id=metadata.get("sectionId"),
            shareable=shareable if isinstance(shareable, bool) else None,
            delegation=delegation_of(metadata),
            decision_relation_id=metadata.get("decisionRelationId"),
        ),
    }


def run_backfill(client: Any, *, apply: bool, human_authors: Sequence[str] = ()) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    updates: list[dict[str, Any]] = []
    for reference in client.list_records("Reference"):
        if reference.get("versionState") not in (None, "current"):
            continue
        counts["scanned"] += 1
        if str(reference.get("curationActorKind") or "").strip():
            counts["alreadyRecorded"] += 1
            continue
        found = newest_curation_message(client, reference.get("lineageId") or reference["id"])
        if found is None:
            counts["noVote"] += 1
            continue
        update = plan_reference_update(reference, found[0], found[1], human_authors)
        kinds[update["curationActorKind"]] += 1
        counts["planned"] += 1
        updates.append(update)
    if apply:
        for update in updates:
            client.update_record("Reference", update)
    return {"dryRun": not apply, **{key: counts[key] for key in ("scanned", "alreadyRecorded", "noVote", "planned")},
            "written": len(updates) if apply else 0, "actorKinds": dict(kinds)}


def references_backfill_vote_details(flags: list[str]) -> None:
    """papyrus references backfill-vote-details [--human-authors <label,label,...>] [--dry-run]: copy each Reference's latest vote details from its old curation Message."""
    from .graphql_authoring import create_authoring_client
    from .options import parse_options, resolve_mutation_apply

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references backfill-vote-details")
    human_authors = [label.strip() for label in str(options.get("human-authors") or "").split(",") if label.strip()]
    client, _ = create_authoring_client()
    result = run_backfill(client, apply=apply, human_authors=human_authors)
    label = "references\tbackfill-vote-details"
    print(f"{label}\tmode\t{'apply' if apply else 'dry-run'}")
    for key in ("scanned", "alreadyRecorded", "noVote", "planned", "written"):
        print(f"{label}\t{key}\t{result.get(key, 0)}")
    for kind, count in sorted(result["actorKinds"].items()):
        print(f"{label}\tactor-kind\t{kind}\t{count}")
