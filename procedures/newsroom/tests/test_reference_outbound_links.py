"""Every Reference's outbound links are recorded at capture, content links told apart from navigation, footer and thanks (PPY-31821c).

No network, no AWS, no model. The acceptance page is a saved copy of a public blog hub page (fixtures/kjam-memorization-hub.html).
"""
from __future__ import annotations

import json
from pathlib import Path

from curation_support import MemoryClient, article_html, page, reference, services
from papyrus_content import reference_capture, reference_curation as curation
from papyrus_content.reference_outbound_links import CONTENT, content_links, extract_links, links_document, summarize_links
from papyrus_content.reference_curation_store import LINKS_SORT_KEY, read_card

HUB_URL = "https://blog.kjamistan.com/a-deep-dive-into-memorization-in-deep-learning.html"
HUB = (Path(__file__).parent / "fixtures" / "kjam-memorization-hub.html").read_text(encoding="utf-8")
PLAYLIST = "https://www.youtube.com/watch?v=JDAPDpbXRXw&list=PLJkNSeYcYBlCaamscxip0l2LGYCZ2TIom&ab_channel=ProbablyPrivate"


def by_kind(links):
    kinds: dict[str, list[str]] = {}
    for link in links:
        kinds.setdefault(link["kind"], []).append(link["url"])
    return kinds


# --- the acceptance page -------------------------------------------------------------------------------------------------------------------


def test_the_series_hub_has_its_articles_and_the_playlist_as_content_links_and_nothing_else():
    links = extract_links(HUB, HUB_URL)
    kinds = by_kind(links)
    series = [url for url in kinds[CONTENT] if url.startswith("https://blog.kjamistan.com/") and url.endswith(".html")]
    assert len(series) == 18 and len(kinds[CONTENT]) == 19   # the page's ordered list has 18 articles (23 links in all: 18 + category + playlist + 3 thanks)
    assert PLAYLIST in kinds[CONTENT]
    assert all(link["listed"] for link in links if link["url"] in series), "the series is a list, and followers can see it"
    # the category page, the three thanks links and the page's chrome are not content
    assert "https://blog.kjamistan.com/category/ml-memorization.html" not in kinds[CONTENT]
    assert not {"https://vickiboykis.com/", "https://desfontain.es/serious.html", "https://www.linkedin.com/in/yanndupis/"} & set(kinds[CONTENT])
    assert set(kinds["credit"]) == {"https://vickiboykis.com/", "https://desfontain.es/serious.html"}
    assert kinds["profile"] == ["https://www.linkedin.com/in/yanndupis/"]
    assert "https://probablyprivate.com/" in kinds["navigation"] and "https://twitter.com/kjam" in kinds["navigation"]
    assert set(kinds["footer"]) == {"http://getpelican.com", "http://bit.ly/flex-pelican"}
    assert summarize_links(links) == {"total": len(links), "content": 19}


def test_links_keep_page_order_and_each_address_once():
    links = extract_links(HUB, HUB_URL)
    assert [link["position"] for link in links] == list(range(1, len(links) + 1))
    assert len({link["url"] for link in links}) == len(links)
    assert links_document(links, HUB_URL).count("\"kind\"") == len(links)


# --- the rule on small pages ---------------------------------------------------------------------------------------------------------------


def test_a_page_without_landmarks_treats_links_outside_nav_like_classes_as_content():
    html = '<div class="menu"><a href="/home">Home</a></div><p>See <a href="https://example.org/a">the report</a>.</p>'
    kinds = by_kind(extract_links(html, "https://site.example/post"))
    assert kinds[CONTENT] == ["https://example.org/a"] and kinds["navigation"] == ["https://site.example/home"]


def test_only_http_links_off_the_page_itself_are_recorded_and_relative_ones_resolve():
    html = ('<article><a href="#top">Top</a><a href="mailto:x@y.example">Mail</a><a href="javascript:void(0)">JS</a><a href="tel:1">Call</a>'
            '<a href="/dir/post">Self</a><a href="https://site.example/dir/post#frag">Self fragment</a><a href="../other">Other</a>'
            '<a href="https://example.org/x?utm_source=a">Tracked</a></article>')
    links = extract_links(html, "https://site.example/dir/post")
    assert [link["url"] for link in links] == ["https://site.example/other", "https://example.org/x?utm_source=a"]   # kept as found: a follower decides what is tracking
    assert all(link["kind"] == CONTENT for link in links)


def test_a_link_in_a_footer_a_sidebar_or_a_header_is_not_content_even_inside_main():
    html = ('<main><header><a href="https://e.org/cat">Category</a></header><p><a href="https://e.org/body">Body</a></p>'
            '<aside><a href="https://e.org/side">Side</a></aside><footer><a href="https://e.org/foot">Foot</a></footer></main>')
    kinds = by_kind(extract_links(html, "https://site.example/p"))
    assert kinds[CONTENT] == ["https://e.org/body"]
    assert kinds["navigation"] == ["https://e.org/cat", "https://e.org/side"] and kinds["footer"] == ["https://e.org/foot"]


