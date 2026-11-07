"""The one definition of how a Story moves through the newsroom (docs/story-procedure.md).

Pure data and pure functions, no model calls. The CLI reads it for `papyrus stories next` and for the reminders printed after a write.
Each live step is also an item of the Story's stored checklist (story_checklist.py): a skipped step needs a recorded reason, and publishing
refuses while a required step is open. The four review steps are the template's readers' lenses. Human sign-off is never a stage: a person
comes in through a review request."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

from .content_item_lifecycle import CONTENT_ITEM_STAGES

LIVE = "live"
OFF = "off"
NOT_BUILT = "not_built"

DONE = "done"
NOT_DONE = "not_done"
UNKNOWN = "unknown"

OUTLINE_KEY = "outline"
EDITOR_REVIEW_KEY = "editorReview"
STAGES_AT_OR_AFTER_COPYWRITING = ("copywriting", "illustration", "typesetting", "published")
STAGES_WITHOUT_NEXT_STEP = ("spiked", "held", "published")

#: The version of this template. Raise it whenever a step is added, removed or changes its status, so each checklist item records the template it came from.
TEMPLATE_VERSION = 2


@dataclass(frozen=True)
class Step:
    key: str
    stage: str
    role: str
    title: str
    command: str
    status: str
    optional: bool
    note: str
    #: Done by hand: no record proves it, so marking it done needs a short findings note (the four review lenses).
    manual: bool = False


STEPS: tuple[Step, ...] = (
    Step("choose", "idea", "Editor agent or a person", "Choose the idea", "papyrus ideas select --section <section>", LIVE, False,
         "The editor agent picks few, under a rate limit. A person can pick by hand with stories assign-research, or undo a pick by moving the Story back."),
    Step("direction", "assignment", "Editor", "Give the research direction",
         "papyrus stories assign-research --story {story} --direction-file direction.md", LIVE, False,
         "The direction is the Assignment's instructions."),
    Step("research", "reporting", "Reporter", "Research the Story",
         "papyrus assignments research-multi <assignment id>", LIVE, False,
         "The research packet is stored on the Assignment."),
    Step("outline", "reporting", "Editor agent", "Write the outline after the research",
         "papyrus stories outline --story {story}", LIVE, False,
         "A person can save their own with stories save-version --outline. A later version counts as the draft."),
    Step("draft", "copywriting", "Copywriter", "Write the draft",
         "papyrus stories draft --story {story}", LIVE, False,
         "A version newer than the outline; a person can save their own with stories save-version."),
    Step("fact_check", "copywriting", "Fact-check agent", "Fact-check the draft", "", NOT_BUILT, False,
         "Not built yet (PPY-719a02)."),
    Step("copy_edit", "copywriting", "Copywriter with Humanus", "Copy-edit the draft",
         "papyrus editorial check-version --item <current version id>", LIVE, False,
         "A finished editorial check of the current version with no error-level violation."),
    Step("editor_review", "copywriting", "Editor agent", "Editor review", "", OFF, False,
         "Off: needs the editor_review.tac procedure, which no site has on."),
    Step("review_people", "copywriting", "Editor or reviewing agent", "Reviewed for readers",
         "papyrus stories step --story {story} --step review_people --state done --note <findings>", LIVE, False,
         "Human readers: a person or agent reads the Story as a reader would and records the findings. What each lens checks is a later design (PPY-59c772df).", True),
    Step("review_reader_agents", "copywriting", "Editor or reviewing agent", "Reviewed for AI reader agents",
         "papyrus stories step --story {story} --step review_reader_agents --state done --note <findings>", LIVE, False,
         "AI agents that read the page for a person. Findings are recorded by hand for now (PPY-59c772df).", True),
    Step("review_search", "copywriting", "Editor or reviewing agent", "Reviewed for search",
         "papyrus stories step --story {story} --step review_search --state done --note <findings>", LIVE, False,
         "Search crawlers. Findings are recorded by hand for now (PPY-59c772df).", True),
    Step("review_social", "copywriting", "Editor or reviewing agent", "Reviewed for social previews",
         "papyrus stories step --story {story} --step review_social --state done --note <findings>", LIVE, False,
         "Social previews (link cards). Findings are recorded by hand for now (PPY-59c772df).", True),
    Step("illustration", "illustration", "Editor", "Illustrate", "", NOT_BUILT, True, "Not built yet."),
    Step("typesetting", "typesetting", "Editor", "Typeset", "", NOT_BUILT, True, "Not built yet."),
    Step("publish", "published", "A person", "Publish the Story", "papyrus ops content publish --id <item id>", LIVE, False,
         "The only hard gate."),
)


STEP_BY_KEY = {step.key: step for step in STEPS}
REVIEW_STEP_KEYS = tuple(step.key for step in STEPS if step.key.startswith("review_"))


def _metadata_of(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    if isinstance(value, str):
        try:
            value = json.loads(value) if value else {}
        except json.JSONDecodeError:
            value = {}
    return value if isinstance(value, dict) else {}


def story_facts(client, lineage: str, read_check_run: Callable[[str], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    """Reads the records once: the current version, the lineage's Assignments with their direction and research packets, and the stored check run."""
    from .assignments import assignment_metadata
    from .assignments_workflow import load_assignment_research_packet_entries
    from .story_reporting import current_story_version

    current = current_story_version(client, lineage)
    assignments = []
    for assignment in client.list_by_index("assignmentsByItemLineageAndCreatedAt", lineage):
        metadata = assignment_metadata(client, assignment)
        direction = metadata.get("direction") or assignment.get("instructions") or metadata.get("instructions")
        try:
            has_packet = bool(load_assignment_research_packet_entries(client, assignment["id"]))
        except Exception:
            has_packet = False
        assignments.append({"id": assignment["id"], "hasDirection": bool(str(direction or "").strip()), "hasResearchPacket": has_packet})
    check_run, check_run_error = None, False
    try:
        if read_check_run is None:
            from .editorial_commands import read_item_check_run as read_check_run
        check_run = read_check_run(current["id"])
    except Exception:
        check_run_error = True
    return {
        "lineage": lineage,
        "stage": current.get("stage") or "idea",
        "versionId": current["id"],
        "versionNumber": int(current.get("versionNumber") or 1),
        "body": current.get("bodyMarkus") or "",
        "metadata": _metadata_of(current),
        "assignments": assignments,
        "checkRun": check_run,
        "checkRunError": check_run_error,
    }


