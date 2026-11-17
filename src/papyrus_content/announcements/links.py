"""The two relations of the Announcement and Delivery records, written as ``SemanticRelation`` rows (the relation types are in
``data/corpora/papyrus-semantic-relation-types.yml``).

``announces``: an Announcement to each Story it is about, with the version of the Story that was looked at. Read from the Story, the relation lists that
Story's Announcements through the object-state index in one query. Read from the Announcement, the subject-state index lists its Stories.

``supersedes``: a Delivery to the Delivery it corrects.

One row for each pair, with a deterministic id, so writing a link again changes nothing. A link is always ``current``; the records themselves carry the state.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..ids import hash_short
from ..reference_links import relation_state_keys
from ..relation_types import semantic_relation_type_fields_for_predicate
from .records import ANNOUNCEMENT_KIND, ANNOUNCES, DELIVERY_KIND, STORY_KIND, SUPERSEDES

MODEL = "SemanticRelation"
CURRENT = "current"
BY_OBJECT = "semanticRelationsByObjectState"
BY_SUBJECT = "semanticRelationsBySubjectState"


@dataclass(frozen=True)
class StoryRef:
    """A Story as an Announcement saw it: the lineage, the version row that was read and its number."""

    lineage_id: str
    item_id: str
    version_number: int


def link_id(predicate: str, subject_id: str, object_lineage_id: str) -> str:
    return f"announcement-link-{predicate}-{hash_short([subject_id, object_lineage_id])}"


def _row(predicate: str, *, subject: tuple[str, str], object_: tuple[str, str, str, int | None], now: str, note: str) -> dict[str, Any]:
    subject_kind, subject_id = subject
    object_kind, object_id, object_lineage, object_version = object_
    return {
        "id": link_id(predicate, subject_id, object_lineage),
        "relationState": CURRENT,
        "predicate": predicate,
        **semantic_relation_type_fields_for_predicate(predicate),
        "subjectKind": subject_kind,
        "subjectId": subject_id,
        "subjectLineageId": subject_id,
        "objectKind": object_kind,
        "objectId": object_id,
        "objectLineageId": object_lineage,
        "objectVersionNumber": object_version,
        **relation_state_keys(subject_kind, subject_id, object_kind, object_lineage, predicate, CURRENT),
        "subjectVersionKey": f"{subject_kind}#{subject_id}",
        "objectVersionKey": f"{object_kind}#{object_id}",
        "score": 1,   # sorts an index on this model, and DynamoDB refuses a null index key
        "rank": 1,
        "reviewRecommended": False,
        "importedAt": now,
        "updatedAt": now,
        "metadata": json.dumps({"kind": f"{predicate}.link", "note": note}, sort_keys=True),
    }


def announces(client, announcement_id: str, story: StoryRef, *, now: str) -> dict[str, Any]:
    """Link an Announcement to a Story at the version looked at. Looking again at a newer version updates the same row."""
    row = _row(ANNOUNCES, subject=(ANNOUNCEMENT_KIND, announcement_id), object_=(STORY_KIND, story.item_id, story.lineage_id, story.version_number), now=now,
               note=f"looked at version {story.version_number}")
    client.upsert(MODEL, row)
    return row


def supersedes(client, new_delivery_id: str, old_delivery_id: str, *, now: str) -> dict[str, Any]:
    row = _row(SUPERSEDES, subject=(DELIVERY_KIND, new_delivery_id), object_=(DELIVERY_KIND, old_delivery_id, old_delivery_id, None), now=now, note="a correction")
    client.upsert(MODEL, row)
    return row


def announcements_of_story(client, lineage_id: str) -> list[dict[str, Any]]:
    """The ``announces`` links that point at a Story, from the object-state index: one indexed query, never a list of the table."""
    return client.list_by_index(BY_OBJECT, f"{STORY_KIND}#{lineage_id}#{CURRENT}", sort_eq=ANNOUNCES)


def stories_of_announcement(client, announcement_id: str) -> list[dict[str, Any]]:
    """The Stories an Announcement is about, from the subject-state index."""
    rows = client.list_by_index(BY_SUBJECT, f"{ANNOUNCEMENT_KIND}#{announcement_id}#{CURRENT}")
    return [row for row in rows if row.get("predicate") == ANNOUNCES]
