"""The static site that ``scripts/test-newsletter-pages-browser.ts`` drives is the standard projector's own output.

``features/fixtures/newsletter-site/newsletter/*/index.html`` is committed so the browser test needs no Python. This test projects the
same site and fails when the committed pages differ; regenerate them with ``PAPYRUS_UPDATE_FIXTURES=1 pytest <this file>``.
Cache-busting hashes (``?v=`` and the asset version) are normalised so the files only change when the markup does.
"""

from __future__ import annotations

import os
import re

import pytest

from papyrus_content.env import PAPYRUS_ROOT
from procedures.newsroom.tests.standard_frontend_support import FIXTURES, ProjectedSite

SITE = PAPYRUS_ROOT / "features" / "fixtures" / "newsletter-site"
SETTINGS = {
    "site": {"name": "Fixture Site", "description": "A fixture site for the newsletter pages.", "productionUrl": "https://fixture.example"},
    "urls": {"style": "directory"},
    "nav": {"links": [{"label": "Front", "href": "/"}, {"label": "New", "href": "/new/"}]},
    "footer": {"text": "Fixture footer."},
    "icons": {"themeColor": "#C6F432", "themeColorDark": "#C6F432"},
}


def projected_pages() -> dict[str, str]:
    site = ProjectedSite(settings=SETTINGS, content=FIXTURES / "flat" / "content", plugins=("newsletter",), extra_files={"css/site-theme.css": (SITE / "css" / "site-theme.css").read_text()})
    try:
        return {
            key: re.sub(r"__markusAssetVersion = \"[0-9a-f]+\"", "__markusAssetVersion = \"fixture\"", re.sub(r"\?v=[0-9a-f]+", "", site.text(key)))
            for key in sorted(site.tree)
            if key.startswith("newsletter/") and key.endswith(".html")
        }
    finally:
        site.cleanup()


def test_the_committed_browser_fixture_is_the_projectors_output() -> None:
    pages = projected_pages()
    assert len(pages) == 6
    if os.environ.get("PAPYRUS_UPDATE_FIXTURES") == "1":
        for key, html in pages.items():
            (SITE / key).parent.mkdir(parents=True, exist_ok=True)
            (SITE / key).write_text(html, encoding="utf-8")
    for key, html in pages.items():
        committed = SITE / key
        assert committed.is_file() and committed.read_text(encoding="utf-8") == html, f"{key} is stale: PAPYRUS_UPDATE_FIXTURES=1 pytest {__file__}"
