"""A Story's type and its section are two attributes; a site keys its URLs on either (``urls.types`` / ``urls.sections``)."""

from __future__ import annotations

import json
import re

import pytest

from papyrus_content.projection.standard.config import standard_settings_from_mapping
from procedures.newsroom.tests.standard_frontend_content_support import cards, cms_site, item, settings

TYPES = {"types": {"article": {"base": "articles", "label": "Articles"}}}
SITE = {"style": "directory"}


def parse(**urls):
    return standard_settings_from_mapping(settings(urls={**SITE, **urls}))


def project(urls: dict, items, **extra):
    site = cms_site(settings(urls={**SITE, **urls}, listings={"types": ["article", "post"]}, **extra), items)
    return site


def pages_of(site) -> set[str]:
    return {key for key in site.tree if key.endswith(".html")}


# ------------------------------------------------------------------ configuration


def test_a_type_group_has_the_settings_of_a_section_and_a_name_that_cannot_be_a_section():
    config = parse(types={"article": {"base": "articles", "label": "Articles", "feed": False, "listingPage": False, "pageSize": 5}})
    (group,) = config.sections
    assert (group.name, group.item_type, group.is_type, group.base, group.label) == ("type:article", "article", True, "articles", "Articles")
    assert (group.feed, group.listing_page, group.page_size) == (False, False, 5)
    assert group.where == "urls.types.article"


def test_a_type_group_defaults_its_base_and_label_from_the_type():
    (group,) = parse(types={"wiki_page": {}}).sections
    assert (group.base, group.label) == ("wiki_page", "Wiki Page")


def test_type_groups_come_before_sections_in_every_list_of_groups():
    config = parse(sections={"platform": {}}, types={"article": {"base": "articles"}})
    assert [group.name for group in config.sections] == ["type:article", "platform"]


def test_an_old_configuration_has_no_type_groups():
    config = parse(sections={"articles": {"base": "articles"}})
    assert [(group.name, group.is_type) for group in config.sections] == [("articles", False)]
    assert config.type_group("article") is None


