"""Collections, tag-page settings, draft marking, section listing pages and the 404 settings of the standard front end."""

from __future__ import annotations

import re

import pytest

from papyrus_content.projection.standard.config import standard_settings_from_mapping
from procedures.newsroom.tests.standard_frontend_content_support import (
    cards,
    cms_site,
    featured,
    item,
    settings,
    title_of,
)

# ------------------------------------------------------------------ configuration


def parse(**extra):
    return standard_settings_from_mapping(settings(**extra))


def collection(**extra) -> dict:
    return {"id": "news", "select": {"tags": ["news"]}, **extra}


def test_a_collection_has_defaults_taken_from_its_id():
    config = parse(collections=[{"id": "case-studies", "select": {"tags": ["case-study"], "notTags": "draft, hidden"}}]).collection("case-studies")
    assert (config.base, config.label, config.sort, config.ties) == ("case-studies", "Case Studies", "date", "slug-desc")
    assert config.page_size is None and config.featured_count is None and config.drafts is False
    assert config.sitemap and not config.sitemap_pages and not config.list_empty
    assert config.select.tags == ("case-study",) and config.select.not_tags == ("draft", "hidden")   # a comma list is a list
    assert parse().collections == () and parse().collection("news") is None


def test_every_collection_setting_is_read():
    config = parse(
        collections=[
            collection(
                base="the-news", label="The News", description="Latest.", pageSize=8, featuredCount=4, sort="title", ties="slug-asc",
                drafts=True, sitemap=False, sitemapPages=True, listEmpty=True,
                select={"sections": ["posts"], "tags": ["a"], "allTags": ["b", "c"], "notTags": ["d"]},
            )
        ]
    ).collection("news")
    assert (config.base, config.label, config.description, config.page_size, config.featured_count) == ("the-news", "The News", "Latest.", 8, 4)
    assert (config.sort, config.ties, config.drafts, config.sitemap, config.sitemap_pages, config.list_empty) == ("title", "slug-asc", True, False, True, True)
    assert (config.select.sections, config.select.tags, config.select.all_tags, config.select.not_tags) == (("posts",), ("a",), ("b", "c"), ("d",))


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"collections": [collection(bogus=1)]}, "Unknown collections settings: bogus"),
        ({"collections": [collection(select={"tag": ["x"]})]}, "Unknown collections.news.select settings: tag"),
        ({"collections": [collection(select={"tags": [3]})]}, "collections.news.select.tags must be a list of names"),
        ({"collections": [collection(select={"tags": {"a": 1}})]}, "must be a list of names"),
        ({"collections": [{"select": {}}]}, "unique lowercase id"),
        ({"collections": [collection(id="News")]}, "unique lowercase id"),
        ({"collections": [collection(id="1news")]}, "unique lowercase id"),
        ({"collections": [collection(), collection(base="other")]}, "unique lowercase id"),
        ({"collections": [collection(sort="newest")]}, "sort is date, order or title"),
        ({"collections": [collection(ties="random")]}, "ties is slug-desc or slug-asc"),
        ({"collections": [collection(pageSize=0)]}, "pageSize must be positive"),
        ({"collections": [collection(featuredCount=-1)]}, "featuredCount must not be negative"),
        ({"collections": [collection(base="Bad Base")]}, "lowercase path"),
        ({"collections": [collection(base="posts")], "urls": {"sections": {"posts": {}}}}, "must be a path that no section with a listing page uses"),
        ({"collections": [collection(base="writing")], "urls": {"sections": {"posts": {"base": "writing"}}}}, "must be a path that no section with a listing page uses"),
        ({"listings": {"tagPageSize": -1}}, "tagPageSize must not be negative"),
        ({"listings": {"tagSelect": {"tag": ["x"]}}}, "Unknown listings.tagSelect settings"),
        ({"listings": {"draft": {"fields": "status"}}}, "Unknown listings.draft settings"),
        ({"listings": {"bogus": 1}}, "Unknown listings settings"),
        ({"notFound": {"heading": "x"}}, "Unknown notFound settings"),
        ({"urls": {"sections": {"posts": {"listingpage": False}}}}, "Unknown urls.sections.posts settings"),
    ],
)
def test_bad_collection_and_listing_settings_are_rejected_with_a_reason(extra, message):
    with pytest.raises(ValueError, match=message):
        parse(**extra)


