from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_snapshot import commands  # noqa: E402
from papyrus_content.knowledge_snapshot.reference_documents import biblicus_reference_id  # noqa: E402
from papyrus_content.knowledge_snapshot.reference_documents_test import FakeStore, reference  # noqa: E402


def command(context, function, *flags):
    context.error = None
    try:
        with mock.patch.object(commands, "create_authoring_client", lambda *args, **kwargs: (context.client, {})):
            function(list(flags))
    except ValueError as error:
        context.error = str(error)


SOURCE_DAY = "T09:00:00Z"


def store_of(context) -> FakeStore:
    if not hasattr(context, "texts"):
        context.texts = {}
    return context.texts


def add_reference(context, name, text, **options):
    reference(context.client, name, **options)
    if text is not None:
        store_of(context)[f"reference-{name}"] = (f"etag-{name}-{len(text)}", text)


@given('the corpus holds the Reference "{name}" with the extracted text "{text}" dated {day:Day}')
def step_with_text(context, name, text, day):
    add_reference(context, name, text, published=f"{day}{SOURCE_DAY}")


@given('the corpus holds the Reference "{name}" with the extracted text "{text}" with no source date')
def step_undated(context, name, text):
    add_reference(context, name, text, published=None)


@given('the corpus holds the Reference "{name}" with no extracted text')
def step_stub(context, name):
    add_reference(context, name, None)


@given('the corpus holds the Reference "{name}" with the extracted text "{text}" which a person rejected')
def step_refused(context, name, text):
    add_reference(context, name, text, status="rejected")


def export(context, *flags, with_documents=True):
    context.store = FakeStore(dict(store_of(context)))
    context.documents_file = context.work / "run" / "reference-documents.json"
    extra = ["--reference-documents-bucket", "media", "--reference-documents-out", str(context.documents_file)] if with_documents else []
    with mock.patch.object(commands, "S3TextStore", lambda bucket, key, extractor: context.store):
        command(context, commands.knowledge_corpus_export, "--out", str(context.out), "--corpus-key", context.key, *extra, *flags)
    assert context.error is None, context.error


@given("the corpus was exported with the Reference documents")
@when("the corpus is exported with the Reference documents")
def step_export(context):
    export(context)


@when("the corpus is exported with the Reference documents again")
def step_export_again(context):
    export(context)


@when("the corpus is exported without the Reference documents")
def step_export_without(context):
    export(context, with_documents=False)


@when('the corpus is exported with the Reference documents and the monitor source "{source}"')
def step_export_records(context, source):
    export(context, "--monitor-sources", source, "--as-of", "2026-10-19", "--monitor-records-out", str(context.records_file))


def documents(context) -> set[str]:
    return {path.name[len("ref-reference-"):-3] for path in context.out.glob("ref-*.md")}


@then('the corpus holds the item files "{first}" and "{second}"')
def step_items(context, first, second):
    assert {path.stem.removeprefix("item-") for path in context.out.glob("item-*.md")} == {first, second}


@then('the corpus holds the Reference documents "{first}" and "{second}"')
def step_documents(context, first, second):
    assert documents(context) == {first, second}, documents(context)


@then('the corpus holds the Reference documents "{only}" only')
def step_documents_only(context, only):
    assert documents(context) == {only}, documents(context)


@then("the corpus holds no Reference document")
def step_no_documents(context):
    assert documents(context) == set()


@then("there is no document for the Reference {first}, the Reference {second} or the story {third}")
def step_not_documents(context, first, second, third):
    found = documents(context)
    for name in (first, second, third):
        assert name.strip('"') not in found, name
    assert not list(context.out.glob("record-*.md"))


def document_of(context, name):
    head, _, body = (context.out / f"ref-reference-{name}.md").read_text(encoding="utf-8")[4:].partition("\n---\n")
    return yaml.safe_load(head), body


@then('the document of "{name}" cites "{url}" and is dated {day:Day}')
def step_cites(context, name, url, day):
    meta, _ = document_of(context, name)
    assert (meta["url"], meta["dates"]["published_at"][:10]) == (url, day), meta
    assert meta["biblicus"]["id"] == biblicus_reference_id(f"reference-{name}")


@then('the document of "{name}" has the title "{title}" and the body "{body}"')
def step_title_body(context, name, title, body):
    meta, text = document_of(context, name)
    assert meta["title"] == title and text == f"# {title}\n\n{body}\n", text


