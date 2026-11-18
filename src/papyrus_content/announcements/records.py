"""The shared vocabulary of the Announcement and Delivery records (docs/announcement-records.md).

An **Announcement** (model ``AnnouncementDecision``) is the decision to say something: a once-only key, the Stories it is about, and when Deliveries may go.
It knows nothing about channels and holds no approval. A **Delivery** is one channel's version of that decision: the words (files in S3), the account, the
approval, every wait as a named time, the attempts and the address of the result.

This module holds only what both stores and their callers share: the states, the ids, the time format, and the rule that decides a Delivery's one pending
time. It reads no backend.

The old X row shape (model ``Announcement``, ``store.py``) stays until the X rewire (PPY-efd06c) deletes it. That model keeps its deployed name, so the new
decision record has a name of its own.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from ..tenant_knowledge_keys import global_key, tenant_unique_id

DECISION_MODEL = "AnnouncementDecision"
DELIVERY_MODEL = "Delivery"

# Announcement states. ``planned``: decided, not yet released. ``released``: its time has come, so its Deliveries may go once each is approved.
# ``cancelled``: stopped before release. ``withdrawn``: every Delivery was withdrawn after release.
PLANNED, RELEASED, CANCELLED, WITHDRAWN = "planned", "released", "cancelled", "withdrawn"
ANNOUNCEMENT_STATES = (PLANNED, RELEASED, CANCELLED, WITHDRAWN)

# Delivery states. The first four are live (work may still happen); the rest are final until a person acts.
DRAFTED, READY, SENDING, BLOCKED = "drafted", "ready", "sending", "blocked"
SENT, FAILED, DRY_RUN, DELIVERY_WITHDRAWN, SUPERSEDED = "sent", "failed", "dry_run", "withdrawn", "superseded"
LIVE_STATES = (DRAFTED, READY, SENDING, BLOCKED)
DELIVERY_STATES = (*LIVE_STATES, SENT, FAILED, DRY_RUN, DELIVERY_WITHDRAWN, SUPERSEDED)
# A Delivery is waiting for its release time or its lock only while it is a draft or ready.
BEFORE_SEND_STATES = (DRAFTED, READY)

NONE, SOFT, HARD = "none", "soft", "hard"
APPROVALS = (NONE, SOFT, HARD)
AUTOMATIC, MANUAL = "automatic", "manual"
MODES = (AUTOMATIC, MANUAL)
RATE_LIMIT, BUDGET_CYCLE, RELEASE = "rate limit", "budget cycle", "release"
WAITING_FOR = (RATE_LIMIT, BUDGET_CYCLE, RELEASE)
# An attempt's outcome (the always-on standard's words, PPY-f58445). An attempt opens ``started`` and closes ``sent``, ``refused`` or ``unknown``; ``started`` and
# ``unknown`` are both open, and only settling (reading what the provider recorded) closes them.
STARTED, ATTEMPT_SENT, ATTEMPT_REFUSED, UNKNOWN = "started", "sent", "refused", "unknown"
ATTEMPT_OUTCOMES = (STARTED, ATTEMPT_SENT, ATTEMPT_REFUSED, UNKNOWN)
OPEN_OUTCOMES = (STARTED, UNKNOWN)
# The codes of a refusal that is a wait, not an answer: the next try is the next attempt.
PAUSED_CODE, BUDGET_REACHED_CODE, RATE_LIMIT_CODE = "paused", "budget reached", "rate limit"
SYSTEM = "system"   # who approved a Delivery whose approval is ``none``: the publication's policy did, and ``approvalPolicy`` says which

#: The one partition of the sparse due index: a Delivery carries it only while it has a pending time.
DUE_KEY = "due"
ANNOUNCES, SUPERSEDES = "announces", "supersedes"
ANNOUNCEMENT_KIND, DELIVERY_KIND = "announcement", "delivery"   # the relation ends' kinds
STORY_KIND = "item"

#: Fields no catalog row may carry: the words, the HTML or the Markus of a Delivery live in S3, never in DynamoDB.
TEXT_FIELDS = ("text", "body", "bodyMarkus", "bodyIr", "html", "markus", "markdown", "content", "post")


class RecordError(ValueError):
    """A record that breaks one of the rules above, said in plain words."""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc(value: Any) -> str | None:
    """A time as UTC text, ``2026-11-16T14:00:00Z``. A time with an offset is converted; a time with none is refused, so a local time is never read as UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip()
        moment = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
    if moment.tzinfo is None:
        raise RecordError(f"A time needs its offset, so it is never read as the wrong zone: {value!r}.")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:24]


