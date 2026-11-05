"""PPY-30e656: with ``pageActions.everywhere`` the shared page actions are on every page that has a Markdown twin.

A site that does not set it projects exactly the bytes it projected before (``test_section_fronts_off_by_default.py`` holds
the digests of the standard fixtures; this file adds the case with page actions on and the option off).
"""

from __future__ import annotations

import re

import pytest

from procedures.newsroom.tests.reference_list_support import SITE_DIRECTORY, SNAPSHOT_KEY, settings as reference_settings, snapshot, snapshot_bytes
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite, fixture_settings

ICONS = {"display": "icons", "actions": ["view", "copy", "x", "reddit", "share"]}
ACTIONS = re.compile(r'data-papyrus-page-actions data-markdown="([^"]*)" data-title="([^"]*)" data-canonical="([^"]*)"')


def sectioned(page_actions: dict | None, **more) -> ProjectedSite:
    found = fixture_settings("sectioned")
    if page_actions is not None:
        found["pageActions"] = page_actions
    found["collections"] = [{"id": "rivers", "base": "rivers", "label": "River writing", "select": {"tags": ["Rivers"]}}]
    found.update(more)
    return ProjectedSite("sectioned", settings=found)


def actions_of(site: ProjectedSite, key: str):
    found = ACTIONS.findall(site.text(key))
    assert len(found) <= 1, f"{key} places the actions {len(found)} times"
    return found[0] if found else None


@pytest.fixture(scope="module")
def everywhere():
    site = sectioned({**ICONS, "everywhere": True})
    yield site
    site.cleanup()


@pytest.fixture(scope="module")
def default():
    site = sectioned(ICONS)
    yield site
    site.cleanup()


@pytest.mark.parametrize(
    ("key", "markdown", "title", "canonical"),
    [
        ("index.html", "/index.md", "Example Ledger", "https://ledger.example.org/"),
        ("essays/index.html", "/essays/index.md", "Essays", "https://ledger.example.org/essays/"),
        ("essays/page/2/index.html", "/essays/page/2/index.md", "Essays — page 2", "https://ledger.example.org/essays/page/2/"),
        ("rivers/index.html", "/rivers/index.md", "River writing", "https://ledger.example.org/rivers/"),
        ("tags/index.html", "/tags/index.md", "Tags", "https://ledger.example.org/tags/"),
        ("tags/rivers/index.html", "/tags/rivers/index.md", "Tagged Rivers", "https://ledger.example.org/tags/rivers/"),
        ("about/index.html", "/about/index.md", "About the Ledger", "https://ledger.example.org/about/"),
        ("colophon/index.html", "/colophon/index.md", "Colophon", "https://ledger.example.org/colophon/"),
    ],
)
def test_every_page_with_a_twin_carries_its_own_title_address_and_twin(everywhere, key, markdown, title, canonical):
    assert actions_of(everywhere, key) == (markdown, title, canonical)
    assert markdown.lstrip("/") in everywhere.tree, "the actions point at a twin that exists"
    assert "_plugins/papyrus-page-actions-v1.js" in everywhere.text(key)


def test_the_twin_of_every_page_with_actions_exists_and_the_404_has_none(everywhere):
    for key in everywhere.tree:
        if key.endswith(".html") and key != "404.html":
            found = actions_of(everywhere, key)
            assert found is not None, key
            assert found[0].lstrip("/") in everywhere.tree, (key, found)
    assert actions_of(everywhere, "404.html") is None


def test_listing_actions_come_first_in_the_header_by_default(everywhere):
    body = everywhere.text("essays/index.html")
    assert body.index("data-papyrus-page-actions") < body.index("<h1")


def test_aside_placement_puts_them_after_the_listing():
    site = sectioned({**ICONS, "everywhere": True, "placement": "aside"})
    try:
        body = site.text("essays/index.html")
        assert body.index("data-papyrus-page-actions") > body.index("markus-card-grid")
    finally:
        site.cleanup()


def test_without_the_option_only_the_pages_that_always_had_actions_carry_them(default):
    assert actions_of(default, "essays/fords/index.html") is not None
    for key in ("index.html", "essays/index.html", "essays/page/2/index.html", "rivers/index.html", "tags/index.html", "tags/rivers/index.html", "about/index.html", "colophon/index.html"):
        assert actions_of(default, key) is None, key
        assert "papyrus-page-actions-v1.js" not in default.text(key), key


def test_a_page_that_is_noindex_gets_none():
    site = sectioned({**ICONS, "everywhere": True}, pages=[{"id": "colophon", "path": "colophon", "title": "Colophon", "noindex": True, "dependsOn": []}])
    try:
        assert actions_of(site, "colophon/index.html") is None
        assert "colophon/index.md" not in site.tree
    finally:
        site.cleanup()


def test_a_site_without_markdown_twins_gets_none():
    site = sectioned({**ICONS, "everywhere": True}, agents={"markdown": False, "llmsTxt": False, "llmsFull": False})
    try:
        assert not any(key.endswith(".md") for key in site.tree)
        assert all(actions_of(site, key) is None for key in site.tree if key.endswith(".html"))
    finally:
        site.cleanup()


