"""The Markdown twin of a page that is a template says what the page shows (PPY-0db38f).

An authored page, the home page and a section front page are written with page directives (``::band``, ``::include``).
The twin of such a page carries the page's content: includes become Markdown lists of titles and links, and no directive
reaches a reader or an agent. An article twin is unchanged (``test_markus_everywhere.py``).
"""

from __future__ import annotations

import json
import re

import pytest

from papyrus_content.projection.engine import project_stale_listings
from papyrus_content.projection.standard import page_twin
from procedures.newsroom.tests.reader_privacy import scan_files
from procedures.newsroom.tests.standard_frontend_content_support import DirectorySite, cms_site, item, settings
from procedures.newsroom.tests.page_twins_support import page_entry, snapshot_site

DIRECTIVE = re.compile(r"^::(band|column|button|island|include|raw|endraw)", re.M)


def no_directives(text: str) -> None:
    assert not DIRECTIVE.search(text), text


# ------------------------------------------------------------------ the pure renderer

def render(text: str, includes=None, values=None) -> str:
    return page_twin.render(text, values or {}, "page.md", lambda attributes: (includes or {}).get(attributes.get("kind"), ""), lambda path: "https://example.org" + path)


def test_layout_directives_vanish_and_the_text_stays():
    twin = render('::band{size="bare"}\n# Title\n\nText.\n\n::column{panel="card"}\nMore.\n')
    assert twin == "# Title\n\nText.\n\nMore.\n"


def test_a_button_is_a_link_with_an_absolute_site_path_and_an_island_is_its_summary():
    twin = render('::button{href="/start/" label="Start"}\n::button{href="https://other.example/" label="Away"}\n::island{name="Chart" summary="A chart."}\n::island{name="Quiet"}\n')
    assert twin == "[Start](https://example.org/start/)\n\n[Away](https://other.example/)\n\nA chart.\n"


def test_an_include_is_replaced_by_its_markdown_and_an_empty_one_leaves_nothing():
    twin = render("Before.\n\n::include{kind=\"a\"}\n::include{kind=\"b\"}\nAfter.\n", {"a": "- [One](https://x.example/1)"})
    assert twin == "Before.\n\n- [One](https://x.example/1)\n\nAfter.\n"


def test_raw_regions_and_directives_in_code_fences_are_handled_as_on_the_page():
    twin = render('```\n::include{kind="a"}\n```\n\n::raw\n<div>x</div>\n::endraw\n\nEnd.\n', {"a": "SHOULD NOT APPEAR"})
    assert "SHOULD NOT APPEAR" not in twin and "<div>" not in twin and '::include{kind="a"}' in twin and twin.endswith("End.\n")


def test_other_markus_directives_and_front_matter_are_kept_as_written():
    twin = render('---\ntitle: T\n---\n::image{src="a.png" alt="A"}\n\n:::card\nIn a card.\n:::\n')
    assert twin.startswith("---\ntitle: T\n---\n") and '::image{src="a.png" alt="A"}' in twin and ":::card" in twin


def test_tokens_are_replaced_before_anything_else():
    assert render("{{name}}\n", values={"name": "Example"}) == "Example\n"


def test_markup_becomes_headings_and_distinct_links():
    markup = (
        '<div class="strip"><h3>Proof</h3><ul>'
        '<li><a href="/a/"><img src="x.png"></a><a href="/a/">Alpha</a><span>1 Jan</span></li>'
        '<li><a href="https://o.example/b">Beta &amp; co</a></li>'
        '<li><a href="javascript:alert(1)">Bad</a></li></ul></div>'
    )
    assert page_twin.markup_markdown(markup, lambda path: "https://example.org" + path) == "### Proof\n\n- [Alpha](https://example.org/a/)\n- [Beta & co](https://o.example/b)"


def test_markup_without_links_is_its_text():
    assert page_twin.markup_markdown("<p>Three posts.</p><script>x()</script>", lambda path: path) == "Three posts."


# ------------------------------------------------------------------ a whole projection: the home-page fixture

