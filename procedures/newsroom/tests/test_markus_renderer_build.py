from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from papyrus_content.env import PAPYRUS_ROOT
from papyrus_content.markus_renderer.build import _build_nav_items, _discover_articles, _discover_section, build_markus_site, slugify


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

    def test_slugify_rules(self) -> None:
        for raw, expected in {
            "Paytronix": "paytronix",
            "Call Criteria": "call-criteria",
            "a_b  c.d": "a-b-c-d",
            "--Hi--": "hi",
            "Caf\u00e9": "cafe",
            "already-lower-1": "already-lower-1",
            "!!!": "",
        }.items():
            self.assertEqual(slugify(raw), expected, raw)

    def test_capitalised_filename_gets_lowercase_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            articles_dir = Path(tmp) / "articles"
            articles_dir.mkdir()
            (articles_dir / "alpha.md").write_text("Fine.", encoding="utf-8")
            (articles_dir / "Paytronix.md").write_text("Now rendered.", encoding="utf-8")
            slugs = [slug for slug, _ in _discover_articles(Path(tmp))]
            self.assertEqual(sorted(slugs), ["alpha", "paytronix"])

    def test_section_discovery_slugifies_and_skips_underscore_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            section_dir = Path(tmp) / "notes"
            section_dir.mkdir()
            (section_dir / "Big Note.md").write_text("x", encoding="utf-8")
            (section_dir / "a-1.md").write_text("x", encoding="utf-8")
            (section_dir / "_draft.md").write_text("x", encoding="utf-8")
            self.assertEqual(
                sorted(s for s, _ in _discover_section(Path(tmp), "notes")), ["a-1", "big-note"]
            )

    def test_slug_collision_raises_naming_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            articles_dir = Path(tmp) / "articles"
            articles_dir.mkdir()
            (articles_dir / "Foo Bar.md").write_text("x", encoding="utf-8")
            (articles_dir / "foo-bar.md").write_text("y", encoding="utf-8")
            with self.assertRaises(RuntimeError) as ctx:
                _discover_articles(Path(tmp))
            self.assertIn("Foo Bar.md", str(ctx.exception))
            self.assertIn("foo-bar.md", str(ctx.exception))

    def test_name_with_empty_slug_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            articles_dir = Path(tmp) / "articles"
            articles_dir.mkdir()
            (articles_dir / "ok.md").write_text("x", encoding="utf-8")
            (articles_dir / "!!!.md").write_text("x", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _discover_articles(Path(tmp))

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
