from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from papyrus_content.markus_renderer.book_site import (
    BookSourceError,
    build_book_site,
    expand_code_includes,
    materialize_book_as_documentation,
    read_quarto_book,
    strip_quarto_heading_classes,
    substitute_meta_shortcodes,
)

QUARTO_PROJECT = """\
project:
  type: book
metadata-files:
  - book-links.yml
book:
  title: "Tiny Book"
  chapters:
    - index.qmd
    - chapters/01-intro.qmd
    - part: "Part Two"
      chapters:
        - chapters/02-tools.qmd
        - chapters/03-state.qmd
"""

TACTUS_CODE_FILE = """\
-- A demo file.

-- snippet:start greeting
    local name = "World"
    return "Hello, " .. name
-- snippet:end greeting

-- snippet:start only-comments
-- first
--   second
-- snippet:end only-comments
"""


def write_book_project(project_directory: Path) -> None:
    (project_directory / "chapters").mkdir(parents=True)
    (project_directory / "code").mkdir()
    (project_directory / "images").mkdir()
    (project_directory / "images" / "cover.png").write_bytes(b"png")
    (project_directory / "_quarto.yml").write_text(QUARTO_PROJECT, encoding="utf-8")
    (project_directory / "book-links.yml").write_text("tactus_version_tag: v1.2.3\n", encoding="utf-8")
    (project_directory / "code" / "demo.tac").write_text(TACTUS_CODE_FILE, encoding="utf-8")
    (project_directory / "index.qmd").write_text(
        "# Preface {.unnumbered}\n\nTested against {{< meta tactus_version_tag >}}.\n", encoding="utf-8"
    )
    (project_directory / "chapters" / "01-intro.qmd").write_text("# Introduction\n\nStart here.\n", encoding="utf-8")
    (project_directory / "chapters" / "02-tools.qmd").write_text(
        '# Tools\n\n```lua {file="code/demo.tac" snippet="greeting" show-path="true"}\n```\n', encoding="utf-8"
    )
    (project_directory / "chapters" / "03-state.qmd").write_text("# State\n\nSee [tools](02-tools.qmd).\n", encoding="utf-8")


class BookSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = Path(tempfile.mkdtemp())
        self.project_directory = self.temporary_directory / "book"
        write_book_project(self.project_directory)

    def tearDown(self) -> None:
        shutil.rmtree(self.temporary_directory)

    def test_chapters_keep_reading_order_and_their_parts(self) -> None:
        book = read_quarto_book(self.project_directory)
        self.assertEqual(book.title, "Tiny Book")
        self.assertEqual(
            [(chapter.source_path, chapter.part_title) for chapter in book.chapters],
            [
                ("index.qmd", None),
                ("chapters/01-intro.qmd", None),
                ("chapters/02-tools.qmd", "Part Two"),
                ("chapters/03-state.qmd", "Part Two"),
            ],
        )

    def test_missing_project_file_is_reported(self) -> None:
        (self.project_directory / "_quarto.yml").unlink()
        with self.assertRaises(BookSourceError):
            read_quarto_book(self.project_directory)

    def test_meta_shortcodes_use_metadata_and_fail_on_unknown_keys(self) -> None:
        self.assertEqual(
            substitute_meta_shortcodes("v {{< meta version >}}", {"version": "1.0"}, "page.qmd"), "v 1.0"
        )
        with self.assertRaises(BookSourceError):
            substitute_meta_shortcodes("{{< meta missing >}}", {}, "page.qmd")

    def test_snippet_include_is_dedented_and_markers_are_removed(self) -> None:
        page = '```lua {file="code/demo.tac" snippet="greeting"}\n```\n'
        expanded = expand_code_includes(page, self.project_directory)
        self.assertEqual(expanded, '```lua\nlocal name = "World"\nreturn "Hello, " .. name\n```\n')
        self.assertNotIn("snippet:", expanded)

    def test_show_path_adds_a_source_label(self) -> None:
        page = '```lua {file="code/demo.tac" snippet="greeting" show-path="true"}\n```\n'
        self.assertTrue(
            expand_code_includes(page, self.project_directory).startswith("Source: `code/demo.tac`\n\n```lua\n")
        )

    def test_a_snippet_made_only_of_comments_is_uncommented(self) -> None:
        page = '```text {file="code/demo.tac" snippet="only-comments"}\n```\n'
        self.assertEqual(expand_code_includes(page, self.project_directory), "```text\nfirst\n  second\n```\n")

    def test_line_ranges_select_lines(self) -> None:
        page = '```text {file="code/demo.tac" lines="4-5"}\n```\n'
        self.assertEqual(expand_code_includes(page, self.project_directory), '```text\nlocal name = "World"\nreturn "Hello, " .. name\n```\n')

    def test_missing_snippet_or_file_fails_the_build(self) -> None:
        with self.assertRaises(BookSourceError):
            expand_code_includes('```lua {file="code/demo.tac" snippet="nope"}\n```\n', self.project_directory)
        with self.assertRaises(BookSourceError):
            expand_code_includes('```lua {file="code/absent.tac"}\n```\n', self.project_directory)

    def test_ordinary_fences_are_left_alone(self) -> None:
        page = "```lua\nlocal x = 1\n```\n"
        self.assertEqual(expand_code_includes(page, self.project_directory), page)

    def test_quarto_heading_classes_are_dropped_but_anchors_stay(self) -> None:
        self.assertEqual(strip_quarto_heading_classes("# Preface {.unnumbered}\n## A {#a}\n"), "# Preface\n## A {#a}\n")

    def test_materialized_documentation_has_index_pages_and_grouped_navigation(self) -> None:
        documentation_directory = self.temporary_directory / "docs"
        documentation_directory.mkdir()
        _, navigation = materialize_book_as_documentation(self.project_directory, documentation_directory)
        self.assertIn("Tested against v1.2.3.", (documentation_directory / "index.md").read_text(encoding="utf-8"))
        self.assertTrue((documentation_directory / "chapters" / "03-state.md").is_file())
        self.assertTrue((documentation_directory / "images" / "cover.png").is_file())
        self.assertEqual(
            navigation,
            (
                ("Tiny Book", (("index.html", "Preface"), ("articles/chapters-01-intro.html", "Introduction"))),
                (
                    "Part Two",
                    (
                        ("articles/chapters-02-tools.html", "Tools"),
                        ("articles/chapters-03-state.html", "State"),
                    ),
                ),
            ),
        )

    @unittest.skipUnless(shutil.which("markus"), "markus executable not installed")
    def test_built_site_links_chapters_and_redirects_the_former_quarto_addresses(self) -> None:
        output_directory = self.temporary_directory / "site"
        result = build_book_site(
            self.project_directory, output_directory, source_repository_url="https://example.test/book"
        )
        self.assertEqual(len(result.pages), 4)
        state_page = (output_directory / "articles" / "chapters-03-state.html").read_text(encoding="utf-8")
        self.assertIn("chapters-02-tools.html", state_page)
        former_address = (output_directory / "chapters" / "02-tools.html").read_text(encoding="utf-8")
        self.assertIn("../articles/chapters-02-tools.html", former_address)

    @unittest.skipUnless(shutil.which("markus"), "markus executable not installed")
    def test_home_page_is_the_real_first_chapter_and_not_a_redirect_to_itself(self) -> None:
        output_directory = self.temporary_directory / "site"
        build_book_site(self.project_directory, output_directory, source_repository_url="https://example.test/book")
        home_page = (output_directory / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('http-equiv="refresh"', home_page)
        self.assertIn("Preface", home_page)

    @unittest.skipUnless(shutil.which("markus"), "markus executable not installed")
    def test_site_with_a_public_address_gets_an_articles_index_a_sitemap_and_a_not_found_page(self) -> None:
        output_directory = self.temporary_directory / "site"
        build_book_site(
            self.project_directory,
            output_directory,
            source_repository_url="https://example.test/book",
            published_site_url="https://example.test/book/",
        )
        articles_index = (output_directory / "articles" / "index.html").read_text(encoding="utf-8")
        self.assertIn("chapters-03-state.html", articles_index)
        sitemap = (output_directory / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("https://example.test/book/index.html", sitemap)
        self.assertIn("https://example.test/book/articles/chapters-03-state.html", sitemap)
        self.assertNotIn("404.html", sitemap)
        self.assertNotIn("chapters/02-tools.html", sitemap)
        not_found_page = (output_directory / "404.html").read_text(encoding="utf-8")
        self.assertIn('<base href="https://example.test/book/articles/">', not_found_page)
        self.assertIn("Page not found", not_found_page)


if __name__ == "__main__":
    unittest.main()