PAGE = page_entry("wire", "wire", "The wire", "Every source.")
WIRE = (
    '::band{size="bare"}\n'
    '::include{kind="references" select="recent" count="2" heading="Recently accepted" more="/tools/"}\n\n'
    '::include{kind="references" select="recent" count="3" empty="Nothing."}\n\n'
    '::include{kind="references" select="recommended" count="2" empty="Nothing is waiting."}\n\n'
    '::include{kind="threads" select="recent" count="5" empty="No conversations."}\n\n'
    '::include{kind="listing" count="2"}\n'
)


@pytest.fixture(scope="module")
def wire():
    site = snapshot_site({"pages/wire.md": WIRE}, [PAGE], forum=True)
    yield site
    site.cleanup()


def test_an_authored_page_twin_lists_the_references_the_page_shows(wire):
    twin = wire.text("wire/index.md")
    no_directives(twin)
    assert twin.startswith("# The wire\n\n> Every source.\n")
    assert "## Recently accepted\n\n- [Accepted eight](https://www.example.org/posts/8)\n- [Accepted seven](https://www.example.org/posts/7)\n\n[More](https://almanac.example.org/tools/)" in twin


def test_includes_on_one_page_do_not_repeat_a_reference_as_on_the_page(wire):
    twin = wire.text("wire/index.md")
    titles = re.findall(r"^- \[(Accepted [a-z]+[^\]]*)\]", twin, re.M)
    assert len(titles) == len(set(titles)) == 5
    assert titles[:2] == ["Accepted eight", "Accepted seven"] and "Accepted six" in titles
    html = wire.text("wire/index.html")
    assert all(f">{title}</a>" in html for title in titles)


def test_a_recommended_reference_is_labelled_as_not_yet_accepted(wire):
    assert "- [Pending high](https://www.example.org/posts/10) (Recommended by Cyclotron, not yet accepted)" in wire.text("wire/index.md")


def test_threads_link_to_their_pages_and_say_how_many_messages(wire):
    twin = wire.text("wire/index.md")
    assert "- [Is this worth adopting?](https://almanac.example.org/conversations/aaaaaaaaaaaa/) (2 messages)" in twin
    assert "(1 message)" in twin


def test_a_listing_include_is_the_stories_it_places_as_links_to_their_twins(wire):
    twin = wire.text("wire/index.md")
    assert re.search(r"^- \[[^\]]+\]\(https://almanac\.example\.org/[^)]*\.md\)", twin, re.M)


def test_the_twin_holds_only_what_the_page_holds_and_no_private_data(wire):
    twin = wire.text("wire/index.md")
    assert scan_files({"wire/index.md": twin, "llms-full.txt": wire.text("llms-full.txt")}, []) == {}
    # the twin says nothing the snapshot does not publish: no author, summary, confidence or status field
    for private in ("Ada Author", "Summary of post", "confidence", "predictedAcceptProbability", "actor"):
        assert private not in twin


def test_llms_full_carries_the_same_includes_and_no_directive(wire):
    full = wire.text("llms-full.txt")
    no_directives(full)
    assert "- [Accepted eight](https://www.example.org/posts/8)" in full


def test_an_empty_include_says_its_empty_text():
    site = snapshot_site({"pages/wire.md": WIRE}, [PAGE], references={"generatedAt": "2026-10-31T12:00:00.000Z", "references": []})
    try:
        twin = site.text("wire/index.md")
        assert "Nothing." in twin and "Nothing is waiting." in twin
        no_directives(twin)
    finally:
        site.cleanup()


# ------------------------------------------------------------------ freshness: the twin follows the data through the page's own path

def test_the_twin_is_rewritten_with_the_page_when_the_snapshot_changes():
    site = snapshot_site({"pages/wire.md": WIRE}, [PAGE])
    try:
        readers = site.projector.home_page_reader_keys()
        assert {"wire/index.html", "wire/index.md", "llms-full.txt"} <= readers
        before = site.text("wire/index.md")
        document = json.loads((site.out / "_data/home-page/references.json").read_text(encoding="utf-8"))
        document["references"][0]["title"] = "Accepted eight, retitled"
        (site.out / "_data/home-page/references.json").write_text(json.dumps(document), encoding="utf-8")
        site.projector._home_page.reset()
        site.projector._plan_cache = None
        report = project_stale_listings(site.context, readers)
        assert report.ok and {"wire/index.html", "wire/index.md", "llms-full.txt"} <= set(report.written)
        assert "Accepted eight, retitled" in site.text("wire/index.md") and "Accepted eight, retitled" not in before
    finally:
        site.cleanup()


