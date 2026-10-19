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
    plan_content_item_backfill,
    plan_content_item_stage_migration,
    plan_undrafted_backfill_story_demotion,
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
        "assignmentTypeKey": "reporting.candidate",
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
            ("idea", "assignment", "reporting", "copywriting", "illustration", "typesetting", "published", "held", "spiked"),
        )

    def test_new_work_mints_one_content_item_version_at_its_stage(self) -> None:
        lineage_id, version = content_item_lineage_for_new_assignment(
            requested_lineage_id=None,
            assignment_id="assignment-research-ransomware-1",
            title="Rising ransomware",
            summary="Why now",
            section_key="news",
            stage="reporting",
            actor_label="tester",
            now=NOW,
        )
        self.assertTrue(lineage_id.startswith("content-item-rising-ransomware-"))
        self.assertEqual(version["lineageId"], lineage_id)
        self.assertEqual(version["versionNumber"], 1)
        self.assertEqual(version["stage"], "reporting")
        self.assertEqual(version["status"], "draft")

    def test_work_on_an_existing_content_item_reuses_its_lineage(self) -> None:
        lineage_id, version = content_item_lineage_for_new_assignment(
            requested_lineage_id=CONTENT_ITEM_LINEAGE_ID,
            assignment_id="assignment-research-ransomware-2",
            title="Rising ransomware",
            summary=None,
            section_key="news",
            stage="reporting",
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
        self.assertEqual(version["stage"], "reporting")

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


class ContentItemBackfillTests(unittest.TestCase):
    def plan(self, *, items=(), reporting_assignments=(), copywriting_work=()):
        return plan_content_item_backfill(
            items=list(items),
            reporting_assignments=list(reporting_assignments),
            copywriting_work=list(copywriting_work),
            actor_label="tester",
            now=NOW,
        )

    def expected_records(self, plan, model_name):
        return {change["expected"]["id"]: change for change in plan["changes"] if change["modelName"] == model_name}

    def test_items_without_a_stage_get_published_or_copywriting(self) -> None:
        plan = self.plan(
            items=[
                {"id": "item-published-v3", "lineageId": "item-published", "status": "published"},
                {"id": "item-draft-v1", "lineageId": "item-draft", "status": "draft"},
                {"id": "item-staged-v1", "lineageId": "item-staged", "status": "draft", "stage": "report"},
            ]
        )
        items = self.expected_records(plan, "Item")
        self.assertEqual(items["item-published-v3"]["expected"]["stage"], "published")
        self.assertEqual(items["item-draft-v1"]["expected"]["stage"], "copywriting")
        self.assertNotIn("item-staged-v1", items)

    def test_drafted_reporting_candidate_adopts_its_draft_lineage(self) -> None:
        reporting = reporting_assignment(itemLineageId=None)
        copywriting = {"id": "assignment-copywriting-1", "assignmentTypeKey": "copywriting.article-draft"}
        plan = self.plan(
            reporting_assignments=[reporting],
            copywriting_work=[
                {
                    "assignment": copywriting,
                    "sourceReportingAssignmentId": reporting["id"],
                    "producedItemLineageIds": ["item-drafted-lineage"],
                }
            ],
        )
        assignments = self.expected_records(plan, "Assignment")
        self.assertEqual(assignments[reporting["id"]]["expected"]["itemLineageId"], "item-drafted-lineage")
        self.assertEqual(assignments[copywriting["id"]]["expected"]["itemLineageId"], "item-drafted-lineage")
        self.assertEqual(self.expected_records(plan, "Item"), {})
        self.assertEqual(plan["warnings"], [])

    def test_undrafted_reporting_candidate_gets_a_new_content_item(self) -> None:
        in_progress = reporting_assignment(id="assignment-reporting-open", status="open", itemLineageId=None)
        completed = reporting_assignment(id="assignment-reporting-done", itemLineageId=None)
        copywriting = {"id": "assignment-copywriting-2", "assignmentTypeKey": "copywriting.brief-draft"}
        plan = self.plan(
            reporting_assignments=[in_progress, completed],
            copywriting_work=[
                {"assignment": copywriting, "sourceReportingAssignmentId": completed["id"], "producedItemLineageIds": []}
            ],
        )
        assignments = self.expected_records(plan, "Assignment")
        stage_by_lineage = {
            change["expected"]["lineageId"]: change["expected"]["stage"] for change in self.expected_records(plan, "Item").values()
        }
        self.assertEqual(stage_by_lineage[assignments[in_progress["id"]]["expected"]["itemLineageId"]], "assignment")
        self.assertEqual(stage_by_lineage[assignments[completed["id"]]["expected"]["itemLineageId"]], "assignment")
        self.assertEqual(
            assignments[copywriting["id"]]["expected"]["itemLineageId"],
            assignments[completed["id"]]["expected"]["itemLineageId"],
        )

    def test_linked_work_is_left_alone_and_ambiguities_are_reported(self) -> None:
        reporting = reporting_assignment(id="assignment-reporting-twice", itemLineageId=None)
        plan = self.plan(
            reporting_assignments=[reporting_assignment()],
            copywriting_work=[
                {
                    "assignment": {"id": "assignment-copywriting-select", "itemLineageId": None},
                    "sourceReportingAssignmentId": reporting["id"],
                    "producedItemLineageIds": ["item-select"],
                },
                {
                    "assignment": {"id": "assignment-copywriting-brief", "itemLineageId": None},
                    "sourceReportingAssignmentId": reporting["id"],
                    "producedItemLineageIds": ["item-brief"],
                },
                {"assignment": {"id": "assignment-copywriting-orphan"}, "sourceReportingAssignmentId": None},
            ],
        )
        assignments = self.expected_records(plan, "Assignment")
        self.assertNotIn("assignment-reporting-1", assignments)
        self.assertNotIn("assignment-copywriting-orphan", assignments)
        self.assertEqual(len(plan["warnings"]), 2)
        self.assertIn("more than one draft lineage", plan["warnings"][0])
        self.assertIn("left unlinked", plan["warnings"][1])


class UndraftedBackfillDemotionTests(unittest.TestCase):
    def placeholder(self, **overrides):
        return {
            "id": "content-item-a-v1",
            "lineageId": "content-item-a",
            "versionNumber": 1,
            "changeReason": "content-item-created",
            "stage": "report",
            "title": "Rising ransomware",
            "body": [],
            **overrides,
        }

    def test_unedited_placeholders_named_after_a_reporting_assignment_move_to_assignment(self) -> None:
        reporting = [reporting_assignment(itemLineageId="content-item-a")]
        changes = plan_undrafted_backfill_story_demotion(items=[self.placeholder()], reporting_assignments=reporting)
        self.assertEqual([change["expected"]["stage"] for change in changes], ["assignment"])

    def test_real_stories_are_left_alone(self) -> None:
        reporting = [reporting_assignment(itemLineageId="content-item-a")]
        items = [
            self.placeholder(id="edited", body=[{"type": "paragraph"}]),
            self.placeholder(id="revised", versionNumber=2),
            self.placeholder(id="retitled", title="A different headline"),
            self.placeholder(id="published", stage="published"),
            self.placeholder(id="other-lineage", lineageId="content-item-b"),
        ]
        self.assertEqual(plan_undrafted_backfill_story_demotion(items=items, reporting_assignments=reporting), [])


class ContentItemStageMigrationTests(unittest.TestCase):
    def test_retired_stages_move_to_reporting_and_current_stages_stay(self) -> None:
        items = [
            {"id": "a", "stage": "research"},
            {"id": "b", "stage": "report"},
            {"id": "c", "stage": "editor_select"},
            {"id": "d", "stage": "copywriting"},
            {"id": "e", "stage": "assignment"},
        ]
        changes = plan_content_item_stage_migration(items=items)
        self.assertEqual({change["expected"]["id"]: change["expected"]["stage"] for change in changes}, {"a": "reporting", "b": "reporting", "c": "reporting"})


if __name__ == "__main__":
    unittest.main()
