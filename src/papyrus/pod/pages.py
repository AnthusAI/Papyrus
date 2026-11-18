"""Which notes of a pod are built into a site as pages.

One rule, so every command that builds or lists pages agrees. A note with a ``stage`` is built only at ``published``; a note with no stage is built unless
``draft: true``. An Announcement and a Delivery are never pages whatever else they say: they record what was said and where, their words are the body, outside
the graph, and nothing builds them into a site. A plain note with no type follows the same lifecycle rule.
"""
from __future__ import annotations

from .notes import Note
from .profile import CLASS_PREFIX, NEVER_PAGES


def class_of(note: Note) -> str | None:
    value = (note.front or {}).get("type")
    return value[len(CLASS_PREFIX):] if isinstance(value, str) and value.startswith(CLASS_PREFIX) else None


def is_page(note: Note) -> bool:
    if note.problem or class_of(note) in NEVER_PAGES:
        return False
    front = note.front or {}
    if "stage" in front:
        return front["stage"] == "published"
    return front.get("draft") is not True


def pages(notes: list[Note]) -> list[Note]:
    return [note for note in notes if is_page(note)]
