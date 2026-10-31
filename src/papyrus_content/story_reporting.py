"""The structure that ties reporting work to a story (an Item lineage).

A story keeps four kinds of reporting records, all addressed by its lineage id and none needing a new table:

* Draft versions: one ``Item`` row per version, ``<lineage>-v<n>``. The row whose ``versionState`` is ``current`` is the
  working record (saving a draft or publishing a version makes that row current); the published record is the one the
  lineage's ``PublishedItem`` points at. Neither is chosen by the highest ``versionNumber``.
* References: one ``SemanticRelation`` with predicate ``uses_evidence`` per story and reference, linked by lineage ids so it
  survives new versions of either side. Its metadata ``role`` says whether the story is ``based_on`` the reference (the
  reference it was made from, written by every path that makes a story from a reference), whether the reference was
  ``consulted`` during reporting, or is ``cited`` in the article. ``based_on`` is never downgraded by a later link.
* Messages: one ``MessageThread`` of kind ``story_reporting`` per story, anchored at the lineage, holding ordered
  ``Message`` rows with author, time and kind.
* Assignments: ``Assignment.itemLineageId`` (unchanged).

See docs/story-reporting.md for the agent workflow.
"""

from __future__ import annotations

import json
from typing import Any

from .content_item_lifecycle import CONTENT_ITEM_STAGES, require_content_item_stage
from .ids import hash_short, safe_id
from .publishing import (
    ItemFields,
    _derive_or_raise,
    _load_front_matter,
    _source_content_hash,
    _status_keys,
    _without_server_fields,
    columns_from_front_matter,
    published_item_id_for,
    utc_now_iso,
)
from .record_helpers import compact_dict, to_aws_json

STORY_THREAD_KIND = "story_reporting"
STORY_MESSAGE_KINDS = ("note", "research_packet", "reporting_context_packet", "draft_note", "editor_note")
STORY_REFERENCE_PREDICATE = "uses_evidence"
BASED_ON = "based_on"
STORY_REFERENCE_ROLES = ("consulted", "cited", BASED_ON)
STORY_REFERENCE_RELATION_FIELDS = {
    "relationTypeId": "semantic-relation-type-uses-evidence",
    "relationTypeKey": STORY_REFERENCE_PREDICATE,
    "relationDomain": "evidence",
}


def story_thread_id(lineage_id: str) -> str:
    return f"thread-story-{safe_id(lineage_id)}-{hash_short([lineage_id])[:8]}"


def story_anchor_key(lineage_id: str) -> str:
    return f"item#{lineage_id}"


def story_versions(client, lineage_id: str) -> list[dict[str, Any]]:
    """Every saved version of the story, newest first."""
    rows = client.list_by_index("itemsByLineageAndVersion", lineage_id)
    return sorted(rows, key=lambda row: int(row.get("versionNumber") or 0), reverse=True)


def _current_of(versions: list[dict[str, Any]]) -> dict[str, Any]:
    """The working record: the row marked current (the most recently touched one if a muddled lineage has several)."""
    pool = [row for row in versions if row.get("versionState") == "current"] or versions
    return max(pool, key=lambda row: (str(row.get("versionCreatedAt") or ""), int(row.get("versionNumber") or 0)))


def current_story_version(client, lineage_id: str) -> dict[str, Any]:
    """The working (latest draft) record of the story: the one marked current, not the highest version number."""
    versions = story_versions(client, lineage_id)
    if not versions:
        raise ValueError(f"No story found for lineage {lineage_id}.")
    return _current_of(versions)


def latest_story_version(client, lineage_id: str) -> dict[str, Any]:
    """The latest draft record. An alias of current_story_version; use published_story_version for the live text."""
    return current_story_version(client, lineage_id)


def published_story_version(client, lineage_id: str) -> dict[str, Any] | None:
    """The record whose text is live (the source of the lineage's PublishedItem), or None when it is not published."""
    published = client.get_record("PublishedItem", published_item_id_for(lineage_id))
    if published is None:
        return None
    source_id = published.get("sourceItemId")
    return next((row for row in story_versions(client, lineage_id) if row["id"] == source_id), None)


