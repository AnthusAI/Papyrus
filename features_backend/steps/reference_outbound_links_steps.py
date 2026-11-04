"""Steps for features_backend/reference-outbound-links.feature. In memory: no network, no AWS, no model."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from curation_support import MemoryClient, article_html, page, reference, services  # noqa: E402
from papyrus_content import reference_capture, reference_curation as curation  # noqa: E402
from papyrus_content.reference_curation_store import LINKS_SORT_KEY, read_card  # noqa: E402

HUB_URL = "https://blog.kjamistan.com/a-deep-dive-into-memorization-in-deep-learning.html"
HUB = (REPO_ROOT / "procedures" / "newsroom" / "tests" / "fixtures" / "kjam-memorization-hub.html").read_text(encoding="utf-8")
CATEGORY = "https://blog.kjamistan.com/category/ml-memorization.html"
THANKS = {"https://vickiboykis.com/", "https://desfontain.es/serious.html", "https://www.linkedin.com/in/yanndupis/"}
CHROME = {"http://getpelican.com", "http://bit.ly/flex-pelican", "https://probablyprivate.com/", "https://twitter.com/kjam", "https://blog.kjamistan.com/feeds/rss.xml"}
PLAYLIST_PREFIX = "https://www.youtube.com/watch?v=JDAPDpbXRXw&list=PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom"


def explorer_for(address: str, body: str):
    return services(MemoryClient([]), pages={address: page(body)}).explorer


def content_urls(links) -> list[str]:
    return [link["url"] for link in links if link["kind"] == "content"]


@given("the saved series hub page")
def hub(context) -> None:
    context.address, context.body = HUB_URL, HUB


@given("an article page with no links")
def linkless(context) -> None:
    context.address, context.body = "https://news.example.org/r1", article_html()


@given("a page whose only content is a linked image")
def image_only(context) -> None:
    context.address = "https://site.example/p"
    context.body = '<html><body><nav><a href="https://e.org/n">N</a></nav><div><a href="https://e.org/x"><img src="a.png"></a></div></body></html>'


@when("the page is captured")
def capture(context) -> None:
    context.capture_result = reference_capture.capture_source(context.address, explorer=explorer_for(context.address, context.body))


@then("its content links are the {count:d} series articles and the YouTube playlist")
def content_links_are(context, count: int) -> None:
    found = content_urls(context.capture_result.links)
    series = [url for url in found if url.startswith("https://blog.kjamistan.com/") and url.endswith(".html")]
    assert len(series) == count and len(found) == count + 1 and any(url.startswith(PLAYLIST_PREFIX) for url in found), found


@then("the category page is not a content link")
def category_not_content(context) -> None:
    assert CATEGORY not in content_urls(context.capture_result.links)
    assert CATEGORY in [link["url"] for link in context.capture_result.links], "it is still recorded, as navigation"


@then("the three thanks links are not content links")
def thanks_not_content(context) -> None:
    assert not THANKS & set(content_urls(context.capture_result.links))
    assert THANKS <= {link["url"] for link in context.capture_result.links}


@then("the sidebar and footer links are not content links")
def chrome_not_content(context) -> None:
    assert not CHROME & set(content_urls(context.capture_result.links))


@then("every series article is marked as part of a list")
def series_listed(context) -> None:
    series = [link for link in context.capture_result.links if link["kind"] == "content" and link["url"].endswith(".html")]
    assert len(series) == 18 and all(link["listed"] for link in series)


@then("the links are in the order the page has them, each address once")
def ordered_once(context) -> None:
    links = context.capture_result.links
    assert [link["position"] for link in links] == list(range(1, len(links) + 1))
    assert len({link["url"] for link in links}) == len(links)


@when("the curation procedure runs for a Reference at that page")
def curate(context) -> None:
    context.ref = reference(sourceUri=context.address)
    context.client = MemoryClient([context.ref])
    context.services = services(context.client, pages={context.address: page(context.body)})
    curation.curate_reference(context.client, context.ref, services=context.services)
    context.card = read_card(context.client, context.ref)


@then("the links are stored in an attachment")
def stored(context) -> None:
    stored_links = json.loads(context.services.store.text(context.ref, LINKS_SORT_KEY))
    assert len(stored_links["links"]) == 34 and context.card["current"]["linksSortKey"] == LINKS_SORT_KEY


@then("the curation card counts {total:d} links, {content:d} of them content links")
def card_counts(context, total: int, content: int) -> None:
    assert context.card["links"] == {"total": total, "content": content}, context.card.get("links")


@then("the curation card is small")
def card_small(context) -> None:
    assert len(json.dumps(context.card)) < 6000


@then("no links attachment is stored")
def none_stored(context) -> None:
    assert LINKS_SORT_KEY not in context.services.store.writes and "links" not in context.card


@then('the capture failed with "{reason}"')
def failed_with(context, reason: str) -> None:
    assert not context.capture_result.ok and context.capture_result.failure == reason


@then("its links are recorded")
def links_recorded(context) -> None:
    assert [link["url"] for link in context.capture_result.links] == ["https://e.org/n", "https://e.org/x"]


# --- the monitor path ---------------------------------------------------------------------------------------------------------------------

@given("a monitored item whose page had a content link and a navigation link")
def monitored(context) -> None:
    context.links = [{"url": "https://example.org/series/1", "label": "Part one", "kind": "content", "listed": True, "position": 1},
                     {"url": "https://example.org/about", "label": "About", "kind": "navigation", "listed": False, "position": 2}]


@when("the item is enriched and delivered")
def enrich_and_deliver(context) -> None:
    from papyrus_content import monitoring_enrichment as me
    from papyrus_content.reference_capture import Capture
    from curation_support import MemoryStore

    text = "# Plan\n\n" + "The board voted on Tuesday to adopt the plan. " * 20
    captured = Capture(True, text=text, source_kind="html", content_type="text/html", via="direct", destination_url="https://example.org/alpha",
                       signals={"wordCount": len(text.split())}, paper={"isPaper": False}, page={"title": "T"}, links=context.links)
    enricher = me.Enricher(texts=me.MemoryTexts(), summarizer=None, capture=lambda url, **kwargs: captured)
    disc = {"sourceId": "s1", "revision": 1, "canonicalUrl": "https://example.org/alpha", "title": "T"}
    row = me.new_row("hn", disc)
    me.enrich_item(row, disc, "hn", enricher, me.utc_now())
    context.row, context.enricher = row, enricher
    context.ref = {"id": "reference-1", "lineageId": "reference-1", "versionNumber": 1}
    context.client = MemoryClient([context.ref])
    store = MemoryStore(context.client)
    original = me.AttachmentStore
    me.AttachmentStore = lambda client: store
    try:
        me.copy_curation(context.client, context.ref, row, enricher.texts, me.utc_now())
    finally:
        me.AttachmentStore = original
    context.store = store


@then("the delivered Reference's links attachment holds both links")
def delivered_links(context) -> None:
    assert json.loads(context.store.text(context.ref, LINKS_SORT_KEY))["links"] == context.links


@then("the delivered Reference's curation card counts {total:d} links, {content:d} of them a content link")
def delivered_counts(context, total: int, content: int) -> None:
    assert context.client.card(context.ref["id"])["links"] == {"total": total, "content": content}
