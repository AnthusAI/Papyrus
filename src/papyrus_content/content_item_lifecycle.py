"""One content item, one lifecycle.

A content item is an Item lineage. It is created when work on a piece starts
and keeps its lineage id through research, reporting, editor selection,
copywriting and publication. The lifecycle stage lives on Item.stage; the copy
itself is versioned by Item.versionState as before. Research, reporting and
copywriting Assignments are work on the content item and carry its lineage id
in Assignment.itemLineageId. See docs/content-item-lifecycle.md.
"""

from __future__ import annotations

from typing import Any

from .ids import hash_short, safe_id

CONTENT_ITEM_STAGES = (
    "idea",
    "assignment",
    "research",
    "report",
    "editor_select",
    "copywriting",
    "illustration",
    "typesetting",
    "published",
)
DEFAULT_CONTENT_ITEM_FORMAT = "article"


def require_content_item_stage(stage: str) -> str:
    if stage not in CONTENT_ITEM_STAGES:
        raise ValueError(f"Unknown content item stage {stage!r}. Expected one of: {', '.join(CONTENT_ITEM_STAGES)}.")
    return stage


def content_item_lineage_id_for_first_work(*, title: str, first_assignment_id: str) -> str:
    return f"content-item-{safe_id(title)[:60]}-{hash_short([first_assignment_id])}"


def require_assignment_content_item_lineage_id(assignment: dict[str, Any]) -> str:
    lineage_id = assignment.get("itemLineageId")
    if not lineage_id:
        raise ValueError(
            f"Assignment {assignment.get('id')} has no itemLineageId. Every research, reporting and copywriting "
            "Assignment is work on one content item; create it with --content-item or let the create command mint one."
        )
    return lineage_id


def build_new_content_item_version(
    *,
    lineage_id: str,
    title: str,
    summary: str | None,
    section_key: str | None,
    stage: str,
    actor_label: str,
    now: str,
) -> dict[str, Any]:
    section = section_key or "unsectioned"
    content_item_format = DEFAULT_CONTENT_ITEM_FORMAT
    return {
        "id": f"{lineage_id}-v1",
        "lineageId": lineage_id,
        "versionNumber": 1,
        "previousVersionId": None,
        "versionState": "draft",
        "versionCreatedAt": now,
        "versionCreatedBy": actor_label,
        "changeReason": "content-item-created",
        "contentHash": hash_short([lineage_id, title, summary or ""]),
        "type": content_item_format,
        "status": "draft",
        "typeStatus": f"{content_item_format}#draft",
        "stage": require_content_item_stage(stage),
        "slug": f"draft-{safe_id(section)}-{hash_short([lineage_id, 1, title])}",
        "shortSlug": None,
        "section": section,
        "sectionStatus": f"{section}#draft",
        "title": title,
        "headline": title,
        "deck": summary,
        "body": [],
        "sortTitle": title,
        "pullQuotes": [],
        "layout": None,
        "updatedAt": now,
    }


def content_item_lineage_for_new_assignment(
    *,
    requested_lineage_id: str | None,
    assignment_id: str,
    title: str,
    summary: str | None,
    section_key: str | None,
    stage: str,
    actor_label: str,
    now: str,
) -> tuple[str, dict[str, Any] | None]:
    """Return the lineage the Assignment works on, plus the new content item version when one is minted."""
    if requested_lineage_id:
        return requested_lineage_id, None
    lineage_id = content_item_lineage_id_for_first_work(title=title, first_assignment_id=assignment_id)
    return lineage_id, build_new_content_item_version(
        lineage_id=lineage_id,
        title=title,
        summary=summary,
        section_key=section_key,
        stage=stage,
        actor_label=actor_label,
        now=now,
    )


def stage_for_existing_item_without_stage(item: dict[str, Any]) -> str:
    return "published" if item.get("status") == "published" else "copywriting"


UNDRAFTED_BACKFILL_STAGES = ("report", "editor_select")


