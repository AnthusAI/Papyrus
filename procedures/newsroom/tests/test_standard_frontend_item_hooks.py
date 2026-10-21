"""The item-level hooks of the standard front end, card variants, the guarded environment and the vendor stylesheet."""

from __future__ import annotations

import dataclasses
import re

import pytest

from papyrus_content.markus_renderer.images import ImagePipeline
from papyrus_content.projection import projector as base_projector
from papyrus_content.projection.projector import MarkusProjectorSettings, read_static_files
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.hooks import HOOK_NAMES, HookSite, Hooks, load_hooks
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from papyrus_content.renditions import RenditionSettings
from procedures.newsroom.tests.standard_frontend_content_support import cards, cms_site, html_written, item, settings, title_of
from procedures.newsroom.tests.standard_frontend_support import edit_item, written_keys

SECTIONS = {"sections": {"posts": {}}}
BAND = '::band{size="bare"}\n'


def posts(*extra):
    return [
        item("a", date="2026-02-03", tags=["red"]),
        item("b", date="2026-02-02", tags=["red"]),
        item("c", date="2026-02-01", tags=["blue"]),
        *extra,
    ]


def site_with(hooks: str, items=None, files=None, **more):
    return cms_site(settings(urls=SECTIONS, hooks="hooks.py", **more), items or posts(), {"hooks.py": hooks, **(files or {})})


def hook_names(module_text: str, tmp_path) -> Hooks:
    (tmp_path / "hooks.py").write_text(module_text, encoding="utf-8")
    return load_hooks(tmp_path, "hooks.py")


# ------------------------------------------------------------------ the hook module

def test_the_new_hooks_are_named_and_loaded(tmp_path):
    names = ("item_filter", "source", "item_transform", "image_pipeline", "page_head", "page_finish", "block", "item_inputs", "redirects")
    assert set(names) <= set(HOOK_NAMES)
    module = "\n".join(f"def {name}(*args):\n    return None\n" for name in names)
    hooks = hook_names(module, tmp_path)
    assert all(getattr(hooks, name) is not None for name in names)


def test_a_misspelled_new_hook_is_still_an_error(tmp_path):
    with pytest.raises(ValueError, match="unknown hooks: item_filters, redirect"):
        hook_names("def item_filters(s):\n    return True\n\ndef redirect(site):\n    return {}\n", tmp_path)


def test_which_hooks_see_the_whole_site():
    quiet = (Hooks(item_filter=lambda s: True), Hooks(source=lambda s, t, site: t), Hooks(item_transform=lambda s: None),
             Hooks(image_pipeline=lambda p: p), Hooks(item_inputs=lambda site: 1), Hooks(redirects=lambda site: {}))
    assert not any(hooks.sees_the_site or hooks.renders_listings for hooks in quiet)
    for hooks in (Hooks(page_head=lambda h, p: h), Hooks(page_finish=lambda h, p: h), Hooks(block=lambda n, a, p: "")):
        assert hooks.sees_the_site
    assert Hooks(block=lambda n, a, p: "").renders_listings and not Hooks(page_head=lambda h, p: h).renders_listings


def test_page_level_hooks_make_every_page_depend_on_every_entry_unless_the_module_narrows_it():
    def projector(hooks):
        return StandardMarkusProjector(MarkusProjectorSettings(theme=None), read_static_files(None, None), standard_settings_from_mapping(settings()), hooks=hooks)

    assert projector(Hooks(page_head=lambda h, p: h))._dependencies("item") == ("*",)
    assert projector(Hooks(page_head=lambda h, p: h, depends_on=()))._dependencies("item") == ()
    assert projector(Hooks(item_filter=lambda s: True))._dependencies("item") == ()


# ------------------------------------------------------------------ item_filter

FILTER = '''
DEPENDS_ON = []

def item_filter(summary):
    return summary.slug != "secret" and not summary.front_matter.get("internal")
'''


def filtered_items():
    return posts(
        item("secret", date="2026-02-10", tags=["red", "hidden"], aliases=["/old/secret/"]),
        item("flagged", date="2026-02-11", tags=["red"], internal=True),
        item("shown", date="2026-02-04", tags=["red"], aliases=["/old/shown/"]),
    )