def _check_run_finished(run: dict[str, Any]) -> bool:
    from .editorial_checks import FINISHED_LANE_STATUSES

    lanes = run.get("lanes")
    if not isinstance(lanes, dict):
        return False
    return all((lane or {}).get("status") in FINISHED_LANE_STATUSES for lane in lanes.values() if isinstance(lane, dict))


def _has_error_violation(run: dict[str, Any]) -> bool:
    return any(f.get("status") == "violation" and f.get("severity") == "error" for f in run.get("findings") or [])


def _state_of(step: Step, facts: dict[str, Any]) -> str:
    stage = facts["stage"]
    metadata = facts["metadata"]
    outline = metadata.get(OUTLINE_KEY)
    if step.key == "choose":
        return DONE if stage != "idea" else NOT_DONE
    if step.key == "direction":
        return DONE if any(a["hasDirection"] for a in facts["assignments"]) else NOT_DONE
    if step.key == "research":
        return DONE if any(a["hasResearchPacket"] for a in facts["assignments"]) else NOT_DONE
    if step.key == "outline":
        return DONE if outline else NOT_DONE
    if step.key == "draft":
        if isinstance(outline, dict) and outline.get("versionNumber") is not None:
            return DONE if facts["versionNumber"] > int(outline["versionNumber"]) else NOT_DONE
        return DONE if facts["body"].strip() and stage in STAGES_AT_OR_AFTER_COPYWRITING else NOT_DONE
    if step.key == "copy_edit":
        # A check of an idea or an outline is not a copy edit of the draft.
        if _state_of(STEP_BY_KEY["draft"], facts) != DONE:
            return NOT_DONE
        if facts["checkRunError"]:
            return UNKNOWN
        run = facts["checkRun"]
        if run and _check_run_finished(run) and not _has_error_violation(run):
            return DONE
        return NOT_DONE
    if step.key == "editor_review":
        review = metadata.get(EDITOR_REVIEW_KEY)
        approved = isinstance(review, dict) and review.get("versionId") == facts["versionId"] and review.get("verdict") == "approve"
        return DONE if approved else NOT_DONE
    if step.key == "publish":
        return DONE if stage == "published" else NOT_DONE
    if step.manual:
        return NOT_DONE   # no record proves a lens review; the Story's stored checklist says whether a person or agent did it
    return UNKNOWN


