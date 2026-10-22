"""Authored page files of the standard front end: the home page from a file, ``::raw``, ``::include`` and the dependency rule."""

from __future__ import annotations

import json
import re

import pytest

from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from procedures.newsroom.tests.standard_frontend_content_support import (
    DirectorySite,
    cards,
    cms_site,
    html_written,
    item,
    settings,
    title_of,
)
from procedures.newsroom.tests.standard_frontend_support import edit_item, written_keys

BAND = '::band{size="bare"}\n'
MAIN = re.compile(r"<main id=\"main\">\n(.*?)\n  </main>", re.S)


ACTIONS = re.compile(r'<div class="markus-page-actions.*?</span></div>', re.S)


def main_of(page: str) -> str:
    """The page's main content without the page actions an authored page also gets (these tests are about the includes)."""
    return ACTIONS.sub("", MAIN.search(page).group(1))


def page_entry(name: str, path: str | None = None, **extra) -> dict:
    return {"id": name, "path": name if path is None else path, "title": name.title(), "source": f"{name}.md", **extra}


def posts():
    return [
        item("f1", date="2026-02-06", tags=["featured"]),
        item("f2", date="2026-02-05", tags=["featured"]),
        item("f3", date="2026-02-04", tags=["featured", "solutions"]),
        item("f4", date="2026-02-03", tags=["featured"]),
        item("n1", date="2026-02-02", tags=["other"]),
        item("n2", date="2026-02-01", tags=["other", "Featured"]),
        item("t1", date="2026-01-20", tags=["tie"]),
        item("t2", date="2026-01-20", tags=["tie"]),
        item("nt1", section="notes", date="2026-02-07", tags=["featured"]),
    ]


SECTIONS = {"sections": {"posts": {"listingPage": False}, "notes": {"listingPage": False}}}

# one page per case: the include line(s) and the slugs the page lists
LISTING_CASES = {
    "all": ('::include{kind="listing" tags="featured"}', ["nt1", "f1", "f2", "f3", "f4", "n2"]),
    "count": ('::include{kind="listing" tags="featured" count="2"}', ["nt1", "f1"]),
    "skip": ('::include{kind="listing" tags="featured" sections="posts" skip="1" count="2"}', ["f2", "f3"]),
    "skip-past-end": ('::include{kind="listing" tags="featured" sections="notes" skip="5"}', []),
    "not-tags": ('::include{kind="listing" tags="featured" sections="posts" notTags="solutions"}', ["f1", "f2", "f4", "n2"]),
    "all-tags": ('::include{kind="listing" allTags="featured,solutions"}', ["f3"]),
    "several-tags": ('::include{kind="listing" tags="tie,other" sections="posts"}', ["n1", "n2", "t2", "t1"]),
    "title": ('::include{kind="listing" tags="featured" sections="posts" sort="title" count="3"}', ["f1", "f2", "f3"]),
    "ties-desc": ('::include{kind="listing" tags="tie"}', ["t2", "t1"]),
    "ties-asc": ('::include{kind="listing" tags="tie" ties="slug-asc"}', ["t1", "t2"]),
    "no-match": ('::include{kind="listing" tags="nothing"}', []),
    "collection": ('::include{kind="listing" collection="feat"}', ["f1", "f2", "f4", "n2"]),
    "collection-count": ('::include{kind="listing" collection="feat" count="2"}', ["f1", "f2"]),
    "collection-sort": ('::include{kind="listing" collection="feat" sort="title" count="2"}', ["f1", "f2"]),
    "collection-refined": ('::include{kind="listing" collection="feat" tags="other"}', ["n1", "n2"]),
    "collection-extra-not-tags": ('::include{kind="listing" collection="feat" notTags="other"}', ["f1", "f2", "f4"]),
    "sorted-collection": ('::include{kind="listing" collection="by-title"}', ["f1", "f2", "f3", "f4", "n2"]),
}
FEATURED = {"id": "feat", "select": {"tags": ["featured"], "sections": ["posts"], "notTags": ["solutions"]}, "base": "feat"}
BY_TITLE = {"id": "by-title", "select": {"tags": ["featured"], "sections": ["posts"]}, "sort": "title", "base": "by-title"}


