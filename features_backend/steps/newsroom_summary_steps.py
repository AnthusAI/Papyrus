from __future__ import annotations

import copy
import sys
from pathlib import Path

from behave import given, then, when

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from papyrus_content.newsroom_summary import (
    build_newsroom_summary_payload,
    build_newsroom_summary_payload_record,
    newsroom_summary_diff,
    update_newsroom_summary_after_assignment_creates,
    update_newsroom_summary_after_extracted_text_attachments,
    update_newsroom_summary_after_reference_registration,
)

MOMENT_OF_THE_COMPARISON_RECOUNT = "2026-11-20T16:00:00Z"
IMPORT_RUN_THAT_REGISTERS_REFERENCES = "import-run-2026-11-20"


class SummaryUpdateRecorder:
    def __init__(self):
        self.summary_updates = []

    def update_newsroom_summary(self, delta, *, actor_label, reason):
        self.summary_updates.append({"delta": delta, "actor_label": actor_label, "reason": reason})


def _recount_of_the_newsroom(context, moment):
    return build_newsroom_summary_payload(
        references=context.newsroom_references,
        assignments=context.newsroom_assignments,
        now=moment,
    )


def _counts_keyed_by_first_column(table):
    return {row[0]: int(row["count"]) for row in table}


def _the_single_summary_update(context):
    assert len(context.summary_update_recorder.summary_updates) == 1, context.summary_update_recorder.summary_updates
    return context.summary_update_recorder.summary_updates[0]


@given("a newsroom with these References")
def given_newsroom_references(context):
    context.summary_update_recorder = SummaryUpdateRecorder()
    context.newsroom_references = [
        {
            "id": f"{row['lineage']}-v{row['version']}",
            "lineageId": row["lineage"],
            "versionNumber": int(row["version"]),
            "versionState": row["state"],
            "curationStatus": row["decision"],
            "corpusId": row["corpus"],
        }
        for row in context.table
    ]


@given("these Assignments")
def given_newsroom_assignments(context):
    context.newsroom_assignments = [
        {"status": row["status"], "assignmentTypeKey": row["type"], "sectionKey": row["section"]}
        for row in context.table
    ]


@when('the newsroom summary is recounted at "{moment}"')
def when_summary_is_recounted(context, moment):
    context.recounted_summary = _recount_of_the_newsroom(context, moment)
    context.recounted_summary_record = build_newsroom_summary_payload_record(context.recounted_summary, now=moment)


@then('the summary counts {expected_count:d} "{count_name}"')
def then_summary_counts(context, expected_count, count_name):
    assert context.recounted_summary["counts"][count_name] == expected_count, context.recounted_summary["counts"]


@then("the summary counts References by decision")
def then_summary_counts_references_by_decision(context):
    assert context.recounted_summary["referenceStatusCounts"] == _counts_keyed_by_first_column(context.table)


@then("the summary counts References by corpus")
def then_summary_counts_references_by_corpus(context):
    assert context.recounted_summary["facets"]["references"]["byCorpus"] == _counts_keyed_by_first_column(context.table)


@then("the summary counts Assignments by status")
def then_summary_counts_assignments_by_status(context):
    assert context.recounted_summary["assignmentStatusCounts"] == _counts_keyed_by_first_column(context.table)


@then("the summary counts Assignments by section")
def then_summary_counts_assignments_by_section(context):
    assert context.recounted_summary["facets"]["assignments"]["bySection"] == _counts_keyed_by_first_column(context.table)


@then('the summary says it came from a "{source}"')
def then_summary_source(context, source):
    assert context.recounted_summary["source"] == source


@then('the summary goes stale at "{moment}"')
def then_summary_goes_stale_at(context, moment):
    assert context.recounted_summary["staleAt"] == moment, context.recounted_summary["staleAt"]


@then('the summary is stored under the single id "{record_id}"')
def then_summary_is_stored_under(context, record_id):
    assert context.recounted_summary_record["id"] == record_id
    assert context.recounted_summary_record["ownerType"] == "newsroom"


@when('{how_many:d} "{status}" Assignments of type "{assignment_type}" are created')
def when_assignments_are_created(context, how_many, status, assignment_type):
    changes = [
        {"modelName": "Assignment", "action": "create", "expected": {"status": status, "assignmentTypeKey": assignment_type}}
        for _ in range(how_many)
    ]
    changes.append({"modelName": "Message", "action": "create", "expected": {"messageKind": "note"}})
    update_newsroom_summary_after_assignment_creates(
        context.summary_update_recorder,
        changes,
        actor_label="Papyrus content CLI",
        reason="assignments create",
    )