def test_item_filter_leaves_an_item_out_of_every_page_listing_and_file():
    site = site_with(FILTER, filtered_items(), collections=[{"id": "reds", "select": {"tags": ["red"]}}])
    try:
        for slug in ("secret", "flagged"):
            assert f"posts/{slug}.html" not in site.tree and f"posts/{slug}.md" not in site.tree
            everything = "\n".join(text.decode("utf-8") for key, text in site.tree.items() if key.endswith((".html", ".xml", ".txt", ".md", ".json")))
            assert f"/posts/{slug}" not in everything
        assert cards(site.text("posts/index.html")) == ["shown", "a", "b", "c"]
        assert cards(site.text("reds/index.html")) == ["shown", "a", "b"]
        assert cards(site.text("tags/red/index.html")) == ["shown", "a", "b"]
        assert "tags/hidden/index.html" not in site.tree                               # the only entry of that tag is filtered
        assert "/posts/shown.html" in site.text("sitemap.xml") and "/posts/secret" not in site.text("sitemap.xml")
        assert "/old/secret/" not in site.redirects.mapping and site.redirects.mapping["/old/shown/"] == "/posts/shown.html"
    finally:
        site.cleanup()


def test_item_filter_applies_when_an_item_is_edited_into_the_filter():
    site = site_with(FILTER)
    try:
        assert "posts/b.html" in site.tree
        edit_item(site, "item-posts-b", front_matter={"internal": True})
        assert not (site.out / "posts" / "b.html").exists() and not (site.out / "posts" / "b.md").exists()
        assert cards(site.text("posts/index.html")) == ["a", "c"]
        edit_item(site, "item-posts-b", front_matter={"internal": False})
        assert (site.out / "posts" / "b.html").exists() and cards(site.text("posts/index.html")) == ["a", "b", "c"]
    finally:
        site.cleanup()


# ------------------------------------------------------------------ source and item_transform

SOURCE = '''
DEPENDS_ON = []

def source(summary, text, site):
    names = site.memo("names", lambda: ", ".join(sorted(item.slug for item in site.items)))
    return text.replace("PLACEHOLDER", "staged for " + summary.slug + " among " + names).replace("INCLUDED", "see %s" % site.static_directory.name)
'''


def test_the_source_hook_stages_the_text_that_is_converted():
    site = site_with(SOURCE, posts(item("p", date="2026-02-09", body="Hello PLACEHOLDER.\n\nINCLUDED\n")))
    try:
        page = site.text("posts/p.html")
        assert "<p>Hello staged for p among a, b, c, p.</p>" in page and f"<p>see {site.static.name}</p>" in page
        assert "PLACEHOLDER" not in page
        assert "Body of a." in site.text("posts/a.html")                              # items without the marker are converted as written
        assert "PLACEHOLDER" in site.text("posts/p.md")                               # the Markdown twin keeps the item's own text
    finally:
        site.cleanup()


def test_the_source_hook_receives_the_items_own_text_and_a_hook_site():
    hooks = '''
import json

DEPENDS_ON = []

def source(summary, text, site):
    with (site.static_directory / "seen.jsonl").open("a") as handle:
        handle.write(json.dumps([summary.slug, text, type(site).__name__, len(site.items)]) + "\\n")
    return "Staged for " + summary.slug + ".\\n"
'''
    site = site_with(hooks, [item("only", date="2026-02-01", body="Original text.\n")])
    try:
        import json

        seen = [json.loads(line) for line in (site.static / "seen.jsonl").read_text().splitlines()]
        assert [entry[0] for entry in seen] == ["only"] and [entry[2:] for entry in seen] == [["HookSite", 1]]
        assert seen[0][1].startswith("---\n") and seen[0][1].endswith("---\nOriginal text.\n")             # the item's text, front matter included
        page = site.text("posts/only.html")
        assert "Staged for only." in page and "Original text." not in page
    finally:
        site.cleanup()


TRANSFORM = '''
from papyrus_content.markus_renderer.transforms import FragmentTransform

def item_transform(summary):
    if summary.slug == "plain":
        return None
    return FragmentTransform(class_map={"markus-document": "post post--" + summary.slug})
'''


def test_the_item_transform_hook_rewrites_the_converted_fragment():
    site = site_with(TRANSFORM, posts(item("plain", date="2026-02-09")))
    try:
        assert '<article class="post post--a" data-theme=' in site.text("posts/a.html")
        assert 'class="markus-document"' not in site.text("posts/a.html")
        assert '<article class="markus-document"' in site.text("posts/plain.html")      # None: the fragment is untouched
    finally:
        site.cleanup()