def test_a_section_without_a_listing_page_leaves_its_base_to_a_collection():
    config = parse(urls={"sections": {"posts": {"listingPage": False}}}, collections=[collection(base="posts")])
    assert config.section("posts").listing and not config.section("posts").listing_page
    assert config.collection("news").base == "posts"


def test_listing_page_defaults_to_true_and_the_new_listing_settings_have_defaults():
    config = parse(urls={"sections": {"posts": {}}})
    listings = config.listings
    assert config.section("posts").listing_page is True
    assert (listings.page_suffix, listings.tag_title, listings.tag_page_size, listings.draft_field) == (" — page {page}", "Tagged {tag}", None, "")
    assert listings.draft_values == ("draft",) and listings.tag_select.tags == ()
    assert (config.not_found.title, config.not_found.description, config.not_found.noindex) == ("Page not found", "", True)


# ------------------------------------------------------------------ tag collections

SECTIONS = {"sections": {"posts": {"listingPage": False}}}
NEWS = {"id": "news", "select": {"tags": ["news"], "notTags": ["solutions"]}, "pageSize": 8, "featuredCount": 4, "drafts": True}
DRAFT_FIELD = {"field": "status", "values": ["wip", "pending"]}
SEE_DRAFTS = '''
def page_finish(html, page):
    view = page.listing
    if view is None:
        return html
    return html + "<!--drafts:" + ",".join(entry.slug for entry in view.drafts) + "|collection:" + str(view.collection) + "-->"
'''


def news_items():
    items = [item(f"n{number:02d}", date=f"2026-03-{number:02d}", tags=["NEWS" if number == 21 else "news"]) for number in range(1, 22)]
    return [
        *items,
        item("s1", date="2026-03-22", tags=["news", "solutions"]),          # excluded by notTags
        item("o1", date="2026-03-23", tags=["other"]),                      # not selected
        item("d1", date="2026-03-24", tags=["news"], draft=True),
        item("w1", date="2026-03-25", tags=["news"], status="wip"),         # a draft by listings.draft
        item("p1", date="2026-03-26", tags=["news"], status="published"),   # the same field with another value: listed
    ]


@pytest.fixture(scope="module")
def news():
    site = cms_site(
        settings(urls=SECTIONS, listings={"pageSize": 5, "draft": DRAFT_FIELD}, collections=[NEWS], hooks="hooks.py"),
        news_items(),
        {"hooks.py": SEE_DRAFTS},
    )
    yield site
    site.cleanup()


def test_a_collection_selects_by_tag_ignoring_case_and_excludes_by_not_tags(news):
    shown = cards(news.text("news/index.html")) + cards(news.text("news/page/2/index.html")) + cards(news.text("news/page/3/index.html"))
    assert "n21" in shown                       # tagged NEWS: tags compare case-insensitively
    assert "s1" not in shown                    # notTags
    assert "o1" not in shown                    # no matching tag
    assert "p1" in shown                        # a draft field with a value that is not a draft value does not hide the item
    assert sorted(shown) == sorted(["p1"] + [f"n{number:02d}" for number in range(1, 22)])
    assert len(shown) == len(set(shown))


def test_featured_four_then_pages_of_eight_newest_first(news):
    first = news.text("news/index.html")
    newest = ["p1"] + [f"n{number:02d}" for number in range(21, 0, -1)]            # 22 entries: p1 is the newest
    assert featured(first) == newest[:4]
    assert cards(first) == newest[:12]                                              # the featured four, then the first page of eight
    assert cards(news.text("news/page/2/index.html")) == newest[12:20]
    assert cards(news.text("news/page/3/index.html")) == newest[20:]
    assert "news/page/4/index.html" not in news.tree
    assert featured(news.text("news/page/2/index.html")) == []


def test_pages_two_and_up_have_their_own_keys_urls_titles_and_pager(news):
    assert {"news/index.html", "news/page/2/index.html", "news/page/3/index.html", "news/index.md", "news/page/2/index.md"} <= set(news.tree)
    assert title_of(news.text("news/index.html")) == "News · Example"
    assert title_of(news.text("news/page/2/index.html")) == "News — page 2 · Example"
    page = news.text("news/page/2/index.html")
    assert 'rel="prev" href="/news/"' in page and 'rel="next" href="/news/page/3/"' in page
    assert "Page 2 of 3" in page
    assert 'rel="canonical" href="https://example.org/news/page/2/"' in page