def assess(facts: dict[str, Any]) -> dict[str, Any]:
    """Pure over facts: each step's state, the next step and the steps skipped before the Story's current stage."""
    stage = facts["stage"]
    rows = []
    for step in STEPS:
        rows.append({
            "key": step.key, "title": step.title, "role": step.role, "stage": step.stage, "status": step.status,
            "state": _state_of(step, facts), "command": step.command.replace("{story}", str(facts["lineage"])), "note": step.note,
            "optional": step.optional, "manual": step.manual,
        })
    next_row = None
    skipped: list[dict[str, Any]] = []
    if stage not in STAGES_WITHOUT_NEXT_STEP:
        pending = [row for row in rows if row["state"] != DONE]
        next_row = next((row for row in pending if row["status"] == LIVE), None) or (pending[0] if pending else None)
        current_index = CONTENT_ITEM_STAGES.index(stage) if stage in CONTENT_ITEM_STAGES else 0
        optional_keys = {step.key for step in STEPS if step.optional}
        skipped = [
            row for row in rows
            if row["state"] == NOT_DONE and row["status"] == LIVE and row["key"] not in optional_keys
            and CONTENT_ITEM_STAGES.index(row["stage"]) < current_index
        ]
    return {"stage": stage, "steps": rows, "next": next_row, "skipped": skipped}


def process_text(assessment: dict[str, Any]) -> str:
    """The procedure as an agent reads it in its context pack: where the Story is, what is done, what is next and what comes after."""
    def named(row: dict[str, Any]) -> str:
        return row["key"] + ({OFF: " (off)", NOT_BUILT: " (not built)"}.get(row["status"], ""))

    rows = assessment["steps"]
    upcoming = [row for row in rows if row["state"] != DONE and row is not assessment["next"]]
    next_row = assessment["next"]
    lines = [f"Stage: {assessment['stage']}",
             "Done: " + (", ".join(row["key"] for row in rows if row["state"] == DONE) or "nothing yet"),
             f"Next: {next_row['title']} ({next_row['role']})" if next_row else "Next: nothing; the Story is not in progress"]
    if next_row and upcoming:
        lines.append("Not done: " + ", ".join(named(row) for row in upcoming))
    if assessment["skipped"]:
        lines.append("Skipped earlier: " + ", ".join(row["key"] for row in assessment["skipped"]))
    return "\n".join(lines)


def _command_text(row: dict[str, Any]) -> str:
    if row["status"] == OFF:
        return f"off: {row['note']}"
    if row["status"] == NOT_BUILT:
        return f"not built: {row['note']}"
    return row["command"]


def next_lines(assessment: dict[str, Any]) -> list[str]:
    lines = []
    row = assessment["next"]
    if row:
        lines.append("\t".join(["next", row["key"], row["role"], row["title"], _command_text(row)]))
    for skipped in assessment["skipped"]:
        lines.append("\t".join(["skipped", skipped["key"], skipped["title"]]))
    return lines


def step_lines(assessment: dict[str, Any]) -> list[str]:
    return ["\t".join(["step", row["key"], row["state"], row["status"], row["stage"], row["role"], row["title"]]) for row in assessment["steps"]]


def reminder_assessment(client, lineage: str, read_check_run=None, *, sync_checklist: bool = False) -> dict[str, Any] | None:
    """The assessment for a reminder after a write; a failure prints one line to stderr and returns None, never raises.

    ``sync_checklist`` is for a reminder printed after a write: the same facts then bring the Story's stored checklist up to date once
    (new template steps open, evidence marks steps done). It never fails the write either; a problem prints one line to stderr."""
    try:
        facts = story_facts(client, lineage, read_check_run)
        assessment = assess(facts)
    except Exception as error:
        print(f"next\tnot computed\t{type(error).__name__}: {str(error)[:160]}", file=sys.stderr)
        return None
    if sync_checklist:
        from .story_checklist import sync_quietly

        sync_quietly(client, lineage, facts=facts, assessment=assessment)
    return assessment


def print_reminder(client, lineage: str, read_check_run=None) -> dict[str, Any] | None:
    assessment = reminder_assessment(client, lineage, read_check_run, sync_checklist=True)
    print_next_lines(assessment)
    return assessment


def next_payload(assessment: dict[str, Any] | None) -> dict[str, Any] | None:
    if assessment is None:
        return None
    return {"next": assessment["next"], "skipped": assessment["skipped"]}


def warn_skipped(assessment: dict[str, Any]) -> None:
    """One stderr line naming each skipped step, for a move to a later stage."""
    for row in assessment["skipped"]:
        print(f"warning: step '{row['key']}' ({row['title']}) was skipped; the Story moved anyway.", file=sys.stderr)


def print_next_lines(assessment: dict[str, Any] | None) -> None:
    if assessment is not None:
        for line in next_lines(assessment):
            print(line)
