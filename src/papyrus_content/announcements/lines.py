"""What the Story drawer and the Announcements list read (PPY-e4ae3a): one line for each Delivery, in words and marks, never colour alone.

Everything here is a read, and every read is an index or a get (``docs/announcement-records.md``):

* **A Story's Announcements** are read through the ``announces`` relation (``Announcements.for_story``): one query on the object-state index, then one Announcement get and
  one Deliveries query for each. The drawer shows one line for each live Delivery under the Announcement that decided it.
* **The list** reads the Announcements newest first from the planned-by-release-time index (one partition for each state, merged), each one's Deliveries from the
  Deliveries index, and what is overdue from the sparse due index. No table is listed and no subscription is open.

The words are said here once, so the console, ``papyrus announcements`` and the agents' tools show the same sentence; ``mark`` is the name of a Lucide icon, which the
console draws beside the words. The approval reads as ``review_policy.approval_label`` says it.

**Overdue** is a Delivery whose ``dueAt`` has passed and which has no attempt: the schedule did not wake it. **Outcome unknown** is a Delivery with an attempt that has no
answer (``started`` or ``unknown``): until Caducus's record settles it (``attempts.Attempts.settle``) the list says so, and no clock decides. The blocked-draft flag is
read once for each Announcement (``blocked_drafts.open_flag``).
"""
from __future__ import annotations

from typing import Any, Iterator, Mapping

from . import link_reads
from .attempts import shown
from .blocked_drafts import blocked_for_check, open_flag
from .decisions import Announcements
from .deliveries import Deliveries
from .records import (
    ANNOUNCEMENT_STATES, BLOCKED, DELIVERY_WITHDRAWN, DRAFTED, DRY_RUN, FAILED, LIVE_STATES, READY, SENDING, SENT, SUPERSEDED, attempt_log, open_attempt_of, utc,
)
from .approval_words import MARKS as APPROVAL_MARKS, approval_label

#: (Lucide icon, words) of each Delivery state.
STATE_SHOWN: dict[str, tuple[str, str]] = {
    DRAFTED: ("pencil-line", "Draft"),
    READY: ("calendar-check", "Ready"),
    SENDING: ("send", "Sending"),
    BLOCKED: ("ban", "Blocked"),
    SENT: ("circle-check", "Sent"),
    FAILED: ("circle-x", "Failed"),
    DRY_RUN: ("flask-conical", "Dry run: not sent"),
    DELIVERY_WITHDRAWN: ("undo-2", "Withdrawn"),
    SUPERSEDED: ("replace", "Superseded by a correction"),
}
OVERDUE_WORDS, OVERDUE_MARK = "Overdue", "clock-alert"
UNKNOWN_WORDS, UNKNOWN_MARK = "Outcome unknown", "circle-help"
FLAG_MARK = "flag"
#: A Delivery's review is shown while it can still go or has gone; not for one that never will.
REVIEW_SHOWN_IN = (*LIVE_STATES, SENT, FAILED)
CHECK_FAILED_WORDS, CHECK_FAILED_MARK = "The checks on its words failed", "shield-alert"
#: Every mark (a Lucide icon name) a line, an attention item or a flag can say; the console draws each one (``components/announcement-marks.tsx``).
MARKS = (*(mark for mark, _ in STATE_SHOWN.values()), OVERDUE_MARK, UNKNOWN_MARK, FLAG_MARK, CHECK_FAILED_MARK, *APPROVAL_MARKS)


def is_overdue(row: Mapping[str, Any], now: str) -> bool:
    """Due and untouched: the earliest pending time has passed (it is before now, not at it) and no attempt was ever opened."""
    return row.get("state") in LIVE_STATES and bool(row.get("dueAt")) and str(row["dueAt"]) < utc(now) and not attempt_log(row)


def delivery_line(row: Mapping[str, Any], now: str) -> dict[str, Any]:
    """One Delivery as one line: its state, its review, its waits, its attempts, and what needs a person's eye."""
    state = str(row.get("state"))
    mark, words = STATE_SHOWN.get(state, ("circle-dashed", state))
    if state == BLOCKED and row.get("blockedReason"):
        words = f"Blocked: {row['blockedReason']}"
    log = attempt_log(row)
    last = log[-1] if log else None
    attention: list[dict[str, str]] = []
    if is_overdue(row, now):
        attention.append({"kind": "overdue", "words": OVERDUE_WORDS, "mark": OVERDUE_MARK, "since": str(row["dueAt"])})
    unanswered = open_attempt_of(row)
    if unanswered is not None:
        attention.append({"kind": "outcome_unknown", "words": UNKNOWN_WORDS, "mark": UNKNOWN_MARK, "since": str(unanswered.get("at") or "")})
    if blocked_for_check(row):
        attention.append({"kind": "check_failed", "words": CHECK_FAILED_WORDS, "mark": CHECK_FAILED_MARK, "since": str(row.get("updatedAt") or "")})
    line: dict[str, Any] = {
        "id": row["id"], "announcementId": row["announcementId"], "channel": row["channel"], "accountId": row["accountId"], "generation": int(row.get("generation") or 1),
        "state": state, "words": words, "mark": mark,
        "approval": approval_label(row) if state in REVIEW_SHOWN_IN else None,
        "releaseAt": row.get("releaseAt"), "lockAt": row.get("lockAt"), "dueAt": row.get("dueAt"),
        "waitingFor": row.get("waitingFor"), "nextAttemptAt": row.get("nextAttemptAt"), "blockedReason": row.get("blockedReason"),
        "attempts": len(log), "lastAttempt": _attempt(last) if last else None,
        "resultUrl": row.get("resultUrl"), "attention": attention,
    }
    return line


