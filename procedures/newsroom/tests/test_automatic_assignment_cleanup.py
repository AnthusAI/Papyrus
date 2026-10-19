from __future__ import annotations

import unittest

from papyrus_content.automatic_assignments import (
    OPERATIONAL_ASSIGNMENT_FEED_KEY,
    plan_automatic_assignment_cleanup,
)
from papyrus_content.catalog import reference_records
from papyrus_content.reference_assignments import build_text_extraction_assignment_records


class AutomaticAssignmentCleanupTests(unittest.TestCase):
    def test_plan_selects_only_automatic_assignments_with_their_events_and_relations(self) -> None:
        assignments = [
            {"id": "a-curate", "assignmentTypeKey": "curation.reference-intake", "status": "open", "title": "Curate reference: X"},
            {"id": "a-accession", "assignmentTypeKey": "reference.corpus-accession", "status": "completed", "title": "Accession source: Y"},
            {"id": "a-backfill", "assignmentTypeKey": "reference.identifier-backfill", "status": "open", "title": "Identifier backfill for z"},
            {"id": "a-reindex", "assignmentTypeKey": "analysis.reindex", "status": "open", "title": "Re-index X"},
            {"id": "a-real", "assignmentTypeKey": "newsroom.research", "status": "open", "title": "Investigate chips"},
        ]
        events = [
            {"id": "e-1", "assignmentId": "a-curate"},
            {"id": "e-2", "assignmentId": "a-real"},
        ]
        relations = [
            {"id": "r-1", "subjectKind": "assignment", "subjectId": "a-accession"},
            {"id": "r-2", "subjectKind": "assignment", "subjectId": "a-real"},
            {"id": "r-3", "subjectKind": "message", "subjectId": "a-curate"},
        ]

        deletions = plan_automatic_assignment_cleanup(
            assignments=assignments, assignment_events=events, semantic_relations=relations
        )

        self.assertEqual(
            sorted((deletion["modelName"], deletion["id"]) for deletion in deletions),
            [
                ("Assignment", "a-accession"),
                ("Assignment", "a-backfill"),
                ("Assignment", "a-curate"),
                ("Assignment", "a-reindex"),
                ("AssignmentEvent", "e-1"),
                ("SemanticRelation", "r-1"),
            ],
        )

    def test_reference_import_no_longer_creates_curation_assignments(self) -> None:
        context = {
            "corpusId": "corpus-1",
            "importRunId": "run-1",
            "now": "2026-10-18T00:00:00Z",
            "classifierId": None,
        }
        item = {"item_id": "11111111-1111-1111-1111-111111111111", "title": "Paper", "url": "https://example.com/p"}
        records = reference_records(item, context)
        self.assertNotIn("Assignment", {record["modelName"] for record in records})

    def test_operational_assignments_stay_off_the_assignments_feed(self) -> None:
        records = build_text_extraction_assignment_records(
            corpus_config={"key": "k", "path": "/tmp/k"},
            corpus_id="corpus-1",
            actor_label="tester",
            now="2026-10-18T00:00:00Z",
            options={},
            run_id="run-1",
        )
        assignment = next(record["expected"] for record in records if record["modelName"] == "Assignment")
        self.assertEqual(assignment["newsroomFeedKey"], OPERATIONAL_ASSIGNMENT_FEED_KEY)
        self.assertNotEqual(assignment["newsroomFeedKey"], "assignments")


if __name__ == "__main__":
    unittest.main()
