"""Read a pod's Announcement and Delivery notes into the records a load writes (``papyrus_content.announcements.pod_history``).

A load refuses a pod that does not check, so every link here already names one typed note of the right class and every attempt line is well formed. The Stories an
Announcement is about are notes of the pod that a load of Stories makes into newsroom items; their references come from that load, by the note's permanent id.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from papyrus_content.announcements.links import StoryRef
from papyrus_content.announcements.pod_history import HistoricAnnouncement, HistoricAttempt, HistoricDelivery
from papyrus_content.operator_errors import OperatorError

from . import attempts as attempt_lines
from .check import check_pod
from .notes import Note, link_name, name_index, walk


def read(pod: Path, stories: Mapping[str, StoryRef]) -> list[HistoricAnnouncement]:
    """The pod's Announcement notes with their Delivery notes. ``stories`` gives the newsroom's reference to each Story note, by the note's permanent id."""
    report = check_pod(pod)
    if report.problems:
        raise OperatorError(f"{pod} does not pass `papyrus pod check` ({len(report.problems)} problems, the first: {report.problems[0].path}: {report.problems[0].message}). Nothing was read.")
    notes = walk(pod)
    index = name_index(notes)
    announcements = [note for note in notes if (note.front or {}).get("type") == "papyrus:Announcement"]
    deliveries = [note for note in notes if (note.front or {}).get("type") == "papyrus:Delivery"]
    found = []
    for announcement in announcements:
        front = announcement.front or {}
        refs = []
        for link in _links(front.get("announces")):
            story = _target(index, link)
            ref = stories.get(str((story.front or {}).get("id")))
            if ref is None:
                raise OperatorError(f"{announcement.path} announces {story.path}, which has not been loaded as a Story, so the newsroom has no version of it to record. Nothing was read.")
            refs.append(ref)
        own = [note for note in deliveries if _target(index, link_name(note.front.get("announcement"))) is announcement]
        found.append(HistoricAnnouncement(
            note_id=front["id"], kind=front["kind"], state=front["state"], stories=tuple(refs), deliveries=tuple(_delivery(note, index) for note in own),
            release_at=front.get("releaseAt"),
        ))
    return found


def _links(value: object) -> list[str]:
    return [name for item in (value if isinstance(value, list) else [value]) if (name := link_name(item))]


def _target(index: Mapping[str, list[Note]], name: str | None) -> Note:
    candidates = index[name or ""]
    exact = [note for note in candidates if note.path.removesuffix(".md") == name]
    return (exact or candidates)[0]


def _delivery(note: Note, index: Mapping[str, list[Note]]) -> HistoricDelivery:
    front = note.front or {}
    attempts = []
    for position, line in enumerate(front.get("attempts", []), 1):
        attempt, _ = attempt_lines.parse(line, position)
        attempts.append(HistoricAttempt(attempt.number, attempt.at, attempt.outcome, attempt.by, attempt.code))
    older = _links(front.get("supersedes"))
    return HistoricDelivery(
        note_id=front["id"], channel=front["channel"], account=front["account"], state=front["state"], text=note.body.strip("\n"), attempts=tuple(attempts),
        result_url=front.get("resultUrl"), supersedes=(_target(index, older[0]).front or {})["id"] if older else None,
    )