def _attempt(entry: Mapping[str, Any]) -> dict[str, Any]:
    mark, words = shown(entry)
    return {"number": int(entry.get("number") or 0), "at": entry.get("at"), "outcome": entry["outcome"], "code": entry.get("code"), "words": words, "mark": mark}


def _flag(client: Any, announcement_id: str) -> dict[str, Any] | None:
    found = open_flag(client, announcement_id)
    if found is None:
        return None
    return {"id": found["id"], "words": "Review requested: a draft was blocked", "mark": FLAG_MARK, "reason": found["reason"], "ask": found.get("ask"), "raisedAt": found.get("raisedAt")}


def announcement_entry(client: Any, announcement: Mapping[str, Any], deliveries: list[dict[str, Any]], now: str, *, version_looked_at: int | None = None) -> dict[str, Any]:
    """An Announcement and one line for each of its live Deliveries, with its one blocked-draft flag when that is open. Lines come in channel order."""
    ordered = sorted(deliveries, key=lambda row: (str(row["channel"]), str(row["accountId"])))
    return {
        "id": announcement["id"], "kind": announcement["kind"], "state": announcement["state"], "releaseAt": announcement["releaseAt"], "trigger": announcement.get("trigger"),
        "createdBy": announcement.get("createdBy"), "versionLookedAt": version_looked_at,
        "reviewFlag": _flag(client, announcement["id"]) if any(blocked_for_check(row) for row in ordered) else None,
        "deliveries": [delivery_line(row, now) for row in ordered],
    }


def story_entries(client: Any, lineage_id: str, now: str) -> list[dict[str, Any]]:
    """Where a Story was announced: each Announcement that announces it, newest release first, one line for each live Delivery. Read through the relation."""
    found = Announcements(client).for_story(lineage_id)
    entries = [announcement_entry(client, item["announcement"], item["deliveries"], now, version_looked_at=item["versionLookedAt"]) for item in found]
    return sorted(entries, key=lambda entry: entry["releaseAt"], reverse=True)


# --- the list ---------------------------------------------------------------------------------------------------------------------------------------


def _newest_first(client: Any, before: str | None) -> Iterator[dict[str, Any]]:
    """Every Announcement newest release first: one partition of the planned-by-release-time index for each state, merged by release time, each read lazily one page at a
    time, so stopping early fetches nothing more. ``before`` starts below a release time, as a key condition on the index."""
    from heapq import merge

    streams = [client.iterate_newest_first("announcementDecisionsByState", state, sort_before=before) for state in ANNOUNCEMENT_STATES]
    yield from merge(*streams, key=lambda row: (str(row["releaseAt"]), str(row["id"])), reverse=True)


def _titles(client: Any, announcement_id: str) -> list[dict[str, Any]]:
    stories = []
    for link in link_reads.stories_of_announcement(client, announcement_id):
        item = client.get_record("Item", link["objectId"]) if link.get("objectId") else None
        stories.append({"lineageId": link["objectLineageId"], "title": str((item or {}).get("title") or link["objectLineageId"]), "versionLookedAt": link.get("objectVersionNumber")})
    return stories


def recent(client: Any, now: str, *, limit: int, before: str | None = None) -> dict[str, Any]:
    """The Announcements list: a page of Announcements newest first, and every Delivery that is overdue.

    ``limit`` is the size of a page, not a cap on what exists. A page ends where the release time changes, so Announcements released at the same moment (a roundup for
    each list) are never split between two pages. ``next`` is the release time of the last Announcement shown: ask for ``before`` it and the index starts below it; it is
    None on the last page. ``overdue`` is read from the sparse due index, so it holds only what is due and untouched, however old the Announcement."""
    deliveries = Deliveries(client)
    page: list[dict[str, Any]] = []
    more = False
    for row in _newest_first(client, before):
        if len(page) >= limit and str(row["releaseAt"]) != page[-1]["releaseAt"]:
            more = True
            break
        entry = announcement_entry(client, row, deliveries.live_for_announcement(row["id"]), now)
        entry["stories"] = _titles(client, row["id"])
        page.append(entry)
    overdue = [delivery_line(row, now) for row in deliveries.due(now) if is_overdue(row, now)]
    return {"announcements": page, "overdue": overdue, "next": page[-1]["releaseAt"] if more else None}
