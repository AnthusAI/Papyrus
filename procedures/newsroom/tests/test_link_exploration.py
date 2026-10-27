"""Link exploration: trackers, redirects, reading, the search fallback and typed failures. No network: a fake HTTP layer and a fake search provider."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[3]
for entry in (ROOT / "src", Path(__file__).parent):
    sys.path.insert(0, str(entry))

from pdf_fixtures import make_pdf  # noqa: E402
from papyrus_content import link_exploration as le  # noqa: E402
from papyrus_content.link_exploration import Context, Response, TransportError, explore  # noqa: E402
from papyrus_content.link_search import SearchError, SearchHit, SearchUnavailable, TavilySearch  # noqa: E402

ARTICLE_TEXT = ("Regulators approved the first cross-border licensing scheme for open models on Tuesday, ending two years of talks. "
                "The scheme lets a lab publish weights in any member state once and be covered everywhere. ") * 3
ARTICLE = f"<html><head><title>Licensing scheme approved</title></head><body><p>{ARTICLE_TEXT}</p></body></html>"
TRACKER = "https://u123.ct.sendgrid.net/ls/click?upn=u001.opaque-subscriber-token"
SUBSCRIBER_FRAGMENT = "opaque-subscriber-token"
HEADLINE = "Regulators approve cross-border licensing scheme for open models"


def html(body: str, status: int = 200) -> Response:
    return Response(status, {"content-type": "text/html; charset=utf-8"}, body.encode())


def redirect(location: str, status: int = 302) -> Response:
    return Response(status, {"location": location})


class FakeHttp:
    """Maps an address to a Response (or a TransportError to raise). Records the addresses it was asked for."""

    def __init__(self, pages: dict) -> None:
        self.pages, self.asked = pages, []

    def __call__(self, url: str) -> Response:
        self.asked.append(url)
        page = self.pages.get(url)
        if page is None:
            raise TransportError("dns")
        if isinstance(page, Exception):
            raise page
        return page


class FakeSearch:
    name = "fake"

    def __init__(self, hits=None, error: Exception | None = None) -> None:
        self.hits, self.error, self.queries = hits or [], error, []

    def search(self, query: str, *, limit: int = 8):
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.hits


def no_search_needed() -> FakeSearch:
    return FakeSearch(error=AssertionError("search must not be used"))


# --- resolving -------------------------------------------------------------------------------------------------------------------


def test_a_tracker_chain_resolves_to_the_canonical_article_and_its_text():
    http = FakeHttp({
        TRACKER: redirect("https://links.publisher.example/r/abc?id=subscriber-9"),
        "https://links.publisher.example/r/abc?id=subscriber-9": redirect("https://www.publisher.example/news/licensing?utm_source=newsletter&utm_medium=email&mc_cid=77&page=2#top", 301),
        "https://www.publisher.example/news/licensing?utm_source=newsletter&utm_medium=email&mc_cid=77&page=2#top": html(ARTICLE),
    })
    result = explore(TRACKER, Context(title=HEADLINE), transport=http, search=no_search_needed())
    assert result.ok and result.via == "direct" and result.failure is None
    assert result.url == "https://www.publisher.example/news/licensing?page=2"
    assert "cross-border licensing scheme" in result.text and result.readable and result.hops == 2


def test_the_result_never_contains_the_subscriber_specific_address_or_a_hop():
    http = FakeHttp({TRACKER: redirect("https://links.publisher.example/r/abc?id=subscriber-9"),
                     "https://links.publisher.example/r/abc?id=subscriber-9": redirect("https://publisher.example/a"),
                     "https://publisher.example/a": html(ARTICLE)})
    record = json.dumps(explore(TRACKER, Context(title=HEADLINE), transport=http).as_record())
    assert "sendgrid" not in record and SUBSCRIBER_FRAGMENT not in record and "subscriber-9" not in record and "links.publisher" not in record


def test_tracking_parameters_are_stripped_and_real_ones_kept():
    assert le.canonical_url("HTTPS://News.Example.org:443/a/b?utm_campaign=x&id=7&fbclid=z&mc_eid=1&gclid=2&sort=new#frag") == "https://news.example.org/a/b?id=7&sort=new"
    assert le.canonical_url("http://example.org") == "http://example.org/"


def test_a_wrapper_that_carries_its_destination_is_decoded_without_asking_the_wrapper():
    wrapped = "https://www.google.com/url?q=https%3A%2F%2Fpublisher.example%2Fa%3Futm_source%3Dx&sa=D"
    http = FakeHttp({"https://publisher.example/a?utm_source=x": html(ARTICLE)})
    result = explore(wrapped, transport=http)
    assert result.ok and result.url == "https://publisher.example/a"
    assert http.asked == ["https://publisher.example/a?utm_source=x"]


def test_a_substack_redirect_token_is_decoded():
    import base64
    payload = base64.urlsafe_b64encode(json.dumps({"e": "https://writer.example/p/post?utm_source=substack", "p": 1}).encode()).decode().rstrip("=")
    wrapped = f"https://substack.com/redirect/2/eyJhbGciOiJIUzI1NiJ9.{payload}.signature"
    http = FakeHttp({"https://writer.example/p/post?utm_source=substack": html(ARTICLE)})
    result = explore(wrapped, transport=http)
    assert result.url == "https://writer.example/p/post" and http.asked == ["https://writer.example/p/post?utm_source=substack"]


def test_an_ordinary_page_with_a_url_parameter_is_not_treated_as_a_wrapper():
    page = "https://publisher.example/share?url=https%3A%2F%2Fother.example%2Fx"
    http = FakeHttp({page: html(ARTICLE)})
    assert explore(page, transport=http).url == "https://publisher.example/share?url=https%3A%2F%2Fother.example%2Fx"
    assert http.asked == [page]


def test_meta_refresh_and_thin_javascript_redirects_are_followed():
    http = FakeHttp({
        "https://go.example/a": html('<html><head><meta http-equiv="refresh" content="0; url=/landing"></head></html>'),
        "https://go.example/landing": html("<html><script>window.location.href = 'https:\\/\\/publisher.example\\/story?a=1\\u0026b=2';</script></html>"),
        "https://publisher.example/story?a=1&b=2": html(ARTICLE),
    })
    result = explore("https://go.example/a", transport=http)
    assert result.ok and result.url == "https://publisher.example/story?a=1&b=2" and result.hops == 2


def test_a_script_on_a_real_article_is_not_followed():
    article = ARTICLE.replace("</body>", "<script>if (x) { location = 'https://elsewhere.example/ad'; }</script></body>")
    http = FakeHttp({"https://publisher.example/a": html(article)})
    result = explore("https://publisher.example/a", transport=http)
    assert result.url == "https://publisher.example/a" and http.asked == ["https://publisher.example/a"]


def test_a_redirect_loop_is_detected():
    http = FakeHttp({"https://a.example/x": redirect("https://b.example/y"), "https://b.example/y": redirect("https://a.example/x#again")})
    result = explore("https://a.example/x", transport=http, use_search=False)
    assert not result.ok and result.failure == "loop"


def test_a_long_chain_of_distinct_addresses_is_not_capped_by_hop_count():
    pages = {f"https://hop.example/{n}": redirect(f"https://hop.example/{n + 1}") for n in range(40)}
    pages["https://hop.example/40"] = html(ARTICLE)
    result = explore("https://hop.example/0", transport=FakeHttp(pages))
    assert result.ok and result.hops == 40


def test_the_overall_deadline_is_a_real_constraint():
    ticks = iter(range(0, 1000, 40))
    http = FakeHttp({f"https://slow.example/{n}": redirect(f"https://slow.example/{n + 1}") for n in range(10)})
    result = explore("https://slow.example/0", transport=http, use_search=False, deadline_seconds=90, clock=lambda: next(ticks))
    assert not result.ok and result.failure == "timeout"


# --- refusing non-public addresses -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("address", ["http://10.0.0.5/admin", "https://127.0.0.1/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/",
                                     "http://localhost:8080/", "https://user:secret@publisher.example/a", "http://[::1]/", "http://intranet/"])
def test_a_private_address_is_refused_before_any_request(address):
    http = FakeHttp({})
    result = explore(address, transport=http, use_search=False)
    assert not result.ok and result.failure == "not_public" and http.asked == []


def test_a_redirect_to_a_private_address_is_refused_at_that_hop():
    http = FakeHttp({"https://publisher.example/a": redirect("http://169.254.169.254/latest/meta-data/")})
    result = explore("https://publisher.example/a", transport=http, use_search=False)
    assert result.failure == "not_public" and http.asked == ["https://publisher.example/a"]


def test_a_host_that_resolves_to_a_private_address_is_refused_by_the_transport():
    result = explore("https://rebind.example/a", transport=FakeHttp({"https://rebind.example/a": TransportError("not_public")}), use_search=False)
    assert result.failure == "not_public"


def test_the_real_transport_verifies_every_resolved_address():
    with mock.patch.object(le.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("10.1.2.3", 443))]):
        with pytest.raises(TransportError) as error:
            le.public_addresses("mixed.example", 443)
    assert error.value.category == "not_public"
    with mock.patch.object(le.socket, "getaddrinfo", side_effect=le.socket.gaierror):
        with pytest.raises(TransportError) as error:
            le.public_addresses("nowhere.example", 443)
    assert error.value.category == "dns"
    with mock.patch.object(le.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
        assert le.public_addresses("ok.example", 443) == ["93.184.216.34"]


# --- typed failures ----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("response, reason", [
    (html("gone", 404), "http_4xx"), (html("gone", 410), "http_4xx"), (html("down", 503), "http_5xx"),
    (html("no", 403), "blocked"), (html("slow down", 429), "blocked"), (html("linkedin", 999), "blocked"),
    (Response(200, {"content-type": "image/png"}, b"\x89PNG"), "unreadable"), (html("<html><body></body></html>"), "unreadable"),
    (Response(302, {}), "unreadable"),
    (TransportError("dns"), "dns"), (TransportError("timeout"), "timeout"), (TransportError("connection"), "connection"), (TransportError("tls"), "tls"),
])
def test_every_failure_carries_a_typed_url_free_reason(response, reason):
    http = FakeHttp({"https://publisher.example/a": response})
    result = explore("https://publisher.example/a", transport=http, use_search=False)
    assert not result.ok and result.failure == reason and reason in le.REASONS
    assert "publisher.example" not in json.dumps({k: v for k, v in result.as_record().items() if k != "url"})


def test_an_invalid_address_has_a_reason():
    for bad in ("", "not a url", "ftp://example.org/x", "https://", None):
        assert explore(bad, use_search=False).failure == "invalid_url"


def test_a_blocked_publisher_is_still_a_destination_when_only_the_address_is_wanted():
    http = FakeHttp({"https://publisher.example/a?utm_source=x": html("no", 403)})
    result = explore("https://publisher.example/a?utm_source=x", want_text=False, transport=http, use_search=False)
    assert result.ok and result.url == "https://publisher.example/a" and not result.readable and result.direct_failure == "blocked"


def test_a_destination_the_caller_refuses_is_unsafe_and_never_returned():
    http = FakeHttp({"https://publisher.example/unsubscribe?u=1": html(ARTICLE)})
    result = explore("https://publisher.example/unsubscribe?u=1", transport=http, accept=lambda url: None, use_search=False)
    assert not result.ok and result.url is None and result.failure == "unsafe_destination"


def test_a_pdf_is_read_and_one_over_the_size_guard_is_too_large():
    pdf = make_pdf([["Decision of the Board.", "The refusal is affirmed on all grounds as set out below."]])
    http = FakeHttp({"https://court.example/d.pdf": Response(200, {"content-type": "application/pdf"}, pdf)})
    assert "refusal is affirmed" in explore("https://court.example/d.pdf", transport=http).text
    big = FakeHttp({"https://court.example/d.pdf": Response(200, {"content-type": "application/pdf"}, pdf, truncated=True)})
    assert explore("https://court.example/d.pdf", transport=big, use_search=False).failure == "too_large"


def test_a_thin_page_wrapping_a_pdf_reads_the_pdf():
    pdf = make_pdf([["In re Example Co.", "The refusal is affirmed."]])
    http = FakeHttp({"https://court.example/case": html("<html><a href='/files/d.pdf'>Download</a></html>"),
                     "https://court.example/files/d.pdf": Response(200, {"content-type": "application/pdf"}, pdf)})
    assert "refusal is affirmed" in explore("https://court.example/case", transport=http).text


# --- the search fallback -----------------------------------------------------------------------------------------------------------


def hit(url, title, snippet="", score=0.5):
    return SearchHit(url, title, snippet, score)


def test_a_dead_link_falls_back_to_a_search_by_headline_and_is_marked():
    http = FakeHttp({TRACKER: html("gone", 404), "https://www.publisher.example/news/licensing": html(ARTICLE)})
    search = FakeSearch([
        hit("https://other.example/unrelated", "Weather outlook for the weekend", "Rain expected"),
        hit("https://www.publisher.example/news/licensing?utm_source=x", "Regulators approve cross-border licensing scheme for open models", "Regulators approved...", 0.9),
    ])
    http.pages["https://www.publisher.example/news/licensing?utm_source=x"] = html(ARTICLE)
    result = explore(TRACKER, Context(title=HEADLINE, publication="Publisher"), transport=http, search=search)
    assert result.ok and result.via == "search" and result.direct_failure == "http_4xx" and result.failure is None
    assert result.url == "https://www.publisher.example/news/licensing"
    assert result.search.query == HEADLINE and result.search.score >= 0.9 and result.search.provider == "fake"
    assert "cross-border licensing scheme" in result.text and result.text_source == "page"
    record = result.as_record()
    assert record["via"] == "search" and record["search"]["matchScore"] == result.search.score
    assert SUBSCRIBER_FRAGMENT not in json.dumps(record) and search.queries == [HEADLINE]


def test_search_is_also_used_when_the_page_cannot_be_read_and_text_is_wanted():
    http = FakeHttp({"https://paywalled.example/a": html("no", 403), "https://open.example/copy": html(ARTICLE)})
    search = FakeSearch([hit("https://open.example/copy", HEADLINE)])
    result = explore("https://paywalled.example/a", Context(title=HEADLINE), transport=http, search=search)
    assert result.via == "search" and result.url == "https://open.example/copy" and result.direct_failure == "blocked"


def test_the_search_snippet_is_used_when_the_matched_page_cannot_be_read():
    http = FakeHttp({"https://paywalled.example/a": html("gone", 404), "https://other.example/copy": html("no", 403)})
    search = FakeSearch([hit("https://other.example/copy", HEADLINE, "Regulators approved the first scheme.")])
    result = explore("https://paywalled.example/a", Context(title=HEADLINE), transport=http, search=search)
    assert result.ok and result.text == "Regulators approved the first scheme." and result.text_source == "search_snippet"


def test_the_query_falls_back_from_headline_to_summary_to_anchor_text():
    assert le.search_query(Context(title=HEADLINE, summary="x")) == HEADLINE
    assert le.search_query(Context(title="", summary="Regulators approve a licensing scheme for open models.")).startswith("Regulators approve")
    assert le.search_query(Context(anchor_text="Regulators approve licensing scheme")) == "Regulators approve licensing scheme"
    assert le.search_query(Context(title="Read more", anchor_text="Click here")) is None
    assert le.search_query(Context(title="https://x.example/a?u=1 two words")) is None


def test_no_usable_text_means_no_query_and_no_search():
    http = FakeHttp({"https://publisher.example/a": html("gone", 404)})
    result = explore("https://publisher.example/a", Context(title="Read more"), transport=http, search=no_search_needed())
    assert not result.ok and result.failure == "no_query" and result.direct_failure == "http_4xx" and result.search_failure == "no_query"


def test_a_weak_match_is_no_match():
    http = FakeHttp({"https://publisher.example/a": html("gone", 404)})
    search = FakeSearch([hit("https://news.example/x", "Weather outlook for the weekend", "Rain expected on Saturday")])
    result = explore("https://publisher.example/a", Context(title=HEADLINE), transport=http, search=search)
    assert not result.ok and result.failure == "no_match" and result.direct_failure == "http_4xx"


def test_no_key_means_search_unavailable():
    http = FakeHttp({"https://publisher.example/a": html("gone", 404)})
    result = explore("https://publisher.example/a", Context(title=HEADLINE), transport=http, search=TavilySearch(environ={}))
    assert not result.ok and result.failure == "search_unavailable" and result.direct_failure == "http_4xx"
    assert explore("https://publisher.example/a", Context(title=HEADLINE), transport=http, search=FakeSearch(error=SearchUnavailable())).failure == "search_unavailable"


def test_a_provider_failure_is_search_error_and_never_raises():
    http = FakeHttp({"https://publisher.example/a": html("gone", 404)})
    for error in (SearchError("http_500"), RuntimeError("boom")):
        assert explore("https://publisher.example/a", Context(title=HEADLINE), transport=http, search=FakeSearch(error=error)).failure == "search_error"


def test_a_search_match_for_an_address_only_caller_is_not_fetched():
    http = FakeHttp({TRACKER: html("gone", 404)})
    search = FakeSearch([hit("https://www.publisher.example/news/licensing?utm_source=x", HEADLINE)])
    result = explore(TRACKER, Context(title=HEADLINE), want_text=False, transport=http, search=search)
    assert result.ok and result.via == "search" and result.url == "https://www.publisher.example/news/licensing" and http.asked == [TRACKER]


def test_the_publication_name_raises_the_score_of_its_own_domain():
    context = Context(title=HEADLINE, publication="Publisher Weekly")
    partial = "Regulators approve licensing scheme"
    own, other = hit("https://publisher.example/a", partial), hit("https://mirror.example/a", partial)
    assert le.match_score(HEADLINE, own, context) > le.match_score(HEADLINE, other, context)
    assert le.match_score(HEADLINE, hit("https://x.example/b", "Entirely different headline words here"), context) < le.MATCH_THRESHOLD


# --- the Tavily provider -----------------------------------------------------------------------------------------------------------


def test_tavily_reads_its_key_from_the_environment_and_parses_results():
    sent = []

    def post(payload, key):
        sent.append((payload, key))
        return {"results": [{"url": "https://a.example/x", "title": "T", "content": "C", "score": 0.8}, {"title": "no url"}]}

    provider = TavilySearch(environ={"TAVILY_API_KEY": " tvly-test "}, post=post)
    assert provider.search("query words here") == [SearchHit("https://a.example/x", "T", "C", 0.8)]
    assert sent[0][1] == "tvly-test" and sent[0][0]["query"] == "query words here"


def test_tavily_reads_its_key_from_the_named_ssm_parameter_once():
    reads = []
    provider = TavilySearch(environ={"PAPYRUS_TAVILY_KEY_PARAMETER": "/papyrus/shared/tavily-api-key"},
                            post=lambda payload, key: {"results": []}, read_secret=lambda name: reads.append(name) or "tvly-ssm")
    provider.search("a b c")
    provider.search("a b c")
    assert reads == ["/papyrus/shared/tavily-api-key"]


def test_tavily_without_a_key_or_with_an_unreadable_parameter_is_unavailable():
    with pytest.raises(SearchUnavailable):
        TavilySearch(environ={}).search("a b c")

    def denied(name):
        raise PermissionError(name)

    with pytest.raises(SearchUnavailable):
        TavilySearch(environ={"PAPYRUS_TAVILY_KEY_PARAMETER": "/x"}, read_secret=denied).search("a b c")


def test_a_malformed_tavily_answer_is_a_search_error():
    with pytest.raises(SearchError):
        TavilySearch(environ={"TAVILY_API_KEY": "k"}, post=lambda payload, key: {"unexpected": 1}).search("a b c")


# --- preview metadata (the References feed's image and dek) ------------------------------------------------------------------------


def page_with(head: str) -> str:
    return f"<html><head>{head}</head><body><p>{ARTICLE_TEXT}</p></body></html>"


def test_the_destination_page_preview_image_description_and_site_name_come_back():
    article = "https://www.publisher.example/news/licensing"
    head = ('<title>Licensing scheme approved</title><meta property="og:image" content="/img/hero.jpg">'
            '<meta property="og:description" content="Regulators  approved a   cross-border scheme."><meta property="og:site_name" content="Publisher">')
    result = explore(article, transport=FakeHttp({article: html(page_with(head))}), use_search=False)
    assert result.metadata == le.PageMetadata("https://www.publisher.example/img/hero.jpg", "Regulators approved a cross-border scheme.", "Publisher", "Licensing scheme approved")
    assert result.as_record()["metadata"]["imageUrl"] == "https://www.publisher.example/img/hero.jpg"


def test_twitter_image_is_the_fallback_and_og_image_wins_when_both_exist():
    assert le.page_metadata(page_with('<meta name="twitter:image" content="https://cdn.example/t.png">'), "https://a.example/p").image_url == "https://cdn.example/t.png"
    both = '<meta name="twitter:image" content="https://cdn.example/t.png"><meta property="og:image" content="https://cdn.example/o.png">'
    assert le.page_metadata(page_with(both), "https://a.example/p").image_url == "https://cdn.example/o.png"


def test_only_public_http_images_are_accepted():
    for bad in ("data:image/png;base64,AAAA", "javascript:alert(1)", "http://127.0.0.1/x.png", "http://localhost/x.png", "https://user:pw@cdn.example/x.png"):
        assert le.page_metadata(page_with(f'<meta property="og:image" content="{bad}">'), "https://a.example/p").image_url is None, bad


def test_a_page_with_no_preview_metadata_gives_an_empty_result_and_a_long_description_is_cut():
    assert le.page_metadata(page_with(""), "https://a.example/p") == le.PageMetadata()
    long = "word " * 200
    cut = le.page_metadata(page_with(f'<meta name="description" content="{long}">'), "https://a.example/p").description
    assert cut is not None and len(cut) <= le.DESCRIPTION_LIMIT and cut.endswith("…")


def test_a_blocked_page_still_reports_nothing_and_never_raises():
    article = "https://www.publisher.example/news/licensing"
    result = explore(article, transport=FakeHttp({article: html("no", 403)}), use_search=False)
    assert not result.ok and result.metadata is None