@pytest.fixture(scope="module")
def listings():
    files = {f"{name}.md": f"---\ntitle: {name}\n---\n{BAND}Before.\n\n{line}\n\nAfter.\n" for name, (line, _expected) in LISTING_CASES.items()}
    pages = [page_entry(name) for name in LISTING_CASES]
    site = cms_site(settings(urls=SECTIONS, collections=[FEATURED, BY_TITLE], pages=pages), posts(), files)
    yield site
    site.cleanup()


@pytest.mark.parametrize("name", sorted(LISTING_CASES))
def test_an_include_listing_shows_the_entries_its_selection_picks(listings, name):
    expected = LISTING_CASES[name][1]
    page = listings.text(f"{name}/index.html")
    assert cards(page) == expected
    assert page.index("Before.") < page.index("After.")                       # the text around an include is kept in order
    if expected:
        assert page.index("Before.") < page.index("markus-card") < page.index("After.")


def test_a_listing_include_is_a_card_grid_unless_the_layout_is_bare():
    files = {
        "grid.md": f'{BAND}::include{{kind="listing" tags="tie" layout="grid"}}\n',
        "bare.md": f'{BAND}::include{{kind="listing" tags="tie" layout="bare"}}\n',
    }
    site = cms_site(settings(urls=SECTIONS, pages=[page_entry("grid"), page_entry("bare")]), posts(), files)
    try:
        assert main_of(site.text("grid/index.html")).startswith('<div class="markus-card-grid"><article')
        bare = main_of(site.text("bare/index.html"))
        assert "markus-card-grid" not in bare and bare.startswith("<article") and bare.count("<article") == 2
    finally:
        site.cleanup()


# ------------------------------------------------------------------ the page file itself

def test_a_page_file_with_path_empty_is_the_home_page():
    home = f'---\ntitle: Ignored\n---\n{BAND}# Welcome\n\nWords.\n\n::include{{kind="listing" tags="other"}}\n'
    pages = [{"id": "home", "path": "", "title": "Start here", "description": "The front door.", "source": "home.md", "image": "/assets/home.png"}]
    site = cms_site(settings(urls=SECTIONS, pages=pages), posts(), {"home.md": home})
    try:
        page = site.text("index.html")
        assert title_of(page) == "Start here · Example"
        assert '<meta name="description" content="The front door.">' in page
        assert '<meta property="og:image" content="https://example.org/assets/home.png">' in page
        assert '<h1 id="welcome">Welcome</h1>' in main_of(page) and cards(page) == ["n1", "n2"]
        assert "Ignored" not in page
        sitemap = site.text("sitemap.xml")
        assert sitemap.count("<loc>https://example.org/</loc>") == 1
        assert "home/index.html" not in site.tree                         # path "" is the root, not /home/
    finally:
        site.cleanup()


def test_a_page_file_at_another_path_has_its_own_url_in_the_sitemap_and_can_be_left_out_of_it():
    files = {"a.md": f"{BAND}Words.\n", "b.md": f"{BAND}Words.\n"}
    pages = [page_entry("a", "guide/start"), page_entry("b", sitemap=False)]
    site = cms_site(settings(pages=pages), [item("x", section=None)], files)
    try:
        assert "guide/start/index.html" in site.tree
        sitemap = site.text("sitemap.xml")
        assert "<loc>https://example.org/guide/start/</loc>" in sitemap and "/b/" not in sitemap
    finally:
        site.cleanup()


def test_a_page_file_converts_markus_between_includes_and_applies_values():
    text = f'{BAND}## Heading {{{{price}}}}\n\nSome *emphasis* and a [link](/x/).\n\n::include{{kind="listing" tags="tie" count="1"}}\n\n- one\n- two\n'
    site = cms_site(settings(values={"price": "$5"}, pages=[page_entry("p")]), posts(), {"p.md": text})
    try:
        body = main_of(site.text("p/index.html"))
        assert '<h2 id="heading-5">Heading $5</h2>' in body and "<em>emphasis</em>" in body and '<a href="/x/">link</a>' in body
        assert body.index("<em>") < body.index("markus-card") < body.index("<li>one</li>")
    finally:
        site.cleanup()


def test_a_page_file_can_use_bands_with_includes_inside():
    text = '::band{tone="muted" size="hero"}\n# Title\n\n::include{kind="listing" tags="tie" count="1"}\n\n::band\nPlain.\n'
    site = cms_site(settings(pages=[page_entry("p")]), posts(), {"p.md": text})
    try:
        body = main_of(site.text("p/index.html"))
        assert 'data-tone="muted" data-size="hero"' in body and body.count("markus-band-inner") == 2
        assert body.index("markus-card-grid") < body.index("Plain.")
    finally:
        site.cleanup()


