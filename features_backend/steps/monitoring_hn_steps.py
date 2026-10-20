from pathlib import Path
import tempfile

from behave import given, when, then

from papyrus_content.monitoring import Monitor, collect

FEED = b'''<rss><channel>
<item><title>AI source</title><link>https://example.org/ai</link><comments>https://news.ycombinator.com/item?id=123</comments></item>
<item><title>Security source</title><link>https://example.org/security</link><comments>https://news.ycombinator.com/item?id=124</comments></item>
</channel></rss>'''


@given("a configured Hacker News Monitor and a two-item feed")
def monitoring_setup(context):
    directory = tempfile.mkdtemp(prefix="papyrus-hn-bdd-")
    context.tmp_dirs.append(directory)
    context.hn_monitor = Monitor("hn", "example", "knowledge-corpus-example", "https://example.org/graphql",
                                 Path(directory) / "checkpoint.sqlite3")
    context.hn_calls, context.hn_results = [], []
    context.hn_fail = None

    def intake(item, provenance):
        context.hn_calls.append((item, provenance))
        if context.hn_fail == item.source_id:
            context.hn_fail = None
            raise ValueError("temporary intake error")
        return {"referenceId": "reference-" + item.source_id, "referenceLineageId": "lineage-" + item.source_id}
    context.hn_intake = intake


@given("the second item fails intake once")
def monitoring_failure(context):
    context.hn_fail = "124"


@when("the Monitor collects the feed twice")
def monitoring_repeat(context):
    context.hn_results = [collect(context.hn_monitor, context.hn_intake, fetch=lambda: FEED, now=1000 + i,
                                  force=True) for i in range(2)]


@then("two persisted Reference receipts have source and publication provenance")
def monitoring_receipts(context):
    assert len(context.hn_results[0]["discoveries"]) == 2
    assert all(r["publication"] == "example" and r["sourceItemUrl"] and r["referenceId"]
               for r in context.hn_results[0]["discoveries"])


@then("the second collection does not register the unchanged items again")
def monitoring_dedup(context):
    assert context.hn_results[1]["unchanged"] == 2 and len(context.hn_calls) == 2


@then("the first item is not registered again")
def monitoring_first_success(context):
    assert [r[0].source_id for r in context.hn_calls].count("123") == 1


@then("the second item has a successful persisted receipt after retry")
def monitoring_retry(context):
    assert context.hn_results[0]["status"] == "partial"
    assert context.hn_results[1]["status"] == "complete"
    assert context.hn_results[1]["discoveries"][0]["sourceId"] == "124"


@when("a previously collected source title changes")
def monitoring_update(context):
    context.hn_results = [collect(context.hn_monitor, context.hn_intake, fetch=lambda: FEED, now=1000)]
    context.hn_results.append(collect(context.hn_monitor, context.hn_intake,
                                      fetch=lambda: FEED.replace(b"AI source", b"AI revision"), now=2000))


@then("a new discovery revision is recorded for the same canonical Reference")
def monitoring_revision(context):
    first, second = context.hn_results
    assert second["discoveries"][0]["revision"] == 2
    assert second["discoveries"][0]["referenceId"] == first["discoveries"][0]["referenceId"]


@then("collection does not create a curation or training label")
def monitoring_no_label(context):
    assert all("label" not in p and "curationStatus" not in p for _, p in context.hn_calls)


@when("a scheduled collection is requested before its next due time")
def monitoring_early(context):
    context.hn_results = [collect(context.hn_monitor, context.hn_intake, fetch=lambda: FEED, now=1000)]
    def forbidden_fetch():
        raise AssertionError("Source fetched before due")
    context.hn_results.append(collect(context.hn_monitor, context.hn_intake, fetch=forbidden_fetch, now=1100))


@then("no source fetch or registration is performed until due")
def monitoring_due(context):
    assert context.hn_results[1]["status"] == "not_due" and len(context.hn_calls) == 2