def test_rel_tag_and_rel_author_links_are_navigation():
    html = '<article><p><a rel="tag" href="https://e.org/tag/x">x</a> <a rel="author" href="https://e.org/me">me</a> <a href="https://e.org/real">real</a></p></article>'
    assert by_kind(extract_links(html, "https://site.example/p"))[CONTENT] == ["https://e.org/real"]


def test_a_thanks_passage_and_a_thanks_heading_are_credits_and_a_sentence_that_only_says_thanks_to_is_content():
    html = ('<article><p>Thanks to <a href="https://e.org/method">this method</a> the run got faster.</p>'
            '<p>We thank <a href="https://e.org/ann">Ann</a> and <a href="https://e.org/bob">Bob</a>.</p>'
            '<h2>Acknowledgements</h2><ul><li><a href="https://e.org/carol">Carol</a></li></ul>'
            '<h2>Further reading</h2><ul><li><a href="https://e.org/more">More</a></li></ul></article>')
    kinds = by_kind(extract_links(html, "https://site.example/p"))
    assert kinds[CONTENT] == ["https://e.org/method", "https://e.org/more"]
    assert kinds["credit"] == ["https://e.org/ann", "https://e.org/bob", "https://e.org/carol"]


def test_a_social_profile_link_is_a_profile_and_a_post_link_is_content():
    html = ('<article><p><a href="https://www.linkedin.com/in/someone/">L</a> <a href="https://x.com/someone">X</a> '
            '<a href="https://x.com/someone/status/1">Post</a> <a href="https://github.com/org/repo">Repo</a></p></article>')
    kinds = by_kind(extract_links(html, "https://site.example/p"))
    assert kinds["profile"] == ["https://www.linkedin.com/in/someone/", "https://x.com/someone"]
    assert kinds[CONTENT] == ["https://x.com/someone/status/1", "https://github.com/org/repo"]


def test_the_same_address_in_the_menu_and_the_body_counts_as_content():
    html = '<nav><a href="https://e.org/a">Menu</a></nav><article><p><a href="https://e.org/a">In text</a></p></article>'
    (link,) = extract_links(html, "https://site.example/p")
    assert link["kind"] == CONTENT and link["label"] == "Menu"


def test_an_image_link_takes_its_label_from_the_alt_text_and_broken_html_still_yields_the_links_before_it():
    (image,) = extract_links('<article><a href="https://e.org/i"><img src="x.png" alt="A chart"></a></article>', "https://site.example/p")
    assert image["label"] == "A chart"
    assert extract_links('<article><a href="https://e.org/a">A</a><<<>>><a href="https://e.org/b"', "https://site.example/p")[0]["url"] == "https://e.org/a"
    assert extract_links("", "https://site.example/p") == []


def test_followers_use_only_content_links():
    assert [link["url"] for link in content_links(extract_links(HUB, HUB_URL))][-1] == PLAYLIST


# --- capture stores them ----------------------------------------------------------------------------------------------------------------------


def test_capture_records_the_links_of_the_page_it_read():
    captured = reference_capture.capture_source(HUB_URL, explorer=services(MemoryClient([]), pages={HUB_URL: page(HUB)}).explorer)
    assert captured.ok and len(captured.links) == len(extract_links(HUB, HUB_URL))
    assert captured.links == extract_links(HUB, captured.destination_url or HUB_URL)


def test_a_capture_that_failed_for_lack_of_text_still_records_its_links():
    html = '<html><body><nav><a href="https://e.org/n">N</a></nav><div><a href="https://e.org/x"><img src="a.png"></a></div></body></html>'
    captured = reference_capture.capture_source("https://site.example/p", explorer=services(MemoryClient([]), pages={"https://site.example/p": page(html)}).explorer)
    assert not captured.ok and captured.failure == "no_text"
    assert [link["url"] for link in captured.links] == ["https://e.org/n", "https://e.org/x"]


def test_a_failed_fetch_has_no_links():
    assert reference_capture.capture_source("https://site.example/missing", explorer=services(MemoryClient([]), pages={}).explorer).links == []


def test_the_curation_run_stores_the_links_in_an_attachment_and_the_counts_on_the_card():
    ref = reference(sourceUri=HUB_URL)
    client = MemoryClient([ref])
    svc = services(client, pages={HUB_URL: page(HUB)})
    curation.curate_reference(client, ref, services=svc)
    card = read_card(client, ref)
    assert card["links"] == {"total": 34, "content": 19}
    assert card["current"]["linksSortKey"] == LINKS_SORT_KEY and LINKS_SORT_KEY in svc.store.writes
    stored = json.loads(svc.store.text(ref, LINKS_SORT_KEY))
    assert stored["pageUrl"] and len(stored["links"]) == 34
    assert len(json.dumps(card)) < 6000, "the row stays small: the links live in the attachment"


def test_a_page_with_no_links_writes_no_links_attachment():
    ref = reference()
    client = MemoryClient([ref])
    svc = services(client, pages={"https://news.example.org/r1": page(article_html())})
    curation.curate_reference(client, ref, services=svc)
    card = read_card(client, ref)
    assert "links" not in card and LINKS_SORT_KEY not in svc.store.writes