# ------------------------------------------------------------------ ::raw

RAW_PAGE = f"""{BAND}Before the raw.

::raw
<div class="custom" data-x='1'>
  <script>if (a < b && c > d) {{ run("*not emphasis*"); }}</script>
  <p>&copy; 2026 *kept* [as](text)</p>
  ::band{{size="hero"}}
  ::include{{kind="nonsense"}}
</div>

<style>.a > .b {{ color: red }}</style>
::endraw

Between.

::raw
<hr id="second">
::endraw

```text
::raw
not a raw region
```

After.
"""


def test_raw_html_is_emitted_exactly_as_written():
    site = cms_site(settings(pages=[page_entry("p")]), [item("x", section=None)], {"p.md": RAW_PAGE})
    try:
        body = main_of(site.text("p/index.html"))
        verbatim = (
            "<div class=\"custom\" data-x='1'>\n"
            '  <script>if (a < b && c > d) { run("*not emphasis*"); }</script>\n'
            "  <p>&copy; 2026 *kept* [as](text)</p>\n"
            '  ::band{size="hero"}\n'
            '  ::include{kind="nonsense"}\n'
            "</div>\n\n"
            "<style>.a > .b { color: red }</style>"
        )
        assert verbatim in body
        assert '<hr id="second">' in body
        assert body.index("Before the raw.") < body.index("custom") < body.index("Between.") < body.index('id="second"') < body.index("After.")
        assert "not a raw region" in body and "<pre><code" in body            # a fence holds ::raw as text
        assert "<p>Between.</p>" in body and "<p>After.</p>" in body
    finally:
        site.cleanup()


def test_an_unclosed_raw_region_is_an_error():
    site = DirectorySite(settings(pages=[page_entry("p")]), [item("x", section=None)], {"p.md": f"{BAND}::raw\n<b>never closed</b>\n"})
    try:
        with pytest.raises(ValueError, match="::raw without a closing ::endraw"):
            site.project_all()
    finally:
        site.cleanup()


@pytest.mark.parametrize("body", ["::raw\n<b>x</b>\n::endraw\n", f"{BAND}::raw\n<b>x</b>\n::endraw\n"])
def test_raw_in_a_content_item_is_an_error(body):
    site = DirectorySite(settings(), [item("x", section="posts", body=body)])
    try:
        with pytest.raises(ValueError, match="::raw is only allowed in a page file"):
            site.project_all()
    finally:
        site.cleanup()


def test_raw_in_a_content_item_is_rejected_even_when_the_item_has_no_other_block():
    site = DirectorySite(settings(), [item("x", section="posts", body="Words.\n\n::raw\n<i>y</i>\n::endraw\n")])
    try:
        with pytest.raises(ValueError, match="::raw"):
            site.project_all()
    finally:
        site.cleanup()


def test_raw_inside_a_code_fence_of_an_item_is_text():
    site = DirectorySite(settings(urls={"sections": {"posts": {}}}), [item("x", section="posts", body="```\n::raw\n<b>y</b>\n```\n")])
    try:
        assert site.project_all().ok
        assert "&lt;b&gt;y&lt;/b&gt;" in site.text("posts/x.html")
    finally:
        site.cleanup()


# ------------------------------------------------------------------ other include kinds

SHOWCASE = {"section": "showcase", "path": "built-with", "title": "Built with it"}
CONTACT = {"title": "Contact us", "fields": [{"name": "email", "label": "Email", "type": "email", "required": True}]}


def showcase_items():
    return [
        item("acme", section="showcase", name="Acme Gazette", url="https://gazette.example.org", kind="customer", order=2),
        item("borealis", section="showcase", name="Borealis Review", url="https://borealis.example.org", kind="customer", order=1),
    ]


def test_showcase_and_form_includes_render_the_logo_wall_and_the_form():
    files = {"p.md": f'{BAND}## Wall\n\n::include{{kind="showcase"}}\n\n::include{{kind="form" id="contact"}}\n'}
    pages = [page_entry("p")]
    site = cms_site(settings(showcase=SHOWCASE, forms={"contact": CONTACT}, pages=pages), [*posts(), *showcase_items()], files)
    try:
        body = main_of(site.text("p/index.html"))
        assert body.index("Borealis Review") < body.index("Acme Gazette")                 # by order
        assert 'href="https://gazette.example.org"' in body
        assert 'data-papyrus-form="contact"' in body or "This form is not open yet" in body
        assert 'name="email"' in body and "Contact us" in body
    finally:
        site.cleanup()