def test_the_image_pipeline_hook_replaces_the_pipeline_pages_are_rendered_with(monkeypatch):
    calls = []

    def image_pipeline(pipeline):
        calls.append(pipeline)
        return dataclasses.replace(pipeline, figure_class="site-figure")

    def build(hooks):
        return StandardMarkusProjector(
            MarkusProjectorSettings(theme=None, images=RenditionSettings(pipeline=ImagePipeline())),
            read_static_files(None, None),
            standard_settings_from_mapping(settings()),
            hooks=hooks,
        )

    projector = build(Hooks(image_pipeline=image_pipeline))
    pipeline = projector._pipeline()
    assert pipeline.figure_class == "site-figure" and calls == [ImagePipeline()]
    assert projector._pipeline() is pipeline and len(calls) == 1                         # computed once

    captured = {}
    monkeypatch.setattr(projector, "_image_builder", lambda text: None)
    monkeypatch.setattr(base_projector, "render_fragment_text", lambda text, **kwargs: captured.update(kwargs) or "<p>x</p>")
    projector._fragment("Text.\n", 0)
    assert captured["images"].figure_class == "site-figure"
    assert build(Hooks())._pipeline().figure_class == "papyrus-image"                     # no hook: the configured pipeline

    bare = StandardMarkusProjector(MarkusProjectorSettings(theme=None), read_static_files(None, None), standard_settings_from_mapping(settings()), hooks=Hooks(image_pipeline=image_pipeline))
    assert bare._pipeline() is None and len(calls) == 1                                  # no images settings: the hook is not called


# ------------------------------------------------------------------ page_head and page_finish

HEAD = '''
import dataclasses

DEPENDS_ON = []

def page_head(head, page):
    if page.kind != "item":
        return head
    return dataclasses.replace(head, title=head.title + " (revised)", description="About " + page.entry.slug + ".", image="/assets/" + page.entry.slug + ".png", noindex=page.entry.slug == "c")
'''


def test_page_head_overrides_the_description_of_the_head():
    site = site_with(HEAD)
    try:
        page = site.text("posts/a.html")
        assert '<meta name="description" content="About a.">' in page
        assert '<meta property="og:title" content="A (revised)">' in page and '<meta name="twitter:title" content="A (revised)">' in page
        assert '<meta property="og:image" content="https://example.org/assets/a.png">' in page
        assert '"headline":"A (revised)"' in page
        assert '<meta name="robots"' not in page and '<meta name="robots" content="noindex, nofollow">' in site.text("posts/c.html")
        listing = site.text("posts/index.html")
        assert "(revised)" not in listing and "About" not in listing                     # other kinds are returned unchanged
    finally:
        site.cleanup()


def test_page_head_title_override_reaches_the_title_tag():
    site = site_with(HEAD)
    try:
        assert title_of(site.text("posts/a.html")).startswith("A (revised)")
    finally:
        site.cleanup()


FINISH = '''
def head_extra(page):
    return '<meta name="stage" content="head_extra">'

def body_class(page):
    return "stage-body"

def page_finish(html, page):
    assert html.startswith("<!DOCTYPE html>") and html.rstrip().endswith("</html>")
    html = html.replace('content="head_extra"', 'content="finished"').replace("stage-body", "stage-body-finished")
    return html.replace("</html>", "<!--finish:" + page.kind + "--></html>")
'''


def test_page_finish_is_the_last_step_and_sees_the_finished_page():
    site = site_with(FINISH)
    try:
        for key, kind in (("posts/a.html", "item"), ("posts/index.html", "listing"), ("404.html", "not_found"), ("tags/index.html", "tags"), ("index.html", "home")):
            page = site.text(key)
            assert page.rstrip().endswith(f"<!--finish:{kind}--></html>")
            assert '<meta name="stage" content="finished">' in page and "stage-body-finished" in page   # it ran after head_extra and body_class
            assert "head_extra" not in page
    finally:
        site.cleanup()


def test_page_finish_runs_after_page_head():
    hooks = HEAD + '''
def page_finish(html, page):
    return html.replace("A (revised)", "A (finished)")
'''
    site = site_with(hooks)
    try:
        assert '<meta property="og:title" content="A (finished)">' in site.text("posts/a.html")
    finally:
        site.cleanup()


# ------------------------------------------------------------------ redirects

