"""The notifications plugin's reader pages are projected as real static pages in the site's chrome (docs/notifications.md).

When the plugin is enabled the standard projector writes ``notifications/index.html`` and ``notifications/{confirm,confirmed,preferences,
unsubscribe,unsubscribed,expired}/``: noindex, never listed in the sitemap, llms.txt, feeds or as Markdown twins, with
``Referrer-Policy: same-origin`` as a meta tag and external scripts only. ``/api/notifications/*`` stays for machines.
"""

from __future__ import annotations

import re

import pytest

from papyrus_content.projection.deploy_render import deploy_render
from papyrus_content.projection.engine import reconcile
from papyrus_content.projection.plugins import PLUGIN_PAGE_PREFIXES
from papyrus_content.projection.standard import notifications_pages
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite, fixture_settings

KEYS = {name: notifications_pages.site_key(name) for name in notifications_pages.PAGE_NAMES}
PAGES = "_plugins/papyrus-notifications-pages@1.js"
COMPONENT = "_plugins/papyrus-notifications@1.js"
FORMS = {"/api/notifications/confirm", "/api/notifications/preferences", "/api/notifications/unsubscribe"}


def inline_scripts(html: str) -> list[str]:
    return re.findall(r"<script(?![^>]*\bsrc=)[^>]*>.*?</script>", html, re.S)


@pytest.fixture(scope="module")
def enabled():
    site = ProjectedSite("sectioned", plugins=("notifications",))
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
    site = ProjectedSite(settings=settings, content=FIXTURES / "sectioned" / "content", plugins=("notifications",))
    yield site
    site.cleanup()


def test_the_page_keys_are_the_ones_the_routes_redirect_to():
    assert KEYS["index"] == "notifications/index.html"
    assert KEYS["confirm"] == "notifications/confirm/index.html"
    assert notifications_pages.site_path("index") == "/notifications/"
    assert notifications_pages.site_path("expired") == "/notifications/expired/"
    assert all(key.startswith(PLUGIN_PAGE_PREFIXES["notifications"]) for key in KEYS.values())


def test_every_page_is_projected_through_the_page_template_with_full_chrome(enabled):
    for name, key in KEYS.items():
        html = enabled.text(key)
        assert f'data-notifications-page="{name}"' in html
        assert re.search(r'<main id="main">\s*<div class="markus-document markus-notifications-page"', html), "the content is the main area"
        assert '<link rel="stylesheet" href="/css/site-theme.css' in html and "markus-components.css" in html
        assert "<header" in html and "<footer" in html and '<a class="markus-skip-link"' in html
        assert html.count("<h1>") >= 1


def test_the_pages_are_noindex_same_origin_and_load_only_external_scripts(enabled):
    for name, key in KEYS.items():
        html = enabled.text(key)
        assert '<meta name="robots" content="noindex, nofollow">' in html
        assert '<meta name="referrer" content="same-origin">' in html
        assert len(re.findall(rf'<script src="/{re.escape(PAGES)}(\?v=\w+)?"></script>', html)) == 1
        assert len(re.findall(rf'<script src="/{re.escape(COMPONENT)}(\?v=\w+)?"></script>', html)) == (1 if name == "index" else 0)
        assert inline_scripts(html) == inline_scripts(enabled.text("404.html")), "no inline script beyond the chrome's"
        assert " style=" not in html.split("<body", 1)[1], "no inline style"
        assert "/api/notifications/state" not in html, "the script owns the JSON endpoint"
    assert "papyrus-notifications" not in enabled.text("404.html"), "other pages do not load the scripts"
    assert PAGES in enabled.tree and COMPONENT in enabled.tree


def test_no_page_links_to_an_api_url_but_the_forms_post_to_the_machine_endpoints(enabled):
    for key in KEYS.values():
        html = enabled.text(key)
        assert not re.findall(r'href="[^"]*/api/', html), "people are never linked to /api"
        for action in re.findall(r'<form[^>]*action="([^"]+)"', html):
            assert action in FORMS
        assert "<noscript>" in html or "data-notifications-form" not in html, "a page with a form says it needs JavaScript"