def plan_version_repair(client, lineage_id: str) -> list[dict[str, Any]]:
    """The record updates that renumber a muddled lineage by creation order and leave exactly one current record.

    Content is never touched. Records are ordered by ``createdAt`` (the server's creation time; ``id`` breaks ties),
    numbered 1..n, and chained through ``previousVersionId``. The current record is the live one when the story is
    published, otherwise the most recently created.
    """
    rows = client.list_by_index("itemsByLineageAndVersion", lineage_id)
    if not rows:
        raise ValueError(f"No story found for lineage {lineage_id}.")
    ordered = sorted(rows, key=lambda row: (str(row.get("createdAt") or ""), row["id"]))
    published = published_story_version(client, lineage_id)
    current_id = published["id"] if published else ordered[-1]["id"]
    updates = []
    for index, row in enumerate(ordered):
        wanted = {
            "versionNumber": index + 1,
            "versionState": "current" if row["id"] == current_id else "superseded",
            "previousVersionId": ordered[index - 1]["id"] if index else None,
        }
        changes = {key: value for key, value in wanted.items() if row.get(key) != value}
        if changes:
            updates.append({"id": row["id"], **changes})
    return updates


def repair_story_versions(client, lineage_id: str, *, apply: bool = False) -> list[dict[str, Any]]:
    """Plans (and with ``apply`` performs) plan_version_repair. Returns the planned updates."""
    updates = plan_version_repair(client, lineage_id)
    if apply:
        for update in updates:
            client.update_record("Item", update)
    return updates


def next_version_record_id(lineage_id: str, version_number: int, taken_ids: set[str]) -> str:
    """The record id for a new version: `<lineage>-v<n>`, skipping ids already used in the lineage.

    Ids written by other paths (for example a draft saved under a renamed slug) can already hold
    `<lineage>-v<n>` with a different version number, so the id is chosen to be free, not derived blindly.
    """
    suffix = version_number
    while f"{lineage_id}-v{suffix}" in taken_ids:
        suffix += 1
    return f"{lineage_id}-v{suffix}"


