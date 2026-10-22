"""The run ledger: one DynamoDB row per stage of an execution, keyed by publication and ISO week.

``publication`` is the partition key and ``runKey`` is ``<ISO week>#<execution>#<stage>``, so a week's history is one
Query. A stage that already succeeded in the same execution is skipped when Step Functions starts it again; a stage of
another execution of the same week always runs, because every stage is idempotent and a second run must refresh the site.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

LEDGER_TTL_DAYS = 400
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"


def run_key(week: str, execution: str, stage: str) -> str:
    return f"{week}#{execution}#{stage}"


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RunLedger:
    def __init__(self, table: Any, publication: str, week: str, execution: str, *, clock=lambda: dt.datetime.now(dt.timezone.utc)) -> None:
        self.table = table
        self.publication = publication
        self.week = week
        self.execution = execution
        self.clock = clock

    def _key(self, stage: str) -> dict:
        return {"publication": self.publication, "runKey": run_key(self.week, self.execution, stage)}

    def status(self, stage: str) -> str | None:
        item = self.table.get_item(Key=self._key(stage)).get("Item")
        return item.get("status") if item else None

    def begin(self, stage: str) -> int:
        """Record that the stage started; returns the attempt number (1 for the first)."""
        now = self.clock()
        response = self.table.update_item(
            Key=self._key(stage),
            UpdateExpression="SET #s = :running, startedAt = :now, expiresAt = :ttl, week = :week, execution = :execution, stage = :stage "
            "ADD attempts :one REMOVE finishedAt, #e",
            ExpressionAttributeNames={"#s": "status", "#e": "error"},
            ExpressionAttributeValues={
                ":running": RUNNING,
                ":now": _iso(now),
                ":ttl": int((now + dt.timedelta(days=LEDGER_TTL_DAYS)).timestamp()),
                ":week": self.week,
                ":execution": self.execution,
                ":stage": stage,
                ":one": 1,
            },
            ReturnValues="UPDATED_NEW",
        )
        return int(response["Attributes"]["attempts"])

    def finish(self, stage: str, details: dict[str, Any] | None = None) -> None:
        self.table.update_item(
            Key=self._key(stage),
            UpdateExpression="SET #s = :done, finishedAt = :now, details = :details",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":done": SUCCEEDED, ":now": _iso(self.clock()), ":details": details or {}},
        )

    def fail(self, stage: str, error: str) -> None:
        self.table.update_item(
            Key=self._key(stage),
            UpdateExpression="SET #s = :failed, finishedAt = :now, #e = :error",
            ExpressionAttributeNames={"#s": "status", "#e": "error"},
            ExpressionAttributeValues={":failed": FAILED, ":now": _iso(self.clock()), ":error": error[:1000]},
        )