def test_the_subscribe_page_places_the_component_and_says_what_it_is_for(enabled):
    html = enabled.text(KEYS["index"])
    assert html.count("<papyrus-notifications></papyrus-notifications>") == 1
    assert "Get an email from" in html and "Already subscribed?" in html


def test_buttons_not_dropdowns_lucide_icons_and_no_borders(enabled):
    for key in KEYS.values():
        html = enabled.text(key)
        assert "<select" not in html and "<option" not in html
        assert re.findall(r'<button type="submit" class="markus-button markus-notifications-button"', html) or "<form" not in html
        for icon in re.findall(r'data-icon="([a-z0-9-]+)"', html.split("<main", 1)[1]):
            assert icon in {"mail", "circle-check", "bell-off", "save", "trash-2", "triangle-alert", "arrow-left"}
    css = enabled.text("css/markus-components.css")
    rules = [line for line in css.splitlines() if "markus-notifications" in line]
    borders = [value.strip() for line in rules for value in re.findall(r"(?<![\w-])border(?:-(?!radius)[a-z-]+)?\s*:\s*([^;]+)", line)]
    assert rules and set(borders) <= {"0", "none"}, "flat fills only: no border, outline rule or hairline"


def test_forms_are_hidden_until_the_script_fills_the_token(enabled):
    for name in ("confirm", "preferences", "unsubscribe"):
        html = enabled.text(KEYS[name])
        assert all("hidden>" in tag for tag in re.findall(r"<form [^>]*>", html))
        assert 'name="t" value=""' in html


def test_the_pages_are_not_a_thing_anyone_can_find(enabled):
    sitemaps = "".join(enabled.text(key) for key in enabled.tree if key.startswith("sitemap"))
    machine_readable = sitemaps + enabled.text("llms.txt") + enabled.text("llms-full.txt") + enabled.text("feed.xml") + enabled.text("atom.xml")
    assert "notifications" not in machine_readable
    assert not [key for key in enabled.tree if key.startswith("notifications/") and key.endswith(".md")], "no Markdown twin"
    assert "notifications/" not in "".join(enabled.text(key) for key in enabled.tree if key.endswith(".html") and not key.startswith("notifications/"))
    for key in KEYS.values():
        assert "text/markdown" not in enabled.text(key)


def test_a_bad_link_lands_on_the_sites_expired_page_which_points_back_to_the_subscribe_page(enabled):
    html = enabled.text(KEYS["expired"])
    assert "This link did not work" in html
    assert 'href="/notifications/"' in html and "/api/" not in html


def test_a_site_without_the_plugin_has_no_pages_and_no_scripts(plain):
    assert not any(key.startswith("notifications/") for key in plain.tree)
    assert PAGES not in plain.tree and COMPONENT not in plain.tree


def test_a_site_under_a_base_path_links_every_page_under_it(based):
    keys = {key for key in based.tree if "notifications/" in key and key.endswith(".html")}
    assert {f"posts/{key}" for key in KEYS.values()} <= keys or {key for key in KEYS.values()} <= keys, sorted(keys)
    html = based.text(next(key for key in keys if key.endswith("notifications/expired/index.html")))
    assert 'href="/posts/notifications/"' in html and 'data-expired-href="/posts/notifications/expired/"' in html


def test_a_full_projection_writes_the_pages_and_the_post_deploy_render_finds_no_drift(enabled):
    report = deploy_render(enabled.context)
    assert report.ok, report.to_dict()
    assert report.drift_count == 0, report.to_dict()
    assert set(KEYS.values()) <= set(enabled.tree)
    assert reconcile(enabled.context, dry_run=True).orphan_pages == []


def test_the_pages_are_owned_so_disabling_the_plugin_cleans_them_up(enabled, plain):
    assert all(enabled.projector.owns_page_key(key) for key in KEYS.values())
    assert all(plain.projector.owns_page_key(key) for key in KEYS.values()), "a site without the plugin still owns the keys it may have written"
