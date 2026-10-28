"""Steps for features_backend/monitoring-enrich-before-decide.feature. In memory: no network, no AWS, no model."""

import json
import sys
from pathlib import Path

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_enrichment as te  # noqa: E402
import test_monitoring_router as tr  # noqa: E402
from curation_support import MemoryClient, MemoryStore  # noqa: E402
from papyrus_content import monitoring_enrichment as me, monitoring_router as mr, reference_curation as curation  # noqa: E402

ROW = ("MONITOR#hn", "ENRICH#101#000001")


def run(context, now=2000):
    context.result = tr.go(context.table_, context.store, context.cyclotron, now=now, enricher=context.enricher, appsync=lambda e: context.client)


def values(context):
    return [c[2]["payload"]["item"]["values"] for c in context.cyclotron.posts()]


@given("a live router with one collected story and an enrichment that can read the article")
def step_router(context):
    context.table_ = tr.collected_table(tr.ONE_FEED)
    context.store, context.cyclotron = tr.setup_router(context.table_)
    context.references = [{"id": f"reference-{p}-101", "lineageId": f"reference-{p}-101", "versionNumber": 1} for p in tr.PUBS]
    context.client = MemoryClient(context.references)
    context.stores = []
    context.original_store = me.AttachmentStore
    me.AttachmentStore = lambda c: context.stores.append(MemoryStore(c)) or context.stores[-1]
    context.add_cleanup(lambda: setattr(me, "AttachmentStore", context.original_store))
    context.article = te.ARTICLE
    context.enricher = te.enricher(te.good(context.article))


@given('the article source refuses the request as "{reason}"')
def step_refused(context, reason):
    context.enricher = te.enricher(te.failed(reason))


@given("the article source times out")
def step_timeout(context):
    context.enricher = te.enricher(te.failed(transient=True), te.failed(transient=True), te.failed(transient=True))


@given("the article is far longer than any size the router once cut to")
def step_long(context):
    context.article = "A sentence about transit that goes on and on. " * 5000
    context.enricher = te.enricher(te.good(context.article))


@when("the enriching router runs")
def step_run(context):
    run(context)


@when("the enriching router runs after the retry delay and the article source still times out until the last attempt")
def step_rerun(context):
    run(context, now=2400)
    run(context, now=3200)


@then("the story was read exactly once for all three publications")
def step_once(context):
    assert len(context.enricher.capture.calls) == 1 and len(context.cyclotron.posts()) == 3


@then('the story\'s enrichment is "{status}"')
def step_status(context, status):
    assert context.table_.items[ROW]["status"] == status and context.table_.items[ROW]["final"] is True


@then('the story\'s enrichment ended "{status}" because the capture failed as "{reason}"')
def step_status_reason(context, status, reason):
    step_status(context, status)
    assert context.table_.items[ROW]["curation"]["capture"]["reason"] == reason


@then("every decision request was sent after the enrichment finished")
def step_after(context):
    assert context.table_.items[ROW]["final"] is True and context.cyclotron.posts()
    assert context.table_.items[ROW]["completedAt"] and all(v["body"] for v in values(context))


@then("each decision request carries the summary and the full captured text")
def step_payload(context):
    assert values(context) and all(v["summary"] == te.SUMMARY and v["body"] == context.article for v in values(context))


@then("the request text is the title, the address, the summary and the captured text")
def step_text(context):
    for v in values(context):
        assert v["text"] == f"{v['title']}\n{v['url']}\n\n{v['summary']}\n\n{v['body']}"


@then('every delivered Reference has a "{status}" curation card holding the summary the lab was given')
def step_card(context, status):
    for reference in context.references:
        card = context.client.card(reference["id"])
        assert card["status"] == status and card["summary"]["text"] == values(context)[0]["summary"]


@then("every delivered Reference holds the same captured text the lab was given")
def step_copy(context):
    for store, reference in zip(context.stores, context.references):
        assert store.text(reference, "curation-text") == values(context)[0]["body"]


@then("the post-delivery curation has nothing left to do")
def step_nothing(context):
    for reference in context.references:
        plan = curation.plan_stages(context.client.card(reference["id"]), force=False, grobid_configured=False, now=me.utc_now(),
                                    summarizer_available=True)
        assert plan["outcome"] == "already_curated"


@then("each decision request carries only the title and the address")
def step_bare(context):
    assert values(context) and all(set(v) == {"title", "url", "source", "sourceItemUrl", "text"} and v["text"] == f"{v['title']}\n{v['url']}"
                                   for v in values(context))


@then("no decision request was sent")
def step_none(context):
    assert context.cyclotron.posts() == []


@then("the story's enrichment is waiting for a retry")
def step_waiting(context):
    row = context.table_.items[ROW]
    assert row["final"] is False and row["nextAttemptAt"] > 2000


@then("every decision request carries the whole body and the matching text")
def step_whole_body(context):
    assert values(context) and all(v["body"] == context.article and v["text"].endswith(context.article) and v["summary"] == te.SUMMARY
                                   for v in values(context))


@then("the story's discovery records no cut")
def step_no_cut(context):
    assert "bodyTruncatedForLabLimit" not in context.table_.items[("MONITOR#hn", "DISC#101#000001")]


@then("the captured text kept for the editors is whole")
def step_whole(context):
    assert context.enricher.texts.objects[context.table_.items[ROW]["textKey"]] == context.article
