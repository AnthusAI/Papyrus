from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from papyrus_content.markus_renderer.docs_site import (
    DocsSiteConfig,
    build_docs_site,
    published_page_path,
    rewrite_links_between_pages,
    stage_docs_content,
)


def write_documentation_tree(documentation_directory: Path) -> None:
    (documentation_directory / "guides").mkdir(parents=True)
    (documentation_directory / "images").mkdir()
    (documentation_directory / "images" / "diagram.svg").write_text("<svg/>", encoding="utf-8")
    (documentation_directory / "index.md").write_text(
        "# Home\n\n[Setup](guides/setup.md) and [CLI](CLI.md#flags).\n", encoding="utf-8"
    )
    (documentation_directory / "CLI.md").write_text(
        "# CLI\n\n![Diagram](images/diagram.svg)\n", encoding="utf-8"
    )
    (documentation_directory / "guides" / "setup.md").write_text(
        "# Setup\n\nBack to [home](../index.md) or [CLI](../CLI.md).\n", encoding="utf-8"
    )


class DocsSiteTests(unittest.TestCase):
    def test_published_page_paths_flatten_nested_pages(self) -> None:
        self.assertEqual(published_page_path("index.md"), "index.md")
        self.assertEqual(published_page_path("CLI.md"), "articles/CLI.md")
        self.assertEqual(published_page_path("guides/setup.md"), "articles/guides-setup.md")

    def test_links_follow_pages_to_their_published_locations(self) -> None:
        known_pages = {"index.md", "CLI.md", "guides/setup.md"}
        self.assertEqual(
            rewrite_links_between_pages(
                "[Setup](guides/setup.md) [CLI](CLI.md#flags)", "index.md", known_pages
            ),
            "[Setup](articles/guides-setup.html) [CLI](articles/CLI.html#flags)",
        )
        self.assertEqual(
            rewrite_links_between_pages(
                "[home](../index.md) [CLI](../CLI.md)", "guides/setup.md", known_pages
            ),
            "[home](../index.html) [CLI](CLI.html)",
        )

    def test_links_to_unknown_or_external_pages_are_left_alone(self) -> None:
        text = "[x](missing.md) [y](https://example.com/page.md)"
        self.assertEqual(rewrite_links_between_pages(text, "index.md", {"index.md"}), text)

    def test_staging_writes_layout_and_moves_images_to_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary_directory = Path(temporary_name)
            write_documentation_tree(temporary_directory / "docs")
            staging_directory = temporary_directory / "staging"
            staging_directory.mkdir()
            config = DocsSiteConfig("Demo", "tag", temporary_directory / "docs", "https://x")
            staged_count = stage_docs_content(config, staging_directory)
            self.assertEqual(staged_count, 3)
            self.assertTrue((staging_directory / "assets" / "diagram.svg").is_file())
            self.assertIn("](../assets/diagram.svg)", (staging_directory / "articles" / "CLI.md").read_text())
            self.assertTrue((staging_directory / "articles" / "guides-setup.md").is_file())

    @unittest.skipUnless(shutil.which("markus"), "markus executable not installed")
    def test_build_renders_every_page_with_the_site_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary_directory = Path(temporary_name)
            write_documentation_tree(temporary_directory / "docs")
            config = DocsSiteConfig("Demo", "tag", temporary_directory / "docs", "https://x")
            result = build_docs_site(config, temporary_directory / "out")
            self.assertEqual(len(result.pages), 3)
            self.assertIn("Demo", (temporary_directory / "out" / "index.html").read_text())
            self.assertTrue((temporary_directory / "out" / "assets" / "diagram.svg").is_file())


if __name__ == "__main__":
    unittest.main()
