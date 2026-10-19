from __future__ import annotations

from collections import Counter
from typing import Any

from .graphql_authoring import PapyrusGraphQLAuthoringClient

OPERATIONAL_ASSIGNMENT_FEED_KEY = "operations"

AUTOMATIC_ASSIGNMENT_TYPE_KEYS = frozenset(
    {
        "analysis.reindex",
        "curation.reference-intake",
        "reference.corpus-accession",
        "reference.identifier-backfill",
        "reference.doi-backfill",
        "reference.text-extraction",
    }
)


def is_automatic_assignment(assignment: dict[str, Any]) -> bool:
    return assignment.get("assignmentTypeKey") in AUTOMATIC_ASSIGNMENT_TYPE_KEYS


def plan_automatic_assignment_cleanup(
    *,
    assignments: list[dict[str, Any]],
    assignment_events: list[dict[str, Any]],
    semantic_relations: list[dict[str, Any]],
) -> list[dict[str, str]]:
    automatic_assignments = [assignment for assignment in assignments if is_automatic_assignment(assignment)]
    automatic_assignment_ids = {assignment["id"] for assignment in automatic_assignments}
    deletions = [
        {
            "modelName": "Assignment",
            "id": assignment["id"],
            "assignmentTypeKey": assignment.get("assignmentTypeKey") or "unknown",
            "status": assignment.get("status") or "unknown",
            "title": assignment.get("title") or "",
        }
        for assignment in automatic_assignments
    ]
    deletions.extend(
        {"modelName": "AssignmentEvent", "id": event["id"]}
        for event in assignment_events
        if event.get("assignmentId") in automatic_assignment_ids
    )
    deletions.extend(
        {"modelName": "SemanticRelation", "id": relation["id"]}
        for relation in semantic_relations
        if relation.get("subjectKind") == "assignment" and relation.get("subjectId") in automatic_assignment_ids
    )
    return deletions


def apply_automatic_assignment_cleanup(
    client: PapyrusGraphQLAuthoringClient,
    deletions: list[dict[str, str]],
    *,
    actor_label: str,
) -> None:
    for deletion in deletions:
        client.delete_record(deletion["modelName"], deletion["id"])
    deleted_assignments = [deletion for deletion in deletions if deletion["modelName"] == "Assignment"]
    if not deleted_assignments:
        return
    client.update_newsroom_summary(
        {
            "source": "incremental",
            "countDeltas": {"assignments": -len(deleted_assignments)},
            "assignmentStatusDeltas": _negative_counts(deleted_assignments, "status"),
            "assignmentTypeDeltas": _negative_counts(deleted_assignments, "assignmentTypeKey"),
        },
        actor_label=actor_label,
        reason="assignments cleanup-automatic",
    )


def _negative_counts(rows: list[dict[str, str]], key: str) -> dict[str, int]:
    return {value: -count for value, count in Counter(row[key] for row in rows).items()}
