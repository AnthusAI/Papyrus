"""Every Markdown-serving path emits the Markus source as written (PPY-b2e95d).

One test per path of the audit table in docs/agent-readable-sites.md. The directives are the ones that a plain-Markdown
conversion would lose: an ``::image{...}`` line with all its attributes, and the page blocks (``::band``, ``::column``,
``::button``, ``::island`` with its ``summary``). The image pipeline needs renditions the fixtures do not have, so the
image checks run on the twin builders; the page-block checks run through a whole projection.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from papyrus_content.projection.standard.config import PageActionSettings
from papyrus_content.projection.standard.markdown import home_markdown, item_markdown, listing_markdown, llms_full_txt
from papyrus_content.projection.standard.page_actions import render_page_actions
from procedures.newsroom.tests.standard_frontend_content_support import DirectorySite, item, settings

IMAGE = '::image{src="images/wide.png" alt="A wide chart" layout="full" caption="Wide"}'
BLOCKS = (
    '::band{id="top" tone="card"}\n# Decision models\n\nA model *decides*.\n\n'
    '::button{href="/start/" label="Start" size="lg"}\n\n'
    '::column{panel="card"}\n'
    '::island{name="Chart" height="20rem" kind="bar" summary="A bar chart of accuracy by model: 2B leads."}\n'
)
ASSERTED_BLOCKS = (
    '::band{id="top" tone="card"}',
    '::button{href="/start/" label="Start" size="lg"}',
    '::column{panel="card"}',
    'summary="A bar chart of accuracy by model: 2B leads."',
)
ENTRY = SimpleNamespace(title="Wide", authors=("Ada",), date="2026-10-01", updated="", summary_text="A summary.")


@pytest.fixture(scope="module")
def projected():
    """A site with a home and an authored page written as page blocks, and an article, projected from a directory."""
    site = DirectorySite(
        settings(islands={"script": "assets/islands.js"}, pages=[{"id": "models", "path": "topics/models", "title": "Models", "description": "How.", "source": "pages/models.md"}]),
        [item("index", section=None, body=BLOCKS, title="Home"), item("hello", date="2026-10-01", tags=["a"], title="Hello")],
        {"assets/islands.js": "window.papyrusIslands = {};\n", "pages/models.md": BLOCKS},
    )
    report = site.project_all()
    assert report.ok, report.errors
    yield site
    site.cleanup()


def has_blocks(text: str) -> None:
    for line in ASSERTED_BLOCKS:
        assert line in text, f"{line!r} missing from:\n{text}"


# 1. Standard front end .md twins: items, authored pages, listings, tags, home.

def test_item_twin_keeps_the_image_directive_and_drops_only_the_front_matter():
    source = f"---\ntitle: Wide\n---\nWords.\n\n{IMAGE}\n"
    twin = item_markdown(ENTRY, source, "https://example.org/wide.html")
    assert IMAGE in twin and "![A wide chart]" not in twin and "title: Wide" not in twin


def test_authored_page_twin_keeps_its_page_blocks(projected):
    has_blocks(projected.text("topics/models/index.md"))


def test_home_twin_keeps_the_page_blocks_without_a_second_title(projected):
    twin = projected.text("index.md")
    has_blocks(twin)
    assert twin.count("# Decision models") == 1 and "# Home" not in twin


def test_home_twin_adds_the_title_only_when_the_source_has_none():
    assert home_markdown("Home", "About.", "---\ntitle: Home\n---\nWords.\n") == "# Home\n\n> About.\n\nWords.\n"
    twin = home_markdown("Home", "", f"Words.\n\n{IMAGE}\n")
    assert IMAGE in twin and twin.startswith("# Home\n")


def test_listing_and_tag_twins_are_link_lists_to_the_markus_twins(projected):
    for key in ("archive/index.md", "tags/a/index.md", "tags/index.md"):
        text = projected.text(key)
        assert "https://example.org/" in text and ".md" in text, text
        assert "<" not in text   # no HTML, no stripped body


def test_listing_twin_lines_link_to_the_twin_not_the_html():
    entry = SimpleNamespace(key="hello.html", title="Hello", summary_text="", date="", link="")
    assert "(https://example.org/hello.md)" in listing_markdown("Archive", "", [entry], "https://example.org")


# 2. Accept: text/markdown negotiation is a URI rewrite to the same twin object: scripts/test-redirect-rules.ts.


# 3. llms.txt (links) and llms-full.txt (bodies).

def test_llms_txt_links_to_the_twins(projected):
    llms = projected.text("llms.txt")
    assert "(https://example.org/topics/models/index.md)" in llms and "(https://example.org/hello.md)" in llms


def test_llms_full_carries_page_blocks_as_written(projected):
    has_blocks(projected.text("llms-full.txt"))


def test_llms_full_carries_the_image_directive():
    identity = SimpleNamespace(name="Example")
    document = item_markdown(ENTRY, f"---\ntitle: Wide\n---\n{IMAGE}\n", None)
    assert IMAGE in llms_full_txt(identity, [document], 100_000)


# 4. Page actions: Copy and View take the twin; the AI links hand over the page URL only (the copy script is in scripts/test-page-actions.ts).

def test_page_actions_point_at_the_twin_and_ai_links_carry_only_the_page_url(projected):
    page = projected.text("topics/models/index.html")
    assert 'data-markdown="/topics/models/index.md"' in page and 'data-action="view" href="/topics/models/index.md"' in page


def test_ai_prompt_targets_never_carry_the_page_body():
    settings_ = PageActionSettings(ai=("chatgpt", "claude", "perplexity"))
    html = render_page_actions(settings_, markdown_path="/a.md", title="A", canonical="https://example.org/a.html")
    for href in re.findall(r'data-action="(?:chatgpt|claude|perplexity)" href="([^"]+)"', html):
        prompt = next(iter(parse_qs(urlparse(href.replace("&amp;", "&")).query).values()))[0]
        assert "https://example.org/a.html" in prompt and "::" not in prompt and len(prompt) < 200


# 5. Feeds: RSS and Atom carry the plain-text summary of the front matter, never Markdown or Markus.

def test_feeds_carry_only_the_front_matter_summary(projected):
    for key in ("feed.xml", "atom.xml"):
        text = projected.text(key)
        assert "::" not in text and "<content" not in text and "content:encoded" not in text
