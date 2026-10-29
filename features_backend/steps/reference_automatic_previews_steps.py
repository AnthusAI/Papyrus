"""Steps for features_backend/reference-automatic-previews.feature. Router, store, Reference table and page fetch are all in memory."""

from __future__ import annotations

import functools
import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from curation_support import MemoryClient, MemoryStore  # noqa: E402
from papyrus_content import monitoring_enrichment as me  # noqa: E402
from papyrus_content.link_exploration import Exploration  # noqa: E402
from papyrus_content.reference_images import attach_preview  # noqa: E402
from test_monitoring_enrichment import ONE_FEED, Delivery, collected_table, enricher, go, good, setup_router  # noqa: E402



def _prepare(context, preview):
    capture = good()
    capture.preview = preview
    context.capture = capture
    context.feed = collected_table(ONE_FEED)


@given('a collected item whose page declares the picture "{image}" and the dek "{dek}"')
def _(context, image, dek):
    _prepare(context, {"imageUrl": image, "description": dek})


@given("a collected item whose page declares no picture and no dek")
def _(context):
    _prepare(context, {})


@given("a collected item whose curation did not keep the page's preview")
def _(context):
    _prepare(context, None)


@given("the page cannot be fetched when the preview is attempted")
def _(context):
    context.page_fetch_fails = True


def _deliver(context, reused):
    from test_monitoring_router import PUBS

    class Reusing(Delivery):
        def __call__(self, *args):
            return {**super().__call__(*args), "referenceReused": reused}

    context.fetches, context.logs, context.attempts = [], [], []

    def fetch(url, **kwargs):
        context.fetches.append(url)
        if getattr(context, "page_fetch_fails", False):
            raise TimeoutError("the page took too long")
        return Exploration(False, None, failure="offline")

    def previewer(client, reference, **kwargs):
        context.attempts.append(reference["id"])
        return attach_preview(client, reference, explorer=fetch, log=context.logs.append, **kwargs)

    references = [{"id": f"reference-{p}-101", "lineageId": f"reference-{p}-101", "versionNumber": 1,
                   "sourceUri": "https://example.org/alpha"} for p in PUBS]
    context.client = MemoryClient(references)
    original = me.AttachmentStore
    me.AttachmentStore = lambda c: MemoryStore(c)
    try:
        store, cyclotron = setup_router(context.feed)
        context.result = go(context.feed, store, cyclotron, enricher=enricher(context.capture), appsync=lambda endpoint: context.client,
                            deliver=Reusing(), previewer=previewer)
    finally:
        me.AttachmentStore = original
    context.reference_ids = [reference["id"] for reference in references]


@when("the router delivers the item as a new Reference")
def _(context):
    _deliver(context, reused=False)


@when("the router delivers the item and finds the Reference already existed")
def _(context):
    _deliver(context, reused=True)


def previews(context):
    return [row for row in context.client.tables["ReferenceAttachment"].values() if row["role"] == "preview"]


@then('the Reference has a preview attachment whose image is "{image}"')
def _(context, image):
    assert previews(context), "no preview attachment was written"
    assert all(row["sourceUri"] == image for row in previews(context)), previews(context)


@then('the preview holds the dek "{dek}"')
def _(context, dek):
    assert all(json.loads(row["metadata"])["description"] == dek for row in previews(context))


@then("the page was not fetched again for the preview")
def _(context):
    assert context.fetches == [], context.fetches


@then("the Reference has a preview attachment with no image that records when it was checked")
def _(context):
    assert previews(context), "no checked row was written"
    assert all(row["sourceUri"] is None and "checkedAt" in json.loads(row["metadata"]) for row in previews(context))


@then("the Reference is delivered")
def _(context):
    assert context.result["counts"]["delivered"] >= 1 and context.result["counts"]["deliveryFailed"] == 0, context.result["counts"]


@then("the Reference has no preview attachment")
def _(context):
    assert previews(context) == []


@then("the failure was logged as a preview failure")
def _(context):
    entries = [json.loads(line) for line in context.logs]
    assert entries and all(entry["referencePreview"] == "failed" and entry["reason"] for entry in entries), entries


@then("no preview was attempted")
def _(context):
    assert context.attempts == [] and context.fetches == [] and previews(context) == []