def announcement_id(dedupe_key: str) -> str:
    """The Announcement's id is made from its once-only key, so creating it with a condition is what makes the decision once-only. It is a permanent id like
    any other: nothing ever changes it. A shared stack puts the tenant in front."""
    return tenant_unique_id(f"announcement-{_digest(dedupe_key)}")


def stored_dedupe_key(dedupe_key: str) -> str:
    """The key as the index stores it: unchanged on a dedicated stack, ``<tenant>#<key>`` on a shared one."""
    return global_key(dedupe_key)


def delivery_id(announcement: str, channel: str, account_id: str, generation: int) -> str:
    """One id for each Announcement, channel, account and generation. Generation 1 is the first Delivery; a correction is the next generation. Creating a
    Delivery with a condition on its id is what keeps one live Delivery per Announcement, channel and account."""
    return f"{announcement}#{channel}#{account_id}#g{generation}"


def attempt_log(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The Delivery's attempts, oldest first."""
    return json_list(row.get("attempts"))


def open_attempt_of(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The attempt that has no answer yet (``started`` or ``unknown``), or None. Only the last entry can be open: a new attempt opens only when the last is closed."""
    log = attempt_log(row)
    return log[-1] if log and log[-1].get("outcome") in OPEN_OUTCOMES else None


def account_key(channel: str, account_id: str) -> str:
    return f"{channel}#{account_id}"


def due_key() -> str:
    return global_key(DUE_KEY)


def story_published_key(lineage_id: str) -> str:
    return f"story-published:{lineage_id}"


def roundup_key(list_id: str, period: str) -> str:
    return f"roundup:{list_id}:{period}"


def correction_key(lineage_id: str, version_number: int) -> str:
    return f"correction:{lineage_id}:{version_number}"


def pending_times(row: Mapping[str, Any]) -> list[str]:
    """The times a Delivery is still waiting for.

    A draft or a ready Delivery waits for its release time and, until it is locked, for its lock time, until its first attempt opens: after that those times are
    used up, and only a named wait (a rate limit, a budget cycle) is pending. A Delivery that is live in any state waits for its next attempt time while one is set. A final Delivery, and a Delivery superseded or withdrawn, waits for nothing."""
    state = row.get("state")
    if state not in LIVE_STATES:
        return []
    times: list[str] = []
    if state in BEFORE_SEND_STATES and not attempt_log(row):
        times.append(row.get("releaseAt"))
        if not row.get("lockedAt"):
            times.append(row.get("lockAt"))
    times.append(row.get("nextAttemptAt"))
    return sorted(str(value) for value in times if value)


def due_at(row: Mapping[str, Any]) -> str | None:
    """The earliest pending time, or None when nothing is pending. It is the one time the schedule wakes the Delivery for, and the sort key of the sparse index."""
    times = pending_times(row)
    return times[0] if times else None


def with_due(row: Mapping[str, Any]) -> dict[str, Any]:
    """The row with ``dueAt`` and ``dueKey`` set from its pending times. With nothing pending both are absent, so the row is not in the sparse index."""
    result = {key: value for key, value in row.items() if key not in ("dueAt", "dueKey")}
    due = due_at(result)
    if due:
        result.update(dueAt=due, dueKey=due_key())
    return result


def require_catalog_only(row: Mapping[str, Any]) -> None:
    present = [name for name in TEXT_FIELDS if row.get(name) not in (None, "")]
    if present:
        raise RecordError(f"The catalog holds no text, so a row cannot carry {', '.join(present)}: the words are a file in S3 (a Delivery's text key and hash).")


# --- JSON fields and the history ----------------------------------------------------------------------------------------------------------------------


def json_list(value: Any) -> list[Any]:
    """A JSON field as a list: AppSync returns an AWSJSON field as text."""
    if isinstance(value, str):
        value = json.loads(value or "[]")
    return list(value) if isinstance(value, list) else []


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value or "{}")
    return dict(value) if isinstance(value, Mapping) else {}


def history_with(row: Mapping[str, Any], *, at: str, by: str, state: str | None, note: str) -> list[dict[str, Any]]:
    """The row's history with one line added: when, by whom, the state it was in and why. A history only grows."""
    return [*json_list(row.get("history")), {"at": at, "by": by, "state": state, "note": note}]


def stored(row: Mapping[str, Any], *, clearing: bool = False) -> dict[str, Any]:
    """The row as it is written: JSON fields as text. A value of None is left out of a create, so an absent key attribute keeps the row out of a sparse index;
    in an update (``clearing``) it is sent as an explicit null, which removes the attribute."""
    return {
        key: (json.dumps(value, sort_keys=True) if key in JSON_FIELDS and value is not None and not isinstance(value, str) else value)
        for key, value in row.items()
        if clearing or value is not None
    }


JSON_FIELDS = ("history", "attempts", "checks", "counts")
