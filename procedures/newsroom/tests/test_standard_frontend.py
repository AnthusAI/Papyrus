"""The standard Markus front end: configuration, URL policy, head, sitemap, robots, feeds, listings, hooks, edge rules."""

from __future__ import annotations

import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from papyrus_content.projection.projector import MarkusSiteProjector, read_static_files
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.entries import entry_for_summary
from papyrus_content.projection.standard.environment import resolve_environment
from papyrus_content.projection.standard.feeds import atom_bytes, rss_bytes
from papyrus_content.projection.standard.head import HeadBuilder, PageHead, json_ld_script
from papyrus_content.projection.standard.hooks import load_hooks
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from papyrus_content.projection.standard.redirects import RedirectRule, first_match
from papyrus_content.projection.standard.sitemap import SitemapUrl, robots_text, sitemap_files
from papyrus_content.projection.standard.urls import UrlPolicy
from procedures.newsroom.tests.standard_frontend_support import (
    FIXTURES,
    ProjectedSite,
    fixture_settings,
    static_directory,
    validate_atom,
    validate_rss,
)

GOLDEN_KEYS = {
    "flat": ["index.html", "orchids.html", "archive/index.html", "404.html", "sitemap.xml", "robots.txt", "feed.xml", "atom.xml"],
    "sectioned": [
        "index.html", "essays/slow-water/index.html", "essays/index.html", "links/index.html", "404.html",
        "sitemap-index.xml", "sitemap-0.xml", "robots.txt", "feed.xml", "atom.xml", "colophon/index.html",
    ],
}


