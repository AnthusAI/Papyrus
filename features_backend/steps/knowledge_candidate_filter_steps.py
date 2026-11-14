from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_snapshot import commands  # noqa: E402
from papyrus_content.knowledge_snapshot.candidate_filter_test import DOCUMENTS, typed_items  # noqa: E402
from papyrus_content.knowledge_snapshot.reference_documents import ReferenceDocument, ReferenceText, write_documents_file  # noqa: E402


def publish(context, *flags):
    context.error, context.plan = None, {}
    captured = io.StringIO()
    try:
        with mock.patch.object(commands, "create_authoring_client", lambda *args, **kwargs: (context.client, {})), contextlib.redirect_stdout(captured):
            commands.knowledge_publish_run(["--entities", str(context.entities_file), "--reference-documents", str(context.documents_file), "--apply", "--json", *flags])
        context.plan = json.loads(captured.getvalue())
    except ValueError as error:
        context.error = str(error)


@given('forty documents whose extraction proposes "attachments", "shows", "material", "curation", "GPT-4", "dark patterns" and "confinement problem"')
def step_documents(context):
    documents = [ReferenceDocument(f"reference-{n}", f"lineage-{n}", f"Paper {n}", f"https://example.org/{n}", None, ReferenceText("", "")) for n in range(DOCUMENTS)]
    context.documents_file = context.work / "run" / "reference-documents.json"
    write_documents_file(context.documents_file, documents)
    context.entities_file = context.work / "run" / "entities.json"
    context.entities_file.write_text(json.dumps({"schema_version": 1, "items": typed_items()}))


def declare(context, kinds):
    context.vocabulary_file = context.work / "run" / "vocabulary.yml"
    context.vocabulary_file.write_text("entity_kinds:\n" + "".join(f"  - {{key: {kind}, label: {kind}}}\n" for kind in kinds))


@given('the site\'s entity vocabulary declares the kinds "{first}" and "{second}"')
def step_vocabulary(context, first, second):
    declare(context, [first, second])


@given('the site\'s entity vocabulary declares the kinds "{only}" only')
def step_vocabulary_only(context, only):
    declare(context, [only])


@given("the extraction was imported before the filter existed")
def step_before(context):
    publish(context)
    context.earlier = {row["id"]: dict(row) for row in context.client.rows["SemanticNode"].values()}


@when("the extraction is imported with the site's vocabulary")
def step_with(context):
    publish(context, "--vocabulary", str(context.vocabulary_file))


@when("the extraction is imported without the site's files")
def step_without(context):
    publish(context)


def names(context) -> set[str]:
    return {row["displayName"] for row in context.client.rows.get("SemanticNode", {}).values()}


def quoted(text: str) -> list[str]:
    return [part for part in text.replace(" and ", ", ").replace('"', "").split(", ") if part]


@then('the map has the concepts {listed}')
def step_has_many(context, listed):
    assert context.error is None, context.error
    assert set(quoted(listed)) <= names(context), names(context)


@then('the map has the concept "{name}"')
def step_has(context, name):
    assert name in names(context)


@then('the map has no concept {listed}')
def step_has_none(context, listed):
    found = names(context)
    assert not [name for name in quoted(listed.replace(" or ", ", ")) if name in found], found


@then("the concepts on the map are exactly the ones the earlier import made")
def step_unchanged(context):
    assert {row["id"]: dict(row) for row in context.client.rows["SemanticNode"].values()} == context.earlier


@then('the import report lists {listed} as dropped common words')
def step_report_common(context, listed):
    dropped = {entry["name"]: entry["reason"] for entry in context.plan["dropped"]}
    assert {name: dropped.get(name) for name in quoted(listed)} == {name: "common word" for name in quoted(listed)}, dropped


@then("the import report counts {number:d} dropped common words")
def step_report_count(context, number):
    assert context.plan["counts"]["candidatesDropped.common word"] == number, context.plan["counts"]


@then("the import report lists no dropped candidate")
def step_report_none(context):
    assert context.plan["dropped"] == []


@then('the import report lists "{name}" as dropped for a kind that is not in the vocabulary')
def step_report_kind(context, name):
    assert {(entry["name"], entry["reason"]) for entry in context.plan["dropped"]} >= {(name, "kind not in the vocabulary")}, context.plan["dropped"]
