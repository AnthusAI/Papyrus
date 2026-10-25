from __future__ import annotations

import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import parse
from behave import given, register_type, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.ideas import trends  # noqa: E402
from papyrus_content.knowledge_snapshot import commands  # noqa: E402
from papyrus_content.knowledge_snapshot.actors import decode_review  # noqa: E402
from papyrus_content.knowledge_snapshot.builder import INDEX_FILE  # noqa: E402
from papyrus_content.knowledge_snapshot.commands_test import FakeClient, Projector, hub_model, published_row, with_published_rows  # noqa: E402
from papyrus_content.knowledge_wiki.sync import entity_specs  # noqa: E402


@parse.with_pattern(r"\d{4}-\d{2}-\d{2}")
def parse_day(text):
    return text


register_type(Day=parse_day)


def names(text: str) -> list[str]:
    return [part.strip().strip('"') for part in text.replace(" and ", ",").split(",") if part.strip()]


@contextmanager
def backend(context):
    with mock.patch.object(commands, "create_authoring_client", lambda *args, **kwargs: (context.client, {})):
        yield


def command(context, function, *flags):
    context.error = None
    try:
        with backend(context):
            function(list(flags))
    except ValueError as error:
        context.error = str(error)


@given('a site "{key}" with the published items "{first}" and "{second}"')
def step_site(context, key, first, second):
    context.work = Path(tempfile.mkdtemp())
    context.tmp_dirs.append(context.work)
    context.key = key
    context.client = FakeClient(
        [
            published_row(first, "2026-10-13T08:00:00Z", entities=[("maker", "Acme")]),
            published_row(second, "2026-10-06T08:00:00Z", entities=[("maker", "Acme")]),
        ]
    )
    with_published_rows(context.client)
    context.records_file = context.work / "run" / "monitor-records.json"
    context.out = context.work / "raw"


@given('the Hugging Face monitor delivered "{model}" released on {day:Day}')
def step_delivered(context, model, day):
    hub_model(context.client, model, f"{day}T08:00:00Z")


@given('the Hugging Face monitor delivered "{model}" released on {day:Day} and built on "{first}" as {first_kind} and on "{second}" as {second_kind}')
def step_delivered_built_on(context, model, day, first, first_kind, second, second_kind):
    hub_model(context.client, model, f"{day}T08:00:00Z", bases=[(first, first_kind), (second, second_kind)])


@given('the Hugging Face monitor delivered "{model}" released on {day:Day} under the licence "{licence}" for the task "{task}"')
def step_delivered_other(context, model, day, licence, task):
    hub_model(context.client, model, f"{day}T08:00:00Z", license=licence, pipelineTag=task)


@given('the Hugging Face monitor delivered "{model}" released on {day:Day} and a person rejected it')
def step_delivered_rejected(context, model, day):
    hub_model(context.client, model, f"{day}T08:00:00Z", status="rejected")


@when("the corpus is exported without monitor sources")
def step_export_plain(context):
    command(context, commands.knowledge_corpus_export, "--out", str(context.out))


@when('the corpus is exported for "{key}" with the monitor source "{source}" as of {day}')
def step_export(context, key, source, day):
    command(
        context, commands.knowledge_corpus_export, "--out", str(context.out), "--monitor-sources", source, "--corpus-key", key, "--as-of", day,
        "--monitor-records-out", str(context.records_file),
    )


@given("the corpus was exported with the monitor records")
def step_export_given(context):
    step_export(context, context.key, "huggingface", "2026-10-19")
    assert context.error is None, context.error


@then('the corpus holds the item documents "{first}" and "{second}" and no record document')
def step_items_only(context, first, second):
    found = sorted(path.name for path in context.out.iterdir())
    assert found == [f"item-{first}.md", f"item-{second}.md"], found


@then("the corpus holds the record documents {models}")
def step_records(context, models):
    found = sorted(path.name for path in context.out.glob("record-*.md"))
    assert found == sorted(f"record-reference-{model.replace('/', '--')}.md" for model in names(models)), found


def record_text(context, model):
    return (context.out / f"record-reference-{model.replace('/', '--')}.md").read_text(encoding="utf-8")


@then('the record document "{model}" is dated {stamp} and marked kind monitor-record')
def step_record_dated(context, model, stamp):
    text = record_text(context, model)
    assert "kind: monitor-record" in text and stamp in text, text


@then('the record document "{model}" says it is built on "{base}" and holds no model card text')
def step_record_body(context, model, base):
    text = record_text(context, model)
    assert f"Built on {base} (finetune)" in text and "model card" not in text.lower()


@then("the monitor records file holds {count:d} records")
def step_file(context, count):
    assert len(json.loads(context.records_file.read_text())["records"]) == count


@then('the export is refused with "{message}"')
def step_refused(context, message):
    assert context.error and message in context.error, context.error


