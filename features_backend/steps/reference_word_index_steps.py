"""Steps for the persistent word index (``papyrus_knowledge_query.reference_words``). Synthetic data; a DynamoDB stand-in that counts requests."""
from behave import given, when, then

from papyrus_content.reference_word_backfill import backfill_words
from procedures.newsroom.tests.test_reference_search import FakeDynamo, FakeSite, row
from procedures.newsroom.tests.test_reference_words import FakeClient
from papyrus_knowledge_query import reference_search as rs


def _titles(site, query):
    return [item["reference"]["title"] for item in rs.search_references({"query": query, "show": "all"}, words=site.source, vectors=None)["items"]]


@when('a Reference titled "{title}" arrives')
def arrives(context, title):
    context.site.change(None, row("sound", title, state="unrated"))


@then('searching for "sound" finds it, and so does searching for "leak" as the start of a word')
def finds(context):
    title = "I discovered a sound that leaks your exact location"
    assert _titles(context.site, "sound") == [title] and _titles(context.site, "leak") == [title]


@when("an editor accepts a Reference and gives it four stars")
def vote(context):
    old = context.site.rows["a"]
    context.site.dynamo.requests.clear()
    context.site.change(old, {**old, "feedStateKey": "c#rated", "curationStatus": "accepted", "starRating": 4})


@then("no word row was written or deleted")
def nothing_written(context):
    assert [operation for operation, _table in context.site.dynamo.requests if operation in ("put_item", "delete_item")] == []


@when("a Reference gets a second version with a new title and the first version's change to superseded arrives after it")
def second_version(context):
    first = context.site.rows["a"]
    context.site.change(None, row("a", "Fresh title", version=2, updated="2026-11-01T10:30:05.000Z"))
    context.site.change(first, {**first, "versionState": "superseded"})


@then("searching finds it under the new title and not the old one")
def new_title_only(context):
    assert _titles(context.site, "fresh") == ["Fresh title"] and _titles(context.site, "old") == []


@given("a site with a pending, an accepted, a rejected and an archived Reference and no word rows")
def backfill_site(context):
    context.site = FakeSite([])
    context.client = FakeClient([row("p", "Pending sound", state="unrated"), row("a", "Accepted sound", state="rated", curationStatus="accepted"),
                                 row("r", "Rejected sound", state="rated", curationStatus="rejected"), row("x", "Archived sound", state=None)])
    for existing in context.client.rows:   # the Reference table already holds them; only the word table is empty
        context.site.dynamo.tables[FakeDynamo.REFERENCES][existing["id"]] = existing


@when("the operator runs the backfill without writing")
def preview(context):
    context.preview = backfill_words(context.client, context.site.writer, corpus_id="c")


@then("it reports three References to index and writes no rows")
def reports(context):
    assert context.preview["toIndex"] == 3 and context.preview["written"] == 0 and context.site.dynamo.tables[FakeDynamo.WORDS] == {}


@then("when the operator runs it with writing every state is searchable and a second run writes nothing")
def writes(context):
    first = backfill_words(context.client, context.site.writer, corpus_id="c", dry_run=False)
    assert first["written"] == 3 and sorted(_titles(context.site, "sound")) == ["Accepted sound", "Pending sound", "Rejected sound"]
    assert backfill_words(context.client, context.site.writer, corpus_id="c", dry_run=False)["written"] == 0
