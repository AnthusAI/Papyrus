from __future__ import annotations

import json
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.content_item_lifecycle import (
    CONTENT_ITEM_STAGES,
    content_item_lineage_for_new_assignment,
    require_assignment_content_item_lineage_id,
)
from papyrus_content.copywriting import build_copywriting_run_plan
from papyrus_content.reporting_packet_review import build_reporting_packet_review_plan
from papyrus_newsroom.coverage_theme import candidate_content_item_version

NOW = "2026-10-17T13:00:00Z"
CONTENT_ITEM_LINEAGE_ID = "content-item-rising-ransomware-abc123"


def reporting_assignment(**overrides):
    return {
        "id": "assignment-reporting-1",
        "assignmentTypeKey": "reporting.edition-candidate",
        "queueKey": "reporting:news:exploratory",
        "status": "completed",
        "title": "Rising ransomware",
        "summary": "Reporting candidate on rising ransomware.",
        "sectionKey": "news",
        "priority": 10,
        "itemLineageId": CONTENT_ITEM_LINEAGE_ID,
        "createdAt": NOW,
        "updatedAt": NOW,
        **overrides,
    }


def reporting_packet_message():
    return {
        "id": "message-reporting-packet-1",
        "messageKind": "reporting_context_packet",
        "summary": "Packet summary",
        "metadata": json.dumps(
            {
                "reporting": {
                    "summary": "Ransomware attacks on hospitals doubled.",
                    "recommendedAngle": "Hospitals are paying",
                    "copywriterBrief": "Lead with the hospitals.",
                    "editorRecommendation": "select",
                }
            }
        ),
    }


def seed_content_item_version():
    return candidate_content_item_version(reporting_assignment(), NOW)


class ContentItemLifecycleTests(unittest.TestCase):
    def test_stages_follow_the_newsroom_story_workflow(self) -> None:
        self.assertEqual(
            CONTENT_ITEM_STAGES,
            ("idea", "assignment", "research", "report", "editor_select", "copywriting", "published"),
        )

    def test_new_work_mints_one_content_item_version_at_its_stage(self) -> None:
        lineage_id, version = content_item_lineage_for_new_assignment(
            requested_lineage_id=None,
            assignment_id="assignment-research-ransomware-1",
            title="Rising ransomware",
            summary="Why now",
            section_key="news",
            stage="research",
            actor_label="tester",
            now=NOW,
        )
        self.assertTrue(lineage_id.startswith("content-item-rising-ransomware-"))
        self.assertEqual(version["lineageId"], lineage_id)
        self.assertEqual(version["versionNumber"], 1)
        self.assertEqual(version["stage"], "research")
        self.assertEqual(version["status"], "draft")

    def test_work_on_an_existing_content_item_reuses_its_lineage(self) -> None:
        lineage_id, version = content_item_lineage_for_new_assignment(
            requested_lineage_id=CONTENT_ITEM_LINEAGE_ID,
            assignment_id="assignment-research-ransomware-2",
            title="Rising ransomware",
            summary=None,
            section_key="news",
            stage="research",
            actor_label="tester",
            now=NOW,
        )
        self.assertEqual(lineage_id, CONTENT_ITEM_LINEAGE_ID)
        self.assertIsNone(version)

    def test_assignment_without_a_content_item_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "no itemLineageId"):
            require_assignment_content_item_lineage_id({"id": "assignment-orphan"})

    def test_coverage_theme_candidate_is_a_content_item_at_the_report_stage(self) -> None:
        version = seed_content_item_version()
        self.assertEqual(version["lineageId"], CONTENT_ITEM_LINEAGE_ID)
        self.assertEqual(version["stage"], "report")

    def test_editor_selection_continues_the_same_content_item(self) -> None:
        for decision in ("select", "brief"):
            plan = build_reporting_packet_review_plan(
                assignment=reporting_assignment(),
                message=reporting_packet_message(),
                decision=decision,
                now=NOW,
            )
            copywriting_assignments = [
                record["expected"]
                for record in plan["records"]
                if record.get("modelName") == "Assignment"
            ]
            self.assertEqual(len(copywriting_assignments), 1, decision)
            self.assertEqual(copywriting_assignments[0]["itemLineageId"], CONTENT_ITEM_LINEAGE_ID, decision)

    def test_copywriting_writes_the_next_version_of_the_same_content_item(self) -> None:
        review = build_reporting_packet_review_plan(
            assignment=reporting_assignment(),
            message=reporting_packet_message(),
            decision="select",
            now=NOW,
        )
        copywriting_assignment = next(
            record["expected"] for record in review["records"] if record.get("modelName") == "Assignment"
        )
        plan = build_copywriting_run_plan(
            assignment=copywriting_assignment,
            reporting_packet_message=reporting_packet_message(),
            existing_items=[seed_content_item_version()],
            now=NOW,
        )
        draft = plan["draftItem"]
        self.assertEqual(draft["lineageId"], CONTENT_ITEM_LINEAGE_ID)
        self.assertEqual(draft["versionNumber"], 2)
        self.assertEqual(draft["previousVersionId"], f"{CONTENT_ITEM_LINEAGE_ID}-v1")
        self.assertEqual(draft["stage"], "copywriting")


if __name__ == "__main__":
    unittest.main()