def test_a_showcase_include_depends_on_the_showcase_items_only():
    files = {"p.md": f'{BAND}::include{{kind="showcase"}}\n', "q.md": f'{BAND}::include{{kind="listing" tags="tie"}}\n'}
    site = cms_site(settings(showcase=SHOWCASE, pages=[page_entry("p"), page_entry("q")]), [*posts(), *showcase_items()], files)
    try:
        edit_item(site, "item-showcase-acme", front_matter={"name": "Acme Weekly"})
        assert "p/index.html" in written_keys(site) and "q/index.html" not in written_keys(site)
        assert "Acme Weekly" in site.text("p/index.html")
        edit_item(site, "item-posts-f1", title="F1 again")
        assert "p/index.html" not in written_keys(site)
    finally:
        site.cleanup()


@pytest.mark.parametrize(
    "line, message",
    [
        ('::include{kind="nope"}', "needs kind to be one of listing, showcase, form, block"),
        ("::include{tags=\"x\"}", "needs kind to be one of"),
        ('::include{kind="listing" bogus="x"}', "::include listing has unknown attributes: bogus"),
        ('::include{kind="listing" id="x" depends="posts"}', "unknown attributes: depends, id"),
        ('::include{kind="listing" collection="missing"}', "names collection 'missing', which projection.json does not define"),
        ('::include{kind="listing" layout="wide"}', "layout must be one of grid, bare"),
        ('::include{kind="listing" sort="random"}', "sort is date, order or title"),
        ('::include{kind="listing" ties="random"}', "ties is slug-desc or slug-asc"),
        ('::include{kind="listing" count="many"}', "count must be a whole number, got 'many'"),
        ('::include{kind="listing" count="-1"}', "count must be a whole number, got '-1'"),
        ('::include{kind="listing" skip="-2"}', "skip must be a whole number"),
        ('::include{kind="showcase" tags="x"}', "::include showcase takes no attributes"),
        ('::include{kind="showcase"}', "needs a showcase in projection.json"),
        ('::include{kind="form" id="nope"}', "names 'nope', which projection.json does not define"),
        ('::include{kind="form"}', "names None, which projection.json does not define"),
        ('::include{kind="block"}', "block needs a name"),
        ('::include{kind="block" name="x"}', "block 'x': the site has no block hook"),
        ('::include{kind="listing" card="mini"}', "card='mini': the site has no card hook"),
    ],
)
def test_bad_includes_are_errors_with_the_page_file_named(line, message):
    site = DirectorySite(settings(pages=[page_entry("p")]), [item("x", section="posts", tags=["t"])], {"p.md": f"{BAND}{line}\n"})
    try:
        with pytest.raises(ValueError, match=re.escape(message)) as raised:
            site.project_all()
        assert "p.md" in str(raised.value) or "pages.p" in str(raised.value) or "card=" in str(raised.value)
    finally:
        site.cleanup()


def test_an_include_before_the_first_band_is_an_error():
    site = DirectorySite(settings(pages=[page_entry("p")]), [item("x", section="posts")], {"p.md": '::include{kind="listing"}\n'})
    try:
        with pytest.raises(ValueError, match="content before the first ::band"):
            site.project_all()
    finally:
        site.cleanup()


def test_an_include_in_a_content_item_is_an_error():
    site = DirectorySite(settings(), [item("x", section="posts", body=f'{BAND}::include{{kind="listing"}}\n')])
    try:
        with pytest.raises(ValueError, match="::include is not available here"):
            site.project_all()
    finally:
        site.cleanup()


@pytest.mark.parametrize("source", ["missing.md", "../outside.md", "/etc/hosts"])
def test_a_page_source_must_be_a_file_inside_the_static_directory(source):
    site = DirectorySite(settings(pages=[{"id": "p", "path": "p", "title": "P", "source": source}]), [item("x", section="posts")])
    try:
        (site.work / "outside.md").write_text("::band\nx\n", encoding="utf-8")
        with pytest.raises(ValueError, match="is not a file inside the static directory"):
            site.project_all()
    finally:
        site.cleanup()