def test_drafts_are_served_but_never_listed_fed_mapped_or_tagged(news):
    everything = "\n".join(news.text(key) for key in news.tree if key.endswith(".html") and key.startswith(("news/", "tags/", "index")))
    for slug in ("d1", "w1"):
        assert f"/posts/{slug}.html" not in everything
        page = news.text(f"posts/{slug}.html")
        assert '<meta name="robots" content="noindex, nofollow">' in page
        for key in ("sitemap.xml", "feed.xml", "atom.xml", "llms.txt"):
            assert f"/posts/{slug}" not in news.text(key)
    assert "/posts/p1.html" in news.text("sitemap.xml")
    assert '<meta name="robots"' not in news.text("posts/p1.html")


def test_drafts_ride_on_page_one_of_a_collection_that_asks_for_them(news):
    assert news.text("news/index.html").rstrip().endswith("<!--drafts:w1,d1|collection:news-->")        # newest first
    assert news.text("news/page/2/index.html").rstrip().endswith("<!--drafts:|collection:news-->")
    assert news.text("news/page/3/index.html").rstrip().endswith("<!--drafts:|collection:news-->")
    assert news.text("tags/news/index.html").rstrip().endswith("<!--drafts:|collection:None-->")


def test_a_collection_without_drafts_true_carries_none_and_ignores_unselected_drafts():
    configured = {**NEWS, "drafts": False}
    site = cms_site(settings(urls=SECTIONS, listings={"draft": DRAFT_FIELD}, collections=[configured], hooks="hooks.py"), news_items(), {"hooks.py": SEE_DRAFTS})
    try:
        assert site.text("news/index.html").rstrip().endswith("<!--drafts:|collection:news-->")
    finally:
        site.cleanup()


def test_the_drafts_of_a_collection_are_the_drafts_its_selection_matches():
    other = [item("x1", date="2026-04-01", tags=["other"], draft=True), item("n1", date="2026-04-02", tags=["news"]), item("x2", date="2026-04-03", tags=["news", "solutions"], draft=True)]
    site = cms_site(settings(collections=[{**NEWS, "base": "n"}], hooks="hooks.py"), other, {"hooks.py": SEE_DRAFTS})
    try:
        assert site.text("n/index.html").rstrip().endswith("<!--drafts:|collection:news-->")           # neither draft matches the selection
    finally:
        site.cleanup()


def test_a_collection_page_is_in_the_sitemap_once_and_a_draft_never_is(news):
    sitemap = news.text("sitemap.xml")
    assert sitemap.count("<loc>https://example.org/news/</loc>") == 1
    assert "/news/page/" not in sitemap
    assert "/posts/d1" not in sitemap and "/posts/w1" not in sitemap
    assert "<loc>https://example.org/news/</loc><lastmod>2026-03-26</lastmod>" in sitemap


@pytest.mark.parametrize(
    "extra, present, absent",
    [
        ({"sitemapPages": True}, ["/news/", "/news/page/2/", "/news/page/3/"], []),
        ({"sitemap": False}, [], ["/news/"]),
        ({"sitemap": False, "sitemapPages": True}, [], ["/news/", "/news/page/2/"]),
    ],
)
def test_collection_sitemap_settings(extra, present, absent):
    site = cms_site(settings(urls=SECTIONS, collections=[{**NEWS, **extra}]), news_items())
    try:
        sitemap = site.text("sitemap.xml")
        for path in present:
            assert f"<loc>https://example.org{path}</loc>" in sitemap
        for path in absent:
            assert f"<loc>https://example.org{path}</loc>" not in sitemap
    finally:
        site.cleanup()


def test_an_empty_collection_has_no_page_unless_list_empty():
    items = [item("a", tags=["x"])]
    for list_empty in (False, True):
        site = cms_site(settings(collections=[collection(listEmpty=list_empty)]), items)
        try:
            assert ("news/index.html" in site.tree) is list_empty
            assert ("<loc>https://example.org/news/</loc>" in site.text("sitemap.xml")) is list_empty
            if list_empty:
                assert cards(site.text("news/index.html")) == []
        finally:
            site.cleanup()


