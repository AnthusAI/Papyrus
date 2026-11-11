"""`papyrus stories retire` on the standard projector: type folders, directory addresses and Markdown twins."""

from __future__ import annotations

import tempfile
from pathlib import Path

from papyrus_content.projection.engine import reconcile
from papyrus_content.projection.projector import MarkusProjectorSettings, read_static_files
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.hooks import Hooks
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from papyrus_content.publishing import ItemFields, publish_item, save_item
from papyrus_content.story_retire import apply_retire, plan_retire
from procedures.newsroom.tests.incremental_site import Site
from procedures.newsroom.tests.projection_fixtures import ACTOR, NOW
from procedures.newsroom.tests.standard_frontend_content_support import SITE

STANDARD = {"urls": {"style": "directory", "types": {"article": {"base": "articles"}, "post": {"base": "posts"}}}}


def standard_site(tmp_path: Path) -> Site:
    def factory():
        static = Path(tempfile.mkdtemp(dir=tmp_path))
        return StandardMarkusProjector(
            MarkusProjectorSettings(theme=None),
            read_static_files(None, None),
            standard_settings_from_mapping({"site": SITE, **STANDARD}),
            static_directory=static,
            hooks=Hooks(),
            environment=None,
        )

    return Site(factory, tmp_path / "work")


def put(site: Site, item_id: str, slug: str, item_type: str) -> None:
    fields = ItemFields(
        type=item_type, slug=slug, section=None, front_matter_yaml=f"title: Story {slug}\ndate: '2026-03-01'\n", body_markus="Body.\n", aliases=[], id=item_id
    )
    save_item(site.client, fields, actor=ACTOR, now=NOW)
    publish_item(site.client, item_id, actor=ACTOR, now=NOW)
    site.project_item(item_id)


def retire(site: Site, story: str, target: str) -> None:
    apply_retire(site.client, plan_retire(site.client, story, target), actor="tester")
    site.project_item(story)


def test_an_article_and_a_post_redirect_to_the_article_with_their_markdown_twins(tmp_path: Path) -> None:
    site = standard_site(tmp_path)
    put(site, "a", "face-match", "article")
    put(site, "p", "detroit", "post")
    put(site, "y", "computer-picked", "article")
    retire(site, "a", "y")
    retire(site, "p", "y")
    redirects = site.redirects.mapping
    assert redirects["/articles/face-match/"] == "/articles/computer-picked/"
    assert redirects["/articles/face-match"] == "/articles/computer-picked/"
    assert redirects["/posts/detroit/"] == "/articles/computer-picked/"
    assert redirects["/articles/face-match/index.md"] == "/articles/computer-picked/index.md"
    assert redirects["/posts/detroit/index.md"] == "/articles/computer-picked/index.md"
    stored = {entry.key for entry in site.store.list() if not entry.key.startswith("_")}
    assert not any("face-match" in key or "detroit" in key for key in stored), sorted(stored)
    for key in ("sitemap.xml", "feed.xml", "atom.xml", "llms.txt", "articles/index.html"):
        text = (site.work / "incremental" / key).read_text()
        assert "face-match" not in text and "detroit" not in text, key
    assert not reconcile(site.context, dry_run=True).drift
