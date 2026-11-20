"""The read side of the two relations (``links.py`` writes them): a Story's Announcements and an Announcement's Stories, each one indexed query.

It holds nothing that needs PyYAML, so the image service function, which does not carry it, can read where a Story was announced (``lines.py``). ``links.py`` writes the rows
and re-exports these names."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .records import ANNOUNCEMENT_KIND, ANNOUNCES, STORY_KIND

CURRENT = "current"
BY_OBJECT = "semanticRelationsByObjectState"
BY_SUBJECT = "semanticRelationsBySubjectState"


@dataclass(frozen=True)
class StoryRef:
    """A Story as an Announcement saw it: the lineage, the version row that was read and its number."""

    lineage_id: str
    item_id: str
    version_number: int


def announcements_of_story(client, lineage_id: str) -> list[dict[str, Any]]:
    """The ``announces`` links that point at a Story, from the object-state index: one indexed query, never a list of the table."""
    return client.list_by_index(BY_OBJECT, f"{STORY_KIND}#{lineage_id}#{CURRENT}", sort_eq=ANNOUNCES)


def stories_of_announcement(client, announcement_id: str) -> list[dict[str, Any]]:
    """The Stories an Announcement is about, from the subject-state index."""
    rows = client.list_by_index(BY_SUBJECT, f"{ANNOUNCEMENT_KIND}#{announcement_id}#{CURRENT}")
    return [row for row in rows if row.get("predicate") == ANNOUNCES]
