import contextlib
import io
import json
import shlex
from contextlib import ExitStack
from unittest.mock import patch

from behave import given, then, when

from papyrus_content import newsroom_commands

NAME_OF_THE_PAYLOAD_BUCKET = "bucket-of-newsroom-payloads"


class NewsroomRecordsHeldInMemory:
    def __init__(self):
        self.records_by_model = {"ModelAttachment": [], "Reference": []}
        self.attachment_records_deleted = []

    def list_records(self, model_name):
        return list(self.records_by_model.get(model_name, []))

    def delete_record(self, model_name, record_id):
        assert model_name == "ModelAttachment", model_name
        self.attachment_records_deleted.append(record_id)
        self.records_by_model[model_name] = [record for record in self.records_by_model[model_name] if record["id"] != record_id]


def record_an_attachment(context, *, attachment, owner_kind, owner, file):
    context.newsroom_records.records_by_model["ModelAttachment"].append({
        "id": attachment,
        "ownerKind": owner_kind,
        "ownerId": owner,
        "storagePath": file,
    })
    context.files_in_the_payload_store.add(file)


@given('the newsroom has the Reference "{reference_id}" and no other owner of attachments')
def newsroom_has_the_reference(context, reference_id):
    context.newsroom_records = NewsroomRecordsHeldInMemory()
    context.newsroom_records.records_by_model["Reference"].append({"id": reference_id})
    context.files_in_the_payload_store = set()
    context.files_deleted_from_the_payload_store = []


@given("these attachments are recorded")
def these_attachments_are_recorded(context):
    for row in context.table:
        record_an_attachment(context, attachment=row["attachment"], owner_kind=row["owner kind"], owner=row["owner"], file=row["file"])


@given('the payload store also holds the file "{file}"')
def payload_store_also_holds_the_file(context, file):
    context.files_in_the_payload_store.add(file)


@given('the attachment "{attachment}" of the {owner_kind} "{owner}" names the file "{file}"')
def attachment_names_the_file(context, attachment, owner_kind, owner, file):
    record_an_attachment(context, attachment=attachment, owner_kind=owner_kind, owner=owner, file=file)


def prune_the_attachments(context, flags: list[str]):
    def list_the_payload_store(*, bucket=None, prefix="newsroom/payloads/"):
        return {
            "bucket": NAME_OF_THE_PAYLOAD_BUCKET,
            "prefix": prefix,
            "keys": sorted(file for file in context.files_in_the_payload_store if file.startswith(prefix)),
        }

    def delete_from_the_payload_store(storage_paths, *, bucket=None, dry_run=False):
        context.files_deleted_from_the_payload_store.extend(storage_paths)
        return {"deleted": len(storage_paths)}

    printed = io.StringIO()
    with ExitStack() as stand_ins:
        stand_ins.enter_context(patch.object(newsroom_commands, "create_authoring_client", lambda: (context.newsroom_records, None)))
        stand_ins.enter_context(patch.object(newsroom_commands, "list_attachment_storage_paths", list_the_payload_store))
        stand_ins.enter_context(patch.object(newsroom_commands, "delete_attachment_storage_paths", delete_from_the_payload_store))
        stand_ins.enter_context(contextlib.redirect_stdout(printed))
        newsroom_commands.newsroom_prune_attachments(["--json", *flags])
    context.prune_report = json.loads(printed.getvalue())


@when("the attachments are pruned")
def attachments_are_pruned(context):
    prune_the_attachments(context, [])


@when('the attachments are pruned with "{flags}"')
def attachments_are_pruned_with(context, flags):
    prune_the_attachments(context, shlex.split(flags))


@then('the attachment records deleted are "{attachments}"')
def attachment_records_deleted_are(context, attachments):
    expected = sorted(name.strip() for name in attachments.split(","))
    assert sorted(context.newsroom_records.attachment_records_deleted) == expected, context.newsroom_records.attachment_records_deleted
    assert context.prune_report["deleted"]["attachmentRecords"] == len(expected), context.prune_report


@then('the files deleted include "{file}"')
def files_deleted_include(context, file):
    assert file in context.files_deleted_from_the_payload_store, context.files_deleted_from_the_payload_store


@then('the file "{file}" is not deleted')
def file_is_not_deleted(context, file):
    assert file not in context.files_deleted_from_the_payload_store, context.files_deleted_from_the_payload_store


@then('the attachment "{attachment}" is still recorded')
def attachment_is_still_recorded(context, attachment):
    assert attachment in [record["id"] for record in context.newsroom_records.list_records("ModelAttachment")]


@then('the prune lists "{attachment}" as kept because its kind of owner is unknown')
def prune_lists_attachment_as_kept(context, attachment):
    assert [kept["id"] for kept in context.prune_report["keptUnknownOwnerKind"]] == [attachment], context.prune_report
    assert context.prune_report["counts"]["keptUnknownOwnerKind"] == 1, context.prune_report


@then("the prune counts {records:d} orphaned attachment records and {files:d} orphaned files")
def prune_counts(context, records, files):
    counts = context.prune_report["counts"]
    assert (counts["orphanAttachmentRecords"], counts["orphanStorageObjects"]) == (records, files), counts


@then("no attachment record and no file is deleted")
def nothing_is_deleted(context):
    assert context.newsroom_records.attachment_records_deleted == []
    assert context.files_deleted_from_the_payload_store == []
    assert context.prune_report["mode"] == "dry-run", context.prune_report


@then('the prune names "{command}" as the next command')
def prune_names_the_next_command(context, command):
    assert context.prune_report["next"] == command, context.prune_report
