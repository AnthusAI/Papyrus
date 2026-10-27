"""Reference previews (features_backend/reference-previews.feature). The HTTP layer and the store are fakes: no network, no AWS."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.link_exploration import Exploration, PageMetadata, explore  # noqa: E402
from papyrus_content.reference_images import PREVIEW_ROLE, enrich_reference_previews  # noqa: E402
from test_link_exploration import ARTICLE_TEXT, FakeHttp, html  # noqa: E402
from test_reference_images import FakeClient, explorer, reference  # noqa: E402

ARTICLE = "https://www.publisher.example/news/licensing"
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


@given('a source page that declares the image "{image}", the description "{description}" and the site name "{site}"')
def step_page_full(context, image, description, site):
    head = f'<meta property="og:image" content="{image}"><meta property="og:description" content="{description}"><meta property="og:site_name" content="{site}">'
    context.http = FakeHttp({ARTICLE: html(f"<html><head>{head}</head><body><p>{ARTICLE_TEXT}</p></body></html>")})


@given('a source page that declares the image "{image}"')
def step_page_image(context, image):
    context.http = FakeHttp({ARTICLE: html(f'<html><head><meta property="og:image" content="{image}"></head><body><p>{ARTICLE_TEXT}</p></body></html>')})


@when("the source page is explored")
def step_explore(context):
    context.result = explore(ARTICLE, transport=context.http, use_search=False)


@then('the exploration returns the image "{image}", the description and the site name')
def step_returns(context, image):
    metadata = context.result.metadata
    assert metadata.image_url == image and metadata.description and metadata.site_name == "Publisher", metadata


@then("the exploration returns no image")
def step_no_image(context):
    assert context.result.metadata is None or context.result.metadata.image_url is None, context.result.metadata


@given("three References, one of which already has a preview attachment")
def step_three(context):
    context.client = FakeClient([reference("a"), reference("b"), reference("c")], [{"role": PREVIEW_ROLE, "referenceVersionKey": "reference#a-v1"}])
    context.explorer = explorer({f"https://{name}.example.org/a": Exploration(True, f"https://{name}.example.org/a", via="direct", metadata=PageMetadata(image_url=f"https://cdn.example.org/{name}.jpg")) for name in "abc"})


@when("the preview enrichment runs")
def step_run(context):
    context.counts = enrich_reference_previews(context.client, explorer=context.explorer, now=lambda: NOW)


@when("the preview enrichment runs as a dry run")
def step_dry(context):
    context.counts = enrich_reference_previews(context.client, dry_run=True, explorer=context.explorer, now=lambda: NOW)


@then("a preview attachment is written for each of the other two")
def step_written(context):
    assert sorted(row["referenceLineageId"] for _, row in context.client.written) == ["b", "c"], context.client.written


@then("the Reference that already had one is not read again")
def step_not_read(context):
    assert all("a.example.org" not in url for url, _ in context.explorer.asked), context.explorer.asked


@then("no preview is written")
def step_nothing(context):
    assert context.client.written == []


@then("the counts say how many would have been written")
def step_counts(context):
    assert context.counts["withImage"] == 2 and context.counts["written"] == 0 and context.counts["alreadyHave"] == 1, context.counts