REDIRECTS = '''
DEPENDS_ON = []

def redirects(site):
    slugs = {summary.slug for summary in site.items}
    return {
        "/derived/": "/posts/a.html",
        "/posts/b.html": "/posts/a.html",
        "/explicit/": "/from-hook/",
        "/aliased/": "/from-hook/",
        "/posts/": "/posts/a.html",
        "/": "/posts/a.html",
        "/only-if-c/": "/posts/c.html" if "c" in slugs else "/posts/a.html",
    }
'''


def test_the_redirects_hook_adds_exact_redirects_and_explicit_settings_win():
    items = posts(item("moved", date="2026-02-09", aliases=["/aliased/"]))
    site = site_with(REDIRECTS, items, redirects={"exact": {"/explicit/": "/from-settings/"}})
    try:
        mapping = site.redirects.mapping
        assert mapping["/derived/"] == "/posts/a.html"
        assert mapping["/explicit/"] == "/from-settings/"                                # redirects.exact wins over the hook
        assert mapping["/aliased/"] == "/from-hook/"                                      # the hook is on top of the aliases
        assert mapping["/only-if-c/"] == "/posts/c.html"
        for live in ("/posts/b.html", "/posts/", "/"):                      # a path that is a page is never redirected
            assert live not in mapping
    finally:
        site.cleanup()


def test_the_redirects_hook_reads_the_current_items_when_it_is_projected_again():
    site = site_with(REDIRECTS)
    try:
        assert site.redirects.mapping["/only-if-c/"] == "/posts/c.html"
        from papyrus_content.projection.engine import project
        from papyrus_content.publishing import unpublish_item
        from procedures.newsroom.tests.projection_fixtures import ACTOR, NOW

        unpublish_item(site.client, "item-posts-c", actor=ACTOR, now=NOW)
        project(site.context, "item-posts-c")
        assert site.redirects.mapping["/only-if-c/"] == "/posts/a.html"
    finally:
        site.cleanup()


# ------------------------------------------------------------------ item_inputs

COUNTING = '''
DEPENDS_ON = []

def source(summary, text, site):
    return text + "\\nThe site has " + str(len(site.items)) + " items.\\n"
'''
INPUTS = COUNTING + '''
def item_inputs(site):
    return sorted(summary.slug for summary in site.items)
'''
NO_INPUTS = COUNTING


def inputs_site(hooks, tmp_extra=None):
    pages = [{"id": "quiet", "path": "quiet", "title": "Quiet", "source": "quiet.md"}]
    return site_with(hooks, files={"quiet.md": f'{BAND}::include{{kind="listing" tags="nothing"}}\n'}, pages=pages, listings={"tags": False, "homeCount": 1})


def publish_new_item(site) -> str:
    from papyrus_content.projection.engine import project
    from papyrus_content.publishing import publish_item, save_item
    from procedures.newsroom.tests.projection_fixtures import ACTOR, NOW
    from procedures.newsroom.tests.standard_frontend_support import fields_for

    path = site.content_root / "posts" / "d.md"
    path.write_text("---\ntitle: D\ndate: '2026-02-09'\ntags: [green]\n---\nBody.\n", encoding="utf-8")
    fields = fields_for(site.content_root, path)
    save_item(site.client, fields, actor=ACTOR, now=NOW)
    publish_item(site.client, fields.id, actor=ACTOR, now=NOW)
    site.writer.operations.clear()
    assert project(site.context, fields.id).ok
    return fields.id


def test_changed_item_inputs_re_render_every_item_page_and_nothing_else():
    site = inputs_site(INPUTS)
    try:
        edit_item(site, "item-posts-b", title="B renamed")                               # the table of slugs did not change
        assert html_written(written_keys(site)) == {"posts/b.html", "posts/index.html"}
        publish_new_item(site)                                                            # it did: every page that reads it is rendered again
        written = html_written(written_keys(site))
        assert {"posts/a.html", "posts/b.html", "posts/c.html", "posts/d.html", "posts/index.html"} <= written
        assert "The site has 4 items." in site.text("posts/a.html")
        assert written - {"posts/a.html", "posts/b.html", "posts/c.html", "posts/d.html", "posts/index.html", "index.html", "tags/green/index.html"} == set()
        assert "quiet/index.html" not in written and "404.html" not in written
    finally:
        site.cleanup()


