import json
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys

from behave import given, then, when

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_monitoring_intake as intake_tests  # noqa: E402
from papyrus_content.knowledge_snapshot.monitor_records import load_monitor_records  # noqa: E402
from papyrus_content.monitor_delivery_backfill import run_backfill  # noqa: E402
from papyrus_content.monitoring import Monitor, SourceItem  # noqa: E402
from papyrus_content.monitoring_intake import ReferenceIntake  # noqa: E402

DETAILS = {"modelId": "org/tuned", "author": "org", "createdAt": "2026-10-14T08:00:00Z", "license": "apache-2.0", "likes": 3,
           "downloads": 10, "baseModels": []}


def _setup(context, monitor_id):
    client = intake_tests.Client()
    monitor = Monitor(monitor_id, "publication", "knowledge-corpus-publication", client.endpoint, Path("/tmp/monitor-state-unused"))
    context.client, context.saved = client, []
    context.sink = ReferenceIntake(client, monitor, auth_mode="iam", persist=lambda rows: context.saved.extend(rows))
    return monitor


def _provenance(monitor, item, **extra):
    return {**monitor.binding, "sourceId": item.source_id, "sourceItemUrl": item.source_item_url, "fingerprint": item.fingerprint,
            "observedAt": "2026-10-20T00:00:00Z", "revision": 1, **extra}


@given('a monitor named "{monitor_id}" delivering to a publication')
def monitor(context, monitor_id):
    context.monitor = _setup(context, monitor_id)


@when("it delivers a model with structured details")
def deliver_model(context):
    item = SourceItem("org--tuned", "org/tuned: text-to-speech model", "https://huggingface.co/org/tuned",
                      "https://huggingface.co/org/tuned", "2026-10-14T08:00:00Z", details=DETAILS)
    context.receipt = context.sink(item, _provenance(context.monitor, item))


@then('the new Reference names the monitor "{monitor_id}" and holds the details')
def names_monitor(context, monitor_id):
    row = context.client.references[0]
    assert row["discoveredByMonitorId"] == monitor_id and json.loads(row["discoveryDetails"]) == DETAILS


@then("the delivery wrote no Message and no relation")
def no_message(context):
    assert not [r for r in context.saved if r["modelName"] in {"Message", "SemanticRelation"}]


@then("the delivery receipt has no provenance Message id")
def no_receipt_id(context):
    assert "provenanceMessageId" not in context.receipt


@when("it delivers an item chosen by its direct rule")
def deliver_direct(context):
    item = SourceItem("1", "A story", "https://example.org/story", "https://news.ycombinator.com/item?id=1", None)
    context.sink(item, _provenance(context.monitor, item, machineDecision={"system": "direct", "rule": {"minLikes": 5}}))


@then("the new Reference holds the direct rule")
def holds_rule(context):
    assert json.loads(context.client.references[0]["discoveryRule"]) == {"system": "direct", "rule": {"minLikes": 5}}


@given("an accepted Reference that another monitor delivered first")
def accepted_other(context):
    context.client.references.append({"id": "reference-earlier-v1", "lineageId": "reference-earlier", "versionNumber": 1,
                                      "corpusId": "knowledge-corpus-publication", "versionState": "current",
                                      "sourceUri": "https://example.org/paper", "curationStatus": "accepted", "discoveredByMonitorId": "first"})
    context.before = deepcopy(context.client.references[0])


@when("it delivers the same document")
def deliver_same(context):
    item = SourceItem("123", "A source", "https://example.org/paper", "https://news.ycombinator.com/item?id=123", None)
    context.sink(item, _provenance(context.monitor, item))


@then("the Reference still names the first monitor")
def keeps_first(context):
    assert context.client.references[0]["discoveredByMonitorId"] == "first"


@then("no field of the Reference is written")
def nothing_written(context):
    assert context.client.updates == [] and context.client.writes == [] and context.client.references[0] == context.before


class _Backend:
    def __init__(self, references, relations=()):
        self.references, self.relations, self.updates, self.queries = references, list(relations), [], 0

    def list_records(self, model):
        return self.references

    def list_semantic_relations_by_object_state(self, state):
        self.queries += 1
        lineage = state.split("#")[1]
        return [row for row in self.relations if row["objectLineageId"] == lineage]

    def update_record(self, model, row):
        self.updates.append(row)
        next(r for r in self.references if r["id"] == row["id"]).update(row)