def test_the_option_can_be_switched_off_with_the_actions_off():
    site = sectioned({**ICONS, "everywhere": True, "enabled": False})
    try:
        assert all(actions_of(site, key) is None for key in site.tree if key.endswith(".html"))
    finally:
        site.cleanup()


def test_the_option_must_be_a_known_key_and_defaults_off():
    from papyrus_content.projection.standard.config import PageActionSettings

    assert PageActionSettings().everywhere is False
    with pytest.raises(ValueError):
        sectioned({"everyWhere": True})


def test_a_hook_that_composes_the_main_places_the_actions_itself_once():
    hook = "def main(page):\n    if page.kind == 'item':\n        return None\n    return '<section id=\"own\">' + page.article_actions() + '</section>'\n"
    found = fixture_settings("sectioned")
    found["pageActions"] = {**ICONS, "everywhere": True}
    found["hooks"] = "hooks.py"
    site = ProjectedSite("sectioned", settings=found, extra_files={"hooks.py": hook})
    try:
        for key in ("index.html", "essays/index.html", "tags/rivers/index.html"):
            assert actions_of(site, key) is not None, key
            assert '<section id="own"><div class="markus-page-actions' in site.text(key), key
    finally:
        site.cleanup()


def test_article_actions_is_empty_on_those_pages_without_the_option():
    hook = "def main(page):\n    if page.kind == 'item':\n        return None\n    return '<section id=\"own\">[' + page.article_actions() + ']</section>'\n"
    found = fixture_settings("sectioned")
    found["pageActions"] = ICONS
    found["hooks"] = "hooks.py"
    site = ProjectedSite("sectioned", settings=found, extra_files={"hooks.py": hook})
    try:
        assert '<section id="own">[]</section>' in site.text("essays/index.html")
    finally:
        site.cleanup()


def test_a_section_front_page_and_the_home_of_sections_carry_their_actions():
    from procedures.newsroom.tests.test_section_fronts import fronts_site

    found = fixture_settings("sectioned-fronts")
    found["pageActions"] = {**ICONS, "everywhere": True}
    site = fronts_site(found)
    try:
        assert actions_of(site, "essays/index.html") == ("/essays/index.md", "Essays", "https://ledger.example.org/essays/")   # a generated front page
        assert actions_of(site, "notes/index.html")[0] == "/notes/index.md"                                                   # a front page authored as a file
        assert actions_of(site, "index.html") == ("/index.md", "Example Ledger", "https://ledger.example.org/")               # the home of sections
        for key in ("essays/index.html", "notes/index.html", "index.html"):
            assert site.text(key).count("data-papyrus-page-actions") == 1, key
    finally:
        site.cleanup()


def test_a_paged_reference_list_page_has_its_own_title_and_twin():
    found = reference_settings(page_size=12)
    found["pageActions"] = {**ICONS, "everywhere": True}
    from procedures.newsroom.tests.reference_list_support import PAGE

    site = ProjectedSite(
        settings=found, content=SITE_DIRECTORY / "content",
        extra_files={"pages/wire.md": (PAGE % {"first": 6}).encode("utf-8")},
        seed={SNAPSHOT_KEY: snapshot_bytes(snapshot(30, 30))},
    )
    try:
        chunk_pages = [key for key in site.tree if key.startswith("reference-lists/") and key.endswith(".html")]
        assert chunk_pages, sorted(site.tree)
        for key in chunk_pages:
            markdown, title, canonical = actions_of(site, key)
            assert title.endswith(": more References"), title
            assert markdown == "/" + key.replace(".html", ".md") and markdown.lstrip("/") in site.tree
            assert canonical == "https://almanac.example.org/" + key.removesuffix("index.html")
        assert actions_of(site, "wire/index.html") == ("/wire/index.md", "The wire", "https://almanac.example.org/wire/")
    finally:
        site.cleanup()


def test_an_article_page_is_byte_identical_with_and_without_the_option_and_the_listing_is_not():
    before, after = sectioned(ICONS), sectioned({**ICONS, "everywhere": True})
    try:
        digests_before, digests_after = before.digests(), after.digests()
        assert digests_before["essays/fords/index.html"] == digests_after["essays/fords/index.html"]
        assert digests_before["essays/index.html"] != digests_after["essays/index.html"]
    finally:
        before.cleanup()
        after.cleanup()


def test_an_archive_page_and_the_showcase_page_carry_their_actions():
    found = fixture_settings("sectioned")
    found["pageActions"] = {**ICONS, "everywhere": True}
    found["urls"]["sections"]["essays"]["archive"] = {"by": "month"}
    site = ProjectedSite("sectioned", settings=found)
    try:
        archives = [key for key in site.tree if key.startswith("essays/archive/") and key.endswith("/index.html")]
        assert archives, sorted(site.tree)
        for key in archives:
            markdown, title, canonical = actions_of(site, key)
            assert title.startswith("Essays: ") and markdown == "/" + key.replace(".html", ".md") and canonical.startswith("https://ledger.example.org/essays/archive/")
    finally:
        site.cleanup()
    shown = fixture_settings("showcase")
    shown["pageActions"] = {**ICONS, "everywhere": True}
    site = ProjectedSite("showcase", settings=shown)
    try:
        key = shown["showcase"]["path"].strip("/") + "/index.html"
        assert actions_of(site, key) is not None, sorted(site.tree)
    finally:
        site.cleanup()