def test_unknown_page_settings_are_rejected():
    with pytest.raises(ValueError, match="Unknown pages settings: src"):
        standard_settings_from_mapping(settings(pages=[{"id": "p", "path": "p", "title": "P", "src": "p.md"}]))
    config = standard_settings_from_mapping(settings(pages=[{"id": "p", "path": "", "title": "P", "source": "p.md", "image": "/a.png"}]))
    assert (config.pages[0].path, config.pages[0].source, config.pages[0].image) == ("", "p.md", "/a.png")


# ------------------------------------------------------------------ the block hook

BLOCK_HOOKS = '''
import json

DEPENDS_ON = []

def block(name, attributes, page):
    posts = [entry.slug for entry in page.entries if entry.section is not None and entry.section.name == "posts"]
    return '<div class="blk" data-name="%s" data-page="%s/%s" data-attrs=\\'%s\\'>posts=%d</div>' % (
        name, page.kind, page.custom_id, json.dumps(attributes, sort_keys=True), len(posts)
    )
'''


def test_a_block_include_calls_the_block_hook_with_its_name_attributes_and_page():
    text = f'{BAND}::include{{kind="block" name="proof-strip" depends="posts" flavor="plain" limit="3"}}\n\n::include{{kind="block" name="other"}}\n'
    site = cms_site(settings(urls=SECTIONS, hooks="hooks.py", pages=[page_entry("p")]), posts(), {"hooks.py": BLOCK_HOOKS, "p.md": text})
    try:
        body = main_of(site.text("p/index.html"))
        first, second = re.findall(r'<div class="blk"[^>]*>posts=\d+</div>', body)
        assert 'data-name="proof-strip" data-page="custom/p"' in first
        assert json.loads(re.search(r"data-attrs='([^']*)'", first).group(1)) == {"flavor": "plain", "limit": "3"}      # not kind, name or depends
        assert "posts=8" in first and 'data-name="other"' in second and "data-attrs='{}'" in second
    finally:
        site.cleanup()


# ------------------------------------------------------------------ the dependency rule

DEPENDENCY_PAGES = {
    "home": ("", f'{BAND}# Home\n\n::include{{kind="listing" tags="other" sections="posts"}}\n'),
    "landing": ("landing", f'{BAND}# Landing\n\n::include{{kind="listing" tags="featured" sections="posts" sort="title"}}\n'),
    "top": ("top", f'{BAND}# Top two\n\n::include{{kind="listing" tags="featured" sections="posts" count="2"}}\n'),
}


def dependency_site(extra_pages=None, files=None, **more):
    pages = [{"id": name, "path": path, "title": name.title(), "source": f"{name}.md"} for name, (path, _text) in DEPENDENCY_PAGES.items()]
    static = {f"{name}.md": text for name, (_path, text) in DEPENDENCY_PAGES.items()}
    return cms_site(
        settings(urls=SECTIONS, listings={"tags": False}, pages=[*pages, *(extra_pages or [])], **more),
        [*posts(), item("z1", date="2026-01-01", tags=["misc"]), item("z2", section="notes", date="2026-01-02", tags=["misc"])],
        {**static, **(files or {})},
    )


@pytest.fixture()
def depending():
    site = dependency_site()
    yield site
    site.cleanup()


def test_editing_a_matching_item_rewrites_the_including_page_and_only_that_one(depending):
    edit_item(depending, "item-posts-n1", title="N1 renamed")                 # n1 is shown by the home page only
    assert html_written(written_keys(depending)) == {"posts/n1.html", "index.html"}
    assert "N1 renamed" in depending.text("index.html")

    edit_item(depending, "item-posts-f3", title="F3 renamed")                 # f3 is shown by landing; top shows two others
    assert html_written(written_keys(depending)) == {"posts/f3.html", "landing/index.html"}

    edit_item(depending, "item-posts-f2", title="F2 renamed")                 # shown by landing and (as the second newest) by top
    assert html_written(written_keys(depending)) == {"posts/f2.html", "landing/index.html", "top/index.html"}


