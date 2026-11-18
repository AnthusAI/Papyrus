"""What a Story loaded from a pod says about itself, kept apart from what the newsroom knows (PPY-50a7f5).

``papyrus pod load`` records a note's lifecycle keys on the Item's ``metadata.pod`` under the names the note uses (``rating``, ``reviewedBy``,
``reviewedOn``, ``reviewedHash``, ``spikedReason``, ``heldReason``, ``format``), beside the note's id and the commit it was loaded at. They are claims:
anyone can type them into a file. Nothing here is read by the publish gate, the checklist, ``publishRequiresRating`` or the announcement rule, which read
the newsroom's own records (a signed-in person's star rating, a review request a person answered). A person confirms once in the newsroom, and that
confirmation is the real record. This module only says what a claim is, in words, so every place that shows one says the same thing.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

POD_METADATA_KEY = "pod"
#: The lifecycle keys a pod note may carry that the Item has no column for. Same names as the note's keys and as the cloud's lifecycle fields.
CLAIM_KEYS = ("format", "rating", "reviewedBy", "reviewedOn", "reviewedHash", "spikedReason", "heldReason")
FIVE_STAR_CANDIDATE = "fiveStarCandidate"


def pod_record(item: Mapping[str, Any] | None) -> dict[str, Any]:
    """The ``metadata.pod`` object of an Item row, or an empty one for an Item that was not loaded from a pod."""
    metadata = (item or {}).get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata) if metadata.strip() else {}
        except ValueError:
            metadata = {}
    record = (metadata or {}).get(POD_METADATA_KEY) if isinstance(metadata, Mapping) else None
    return dict(record) if isinstance(record, Mapping) else {}


def claim_lines(item: Mapping[str, Any] | None) -> list[str]:
    """One plain line for each claim the Item carries from its pod. Empty for an Item that has none."""
    record = pod_record(item)
    lines: list[str] = []
    by = str(record.get("reviewedBy") or "").strip()
    on = str(record.get("reviewedOn") or "").strip()
    if by or on:
        lines.append(f"Recorded in the pod by {by or 'someone unnamed'}{' on ' + on if on else ''}, not verified")
    if record.get("rating") is not None:
        lines.append(f"Rated {record['rating']} in the pod, not verified")
    if record.get(FIVE_STAR_CANDIDATE):
        lines.append("Five-star candidate from the pod: a person confirms five stars in the newsroom")
    return lines
