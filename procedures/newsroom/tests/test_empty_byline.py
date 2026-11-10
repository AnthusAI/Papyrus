"""A site hook's empty byline means 'this item has no byline' (a post): neither the page byline nor the Markdown twin falls back to the authors."""

from __future__ import annotations

from types import SimpleNamespace

from papyrus_content.authors import Author

from papyrus_content.projection.standard import components
from papyrus_content.projection.standard.markdown import item_markdown

AUTHOR = Author("Ryan Porter")


def entry():
    return SimpleNamespace(
        title="A post", author_details=(AUTHOR,), date="2026-11-09", updated=None, key="posts/a-post", link=None, summary_text="A summary.",
    )


def twin(byline):
    return item_markdown(entry(), "Words of the post.\n", None, (), None, byline)


def test_with_no_hook_the_twin_and_the_page_show_the_authors():
    assert "By Ryan Porter" in twin(None)
    assert "Ryan Porter" in components.byline(entry(), "", None)


def test_a_hook_byline_replaces_the_authors():
    assert "By various bots and Ryan Porter" in twin("By various bots and Ryan Porter")
    assert "By various bots and Ryan Porter" in components.byline(entry(), "", "By various bots and Ryan Porter")


def test_an_empty_hook_byline_means_no_byline_and_the_authors_are_not_a_fallback():
    markdown = twin("")
    assert "By Ryan Porter" not in markdown and "Ryan Porter" not in markdown
    assert "Published 2026-11-09" in markdown
    page = components.byline(entry(), "", "")
    assert "Ryan Porter" not in page and "markus-byline-authors" not in page
