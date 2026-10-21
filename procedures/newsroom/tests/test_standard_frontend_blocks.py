"""Page blocks, islands, header brand and groups, and the family footer of the standard front end.

Blocks come from a content directory (``project --all --from-dir``): the CMS save path validates bodies with Markus,
which does not know ``::band``.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from papyrus_content.projection.directory_source import DirectoryContentSource
from papyrus_content.projection.engine import ProjectionContext, project, project_all
from papyrus_content.projection.standard import blocks
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.family import REGISTRY, brand_links, platform_links
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from papyrus_content.projection.writers import LocalDirectoryWriter
from procedures.newsroom.tests.projection_fixtures import tree_digests
from procedures.newsroom.tests.standard_frontend_support import static_directory

HOME = """---
title: Home
---
::band{id="top" tone="card" size="hero" eyebrow="Open source" columns="home"}
# Price {{price}}

Plain *text*.

::button{href="/start/" label="Start" size="lg"}

::button{href="https://example.org/" label="Source" variant="secondary"}

::column{panel="card"}
::island{name="Chart" height="20rem" kind="bar" note="it's <b>"}

::band{tone="muted"}
Second band.

::band{size="bare"}
::island{name="Bare"}
"""
PLAIN = "---\ntitle: About\ntype: page\n---\nJust Markus.\n"


class Site:
    """A content directory projected with the standard front end into a local directory."""

    def __init__(self, settings: dict, files: dict[str, str], extra_static: dict[str, str] | None = None) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="blocks-"))
        self.content = self.work / "content"
        for name, text in files.items():
            (self.content / name).parent.mkdir(parents=True, exist_ok=True)
            (self.content / name).write_text(text, encoding="utf-8")
        self.static = static_directory(self.work, settings, extra_static)
        self.out = self.work / "out"

    def context(self, out: Path | None = None) -> ProjectionContext:
        projector = StandardMarkusProjector.from_static_directory(self.static, environ={"PAPYRUS_SITE_PUBLIC_URL": ""})
        return ProjectionContext(source=DirectoryContentSource(self.content), projector=projector, writer=LocalDirectoryWriter(out or self.out))

    def project_all(self, out: Path | None = None):
        return project_all(self.context(out))

    def text(self, key: str) -> str:
        return (self.out / key).read_text(encoding="utf-8")

    def cleanup(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)


ISLANDS = {"islands": {"script": "assets/islands.js", "stylesheet": "css/islands.css"}}
ISLAND_FILES = {"assets/islands.js": "window.papyrusIslands = {};\n", "css/islands.css": ".papyrus-island{}\n"}


def settings(**extra) -> dict:
    return {"site": {"name": "Example", "productionUrl": "https://example.org"}, "values": {"price": "$5", "count": 3}, **extra}


@pytest.fixture()
def blocked():
    site = Site(settings(**ISLANDS), {"index.md": HOME, "about.md": PLAIN}, ISLAND_FILES)
    report = site.project_all()
    assert report.ok, report.errors
    yield site
    site.cleanup()


# ------------------------------------------------------------------ page blocks

def test_a_band_page_renders_the_documented_markup(blocked):
    page = blocked.text("index.html")
    assert (
        '<section class="markus-band" id="top" data-tone="card" data-size="hero" data-layout="home"><div class="markus-band-inner">'
        '<p class="markus-band-eyebrow">Open source</p><div class="markus-columns" data-count="2"><div class="markus-column">'
    ) in page
    assert '<h1 id="price-5">Price $5</h1>' in page and "<p>Plain <em>text</em>.</p>" in page
    assert (
        '<p class="markus-actions"><a class="markus-button" data-size="lg" data-variant="default" href="/start/">Start</a>'
        '<a class="markus-button" data-size="default" data-variant="secondary" href="https://example.org/">Source</a></p>'
    ) in page
    assert '<div class="markus-column" data-panel="card"><div class="papyrus-island" data-island="Chart"' in page
    assert '<section class="markus-band" data-tone="muted" data-size="standard"><div class="markus-band-inner"><div class="markus-columns" data-count="1">' in page
    assert "<article" not in page.split("<main")[1].split("</main>")[0]


def test_a_bare_band_emits_only_its_contents(blocked):
    page = blocked.text("index.html")
    assert '</section>\n<div class="papyrus-island" data-island="Bare" data-props=\'{}\'></div>\n  </main>' in page


def test_island_attributes_become_escaped_json_props(blocked):
    page = blocked.text("index.html")
    marker = 'data-island="Chart" style="min-height:20rem" data-props=\''
    props = page.split(marker)[1].split("'></div>")[0]
    assert "<" not in props and "'" not in props
    import html

    assert json.loads(html.unescape(props)) == {"kind": "bar", "note": "it's <b>"}


def test_a_file_without_bands_is_untouched_by_the_block_pass(blocked):
    page = blocked.text("about.html")
    assert "markus-band" not in page and "papyrus-island" not in page and "<p>Just Markus.</p>" in page


def test_unsafe_button_hrefs_and_bad_choices_are_errors():
    for bad in ('javascript:alert(1)', "//evil.example/", "relative/path"):
        with pytest.raises(ValueError, match="href"):
            blocks.render(f'::band\n::button{{href="{bad}" label="x"}}\n', "f.md", lambda text: text)
    for line, message in (
        ('::band{tone="loud"}', "band tone"),
        ('::band{size="huge"}', "band size"),
        ('::band\n::button{href="/" label="x" size="xl"}', "button size"),
        ('::band{colour="red"}', "unknown attributes"),
        ('::band\n::column{panel="wide"}', "column panel"),
        ('::band\n::island{height="1rem"}', "needs a name"),
        ('::band\n::island{name="X" height="tall"}', "height"),
    ):
        with pytest.raises(ValueError, match=message):
            blocks.render(line + "\n", "f.md", lambda text: text)


def test_button_labels_and_attributes_are_escaped():
    html = blocks.render('::band\n::button{href="/a?x=1&y=2" label="<b>Go</b>"}\n', "f.md", lambda text: text)
    assert 'href="/a?x=1&amp;y=2">&lt;b&gt;Go&lt;/b&gt;</a>' in html


def test_content_before_the_first_band_is_an_error():
    with pytest.raises(ValueError, match="f.md: content before the first ::band"):
        blocks.render("Intro\n::band\nText\n", "f.md", lambda text: text)
    with pytest.raises(ValueError, match="content before the first ::band"):
        blocks.render("::column\n::band\n", "f.md", lambda text: text)


def test_directives_inside_code_fences_are_text():
    assert not blocks.uses_bands("```\n::band\n```\n")
    assert blocks.uses_bands("```\ncode\n```\n::band\n")


def test_an_unknown_token_is_a_build_error_naming_the_file_and_the_token():
    site = Site(settings(), {"index.md": "---\ntitle: Home\n---\n::band\nCost {{prcie}}\n"})
    try:
        with pytest.raises(ValueError, match=r"index\.md: no value named \{\{prcie\}\}"):
            site.project_all()
    finally:
        site.cleanup()


def test_tokens_are_left_alone_when_the_site_defines_no_values():
    assert blocks.substitute("{{anything}} and {{ section listing }}", {}, "f.md") == "{{anything}} and {{ section listing }}"
    assert blocks.substitute("{{ section listing }}", {"a": "b"}, "f.md") == "{{ section listing }}"


def test_values_must_be_strings_or_numbers():
    assert dict(standard_settings_from_mapping(settings()).values) == {"price": "$5", "count": "3"}
    for bad in ({"a": True}, {"a": [1]}, {"a b": "x"}):
        with pytest.raises(ValueError, match="values"):
            standard_settings_from_mapping(settings(values=bad))


def test_values_are_part_of_the_shared_fingerprint():
    def fingerprint(values):
        return StandardMarkusProjector(
            __import__("papyrus_content.projection.projector", fromlist=["x"]).MarkusProjectorSettings(theme=None), {},
            standard_settings_from_mapping(settings(values=values)),
        )._shared_fingerprint

    assert fingerprint({"price": "$5"}) != fingerprint({"price": "$6"})


def test_the_markdown_twin_drops_markers_turns_buttons_into_links_and_omits_islands(blocked):
    twin = blocked.text("index.md")
    assert "::" not in twin and "papyrus-island" not in twin and "Chart" not in twin
    assert "# Price $5" in twin and "[Start](/start/) · [Source](https://example.org/)" in twin and "Second band." in twin
    assert "Open source" not in twin
    assert "::" not in blocked.text("llms-full.txt")


# ------------------------------------------------------------------ islands

def test_the_island_script_loads_on_island_pages_only(blocked):
    home, about = blocked.text("index.html"), blocked.text("about.html")
    assert re.search(r'<script type="module" src="/assets/islands\.js\?v=[0-9a-f]+"></script>\n</body>', home)
    assert re.search(r'<script src="/_plugins/papyrus-islands-v1\.js\?v=[0-9a-f]+"></script>', home)
    assert home.index("papyrus-islands-v1.js") > home.index("</footer>")
    assert "islands.js" not in about and "papyrus-islands" not in about
    assert '/css/islands.css?v=' in home and '/css/islands.css?v=' in about    # the stylesheet is on every page


def test_the_runtime_ships_and_follows_the_contract(blocked):
    runtime = blocked.text("_plugins/papyrus-islands-v1.js")
    for needle in ("DOMContentLoaded", "[data-island]", "window.papyrusIslands", "console.warn", "data-props"):
        assert needle in runtime
    assert blocked.text("assets/islands.js").startswith("window.papyrusIslands")


def test_a_hook_that_emits_an_island_gets_the_script(tmp_path):
    hooks = 'def page_body(page):\n    return \'<main id="main"><div class="papyrus-island" data-island="Hooked"></div></main>\' if page.kind == "home" else None\n'
    site = Site(settings(hooks="hooks.py", **ISLANDS), {"index.md": PLAIN}, {**ISLAND_FILES, "hooks.py": hooks})
    try:
        assert site.project_all().ok
        assert "islands.js" in site.text("index.html")
        assert "islands.js" not in site.text("404.html")
    finally:
        site.cleanup()


def test_islands_configuration_is_checked():
    with pytest.raises(ValueError, match="islands.script is required"):
        standard_settings_from_mapping(settings(islands={}))
    with pytest.raises(ValueError, match="Unknown islands settings"):
        standard_settings_from_mapping(settings(islands={"script": "a.js", "bundle": "b"}))
    site = Site(settings(islands={"script": "assets/missing.js"}), {"index.md": PLAIN})
    try:
        with pytest.raises(ValueError, match="assets/missing.js"):
            site.context()
    finally:
        site.cleanup()


def test_a_site_without_islands_never_gets_the_runtime():
    site = Site({"site": {"name": "Example"}}, {"index.md": PLAIN})
    try:
        assert site.project_all().ok
        assert not (site.out / "_plugins" / "papyrus-islands-v1.js").exists()
    finally:
        site.cleanup()


# ------------------------------------------------------------------ incremental equals full

def test_incremental_projection_equals_project_all_for_a_site_using_blocks():
    site = Site(settings(**ISLANDS), {"index.md": HOME, "about.md": PLAIN, "more.md": "---\ntitle: More\ntype: page\n---\n::band\nMore text.\n"}, ISLAND_FILES)
    try:
        assert site.project_all().ok
        edits = [
            ("index.md", HOME.replace("Second band.", "Second band, edited.")),
            ("more.md", "---\ntitle: More\ntype: page\n---\n::band{tone=\"card\"}\nPrice {{price}}\n\n::island{name=\"Late\"}\n"),
            ("about.md", PLAIN.replace("Just Markus.", "Just Markus, edited.")),
        ]
        for name, text in edits:
            (site.content / name).write_text(text, encoding="utf-8")
            assert project(site.context(), f"file:{name}").ok
            fresh = site.work / f"fresh-{name}"
            assert site.project_all(fresh).ok
            # llms-full.txt is keyed on item versions, which a content directory does not have (every item is version 1).
            incremental, full = tree_digests(site.out), tree_digests(fresh)
            incremental.pop("llms-full.txt"), full.pop("llms-full.txt")
            assert incremental == full, name
        assert "Late" in site.text("more.html") and "islands.js" in site.text("more.html")
    finally:
        site.cleanup()


# ------------------------------------------------------------------ header

def nav_settings(**nav) -> dict:
    return {"site": {"name": "Example Site"}, "nav": nav}


def project_home(raw: dict) -> str:
    site = Site(raw, {"index.md": PLAIN.replace("type: page\n", "")})
    try:
        assert site.project_all().ok
        return site.text("index.html")
    finally:
        site.cleanup()


def test_brand_html_goes_inside_the_wordmark_link_which_keeps_its_label():
    page = project_home(nav_settings(brandHtml='<svg role="img"></svg><span>Example</span>'))
    assert '<p class="markus-site-wordmark"><a href="/" aria-label="Example Site, home"><svg role="img"></svg><span>Example</span></a></p>' in page


def test_without_brand_html_the_wordmark_is_the_plain_name():
    assert '<p class="markus-site-wordmark"><a href="/">Example Site</a></p>' in project_home(nav_settings(links=[{"label": "A", "href": "/a/"}]))


def test_nav_links_can_be_external_and_can_group_children():
    page = project_home(nav_settings(links=[
        {"label": "Docs", "href": "https://docs.example.org/", "external": True},
        {"label": "More", "children": [{"label": "One", "href": "/one/"}, {"label": "Two", "href": "https://two.example.org/", "external": True}]},
        {"label": "Plain", "href": "/plain/", "cta": True},
    ]))
    assert '<a href="https://docs.example.org/" rel="noopener">Docs</a>' in page
    assert (
        '<details class="markus-nav-group"><summary>More</summary><div class="markus-nav-group-links">'
        '<a href="/one/">One</a><a href="https://two.example.org/" rel="noopener">Two</a></div></details>'
    ) in page
    assert '<a class="markus-nav-cta" href="/plain/">Plain</a>' in page


def test_nav_group_configuration_is_checked():
    with pytest.raises(ValueError, match="takes no href"):
        standard_settings_from_mapping(nav_settings(links=[{"label": "G", "href": "/g/", "children": [{"label": "A", "href": "/a/"}]}]))
    with pytest.raises(ValueError, match="Unknown nav.links.children settings"):
        standard_settings_from_mapping(nav_settings(links=[{"label": "G", "children": [{"label": "A", "href": "/a/", "children": []}]}]))
    with pytest.raises(ValueError, match="need label and href"):
        standard_settings_from_mapping(nav_settings(links=[{"label": "G"}]))


# ------------------------------------------------------------------ family footer

def family_page(**footer) -> str:
    return project_home({"site": {"name": "Example Site"}, "footer": footer})


def test_the_family_footer_has_the_packages_three_parts():
    page = family_page(
        text="The text fallback.",
        family={"siteId": "tactus", "byline": "Designed by us"},
        columns=[{"title": "Resources", "links": [{"label": "Docs", "href": "/docs/"}, {"label": "Repo", "href": "https://example.org/r", "external": True}]}],
    )
    footer = page.split('<footer class="markus-site-footer">')[1].split("</footer>")[0]
    local, rest = footer.split('<div class="papyrus-family-footer-band">')
    band, community = rest.split('<div class="papyrus-family-footer-community">')
    assert '<h2 class="papyrus-family-footer-title">Tactus</h2><p class="papyrus-family-footer-description">The text fallback.</p>' in local
    assert "papyrus-family-footer-eyebrow" not in local
    assert '<h3 class="papyrus-family-footer-column-title">Resources</h3>' in local
    assert '<li><a href="/docs/">Docs</a></li><li><a href="https://example.org/r" rel="noopener">Repo</a></li>' in local
    assert '<span class="papyrus-family-footer-eyebrow">Made by</span><h2 class="papyrus-family-footer-title"><a href="https://anth.us/">Anthus AI Solutions</a></h2>' in band
    assert re.findall(r'<h3 class="papyrus-family-footer-column-title">([^<]+)</h3>', band) == ["Products", "Open source we use", "Research"]
    assert '<div class="papyrus-family-footer-bottom"><a href="https://anth.us/">Designed by us</a></div>' in band
    assert re.findall(r'<a href="[^"]+" target="_blank" rel="noreferrer">([^<]+)</a><p>([^<]+)</p>', community) == [
        ("Contact us", "Tell us what you need."), ("GitHub", "Browse the code."), ("LinkedIn", "Company updates."),
    ]


def test_the_family_footer_lists_the_registry_in_the_packages_order_and_only_live_shown_sites():
    page = family_page(family={})
    names = re.findall(r'<div class="papyrus-family-footer-item"><a href="[^"]+">([^<]+)</a>', page)
    assert names == [
        "Cyclotron", "Chatticus", "Papyrus", "Auritus", "Tactus", "Kanbus", "Biblicus", "Markus", "Hard Decisions", "Biased Decisions",
    ]
    for hidden in ("Primus", "Korporus", "Babulus", "Caducus", "Virtuus"):
        assert hidden not in page
    assert "Durable runtime for agent procedures." in page
    assert '<h2 class="papyrus-family-footer-title">Example Site</h2>' in page and "powerful, AI-native solutions" in page
    assert "© Anthus AI Solutions" in page


def test_the_company_site_gets_the_anthus_column_and_no_made_by():
    page = family_page(family={"siteId": "anthus"})
    assert '<h3 class="papyrus-family-footer-column-title">Anthus</h3>' in page and "Made by" not in page


def test_registry_filtering_matches_status_and_visibility():
    sites = REGISTRY["sites"]
    assert not sites["virtuus"]["showInFooter"] and sites["virtuus"]["status"] != "live"
    assert all(sites[key]["status"] == "live" and sites[key]["showInFooter"] for key in ("cyclotron", "chatticus", "papyrus", "auritus"))
    assert not sites["primus"]["showInFooter"]
    live = [label for label, _href in platform_links()]
    assert live == [sites[key]["label"] for key in REGISTRY["platformSiteIds"] if sites[key]["href"] and sites[key]["showInFooter"] and sites[key]["status"] == "live"]
    assert all(href.startswith("https://") for _label, href in brand_links() + platform_links())
    assert "anthus-footer" in REGISTRY["_comment"]


def test_a_footer_hook_wins_over_the_family_footer():
    site = Site(
        {"site": {"name": "Example"}, "hooks": "hooks.py", "footer": {"family": {"siteId": "tactus"}}},
        {"index.md": PLAIN},
        {"hooks.py": 'def footer(page):\n    return "<p>Hooked footer</p>"\n'},
    )
    try:
        assert site.project_all().ok
        page = site.text("index.html")
        assert "Hooked footer" in page and "papyrus-family-footer" not in page
    finally:
        site.cleanup()


def test_family_footer_configuration_is_checked():
    with pytest.raises(ValueError, match="Unknown footer.family settings"):
        standard_settings_from_mapping({"site": {"name": "X"}, "footer": {"family": {"colour": "red"}}})


# ------------------------------------------------------------------ opt-in: a site using none of it

def test_a_site_using_none_of_it_has_none_of_its_markup_or_files():
    site = Site({"site": {"name": "Example"}, "nav": {"links": [{"label": "A", "href": "/a/"}]}, "footer": {"text": "Plain footer"}}, {"index.md": PLAIN.replace("type: page\n", "")})
    try:
        assert site.project_all().ok
        page = site.text("index.html")
        for marker in ("markus-band", "papyrus-island", "papyrus-family", "markus-nav-group", "islands", "aria-label=\"Example, home\""):
            assert marker not in page
        assert '<p class="markus-site-wordmark"><a href="/">Example</a></p>' in page
        assert '<p class="markus-footer-text">Plain footer</p>' in page
        assert not (site.out / "_plugins" / "papyrus-islands-v1.js").exists()
    finally:
        site.cleanup()


def test_a_longer_code_fence_can_hold_shorter_ones():
    text = "::band\n````lua\n```nested```\n::band\n````\n\n::band{tone=\"muted\"}\nAfter.\n"
    names = [name for _line, name, _attributes in blocks._directives(text) if name]
    assert names == ["band", "band"]
    html = blocks.render(text, "f.md", lambda markdown: f"<md>{markdown}</md>")
    assert html.count("<section") == 2 and "::band" in html.split("</section>")[0]
