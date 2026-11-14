"""proposal-actions: the Proposals queue every newsroom backend has (editors and operators only).

Behind ``fileProposal``, ``transitionProposal``, ``editProposal`` and ``listStoryDrafts``. The rules are the stdlib module
``proposals.py`` beside this file; this file is the DynamoDB store and the AppSync entry point. The ``Proposal`` table is the
Amplify model table written directly, so editors can list it through the data API. Reader votes on proposals and the public
files belong to the reader-steering plugin, which reads this same table.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

_FUNCTION_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if _FUNCTION_DIRECTORY not in sys.path:  # a Lambda already has its code directory on the path; a test loading this file by path does not
    sys.path.insert(0, _FUNCTION_DIRECTORY)
import proposals as proposal_rules  # noqa: E402

PROPOSAL_TABLE_ENV = "PAPYRUS_PROPOSAL_TABLE"


def iso(now_seconds: float) -> str:
    """UTC with milliseconds, so rows written in the same second still sort in the order they were written."""
    moment = datetime.fromtimestamp(now_seconds, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


def _without_none(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None}


def is_conditional_failure(error: Exception) -> bool:
    return str(getattr(error, "response", {}).get("Error", {}).get("Code", "")) == "ConditionalCheckFailedException"


class DynamoProposalStore:
    """The ``Proposal`` model table written directly: items carry ``__typename`` and ``updatedAt`` so staff can list them."""

    def __init__(self, *, resource: Any, proposal_table: str) -> None:
        self._table = resource.Table(proposal_table)

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        item = self._table.get_item(Key={"id": proposal_id}, ConsistentRead=True).get("Item")
        return plain(item) if item else None

    def create_proposal(self, row: dict[str, Any]) -> bool:
        item = {**_without_none(row), "__typename": "Proposal", "updatedAt": row["createdAt"]}
        try:
            self._table.put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
        except Exception as error:
            if is_conditional_failure(error):
                return False
            raise
        return True

    def list_story_drafts(self, limit: int) -> list[dict[str, Any]]:
        """The story drafts of the table, only the fields ``listStoryDrafts`` may answer; at most ``limit`` (the newest if there are more)."""
        fields = proposal_rules.STORY_DRAFT_FIELDS
        names = {"#kind": "kind", **{f"#f{index}": field for index, field in enumerate(fields)}}
        request: dict[str, Any] = {
            "FilterExpression": "#kind = :kind",
            "ProjectionExpression": ", ".join(f"#f{index}" for index in range(len(fields))) + ", #kind",
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": {":kind": "story_draft"},
        }
        rows: list[dict[str, Any]] = []
        while True:
            page = self._table.scan(**request)
            rows.extend(plain(item) for item in page.get("Items") or [])
            if not page.get("LastEvaluatedKey"):
                break
            request["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        rows.sort(key=lambda row: (row.get("createdAt") or "", row.get("id") or ""), reverse=True)
        return [{field: row.get(field) for field in fields} for row in rows[:limit]]

    def change_proposal(self, proposal_id: str, changes: dict[str, Any], expected_state: str, now_iso: str, *, expected_updated_at: str | None = None) -> bool:
        """Apply ``changes`` if the state (and, when given, ``updatedAt``) is still what the caller saw; a value of ``None`` removes the attribute."""
        names = {"#st": "state", "#u": "updatedAt", **{f"#c{index}": key for index, key in enumerate(changes)}}
        sets = ", ".join(f"#c{index} = :c{index}" for index, value in enumerate(changes.values()) if value is not None)
        removes = ", ".join(f"#c{index}" for index, value in enumerate(changes.values()) if value is None)
        values = {":expected": expected_state, ":now": now_iso, **{f":c{index}": value for index, value in enumerate(changes.values()) if value is not None}}
        condition = "#st = :expected"
        if expected_updated_at is not None:
            condition += " AND #u = :seen"
            values[":seen"] = expected_updated_at
        expression = f"SET {sets + ', ' if sets else ''}#u = :now" + (f" REMOVE {removes}" if removes else "")
        try:
            self._table.update_item(
                Key={"id": proposal_id},
                UpdateExpression=expression,
                ConditionExpression=condition,
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
        except Exception as error:
            if is_conditional_failure(error):
                return False
            raise
        return True


def store_from_environment(environment: dict[str, str] | None = None) -> DynamoProposalStore:
    import boto3

    environment = os.environ if environment is None else environment
    return DynamoProposalStore(resource=boto3.resource("dynamodb"), proposal_table=environment[PROPOSAL_TABLE_ENV])


def function_account(context: Any) -> str | None:
    """The AWS account this function runs in, from its own ARN: the only account whose IAM operators may file proposals."""
    parts = str(getattr(context, "invoked_function_arn", None) or "").split(":")
    return parts[4] if len(parts) > 4 and parts[4] else None


def handle_event(event: dict[str, Any], *, store: Any, now_seconds: float, account_id: str | None = None) -> dict[str, Any]:
    """Route an AppSync invocation to the proposal rules. Answers a receipt, never an exception."""
    if proposal_rules.event_field_name(event) in proposal_rules.QUERIES:
        return proposal_rules.handle_proposal_query(event, store, account_id=account_id)
    return proposal_rules.handle_proposal_event(event, store, now_iso=iso(now_seconds), account_id=account_id)


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    return handle_event(event, store=store_from_environment(), now_seconds=time.time(), account_id=function_account(_context))