def test_without_the_hook_a_new_item_leaves_the_other_item_pages_alone():
    site = inputs_site(NO_INPUTS)
    try:
        publish_new_item(site)
        assert {key for key in html_written(written_keys(site)) if key.startswith("posts/") and key != "posts/index.html"} == {"posts/d.html"}
        assert "The site has 3 items." in site.text("posts/a.html")                      # the stale page the hook exists to avoid
    finally:
        site.cleanup()


# ------------------------------------------------------------------ HookSite

def test_hook_site_memo_builds_each_name_once():
    calls = []
    hook_site = HookSite(("a", "b"), static_directory=None, records=lambda: calls.append("records") or [{"id": 1}])
    assert hook_site.items == ("a", "b") and hook_site.static_directory is None
    assert hook_site.memo("x", lambda: calls.append("x") or {"v": 1}) is hook_site.memo("x", lambda: calls.append("x again") or {"v": 2})
    assert hook_site.memo("y", lambda: calls.append("y") or 2) == 2 and hook_site.memo("falsy", lambda: calls.append("f") or 0) == 0
    hook_site.memo("falsy", lambda: calls.append("f2") or 0)
    assert hook_site.rendition_records() == [{"id": 1}] and hook_site.rendition_records() is hook_site.rendition_records()
    assert calls == ["x", "y", "f", "records"]


def test_hook_site_is_shared_by_all_hooks_of_one_projection_and_memo_is_built_once():
    hooks = '''
DEPENDS_ON = []

def _count(site, name):
    with (site.static_directory / "calls.log").open("a") as handle:
        handle.write(name + "\\n")

def source(summary, text, site):
    site.memo("table", lambda: _count(site, "source-table") or {s.slug: s.output_path for s in site.items})
    return text

def item_inputs(site):
    return site.memo("table", lambda: _count(site, "inputs-table") or {})

def redirects(site):
    site.memo("table", lambda: _count(site, "redirects-table") or {})
    return {}

def page_finish(html, page):
    page.site.memo("table", lambda: _count(page.site, "finish-table") or {})
    return html
'''
    site = site_with(hooks)
    try:
        log = (site.static / "calls.log").read_text().split()
        assert len(log) == 1 and log[0].endswith("-table")                              # one build for the whole projection
    finally:
        site.cleanup()


def test_page_site_is_the_hook_site_with_the_items_and_the_static_directory():
    hooks = '''
DEPENDS_ON = []

def page_finish(html, page):
    site = page.site
    return html + "<!--" + str(len(site.items)) + ":" + site.static_directory.name + ":" + str(site.rendition_records()) + "-->"
'''
    site = site_with(hooks)
    try:
        assert site.text("posts/index.html").rstrip().endswith(f"<!--3:{site.static.name}:[]-->")
    finally:
        site.cleanup()


# ------------------------------------------------------------------ card variant and index

CARDS = '''
DEPENDS_ON = []

def card(entry, page, variant=None, index=0):
    return '<li class="c" data-variant="%s" data-index="%d" data-page="%s">%s</li>' % (variant, index, page.kind, entry.slug)
'''
INDEX_ONLY = '''
DEPENDS_ON = []

def card(entry, page, index):
    return '<li data-index="%d">%s</li>' % (index, entry.slug)
'''
PLAIN_CARD = '''
DEPENDS_ON = []

def card(entry, page):
    return '<li>%s</li>' % entry.slug
'''


def card_page(hooks, line, **more):
    files = {"p.md": f"{BAND}{line}\n"}
    pages = [{"id": "p", "path": "p", "title": "P", "source": "p.md"}]
    return site_with(hooks, files=files, pages=pages, **more)


def test_card_receives_the_variant_and_the_index_of_each_card_in_an_include():
    site = card_page(CARDS, '::include{kind="listing" card="mini" tags="red"}')
    try:
        body = site.text("p/index.html")
        assert re.findall(r'<li class="c" data-variant="mini" data-index="(\d)" data-page="custom">(\w)</li>', body) == [("0", "a"), ("1", "b")]
        assert 'data-variant="None" data-index="0" data-page="listing">a</li>' in site.text("posts/index.html")         # listings: no variant, index 0
        assert 'data-variant="None" data-index="0" data-page="home">' in site.text("index.html")
    finally:
        site.cleanup()


def test_an_include_without_a_variant_passes_none():
    site = card_page(CARDS, '::include{kind="listing" tags="red" layout="bare"}')
    try:
        assert re.findall(r'data-variant="(\w+)" data-index="(\d)"', site.text("p/index.html")) == [("None", "0"), ("None", "1")]
    finally:
        site.cleanup()


