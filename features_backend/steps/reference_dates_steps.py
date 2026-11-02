"""Steps for features_backend/reference-dates.feature. Everything is in memory: no network, no AWS, no model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from curation_support import NOW, MemoryClient, Summarizer, article_html, page, reference, services as build_services  # noqa: E402
from papyrus_content import reference_curation as curation  # noqa: E402
from papyrus_content.reference_curation_store import new_card, read_card, write_card  # noqa: E402

DATED_ARTICLE_URL = "https://news.example.org/dated"
ADDED_AT = "2026-11-01T08:00:00Z"


def declare_in_head(context, markup):
    context.head_markup += markup


def dated_reference(context):
    return context.client.get_record("Reference", context.ref["id"])


def stored_resolution(context):
    """The provenance lives on the curation card (the curation attachment's metadata): the Reference model has no metadata field."""
    card = curation.read_card(context.client, dated_reference(context)) or {}
    return card.get("publicationDate")


@given("a site with a pending Reference whose source page declares its date in no way yet")
def _(context):
    context.head_markup = ""
    context.footer_markup = ""
    context.ref = reference("dated", createdAt=ADDED_AT)


@given('the page declares the Open Graph article published time "{value}"')
def _(context, value):
    declare_in_head(context, f"<meta property='article:published_time' content='{value}'>")


@given('the page declares the JSON-LD date published "{value}"')
def _(context, value):
    declare_in_head(context, f'<script type="application/ld+json">{{"@type": "NewsArticle", "datePublished": "{value}"}}</script>')


@given('the page declares the date published "{value}" inside a JSON-LD graph')
def _(context, value):
    graph = {"@context": "https://schema.org", "@graph": [{"@type": "WebSite", "name": "Example"}, {"@type": "NewsArticle", "datePublished": value}]}
    declare_in_head(context, f'<script type="application/ld+json">{json.dumps(graph)}</script>')


@given('the page shows a time element with the datetime "{value}"')
def _(context, value):
    context.footer_markup += f'<p>Posted <time datetime="{value}">some day</time> by the desk.</p>'


@given('the Reference already has the publication date "{value}" from a monitor')
def _(context, value):
    context.ref["sourcePublishedAt"] = value


@when("curation reads the page")
def _(context):
    context.client = MemoryClient([context.ref])
    html = article_html(extra_head=context.head_markup, footer=context.footer_markup)
    pages = {DATED_ARTICLE_URL: page(html)}
    context.ref["sourceUri"] = DATED_ARTICLE_URL
    context.client.tables["Reference"][context.ref["id"]]["sourceUri"] = DATED_ARTICLE_URL
    services = build_services(context.client, pages=pages, summarizer=Summarizer(), grobid_url=None, grobid=None)
    curation.curate_reference(context.client, context.ref, services=services)


@then('the Reference\'s publication date is "{value}"')
def _(context, value):
    assert dated_reference(context).get("sourcePublishedAt") == value, dated_reference(context).get("sourcePublishedAt")


@then('the publication date was resolved from "{source}" with "{precision}" precision')
def _(context, source, precision):
    resolution = stored_resolution(context)
    assert resolution and (resolution["source"], resolution["precision"]) == (source, precision), resolution
    assert resolution["resolvedAt"]


@then("the Reference has no publication date")
def _(context):
    assert not dated_reference(context).get("sourcePublishedAt")


@then("the Reference records no publication date resolution")
def _(context):
    assert stored_resolution(context) is None


@then("the Reference's added date is unchanged")
def _(context):
    assert dated_reference(context)["createdAt"] == ADDED_AT



import test_idea_context_packs as pack_support  # noqa: E402
from papyrus_content.ideas.context_packs import build_packs  # noqa: E402
from papyrus_content.knowledge_snapshot.builder import INDEX_FILE, build_files, entity_file  # noqa: E402
from papyrus_content.knowledge_snapshot.builder_test import AI, OPTIONS, item as snapshot_item, link as snapshot_link, node as snapshot_node  # noqa: E402
from papyrus_content.knowledge_snapshot.model import KnowledgeData  # noqa: E402


def pack_of(context, signal):
    return next((pack for pack in context.packs if pack.signal_type == signal), None)


@given("References accepted in a burst, one with no publication date")
def _(context):
    context.votes = [*pack_pack_votes(), pack_support.dated_vote("no-date", 1.2, 0.7, None)]


@given("References accepted in a burst, with publication dates far apart")
def _(context):
    context.votes = [*pack_pack_votes(), pack_support.dated_vote("published-early", 1.0, 0.9, 400), pack_support.dated_vote("published-late", 1.1, 0.8, 5)]


def pack_pack_votes():
    return pack_support.acceptance_votes()


@given("a site where sources usually reach it days after publication")
def _(context):
    context.votes = pack_support.ordinary_votes()
    context.messages = []


@given("a source published long before it reached the site that people accepted and discussed today")
def _(context):
    context.votes.append(pack_support.dated_vote("old-source", 0.4, 200, 600))
    context.messages = [pack_support.message(1, 0.2, thread="thread-old", anchor="reference#old-source")]


@given("a source published long before it reached the site that nobody has attended to for months")
def _(context):
    context.votes.append(pack_support.dated_vote("old-source", 150, 200, 600))


@when("the context packs are built from them")
def _(context):
    context.packs = build_packs(pack_support.inputs(votes=context.votes, messages=getattr(context, "messages", [])), pack_support.LOOKUPS, now=pack_support.NOW)


@then("the acceptance pack states that its dates are ingestion dates")
def _(context):
    assert pack_of(context, "acceptance").signal["dateBasis"] == "ingestion"


@then("the Reference with no publication date shows no publication date and is ordered by its added date")
def _(context):
    row = next(row for row in pack_of(context, "acceptance").as_json()["references"] if row["title"] == "Title no-date")
    assert row["published"] is None and row["orderedBy"] == "added" and row["added"]


@then("the Reference published most recently comes first in the acceptance pack")
def _(context):
    titles = [row["title"] for row in pack_of(context, "acceptance").as_json()["references"]]
    assert titles.index("Title published-late") < titles.index("Title published-early")


@given("a concept linked to items published in three different weeks")
def _(context):
    context.voice = snapshot_node("task", "Voice cloning", accepted_by=AI)
    context.snapshot_items = [snapshot_item("early", offset=6), snapshot_item("middle", offset=3), snapshot_item("latest", offset=0)]


@when("the concept snapshot files are built")
def _(context):
    links = tuple(snapshot_link(each.key.removeprefix("lineage-"), context.voice) for each in context.snapshot_items)
    context.snapshot = build_files(KnowledgeData(items=tuple(context.snapshot_items), nodes=(context.voice,), links=links), OPTIONS)


@then("each item is counted in the week it was published")
def _(context):
    assert context.snapshot[entity_file("task--voice-cloning")]["series8"] == [0, 1, 0, 0, 1, 0, 0, 1]


@then("the concept series states that its dates are publication dates")
def _(context):
    assert context.snapshot[entity_file("task--voice-cloning")]["dateBasis"] == "publication"
    assert all(row["dateBasis"] == "publication" for row in context.snapshot[INDEX_FILE]["entities"])


@then("a resurfaced pack exists for that source")
def _(context):
    assert pack_of(context, "resurfaced").anchor == "reference#old-source"


@then("the pack states that its dates are publication dates")
def _(context):
    assert pack_of(context, "resurfaced").signal["dateBasis"] == "publication"


@then("the pack says the accept and the Message that pointed attention at it")
def _(context):
    assert [row["kind"] for row in pack_of(context, "resurfaced").signal["pointedAttentionAt"]] == ["human accept", "message"]


@then("no resurfaced pack exists")
def _(context):
    assert pack_of(context, "resurfaced") is None


# --- the publication-date backfill ----------------------------------------------------------------------------------------


def backfill_url(name):
    return f"https://news.example.org/{name}"


def backfill_state(context):
    if not hasattr(context, "backfill_refs"):
        context.backfill_refs, context.backfill_pages = [], {}
    return context.backfill_refs, context.backfill_pages


@given('Reference "{name}" has a page that declares the Open Graph article published time "{value}"')
def _(context, name, value):
    refs, pages = backfill_state(context)
    refs.append(reference(name, sourceUri=backfill_url(name)))
    pages[backfill_url(name)] = page(article_html(extra_head=f"<meta property='article:published_time' content='{value}'>"))


@given('Reference "{name}" already has the publication date "{value}" from a monitor')
def _(context, name, value):
    backfill_state(context)[0].append(reference(name, sourceUri=backfill_url(name), sourcePublishedAt=value))


@given('Reference "{name}" has a page that cannot be fetched')
def _(context, name):
    backfill_state(context)[0].append(reference(name, sourceUri=backfill_url(name)))


@given('Reference "{name}" already has a publication date recorded on its curation card')
def _(context, name):
    backfill_state(context)[0].append(reference(name, sourceUri=backfill_url(name)))
    context.backfill_resolved = [*getattr(context, "backfill_resolved", []), name]


def run_backfill(context, dry_run):
    from papyrus_content.link_exploration import Exploration

    refs, pages = backfill_state(context)
    context.client = MemoryClient(refs)
    for name in getattr(context, "backfill_resolved", []):
        done = next(ref for ref in refs if ref["id"] == f"{name}-v1")
        card = new_card(done)
        card["publicationDate"] = {"source": "pdf", "precision": "day", "resolvedAt": "2026-10-01T00:00:00Z"}
        write_card(context.client, done, card, NOW)
    context.writes_before = context.client.writes

    def explorer(url, context=None, **kwargs):
        found = pages.get(url)
        if found is None:
            return Exploration(False, None, failure="timeout", direct_failure="timeout")
        return Exploration(True, url, None, "direct", readable=False, response=found if kwargs.get("keep_response") else None)

    context.backfill = curation.backfill_publication_dates(context.client, corpus_id="knowledge-corpus-site", dry_run=dry_run, explorer=explorer,
                                                           now=lambda: NOW)


@when("the publication date backfill runs")
def _(context):
    run_backfill(context, False)


@when("the publication date backfill runs as a dry run")
def _(context):
    run_backfill(context, True)


def backfilled(context, name):
    return context.client.get_record("Reference", f"{name}-v1")


@then('Reference "{name}" has the publication date "{value}" resolved from "{source}"')
def _(context, name, value, source):
    row = backfilled(context, name)
    assert row["sourcePublishedAt"] == value
    assert read_card(context.client, row)["publicationDate"]["source"] == source


@then('Reference "{name}" records its publication date as resolved from "{source}"')
def _(context, name, source):
    assert (read_card(context.client, backfilled(context, name)) or {}).get("publicationDate", {}).get("source") == source


@then('Reference "{name}" is unchanged and counted as a fetch failure')
def _(context, name):
    assert backfilled(context, name) == reference(name, sourceUri=backfill_url(name))
    assert context.backfill["counts"]["fetchFailures"] == 1


@then('Reference "{name}" is skipped')
def _(context, name):
    assert next(item for item in context.backfill["items"] if item["referenceId"] == f"{name}-v1")["outcome"] == "already_resolved"


@then("no summary was written and no curation card exists for any of them")
def _(context):
    assert not context.client.tables["ModelAttachment"]
    for row in context.client.tables["ReferenceAttachment"].values():
        card = json.loads(row["metadata"])
        assert card["summary"] == {"status": "not_run"} and card["capture"] == {"status": "not_run"}


@then('the dry run lists Reference "{name}" with the date "{value}" from "{source}"')
def _(context, name, value, source):
    item = next(item for item in context.backfill["items"] if item["referenceId"] == f"{name}-v1")
    assert (item["date"], item["source"]) == (value, source)


@then("the dry run wrote nothing")
def _(context):
    assert context.client.writes == context.writes_before