@when("the run is imported with the monitor records")
@given("the run was imported with the monitor records")
def step_import(context):
    command(context, commands.knowledge_publish_run, "--monitor-records", str(context.records_file), "--apply")
    assert context.error is None, context.error


@then('the entity "{key}" exists, accepted by the "{actor}"')
def step_entity_accepted(context, key, actor):
    node = next(row for row in context.client.rows["SemanticNode"].values() if row["nodeKey"] == key)
    marks = decode_review(node["changeReason"])
    assert node["status"] == "accepted" and marks.accepted_by and marks.accepted_by.name == actor and marks.accepted_by.actor == "ai"


@then("the entities {keys} exist")
def step_entities(context, keys):
    present = {row["nodeKey"] for row in context.client.rows["SemanticNode"].values()}
    missing = [key for key in names(keys) if key not in present]
    assert not missing, missing


@then('there is no entity "{key}"')
def step_no_entity(context, key):
    assert key not in {row["nodeKey"] for row in context.client.rows["SemanticNode"].values()}


def lineage(model):
    return f"semantic-node-model--{model.replace('/', '-')}"


@then('"{model}" is built on "{base}" as {subtype}, confirmed, with the evidence "{evidence}" and the provenance "{provenance}"')
def step_built_on(context, model, base, subtype, evidence, provenance):
    [relation] = [row for row in context.client.rows["SemanticRelation"].values() if row["predicate"] == "built_on" and row["subjectLineageId"] == lineage(model)]
    metadata = json.loads(relation["metadata"])
    assert relation["objectLineageId"] == lineage(base)
    assert (metadata["confirmed"], metadata["subtype"], metadata["evidence"], metadata["provenance"]) == (True, subtype, evidence, provenance)


@then('there is no relation for the base model "{base}" because it is not on the map')
def step_off_map(context, base):
    assert not [row for row in context.client.rows["SemanticRelation"].values() if row["predicate"] == "built_on" and base.replace("/", "-") in row["objectLineageId"]]


@then("nothing was written")
def step_nothing(context):
    before = len(context.client.writes)
    command(context, commands.knowledge_publish_run, "--monitor-records", str(context.records_file), "--apply")
    assert len(context.client.writes) == before


@when("the snapshot is built as of {day} with the monitor records")
@given("the snapshot was built as of {day} with the monitor records")
def step_snapshot(context, day):
    context.site = context.work / "site"
    command(context, commands.knowledge_snapshot, "--out", str(context.site), "--as-of", day, "--entity-href", "/wiki/{slug}/", "--monitor-records", str(context.records_file))
    assert context.error is None, context.error
    context.index = {row["key"]: row for row in json.loads((context.site / INDEX_FILE).read_text())["entities"]}


def entity_file(context, key):
    return json.loads((context.site / "_data" / "knowledge" / "entities" / f"{key}.json").read_text())


@then('the entity "{key}" counts {records:d} records, {items:d} items in all, and links to no page')
def step_counts(context, key, records, items):
    row = context.index[key]
    assert (row["recordCount"], row["itemCount"], row["href"]) == (records, items, None), row


@then('the entity "{key}" lists the record "{model}" with the address "{url}" apart from its items')
def step_lists(context, key, model, url):
    detail = entity_file(context, key)
    assert [row["url"] for row in detail["relatedRecords"] if row["title"] == model] == [url]
    assert all(row["url"].startswith("/") for row in detail["relatedItems"])


@then('the entity "{key}" is not on the map')
def step_not_on_map(context, key):
    assert key not in context.index


@then('the entity "{key}" shows the built-on neighbour "{other}" as {subtype}')
def step_neighbour(context, key, other, subtype):
    [row] = [row for row in entity_file(context, key)["neighbours"] if row["relation"] == "built_on"]
    assert (row["key"], row["subtype"]) == (other, subtype)


@when("the wiki sync plans its pages with the monitor records")
def step_wiki(context):
    options = {"monitor-records": str(context.records_file)}
    context.data = commands.load_knowledge_data(context.client, Projector(), options)
    context.pages = {spec.key for spec in entity_specs(context.data, {})}


@then('there is no wiki page for "{key}"')
def step_no_page(context, key):
    assert key not in context.pages and "maker--acme" in context.pages, context.pages


@when("the trend signals are built from the published snapshot")
def step_signals(context):
    fetched = []
    context.fetched = fetched
    snapshot = trends.load_snapshot(str(context.site / "_data" / "knowledge"))
    context.signals = {signal["id"]: signal for signal in trends.build_signals(snapshot, lambda url: fetched.append(url) or "# Page\n\nSummary.\n")}


@then('the signal for "{key}" has the release "{model}" from the Hugging Face Hub dated {day}')
def step_release(context, key, model, day):
    context.release = next(item for item in context.signals[f"entity:{key}"]["items"] if item["title"] == model)
    assert (context.release["from"], context.release["date"]) == ("from the Hugging Face Hub", day)


