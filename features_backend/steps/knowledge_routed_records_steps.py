from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.ideas import trends  # noqa: E402
from papyrus_content.knowledge_snapshot import commands  # noqa: E402
from papyrus_content.knowledge_snapshot.builder import INDEX_FILE  # noqa: E402
from papyrus_content.knowledge_snapshot.commands_test import HUB_CORPUS, routed_story  # noqa: E402



def command(context, function, *flags):
    from unittest import mock

    context.error = None
    try:
        with mock.patch.object(commands, "create_authoring_client", lambda *args, **kwargs: (context.client, {})):
            function(list(flags))
    except ValueError as error:
        context.error = str(error)


def step_export(context, key, source, day):
    command(
        context, commands.knowledge_corpus_export, "--out", str(context.out), "--monitor-sources", source, "--corpus-key", key, "--as-of", day,
        "--monitor-records-out", str(context.records_file),
    )


def entity_file(context, key):
    return json.loads((context.site / "_data" / "knowledge" / "entities" / f"{key}.json").read_text())

MENTION = "knowledge.record_mention"


@given('the router delivered the story "{slug}" titled "{title}" on {day:Day}')
def step_story(context, slug, title, day):
    routed_story(context.client, slug, title, f"{day}T09:00:00Z")


@given('the router delivered the story "{slug}" titled "{title}" on {day:Day} and a person rejected it')
def step_story_rejected(context, slug, title, day):
    routed_story(context.client, slug, title, f"{day}T09:00:00Z", status="rejected")


@given('the router delivered the story "{slug}" titled "{title}" on {day:Day} through the monitor "{monitor}"')
def step_story_monitor(context, slug, title, day, monitor):
    routed_story(context.client, slug, title, f"{day}T09:00:00Z", monitor=monitor)


@given('a Reference "{slug}" with no monitor behind it, titled "{title}", is in the corpus')
def step_unrouted(context, slug, title):
    context.client.rows.setdefault("Reference", {})[f"reference-{slug}"] = {
        "id": f"reference-{slug}", "lineageId": f"lineage-{slug}", "versionState": "current", "corpusId": HUB_CORPUS, "curationStatus": "accepted",
        "sourceUri": f"https://example.org/{slug}", "title": title, "sourcePublishedAt": "2026-10-14T09:00:00Z",
    }


@given("the map has the accepted entities of the site's items")
def step_map(context):
    command(context, commands.knowledge_publish_run, "--apply")
    assert context.error is None, context.error


@given("the corpus was exported with the routed records")
def step_export_routed(context):
    step_export(context, context.key, "routed", "2026-10-19")
    assert context.error is None, context.error


@given('the corpus was exported with the monitor sources "{first}" and "{second}"')
def step_export_both(context, first, second):
    step_export(context, context.key, f"{first},{second}", "2026-10-19")
    assert context.error is None, context.error


@then("the monitor records are {expected}")
def step_records_are(context, expected):
    found = {(entry["referenceId"], entry["source"]) for entry in json.loads(context.records_file.read_text())["records"]}
    wanted = {(f"reference-{slug}", monitor) for slug, monitor in (part.strip().split(" from ") for part in expected.replace(" and ", ",").split(","))}
    wanted = {(reference.replace('"', ""), monitor.replace('"', "")) for reference, monitor in wanted}
    assert found == wanted, found


def mentions(context, slug):
    rows = [
        row for row in context.client.rows["SemanticRelation"].values()
        if row["subjectLineageId"] == f"lineage-{slug}" and row["predicate"] == "mentions" and row["relationState"] == "current"
    ]
    return rows


def keys_of(context, slug):
    nodes = {row["lineageId"]: row["nodeKey"] for row in context.client.rows["SemanticNode"].values()}
    return sorted(nodes[row["objectLineageId"]] for row in mentions(context, slug))


@then('the story "{slug}" is linked to "{key}" and to nothing else')
def step_linked_one(context, slug, key):
    assert keys_of(context, slug) == [key], keys_of(context, slug)


@then('the story "{slug}" is linked to nothing')
def step_linked_none(context, slug):
    assert keys_of(context, slug) == []