def _model_reference(**extra):
    return {"id": "reference-org--tuned", "lineageId": "lineage-org--tuned", "versionState": "current", "corpusId": "knowledge-corpus-shipped",
            "curationStatus": "pending", "sourceUri": "https://huggingface.co/org/tuned", "title": "org/tuned: text-to-speech model",
            "sourcePublishedAt": "2026-10-14T08:00:00.000Z", **extra}


@given("a delivered model Reference with the Hub details on it")
def delivered_model(context):
    context.backend = _Backend([_model_reference(discoveredByMonitorId="huggingface", discoveryDetails=json.dumps(DETAILS))])


@when("the monitor records are loaded")
def load(context):
    context.records, _ = load_monitor_records(context.backend, corpus_id="knowledge-corpus-shipped", sources=("huggingface",), as_of=date(2026, 10, 19))


@then("the record has the model id and the likes from the Reference")
def record(context):
    [one] = context.records
    assert one.model_id == "org/tuned" and one.details["likes"] == 3


@then("no relation was queried")
def no_query(context):
    assert context.backend.queries == 0


@given("a Reference delivered before the fields existed, with an old provenance relation")
def old_delivery(context):
    relation = {"predicate": "ingestion_rationale", "relationState": "current", "objectLineageId": "lineage-org--tuned",
                "importedAt": "2026-10-15T00:00:00Z", "metadata": json.dumps({"monitorId": "huggingface", "details": DETAILS})}
    context.backend = _Backend([_model_reference()], [relation])


@when("the monitor delivery backfill runs as a dry run")
def dry(context):
    context.result = run_backfill(context.backend, apply=False)


@then("it counts one planned update and writes nothing")
def planned(context):
    assert context.result["planned"] == 1 and context.backend.updates == []


@when("the monitor delivery backfill runs for real")
def real(context):
    context.result = run_backfill(context.backend, apply=True)


@then("the Reference names the monitor and holds the details from the old relation")
def backfilled(context):
    row = context.backend.references[0]
    assert row["discoveredByMonitorId"] == "huggingface" and json.loads(row["discoveryDetails"]) == DETAILS


@given("a publication that already holds {size:d} References")
def publication_holding(context, size):
    context.size = size
    context.tmp = Path("/tmp/monitor-state-unused")


@when("a run delivers {count:d} new items through one shared listing")
def deliver_through_shared_listing(context, count):
    from papyrus_content.monitoring_intake import ReferenceListing

    context.count = count
    context.each = intake_tests.CountingClient(context.size)
    context.shared = intake_tests.CountingClient(context.size)
    intake_tests.deliveries(context.each, None, count, context.tmp)
    context.receipts = intake_tests.deliveries(context.shared, ReferenceListing(context.shared), count, context.tmp)


@then("the table was read {pages:d} requests in all")
def table_read(context, pages):
    assert context.shared.requests == pages, context.shared.requests


@then("a run that read the table for each delivery would have made more than {pages:d} requests")
def per_delivery_cost(context, pages):
    assert context.each.requests > pages, (context.each.requests, pages)
    print(f"\n  {context.size} References, {context.count} deliveries: {context.each.requests} requests before, {context.shared.requests} now")  # noqa: T201


@then("the {count:d} items became {created:d} References")
def items_became_references(context, count, created):
    assert len({receipt["referenceId"] for receipt in context.receipts}) == created and len(context.shared.writes) == created


@when("a run delivers the same document twice through one shared listing")
def deliver_twice(context):
    from papyrus_content.monitoring_intake import ReferenceListing

    context.shared = intake_tests.CountingClient(context.size)
    listing = ReferenceListing(context.shared)
    monitor = Monitor("hn", "publication", "knowledge-corpus-publication", context.shared.endpoint, context.tmp)
    context.receipts = []
    for number in (1, 2):
        item = SourceItem(str(number), "Same document", "https://example.org/same", f"https://news.ycombinator.com/item?id={number}", None)
        context.receipts.append(ReferenceIntake(context.shared, monitor, auth_mode="iam", persist=lambda rows: None, listing=listing)(item, _provenance(monitor, item)))


@then("there is one new Reference and the second delivery reused it")
def one_new_reference(context):
    assert len(context.shared.writes) == 1 and context.receipts[1]["referenceReused"] is True
    assert context.receipts[0]["referenceId"] == context.receipts[1]["referenceId"]
