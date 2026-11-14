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
    "reporting",
    "copywriting",
    "illustration",
    "typesetting",
    "published",
    "held",
    "spiked",
)
#: The stage a Story is in after `papyrus stories retire`: its page is down and its address redirects to another Story. Not a board column; it is the
#: same value `machine_writes.RETIRED_STAGE` gives an Item whose machine write was undone.
RETIRED_STAGE = "retired"
#: The key in a retired Story's head-row `metadata` that says where its address goes: `{"toLineageId", "liveItemId", "at", "by", "previousStage"}`.
#: Written by `papyrus stories retire`; read by the projection (`PublishedContentSource.retirement`) and by `stories retire --undo`.
RETIRED_INTO_KEY = "retiredInto"
LEGACY_CONTENT_ITEM_STAGE_REPLACEMENTS = {
    "research": "reporting",
    "report": "reporting",
    "editor_select": "reporting",
}
#: The stored type of a Story that has none yet. `Item.type` is required and `typeStatus` is a key (`<type>#<status>`), so "no type" is an explicit value
#: rather than a missing one; it is the same string in lib/content-item-lifecycle.ts. A Story of this type can be drafted and edited but not published.
UNTYPED_ITEM_TYPE = "untyped"
#: The Item types that are not Stories: the fixed system set, the same list as SYSTEM_ITEM_TYPES in lib/content-item-lifecycle.ts (change both).
#: Every other type is a Story type, so a site's own new type needs no engine change.
SYSTEM_ITEM_TYPES = ("wiki_page", "doctrine", "page", "sub-task")


def is_story_item_type(item_type: str | None) -> bool:
    """Every Item type outside the system set is a Story type."""
    return bool(item_type) and item_type not in SYSTEM_ITEM_TYPES


SUB_TASK_ITEM_TYPE = "sub-task"


def without_sub_tasks(rows):
    """The rows that are not checklist steps. A step is an Item of type ``sub-task`` (docs/story-procedure.md); every scan of the Item table that means
    Stories, pages or anything a reader or an editor lists leaves them out."""
    return [row for row in rows if row.get("type") != SUB_TASK_ITEM_TYPE]


def is_untyped(item_type: str | None) -> bool:
    return item_type == UNTYPED_ITEM_TYPE


#: The sparse attribute only the head row of a lineage carries (docs/plans/story-head-stage-index.md). It equals the row's stage (tenant-prefixed by
#: the authoring client on a tenant backend), so the index ``listItemsByHeadStageAndUpdatedAt`` holds one row per story. The same rule is
#: contentItemHeadStageKey in lib/content-item-lifecycle.ts.
HEAD_STAGE_KEY_FIELD = "headStageKey"


def head_stage_key(row: dict[str, Any]) -> str | None:
    """The head stage key a row should carry: its stage while it is the head of its lineage (any version state but ``superseded``: a story whose
    only row is a ``draft`` is still on the board), else None. A row with no stage (a sub-task, a doctrine page) is in no stage index."""
    if row.get("versionState") == "superseded":
        return None
    return str(row["stage"]) if row.get("stage") else None


def head_stage_fields(row: dict[str, Any], *, head: bool = True) -> dict[str, Any]:
    """The field to put in the create or update a writer already makes: ``{"headStageKey": stage}`` for the head row, ``{"headStageKey": None}`` for a
    row being superseded (an update with null removes the attribute, so the row leaves the index). ``row`` is the row as it will be after the write."""
    return {HEAD_STAGE_KEY_FIELD: head_stage_key(row) if head else None}


def with_stage(item: dict[str, Any], stage: str) -> dict[str, Any]:
    """The row with a new stage and the head stage key that goes with it."""
    moved = {**item, "stage": stage}
    return {**moved, **head_stage_fields(moved)}


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
    item_type: str | None = None,
) -> dict[str, Any]:
    section = section_key or None  # a story with no section stores none (a section is a topic, never a placeholder)
    from .story_types import type_for_new_story

    content_item_format = item_type or type_for_new_story()
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
        "slug": f"draft-{safe_id(section or 'unsectioned')}-{hash_short([lineage_id, 1, title])}",
        "shortSlug": None,
        "section": section,
        "sectionStatus": f"{section or ''}#draft",
        "title": title,
        "headline": title,
        "deck": summary,
        "body": [],
        "sortTitle": title,
        "pullQuotes": [],
        "layout": None,
        "updatedAt": now,
        HEAD_STAGE_KEY_FIELD: require_content_item_stage(stage),   # the first row of a lineage is its head
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


UNDRAFTED_BACKFILL_STAGES = ("report", "editor_select", "reporting")


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
            changes.append({"modelName": "Item", "current": item, "expected": with_stage(item, "assignment")})
    return changes


def plan_content_item_stage_migration(*, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Plan moving items off the retired research, report and editor_select stages onto reporting."""
    return [
        {
            "modelName": "Item",
            "current": item,
            "expected": with_stage(item, LEGACY_CONTENT_ITEM_STAGE_REPLACEMENTS[item["stage"]]),
        }
        for item in items
        if item.get("stage") in LEGACY_CONTENT_ITEM_STAGE_REPLACEMENTS
    ]


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
                {"modelName": "Item", "current": item, "expected": with_stage(item, stage_for_existing_item_without_stage(item))}
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