def test_a_card_hook_may_take_only_the_index():
    site = card_page(INDEX_ONLY, '::include{kind="listing" tags="red" layout="bare"}')
    try:
        assert re.findall(r'<li data-index="(\d)">(\w)</li>', site.text("p/index.html")) == [("0", "a"), ("1", "b")]
        assert '<li data-index="0">a</li>' in site.text("posts/index.html")
    finally:
        site.cleanup()


def test_a_card_hook_without_variant_rejects_an_include_that_names_one():
    from procedures.newsroom.tests.standard_frontend_content_support import DirectorySite

    work = DirectorySite(settings(urls=SECTIONS, hooks="hooks.py", pages=[{"id": "p", "path": "p", "title": "P", "source": "p.md"}]), posts(),
                         {"hooks.py": PLAIN_CARD, "p.md": f'{BAND}::include{{kind="listing" card="mini"}}\n'})
    try:
        with pytest.raises(ValueError, match="card='mini': the site's card hook takes no variant"):
            work.project_all()
    finally:
        work.cleanup()
    ok = DirectorySite(settings(urls=SECTIONS, hooks="hooks.py", pages=[{"id": "p", "path": "p", "title": "P", "source": "p.md"}]), posts(),
                       {"hooks.py": PLAIN_CARD, "p.md": f'{BAND}::include{{kind="listing"}}\n'})
    try:
        assert ok.project_all().ok and "<li>a</li>" in ok.text("p/index.html")
    finally:
        ok.cleanup()


# ------------------------------------------------------------------ the guarded environment and the vendor stylesheet

ANALYTICS = {"ga_measurement_id": "G-ABC123DEF4", "consent_mode": {"banner_heading": "Cookies and analytics"}}
STAGING = {"PAPYRUS_SITE_PUBLIC_URL": "https://staging.example.org"}


@pytest.mark.parametrize("chrome", [{"ga_measurement_id": "G-ABC123DEF4"}, ANALYTICS, {**ANALYTICS, "ga_owner_opt_out": True}])
def test_a_guarded_environment_never_emits_google_analytics(chrome):
    production = cms_site(settings(chrome=chrome), [item("a", section=None)])
    guarded = cms_site(settings(chrome=chrome), [item("a", section=None)], environ=STAGING)
    try:
        assert "googletagmanager.com/gtag/js?id=G-ABC123DEF4" in production.text("a.html")
        if "consent_mode" in chrome:
            assert "Cookies and analytics" in production.text("a.html") and "gtag('consent','default'" in production.text("a.html")
        for key in ("a.html", "index.html", "404.html"):
            page = guarded.text(key)
            assert '<meta name="robots" content="noindex, nofollow">' in page
            for marker in ("googletagmanager", "G-ABC123DEF4", "gtag(", "dataLayer", "Cookies and analytics", "consent"):
                assert marker not in page, (key, marker)
    finally:
        production.cleanup()
        guarded.cleanup()


def test_a_guarded_environment_without_analytics_is_unchanged():
    plain = cms_site(settings(), [item("a", section=None)])
    guarded = cms_site(settings(), [item("a", section=None)], environ=STAGING)
    try:
        assert "gtag" not in plain.text("a.html") and "gtag" not in guarded.text("a.html")
    finally:
        plain.cleanup()
        guarded.cleanup()


def test_the_vendor_stylesheet_is_published_by_default_and_when_the_chrome_links_it():
    for chrome in ({}, {"stylesheets": ["css/markus-vendor.css", "css/site-theme.css"]}):
        site = cms_site(settings(chrome=chrome), [item("a", section=None)])
        try:
            assert "css/markus-vendor.css" in site.tree and 'href="/css/markus-vendor.css?v=' in site.text("a.html")
        finally:
            site.cleanup()


def test_the_vendor_stylesheet_is_not_published_when_the_chrome_does_not_link_it():
    site = cms_site(settings(chrome={"stylesheets": ["css/site-theme.css"]}), [item("a", section=None)])
    try:
        assert "css/markus-vendor.css" not in site.tree
        assert "css/site-theme.css" in site.tree and "css/markus-components.css" in site.tree
        assert "markus-vendor" not in site.text("a.html") and 'href="/css/site-theme.css?v=' in site.text("a.html")
    finally:
        site.cleanup()