def plan_undrafted_backfill_story_demotion(
    *,
    items: list[dict[str, Any]],
    reporting_assignments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Plan moving backfill-made placeholders from the story stages back to the assignment stage.

    An earlier backfill gave every undrafted reporting assignment its own content item at the report or
    editor_select stage. Such a placeholder is the first version of its lineage, still has an empty body, and carries
    the title of a reporting assignment that works on that lineage. Anything else is a real story and is left alone.
    """
    reporting_titles_by_lineage: dict[str, set[str]] = {}
    for assignment in reporting_assignments:
        lineage_id = assignment.get("itemLineageId")
        if lineage_id and assignment.get("title"):
            reporting_titles_by_lineage.setdefault(lineage_id, set()).add(assignment["title"])
    changes: list[dict[str, Any]] = []
    for item in items:
        lineage_id = item.get("lineageId") or item.get("id")
        is_unedited_placeholder = (
            item.get("stage") in UNDRAFTED_BACKFILL_STAGES
            and item.get("versionNumber") == 1
            and item.get("changeReason") == "content-item-created"
            and not item.get("body")
            and item.get("title") in reporting_titles_by_lineage.get(lineage_id, set())
        )
        if is_unedited_placeholder:
            changes.append({"modelName": "Item", "current": item, "expected": {**item, "stage": "assignment"}})
    return changes


def plan_content_item_backfill(
    *,
    items: list[dict[str, Any]],
    reporting_assignments: list[dict[str, Any]],
    copywriting_work: list[dict[str, Any]],
    actor_label: str,
    now: str,
) -> dict[str, Any]:
    """Plan the one-time move of existing records onto content item lineages.

    copywriting_work rows are {"assignment", "sourceReportingAssignmentId", "producedItemLineageIds"}.
    A reporting candidate whose copy was already drafted adopts that draft's lineage; any other reporting candidate
    gets a content item at the assignment stage, because no story exists yet. Copywriting work follows its draft, or else its
    reporting candidate.
    """
    changes: list[dict[str, Any]] = []
    warnings: list[str] = []
    for item in items:
        if not item.get("stage"):
            changes.append(
                {"modelName": "Item", "current": item, "expected": {**item, "stage": stage_for_existing_item_without_stage(item)}}
            )

    drafted_lineage_by_reporting_assignment: dict[str, str] = {}
    for work in copywriting_work:
        produced_lineage_ids = sorted(set(work.get("producedItemLineageIds") or []))
        source_reporting_assignment_id = work.get("sourceReportingAssignmentId")
        if not produced_lineage_ids or not source_reporting_assignment_id:
            continue
        adopted = drafted_lineage_by_reporting_assignment.setdefault(source_reporting_assignment_id, produced_lineage_ids[0])
        if len(produced_lineage_ids) > 1 or adopted != produced_lineage_ids[0]:
            warnings.append(
                f"Reporting assignment {source_reporting_assignment_id} produced more than one draft lineage; "
                f"{adopted} is the content item, merge or kill the others by hand."
            )

    lineage_by_reporting_assignment: dict[str, str] = {}
    for assignment in reporting_assignments:
        if assignment.get("itemLineageId"):
            lineage_by_reporting_assignment[assignment["id"]] = assignment["itemLineageId"]
            continue
        lineage_id = drafted_lineage_by_reporting_assignment.get(assignment["id"])
        if not lineage_id:
            lineage_id = content_item_lineage_id_for_first_work(
                title=assignment.get("title") or assignment["id"], first_assignment_id=assignment["id"]
            )
            changes.append(
                {
                    "modelName": "Item",
                    "current": None,
                    "expected": build_new_content_item_version(
                        lineage_id=lineage_id,
                        title=assignment.get("title") or assignment["id"],
                        summary=assignment.get("summary"),
                        section_key=assignment.get("sectionKey") or assignment.get("sectionId"),
                        stage="assignment",
                        actor_label=actor_label,
                        now=now,
                    ),
                }
            )
        lineage_by_reporting_assignment[assignment["id"]] = lineage_id
        changes.append(
            {"modelName": "Assignment", "current": assignment, "expected": {**assignment, "itemLineageId": lineage_id}}
        )

    for work in copywriting_work:
        assignment = work["assignment"]
        if assignment.get("itemLineageId"):
            continue
        produced_lineage_ids = sorted(set(work.get("producedItemLineageIds") or []))
        lineage_id = (produced_lineage_ids[0] if produced_lineage_ids else None) or lineage_by_reporting_assignment.get(
            work.get("sourceReportingAssignmentId") or ""
        )
        if not lineage_id:
            warnings.append(f"Copywriting assignment {assignment['id']} has no draft and no reporting candidate; left unlinked.")
            continue
        changes.append(
            {"modelName": "Assignment", "current": assignment, "expected": {**assignment, "itemLineageId": lineage_id}}
        )
    return {"changes": changes, "warnings": warnings}
