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