def test_collection_description_label_and_default_page_size():
    items = [item(f"a{number}", date=f"2026-01-0{number}", tags=["news"]) for number in range(1, 8)]
    site = cms_site(settings(listings={"pageSize": 3}, collections=[collection(label="Dispatches", description="What we reported.")]), items)
    try:
        first = site.text("news/index.html")
        assert title_of(first) == "Dispatches · Example"
        assert '<meta name="description" content="What we reported.">' in first
        assert [len(cards(site.text(key))) for key in ("news/index.html", "news/page/2/index.html", "news/page/3/index.html")] == [3, 3, 1]    # the site's pageSize
    finally:
        site.cleanup()


def test_a_collection_selects_by_section_and_all_tags():
    items = [
        item("a", section="posts", tags=["x", "y"]), item("b", section="notes", tags=["x", "y"]), item("c", section="posts", tags=["x"]),
        item("d", section=None, tags=["x", "y"]),
    ]
    sections = {"sections": {"posts": {}, "notes": {}}}
    cases = {
        "posts-only": ({"sections": ["posts"]}, ["c", "a"]),
        "both-tags": ({"allTags": ["x", "y"]}, ["d", "b", "a"]),
        "root": ({"sections": ["@root"]}, ["d"]),
        "posts-and-notes": ({"sections": ["posts", "notes"], "tags": ["y"]}, ["b", "a"]),
        "no-notes": ({"tags": ["x"], "notTags": ["y"]}, ["c"]),
    }
    configured = [{"id": name, "select": select} for name, (select, _) in cases.items()]
    site = cms_site(settings(urls=sections, collections=configured), [(p, {**f, "date": f"2026-01-0{i}"}, b) for i, (p, f, b) in enumerate(items, 1)])
    try:
        for name, (_select, expected) in cases.items():
            assert cards(site.text(f"{name}/index.html")) == expected, name
    finally:
        site.cleanup()


# ------------------------------------------------------------------ order

def tie_items():
    return [item(slug, date="2026-04-01", tags=["tie"], title=title, order=order) for slug, title, order in (("b", "Zebra", 2), ("a", "mango", 3), ("c", "Apple", 1)) ] + [
        item("older", date="2026-03-01", tags=["tie"], title="Older", order=9)
    ]


@pytest.mark.parametrize(
    "extra, expected",
    [
        ({}, ["c", "b", "a", "older"]),                                 # slug-desc is the default
        ({"ties": "slug-desc"}, ["c", "b", "a", "older"]),
        ({"ties": "slug-asc"}, ["a", "b", "c", "older"]),               # the date still decides first
        ({"sort": "order"}, ["c", "b", "a", "older"]),                  # front matter order 1, 2, 3, 9
        ({"sort": "title"}, ["c", "a", "older", "b"]),                  # Apple, mango, Older, Zebra: case-insensitive
    ],
)
def test_collection_sort_and_ties(extra, expected):
    site = cms_site(settings(collections=[{"id": "tie", "select": {"tags": ["tie"]}, **extra}]), tie_items())
    try:
        page = site.text("tie/index.html")
        assert cards(page) == expected
    finally:
        site.cleanup()


# ------------------------------------------------------------------ tag pages

def tagged_items():
    return [
        item("a", section="posts", date="2026-01-01", tags=["red", "Blue"]),
        item("b", section="posts", date="2026-01-02", tags=["red"]),
        item("c", section="notes", date="2026-01-03", tags=["red", "blue"]),
        item("d", section="posts", date="2026-01-04", tags=["red", "hidden"]),
        item("e", section="posts", date="2026-01-05", tags=["red"]),
        item("f", section="posts", date="2026-01-06", tags=["red"]),
    ]


TAG_SECTIONS = {"sections": {"posts": {"listingPage": False}, "notes": {}}}