def test_editing_a_non_matching_item_rewrites_no_other_page(depending):
    before = depending.digests()
    edit_item(depending, "item-posts-z1", title="Z1 renamed")
    assert html_written(written_keys(depending)) == {"posts/z1.html"}
    edit_item(depending, "item-notes-z2", title="Z2 renamed")                 # another section: nothing selects it
    assert html_written(written_keys(depending)) == {"notes/z2.html"}
    edit_item(depending, "item-notes-nt1", title="NT1 renamed")               # featured, but in a section the includes do not select
    assert html_written(written_keys(depending)) == {"notes/nt1.html"}
    changed = {key for key, digest in depending.digests().items() if before.get(key) != digest and key.endswith(".html")}
    assert changed == {"posts/z1.html", "notes/z2.html", "notes/nt1.html"}


def test_an_entry_past_the_count_does_not_rewrite_the_page(depending):
    edit_item(depending, "item-posts-f4", title="F4 renamed")                 # fourth in line: top shows two
    assert "top/index.html" not in written_keys(depending) and "landing/index.html" in written_keys(depending)


def test_a_body_only_edit_rewrites_the_item_page_alone(depending):
    edit_item(depending, "item-posts-f1", body="A different body entirely.\n")     # the cards do not show the body
    assert html_written(written_keys(depending)) == {"posts/f1.html"}


def test_a_change_of_tags_moves_an_item_between_the_pages_that_select_it(depending):
    edit_item(depending, "item-posts-z1", front_matter={"tags": ["featured"]})
    assert html_written(written_keys(depending)) == {"posts/z1.html", "landing/index.html"}
    assert "Z1" in depending.text("landing/index.html")
    edit_item(depending, "item-posts-z1", front_matter={"tags": ["misc"]})
    assert html_written(written_keys(depending)) == {"posts/z1.html", "landing/index.html"}
    assert "Z1" not in depending.text("landing/index.html")


def test_publishing_a_new_matching_item_rewrites_only_the_selecting_pages():
    from papyrus_content.projection.engine import project
    from papyrus_content.publishing import publish_item, save_item
    from procedures.newsroom.tests.projection_fixtures import ACTOR, NOW
    from procedures.newsroom.tests.standard_frontend_support import fields_for

    site = dependency_site()
    try:
        path = site.content_root / "posts" / "new.md"
        path.write_text("---\ntitle: Brand new\ndate: '2026-03-01'\ntags: [other]\n---\nBody.\n", encoding="utf-8")
        fields = fields_for(site.content_root, path)
        save_item(site.client, fields, actor=ACTOR, now=NOW)
        publish_item(site.client, fields.id, actor=ACTOR, now=NOW)
        site.writer.operations.clear()
        assert project(site.context, fields.id).ok
        assert html_written(written_keys(site)) == {"posts/new.html", "index.html"}
        assert cards(site.text("index.html"))[0] == "new"
    finally:
        site.cleanup()


def changed_inputs(site, page_file: str, text: str) -> set[str]:
    """The pages whose input digest differs once a page file of the static directory has new text."""
    index = site.context.source.site_index()
    before = site.projector.listing_inputs(index)
    (site.static / page_file).write_text(text, encoding="utf-8")
    after = StandardMarkusProjector.from_static_directory(site.static, environ=site.environ).listing_inputs(index)
    return {key for key in after if before.get(key) != after[key]}


def test_editing_the_page_file_changes_the_inputs_of_that_page_only(depending):
    revised = f'{BAND}# Landing, revised\n\n::include{{kind="listing" tags="featured" sections="posts" sort="title"}}\n'
    assert changed_inputs(depending, "landing.md", revised) == {"landing/index.html", "landing/index.md", "llms-full.txt"}    # llms-full.txt carries the authored page's twin text


def test_changing_an_include_attribute_changes_the_inputs_even_when_the_entries_are_the_same(depending):
    same_entries = f'{BAND}# Top two\n\n::include{{kind="listing" tags="featured" sections="posts" count="2" layout="bare"}}\n'
    assert changed_inputs(depending, "top.md", same_entries) == {"top/index.html", "top/index.md"}


def test_an_unchanged_page_file_changes_no_input(depending):
    assert changed_inputs(depending, "top.md", DEPENDENCY_PAGES["top"][1]) == set()


BLOCK_PAGES = {
    "blk": f'{BAND}::include{{kind="block" name="count" depends="posts"}}\n',
    "blk-all": f'{BAND}::include{{kind="block" name="count" depends="*"}}\n',
    "blk-none": f'{BAND}::include{{kind="block" name="count"}}\n',
    "blk-notes": f'{BAND}::include{{kind="block" name="count" depends="notes,@root"}}\n',
}