def test_a_page_with_no_data_include_is_not_a_reader_and_its_twin_stays_put():
    plain = {"id": "plain", "path": "plain", "title": "Plain", "dependsOn": [], "source": "pages/plain.md"}
    site = snapshot_site({"pages/plain.md": '::band{size="bare"}\n# Plain\n\n::button{href="/x/" label="Go"}\n'}, [plain])
    try:
        assert not any(key.startswith("plain/") for key in site.projector.home_page_reader_keys())
        assert "[Go](https://almanac.example.org/x/)" in site.text("plain/index.md")
    finally:
        site.cleanup()


def test_an_include_of_stories_changes_the_twin_digest_with_the_stories():
    site = cms_site(
        settings(urls={"sections": {"posts": {}}}, pages=[{"id": "p", "path": "p", "title": "P", "source": "p.md"}]),
        [item("a1", date="2026-01-02"), item("a2", date="2026-01-01")],
        {"p.md": '::band{size="bare"}\n::include{kind="listing" sections="posts" count="1"}\n'},
    )
    try:
        twin = site.text("p/index.md")
        no_directives(twin)
        assert "[A1](" in twin and "[A2](" not in twin
    finally:
        site.cleanup()


# ------------------------------------------------------------------ a site hook's block, a section front page, the home page, an article

BLOCK_HOOKS = '''
DEPENDS_ON = []

def block(name, attributes, page):
    stories = [entry for entry in page.entries if entry.section is not None and entry.section.name == "posts"][:2]
    cards = "".join('<li class="card"><a href="%s">%s</a><span>%s</span></li>' % (entry.url, entry.title, entry.date) for entry in stories)
    return '<section class="strip"><h2>Proof strip</h2><ul>%s</ul></section>' % cards
'''


def test_a_site_hook_block_reaches_the_twin_as_a_list_of_titles_and_links():
    site = cms_site(
        settings(urls={"sections": {"posts": {}}}, hooks="hooks.py", pages=[{"id": "p", "path": "p", "title": "P", "source": "p.md", "dependsOn": ["*"]}]),
        [item("a1", date="2026-01-02"), item("a2", date="2026-01-01")],
        {"hooks.py": BLOCK_HOOKS, "p.md": '::band{size="bare"}\n# P\n\n::include{kind="block" name="proof-strip" depends="posts"}\n'},
    )
    try:
        twin = site.text("p/index.md")
        no_directives(twin)
        assert "## Proof strip\n\n- [A1](" in twin and "- [A2](" in twin
        assert "2026-01-02" not in twin
    finally:
        site.cleanup()


def test_the_home_item_twin_drops_its_template_lines_and_keeps_its_words():
    body = '::band{size="hero"}\n# Welcome\n\nWords here.\n\n::button{href="/start/" label="Start"}\n'
    site = DirectorySite(settings(), [item("index", section=None, body=body, title="Home"), item("hello", date="2026-10-01")])
    try:
        assert site.project_all().ok
        twin = site.text("index.md")
        no_directives(twin)
        assert twin.count("# Welcome") == 1 and "Words here." in twin and "[Start](https://example.org/start/)" in twin
    finally:
        site.cleanup()


def test_an_article_twin_keeps_its_directives_as_written():
    body = '::band{size="bare"}\n# Story\n\n::button{href="/x/" label="Go"}\n'
    site = DirectorySite(settings(), [item("index", section=None, title="Home", body="# Home\n"), item("story", date="2026-10-01", body=body)])
    try:
        assert site.project_all().ok
        twin = site.text("story.md")
        assert '::band{size="bare"}' in twin and '::button{href="/x/" label="Go"}' in twin
    finally:
        site.cleanup()