@pytest.mark.parametrize(
    "urls, message",
    [
        ({"types": {"article": {"bogus": 1}}}, "Unknown urls.types.article settings: bogus"),
        ({"types": {"article": {"aliases": ["x"]}}}, "Unknown urls.types.article settings: aliases"),
        ({"sections": {"aws": {"aliases": "AWS"}}}, "urls.sections.aws.aliases must be a list"),
        ({"sections": {"aws": {"aliases": ["AWS"]}, "azure": {"aliases": ["AWS"]}}}, "'AWS' names both 'aws' and 'azure'"),
        ({"sections": {"aws": {"aliases": ["azure"]}, "azure": {}}}, "'azure' names both 'aws' and 'azure'"),
        ({"types": {"article": {"base": "articles"}}, "sections": {"essays": {"base": "articles"}}}, "urls.types.article.base 'articles' is already the base of 'essays'"),
        ({"types": {"article": {"sort": "random"}}}, "urls.types.article.sort must be 'date' or 'order'"),
    ],
)
def test_bad_group_settings_are_refused_naming_where(urls, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        parse(**urls)


def test_a_section_answers_to_its_aliases_but_a_type_group_is_found_by_type():
    config = parse(sections={"aws": {"base": "aws", "aliases": ["AWS"]}}, types={"article": {"base": "articles"}})
    assert config.section("AWS").name == "aws" and config.section("aws").name == "aws" and config.section("azure") is None
    assert config.group_for("AWS", "article").name == "aws"                 # a declared section wins over the type
    assert config.group_for("agent-security", "article").name == "type:article"
    assert config.group_for(None, "article").name == "type:article"
    assert config.group_for(None, "page") is None and config.group_for("agent-security", "page") is None


# ------------------------------------------------------------------ projection


def story(slug, section="agent-security", **front):
    front.setdefault("date", "2026-03-01")
    return item(slug, section=section, **front)


def test_an_article_in_a_topic_section_publishes_at_the_type_base():
    site = project(TYPES, [story("a-first"), story("a-second", section=None, date="2026-03-02"), story("a-third", section="unsectioned", date="2026-03-03")])
    try:
        assert {"articles/a-first/index.html", "articles/a-second/index.html", "articles/a-third/index.html"} <= pages_of(site)
        assert not any(key.startswith("agent-security/") for key in site.tree)
        sitemap = site.text("sitemap-0.xml") if "sitemap-0.xml" in site.tree else site.text("sitemap.xml")
        assert all(f"/articles/{slug}/" in sitemap for slug in ("a-first", "a-second", "a-third"))
        assert "<link>" in site.text("feed.xml") and all(f"/articles/{slug}/" in site.text("feed.xml") for slug in ("a-first", "a-second", "a-third"))
    finally:
        site.cleanup()


def test_the_type_listing_collects_every_article_whatever_its_section():
    site = project(
        {"types": {"article": {"base": "articles", "label": "Articles"}}},
        [story("a-first"), story("a-second", section="agent-engineering", date="2026-03-02"), story("a-third", section=None, date="2026-03-03")],
    )
    try:
        assert cards(site.text("articles/index.html")) == ["a-third", "a-second", "a-first"]
    finally:
        site.cleanup()


def test_a_section_can_still_be_a_topic_listing_through_a_collection():
    site = cms_site(
        settings(
            urls={**SITE, **TYPES}, listings={"types": ["article"]},
            collections=[{"id": "security", "select": {"sections": ["agent-security"]}}, {"id": "every-article", "select": {"types": ["article"]}}],
        ),
        [story("a-first"), story("a-second", section="agent-engineering", date="2026-03-02"), story("a-third", section=None, date="2026-03-03")],
    )
    try:
        assert cards(site.text("security/index.html")) == ["a-first"]
        assert cards(site.text("every-article/index.html")) == ["a-third", "a-second", "a-first"]
    finally:
        site.cleanup()


def test_a_post_is_a_story_type_of_its_own_and_can_have_its_own_base():
    site = project(
        {"types": {"article": {"base": "articles"}, "post": {"base": "posts", "label": "Posts"}}},
        [story("an-article"), story("a-post", type="post", date="2026-03-02")],
    )
    try:
        assert {"articles/an-article/index.html", "posts/a-post/index.html"} <= pages_of(site)
        assert cards(site.text("posts/index.html")) == ["a-post"]
    finally:
        site.cleanup()


def test_the_same_url_with_the_old_section_key_and_with_the_new_type_key():
    """An article stored with section 'articles' publishes at the same address under either configuration."""
    old = project({"sections": {"articles": {"base": "articles", "label": "Articles"}}}, [story("a-first", section="articles"), story("a-second", section="articles", date="2026-03-02")])
    new = project(TYPES, [story("a-first", section="articles"), story("a-second", section=None, date="2026-03-02")])
    try:
        assert sorted(old.tree) == sorted(new.tree)
        assert old.text("sitemap-0.xml" if "sitemap-0.xml" in old.tree else "sitemap.xml") == new.text("sitemap-0.xml" if "sitemap-0.xml" in new.tree else "sitemap.xml")
        assert cards(old.text("articles/index.html")) == cards(new.text("articles/index.html"))
    finally:
        old.cleanup()
        new.cleanup()


def test_a_declared_section_wins_over_the_type_and_an_undeclared_section_of_an_undeclared_type_is_still_ignored():
    site = project(
        {"types": {"article": {"base": "articles"}}, "sections": {"rulings": {"base": "rulings"}}},
        [story("a-ruling", section="rulings"), story("an-article"), item("a-page", section="elsewhere", type="page")],
    )
    try:
        keys = pages_of(site)
        assert "rulings/a-ruling/index.html" in keys and "articles/an-article/index.html" in keys
        assert not any("a-page" in key for key in keys)
    finally:
        site.cleanup()


def test_a_stored_title_is_read_as_the_section_it_is_an_alias_of():
    site = project(
        {"sections": {"aws": {"base": "aws", "label": "AWS", "aliases": ["AWS"]}}},
        [story("by-title", section="AWS"), story("by-id", section="aws", date="2026-03-02")],
    )
    try:
        assert {"aws/by-title/index.html", "aws/by-id/index.html"} <= pages_of(site)
        assert cards(site.text("aws/index.html")) == ["by-id", "by-title"]
    finally:
        site.cleanup()


def test_only_types_in_the_tag_selection_narrows_the_tag_pages():
    site = cms_site(
        settings(urls={**SITE, **TYPES, "sections": {"platform": {"base": "platform"}}}, listings={"types": ["article", "page"], "tagSelect": {"types": ["article"]}}),
        [story("an-article", tags=["alpha"]), item("a-page", section="platform", type="page", tags=["beta"])],
    )
    try:
        assert "tags/alpha/index.html" in site.tree and "tags/beta/index.html" not in site.tree
    finally:
        site.cleanup()


def test_the_topic_is_what_selections_dependencies_and_json_ld_read():
    site = cms_site(
        settings(urls={**SITE, **TYPES}, listings={"types": ["article"]}, seo={"jsonLdTypes": {"agent-security": "NewsArticle"}}),
        [story("topical"), story("untopical", section=None, date="2026-03-02")],
    )
    try:
        assert '"NewsArticle"' in site.text("articles/topical/index.html")
        assert '"NewsArticle"' not in site.text("articles/untopical/index.html")
    finally:
        site.cleanup()


def test_a_type_group_can_be_a_feed_and_sitemap_of_its_own():
    site = project({"types": {"article": {"base": "articles", "feed": False, "sitemap": False}}}, [story("quiet")])
    try:
        assert "articles/quiet/index.html" in pages_of(site)
        assert "/articles/quiet/" not in site.text("feed.xml")
        assert not any("/articles/quiet/" in site.text(key) for key in site.tree if key.startswith("sitemap"))
    finally:
        site.cleanup()


def test_a_site_without_urls_types_projects_exactly_as_before():
    items = [item("one", section="essays"), item("two", section="essays", date="2026-03-02"), item("root-page", section=None, type="page")]
    urls = {"sections": {"essays": {"base": "essays"}}}
    first = project(urls, items)
    second = project({**urls, "types": {}}, items)
    try:
        assert first.tree == second.tree
    finally:
        first.cleanup()
        second.cleanup()