@then('the document of "{name}" has no date')
def step_no_date(context, name):
    assert "dates" not in document_of(context, name)[0]


@then("no extracted text was downloaded")
def step_no_download(context):
    assert context.store.reads == [], context.store.reads


@then('only the extracted text of "{name}" was downloaded')
def step_only_download(context, name):
    assert context.store.reads == [f"reference-{name}"], context.store.reads


@when('the extracted text of "{name}" changes to "{text}"')
def step_change(context, name, text):
    store_of(context)[f"reference-{name}"] = (f"etag-{name}-changed", text)


@when('a person rejects the Reference "{name}"')
def step_reject(context, name):
    context.client.rows["Reference"][f"reference-{name}"]["curationStatus"] = "rejected"


@when('the entity "{entity}" is extracted from the document of "{name}" and the run is imported')
@given('the entity "{entity}" was extracted from the document of "{name}" and imported')
def step_extracted(context, entity, name):
    typed = {
        "schema_version": 1,
        "items": [
            {
                "item_id": biblicus_reference_id(f"reference-{name}"),
                "entities": [{"id": "e1", "kind": "model", "text": entity, "state": "proposed", "span": {"start": 0, "end": 6}, "score": 0.9}],
                "relations": [],
            }
        ],
    }
    context.typed_file = context.work / "run" / "entities.json"
    context.typed_file.write_text(json.dumps(typed))
    command(context, commands.knowledge_publish_run, "--entities", str(context.typed_file), "--reference-documents", str(context.documents_file), "--apply")
    assert context.error is None, context.error


def node_of(context, entity):
    return next(row for row in context.client.rows["SemanticNode"].values() if row["displayName"] == entity)


def mentions_of(context, entity):
    node = node_of(context, entity)
    return [row for row in context.client.rows["SemanticRelation"].values() if row["objectLineageId"] == node["lineageId"] and row["predicate"] == "mentions"]


@then('the entity "{entity}" is mentioned by the Reference "{name}" and by no item')
def step_mentioned(context, entity, name):
    rows = mentions_of(context, entity)
    assert [(row["subjectKind"], row["subjectId"]) for row in rows] == [("reference", f"reference-{name}")], rows


@then("that link is an unconfirmed extractor link marked as a Reference mention")
def step_link(context):
    metadata = json.loads(mentions_of(context, "Tern 3")[0]["metadata"])
    assert (metadata["kind"], metadata["linkSource"], metadata["confirmed"]) == ("knowledge.reference_mention", "extractor", False), metadata


@when('an editor accepts the entity "{entity}"')
@given('an editor accepted the entity "{entity}" through the review')
def step_accept(context, entity):
    command(context, commands.knowledge_entities_accept, "--key", node_of(context, entity)["nodeKey"], "--actor", "ai")
    assert context.error is None, context.error


@given('the entity "{entity}" was extracted from the document of "{name}", imported and accepted')
def step_extracted_accepted(context, entity, name):
    step_extracted(context, entity, name)
    step_accept(context, entity)


def take_snapshot(context, *flags):
    out = context.work / f"site-{len(flags)}"
    command(context, commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19", "--entity-href", "/wiki/{slug}/", *flags)
    assert context.error is None, context.error
    context.site = out


@when("the snapshot is taken with the Reference documents")
def step_snapshot_with(context):
    take_snapshot(context, "--reference-documents", str(context.documents_file))


@when("the snapshot is taken without the Reference documents")
def step_snapshot_without(context):
    take_snapshot(context)


def entity_file_of(context, entity):
    return context.site / "_data" / "knowledge" / "entities" / f"{node_of(context, entity)['nodeKey']}.json"


@then('the entity file for "{entity}" lists the Reference "{name}" as a source with its address')
def step_lists(context, entity, name):
    related = json.loads(entity_file_of(context, entity).read_text())["relatedItems"]
    assert [(item["title"], item["url"]) for item in related] == [(f"Paper {name}", f"https://example.org/{name}.pdf")], related


@then('the entity "{entity}" has a wiki page')
def step_page(context, entity):
    assert json.loads(entity_file_of(context, entity).read_text())["href"]


@then('there is no entity file for "{entity}"')
def step_no_file(context, entity):
    assert not entity_file_of(context, entity).exists()
