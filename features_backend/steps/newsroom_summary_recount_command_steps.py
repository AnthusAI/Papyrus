from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from papyrus_content import newsroom_commands
from papyrus_content.newsroom_summary import NEWSROOM_SUMMARY_PAYLOAD_ID, build_newsroom_summary_payload

DATE_THE_SUMMARY_WAS_FIRST_CREATED = "2026-11-01T00:00:00Z"
ERROR_THE_SERVICE_GIVES_FOR_A_MESSAGE_WITHOUT_STATUS = (
    "GraphQL error: Cannot return null for non-nullable type: 'String' within parent 'Message' (/listMessages/items[0]/status)"
)


class NewsroomRecordsRecorder:
    def __init__(self, records_by_model):
        self.records_by_model = records_by_model
        self.one_message_has_no_status = False
        self.written_records = []

    def list_records(self, model_name):
        if model_name == "Message" and self.one_message_has_no_status:
            raise RuntimeError(ERROR_THE_SERVICE_GIVES_FOR_A_MESSAGE_WITHOUT_STATUS)
        return list(self.records_by_model.get(model_name, []))

    def safe_list_records(self, model_name):
        return self.list_records(model_name)

    def get_record(self, model_name, record_id):
        if model_name == "KnowledgeRawPayload" and record_id == NEWSROOM_SUMMARY_PAYLOAD_ID:
            return {
                "id": NEWSROOM_SUMMARY_PAYLOAD_ID,
                "ownerType": "newsroom",
                "ownerId": "newsroom",
                "payloadKind": "summary-snapshot",
                "createdAt": DATE_THE_SUMMARY_WAS_FIRST_CREATED,
                "updatedAt": DATE_THE_SUMMARY_WAS_FIRST_CREATED,
            }
        return None

    def upsert(self, model_name, record):
        self.written_records.append((model_name, record))


def _references(how_many):
    return [
        {"id": f"reference-{number}", "lineageId": f"reference-{number}", "versionState": "current", "curationStatus": "pending"}
        for number in range(how_many)
    ]


def _assignments(how_many):
    return [{"id": f"assignment-{number}", "status": "open", "assignmentTypeKey": "research.reference"} for number in range(how_many)]


@given("a newsroom that holds {references:d} References, {assignments:d} Assignments and {messages:d} message")
def given_newsroom_holds_records(context, references, assignments, messages):
    context.newsroom_records_recorder = NewsroomRecordsRecorder(
        {
            "Reference": _references(references),
            "Assignment": _assignments(assignments),
            "Message": [{"id": f"message-{number}", "status": "active", "messageKind": "note"} for number in range(messages)],
        }
    )
    context.uploaded_summary_bodies = []
    context.recount_refusal = None
    context.recount_output = ""


@given("a stored summary that counts {references:d} References and {assignments:d} Assignment")
def given_stored_summary(context, references, assignments):
    context.stored_summary_payload = build_newsroom_summary_payload(
        references=_references(references),
        assignments=_assignments(assignments),
        messages=context.newsroom_records_recorder.records_by_model["Message"],
        now=DATE_THE_SUMMARY_WAS_FIRST_CREATED,
    )


@given("one message in the newsroom has no status")
def given_message_without_status(context):
    context.newsroom_records_recorder.one_message_has_no_status = True


@when('an operator runs the recount with "{flags}"')
def when_operator_runs_recount(context, flags):
    printed = io.StringIO()
    with mock.patch.object(
        newsroom_commands, "create_authoring_client", return_value=(context.newsroom_records_recorder, {})
    ), mock.patch.object(
        newsroom_commands, "read_json_model_payload", return_value=context.stored_summary_payload
    ), mock.patch.object(
        newsroom_commands,
        "upload_attachment_body",
        side_effect=lambda client, attachment, body: context.uploaded_summary_bodies.append((attachment, body)),
    ), contextlib.redirect_stdout(printed):
        try:
            newsroom_commands.newsroom_recount_summary(flags.split())
        except ValueError as refusal:
            context.recount_refusal = refusal
    context.recount_output = printed.getvalue()


def _recount_report(context):
    assert context.recount_refusal is None, context.recount_refusal
    return json.loads(context.recount_output)


@then('the recount reports the action "{action}"')
def then_recount_reports_action(context, action):
    assert _recount_report(context)["action"] == action, context.recount_output


@then("the recount reports that {how_many:d} counts changed")
def then_recount_reports_counts_changed(context, how_many):
    assert _recount_report(context)["countsChanged"] == how_many, context.recount_output


@then("the recount says the stored summary was not updated")
def then_recount_says_not_updated(context):
    assert _recount_report(context)["attachmentUpdated"] is False


@then("the recount says the stored summary was updated")
def then_recount_says_updated(context):
    assert _recount_report(context)["attachmentUpdated"] is True


@then("nothing is written to the newsroom")
def then_nothing_is_written(context):
    assert context.newsroom_records_recorder.written_records == []
    assert context.uploaded_summary_bodies == []


@then("the summary record is written once")
def then_summary_record_written_once(context):
    summary_writes = [
        record for model_name, record in context.newsroom_records_recorder.written_records if model_name == "KnowledgeRawPayload"
    ]
    assert len(summary_writes) == 1, context.newsroom_records_recorder.written_records
    assert summary_writes[0]["id"] == NEWSROOM_SUMMARY_PAYLOAD_ID


@then("the summary's counts are uploaded once as its attachment")
def then_summary_counts_uploaded_once(context):
    assert len(context.uploaded_summary_bodies) == 1
    attachment_writes = [
        record for model_name, record in context.newsroom_records_recorder.written_records if model_name == "ModelAttachment"
    ]
    assert len(attachment_writes) == 1
    assert attachment_writes[0]["ownerId"] == NEWSROOM_SUMMARY_PAYLOAD_ID


@then('the written summary record was created at "{moment}"')
def then_written_summary_created_at(context, moment):
    summary_writes = [
        record for model_name, record in context.newsroom_records_recorder.written_records if model_name == "KnowledgeRawPayload"
    ]
    assert summary_writes[0]["createdAt"] == moment, summary_writes[0]


@then('the recount prints the line "{line}"')
def then_recount_prints_line(context, line):
    assert context.recount_refusal is None, context.recount_refusal
    assert line in context.recount_output.splitlines(), context.recount_output


@then('the recount stops and tells the operator to run "{command}"')
def then_recount_names_the_repair(context, command):
    assert context.recount_refusal is not None, context.recount_output
    assert command in str(context.recount_refusal), context.recount_refusal


@then("the recount stops and says writes now run by default")
def then_recount_refuses_apply_flag(context):
    assert context.recount_refusal is not None, context.recount_output
    assert "Writes now run by default" in str(context.recount_refusal), context.recount_refusal