def save_story_version(
    client,
    lineage_id: str,
    *,
    front_matter_yaml: str | None,
    body_markus: str,
    actor: str,
    change_reason: str,
    now: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    """Records the next draft version of a story and marks the previous latest version superseded."""
    now = now or utc_now_iso()
    versions = story_versions(client, lineage_id)
    if not versions:
        raise ValueError(f"No story found for lineage {lineage_id}.")
    latest = _current_of(versions)
    next_number = max(int(row.get("versionNumber") or 1) for row in versions) + 1
    record_id = next_version_record_id(lineage_id, next_number, {row["id"] for row in versions})
    fields = ItemFields(
        type=latest["type"],
        slug=latest["slug"],
        section=latest.get("section"),
        front_matter_yaml=front_matter_yaml,
        body_markus=body_markus,
        aliases=list(latest.get("aliases") or []),
    )
    envelope = _derive_or_raise(fields.front_matter_yaml, fields.body_markus)
    columns = columns_from_front_matter(_load_front_matter(fields.front_matter_yaml))
    for key in ("title", "headline"):
        if not columns.get(key):
            carried = next((row.get(key) for row in versions if row.get(key)), None)
            if carried:
                columns[key] = carried
    metadata = json.loads(latest.get("metadata") or "{}") if isinstance(latest.get("metadata"), str) else dict(latest.get("metadata") or {})
    metadata["frontMatterYaml"] = fields.front_matter_yaml
    record = {
        **_without_server_fields(latest),
        **compact_dict(columns),
        "id": record_id,
        "lineageId": lineage_id,
        "versionNumber": next_number,
        "previousVersionId": latest["id"],
        "versionState": "current",
        "versionCreatedAt": now,
        "versionCreatedBy": actor,
        "changeReason": change_reason,
        "status": "draft",
        **_status_keys(fields.type, fields.section, "draft"),
        "bodyMarkus": fields.body_markus,
        "bodyIr": to_aws_json(envelope),
        "metadata": to_aws_json(metadata),
        "contentHash": _source_content_hash(fields),
        "publishedAt": None,
    }
    if stage:
        record["stage"] = require_content_item_stage(stage)
    client.create_record("Item", compact_dict(record))
    _carry_media_forward(client, record_id, envelope, versions)
    for row in versions:
        if row.get("versionState") == "current" or row["id"] == latest["id"]:
            client.update_record("Item", {"id": row["id"], "versionState": "superseded"})
    return record


def _carry_media_forward(client, new_item_id: str, envelope: dict[str, Any], earlier_versions: list[dict[str, Any]]) -> None:
    """Gives the new version the MediaAsset rows for the local images its body references.

    Media is keyed by item version id, so a saved version starts with none and would fail the publish check
    ``image-missing``. Each missing src is copied from the most recent earlier version that has a row for it.
    """
    from .markus_import import media_id_for

    wanted = []
    for image in (envelope.get("papyrus", {}).get("images") or {}).values():
        src = image.get("src") or ""
        if src and not src.startswith(("http://", "https://")) and src not in wanted:
            wanted.append(src)
    if not wanted:
        return

    def src_path_of(row: dict[str, Any]) -> str | None:
        metadata = row.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except ValueError:
                return None
        return (metadata or {}).get("srcPath")

    have = {src_path_of(row) for row in client.list_by_index("mediaAssetsByItemAndSortKey", new_item_id)}
    pending = [src for src in wanted if src not in have]
    for version in sorted(earlier_versions, key=lambda row: int(row.get("versionNumber") or 0), reverse=True):
        if not pending:
            break
        by_src = {src_path_of(row): row for row in client.list_by_index("mediaAssetsByItemAndSortKey", version["id"])}
        for src in [src for src in pending if src in by_src]:
            row = {k: v for k, v in _without_server_fields(by_src[src]).items()}
            row["id"] = media_id_for(new_item_id, src)
            row["itemId"] = new_item_id
            client.upsert("MediaAsset", row)
            pending.remove(src)


def create_story(client, *, title: str, section_key: str | None, stage: str = "idea", summary: str | None = None,
                 actor: str, now: str | None = None) -> dict[str, Any]:
    """Records a new story (the first Item of a new lineage) at the idea, assignment or reporting stage."""
    from .content_item_lifecycle import build_new_content_item_version, content_item_lineage_id_for_first_work
    from .records import apply_record_changes, build_record_changes

    if stage not in ("idea", "assignment", "reporting"):
        raise ValueError("stage must be idea, assignment or reporting.")
    if section_key and not client.get_record("NewsroomSection", section_key):
        raise ValueError(f"Unknown NewsroomSection {section_key}.")
    now = now or utc_now_iso()
    lineage_id = content_item_lineage_id_for_first_work(title=title, first_assignment_id=f"story-create-{now}")
    item = build_new_content_item_version(
        lineage_id=lineage_id, title=title, summary=summary or title, section_key=section_key, stage=stage, actor_label=actor, now=now
    )
    apply_record_changes(client, build_record_changes(client, [{"modelName": "Item", "expected": item}]))
    return item


def advance_stage(stage: str | None) -> str:
    """The stage after this one on the board, for stages before publication."""
    order = [name for name in CONTENT_ITEM_STAGES if name not in ("published", "held", "spiked")]
    current = stage or "idea"
    if current not in order:
        raise ValueError(f"Stage {current!r} has no next stage to advance to; pass --stage.")
    index = order.index(current)
    if index + 1 >= len(order):
        raise ValueError(f"Stage {current!r} is the last before publication; publish the story instead.")
    return order[index + 1]


STAGE_MOVES_KEY = "stageMoves"
MAX_STAGE_MOVES = 20


def move_story_stage(client, lineage_id: str, stage: str, *, actor: str, reason: str | None = None, now: str | None = None) -> dict[str, Any]:
    """Moves a story to a board stage (the Item stage update a card move makes). The move is recorded on the Item version's metadata (``stageMoves``), never as a Message."""
    require_content_item_stage(stage)
    latest = latest_story_version(client, lineage_id)
    previous = latest.get("stage") or "idea"
    if previous == stage:
        return {"changed": False, "stage": stage, "from": previous, "itemId": latest["id"]}
    now = now or utc_now_iso()
    # The stage changes in place on the version, so the version itself keeps who moved it, when and why (`stories show` lists them).
    metadata = json.loads(latest.get("metadata") or "{}") if isinstance(latest.get("metadata"), str) else dict(latest.get("metadata") or {})
    moves = [move for move in metadata.get(STAGE_MOVES_KEY) or [] if isinstance(move, dict)]
    moves.append({"at": now, "from": previous, "to": stage, "by": actor, "reason": reason})
    metadata[STAGE_MOVES_KEY] = moves[-MAX_STAGE_MOVES:]
    client.update_record("Item", {"id": latest["id"], "stage": stage, "updatedAt": now, "metadata": to_aws_json(metadata)})
    return {"changed": True, "stage": stage, "from": previous, "itemId": latest["id"]}


def story_reference_relation_id(lineage_id: str, reference_lineage_id: str) -> str:
    return "semantic-relation-" + hash_short(["story-reference", lineage_id, reference_lineage_id])


def current_reference(client, reference_id_or_lineage: str) -> dict[str, Any] | None:
    """A Reference by record id, or the current version of a reference lineage."""
    reference = client.get_record("Reference", reference_id_or_lineage)
    if reference is not None:
        return reference
    versions = client.list_by_index("referencesByLineageAndVersion", reference_id_or_lineage)
    current = [row for row in versions if row.get("versionState") == "current"] or versions
    return max(current, key=lambda row: int(row.get("versionNumber") or 0)) if current else None


def link_reference_to_story(
    client,
    lineage_id: str,
    reference_id: str,
    *,
    role: str,
    actor: str,
    note: str | None = None,
    citation_key: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Attaches a reference to a story, or changes its role (consulted to cited) when already attached."""
    if role not in STORY_REFERENCE_ROLES:
        raise ValueError(f"role must be one of {', '.join(STORY_REFERENCE_ROLES)}.")
    now = now or utc_now_iso()
    story = latest_story_version(client, lineage_id)
    reference = current_reference(client, reference_id)
    if reference is None:
        raise ValueError(f"Reference not found: {reference_id}")
    reference_lineage_id = reference.get("lineageId") or reference_id
    relation_id = story_reference_relation_id(lineage_id, reference_lineage_id)
    existing = client.get_record("SemanticRelation", relation_id)
    previous_metadata = {}
    if existing and isinstance(existing.get("metadata"), str):
        previous_metadata = json.loads(existing["metadata"] or "{}")
    if previous_metadata.get("role") == BASED_ON:
        role = BASED_ON  # the strongest statement about a reference is never weakened by a later citation
    metadata = {
        **previous_metadata,
        "kind": "story.reference",
        "role": role,
        "addedBy": previous_metadata.get("addedBy") or actor,
        "addedAt": previous_metadata.get("addedAt") or now,
        "updatedBy": actor,
        "updatedAt": now,
    }
    if note:
        metadata["note"] = note
    if citation_key:
        metadata["citationKey"] = citation_key
    subject_state_key = f"item#{lineage_id}#current"
    object_state_key = f"reference#{reference_lineage_id}#current"
    record = {
        "id": relation_id,
        "relationState": "current",
        "predicate": STORY_REFERENCE_PREDICATE,
        **STORY_REFERENCE_RELATION_FIELDS,
        "subjectKind": "item",
        "subjectId": story["id"],
        "subjectLineageId": lineage_id,
        "subjectVersionNumber": story.get("versionNumber"),
        "objectKind": "reference",
        "objectId": reference["id"],
        "objectLineageId": reference_lineage_id,
        "objectVersionNumber": reference.get("versionNumber"),
        "subjectStateKey": subject_state_key,
        "objectStateKey": object_state_key,
        "objectSubjectStateKey": f"{object_state_key}#item",
        "predicateObjectStateKey": f"{STORY_REFERENCE_PREDICATE}#{object_state_key}",
        "subjectVersionKey": f"item#{story['id']}",
        "objectVersionKey": f"reference#{reference['id']}",
        "score": 1,
        "rank": 1,
        "reviewRecommended": False,
        "importedAt": now,
        "metadata": json.dumps(metadata, sort_keys=True),
        "newsroomFeedKey": "story-references",
    }
    outcome = client.upsert("SemanticRelation", record)
    return {"relationId": relation_id, "role": role, "outcome": outcome, "referenceLineageId": reference_lineage_id}


def stories_based_on_reference(client, reference_lineage_id: str) -> list[dict[str, Any]]:
    """The stories (by lineage id) whose ``uses_evidence`` link names this reference, each with its role."""
    relations = client.list_semantic_relations_by_object_state(f"reference#{reference_lineage_id}#current")
    rows: list[dict[str, Any]] = []
    for relation in relations:
        if relation.get("predicate") != STORY_REFERENCE_PREDICATE or relation.get("subjectKind") != "item":
            continue
        metadata = json.loads(relation["metadata"]) if isinstance(relation.get("metadata"), str) and relation["metadata"] else {}
        rows.append({"relationId": relation["id"], "storyLineageId": relation.get("subjectLineageId"), "role": metadata.get("role", "consulted")})
    return rows


def story_references(client, lineage_id: str) -> list[dict[str, Any]]:
    """The references attached to the story, each with its role and who added it."""
    relations = client.list_by_index("semanticRelationsBySubjectState", f"item#{lineage_id}#current")
    rows: list[dict[str, Any]] = []
    for relation in relations:
        if relation.get("predicate") != STORY_REFERENCE_PREDICATE or relation.get("objectKind") != "reference":
            continue
        metadata = json.loads(relation["metadata"]) if isinstance(relation.get("metadata"), str) and relation["metadata"] else {}
        rows.append({
            "relationId": relation["id"],
            "referenceLineageId": relation.get("objectLineageId"),
            "role": metadata.get("role", "consulted"),
            "note": metadata.get("note"),
            "citationKey": metadata.get("citationKey"),
            "addedBy": metadata.get("addedBy"),
            "addedAt": metadata.get("addedAt"),
        })
    return rows


def ensure_story_thread(client, lineage_id: str, *, now: str) -> dict[str, Any]:
    thread_id = story_thread_id(lineage_id)
    existing = client.get_record("MessageThread", thread_id)
    if existing is not None:
        return existing
    story = latest_story_version(client, lineage_id)
    record = {
        "id": thread_id,
        "threadKind": STORY_THREAD_KIND,
        "status": "active",
        "title": story.get("headline") or story.get("title") or lineage_id,
        "primaryAnchorKind": "item",
        "primaryAnchorId": story["id"],
        "primaryAnchorLineageId": lineage_id,
        "primaryAnchorKey": story_anchor_key(lineage_id),
        "messageCount": 0,
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "messages",
    }
    client.create_record("MessageThread", record)
    return record


def append_story_message(
    client,
    lineage_id: str,
    *,
    body: str,
    summary: str,
    author_label: str,
    message_kind: str = "note",
    reference_lineage_id: str | None = None,
    version_number: int | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Adds one message, written by a person, to the story's reporting thread: ordered, time stamped and attributed.

    Messages come only from people, so the role is always ``human``. A bot or an agent never calls this."""
    if message_kind not in STORY_MESSAGE_KINDS:
        raise ValueError(f"message kind must be one of {', '.join(STORY_MESSAGE_KINDS)}.")
    now = now or utc_now_iso()
    thread = ensure_story_thread(client, lineage_id, now=now)
    sequence_number = int(thread.get("messageCount") or 0) + 1
    message_id = f"message-story-{safe_id(lineage_id)}-{sequence_number:05d}-{hash_short([lineage_id, sequence_number, now, body])[:8]}"
    metadata = {"kind": "story.message", "storyLineageId": lineage_id}
    if reference_lineage_id:
        metadata["referenceLineageId"] = reference_lineage_id
    if version_number is not None:
        metadata["versionNumber"] = version_number
    message = {
        "id": message_id,
        "messageKind": message_kind,
        "messageDomain": "newsroom",
        "status": "active",
        "summary": summary,
        "source": "newsroom",
        "authorLabel": author_label,
        "threadId": thread["id"],
        "sequenceNumber": sequence_number,
        "role": "human",
        "messageType": "text",
        "content": body,
        "responseTarget": "none",
        "responseStatus": "COMPLETED",
        "metadata": json.dumps(metadata, sort_keys=True),
        "createdAt": now,
        "updatedAt": now,
        "newsroomFeedKey": "messages",
    }
    client.create_record("Message", message)
    client.update_record("MessageThread", {"id": thread["id"], "messageCount": sequence_number, "lastMessageId": message_id, "lastMessageAt": now, "updatedAt": now})
    return message
