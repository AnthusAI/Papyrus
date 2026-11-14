"""Link exploration (features_backend/link-exploration.feature). The HTTP layer, the search provider and the store are fakes: no network."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import monitoring_view_fixture as fx  # noqa: E402
from papyrus_content import link_exploration, monitoring_view  # noqa: E402
from papyrus_content.link_exploration import Context, Response, TransportError, explore  # noqa: E402
from papyrus_content.link_search import SearchHit, TavilySearch  # noqa: E402
from test_link_exploration import ARTICLE, FakeHttp, FakeSearch, html, redirect  # noqa: E402
from test_monitoring_view import email_rows  # noqa: E402

START = "https://u123.ct.sendgrid.net/ls/click?upn=u001.opaque-subscriber-token"
FAILURES = {
    "a missing host name": TransportError("dns"), "a timeout": TransportError("timeout"), "a refused connection": TransportError("connection"),
    "a certificate error": TransportError("tls"), "status 404": html("gone", 404), "status 503": html("down", 503),
    "status 403": html("no", 403), "status 429": html("slow", 429),
    "an image instead of a page": Response(200, {"content-type": "image/png"}, b"\x89PNG"), "a redirect with no target": Response(302, {}),
}


def start(context, pages, address=START):
    context.http = FakeHttp(pages)
    context.start = address
    context.search = None
    context.result = None


def hit_for(url, title="Regulators approve cross-border licensing scheme for open models"):
    return SearchHit(url, title, "", 0.9)


@given('a newsletter link that redirects through "{host}" to the article "{article}"')
def step_chain(context, host, article):
    middle = f"https://{host}/r/abc?id=subscriber-9"
    start(context, {START: redirect(middle), middle: redirect(article, 301), article: html(ARTICLE)})


@given('a newsletter link that redirects to the article "{article}"')
def step_to_article(context, article):
    start(context, {START: redirect(article), article: html(ARTICLE)})


@given('a newsletter link that redirects to "{target}"')
def step_to_private(context, target):
    start(context, {START: redirect(target)})


@given("a newsletter link that redirects in a loop")
def step_loop(context):
    start(context, {START: redirect("https://b.example/y"), "https://b.example/y": redirect(START + "#again")})


@given("a newsletter link that answers 404")
def step_404(context):
    start(context, {START: html("gone", 404)})


@given("a newsletter link that fails with {failure}")
def step_fails(context, failure):
    start(context, {START: FAILURES[failure]})


@given('the address "{address}"')
def step_address(context, address):
    start(context, {}, address)


@given('a search for the headline finds the article "{article}"')
def step_search_finds(context, article):
    (context.http.pages if hasattr(context, "http") and not hasattr(context, "store") else context.pages)[article] = html(ARTICLE)
    context.search = FakeSearch([hit_for(article)])


@given('a search for the headline finds only the unrelated article "{article}" titled "{title}"')
def step_search_unrelated(context, article, title):
    context.search = FakeSearch([hit_for(article, title)])


@given("no search key is configured")
def step_no_key(context):
    context.search = TavilySearch(environ={})


@when('the link is explored with the headline "{headline}"')
def step_explore_headline(context, headline):
    context.result = explore(context.start, Context(title=headline), transport=context.http, search=context.search or FakeSearch())


@when("the link is explored without search")
def step_explore_plain(context):
    context.result = explore(context.start, transport=context.http, use_search=False)


@when("the address is explored without search")
def step_explore_address(context):
    context.result = explore(context.start, transport=context.http, use_search=False)


@then('the exploration found the destination "{url}" directly')
def step_found_direct(context, url):
    assert context.result.ok and context.result.via == "direct" and context.result.url == url, context.result.as_record()


@then('the exploration found the destination "{url}" via search')
def step_found_search(context, url):
    assert context.result.ok and context.result.via == "search" and context.result.url == url, context.result.as_record()


@then("the exploration read the article text")
def step_read(context):
    assert context.result.readable and "cross-border licensing scheme" in context.result.text


@then("the exploration result does not contain the newsletter link")
def step_private(context):
    text = json.dumps(context.result.as_record()) + repr(context.result)
    assert "sendgrid" not in text and "subscriber" not in text and "links.publisher" not in text, text


@then('the exploration recorded the search query "{query}" and a match score of at least {score:f}')
def step_query(context, query, score):
    assert context.result.search.query == query and context.result.search.score >= score, context.result.as_record()


@then('the exploration recorded that the original link failed with "{reason}"')
def step_direct_failure(context, reason):
    assert context.result.direct_failure == reason, context.result.as_record()


@then('the exploration failed with "{reason}"')
def step_failed(context, reason):
    assert not context.result.ok and context.result.failure == reason, context.result.as_record()


@then("no page was requested")
def step_nothing_requested(context):
    assert context.http.asked == []


@then("the failure reason names no address")
def step_url_free(context):
    reason = context.result.failure
    assert reason in link_exploration.REASONS and "/" not in reason and "." not in reason
    assert "publisher.example" not in json.dumps({key: value for key, value in context.result.as_record().items() if key != "url"})


# --- the editor's resolve action -------------------------------------------------------------------------------------------------


@given('an email receipt with the newsletter link "{link}" titled "{title}"')
def step_receipt(context, link, title):
    context.store = fx.FakeViewStore(fx.rows() + email_rows())
    context.receipt_id = "EMAIL#" + "a" * 64
    context.wrapper = link
    context.store.table["EMAILDETAIL#" + "a" * 64 + "#LINKS#0000"]["json"] = json.dumps([{"url": link, "title": title, "resolutionStatus": "unresolved"}])
    context.pages = {}
    context.search = None


@given('the wrapper redirects to the article "{article}"')
def step_wrapper_redirects(context, article):
    context.pages[context.wrapper] = redirect(article)
    context.pages[article] = html(ARTICLE)


@given("the wrapper answers 404")
def step_wrapper_404(context):
    context.pages[context.wrapper] = html("gone", 404)


@when("an editor resolves the candidate")
def step_resolve(context):
    pages = context.pages
    if context.search is not None:
        for hit in context.search.hits:
            pages.setdefault(hit.url, html(ARTICLE))
    with mock.patch.object(link_exploration, "http_transport", FakeHttp(pages)), \
            mock.patch.object(link_exploration, "default_search_provider", lambda: context.search or FakeSearch()):
        context.resolution = monitoring_view.monitoring_email_resolve_article_link(
            context.store, groups=["editor"], site_endpoint=fx.APP_ANTH, receipt_id=context.receipt_id, candidate_index=0)


@then('the editor sees the destination "{url}" and no search mark')
def step_editor_direct(context, url):
    assert context.resolution["url"] == url and "foundVia" not in context.resolution, context.resolution


@then('the editor sees the destination "{url}" marked found via search with the query and match score')
def step_editor_search(context, url):
    resolution = context.resolution
    assert resolution["url"] == url and resolution["foundVia"] == "search", resolution
    assert resolution["search"]["query"] and resolution["search"]["matchScore"] >= 0.9, resolution


@then("the recorded resolution holds the destination and not the newsletter link")
def step_recorded(context):
    saved = context.store.get(f"EMAILRESOLVED#{'a' * 64}#000000")
    assert saved["sourceUri"] == context.resolution["url"] and context.wrapper not in json.dumps(saved, default=str), saved
