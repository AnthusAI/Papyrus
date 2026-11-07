"""The share preview the lens checks judge is the one the projector emits (PPY-59c772)."""

from __future__ import annotations

import json
import re

from papyrus_content import lens_evidence as evidence
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.environment import resolve_environment
from procedures.newsroom.tests.standard_frontend_content_support import cms_site, item, settings

ORIGIN = "https://example.org"
ENVIRON = {"PAPYRUS_SITE_PUBLIC_URL": ORIGIN}
TAGS = ("description", "og:title", "og:description", "og:image", "og:image:alt", "twitter:card", "twitter:title", "twitter:image", "twitter:image:alt")
BODY = "The board refused the merger on March 3.\n"


def project(front: dict, body: str = BODY, **extra) -> str:
    site = cms_site(settings(**extra), [item("board", section=None, body=body, **front)], environ=ENVIRON)
    try:
        return site.text("board.html")
    finally:
        site.cleanup()


def facts_head(front_yaml: str, body: str, mapping: dict) -> str:
    standard = standard_settings_from_mapping(mapping)
    site = evidence.LensSite(standard, resolve_environment(standard, ENVIRON))
    row = {"id": "v1", "lineageId": "s1", "versionNumber": 1, "type": "article", "slug": "board", "section": None, "stage": "copywriting", "title": "Board",
           "bodyMarkus": body, "metadata": json.dumps({"frontMatterYaml": front_yaml})}
    return evidence.Facts(evidence.story_from_row(row), site).head_html


def tag(html: str, name: str) -> str | None:
    return evidence.meta(html, name)


def test_the_checks_see_the_same_tags_as_the_projected_page():
    front = {"title": "Board refuses", "summary": "The board refused the merger.", "image": "/assets/own.jpg", "imageAlt": "A harbour at dusk", "date": "2026-03-03"}
    page = project(front)
    import yaml

    mine = facts_head(yaml.safe_dump(front), BODY, settings())
    for name in TAGS:
        assert tag(mine, name) == tag(page, name), name
    assert tag(page, "og:image:alt") == "A harbour at dusk"
    assert re.search(r'<link rel="canonical" href="([^"]+)"', mine).group(1) == re.search(r'<link rel="canonical" href="([^"]+)"', page).group(1)


def test_a_story_without_image_alt_still_emits_none_as_before():
    page = project({"title": "Board refuses", "summary": "S.", "image": "/assets/own.jpg"})
    assert tag(page, "og:image") == f"{ORIGIN}/assets/own.jpg" and tag(page, "og:image:alt") is None


def test_the_description_falls_back_from_summary_to_the_opening_to_the_site():
    from papyrus_content.projection.standard.share_preview import item_share_preview

    standard = standard_settings_from_mapping(settings())
    from papyrus_content.projection.source import summary_from_row
    from papyrus_content.projection.standard.entries import entry_for_summary
    from papyrus_content.projection.standard.urls import UrlPolicy

    def source(front_yaml: str) -> str:
        row = {"id": "v1", "type": "article", "slug": "board", "section": None, "title": "Board", "metadata": json.dumps({"frontMatterYaml": front_yaml})}
        entry = entry_for_summary(summary_from_row(row), standard, UrlPolicy(standard))
        return item_share_preview(entry, standard, UrlPolicy(standard), opening="Opening.").description_source

    assert source("title: T\nsummary: Dek.\n") == "summary"
    assert source("title: T\n") == "opening"
