from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_snapshot import commands, reference_documents  # noqa: E402
from papyrus_content.knowledge_snapshot.accepted_reference_documents_test import TEXTS, attach_text, typed_run  # noqa: E402
from papyrus_content.knowledge_snapshot.reference_documents_test import reference  # noqa: E402



def command(context, function, *flags):
    context.error = None
    try:
        with mock.patch.object(commands, "create_authoring_client", lambda *args, **kwargs: (context.client, {})):
            function(list(flags))
    except ValueError as error:
        context.error = str(error)


def stub_downloads(context):
    if getattr(context, "downloads_stubbed", False):
        return
    context.downloads_stubbed = True
    TEXTS.clear()
    patcher = mock.patch.object(reference_documents, "download_attachment_buffer", lambda _client, attachment: TEXTS[attachment["id"]].encode("utf-8"))
    patcher.start()
    context.add_cleanup(patcher.stop)


def add(context, name, text, **options):
    stub_downloads(context)
    reference(context.client, name, **options)
    if text is not None:
        attach_text(context.client, name, text)


@given('the corpus accepted the Reference "{name}" with the curation text "{text}"')
def step_accepted(context, name, text):
    add(context, name, text)


@given('the corpus accepted the Reference "{name}" which the monitor "{monitor}" brought, with the curation text "{text}"')
def step_accepted_delivered(context, name, monitor, text):
    add(context, name, text, discoveredByMonitorId=monitor)


@given('the corpus accepted the Reference "{name}" but captured no curation text')
def step_accepted_no_text(context, name):
    add(context, name, None)


@given('the corpus holds the pending Reference "{name}" with the curation text "{text}"')
def step_pending(context, name, text):
    add(context, name, text, status="pending")


@given('the corpus holds the rejected Reference "{name}" with the curation text "{text}"')
def step_rejected(context, name, text):
    add(context, name, text, status="rejected")


@given("the corpus was exported from the accepted References")
@when("the corpus is exported from the accepted References")
def step_export(context):
    context.documents_file = context.work / "run" / "reference-documents.json"
    command(
        context, commands.knowledge_corpus_export, "--out", str(context.out), "--corpus-key", context.key, "--reference-documents-accepted",
        "--reference-documents-out", str(context.documents_file), "--monitor-sources", "routed", "--as-of", "2026-10-19",
        "--monitor-records-out", str(context.records_file),
    )


@when("an editor sends every Reference back to pending")
def step_pending_all(context):
    for row in context.client.rows["Reference"].values():
        row["curationStatus"] = "pending"


def held(context) -> set[str]:
    return {path.name[len("ref-reference-"):-3] for path in context.out.glob("ref-*.md")}


@then('the corpus holds the accepted Reference documents "{first}" and "{second}"')
@then('the corpus still holds the accepted Reference documents "{first}" and "{second}"')
def step_holds(context, first, second):
    assert held(context) == {first, second}, held(context)


@then('the accepted Reference "{name}" is a document and not a monitor record')
def step_not_record(context, name):
    assert name in held(context)
    records = {entry["referenceId"] for entry in json.loads(context.records_file.read_text())["records"]}
    assert f"reference-{name}" not in records, records


@then('the export report lists the Reference "{name}" with a reason saying it has no curation text')
def step_report(context, name):
    assert context.error is None, context.error
    report = json.loads(context.documents_file.read_text())["withoutText"]
    assert [(entry["referenceId"], "no curation text" in entry["reason"]) for entry in report] == [(f"reference-{name}", True)], report


@then("the export fails saying it found no accepted Reference with a text")
def step_fails(context):
    assert context.error and "found no accepted Reference with a text to read" in context.error, context.error


@when('the entity "{entity}" is extracted from the accepted Reference "{name}" and the run is imported')
def step_extracted(context, entity, name):
    context.typed_file = typed_run(context.work, f"reference-{name}")
    command(context, commands.knowledge_publish_run, "--apply")
    command(context, commands.knowledge_publish_run, "--entities", str(context.typed_file), "--reference-documents", str(context.documents_file), "--monitor-records", str(context.records_file), "--apply")
    assert context.error is None, context.error


@then('the entity "{entity}" is mentioned by the Reference "{name}" with a Reference mention link')
def step_mentioned(context, entity, name):
    node = next(row for row in context.client.rows["SemanticNode"].values() if row["displayName"] == entity)
    rows = [row for row in context.client.rows["SemanticRelation"].values() if row["objectLineageId"] == node["lineageId"] and row["predicate"] == "mentions"]
    assert [(row["subjectKind"], row["subjectId"]) for row in rows] == [("reference", f"reference-{name}")], rows
    assert json.loads(rows[0]["metadata"])["kind"] == "knowledge.reference_mention"
