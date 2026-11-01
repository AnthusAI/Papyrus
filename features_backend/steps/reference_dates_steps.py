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

from curation_support import MemoryClient, Summarizer, article_html, page, reference, services as build_services  # noqa: E402
from papyrus_content import reference_curation as curation  # noqa: E402

DATED_ARTICLE_URL = "https://news.example.org/dated"
ADDED_AT = "2026-11-01T08:00:00Z"


def declare_in_head(context, markup):
    context.head_markup += markup


def dated_reference(context):
    return context.client.get_record("Reference", context.ref["id"])


def stored_resolution(context):
    raw = dated_reference(context).get("metadata")
    return (json.loads(raw) if raw else {}).get("publicationDateResolution")


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
