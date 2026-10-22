"""A newsletter issue is an ordinary Item of the list's ``issueType``; the standard front end archives it from settings alone.

The newsletter plugin files an issue under the section named by the list's ``archivePath`` (``/roundup/`` is the section
``roundup``). Nothing in the projector knows about newsletters: the site declares that section and lists the issue type.
"""

from __future__ import annotations

from procedures.newsroom.tests.standard_frontend_content_support import cards, cms_site, item, settings

SITE_SETTINGS = settings(
    urls={
        "style": "directory",
        "sections": {
            "posts": {"base": "posts", "label": "Posts"},
            "roundup": {"base": "roundup", "label": "Roundup", "description": "Every weekly issue.", "feed": False},
        },
    },
    listings={"types": ["article", "newsletter_issue"]},
)
ITEMS = [
    item("first-post", section="posts"),
    item("2026-10-16", section="roundup", type="newsletter_issue", title="Weekly roundup: Oct 9 to Oct 16, 2026", date="2026-10-16"),
]


def test_an_issue_gets_a_page_a_markdown_twin_a_listing_and_an_llms_entry():
    site = cms_site(SITE_SETTINGS, ITEMS)
    try:
        keys = set(site.tree)
        assert "roundup/2026-10-16/index.html" in keys
        assert "roundup/2026-10-16/index.md" in keys or "roundup/2026-10-16.md" in keys
        assert "roundup/index.html" in keys, "the archive page"
        assert cards(site.text("roundup/index.html")) == ["2026-10-16"]
        assert "roundup/2026-10-16/" in site.text("llms.txt")
        assert "/roundup/2026-10-16/" in site.text("sitemap.xml")
        assert "2026-10-16" not in site.text("feed.xml"), "the section's feed switch keeps issues out of the site feed"
    finally:
        site.cleanup()


def test_a_site_that_does_not_list_the_issue_type_projects_nothing_for_it():
    site = cms_site({**SITE_SETTINGS, "listings": {"types": ["article"]}}, ITEMS)
    try:
        assert not [key for key in site.tree if key.startswith("roundup/")], "unlisted types stay unprojected, as before"
        assert "posts/first-post/index.html" in site.tree
    finally:
        site.cleanup()
