"""The run ledger: one DynamoDB row per stage of an execution, keyed by publication and ISO week.

``publication`` is the partition key and ``runKey`` is ``<ISO week>#<execution>#<stage>``, so a week's history is one
Query. A stage that already succeeded in the same execution is skipped when Step Functions starts it again; a stage of
another execution of the same week always runs, because every stage is idempotent and a second run must refresh the site.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from typing import Any

LEDGER_TTL_DAYS = 400
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
RUN_TOTAL_STAGE = "run"


def run_key(week: str, execution: str, stage: str) -> str:
    return f"{week}#{execution}#{stage}"


def to_dynamo(value: Any) -> Any:
    """DynamoDB takes Decimal, not float: the ledger holds dollars and tokens."""
    return json.loads(json.dumps(value), parse_float=Decimal)


def from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: from_dynamo(item) for key, item in value.items()}
    if isinstance(value, list):
        return [from_dynamo(item) for item in value]
    return value


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
            ExpressionAttributeValues={":done": SUCCEEDED, ":now": _iso(self.clock()), ":details": to_dynamo(details or {})},
        )

    def fail(self, stage: str, error: str, cost: dict[str, Any] | None = None) -> None:
        """Record the failure. ``cost`` is what the attempts so far cost; a retry adds to it (``details.cost``)."""
        update = "SET #s = :failed, finishedAt = :now, #e = :error"
        values: dict[str, Any] = {":failed": FAILED, ":now": _iso(self.clock()), ":error": error[:1000]}
        if cost is not None:
            update += ", details = :details"
            values[":details"] = to_dynamo({"cost": cost})
        self.table.update_item(Key=self._key(stage), UpdateExpression=update, ExpressionAttributeNames={"#s": "status", "#e": "error"}, ExpressionAttributeValues=values)

    def cost(self, stage: str) -> dict[str, Any] | None:
        """The cost recorded by earlier failed attempts of this stage in this execution, if any."""
        item = self.table.get_item(Key=self._key(stage)).get("Item")
        cost = ((item or {}).get("details") or {}).get("cost")
        return from_dynamo(cost) if cost else None

    def rows(self) -> list[dict[str, Any]]:
        """Every stage row of this execution (not the run total)."""
        prefix = run_key(self.week, self.execution, "")
        return [row for row in query_rows(self.table, self.publication, prefix) if row.get("stage") != RUN_TOTAL_STAGE]

    def write_run_total(self, total: dict[str, Any]) -> None:
        """The run-level row, ``<week>#<execution>#run``: the sum of the stages' cost and the run's duration."""
        now = self.clock()
        self.table.put_item(Item=to_dynamo({
            **self._key(RUN_TOTAL_STAGE), "stage": RUN_TOTAL_STAGE, "week": self.week, "execution": self.execution, "status": total["status"],
            "finishedAt": _iso(now), "expiresAt": int((now + dt.timedelta(days=LEDGER_TTL_DAYS)).timestamp()), "details": {"cost": total},
        }))


def query_rows(table: Any, publication: str, prefix: str = "") -> list[dict[str, Any]]:
    """All rows of a publication whose runKey starts with ``prefix`` (numbers as int/float)."""
    from boto3.dynamodb.conditions import Key  # noqa: PLC0415

    condition = Key("publication").eq(publication) & Key("runKey").begins_with(prefix) if prefix else Key("publication").eq(publication)
    rows: list[dict[str, Any]] = []
    arguments: dict[str, Any] = {"KeyConditionExpression": condition}
    while True:
        page = table.query(**arguments)
        rows += [from_dynamo(item) for item in page.get("Items", [])]
        if not page.get("LastEvaluatedKey"):
            return rows
        arguments["ExclusiveStartKey"] = page["LastEvaluatedKey"]
