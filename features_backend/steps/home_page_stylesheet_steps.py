from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from behave import given, then

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.standard import projector as standard_projector  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite  # noqa: E402

SITE_DIRECTORY = FIXTURES / "home-page"
SNAPSHOT_KEY = "_data/home-page/references.json"
STYLESHEET_PATH = "css/papyrus-home-page.css"
STYLESHEET_LINK = re.compile(r'<link rel="stylesheet" href="[^"]*papyrus-home-page\.css\?v=(?P<version>[^"]*)">')


def fixture_settings() -> dict:
    return copy.deepcopy(json.loads((SITE_DIRECTORY / "projection.json").read_text(encoding="utf-8")))


def project(context, settings: dict, page_names: list[str]) -> ProjectedSite:
    extra_files = {f"pages/{name}.md": (SITE_DIRECTORY / "pages" / f"{name}.md").read_bytes() for name in page_names}
    seed = {SNAPSHOT_KEY: (SITE_DIRECTORY / "_data" / "home-page" / "references.json").read_bytes()}
    site = ProjectedSite(settings=settings, content=SITE_DIRECTORY / "content", extra_files=extra_files, seed=seed)
    context.add_cleanup(site.cleanup)
    return site


def quiet_only(settings: dict) -> dict:
    settings["pages"] = [page for page in settings["pages"] if page["id"] == "quiet"]
    return settings


@given("the home-page fixture site with only its quiet page is projected with homePage set")
def projected_quiet_with_home_page(context) -> None:
    context.first = project(context, quiet_only(fixture_settings()), ["quiet"])


@given("the same site is projected without homePage")
def projected_quiet_without_home_page(context) -> None:
    settings = quiet_only(fixture_settings())
    del settings["homePage"]
    context.second = project(context, settings, ["quiet"])


@given("the home-page stylesheet is edited and the site is projected again")
def projected_with_edited_stylesheet(context) -> None:
    edited = Path(tempfile.mkdtemp(prefix="home-page-assets-"))
    context.add_cleanup(lambda: shutil.rmtree(edited, ignore_errors=True))
    shutil.copytree(standard_projector.ASSET_DIRECTORY, edited, dirs_exist_ok=True)
    stylesheet = edited / "papyrus-home-page.css"
    stylesheet.write_text(stylesheet.read_text(encoding="utf-8") + "\n.home-page-edited-for-test { margin: 0; }\n", encoding="utf-8")
    original = standard_projector.ASSET_DIRECTORY
    standard_projector.ASSET_DIRECTORY = edited
    try:
        context.second = project(context, quiet_only(fixture_settings()), ["quiet"])
    finally:
        standard_projector.ASSET_DIRECTORY = original
    assert context.first.tree[STYLESHEET_PATH] != context.second.tree[STYLESHEET_PATH]


@then('"{path}" is identical in both projections')
def identical(context, path: str) -> None:
    assert context.first.text(path) == context.second.text(path)


@then('the page "{path}" has no home-page stylesheet link')
def no_link(context, path: str) -> None:
    site = getattr(context, "site", None) or context.first
    assert "papyrus-home-page.css" not in site.text(path)


@then('the stylesheet "{path}" is published in the first projection only')
def published_first_only(context, path: str) -> None:
    assert path in context.first.tree
    assert path not in context.second.tree


@then("the page \"{path}\" links the home-page stylesheet with the first 12 hex characters of that file's SHA-256 as its version")
def own_version(context, path: str) -> None:
    link = STYLESHEET_LINK.search(context.site.text(path))
    assert link, f"{path} does not link the home-page stylesheet"
    assert link["version"] == hashlib.sha256(context.site.tree[STYLESHEET_PATH]).hexdigest()[:12]
    other = re.search(r'site-theme\.css\?v=(?P<version>[^"]*)"', context.site.text(path))
    assert other and other["version"] != link["version"]