def block_site():
    pages = [{"id": name, "path": name, "title": name, "source": f"{name}.md"} for name in BLOCK_PAGES]
    return cms_site(
        settings(urls=SECTIONS, listings={"tags": False, "homeCount": 1}, hooks="hooks.py", pages=pages),
        [*posts(), item("z1", date="2026-01-01", tags=["misc"]), item("z2", section="notes", date="2026-01-02", tags=["misc"])],
        {"hooks.py": BLOCK_HOOKS, **{f"{name}.md": text for name, text in BLOCK_PAGES.items()}},
    )


def test_a_block_include_depends_on_the_sections_it_names():
    site = block_site()
    try:
        assert "posts=9" in site.text("blk/index.html")
        edit_item(site, "item-posts-z1", title="Z1 renamed")
        assert html_written(written_keys(site)) == {"posts/z1.html", "blk/index.html", "blk-all/index.html"}
        edit_item(site, "item-notes-z2", title="Z2 renamed")
        assert html_written(written_keys(site)) == {"notes/z2.html", "blk-all/index.html", "blk-notes/index.html"}
        edit_item(site, "item-posts-z1", title="Z1 renamed", body="Only the body changed.\n")
        assert html_written(written_keys(site)) == {"posts/z1.html"}
    finally:
        site.cleanup()


def test_a_block_that_names_no_section_depends_on_no_entry():
    site = block_site()
    try:
        for item_id, title in (("item-posts-f1", "F1 renamed"), ("item-notes-nt1", "NT1 renamed")):
            edit_item(site, item_id, title=title)
            assert "blk-none/index.html" not in written_keys(site)
    finally:
        site.cleanup()


def test_publishing_a_post_changes_the_block_that_counts_posts():
    from papyrus_content.publishing import unpublish_item
    from papyrus_content.projection.engine import project
    from procedures.newsroom.tests.projection_fixtures import ACTOR, NOW

    site = block_site()
    try:
        unpublish_item(site.client, "item-posts-z1", actor=ACTOR, now=NOW)
        site.writer.operations.clear()
        assert project(site.context, "item-posts-z1").ok
        assert "blk/index.html" in written_keys(site) and "posts=8" in site.text("blk/index.html")
        assert "blk-none/index.html" not in written_keys(site)
    finally:
        site.cleanup()


# ------------------------------------------------------------------ the wrapper element, and the 404 page file

def test_a_listing_include_with_a_tag_wraps_the_cards_and_draws_nothing_when_nothing_is_selected():
    files = {
        "wrapped.md": f'{BAND}::include{{kind="listing" tags="tie" layout="bare" tag="ul" class="grid list"}}\n',
        "empty.md": f'{BAND}Before.\n\n::include{{kind="listing" tags="nothing" layout="bare" tag="ul" class="grid list"}}\n\nAfter.\n',
    }
    site = cms_site(settings(urls=SECTIONS, pages=[page_entry("wrapped"), page_entry("empty")]), posts(), files)
    try:
        wrapped = main_of(site.text("wrapped/index.html"))
        assert wrapped.startswith('<ul class="grid list"><article') and wrapped.endswith("</ul>")
        assert "<ul" not in main_of(site.text("empty/index.html"))
    finally:
        site.cleanup()


@pytest.mark.parametrize("line", ['::include{kind="listing" tag="table" layout="bare"}', '::include{kind="listing" class="x" layout="bare"}', '::include{kind="listing" tag="ul"}'])
def test_a_bad_wrapper_is_an_error(line):
    site = DirectorySite(settings(pages=[page_entry("p")]), [item("x", section="posts", tags=["t"])], {"p.md": f"{BAND}{line}\n"})
    try:
        with pytest.raises(ValueError, match="::include tag"):
            site.project_all()
    finally:
        site.cleanup()


def test_the_not_found_page_can_be_a_page_file_with_includes():
    files = {"404.md": f'{BAND}::raw\n<p class="lost">Lost.</p>\n::endraw\n\n::include{{kind="listing" tags="tie" count="1" layout="bare"}}\n'}
    site = cms_site(settings(urls=SECTIONS, notFound={"title": "Gone", "source": "404.md"}), posts(), files)
    try:
        page = site.text("404.html")
        assert '<p class="lost">Lost.</p>' in page and "<title>Gone" in page and "<article" in page
    finally:
        site.cleanup()
