"""Wake keys: what a wake is about, written once so the same wake can never start a second run (PPY-70c6e8, slice A2).

Every wake that starts a procedure carries a key. The run record's id is derived from the key and the record is created
with a condition, so a wake delivered twice finds its record already there and does not run again.

* a change:   `<owner>|<subject id>|<subject version>|<what>`   (a Story at version 7 entered a stage)
* a timer:    `<owner>|schedule|<scheduled time>`
* a person:   `<owner>|manual|<request id>`                      (Run now, or a command-line run)

The owner is the automation's id; a start that no automation governs is owned by its procedure (`procedure:<key>`).
The key's meaning is its parts: nothing here guesses, truncates or defaults a part. See
docs/design/always-on-agents-architecture.md section 12 (slice A2).
"""
from __future__ import annotations

SEPARATOR = "|"
MAX_KEY_CHARACTERS = 1000
SCHEDULE, MANUAL, UNVERSIONED = "schedule", "manual", "unversioned"
PROCEDURE_OWNER_PREFIX = "procedure:"


class InvalidWakeKey(ValueError):
    """A wake key (or a part of one) the contract does not allow."""


def _part(name: str, value: object) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise InvalidWakeKey(f"a wake key needs {name}")
    if SEPARATOR in text:
        raise InvalidWakeKey(f"{name} must not contain {SEPARATOR!r}: {text!r}")
    return text


def owner(automation_id: str | None, procedure_key: str) -> str:
    """Who the wake belongs to: the automation, or, when no automation governs the start, the procedure itself."""
    return _part("an automation id", automation_id) if automation_id else PROCEDURE_OWNER_PREFIX + _part("a procedure key", procedure_key)


def change_key(owner_id: str, subject_id: str, subject_version: str | None, what: str) -> str:
    """A change to a record. A subject with no versions (a Reference) says so with `unversioned`."""
    return SEPARATOR.join([_part("an owner", owner_id), _part("a subject id", subject_id),
                           _part("a subject version", subject_version) if subject_version else UNVERSIONED, _part("what changed", what)])


def schedule_key(owner_id: str, scheduled_time: str) -> str:
    """A timer, named by the time it was scheduled for (not the time it fired), so a redelivered timer is the same wake."""
    return SEPARATOR.join([_part("an owner", owner_id), SCHEDULE, _part("a scheduled time", scheduled_time)])


def manual_key(owner_id: str, request_id: str) -> str:
    """A person's request, named by the request's own id."""
    return SEPARATOR.join([_part("an owner", owner_id), MANUAL, _part("a request id", request_id)])


def checked(key: object) -> str:
    """The key if it is a well-formed wake key, else InvalidWakeKey."""
    if not isinstance(key, str) or not key:
        raise InvalidWakeKey("a run needs a wake key (see docs/procedure-runner.md)")
    parts = key.split(SEPARATOR)
    if len(key) > MAX_KEY_CHARACTERS or len(parts) not in (3, 4) or any(not part.strip() for part in parts):
        raise InvalidWakeKey(f"{key!r} is not a wake key: <owner>|<subject>|<version>|<what>, <owner>|schedule|<time> or <owner>|manual|<request id>")
    if len(parts) == 3 and parts[1] not in (SCHEDULE, MANUAL):
        raise InvalidWakeKey(f"{key!r} is not a wake key: it has three parts, so its second part must be {SCHEDULE!r} or {MANUAL!r}")
    return key