def test_tag_select_narrows_the_tag_pages_and_the_tag_index_but_not_the_listings():
    select = {"sections": ["posts"], "notTags": ["hidden"]}
    site = cms_site(settings(urls=TAG_SECTIONS, listings={"tagSelect": select}), tagged_items())
    try:
        assert cards(site.text("tags/red/index.html")) == ["f", "e", "b", "a"]        # c is in notes, d is tagged hidden
        assert "tags/hidden/index.html" not in site.tree                               # d is the only entry of that tag and it is excluded
        index = site.text("tags/index.html")
        assert ">red</a> (4)" in index and ">Blue</a> (1)" in index
        assert "hidden" not in index
        sitemap = site.text("sitemap.xml")
        assert "/tags/red/" in sitemap and "/tags/hidden/" not in sitemap
        assert cards(site.text("notes/index.html")) == ["c"]                            # section listings are not narrowed
    finally:
        site.cleanup()


def test_tag_page_size_zero_puts_every_entry_of_a_tag_on_one_page():
    items = [item(f"e{number:02d}", date=f"2026-02-{number:02d}", tags=["many"]) for number in range(1, 24)]
    site = cms_site(settings(urls={"sections": {"posts": {}}}, listings={"pageSize": 5, "featuredCount": 2, "tagPageSize": 0}), items)
    try:
        page = site.text("tags/many/index.html")
        assert len(cards(page)) == 23 and featured(page) == []
        assert "tags/many/page/2/index.html" not in site.tree and "markus-pager" not in page
        assert len(cards(site.text("posts/index.html"))) == 5 + 2                       # listings keep pageSize and featuredCount
    finally:
        site.cleanup()


def test_tag_page_size_sets_the_size_of_tag_pages_without_featured_entries():
    items = [item(f"e{number:02d}", date=f"2026-02-{number:02d}", tags=["many"]) for number in range(1, 8)]
    site = cms_site(settings(urls={"sections": {"posts": {}}}, listings={"pageSize": 5, "featuredCount": 2, "tagPageSize": 3}), items)
    try:
        sizes = [len(cards(site.text(key))) for key in ("tags/many/index.html", "tags/many/page/2/index.html", "tags/many/page/3/index.html")]
        assert sizes == [3, 3, 1] and featured(site.text("tags/many/index.html")) == []
    finally:
        site.cleanup()


def test_tag_title_and_page_suffix_come_from_the_settings():
    items = [item(f"e{number}", date=f"2026-02-0{number}", tags=["Many Words"]) for number in range(1, 6)]
    custom = {"pageSize": 2, "tagTitle": "All about {tag}", "pageSuffix": " (p{page})"}
    site = cms_site(settings(urls={"sections": {"posts": {}}}, listings=custom), items)
    try:
        first, second = site.text("tags/many-words/index.html"), site.text("tags/many-words/page/2/index.html")
        assert title_of(first) == "All about Many Words · Example" and "<h1>All about Many Words</h1>" in first
        assert title_of(second) == "All about Many Words (p2) · Example"
        assert title_of(site.text("posts/index.html")) == "Posts · Example"
        assert title_of(site.text("posts/page/3/index.html")) == "Posts (p3) · Example"
    finally:
        site.cleanup()


def test_the_default_titles_are_tagged_and_page():
    items = [item(f"e{number}", date=f"2026-02-0{number}", tags=["red"]) for number in range(1, 5)]
    site = cms_site(settings(urls={"sections": {"posts": {}}}, listings={"pageSize": 3}), items)
    try:
        assert title_of(site.text("tags/red/index.html")) == "Tagged red · Example"
        assert title_of(site.text("tags/red/page/2/index.html")) == "Tagged red — page 2 · Example"
    finally:
        site.cleanup()


def test_the_draft_field_marks_items_draft_with_its_own_values():
    items = [item("live", tags=["x"], status="published"), item("held", tags=["x"], status="Pending"), item("plain", tags=["x"]), item("flag", tags=["x"], draft=True)]
    for configured, hidden in (
        ({"field": "status", "values": ["pending"]}, {"held", "flag"}),            # values compare case-insensitively
        ({"field": "status"}, {"flag"}),                                            # the default value is "draft"
        (None, {"flag"}),
    ):
        site = cms_site(settings(urls={"sections": {"posts": {}}}, listings={"draft": configured} if configured else {}), items)
        try:
            shown = set(cards(site.text("posts/index.html")))
            assert shown == {"live", "held", "plain", "flag"} - hidden
            for slug in hidden:
                assert '<meta name="robots" content="noindex, nofollow">' in site.text(f"posts/{slug}.html")
        finally:
            site.cleanup()