@then('those links are confirmed, marked as monitor links, with the provenance "{provenance}"')
def step_link_metadata(context, provenance):
    for row in mentions(context, "cloning"):
        metadata = json.loads(row["metadata"])
        assert (metadata["kind"], metadata["linkSource"], metadata["confirmed"], metadata["provenance"]) == (MENTION, "monitor", True, provenance), metadata


@given('an editor accepted the entity "{name}" on the map')
def step_accept_entity(context, name):
    key = "concept--" + name.lower().replace(" ", "-")
    template = next(iter(context.client.rows["SemanticNode"].values()))
    row = {
        **template, "id": f"semantic-node-{key}-v1", "lineageId": f"semantic-node-{key}", "nodeKey": key, "nodeKind": "concept",
        "displayName": name, "aliases": [], "status": "accepted",
    }
    context.client.rows["SemanticNode"][row["id"]] = row


@when("the routed records are exported again and the run is imported again with the import ledger")
def step_import_again(context):
    step_export(context, context.key, "routed", "2026-10-19")
    command(context, commands.knowledge_publish_run, "--monitor-records", str(context.records_file), "--monitor-ledger", str(context.ledger_file), "--apply")
    assert context.error is None, context.error


@then('the entity "{key}" counts {records:d} record and {items:d} items in all')
def step_counts_one(context, key, records, items):
    row = context.index[key]
    assert (row["recordCount"], row["itemCount"]) == (records, items), row


@then('the entity "{key}" lists the story "{slug}" with the address "{url}" apart from its items')
def step_lists_story(context, key, slug, url):
    detail = entity_file(context, key)
    assert [row["url"] for row in detail["relatedRecords"]] == [url] and not any(row["url"] == url for row in detail["relatedItems"])


@then('the story "{slug}" is cited as "{provenance}"')
def step_cited(context, slug, provenance):
    [row] = entity_file(context, "maker--acme")["relatedRecords"]
    assert row["provenance"] == provenance and row["source"] == "hn", row


@when('the trend signals are built for "{key}"')
def step_signals(context, key):
    context.fetched = []
    snapshot = trends.load_snapshot(str(context.site / "_data" / "knowledge"))
    chosen = {"anchors": [{"key": key, "window": {"windowWeeks": 4, "count": 0, "baselineWeeks": 4, "baselineCount": 0}}], "context": []}
    context.signals = {signal["id"]: signal for signal in trends.build_signals(snapshot, lambda url: context.fetched.append(url) or "# Page\n\nSummary.\n", selection=chosen)}


@then('the signal for "{key}" has the story "{title}" from "{origin}" dated {day}')
def step_story_signal(context, key, title, origin, day):
    context.release = next(item for item in context.signals[f"entity:{key}"]["items"] if item["title"] == title)
    assert (context.release["from"], context.release["date"]) == (origin, day)


@then("no page of that story is fetched")
def step_story_not_fetched(context):
    assert not [url for url in context.fetched if "example.org" in url]


def hub_snapshot(context, name):
    out = context.work / name
    command(context, commands.knowledge_publish_run, "--monitor-records", str(context.records_file), "--apply")
    command(context, commands.knowledge_snapshot, "--out", str(out), "--as-of", "2026-10-19", "--entity-href", "/wiki/{slug}/", "--monitor-records", str(context.records_file))
    assert context.error is None, context.error
    return {str(path.relative_to(out)): path.read_bytes() for path in sorted(out.rglob("*")) if path.is_file()}


@given("the snapshot of the Hub records alone was taken as of {day}")
def step_first_snapshot(context, day):
    step_export(context, context.key, "huggingface", day)
    context.first_snapshot = hub_snapshot(context, "first")


@when("the snapshot of the Hub records alone is taken as of {day} again")
def step_second_snapshot(context, day):
    context.second_snapshot = hub_snapshot(context, "second")


@then("the two snapshots are byte for byte the same")
def step_same(context):
    assert context.first_snapshot and context.second_snapshot == context.first_snapshot


@then("no review request was raised for a routed story")
def step_no_suggestion(context):
    assert not context.site.created and context.suggestion.get("status") in {"none", "requested"}, (context.site.created, context.suggestion)
