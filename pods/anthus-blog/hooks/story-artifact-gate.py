#!/usr/bin/env python3
"""Fail-closed artifact gates for Anth.us newsroom story transitions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

STORY_WORKFLOW: dict[str, list[str]] = {
    "idea": ["assignment"],
    "assignment": ["research", "idea"],
    "research": ["report", "assignment"],
    "report": ["editor_select", "research"],
    "editor_select": ["copywriting", "research"],
    "copywriting": ["published", "copywriting"],
    "published": ["copywriting"],
}

ARTIFACT_FOR_TARGET: dict[str, str] = {
    "assignment": "idea.md",
    "research": "assignment.md",
    "report": "research.md",
    "editor_select": "report.md",
    "copywriting": "editor_select.md",
    "published": "article.md",
}

SKIP_AHEAD_COACHING: dict[tuple[str, str], str] = {
    ("idea", "research"): (
        "Assignment captures the editorial charter before research begins. "
        "Advance idea → assignment → research."
    ),
    ("idea", "report"): (
        "Reporting requires assignment and research first. "
        "Walk the ladder: idea → assignment → research → report."
    ),
    ("idea", "editor_select"): (
        "Editor selection happens after a private report exists. "
        "Complete assignment, research, and report first."
    ),
    ("idea", "copywriting"): (
        "Copywriting requires a private report and editor selection. "
        "Walk the ladder: idea → assignment → research → report → editor select → copywriting."
    ),
    ("idea", "published"): (
        "Publication requires reader-facing copy. Finish every earlier stage first."
    ),
    ("assignment", "report"): (
        "Research notes belong in research.md before the report stage."
    ),
    ("assignment", "editor_select"): (
        "Editor selection requires a completed private report."
    ),
    ("assignment", "copywriting"): (
        "Copywriting starts only after editor selection from the private report."
    ),
    ("research", "editor_select"): (
        "Finish the private report before editor selection."
    ),
    ("research", "copywriting"): (
        "Editors select from the private report before copywriting starts."
    ),
    ("report", "copywriting"): (
        "Editor selection records which angle proceeds to copywriting. "
        "Advance report → editor select → copywriting."
    ),
}


def _story_workspace(root: Path, story_id: str) -> Path:
    return root / "stories" / story_id


def _artifact_ready(path: Path) -> bool:
    return path.is_file() and path.read_text(encoding="utf-8").strip() != ""


def main() -> int:
    payload = json.load(sys.stdin)
    operation = payload.get("operation") or {}
    before_issue = operation.get("before_issue") or {}
    target_status = operation.get("status")
    story_id = operation.get("identifier") or before_issue.get("id")

    if before_issue.get("type") != "story" or not target_status or not story_id:
        return 0

    current_status = before_issue.get("status")
    if not current_status or current_status == target_status:
        return 0

    allowed = STORY_WORKFLOW.get(current_status, [])
    if target_status not in allowed:
        coaching = SKIP_AHEAD_COACHING.get((current_status, target_status))
        if coaching:
            print(
                f"story-artifact-gate: refuse skip-ahead {current_status} → {target_status}\n"
                f"{coaching}",
                file=sys.stderr,
            )
            return 1
        print(
            f"story-artifact-gate: transition {current_status} → {target_status} "
            "is not configured for newsroom stories.",
            file=sys.stderr,
        )
        return 1

    artifact_name = ARTIFACT_FOR_TARGET.get(target_status)
    if not artifact_name:
        return 0

    project_root = Path(payload["mode"]["project_root"])
    artifact_path = _story_workspace(project_root, story_id) / artifact_name
    if _artifact_ready(artifact_path):
        return 0

    print(
        f"story-artifact-gate: refuse {current_status} → {target_status}\n"
        f"Write non-empty {artifact_name} under stories/{story_id}/ before advancing. "
        f"The {artifact_name.replace('.md', '')} stage exists so private reporting "
        "precedes reader-facing copy.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
