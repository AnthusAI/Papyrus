"""Who counts as newsroom staff. ``admin`` has every editor right.

An admin who is not in the ``editor`` group (a site owner, say) can do everything an editor can, so every editor check
reads :data:`STAFF_GROUPS` through :func:`has_editor_rights` rather than comparing against ``"editor"`` alone. The
TypeScript twin is ``lib/staff-groups.ts``; the standalone Lambdas (proposal-actions, reader-steering) carry a copy of
:func:`claim_groups` and a test keeps the copies in step.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

STAFF_GROUPS = frozenset({"editor", "admin"})
_SEPARATORS = re.compile(r"[\s,]+")
_BRACKETS = "\"'[](){}"


def claim_groups(value: Any) -> list[str]:
    """Groups from a ``cognito:groups`` claim: a list, a JSON list, ``[a b]``, or ``a,b`` as the forwarder happened to send it."""
    if isinstance(value, (list, tuple, set, frozenset)):
        raw = [item for item in value if isinstance(item, str)]
    elif isinstance(value, str):
        raw = _SEPARATORS.split(value)
    else:
        return []
    cleaned = (item.strip().strip(_BRACKETS).strip() for item in raw)
    return [item for item in cleaned if item]


def has_editor_rights(groups: Iterable[Any] | str | None) -> bool:
    """True when any group is ``editor`` or ``admin`` (any case)."""
    return any(group.lower() in STAFF_GROUPS for group in claim_groups(groups))
