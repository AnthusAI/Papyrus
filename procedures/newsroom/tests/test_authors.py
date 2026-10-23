"""The shared author normaliser: every accepted form, and the places that read it."""

from __future__ import annotations

import pytest

from papyrus_content.authors import Author, absolute_author_url, author_names, normalize_authors
from papyrus_content.projection.public_data import PublicDataSettings, entry_for
from papyrus_content.projection.standard.markdown import byline_markdown, item_markdown
from papyrus_content.publishing import columns_from_front_matter

OBJECTS = [{"name": "Ryan Porter", "url": "/ryan"}, {"name": "Derek Norrbom", "url": "https://www.linkedin.com/in/dereknorrbom/"}]


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, ()),
        ("", ()),
        ([], ()),
        ("Ann Lee", (Author("Ann Lee"),)),
        ("Ann Lee, Bo Reed", (Author("Ann Lee"), Author("Bo Reed"))),
        (["Ann Lee", "Bo Reed"], (Author("Ann Lee"), Author("Bo Reed"))),
        (["Ann Lee", " ", None], (Author("Ann Lee"),)),
        (OBJECTS, (Author("Ryan Porter", "/ryan"), Author("Derek Norrbom", "https://www.linkedin.com/in/dereknorrbom/"))),
        ({"name": "Ryan Porter", "url": "/ryan"}, (Author("Ryan Porter", "/ryan"),)),
        ([{"name": "Eve Stone"}, {"url": "/nameless"}, {"name": " "}], (Author("Eve Stone"),)),
        (["Ann Lee", {"name": "Bo Reed", "url": "/bo"}], (Author("Ann Lee"), Author("Bo Reed", "/bo"))),
        (["Ann Lee", {"name": "Ann Lee", "url": "/ann"}, "Ann Lee"], (Author("Ann Lee", "/ann"),)),
        ([Author("Ann Lee", "/ann")], (Author("Ann Lee", "/ann"),)),
    ],
)
def test_every_form_normalises_to_authors(raw, expected):
    assert normalize_authors(raw) == expected


def test_a_name_is_never_a_python_repr():
    assert author_names(OBJECTS) == ("Ryan Porter", "Derek Norrbom")
    assert str(Author("Ryan Porter", "/ryan")) == "Ryan Porter"


@pytest.mark.parametrize(
    "url, origin, expected",
    [
        ("", "https://a.example", ""),
        ("/ryan", "https://a.example", "https://a.example/ryan"),
        ("/ryan", "https://a.example/", "https://a.example/ryan"),
        ("/ryan", None, ""),
        ("https://x.example/y", None, "https://x.example/y"),
        ("https://x.example/y", "https://a.example", "https://x.example/y"),
    ],
)
def test_urls_become_absolute_with_the_site_origin(url, origin, expected):
    assert absolute_author_url(url, origin) == expected


def test_markdown_byline_links_only_authors_with_a_url():
    assert byline_markdown(OBJECTS + [{"name": "Eve Stone"}], "https://a.example") == (
        "[Ryan Porter](https://a.example/ryan), [Derek Norrbom](https://www.linkedin.com/in/dereknorrbom/), Eve Stone"
    )
    assert byline_markdown("Ann Lee, Bo Reed") == "Ann Lee, Bo Reed"
    assert byline_markdown(OBJECTS) == "Ryan Porter, [Derek Norrbom](https://www.linkedin.com/in/dereknorrbom/)"


def test_the_twin_accepts_raw_forms_through_the_same_normaliser():
    from types import SimpleNamespace

    for authors, line in (
        ("Ann Lee, Bo Reed", "By Ann Lee, Bo Reed · Published 2026-01-01"),
        (["Ann Lee", "Bo Reed"], "By Ann Lee, Bo Reed · Published 2026-01-01"),
        (OBJECTS, "By [Ryan Porter](https://a.example/ryan), [Derek Norrbom](https://www.linkedin.com/in/dereknorrbom/) · Published 2026-01-01"),
    ):
        entry = SimpleNamespace(title="T", authors=(), author_details=authors, date="2026-01-01", updated="", summary_text="")
        assert line in item_markdown(entry, "Body.", None, (), "https://a.example")


def test_the_editor_byline_is_names_for_every_form():
    assert columns_from_front_matter({"authors": OBJECTS})["byline"] == "Ryan Porter, Derek Norrbom"
    assert columns_from_front_matter({"authors": ["Ann Lee", "Bo Reed"]})["byline"] == "Ann Lee, Bo Reed"
    assert columns_from_front_matter({"author": "Ann Lee"})["byline"] == "Ann Lee"
    assert columns_from_front_matter({"title": "T"})["byline"] is None


@pytest.mark.parametrize(
    "front_matter, expected",
    [
        ({"authors": OBJECTS}, ("Ryan Porter", "Derek Norrbom")),
        ({"authors": ["Ann Lee", "Bo Reed"]}, ("Ann Lee", "Bo Reed")),
        ({"author": "Ann Lee, Bo Reed"}, ("Ann Lee", "Bo Reed")),
        ({}, ()),
    ],
)
def test_public_data_entries_hold_author_names(front_matter, expected):
    summary = _public_summary(front_matter)
    assert entry_for(summary, "s.html", PublicDataSettings()).authors == expected


def _public_summary(front_matter: dict):
    from types import SimpleNamespace

    return SimpleNamespace(front_matter=front_matter, page_title="T", title="T", slug="s", published_at="2026-01-01")
