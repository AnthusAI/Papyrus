"""Core follow-ups from the Chatticus and Cyclotron migrations (PPY-9cd419, PPY-2c3c69)."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from papyrus_content.projection.standard import blocks
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.fragments import with_lede
from papyrus_content.projection.standard.grouping import group_entries
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite, fixture_settings


def test_escaped_placeholder_prints_literally_and_others_still_substitute():
    text = blocks.substitute(r"Use \{{name}} for {{name}}.", {"name": "Zed"}, "x.md")
    assert text == "Use {{name}} for Zed."
    assert blocks.substitute("{{name}}", {}, "x.md") == "{{name}}"          # no values: untouched, as before
    with pytest.raises(ValueError, match="no value named"):
        blocks.substitute("{{other}}", {"name": "Zed"}, "x.md")


def test_band_that_starts_with_a_column_has_no_empty_first_column():
    html = blocks.render("::band\n::column\nOne\n::column\nTwo\n", "x.md", lambda md: f"<p>{md}</p>", None)
    assert html.count('class="markus-column"') == 2 and "<p>One</p>" in html
    kept = blocks.render("::band\nLead\n::column\nTwo\n", "x.md", lambda md: f"<p>{md}</p>", None)
    assert kept.count('class="markus-column"') == 2                             # text before the first column keeps it


class Entry:
    def __init__(self, name, data):
        self.name, self.data, self.date = name, data, "2026-01-01"


def test_group_by_front_matter_field_keeps_listing_order_and_collects_the_rest():
    entries = [Entry("a", {"category": "Ideas"}), Entry("b", {"category": "Product"}), Entry("c", {}), Entry("d", {"category": "Ideas"})]
    groups = group_entries(entries, "field:category")
    assert [(key, label, [e.name for e in found]) for key, label, found in groups] == [
        ("ideas", "Ideas", ["a", "d"]), ("product", "Product", ["b"]), ("other", "Other", ["c"]),
    ]


def test_settings_validate_the_new_options():
    base = {"site": {"name": "X"}}
    with pytest.raises(ValueError, match="groupBy"):
        standard_settings_from_mapping({**base, "urls": {"sections": {"s": {"groupBy": "field:"}}}})
    assert standard_settings_from_mapping({**base, "site": {"name": "X", "dateFormat": "%B %d, %Y", "ledeField": "standfirst"}}).identity.lede_field == "standfirst"


def test_with_lede_adds_it_once_to_the_header():
    fragment = '<article class="markus-document"><header class="markus-header"><h1>T</h1></header><p>Body</p></article>'
    assert '<h1>T</h1><p class="markus-lede">A &amp; B</p></header>' in with_lede(fragment, "A & B")
    assert with_lede(with_lede(fragment, "x"), "y").count("markus-lede") == 1 and "<p class=\"markus-lede\">y</p>" in with_lede(with_lede(fragment, "x"), "y")
    assert with_lede(fragment, "") == fragment and with_lede("<p>no header</p>", "x") == "<p>no header</p>"


@pytest.fixture()
def projected():
    content = Path(tempfile.mkdtemp(prefix="followups-content-"))
    (content / "orchids.md").write_text(
        "---\ntitle: Orchids\ndate: '2026-01-05'\ndescription: Marsh orchids.\nstandfirst: Wet ground flowers.\n"
        "original: https://example.com/orchids\ncategory: Botany\n---\nMarsh orchids flower in June.\n", encoding="utf-8")
    (content / "ferns.md").write_text("---\ntitle: Ferns\ndate: '2026-01-04'\ndescription: Ferns.\n---\nFerns unfurl.\n", encoding="utf-8")
    (content / "guide.md").write_text(
        "---\ntitle: Guide\ndate: '2026-01-01'\ntype: page\ndescription: How.\n---\nPlain guide.\n", encoding="utf-8")
    settings = {
        **fixture_settings("flat"),
        "site": {**fixture_settings("flat")["site"], "dateFormat": "%B %d, %Y", "ledeField": "standfirst"},
        "seo": {"isBasedOnField": "original", "articleTypes": ["page"]},
    }
    site = ProjectedSite("flat", settings=settings, content=content)
    yield site
    site.cleanup()
    shutil.rmtree(content, ignore_errors=True)


def test_options_reach_the_pages(projected):
    page = projected.text("orchids.html")
    assert '<p class="markus-lede">Wet ground flowers.</p>' in page
    assert '<p class="markus-byline">January 05, 2026</p>' in page and "2026-01-05" not in page.split("</header>")[0].split("<header")[1]
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
    article = ld if ld.get("@type") != "BreadcrumbList" else None
    assert article is not None and article["isBasedOn"] == "https://example.com/orchids"
    assert "isBasedOn" not in projected.text("ferns.html")
    guide = projected.text("guide.html")
    assert '<meta property="og:type" content="article">' in guide              # articleTypes: an unlisted type reports article
