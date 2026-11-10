"""Paper feeds: the general RSS/Atom reader (`sourceType: feed`) with its arXiv rule, and the Hugging Face daily papers source.

Every response here is a recorded one (fixtures/feeds); nothing touches the network.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

from papyrus_content import monitoring_feed as feed
from papyrus_content import monitoring_hf_papers as papers
from papyrus_content import monitoring_router as mr
from papyrus_content.monitoring import SOURCE_TYPES
from papyrus_content.monitoring_cloud import DynamoStore, _validate_config, run_collection
from papyrus_content.monitoring_paging import RateLimited

from test_monitoring_router import FakeTable

FIXTURES = Path(__file__).parent / "fixtures" / "feeds"
ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 11, 3, 19, 0, tzinfo=timezone.utc).timestamp()
DAY = 86400
AI_FEED = "https://rss.arxiv.org/rss/cs.AI+cs.LG+cs.CL+cs.MA+stat.ML"
SECURITY_FEED = "https://rss.arxiv.org/rss/cs.CR"
ATOM_FEED = "https://export.arxiv.org/api/query?search_query=cat:cs.CR&max_results=2"
PAPERS = "https://huggingface.co/api/daily_papers"
METR_FEED = "https://metr.org/feed.xml"


def read(name) -> bytes:
    return (FIXTURES / name).read_bytes()


def by_id(items):
    return {item.source_id: item for item in items}


def feed_config(url=AI_FEED, **more):
    return {"pk": "MONITOR#papers", "sk": "CONFIG", "sourceType": "feed", "sourceUrl": url, "intervalSeconds": 6 * 3600,
            "enabled": True, **more}


def run(table, monitor, fetch, now=NOW):
    return run_collection(DynamoStore(table), monitor, fetch=fetch, now=now)


# --- the arXiv RSS feed ----------------------------------------------------------------------------

def test_arxiv_rss_keeps_new_and_cross_and_skips_revisions():
    items = by_id(feed.parse_feed(read("arxiv-ai-rss.xml"), AI_FEED))

    assert list(items) == ["2611_00015", "2611_03424", "2609_23790"]        # replace (1903.07745) and replace-cross (2303.16880) are gone


def test_an_arxiv_item_is_the_paper_with_its_abstract_as_details():
    item = by_id(feed.parse_feed(read("arxiv-ai-rss.xml"), AI_FEED))["2611_00015"]

    assert item.canonical_url == item.source_item_url == "https://arxiv.org/abs/2611.00015"
    assert item.title == "Output-Aware Block Influence: Jacobian-Lens Weighting for Depth Pruning"
    assert item.published_at == "2026-11-03T05:00:00Z"
    assert item.details["arxivId"] == "2611.00015" and item.details["announceType"] == "new"
    assert item.details["publishedAt"] == item.published_at and item.details["title"] == item.title
    assert item.details["authors"][0] == "Kyle Lemoi" and item.details["categories"] == ["cs.LG", "cs.AI"]


def test_the_abstract_loses_the_feeds_header_and_label_and_keeps_latex_as_is():
    abstract = by_id(feed.parse_feed(read("arxiv-ai-rss.xml"), AI_FEED))["2611_00015"].details["abstract"]

    assert abstract.startswith("Depth pruning removes entire transformer blocks")
    assert "Announce Type" not in abstract and "Abstract:" not in abstract
    assert "$BI$" in abstract and "$J-BI$" in abstract


@pytest.mark.parametrize("text, expected", [
    ("arXiv:2611.00015v1 Announce Type: new \nAbstract: We study $x^2$.", "We study $x^2$."),
    ("arXiv:2611.00015v1 Announce Type: cross \nAbstract:  Spaces.", "Spaces."),
    ("Abstract: Only the label.", "Only the label."),
    ("No prefix, and an Abstract: later in the text.", "No prefix, and an Abstract: later in the text."),
    ("", "")])
def test_strip_arxiv_header(text, expected):
    assert feed.strip_arxiv_header(text) == expected


def test_the_source_id_is_the_bare_arxiv_id_without_the_version():
    rss = '''<rss version="2.0" xmlns:arxiv="http://arxiv.org/schemas/atom"><channel>
      <item><title>Versioned</title><link>https://arxiv.org/abs/2611.00159v3</link><guid>oai:arXiv.org:2611.00159v3</guid>
        <description>arXiv:2611.00159v3 Announce Type: new \nAbstract: Text.</description><arxiv:announce_type>new</arxiv:announce_type></item>
      <item><title>Guid only</title><link>https://example.test/not-arxiv</link><guid>oai:arXiv.org:2611.00160v2</guid>
        <arxiv:announce_type>new</arxiv:announce_type></item>
      <item><title>Old style</title><link>https://arxiv.org/abs/cs/0112017</link><arxiv:announce_type>new</arxiv:announce_type></item>
    </channel></rss>'''.encode()

    items = feed.parse_feed(rss, SECURITY_FEED)

    assert [(i.source_id, i.canonical_url) for i in items] == [
        ("2611_00159", "https://arxiv.org/abs/2611.00159"), ("2611_00160", "https://arxiv.org/abs/2611.00160"),
        ("cs--0112017", "https://arxiv.org/abs/cs/0112017")]
    assert all(feed.SOURCE_ID.match(i.source_id) for i in items)


def test_an_entry_listed_twice_is_one_item():
    rss = b'''<rss version="2.0"><channel>
      <item><title>Twice</title><link>https://arxiv.org/abs/2611.00001</link></item>
      <item><title>Twice</title><link>https://arxiv.org/abs/2611.00001</link></item></channel></rss>'''

    assert len(feed.parse_feed(rss, SECURITY_FEED)) == 1


# --- the Atom feed ---------------------------------------------------------------------------------

def test_an_atom_feed_is_read_the_same_way():
    items = feed.parse_feed(read("arxiv-api-atom.xml"), ATOM_FEED)

    assert [i.source_id for i in items] == ["2611_03558", "2611_03555"]
    first = items[0]
    assert first.canonical_url == "https://arxiv.org/abs/2611.03558"             # the version is dropped from the address
    assert first.title == "Quantum Private Information Retrieval on Forests" and first.published_at == "2026-11-02T18:19:25Z"
    assert first.details["abstract"].startswith("We consider the problem of graph private information retrieval")
    assert first.details["authors"] and first.details["categories"]


# --- any other feed, on a host that is allowed -----------------------------------------------------

@pytest.fixture
def other_host(monkeypatch):
    monkeypatch.setitem(feed.FEED_HOSTS, "feeds.example.test", "Example Journal")
    return "https://feeds.example.test/rss.xml"


def test_a_feed_on_a_host_with_no_rule_uses_the_entrys_own_id_and_link(other_host):
    rss = b'''<rss version="2.0"><channel>
      <item><title>  A study of
          things </title><link>https://feeds.example.test/a?utm_source=rss&amp;id=7</link>
        <guid isPermaLink="false">urn:example:article:7</guid><pubDate>Mon, 02 Nov 2026 12:00:00 GMT</pubDate>
        <description>An abstract.</description></item></channel></rss>'''

    (item,) = feed.parse_feed(rss, other_host)

    assert item.title == "A study of things" and item.canonical_url == "https://feeds.example.test/a?id=7"
    assert item.source_id.startswith("urn_example_article_7-") and feed.SOURCE_ID.match(item.source_id)
    assert item.source_id == feed.safe_source_id("urn:example:article:7")
    assert item.published_at == "2026-11-02T12:00:00Z" and item.details == {
        "title": "A study of things", "publishedAt": "2026-11-02T12:00:00Z", "abstract": "An abstract."}


def test_an_entry_with_no_title_or_link_or_a_bad_date_does_not_stop_the_feed(other_host):
    rss = b'''<rss version="2.0"><channel>
      <item><title>No link</title></item><item><link>https://feeds.example.test/b</link></item>
      <item><title>Odd date</title><link>https://feeds.example.test/c</link><pubDate>last Tuesday</pubDate></item></channel></rss>'''

    assert [(i.title, i.published_at) for i in feed.parse_feed(rss, other_host)] == [("Odd date", None)]


# --- refusals --------------------------------------------------------------------------------------

def test_a_doctype_or_entity_declaration_is_refused():
    with pytest.raises(ValueError, match="unsupported XML declaration"):
        feed.parse_feed(read("doctype-rss.xml"), SECURITY_FEED)
    with pytest.raises(ValueError, match="unsupported XML declaration"):
        feed.parse_feed(b'<?xml version="1.0"?><!entity x "y"><rss version="2.0"><channel/></rss>', SECURITY_FEED)


def test_an_empty_feed_is_fine():
    assert feed.parse_feed(read("empty-rss.xml"), SECURITY_FEED) == []


@pytest.mark.parametrize("body", [read("malformed-rss.xml"), b"<html><body>503</body></html>", b"", b"[1, 2]"])
def test_a_feed_that_is_not_a_feed_is_an_error(body):
    with pytest.raises(ValueError):
        feed.parse_feed(body, SECURITY_FEED)


def test_an_oversized_document_is_refused():
    with pytest.raises(ValueError, match="oversized"):
        feed.parse_feed(b"<rss>" + b" " * feed.MAX_FEED_DOCUMENT_BYTES + b"</rss>", SECURITY_FEED)


def test_the_real_arxiv_daily_feed_fits_the_size_limit():
    assert feed.MAX_FEED_DOCUMENT_BYTES > 3_600_000          # measured: 3.59 MB for the five-category feed on 2026-11-03


@pytest.mark.parametrize("url", ["https://evil.example/rss", "http://rss.arxiv.org/rss/cs.CR", "https://user:pw" + "@rss.arxiv.org/rss/cs.CR",
                                 "https://rss.arxiv.org.evil.example/rss/cs.CR", "https://rss.arxiv.org/rss/cs.CR#x", "", "ftp://rss.arxiv.org/x"])
def test_a_host_outside_the_list_or_a_bad_address_is_refused(url):
    with pytest.raises(ValueError, match="https URL on one of"):
        feed.check_feed_url(url)
    with pytest.raises(ValueError):
        _validate_config({"sourceType": "feed", "sourceUrl": url, "intervalSeconds": 3600})


def test_the_fetch_checks_the_address_before_any_request(monkeypatch):
    monkeypatch.setattr(feed, "urlopen", lambda *a, **k: pytest.fail("requested"))

    with pytest.raises(ValueError):
        feed.fetch_feed("https://evil.example/rss")


def test_the_fetch_bounds_the_response_and_names_the_rate_limit(monkeypatch):
    class Response:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n): return self.body[:n]

    seen = {}
    monkeypatch.setattr(feed, "urlopen", lambda request, timeout: seen.update(agent=request.get_header("User-agent")) or Response(b"x" * (feed.MAX_FEED_DOCUMENT_BYTES + 5)))
    with pytest.raises(ValueError, match="size bound"):
        feed.fetch_feed(SECURITY_FEED)
    assert seen["agent"].startswith("Papyrus-Monitor/")

    from urllib.error import HTTPError
    from email.message import Message
    headers = Message()
    headers["Retry-After"] = "30"

    def limited(request, timeout):
        raise HTTPError(request.full_url, 429, "Too Many Requests", headers, None)

    monkeypatch.setattr(feed, "urlopen", limited)
    with pytest.raises(RateLimited) as limit:
        feed.fetch_feed(SECURITY_FEED)
    assert limit.value.retry_after == 30


# --- config and wiring -----------------------------------------------------------------------------

def test_the_feed_address_is_configuration_and_a_query_is_allowed():
    config = _validate_config(feed_config(ATOM_FEED))

    assert config["sourceType"] == "feed" and config["sourceUrl"] == ATOM_FEED and config["intervalSeconds"] == 6 * 3600


def test_the_papers_config_defaults_and_bounds():
    config = _validate_config({"sourceType": "huggingface-papers", "sourceUrl": PAPERS, "intervalSeconds": 3600})

    assert (config["lookbackDays"], config["pageSize"]) == (7, 100)
    for bad in ({"lookbackDays": 0}, {"lookbackDays": 400}, {"pageSize": 101}, {"pageSize": 0}):
        with pytest.raises(ValueError):
            _validate_config({"sourceType": "huggingface-papers", "sourceUrl": PAPERS, "intervalSeconds": 3600, **bad})
    with pytest.raises(ValueError, match="huggingface-papers"):
        _validate_config({"sourceType": "huggingface-papers", "sourceUrl": "https://huggingface.co/api/models", "intervalSeconds": 3600})
    with pytest.raises(ValueError):
        _validate_config({"sourceType": "huggingface-papers", "sourceUrl": "https://example.org/api/daily_papers", "intervalSeconds": 3600})


def test_the_sources_have_names_and_cyclotron_sources():
    assert mr.source_name_for(SECURITY_FEED, "feed") == "arXiv" and mr.source_name_for(ATOM_FEED) == "arXiv"
    assert mr.source_name_for(PAPERS, "huggingface-papers") == "Hugging Face Papers"
    assert mr.source_name_for("https://huggingface.co/api/models", "huggingface-models") == "Hugging Face Hub"
    assert mr.source_name_for("https://news.ycombinator.com/rss") == "Hacker News"
    assert SOURCE_TYPES["feed"]["name"] == "Feed" and mr.ITEM_SOURCES["feed"] in mr.ITEM_SOURCE_NAMES
    assert mr.ITEM_SOURCES["huggingface-papers"] in mr.ITEM_SOURCE_NAMES


# --- the Hugging Face daily papers -----------------------------------------------------------------

def hf_rows():
    return json.loads(read("hf-daily-papers.json"))


def test_a_daily_paper_is_the_arxiv_paper_with_its_signals():
    (item, *_) = [papers.paper_item(d) for d in papers.parse_papers(read("hf-daily-papers.json"))]

    assert item.canonical_url == "https://arxiv.org/abs/2611.03424" and item.source_item_url == item.canonical_url
    assert item.source_id == "2611_03424" and item.title.startswith("IdeaTaste: Do LLMs Share")
    assert item.details["upvotes"] == 15 and item.details["comments"] == 1
    assert item.details["abstract"].startswith("Research taste, the judgment of what to read")
    assert item.details["authors"][0] == "Shanshan Zhong" and item.details["submittedBy"] == "zhongshsh"
    assert item.details["organization"] == "Carnegie Mellon University School of Computer Science"
    assert item.details["arxivId"] == "2611.03424" and "avatarUrl" not in json.dumps(item.details)


def test_the_same_paper_from_arxiv_and_hugging_face_has_one_canonical_url_and_source_id():
    from_arxiv = by_id(feed.parse_feed(read("arxiv-ai-rss.xml"), AI_FEED))["2611_03424"]
    from_hf = papers.paper_item(papers.parse_papers(read("hf-daily-papers.json"))[0])

    assert from_arxiv.canonical_url == from_hf.canonical_url == "https://arxiv.org/abs/2611.03424"
    assert from_arxiv.source_id == from_hf.source_id


def test_rows_that_are_not_usable_papers_are_skipped_and_error_pages_refused():
    rows = hf_rows() + [{"paper": {"id": "not-an-arxiv-id", "title": "Bad id"}}, {"paper": {"id": "2611.00001"}}, {"title": "No paper"}, "junk"]

    assert [d["arxivId"] for d in papers.parse_papers(json.dumps(rows).encode())] == ["2611.03424", "2611.03097", "2610.38293"]
    for body in (b"<html>nope</html>", json.dumps({"error": "bad"}).encode()):
        with pytest.raises(ValueError):
            papers.parse_papers(body)


def test_only_the_daily_papers_url_is_ever_requested(monkeypatch):
    monkeypatch.setattr(papers, "urlopen", lambda *a, **k: pytest.fail("requested"))
    for url in ("https://huggingface.co/api/models", "http://huggingface.co/api/daily_papers", "https://evil.example/api/daily_papers"):
        with pytest.raises(ValueError):
            papers.fetch_papers_page(url)


class Daily:
    """Replays the recorded rows as the API would: newest first, `limit` rows a page, the next page named in the Link header."""

    def __init__(self, rows):
        self.rows, self.requests = rows, []

    def __call__(self, url):
        from urllib.parse import parse_qs, urlsplit
        self.requests.append(url)
        params = parse_qs(urlsplit(url).query)
        limit, page = int(params["limit"][0]), int(params.get("p", ["0"])[0])
        rows = self.rows[page * limit:(page + 1) * limit]
        following = f"{PAPERS}?limit={limit}&p={page + 1}" if rows else None
        return json.dumps(rows).encode(), following


def papers_config(**more):
    return {"pk": "MONITOR#papers-huggingface", "sk": "CONFIG", "sourceType": "huggingface-papers", "sourceUrl": PAPERS,
            "intervalSeconds": 6 * 3600, "enabled": True, **more}


def test_every_recent_row_is_read_page_by_page_until_the_window_ends():
    table = FakeTable()
    table.put_item(papers_config(pageSize=1, lookbackDays=2))
    api = Daily(hf_rows())

    result = run(table, "papers-huggingface", api)

    assert result["new"] == 2 and result["status"] == "complete"              # the third paper was picked on 10-30: outside the window
    assert len(api.requests) == 3 and all(u.startswith(PAPERS + "?limit=1") for u in api.requests)
    assert {r["sourceId"]: r["sourceType"] for r in table.by_prefix("DISC#")} == {"2611_03424": "huggingface-papers", "2611_03097": "huggingface-papers"}


def test_a_later_pass_stops_at_the_papers_it_already_has_and_votes_do_not_revise_them():
    table = FakeTable()
    table.put_item(papers_config(pageSize=1, lookbackDays=30))
    run(table, "papers-huggingface", Daily(hf_rows()))
    rows = hf_rows()
    rows[0]["paper"]["upvotes"] = 99                                             # the vote count moves; the paper is the same
    api = Daily(rows)

    result = run(table, "papers-huggingface", api, NOW + 7 * 3600)

    assert (result["new"], result["revised"], result["unchanged"]) == (0, 0, 1)
    assert len(api.requests) == 1                                                # the first page held a collected paper: the high-water mark


def test_a_rate_limited_page_is_waited_out_or_resumed_next_pass():
    table = FakeTable()
    table.put_item(papers_config(pageSize=1, lookbackDays=30))
    api, calls = Daily(hf_rows()), []

    def limited(url):
        calls.append(url)
        if len(calls) == 2:
            raise RateLimited("slow down", 10_000)
        return api(url)

    result = run_collection(DynamoStore(table), "papers-huggingface", fetch=limited, now=NOW)

    assert result["new"] == 1 and any("rate_limited" in e["message"] for e in result["errors"])
    assert table.get_item({"pk": "MONITOR#papers-huggingface", "sk": "STATE"})["Item"]["resume"]


# --- METR (RSS 2.0 with full-content `content:encoded`, no description) ----------------------------

def test_the_metr_feed_is_read_by_the_general_reader():
    assert feed.FEED_HOSTS["metr.org"] == "METR" and feed.check_feed_url(METR_FEED) == METR_FEED
    items = feed.parse_feed(read("metr-rss.xml"), METR_FEED)

    assert [i.title for i in items][:2] == ['Review of the "Risks from automated R&D" section in Anthropic\'s Risk Report (August 2026)',
                                           "Implementing and Evaluating a Basic Per-Action Monitor for Safer Evals"]
    assert len(items) == 5 and len({i.source_id for i in items}) == 5
    first = items[0]
    assert first.canonical_url == first.source_item_url == "https://metr.org/blog/2026-11-05-rd-section-anthropic-risk-report-august-2026-review/"
    assert first.published_at == "2026-11-05T08:00:00Z" and first.details["publishedAt"] == first.published_at
    assert first.details["abstract"].startswith("<p>Redaction summary")      # the post's content:encoded, as the feed gives it
    assert "authors" not in first.details and "categories" not in first.details


def test_a_metr_entry_is_keyed_on_its_guid_and_addressed_by_its_link():
    items = by_id(feed.parse_feed(read("metr-rss.xml"), METR_FEED))
    evaluation = next(i for i in items.values() if i.title == "GPT-5.1-Codex-Max Evaluation Results")

    assert evaluation.canonical_url == "https://metr.org/evaluations/gpt-5-1-codex-max-report/"     # /evaluations/ link, /blog/ guid
    assert evaluation.source_id.startswith("https___metr_org_blog_2025-11-19-gpt-5-1-codex-max-repo-")
    paper = next(i for i in items.values() if i.title.startswith("HCAST"))
    assert paper.canonical_url == "https://arxiv.org/abs/2503.17354"                              # a post that points off the site
    root_page = next(i for i in items.values() if i.title == "Frontier AI Safety Policies")
    assert root_page.canonical_url == "https://metr.org/fsp"                                       # a site-root link


def test_a_metr_item_without_title_or_link_is_left_out_and_the_channel_is_not_an_entry():
    body = read("metr-rss.xml").decode().replace("</channel>", "<item><title>No link</title><guid>x</guid></item>"
                                                  "<item><link>https://metr.org/blog/y/</link><guid>y</guid></item></channel>")

    assert len(feed.parse_feed(body.encode(), METR_FEED)) == 5


def long_metr_feed() -> bytes:
    return read("metr-rss.xml").decode().replace("</channel>", "<item><title>Long</title><link>https://metr.org/blog/long/</link>"
        "<guid>https://metr.org/blog/long/</guid><content:encoded><![CDATA[" + "x" * 800_000 + "]]></content:encoded></item></channel>").encode()


def test_a_long_metr_post_is_cut_to_the_abstract_limit_before_it_is_stored():
    table = FakeTable()
    table.put_item(feed_config(METR_FEED))

    run(table, "papers", lambda url: long_metr_feed())

    row = next(r for r in table.by_prefix("DISC#") if r["canonicalUrl"] == "https://metr.org/blog/long/")
    assert len(row["details"]["abstract"]) == feed.MAX_ABSTRACT_CHARACTERS == 20_000
    assert all(len(json.dumps(r, default=str)) < 100_000 for r in table.by_prefix("DISC#"))


# --- collection of a feed --------------------------------------------------------------------------

def test_a_feed_monitor_collects_papers_and_dedupes_on_the_next_pass():
    table = FakeTable()
    table.put_item(feed_config())

    first = run(table, "papers", lambda url: read("arxiv-ai-rss.xml"))
    second = run(table, "papers", lambda url: read("arxiv-ai-rss.xml"), NOW + 7 * 3600)

    assert (first["new"], first["status"]) == (3, "complete") and (second["new"], second["unchanged"]) == (0, 3)
    disc = {r["sourceId"]: r for r in table.by_prefix("DISC#")}
    assert set(disc) == {"2611_00015", "2611_03424", "2609_23790"}
    row = disc["2611_00015"]
    assert row["canonicalUrl"] == "https://arxiv.org/abs/2611.00015" and row["sourceType"] == "feed" and row["routing"] == "collected"
    assert row["details"]["abstract"].startswith("Depth pruning") and row["sourcePublishedAt"] == "2026-11-03T05:00:00Z"


def test_a_long_feed_is_read_whole_in_pages_and_resumes_after_the_last_committed_entry(monkeypatch):
    monkeypatch.setattr(feed, "FEED_PAGE_ITEMS", 2)
    table = FakeTable()
    table.put_item(feed_config())

    result = run(table, "papers", lambda url: read("arxiv-ai-rss.xml"))

    assert result["new"] == 3                                                    # two pages: 2 + 1 entries
    page = feed.feed_page_reader(lambda: feed.parse_feed(read("arxiv-ai-rss.xml"), AI_FEED))
    assert page(None)[1] == "2611_03424"                                        # the cursor is an entry id, not an offset
    assert [i.source_id for i in page("2611_03424")[0]] == ["2609_23790"] and page("2611_03424")[1] is None
    assert [i.source_id for i in page("gone-from-the-feed")[0]] == ["2611_00015", "2611_03424"]   # an id that left the feed starts over


def test_the_five_category_feed_size_is_committed_in_pages():
    items = [feed.SourceItem(f"{n:05d}", f"T{n}", f"https://arxiv.org/abs/2611.{n:05d}", "u", None) for n in range(1090)]
    page = feed.feed_page_reader(lambda: items)
    seen, cursor = [], None
    while True:
        rows, cursor = page(cursor)
        assert len(rows) <= feed.FEED_PAGE_ITEMS
        seen += rows
        if cursor is None:
            break

    assert seen == items


def test_an_empty_feed_is_a_complete_pass_and_a_broken_one_is_a_failed_pass():
    empty, broken = FakeTable(), FakeTable()
    empty.put_item(feed_config(SECURITY_FEED))
    broken.put_item(feed_config(SECURITY_FEED))

    assert run(empty, "papers", lambda url: read("empty-rss.xml"))["status"] == "complete"
    failed = run(broken, "papers", lambda url: read("malformed-rss.xml"))
    assert failed["status"] == "failed" and failed["errors"][0]["stage"] == "fetch"
    assert not broken.by_prefix("DISC#")


# --- what the decision sees ------------------------------------------------------------------------

def disc_of(item, source_type="feed"):
    return {"sourceId": item.source_id, "monitorId": "papers-arxiv-ai", "title": item.title, "canonicalUrl": item.canonical_url,
            "sourceItemUrl": item.source_item_url, "sourceType": source_type, "details": item.details}


def test_the_decision_uses_the_feeds_abstract_when_enrichment_has_no_summary():
    item = by_id(feed.parse_feed(read("arxiv-ai-rss.xml"), AI_FEED))["2611_00015"]

    values = mr.build_item(disc_of(item))["values"]

    assert values["source"] == "feed" and values["summary"] == item.details["abstract"]
    assert values["text"] == f"{item.title}\n{item.canonical_url}\n\n{item.details['abstract']}"
    assert mr.build_item(disc_of(item), {"summary": "A model summary.", "body": ""})["values"]["summary"] == "A model summary."


def test_a_hugging_face_paper_also_decides_on_its_abstract_and_a_model_does_not():
    item = papers.paper_item(papers.parse_papers(read("hf-daily-papers.json"))[0])

    values = mr.build_item(disc_of(item, "huggingface-papers"))["values"]
    assert values["source"] == "huggingface-papers" and values["summary"].startswith("Research taste")
    model = mr.build_item({**disc_of(item, "huggingface-models"), "details": {"abstract": "ignored"}})["values"]
    assert "summary" not in model


def test_a_paper_item_passes_the_request_validator():
    item = by_id(feed.parse_feed(read("arxiv-ai-rss.xml"), AI_FEED))["2611_00015"]
    body = {"contractVersion": mr.CONTRACT_VERSION, "operation": "decide", "requestId": "r" * 16,
            "payload": {"bindingRevision": "1", "item": mr.build_item(disc_of(item))}}

    mr.validate_request(body)


def test_intake_notes_a_paper_without_model_fields():
    from papyrus_content.monitoring_intake import ReferenceIntake
    item = papers.paper_item(papers.parse_papers(read("hf-daily-papers.json"))[0])
    arxiv = by_id(feed.parse_feed(read("arxiv-ai-rss.xml"), AI_FEED))["2611_00015"]

    assert ReferenceIntake._details_note(item) == " 15 upvotes on Hugging Face; 1 comment."
    assert ReferenceIntake._details_note(arxiv) == ""


# --- packaging -------------------------------------------------------------------------------------

def test_the_new_modules_are_in_the_collector_and_router_zips():
    sys.path.insert(0, str(ROOT / "infra" / "monitoring"))
    try:
        import build
    finally:
        sys.path.pop(0)

    assert {"monitoring_feed", "monitoring_hf_papers"} <= set(build.package_modules(build.COLLECTOR_ROOTS))
    assert {"monitoring_feed", "monitoring_hf_papers"} <= set(build.package_modules(build.ROUTER_ROOTS))