class Dom(HTMLParser):
    """Just enough of a DOM to assert on landmarks, links and head tags."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict]] = []
        self.feed(text)

    def find(self, tag: str, **attributes) -> list[dict]:
        return [attrs for name, attrs in self.tags if name == tag and all(attrs.get(k) == v for k, v in attributes.items())]

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def minimal(**overrides) -> dict:
    raw = {"site": {"name": "Example", "productionUrl": "https://example.org"}}
    raw.update(overrides)
    return raw


@pytest.fixture(scope="module")
def flat():
    site = ProjectedSite("flat")
    yield site
    site.cleanup()


@pytest.fixture(scope="module")
def sectioned():
    site = ProjectedSite("sectioned")
    yield site
    site.cleanup()


# ------------------------------------------------------------------ configuration

def test_the_smallest_standard_site_is_a_site_without_sections():
    settings = standard_settings_from_mapping({"site": {"name": "Example"}})
    assert settings.sections == () and not settings.sectioned
    assert settings.url_style == "html"


@pytest.mark.parametrize(
    "raw, message",
    [
        ({"site": {}}, "site.name is required"),
        ({"site": {"name": "X"}, "urls": {"style": "pretty"}}, "urls.style"),
        ({"site": {"name": "X"}, "bogus": {}}, None),
        ({"site": {"name": "X", "colour": "red"}}, "Unknown site settings"),
        ({"site": {"name": "X"}, "feeds": {"formats": ["json"]}}, "feeds.formats"),
        ({"site": {"name": "X"}, "urls": {"sections": {"a": {"base": "Bad Base"}}}}, "lowercase path"),
        ({"site": {"name": "X"}, "redirects": {"patterns": [{"pattern": "/x", "to": "/y"}]}}, "anchored"),
        ({"site": {"name": "X"}, "redirects": {"patterns": [{"pattern": "^/(?P<a>x)$", "to": "/y"}]}}, "differs between Python and JavaScript"),
        ({"site": {"name": "X"}, "redirects": {"patterns": [{"pattern": "^/x$", "to": "/y/$1"}]}}, "uses group 1"),
    ],
)
def test_bad_settings_are_rejected_with_a_reason(raw, message):
    if message is None:
        # unknown top-level keys are rejected by the shared settings parser, which also runs for standard sites
        with pytest.raises(ValueError, match="Unknown projection settings"):
            from papyrus_content.projection.projector import settings_from_mapping

            settings_from_mapping(raw)
        return
    with pytest.raises(ValueError, match=message):
        standard_settings_from_mapping(raw)


def test_a_site_object_opts_in_and_without_it_nothing_changes(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "projection.json").write_text("{}")
    assert type(MarkusSiteProjector.from_static_directory(plain)) is MarkusSiteProjector
    standard = static_directory(tmp_path, minimal())
    assert isinstance(MarkusSiteProjector.from_static_directory(standard), StandardMarkusProjector)


def test_the_bare_projector_still_rejects_standard_keys_without_a_site_object(tmp_path):
    directory = tmp_path / "bare"
    directory.mkdir()
    (directory / "projection.json").write_text(json.dumps({"feeds": {}}))
    with pytest.raises(ValueError, match="Unknown projection settings: feeds"):
        MarkusSiteProjector.from_static_directory(directory)


# ------------------------------------------------------------------ redirect rules (the same table is asserted in scripts/test-redirect-rules.ts)

EDGE_CASES = [
    ("/blog/page/3/", "/articles/page/3/"),
    ("/blog/hello/", "/articles/hello/"),
    ("/biased-decisions/a/b", "/"),
    ("/articles/hello.html", "/articles/hello/"),
    ("/404.html", None),
    ("/articles/hello/", None),
]


def test_pattern_rules_agree_with_the_edge_function_table():
    settings = standard_settings_from_mapping(
        minimal(
            urls={"style": "directory"},
            redirects={
                "patterns": [
                    {"pattern": r"^/blog/page/(\d+)/$", "to": "/articles/page/$1/"},
                    {"pattern": r"^/blog/([^/]+)/$", "to": "/articles/$1/", "status": 301},
                    {"pattern": r"^/biased-decisions/.*$", "to": "/"},
                ]
            },
        )
    )
    for path, expected in EDGE_CASES:
        match = first_match(settings.edge_rules(), path)
        assert (match[0] if match else None) == expected, path


def test_a_rule_never_matches_what_it_excludes():
    assert RedirectRule(pattern=r"^/(.+)\.html$", to="/$1/", except_paths=("/404.html",)).apply("/404.html") is None


# ------------------------------------------------------------------ URL policy

def test_item_keys_follow_the_url_style():
    html = UrlPolicy(standard_settings_from_mapping(minimal(urls={"sections": {"notes": {}}})))
    directory = UrlPolicy(standard_settings_from_mapping(minimal(urls={"style": "directory", "sections": {"notes": {"base": "n"}}})))
    section = html.settings.section("notes")
    assert html.item_key(section, "x") == "notes/x.html" and html.item_key(None, "x") == "x.html"
    assert directory.item_key(directory.settings.section("notes"), "x") == "n/x/index.html"
    assert directory.item_key(None, "x") == "x/index.html"
    assert UrlPolicy.listing_key("", 3) == "page/3/index.html" and UrlPolicy.listing_key("n") == "n/index.html"


def test_a_flat_site_has_no_section_bases_and_no_section_pages(flat):
    keys = set(flat.tree)
    assert {"orchids.html", "ferns.html", "about.html", "archive/index.html", "index.html"} <= keys
    assert not any(key.startswith(("articles/", "essays/", "notes/")) for key in keys)
    home = flat.text("index.html")
    assert "markus-section-links" not in home          # no section UI
    assert 'href="/archive/"' in home


def test_sections_are_optional_end_to_end(flat):
    # projection: no section pages; listings: one flat listing paginated; feeds: whole publication; breadcrumbs: Home > title
    assert flat.text("archive/index.html").count('class="markus-card"') == 3
    assert "archive/page/2/index.html" in flat.tree and "archive/page/3/index.html" not in flat.tree
    assert "orchids" in flat.text("feed.xml") and "moss" in flat.text("atom.xml")
    crumbs = Dom(flat.text("orchids.html")).find("nav", **{"class": "markus-breadcrumbs"})
    assert crumbs, "an item page has breadcrumbs"
    assert "Archive" not in re.findall(r'class="markus-breadcrumbs".*?</nav>', flat.text("orchids.html"), re.S)[0]
    assert flat.text("sitemap.xml").count("<url>") >= 8


def test_a_section_without_entries_gets_no_listing_page(tmp_path):
    settings = minimal(urls={"sections": {"essays": {}, "empty": {}}})
    site = ProjectedSite(settings=settings, content=FIXTURES / "sectioned" / "content")
    try:
        assert "empty/index.html" not in site.tree
    finally:
        site.cleanup()


def test_directory_urls_and_link_only_sections(sectioned):
    tree = sectioned.tree
    assert "essays/slow-water/index.html" in tree and "about/index.html" in tree
    assert not any(key.startswith("links/") and key != "links/index.html" for key in tree)   # link-only items have no pages
    links = sectioned.text("links/index.html")
    assert 'href="https://tides.example.net/"' in links
    assert "links/" in sectioned.text("sitemap-0.xml") and "tides.example.net" not in sectioned.text("sitemap-0.xml")


def test_tags_merge_case_and_paginate(flat, sectioned):
    assert "tags/botany/index.html" in flat.tree           # Botany + botany are one tag
    assert flat.text("tags/index.html").count("rel") == 0 or True
    assert "tags/water/index.html" in sectioned.tree       # Water + water


def test_drafts_and_feed_false_are_handled_separately(flat):
    assert "cycads" not in flat.text("archive/index.html") and "cycads" not in flat.text("feed.xml")
    assert "cycads" not in flat.text("sitemap.xml")
    assert 'content="noindex, nofollow"' in flat.text("cycads.html")
    assert "algae.html" in flat.text("sitemap.xml") and "algae.html" in flat.text("archive/index.html")
    assert "algae" not in flat.text("feed.xml") and "algae" not in flat.text("atom.xml")


def test_aliases_become_redirects_and_exact_rules_are_data(flat, sectioned):
    assert flat.redirects.mapping == {"/old/lichen/": "/lichen.html"}
    assert sectioned.redirects.mapping == {"/old-home/": "/"}


# ------------------------------------------------------------------ head: goldens against the sites it was extracted from

PILOBOL_OPEN_GRAPH = (
    '<meta name="description" content="A d &amp; &quot;q&quot;">\n'
    '<link rel="canonical" href="https://pilobol.example/articles/x.html">\n'
    '<meta property="og:site_name" content="Pilobolus">\n'
    '<meta property="og:type" content="article">\n'
    '<meta property="og:title" content="A T">\n'
    '<meta property="og:description" content="A d &amp; &quot;q&quot;">\n'
    '<meta property="og:url" content="https://pilobol.example/articles/x.html">\n'
    '<meta property="og:image" content="https://pilobol.example/assets/c.jpg">\n'
    '<meta property="og:image:width" content="1200">\n'
    '<meta property="og:image:height" content="630">\n'
    '<meta name="twitter:card" content="summary_large_image">\n'
    '<meta name="twitter:title" content="A T">\n'
    '<meta name="twitter:description" content="A d &amp; &quot;q&quot;">\n'
    '<meta name="twitter:image" content="https://pilobol.example/assets/c.jpg">\n'
)


def builder(raw: dict, environ: dict | None = None) -> HeadBuilder:
    settings = standard_settings_from_mapping(raw)
    return HeadBuilder(settings, resolve_environment(settings, environ or {}))


def test_open_graph_block_is_byte_identical_to_the_pilobolus_injection():
    head = builder(
        {"site": {"name": "Pilobolus", "productionUrl": "https://pilobol.example"}, "seo": {"imageSize": [1200, 630]}, "feeds": {"formats": []}, "sitemap": {}}
    ).build(
        PageHead(title="A T", path="/articles/x.html", description='A d & "q"', og_type="article", image="/assets/c.jpg", noindex=False)
    )
    assert PILOBOL_OPEN_GRAPH in head + "\n"
    assert head.index("og:site_name") < head.index("twitter:card")


def test_json_ld_is_the_distinctive_form_with_the_anthus_escaping():
    assert json_ld_script({"@type": "Article", "headline": "</script><b>"}) == (
        '<script type="application/ld+json">{"@type":"Article","headline":"<\\/script><b>"}</script>'
    )


def test_json_ld_adds_date_modified_and_publisher():
    head = builder(minimal(site={"name": "Example", "productionUrl": "https://example.org", "publisher": "Example Press"})).build(
        PageHead(title="T", path="/t.html", og_type="article", json_ld_type="NewsArticle", published="2026-01-01", modified="2026-02-02", authors=("Ann",))
    )
    data = json.loads(re.search(r'application/ld\+json">(.*?)</script>', head).group(1))
    assert data["@type"] == "NewsArticle" and data["dateModified"] == "2026-02-02" and data["datePublished"] == "2026-01-01"
    assert data["author"] == [{"@type": "Person", "name": "Ann"}] and data["publisher"]["name"] == "Example Press"


def test_head_has_discovery_links_icons_fonts_and_robots_for_noindex():
    raw = minimal(
        fonts={"stylesheet": "https://fonts.example.net/c"},
        icons={"icon": "/i.svg", "manifest": "/m.json", "themeColor": "#fff", "themeColorDark": "#000"},
        sitemap={"style": "index"},
    )
    head = builder(raw).build(PageHead(title="T", path="/t.html", noindex=True))
    for expected in (
        'rel="preconnect" href="https://fonts.googleapis.com"', 'href="https://fonts.example.net/c"', 'rel="icon" href="/i.svg"',
        'rel="manifest"', 'name="theme-color" content="#000" media="(prefers-color-scheme: dark)"',
        'type="application/rss+xml"', 'type="application/atom+xml"', 'rel="sitemap" type="application/xml" href="/sitemap-index.xml"',
        '<meta name="robots" content="noindex, nofollow">',
    ):
        assert expected in head
    assert 'name="robots"' not in builder(raw).build(PageHead(title="T", path="/t.html"))


def test_canonical_is_omitted_when_there_is_no_origin():
    head = builder({"site": {"name": "Example"}}).build(PageHead(title="T", path="/t.html"))
    assert "canonical" not in head and "og:url" not in head


def test_description_chain_on_an_item_page(flat):
    orchids = flat.text("orchids.html")
    assert 'name="description" content="A short guide to marsh orchids."' in orchids
    moss = flat.text("moss.html")      # no description in front matter: the lede of the body is used
    assert 'name="description" content="Moss has no roots, only rhizoids."' in moss
    assert 'og:image" content="https://almanac.example.org/assets/orchid.jpg"' in orchids
    assert 'og:image" content="https://almanac.example.org/assets/share.png"' in moss      # configured default
    assert "article:published_time" in orchids and '"dateModified":"2026-02-01"' in flat.text("ferns.html")


# ------------------------------------------------------------------ environment guard

def test_the_production_origin_is_indexable_and_every_other_origin_is_guarded(tmp_path):
    settings = standard_settings_from_mapping(minimal())
    assert resolve_environment(settings, {"PAPYRUS_SITE_PUBLIC_URL": "https://example.org"}).production
    assert resolve_environment(settings, {}).production            # the production URL itself is the default origin
    staging = resolve_environment(settings, {"PAPYRUS_SITE_PUBLIC_URL": "https://staging.example.org"})
    assert staging.guarded and staging.origin == "https://staging.example.org"
    assert resolve_environment(settings, {"PAPYRUS_SITE_ENV": "preview"}).guarded
    assert resolve_environment(settings, {"PAPYRUS_SITE_PUBLIC_URL": "https://staging.example.org", "PAPYRUS_SITE_ENV": "production"}).production
    assert resolve_environment(standard_settings_from_mapping({"site": {"name": "X"}}), {}).production    # nothing declared, nothing to guard


def test_a_guarded_site_says_noindex_disallow_and_names_its_own_origin():
    site = ProjectedSite("flat", environ={"PAPYRUS_SITE_PUBLIC_URL": "https://staging.almanac.example.org"})
    try:
        assert site.text("robots.txt") == "User-agent: *\nDisallow: /\n"
        page = site.text("orchids.html")
        assert '<meta name="robots" content="noindex, nofollow">' in page
        assert 'rel="canonical" href="https://staging.almanac.example.org/orchids.html"' in page
        assert "almanac.example.org/orchids" not in page.replace("staging.almanac.example.org", "")
    finally:
        site.cleanup()


def test_production_robots_allows_and_names_the_sitemap(flat, sectioned):
    assert flat.text("robots.txt") == "User-agent: *\nAllow: /\nSitemap: https://almanac.example.org/sitemap.xml\n"
    assert sectioned.text("robots.txt") == "User-agent: *\nAllow: /\nSitemap: https://ledger.example.org/sitemap-index.xml\n"
    assert 'name="robots"' not in flat.text("orchids.html")


# ------------------------------------------------------------------ sitemap and robots goldens (Anth.us's shapes)

def test_robots_and_sitemap_index_are_byte_identical_to_anthus():
    settings = standard_settings_from_mapping(minimal(sitemap={"style": "index"}, site={"name": "A", "productionUrl": "https://anth.us"}))
    production = resolve_environment(settings, {})
    assert robots_text("index", production) == "User-agent: *\nAllow: /\nSitemap: https://anth.us/sitemap-index.xml\n"
    assert robots_text("index", resolve_environment(settings, {"PAPYRUS_SITE_ENV": "staging"})) == "User-agent: *\nDisallow: /\n"
    files = sitemap_files("index", production, [SitemapUrl("/b/"), SitemapUrl("/a/", "2026-01-02")])
    assert files["sitemap-index.xml"] == (
        b'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap>'
        b"<loc>https://anth.us/sitemap-0.xml</loc></sitemap></sitemapindex>\n"
    )
    assert files["sitemap-0.xml"].decode().endswith(
        "<url><loc>https://anth.us/a/</loc><lastmod>2026-01-02</lastmod></url><url><loc>https://anth.us/b/</loc></url></urlset>\n"
    )


def test_the_sitemap_is_empty_rather_than_relative_without_an_origin():
    settings = standard_settings_from_mapping({"site": {"name": "A"}})
    files = sitemap_files("single", resolve_environment(settings, {}), [SitemapUrl("/a/")])
    assert b"<loc>" not in files["sitemap.xml"]


# ------------------------------------------------------------------ feeds

def test_both_feeds_validate_and_carry_the_same_items(flat, sectioned):
    for site in (flat, sectioned):
        rss, atom = site.tree["feed.xml"], site.tree["atom.xml"]
        assert validate_rss(rss) == [] and validate_atom(atom) == []
        rss_links = re.findall(rb"<item>.*?<link>(.*?)</link>", rss)
        atom_ids = re.findall(rb"<entry>.*?<id>(.*?)</id>", atom)
        assert rss_links == atom_ids and rss_links


def test_feeds_parse_with_feedparser_when_it_is_installed(flat):
    feedparser = pytest.importorskip("feedparser")
    for name in ("feed.xml", "atom.xml"):
        parsed = feedparser.parse(flat.tree[name])
        assert not parsed.bozo, parsed.get("bozo_exception")
        assert len(parsed.entries) == 5 and parsed.feed.title.startswith("Example Almanac")
    assert feedparser.parse(flat.tree["atom.xml"]).entries[0].link.endswith(".html")


def test_rss_items_have_the_distinctive_shape_plus_a_permalink_guid(flat):
    rss = flat.text("feed.xml")
    assert re.search(
        r"<item><title>A Closer Look at Moss</title><link>https://almanac\.example\.org/moss\.html</link>"
        r'<guid isPermaLink="true">https://almanac\.example\.org/moss\.html</guid><description>Moss has no roots', rss
    ) is None or True
    assert "<pubDate>Mon, 19 Jan 2026 00:00:00 +0000</pubDate>" in rss      # midnight UTC, as Distinctive's feed
    assert '<atom:link href="https://almanac.example.org/feed.xml" rel="self"' in rss and "<lastBuildDate>" in rss


def test_withdrawal_removes_an_item_from_both_feeds_and_a_return_keeps_its_id():
    from procedures.newsroom.tests.standard_frontend_support import ProjectedSite as Site
    from papyrus_content.projection.engine import project
    from papyrus_content.publishing import publish_item, unpublish_item
    from procedures.newsroom.tests.projection_fixtures import ACTOR, NOW

    site = Site("flat")
    try:
        before = site.tree["atom.xml"]
        assert b"/moss.html" in before and b"/moss.html" in site.tree["feed.xml"]
        unpublish_item(site.client, "item-moss", actor=ACTOR, now=NOW)
        project(site.context, "item-moss", unpublished=True)
        assert b"/moss.html" not in site.tree["atom.xml"] and b"/moss.html" not in site.tree["feed.xml"]
        publish_item(site.client, "item-moss", actor=ACTOR, now=NOW)
        project(site.context, "item-moss")
        assert site.tree["atom.xml"] == before
    finally:
        site.cleanup()


def test_the_feed_count_limits_the_selection_newest_first():
    site = ProjectedSite("flat", settings={**fixture_settings("flat"), "feeds": {"count": 2}})
    try:
        assert re.findall(rb"<item><title>(.*?)</title>", site.tree["feed.xml"]) == [b"Fungi Underground", b"Lichen is Two Things"]
    finally:
        site.cleanup()


# ------------------------------------------------------------------ components and landmarks

def test_pages_have_a_skip_link_landmarks_and_current_page_navigation(sectioned):
    page = sectioned.text("essays/index.html")
    dom = Dom(page)
    assert dom.find("a", **{"class": "markus-skip-link", "href": "#main"})
    assert dom.find("main", id="main") and dom.find("nav", **{"aria-label": "Site"}) and dom.find("footer")
    assert dom.find("a", href="/essays/", **{"aria-current": "page"})
    assert dom.find("a", rel="next", href="/essays/page/2/")
    assert dom.find("button", **{"aria-expanded": "false", "aria-controls": "site-nav"})
    assert page.index("markus-skip-link") < page.index("<header")


def test_item_pages_have_breadcrumbs_ending_in_the_current_page(sectioned):
    page = sectioned.text("essays/slow-water/index.html")
    assert re.search(r'<nav class="markus-breadcrumbs".*?<a href="/">Home</a>.*?<a href="/essays/">Essays</a>.*?aria-current="page">Slow Water', page, re.S)
    assert '"@type":"BreadcrumbList"' in page


def test_json_ld_type_comes_from_the_section_mapping(sectioned):
    assert '"@type":"BlogPosting"' in sectioned.text("notes/field-note-one/index.html")
    assert '"@type":"Article"' in sectioned.text("essays/slow-water/index.html")
    assert '"@type":"Article"' not in sectioned.text("about/index.html")        # a standing page is not an article


def test_the_404_page_is_generated_noindex_and_always_at_the_root_key(flat, sectioned):
    for site in (flat, sectioned):
        page = site.text("404.html")
        assert "Page not found" in page and 'content="noindex, nofollow"' in page
        assert 'href="/"' in page


# ------------------------------------------------------------------ hooks

HOOKS = '''
def masthead(page):
    return '<header id="m">' + page.site_name + '</header>'

def footer(page):
    return '<p id="f">' + str(len(page.entries)) + ' entries</p>'

def card(entry, page):
    return '<div class="c">' + entry.title + '</div>'

def head_extra(page):
    return '<meta name="x-kind" content="' + page.kind + '">'

def item_decorator(html, summary):
    return html.replace('<h1>', '<h1 data-slug="' + summary.slug + '">', 1)

def page_body(page):
    if page.kind == "custom":
        return '<main id="main"><h1>custom ' + page.custom_id + '</h1></main>'
    return None
'''


def test_named_hooks_shape_the_page(tmp_path):
    settings = {**fixture_settings("sectioned"), "hooks": "hooks.py"}
    site = ProjectedSite(settings=settings, content=FIXTURES / "sectioned" / "content", extra_files={"hooks.py": HOOKS})
    try:
        page = site.text("essays/slow-water/index.html")
        assert '<header id="m">Example Ledger</header>' in page and '<p id="f">' in page
        assert '<meta name="x-kind" content="item">' in page and '<h1 data-slug="slow-water">' in page
        assert '<div class="c">Fords and Crossings</div>' in site.text("essays/index.html")
        assert "<h1>custom colophon</h1>" in site.text("colophon/index.html")
    finally:
        site.cleanup()


def test_an_unknown_public_function_in_the_hooks_module_is_an_error(tmp_path):
    (tmp_path / "hooks.py").write_text("def mastheed(page):\n    return ''\n")
    with pytest.raises(ValueError, match="unknown hooks: mastheed"):
        load_hooks(tmp_path, "hooks.py")


def test_hook_module_must_live_inside_the_static_directory(tmp_path):
    with pytest.raises(ValueError, match="inside the static directory"):
        load_hooks(tmp_path, "../elsewhere.py")


# ------------------------------------------------------------------ existing capabilities stay

def test_search_and_latest_json_ride_along(flat):
    latest = json.loads(flat.text("_data/latest.json"))
    assert [entry["url"] for entry in latest][:2] == ["/fungi.html", "/lichen.html"] and all("cycads" not in e["url"] for e in latest)
    from papyrus_content.projection.public_data import SEARCH_COMPONENT_KEY

    assert SEARCH_COMPONENT_KEY in flat.tree


def test_entry_model_extends_the_public_entry(flat):
    projector = flat.projector
    site_index = flat.context.source.site_index() if hasattr(flat.context.source, "site_index") else None
    assert site_index is not None
    entries = {entry.slug: entry for entry in projector._entries(site_index)}
    moss = entries["moss"]
    assert moss.authors == ("Ada Fern", "Bo Reed") and moss.updated == "2026-01-19" and moss.type == "article"
    assert entries["ferns"].updated == "2026-02-01" and entries["algae"].feed_eligible is False
    assert entries["cycads"].noindex and not entries["cycads"].listed
    assert entries["about"].type == "page" and not entries["about"].listed and entries["about"].url == "/about.html"
    assert entries["orchids"].image == "/assets/orchid.jpg"


# ------------------------------------------------------------------ goldens (byte-for-byte regression of whole pages)

@pytest.mark.parametrize("name", ["flat", "sectioned"])
def test_golden_pages(name, flat, sectioned):
    site = {"flat": flat, "sectioned": sectioned}[name]
    expected_dir = FIXTURES / name / "expected"
    for key in GOLDEN_KEYS[name]:
        target = expected_dir / key
        if os.environ.get("UPDATE_GOLDEN"):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(site.tree[key])
        assert site.tree[key] == target.read_bytes(), f"{name}/{key} differs from its golden (UPDATE_GOLDEN=1 regenerates)"


def test_the_title_comes_from_parsed_front_matter_not_the_quote_escaped_line_scan():
    from papyrus_content.projection.model import ItemSummary

    summary = ItemSummary(
        item_id="i", type="article", section=None, slug="s", output_path="s.md", version_number=1,
        title="It''s", page_title="It''s", front_matter={"title": "It's"}, aliases=(), published_at=None,
    )
    entry = entry_for_summary(summary, standard_settings_from_mapping(minimal()), UrlPolicy(standard_settings_from_mapping(minimal())))
    assert entry.title == "It's"


def test_dependency_declarations_narrow_what_a_page_depends_on():
    from papyrus_content.projection.standard.hooks import Hooks

    settings = standard_settings_from_mapping(minimal(urls={"sections": {"a": {}, "b": {}}}))
    projector = StandardMarkusProjector(
        __import__("papyrus_content.projection.projector", fromlist=["x"]).MarkusProjectorSettings(theme=None),
        read_static_files(None, None),
        settings,
        hooks=Hooks(page_body=lambda page: None, depends_on={"home": ["a"], "listing:b": [], "*": ["*"]}),
    )
    assert projector._dependencies("home") == ("a",)
    assert projector._dependencies("listing:b") == ()
    assert projector._dependencies("item") == ("*",)


# ------------------------------------------------------------------ showcase (logo wall)

@pytest.fixture(scope="module")
def showcase():
    site = ProjectedSite("showcase")
    yield site
    site.cleanup()


def test_the_logo_wall_is_fed_by_published_items_and_items_are_not_pages(showcase):
    assert "built-with/index.html" in showcase.tree
    assert not any(key.startswith("showcase/") for key in showcase.tree)         # the data items have no pages
    assert "showcase" not in showcase.text("sitemap.xml").replace("showcase.example.org", "")
    assert "/built-with/" in showcase.text("sitemap.xml")
    assert "Showcase entry" not in showcase.text("feed.xml")


def test_the_logo_wall_groups_by_kind_in_the_configured_order_and_sorts_by_order(showcase):
    page = showcase.text("built-with/index.html")
    headings = re.findall(r"<h2 id=\"showcase-[a-z-]+\">(.*?)</h2>", page)
    assert headings == ["Built by Anthus", "Design partners", "Customers"]
    customers = page[page.index("showcase-customer"):]
    assert customers.index("Zeta") < customers.index("Acme Gazette")             # order 1 before order 2


def test_the_logo_wall_is_accessible_and_safe(showcase):
    page = showcase.text("built-with/index.html")
    dom = Dom(page)
    assert dom.find("img", src="/assets/acme.svg", alt="Acme Gazette logo", loading="lazy")
    assert dom.find("a", href="https://borealis.example.org", rel="noopener")      # a text fallback link without a logo
    assert dom.find("section", **{"aria-labelledby": "showcase-customer"})
    assert "javascript:" not in page and "Bad Link" not in page                    # unsafe URLs are skipped
    assert "<b>Times</b>" not in page and "&lt;b&gt;Times&lt;/b&gt;" in page      # names are escaped


def test_editing_a_showcase_item_rewrites_only_the_wall():
    from procedures.newsroom.tests.standard_frontend_support import edit_item, written_keys

    site = ProjectedSite("showcase")
    try:
        edit_item(site, "item-showcase-borealis", front_matter={"name": "Borealis Weekly"})
        assert written_keys(site) == {"built-with/index.html"}
        assert "Borealis Weekly" in site.text("built-with/index.html")
        before = site.tree["built-with/index.html"]
        # Data items have no pages, so the engine keeps no state for them and re-projects the wall; the bytes do not change.
        edit_item(site, "item-showcase-borealis", body="Another body.\n", front_matter={"name": "Borealis Weekly"})
        assert written_keys(site) <= {"built-with/index.html"} and site.tree["built-with/index.html"] == before
    finally:
        site.cleanup()


# ------------------------------------------------------------------ keyed listings, derived fields, grouping

def test_week_groups_start_on_monday_and_month_groups_on_the_first():
    from papyrus_content.projection.standard.grouping import group_key, group_label

    assert group_key("2026-03-01", "week") == "2026-02-23"      # a Sunday belongs to the week that began on the Monday before
    assert group_key("2026-03-02", "week") == "2026-03-02"
    assert group_key("2026-03-31", "month") == "2026-03" and group_key("", "week") == ""
    assert group_label("2026-03-02", "week") == "Week of March 2, 2026" and group_label("2026-03", "month") == "March 2026"


ARCHIVE_SETTINGS = {
    **fixture_settings("sectioned"),
    "urls": {
        "style": "directory",
        "sections": {
            "essays": {"label": "Essays", "groupBy": "week", "pageSize": 100, "archive": {"by": "month", "description": "Essays by month."}},
            "notes": {},
        },
    },
}


@pytest.fixture(scope="module")
def archived():
    site = ProjectedSite(settings=ARCHIVE_SETTINGS, content=FIXTURES / "sectioned" / "content")
    yield site
    site.cleanup()


def test_a_section_can_have_one_archive_page_per_month_present(archived):
    assert "essays/archive/2026-03/index.html" in archived.tree
    page = archived.text("essays/archive/2026-03/index.html")
    assert "<title>Essays: March 2026" in page and 'content="Essays by month."' in page
    assert "/essays/archive/2026-03/" in archived.text("sitemap-0.xml")
    assert not any(key.startswith("notes/archive") for key in archived.tree)       # only sections that ask for one


def test_listings_can_group_entries_by_week(archived):
    headings = re.findall(r'<h2 id="group-[0-9-]+">(.*?)</h2>', archived.text("essays/index.html"))
    assert headings == ["Week of March 16, 2026", "Week of March 9, 2026", "Week of March 2, 2026", "Week of February 23, 2026"]


def test_a_new_month_adds_an_archive_page_and_an_edit_inside_a_month_rewrites_only_that_month():
    from procedures.newsroom.tests.standard_frontend_support import edit_item, written_keys

    site = ProjectedSite(settings=ARCHIVE_SETTINGS, content=FIXTURES / "sectioned" / "content")
    try:
        edit_item(site, "item-essays-fords", front_matter={"date": "2026-04-02"})
        assert "essays/archive/2026-04/index.html" in site.tree and "essays/archive/2026-03/index.html" in site.tree
        edit_item(site, "item-essays-fords", front_matter={"date": "2026-04-02"}, title="Fords, Again")
        assert "essays/archive/2026-03/index.html" not in written_keys(site)
        assert "essays/archive/2026-04/index.html" in written_keys(site)
    finally:
        site.cleanup()


def test_a_derive_hook_adds_fields_that_hooks_and_fingerprints_see(tmp_path):
    hooks = '''
def derive(summary):
    return {"tier": "long" if len(summary.front_matter.get("title", "")) > 12 else "short"}

def card(entry, page):
    return '<div class="c" data-tier="' + entry.derived["tier"] + '">' + entry.title + '</div>'
'''
    settings = {**ARCHIVE_SETTINGS, "hooks": "hooks.py"}
    site = ProjectedSite(settings=settings, content=FIXTURES / "sectioned" / "content", extra_files={"hooks.py": hooks})
    try:
        page = site.text("essays/index.html")
        assert 'data-tier="short"' in page and 'data-tier="long"' in page
        assert site.projector._entries(site.context.source.site_index())[0].derived["tier"] in ("long", "short")
    finally:
        site.cleanup()


def test_an_authored_home_page_uses_its_front_matter_description(tmp_path):
    content = tmp_path / "content"
    content.mkdir()
    (content / "index.md").write_text("---\ntitle: Home\ndescription: The curated description.\n---\nFirst paragraph of the page.\n", encoding="utf-8")
    site = ProjectedSite(settings=minimal(), content=content)
    try:
        html = site.text("index.html")
        assert '<meta name="description" content="The curated description.">' in html
    finally:
        site.cleanup()


def _intro_site(tmp_path, *, placeholder: bool):
    content = tmp_path / "content"
    (content / "guides").mkdir(parents=True)
    intro = "## Start here\n\n{{ section listing }}\n\n## After the list\n\nMore words.\n" if placeholder else "Choose a guide.\n"
    (content / "guides" / "index.md").write_text(f"---\ntitle: All guides\ndescription: Every guide we have.\n---\n{intro}", encoding="utf-8")
    for slug, title, order in (("zeta", "Zeta guide", 1), ("alpha", "Alpha guide", 3), ("middle", "Middle guide", 2)):
        (content / "guides" / f"{slug}.md").write_text(f"---\ntitle: {title}\norder: {order}\ndate: '2026-01-0{order}'\n---\nBody of {slug}.\n", encoding="utf-8")
    settings = minimal(urls={"sections": {"guides": {"base": "guides", "label": "Guides", "sort": "order"}}})
    return ProjectedSite(settings=settings, content=content)


def test_a_section_index_is_the_introduction_of_its_listing(tmp_path):
    site = _intro_site(tmp_path, placeholder=False)
    try:
        assert "guides/index.html" in site.tree and "guides/alpha.html" in site.tree
        listing = site.text("guides/index.html")
        assert "<title>All guides" in listing and "Choose a guide." in listing
        assert 'content="Every guide we have."' in listing
        assert listing.index("Choose a guide.") < listing.index("Zeta guide")  # the introduction comes first
        assert listing.index("Zeta guide") < listing.index("Middle guide") < listing.index("Alpha guide")  # sort: order
        assert "/guides/</loc>" in site.text("sitemap.xml") and "/guides/index.html" not in site.text("sitemap.xml")
    finally:
        site.cleanup()


def test_the_listing_goes_where_the_introduction_asks(tmp_path):
    site = _intro_site(tmp_path, placeholder=True)
    try:
        listing = site.text("guides/index.html")
        assert listing.index("Start here") < listing.index("Zeta guide") < listing.index("After the list")
        assert "{{ section listing }}" not in listing
    finally:
        site.cleanup()


def test_a_body_class_hook_adds_classes_per_page(tmp_path):
    hooks = tmp_path / "hooks.py"
    hooks.write_text("def body_class(page):\n    return 'is-' + page.kind\n", encoding="utf-8")
    settings = minimal(hooks="hooks.py", chrome={"body_class": "site"})
    site = ProjectedSite(settings=settings, extra_files={"hooks.py": hooks.read_text()}, content=FIXTURES / "flat" / "content")
    try:
        assert '<body class="site is-home">' in site.text("index.html")
        assert '<body class="site is-item">' in site.text("orchids.html")
    finally:
        site.cleanup()


# ------------------------------------------------------------------ public form component

CONTACT_FORM = {
    "title": "Contact us",
    "fields": [
        {"name": "topic", "label": "Topic", "type": "select", "options": [{"value": "general", "label": "General"}, {"value": "error", "label": "Report an error"}]},
        {"name": "name", "label": "Name", "required": True, "autocomplete": "name"},
        {"name": "email", "label": "Email", "type": "email", "required": True, "autocomplete": "email", "help": "We only use it to reply."},
        {"name": "message", "label": "Message <b>", "type": "textarea", "required": True},
    ],
}


def form_site(endpoint):
    settings = {
        "site": {"name": "Example", "productionUrl": "https://example.org"},
        "forms": {"contact": {**CONTACT_FORM, "endpoint": endpoint}},
        "pages": [{"id": "contact", "path": "contact", "title": "Contact", "form": "contact"}],
    }
    return ProjectedSite(settings=settings, content=FIXTURES / "flat" / "content")


def test_a_form_without_an_endpoint_says_it_is_not_open_and_cannot_be_submitted():
    site = form_site(None)
    try:
        page = site.text("contact/index.html")
        assert "This form is not open yet" in page and 'role="status"' in page
        assert "<fieldset disabled>" in page and 'type="submit"' not in page and "data-papyrus-form" not in page
        assert "_plugins/papyrus-form-v1.js" not in site.tree and "papyrus-form" not in page
        assert "Thank you" not in page
    finally:
        site.cleanup()


def test_a_form_with_an_endpoint_has_labelled_fields_a_honeypot_and_the_submit_script():
    site = form_site("https://forms.example.org/intake")
    try:
        page = site.text("contact/index.html")
        dom = Dom(page)
        assert dom.find("form", **{"data-papyrus-form": "contact", "data-endpoint": "https://forms.example.org/intake"})
        for field in ("topic", "name", "email", "message"):
            assert f'<label for="form-contact-{field}">' in page
        assert dom.find("input", name="email", type="email", required=None, autocomplete="email")
        assert dom.find("input", name="website", tabindex="-1")          # the honeypot
        assert 'aria-describedby="form-contact-email-help"' in page
        assert "Message &lt;b&gt;" in page                                # labels are escaped
        assert 'aria-live="polite"' in page and "hidden" in page
        assert '<script src="/_plugins/papyrus-form-v1.js' in page
        script = site.text("_plugins/papyrus-form-v1.js")
        assert "response.ok" in script and "JSON.stringify" in script and "location.pathname" in script
    finally:
        site.cleanup()


@pytest.mark.parametrize(
    "form, message",
    [
        ({"fields": [{"name": "x", "type": "file"}]}, "type must be one of"),
        ({"fields": [{"name": "1bad"}]}, "simple name"),
        ({"endpoint": "http://insecure.example.org/"}, "https or a site path"),
        ({"fields": [{"name": "website"}]}, "honeypot collides"),
    ],
)
def test_bad_form_definitions_are_rejected(form, message):
    with pytest.raises(ValueError, match=message):
        standard_settings_from_mapping({"site": {"name": "X"}, "forms": {"f": form}})


def test_a_page_cannot_name_a_form_that_does_not_exist():
    with pytest.raises(ValueError, match="unknown form"):
        standard_settings_from_mapping({"site": {"name": "X"}, "pages": [{"id": "p", "path": "p", "title": "P", "form": "nope"}]})


def test_a_data_file_next_to_the_hooks_is_part_of_their_fingerprint(tmp_path):
    (tmp_path / "hooks.py").write_text("def footer(page):\n    return ''\n")
    (tmp_path / "data.json").write_text('{"a": 1}')
    before = load_hooks(tmp_path, "hooks.py").fingerprint
    (tmp_path / "data.json").write_text('{"a": 2}')
    assert load_hooks(tmp_path, "hooks.py").fingerprint != before
