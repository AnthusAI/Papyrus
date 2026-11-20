"""What a handoff Assignment looks like as a row, with no imports: the change feed reads it in a small function (PPY-51f96f; the writer is ``agent_assignments.py``)."""
from __future__ import annotations

from typing import Any

TYPE_PREFIX = "responsibility."
OPEN, CLAIMED, COMPLETED, CANCELED, FAILED = "open", "claimed", "completed", "canceled", "failed"
FINAL = (COMPLETED, CANCELED, FAILED)


def type_key(responsibility: str) -> str:
    return f"{TYPE_PREFIX}{responsibility}"


def responsibility_of(row: dict[str, Any]) -> str | None:
    """The responsibility an Assignment asks for work from, or None when it is not a handoff (research, reindexing and the other kinds have their own executors)."""
    key = str(row.get("assignmentTypeKey") or "")
    return key[len(TYPE_PREFIX):] if key.startswith(TYPE_PREFIX) and len(key) > len(TYPE_PREFIX) else None