@then("that release carries its own summary and no page of it is fetched")
def step_release_summary(context):
    assert "released 2026-10-14" in context.release["summary"]
    assert not [url for url in context.fetched if "huggingface.co" in url]


# -- promotion and the weekly suggestion --------------------------------------------------------------------------------
import datetime as dt  # noqa: E402

from papyrus_content import references_commands  # noqa: E402
from papyrus_content.knowledge_cloud.fakes import make_run  # noqa: E402
from papyrus_content.knowledge_cloud.stages import suggest_promotions  # noqa: E402
from papyrus_content.knowledge_snapshot.monitor_records import read_records  # noqa: E402


def promote(context, model, section):
    reference = f"reference-{model.replace('/', '--')}"
    with mock.patch.object(references_commands, "create_authoring_client", lambda *args, **kwargs: (context.client, {})):
        references_commands.references_promote([reference, "--section", section])


@when('a person promotes "{model}" to the section "{section}"')
@given('a person promoted "{model}" to the section "{section}"')
def step_promote(context, model, section):
    promote(context, model, section)
    context.item_id = f"item-{section}-{model.replace('/', '-')}"


@then('a draft item "{item_id}" exists in the section "{section}"')
def step_draft(context, item_id, section):
    item = context.client.rows["Item"][item_id]
    assert (item["status"], item["section"], item["type"]) == ("draft", section, "article")


@then('the draft carries the source link "{url}", the structured facts and the entities of the record')
def step_draft_fields(context, url, ):
    import yaml

    item = context.client.rows["Item"][context.item_id]
    metadata = item["metadata"] if isinstance(item["metadata"], dict) else json.loads(item["metadata"])
    front = yaml.safe_load(metadata["frontMatterYaml"])
    assert front["sources"][0]["url"] == url and front["monitorRecord"]["license"] == "apache-2.0"
    assert {"kind": "maker", "name": "org"} in front["entities"] and url in item["bodyMarkus"]


@then("nothing is published and the Reference is still pending")
def step_unpublished(context):
    assert not [row for row in context.client.rows.get("PublishedItem", {}).values() if row.get("sourceItemId") == context.item_id]
    assert context.client.rows["Reference"]["reference-org--tuned"]["curationStatus"] == "pending"


@given("the editor rewrote the draft")
def step_rewrite(context):
    context.client.rows["Item"][context.item_id]["bodyMarkus"] = "The editor wrote this.\n"


@then("the draft still holds the editor's text")
def step_kept(context):
    assert context.client.rows["Item"][context.item_id]["bodyMarkus"] == "The editor wrote this.\n"


class ReviewSite:
    def __init__(self, fail=False):
        self.fail, self.created = fail, {}

    def list_records(self, model):
        return []

    def get_record(self, model, record_id):
        return self.created.get(record_id)

    def create_record(self, model, row):
        if self.fail:
            raise RuntimeError("ReviewRequest is not in this schema")
        self.created[row["id"]] = row


def suggestion_context(context, count):
    import boto3  # noqa: F401
    from moto import mock_aws

    context.mock = mock_aws()
    context.mock.start()
    context.add_cleanup(context.mock.stop)
    import os

    for name, value in {"AWS_ACCESS_KEY_ID": "t", "AWS_SECRET_ACCESS_KEY": "t", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        os.environ.setdefault(name, value)
    run, _ = make_run(context.work / "cloud", {"KNOWLEDGE_MONITOR_SOURCES": "huggingface", "KNOWLEDGE_MONITOR_SUGGESTIONS": str(count)})
    records = read_records(context.records_file)
    from papyrus_content.knowledge_snapshot.monitor_records import write_records

    write_records(run.monitor_records, records, as_of=dt.date(2026, 10, 26), sources=("huggingface",))
    return run


@when("the weekly suggestion runs for the {count:d} records the Hub shows the most interest in")
def step_suggest(context, count):
    context.run_ = suggestion_context(context, count)
    context.site = ReviewSite()
    context.suggestion = suggest_promotions(context.run_, context.site)


@then('one soft review request lists "{first}" and "{second}" with their reference ids, the model id deciding between records that tie')
def step_request(context, first, second):
    [request] = context.site.created.values()
    links = json.loads(request["links"]) if isinstance(request["links"], str) else request["links"]
    labels = [link["label"] for link in links]
    assert request["mode"] == "soft_review" and len(labels) == 2, request
    assert all(f"({'reference-' + model.replace('/', '--')})" in " ".join(labels) for model in (first, second)), labels


@then("running the suggestion again raises no second request")
def step_idempotent(context):
    suggest_promotions(context.run_, context.site)
    assert len(context.site.created) == 1


@when("the weekly suggestion runs on a site without review requests")
def step_suggest_failing(context):
    context.run_ = suggestion_context(context, 2)
    context.suggestion = suggest_promotions(context.run_, ReviewSite(fail=True))


@then("the suggestion says it was not raised and the run goes on")
def step_not_raised(context):
    assert context.suggestion["status"] == "not_raised"
