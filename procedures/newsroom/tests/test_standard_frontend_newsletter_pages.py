"""The newsletter plugin's human pages are projected as real static pages in the site's chrome.

When the plugin is enabled the standard projector writes ``newsletter/{confirm,confirmed,preferences,unsubscribe,unsubscribed,expired}/``:
noindex, never listed in the sitemap, llms.txt, feeds or as Markdown twins, with ``Referrer-Policy: same-origin`` as a meta tag and
one external script. ``/api/newsletter/*`` stays for machines.
"""

from __future__ import annotations

import re

import pytest

from papyrus_content.projection.deploy_render import deploy_render
from papyrus_content.projection.engine import project_all, reconcile
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, fixture_settings

NAMES = ("confirm", "confirmed", "preferences", "unsubscribe", "unsubscribed", "expired")
KEYS = {name: f"newsletter/{name}/index.html" for name in NAMES}
SCRIPT = "_plugins/papyrus-newsletter-pages@1.js"


def inline_scripts(html: str) -> list[str]:
    return re.findall(r"<script(?![^>]*\bsrc=)[^>]*>.*?</script>", html, re.S)


@pytest.fixture(scope="module")
def enabled():
    site = ProjectedSite("sectioned", plugins=("newsletter",))
    yield site
    site.cleanup()


@pytest.fixture(scope="module")
def plain():
    site = ProjectedSite("sectioned")
    yield site
    site.cleanup()


@pytest.fixture(scope="module")
def based():
    settings = fixture_settings("sectioned")
    settings["urls"] = {**settings.get("urls", {}), "basePath": "/posts"}
    settings.pop("images", None)
    settings.pop("media", None)
    site = ProjectedSite(settings=settings, content=FIXTURES / "sectioned" / "content", plugins=("newsletter",))
    yield site
    site.cleanup()


def test_every_page_is_projected_through_the_page_template_with_full_chrome(enabled):
    for name, key in KEYS.items():
        html = enabled.text(key)
        assert f'data-newsletter-page="{name}"' in html
        assert re.search(r'<main id="main">\s*<div class="markus-document markus-newsletter-page"', html), "the content is the main area"
        assert '<link rel="stylesheet" href="/css/site-theme.css' in html and "markus-components.css" in html
        assert "<header" in html and "<footer" in html and '<a class="markus-skip-link"' in html
        assert html.count("<h1>") >= 1


def test_the_pages_are_noindex_same_origin_and_load_one_external_script(enabled):
    for key in KEYS.values():
        html = enabled.text(key)
        assert '<meta name="robots" content="noindex, nofollow">' in html
        assert '<meta name="referrer" content="same-origin">' in html
        assert len(re.findall(rf'<script src="/{re.escape(SCRIPT)}(\?v=\w+)?"></script>', html)) == 1
        assert inline_scripts(html) == inline_scripts(enabled.text("index.html")), "the pages add no inline script to the chrome's"
        assert " style=" not in html.split("<body", 1)[1], "no inline style"
        assert "/api/newsletter/state" not in html, "the script owns the JSON endpoint"
    assert "papyrus-newsletter-pages" not in enabled.text("index.html"), "other pages do not load it"
    assert SCRIPT in enabled.tree


def test_no_page_links_to_an_api_url_but_the_forms_post_to_the_machine_endpoints(enabled):
    for key in KEYS.values():
        html = enabled.text(key)
        assert not re.findall(r'href="[^"]*/api/', html), "people are never linked to /api"
        for action in re.findall(r'<form[^>]*action="([^"]+)"', html):
            assert action in ("/api/newsletter/confirm", "/api/newsletter/preferences", "/api/newsletter/unsubscribe")
        assert "<noscript>" in html or "data-newsletter-form" not in html, "a page with a form says it needs JavaScript"


def test_forms_are_hidden_until_the_script_fills_the_token(enabled):
    for name in ("confirm", "preferences", "unsubscribe"):
        html = enabled.text(KEYS[name])
        assert all("hidden>" in tag for tag in re.findall(r"<form [^>]*>", html))
        assert 'name="t" value=""' in html


def test_the_pages_are_not_a_thing_anyone_can_find(enabled):
    sitemaps = "".join(enabled.text(key) for key in enabled.tree if key.startswith("sitemap"))
    machine_readable = sitemaps + enabled.text("llms.txt") + enabled.text("llms-full.txt") + enabled.text("feed.xml") + enabled.text("atom.xml")
    assert "newsletter" not in machine_readable
    assert not [key for key in enabled.tree if key.startswith("newsletter/") and key.endswith(".md")], "no Markdown twin"
    assert "newsletter/" not in "".join(enabled.text(key) for key in enabled.tree if key.endswith(".html") and not key.startswith("newsletter/"))
    for key in KEYS.values():
        assert "text/markdown" not in enabled.text(key)


def test_a_site_without_the_plugin_has_no_pages_and_no_script(plain):
    assert not any(key.startswith("newsletter/") for key in plain.tree)
    assert SCRIPT not in plain.tree


def test_a_full_projection_writes_the_pages_and_the_post_deploy_render_finds_no_drift(enabled):
    report = deploy_render(enabled.context)
    assert report.ok, report.to_dict()
    assert report.drift_count == 0, report.to_dict()
    assert set(KEYS.values()) <= set(enabled.tree)
    assert reconcile(enabled.context, dry_run=True).orphan_pages == []


def test_the_pages_are_owned_so_disabling_the_plugin_cleans_them_up(enabled, plain):
    assert all(enabled.projector.owns_page_key(key) for key in KEYS.values())
    assert all(plain.projector.owns_page_key(key) for key in KEYS.values()), "a site without the plugin still owns the keys it may have written"


def test_the_legacy_shell_is_owned_so_the_reconcile_removes_it(plain):
    assert plain.projector.owns_page_key("_plugins/newsletter-shell/index.html")


def test_the_digest_is_stable_between_runs(enabled):
    before = {key: enabled.digests()[key] for key in KEYS.values()}
    assert project_all(enabled.context).ok
    assert {key: enabled.digests()[key] for key in KEYS.values()} == before


def test_paths_follow_the_base_path(based):
    tree = set(based.tree)
    assert {f"posts/newsletter/{name}/index.html" for name in NAMES} <= tree
    assert "posts/_plugins/papyrus-newsletter-pages@1.js" in tree
    assert not any(key.startswith("newsletter/") for key in tree)
    html = based.text("posts/newsletter/confirm/index.html")
    assert 'data-expired-href="/posts/newsletter/expired/"' in html
    assert 'data-preferences-href="/posts/newsletter/preferences/"' in html
    assert re.search(r'<script src="/posts/_plugins/papyrus-newsletter-pages@1.js(\?v=\w+)?"></script>', html)
    assert 'href="/posts/"' in based.text("posts/newsletter/confirmed/index.html"), "the way back is the site's home under the base path"
    assert "newsletter" not in based.text("posts/sitemap-0.xml")
