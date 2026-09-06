from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from papyrus_content.env import PAPYRUS_ROOT
from papyrus_content.markus_renderer.build import _build_nav_items, _discover_articles, build_markus_site


class MarkusRendererBuildTests(unittest.TestCase):
    def test_build_nav_items_lists_home_and_all_articles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            articles_dir = tmp_path / "articles"
            articles_dir.mkdir()
            (articles_dir / "alpha.md").write_text("---\ntitle: Alpha\n---\n\nOne.", encoding="utf-8")
            (articles_dir / "beta.md").write_text("---\ntitle: Beta\n---\n\nTwo.", encoding="utf-8")

            articles = _discover_articles(tmp_path)
            nav_items = _build_nav_items(articles)

            self.assertEqual([item.label for item in nav_items], ["Home", "Alpha", "Beta"])
            self.assertEqual(
                [item.href for item in nav_items],
                ["index.html", "articles/alpha.html", "articles/beta.html"],
            )

    def test_markus_build_sample_article_emits_construct_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "markus-dist"
            result = build_markus_site(
                content_dir=PAPYRUS_ROOT / "web" / "content",
                out_dir=out_dir,
                theme="hackerman",
            )
            sample_html = next(path for path in result.pages if path.name == "sample.html")
            html = sample_html.read_text(encoding="utf-8")
            for marker in (
                "markus-pull-quote",
                "markus-card-grid",
                "markus-two-up",
                "markus-figure",
            ):
                self.assertIn(marker, html, f"expected Markus HTML marker {marker} in sample.html")


if __name__ == "__main__":
    unittest.main()
