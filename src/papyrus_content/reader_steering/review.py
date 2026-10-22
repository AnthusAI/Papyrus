"""The asynchronous review step of the ``reader-snapshot`` run: signals on new submissions.

A new submission is public at once; this step runs after the request, in the worker, so nothing here can slow or block a
reader's submit. Entity extraction is a later step of the same worker (the knowledge-base lead owns it): a submission waits
in ``extractionState: "pending"`` and this step leaves that state alone.

``signals`` is stored as a JSON string, because the Amplify ``a.json()`` field is an AWSJSON scalar.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .signals import submission_signals

REVIEW_BATCH = 50


@dataclass
class ReviewReport:
    submissions: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        return {"submissions": self.submissions, "error": self.error}


def parsed_signals(value: Any) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return [signal for signal in value if isinstance(signal, dict)] if isinstance(value, list) else []


def review_submissions(
    resource: Any,
    submission_table: str,
    submissions: list[Mapping],
    *,
    now_iso: str,
    signals: Callable[..., list[dict]] = submission_signals,
    limit: int = REVIEW_BATCH,
) -> int:
    """Adds ``signals`` and ``reviewedAt`` to up to ``limit`` submissions that have not been reviewed. Returns how many."""
    table = resource.Table(submission_table)
    reviewed = 0
    for submission in sorted(submissions, key=lambda row: row["createdAt"]):
        if submission.get("reviewedAt") or reviewed >= limit:
            continue
        found = signals(submission["title"], submission.get("note"), submission["canonicalUrl"])
        table.update_item(
            Key={"id": submission["id"]},
            UpdateExpression="SET signals = :signals, reviewedAt = :now, updatedAt = :now",
            ConditionExpression="attribute_exists(id)",
            ExpressionAttributeValues={":signals": json.dumps(found, separators=(",", ":")), ":now": now_iso},
        )
        reviewed += 1
    return reviewed
