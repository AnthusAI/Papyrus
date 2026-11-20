"""A blocked draft asks for help once (design section 13.3, change L).

When the checks on a Delivery's words fail, the Delivery is blocked (``Deliveries.block_draft``) and one review request, a flag, is raised for the editor. It is one for each
**Announcement**, not for each channel: its id is made from the Announcement's id, so a second channel's failed check, or the same check run again, finds the first flag.
A flag waits for nobody; the machine redrafts only when an input changes (the Story, the guidelines), never in a loop.

The Announcements list and the Story drawer read the flag with one get by that id: ``open_flag``. Nothing lists the review requests.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .deliveries import Deliveries
from .records import BLOCKED, CHECK_FAILED_CODE

FLAG_SUBJECT = "announcement"
FLAG_RAISER = "announce"
FLAG_PREFIX = "blocked-draft-"


def flag_id(announcement_id: str) -> str:
    """One flag for one Announcement."""
    return FLAG_PREFIX + hashlib.sha256(announcement_id.encode("utf-8")).hexdigest()[:24]


def block_and_flag(deliveries: Deliveries, row: Mapping[str, Any], *, problems: list[str], by: str, now: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Block a draft whose checks failed and raise the Announcement's flag. Returns the blocked Delivery and the flag (the first one, when it was raised already)."""
    from ..review_requests import raise_review

    note = "the checks on its words failed: " + "; ".join(problems) if problems else "the checks on its words failed"
    blocked = deliveries.block_draft(row, by=by, note=note, now=now)
    request = raise_review(
        deliveries.client, subject={"type": FLAG_SUBJECT, "id": row["announcementId"]}, mode="flag", raised_by=FLAG_RAISER, request_id=flag_id(row["announcementId"]),
        reason=f"A draft was blocked: {note}.", ask=f"{row['channel']} {row['accountId']}: the words did not pass their checks, so nothing will be sent. Look at the draft and decide what should go out.",
    )
    return blocked, request


def open_flag(client: Any, announcement_id: str) -> dict[str, Any] | None:
    """The Announcement's flag while it is open, from one get by its id; None when it was never raised or has been answered."""
    from ..review_requests import read_review

    row = client.get_record("ReviewRequest", flag_id(announcement_id))
    request = read_review(row) if row else None
    return request if request and request["state"] == "open" else None


def blocked_for_check(row: Mapping[str, Any]) -> bool:
    return row.get("state") == BLOCKED and row.get("blockedReason") == CHECK_FAILED_CODE
