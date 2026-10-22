"""One-time EventBridge Scheduler schedules that start an approved send (``papyrus-nl-<siteId>-<issue8>``)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable

MINIMUM_LEAD_SECONDS = 2 * 60


def schedule_name(site_id: str, issue_id: str) -> str:
    return f"papyrus-nl-{site_id}-{issue_id[:8]}"


def effective_send_time(requested: float | None, now: float) -> tuple[float, bool]:
    """A send time less than two minutes ahead (or in the past, or missing) becomes now plus two minutes."""
    earliest = now + MINIMUM_LEAD_SECONDS
    if requested is None or requested < earliest:
        return earliest, True
    return requested, False


def at_expression(send_at: float) -> str:
    return "at(" + datetime.fromtimestamp(int(send_at), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ")"


class IssueScheduler:
    def __init__(self, *, function_arn: str, role_arn: str, client: Any = None) -> None:
        self.function_arn = function_arn
        self.role_arn = role_arn
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("scheduler")
        return self._client

    def _parameters(self, name: str, issue_id: str, send_at: float) -> dict[str, Any]:
        return {
            "Name": name,
            "ScheduleExpression": at_expression(send_at),
            "ScheduleExpressionTimezone": "UTC",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "ActionAfterCompletion": "DELETE",
            "State": "ENABLED",
            "Target": {
                "Arn": self.function_arn,
                "RoleArn": self.role_arn,
                "Input": json.dumps({"task": "start-send", "issueId": issue_id}),
            },
        }

    def upsert(self, name: str, issue_id: str, send_at: float) -> None:
        """Create the schedule, or update it when re-approving (a new time replaces the old)."""
        parameters = self._parameters(name, issue_id, send_at)
        try:
            self.client.create_schedule(**parameters)
        except self.client.exceptions.ConflictException:
            self.client.update_schedule(**parameters)

    def delete(self, name: str) -> None:
        try:
            self.client.delete_schedule(Name=name)
        except self.client.exceptions.ResourceNotFoundException:
            pass