# ------------------------------------------------------------------ section listing pages

def test_a_section_without_a_listing_page_is_still_listed_everywhere_else():
    items = [item("a", section="posts", date="2026-01-01", tags=["t"]), item("b", section="notes", date="2026-01-02", tags=["t"])]
    site = cms_site(settings(urls=TAG_SECTIONS, collections=[{"id": "all", "select": {"sections": ["posts"]}}]), items)
    try:
        assert "posts/index.html" not in site.tree and "notes/index.html" in site.tree
        assert "posts/a.html" in site.tree
        assert "<loc>https://example.org/posts/</loc>" not in site.text("sitemap.xml") and "<loc>https://example.org/notes/</loc>" in site.text("sitemap.xml")
        assert cards(site.text("tags/t/index.html")) == ["b", "a"]
        assert "/posts/a.html" in site.text("feed.xml")
        assert 'href="/posts/"' not in site.text("posts/a.html") and 'href="/posts/"' not in site.text("index.html")
        assert cards(site.text("all/index.html")) == ["a"]
        assert "/posts/" not in site.text("llms.txt").replace("/posts/a", "")
    finally:
        site.cleanup()


def test_the_breadcrumb_of_an_item_skips_a_section_without_a_listing_page():
    items = [item("a", section="posts", date="2026-01-01"), item("b", section="notes", date="2026-01-02")]
    site = cms_site(settings(urls=TAG_SECTIONS, components={"breadcrumbs": True}), items)
    try:
        assert 'href="/notes/"' in site.text("notes/b.html") and 'href="/posts/"' not in site.text("posts/a.html")
    finally:
        site.cleanup()


def test_the_generated_home_page_does_not_link_to_a_listing_that_does_not_exist():
    site = cms_site(settings(urls=SECTIONS), [item("a", date="2026-01-01")])
    try:
        assert "archive/index.html" not in site.tree
        assert 'href="/archive/"' not in site.text("index.html")
    finally:
        site.cleanup()


def test_two_collections_cannot_share_a_base():
    with pytest.raises(ValueError):
        parse(collections=[collection(id="a", base="x"), collection(id="b", base="x")])


def test_a_collection_cannot_take_the_tag_index_path():
    with pytest.raises(ValueError):
        parse(collections=[collection(base="tags")])


# ------------------------------------------------------------------ the 404 page

def test_the_not_found_page_is_noindex_with_the_site_description_by_default():
    site = cms_site(settings(), [item("a")])
    try:
        page = site.text("404.html")
        assert title_of(page) == "Page not found · Example"
        assert '<meta name="robots" content="noindex, nofollow">' in page
        assert '<meta name="description" content="An example.">' in page
    finally:
        site.cleanup()


def test_not_found_settings_reach_the_404_head():
    custom = {"title": "Nothing here", "description": "Try the archive.", "noindex": False}
    site = cms_site(settings(notFound=custom), [item("a")])
    try:
        page = site.text("404.html")
        assert title_of(page) == "Nothing here · Example"
        assert '<meta name="description" content="Try the archive.">' in page
        assert re.search(r'<meta name="robots" content="[^"]*noindex', page) is None
        assert "Nothing here" in page.split("</head>")[0]
    finally:
        site.cleanup()


def test_not_found_title_and_description_alone_keep_noindex():
    site = cms_site(settings(notFound={"title": "Lost"}), [item("a")])
    try:
        page = site.text("404.html")
        assert title_of(page) == "Lost · Example" and '<meta name="robots" content="noindex, nofollow">' in page
        assert '<meta name="description" content="An example.">' in page          # empty description: the site's
    finally:
        site.cleanup()


def test_a_collection_selection_reads_story_types():
    config = parse(collections=[collection(select={"types": "article, guide", "notTypes": ["post"]})]).collection("news")
    assert config.select.types == ("article", "guide") and config.select.not_types == ("post",)
    with pytest.raises(ValueError, match="Unknown collections.news.select settings: type"):
        parse(collections=[collection(select={"type": ["x"]})])
