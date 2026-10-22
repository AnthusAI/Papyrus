"""The newsletter plugin's pages are drawn inside the site's own chrome.

When the plugin is enabled the standard projector writes one noindex page, ``_plugins/newsletter-shell/index.html``: the
site's full page template with a single marker in the main area. The CMS routes fetch it and put the page content there.
"""

from __future__ import annotations

import re

import pytest

from papyrus_content.projection.deploy_render import deploy_render
from papyrus_content.projection.engine import project_all, reconcile
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite

SHELL = "_plugins/newsletter-shell/index.html"
MARKER = "<!--papyrus:newsletter-content-->"


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


def test_a_site_with_the_plugin_projects_a_shell_with_the_full_chrome_and_one_marker(enabled):
    html = enabled.text(SHELL)
    assert html.count(MARKER) == 1
    assert re.search(r'<main id="main">\s*' + re.escape(MARKER) + r"\s*</main>", html), "the marker is the whole main area"
    assert '<link rel="stylesheet" href="/css/site-theme.css' in html and "markus-components.css" in html
    assert "<header" in html and "<footer" in html and '<a class="markus-skip-link"' in html
    assert '<meta name="robots" content="noindex, nofollow">' in html


def test_the_shell_is_not_a_page_anyone_can_find(enabled):
    assert not any("newsletter-shell" in enabled.text(key) for key in enabled.tree if key.startswith("sitemap"))
    assert "newsletter-shell" not in enabled.text("llms.txt") and "newsletter-shell" not in enabled.text("llms-full.txt")
    for feed in ("feed.xml", "atom.xml"):
        assert "newsletter-shell" not in enabled.text(feed)
    assert not [key for key in enabled.tree if "newsletter-shell" in key and key != SHELL], "no Markdown twin or other file"
    assert "newsletter-shell" not in "".join(enabled.text(key) for key in enabled.tree if key.endswith(".html") and key != SHELL)


def test_a_site_without_the_plugin_has_no_shell(plain):
    assert SHELL not in plain.tree
    assert not any("newsletter-shell" in key for key in plain.tree)


def test_a_full_projection_writes_the_shell_and_the_post_deploy_render_finds_no_drift(enabled):
    assert SHELL in enabled.tree
    report = deploy_render(enabled.context)
    assert report.ok, report.to_dict()
    assert report.drift_count == 0, report.to_dict()
    assert SHELL in enabled.tree
    assert reconcile(enabled.context, dry_run=True).orphan_pages == []


def test_the_shell_is_an_owned_page_so_disabling_the_plugin_cleans_it_up(enabled, plain):
    assert enabled.projector.owns_page_key(SHELL)
    assert not plain.projector.owns_page_key(SHELL)


def test_the_shell_digest_is_stable_between_runs(enabled):
    before = enabled.digests()[SHELL]
    assert project_all(enabled.context).ok
    assert enabled.digests()[SHELL] == before