@when("extracted text is attached to {how_many:d} References")
def when_extracted_text_is_attached(context, how_many):
    changes = [
        {"modelName": "ReferenceAttachment", "action": "create", "expected": {"role": "extracted_text"}}
        for _ in range(how_many)
    ]
    update_newsroom_summary_after_extracted_text_attachments(
        context.summary_update_recorder,
        changes,
        actor_label="Papyrus content CLI",
        reason="references extract-text",
    )


@when("a catalog import creates {created:d} pending References and updates {updated:d} accepted Reference")
def when_catalog_import_registers_references(context, created, updated):
    changes = [
        {
            "modelName": "Reference",
            "action": "create",
            "expected": {"versionState": "current", "curationStatus": "pending", "corpusId": "health"},
        }
        for _ in range(created)
    ] + [
        {
            "modelName": "Reference",
            "action": "update",
            "expected": {"versionState": "current", "curationStatus": "accepted", "corpusId": "health"},
        }
        for _ in range(updated)
    ]
    changes.append(
        {"modelName": "KnowledgeImportRun", "action": "create", "expected": {"id": IMPORT_RUN_THAT_REGISTERS_REFERENCES}}
    )
    update_newsroom_summary_after_reference_registration(
        context.summary_update_recorder,
        changes,
        {"importRunId": IMPORT_RUN_THAT_REGISTERS_REFERENCES},
    )


@when("a catalog import writes only a superseded version of a Reference")
def when_catalog_import_writes_superseded_version(context):
    changes = [
        {
            "modelName": "Reference",
            "action": "create",
            "expected": {"versionState": "superseded", "curationStatus": "pending", "corpusId": "health"},
        }
    ]
    update_newsroom_summary_after_reference_registration(
        context.summary_update_recorder,
        changes,
        {"importRunId": IMPORT_RUN_THAT_REGISTERS_REFERENCES},
    )


@then("one summary update is sent")
def then_one_summary_update_is_sent(context):
    _the_single_summary_update(context)


@then("no summary update is sent")
def then_no_summary_update_is_sent(context):
    assert context.summary_update_recorder.summary_updates == []


@then('the update adds {amount:d} to "{count_name}"')
def then_update_adds_to_count(context, amount, count_name):
    count_deltas = _the_single_summary_update(context)["delta"]["countDeltas"]
    assert count_deltas[count_name] == amount, count_deltas


@then('the update adds {amount:d} to the Assignment status "{status}"')
def then_update_adds_to_assignment_status(context, amount, status):
    status_deltas = _the_single_summary_update(context)["delta"]["assignmentStatusDeltas"]
    assert status_deltas == {status: amount}, status_deltas


@then('the update says it is "{source}"')
def then_update_source(context, source):
    assert _the_single_summary_update(context)["delta"]["source"] == source


@then("the update names the import run in its reason")
def then_update_names_import_run(context):
    assert IMPORT_RUN_THAT_REGISTERS_REFERENCES in _the_single_summary_update(context)["reason"]


@given('the stored summary was recounted before {how_many:d} more "{status}" Assignment existed')
def given_stored_summary_predates_assignments(context, how_many, status):
    context.stored_summary = copy.deepcopy(_recount_of_the_newsroom(context, MOMENT_OF_THE_COMPARISON_RECOUNT))
    context.newsroom_assignments.extend(
        {"status": status, "assignmentTypeKey": "research.reference", "sectionKey": "news"} for _ in range(how_many)
    )


@given("the stored summary was recounted just now")
def given_stored_summary_is_fresh(context):
    context.stored_summary = copy.deepcopy(_recount_of_the_newsroom(context, MOMENT_OF_THE_COMPARISON_RECOUNT))


@when("the stored summary is compared with a fresh recount")
def when_stored_summary_is_compared(context):
    context.summary_drift = newsroom_summary_diff(
        context.stored_summary,
        _recount_of_the_newsroom(context, MOMENT_OF_THE_COMPARISON_RECOUNT),
    )


@then("{how_many:d} count differs")
@then("{how_many:d} counts differ")
def then_counts_differ(context, how_many):
    assert context.summary_drift["countsChanged"] == how_many, context.summary_drift


@then("{how_many:d} group of breakdowns differs")
@then("{how_many:d} groups of breakdowns differ")
def then_breakdown_groups_differ(context, how_many):
    assert context.summary_drift["facetSectionsChanged"] == how_many, context.summary_drift
