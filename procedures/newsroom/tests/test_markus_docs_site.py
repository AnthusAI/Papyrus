from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from papyrus_content.markus_renderer.docs_markdown import convert_markdown_dialects
from papyrus_content.markus_renderer.docs_site import (
    DocsSiteConfig,
    build_docs_site,
    docs_site_chrome,
    published_page_path,
    rewrite_image_references,
    rewrite_links_between_pages,
    stage_docs_content,
    write_sitemap_and_not_found_page,
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
        self.assertEqual(published_page_path("CLI.md"), "articles/cli.md")
        self.assertEqual(published_page_path("guides/setup.md"), "articles/guides-setup.md")

    def test_links_follow_pages_to_their_published_locations(self) -> None:
        known_pages = {"index.md", "CLI.md", "guides/setup.md"}
        self.assertEqual(
            rewrite_links_between_pages(
                "[Setup](guides/setup.md) [CLI](CLI.md#flags)", "index.md", known_pages
            ),
            "[Setup](articles/guides-setup.html) [CLI](articles/cli.html#flags)",
        )
        self.assertEqual(
            rewrite_links_between_pages(
                "[home](../index.md) [CLI](../CLI.md)", "guides/setup.md", known_pages
            ),
            "[home](../index.html) [CLI](cli.html)",
        )

    def test_html_links_between_pages_follow_the_page_to_its_published_name(self) -> None:
        known_pages = {"index.md", "CLI_REFERENCE.md"}
        self.assertEqual(
            rewrite_links_between_pages("[CLI](CLI_REFERENCE.html#flags)", "index.md", known_pages),
            "[CLI](articles/cli-reference.html#flags)",
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
            self.assertIn("](../assets/diagram.svg)", (staging_directory / "articles" / "cli.md").read_text())
            self.assertTrue((staging_directory / "articles" / "guides-setup.md").is_file())

    def test_excluded_pages_are_never_staged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary_directory = Path(temporary_name)
            write_documentation_tree(temporary_directory / "docs")
            staging_directory = temporary_directory / "staging"
            staging_directory.mkdir()
            config = DocsSiteConfig(
                "Demo",
                "tag",
                temporary_directory / "docs",
                "https://x",
                excluded_page_patterns=("guides/*",),
            )
            staged_count = stage_docs_content(config, staging_directory)
            self.assertEqual(staged_count, 2)
            self.assertFalse((staging_directory / "articles" / "guides-setup.md").exists())

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


class DocsAgentOutputTests(unittest.TestCase):
    def test_site_with_an_address_gets_twins_llms_files_lastmod_and_robots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            write_documentation_tree(root / "docs")
            config = DocsSiteConfig("Demo", "A demo.", root / "docs", "https://x", published_site_url="https://d.example/")
            staging = root / "staging"
            staging.mkdir()
            stage_docs_content(config, staging)
            out = root / "out"
            (out / "articles").mkdir(parents=True)
            for name in ("index", "articles/cli", "articles/guides-setup", "articles/not-found"):
                (out / f"{name}.html").write_text("<html><head></head><body><main>\n<h1>x</h1>\n</main></body></html>", encoding="utf-8")
            write_sitemap_and_not_found_page(config, out, content_directory=staging, last_modified_by_address={"index.html": "2026-01-02"})
            self.assertIn("# CLI", (out / "articles" / "cli.md").read_text())
            llms = (out / "llms.txt").read_text()
            self.assertTrue(llms.startswith("# Demo\n\n> A demo.\n"))
            self.assertIn("[Home](https://d.example/index.md)", llms)
            self.assertIn("Source: https://d.example/articles/cli.md", (out / "llms-full.txt").read_text())
            sitemap = (out / "sitemap.xml").read_text()
            self.assertIn("<loc>https://d.example/index.html</loc><lastmod>2026-01-02</lastmod>", sitemap)
            self.assertEqual(sitemap.count("<lastmod>"), 3)
            self.assertIn("Sitemap: https://d.example/sitemap.xml", (out / "robots.txt").read_text())
            self.assertFalse((out / "articles" / "not-found.md").exists())
            page = (out / "articles" / "cli.html").read_text()
            self.assertIn('<link rel="alternate" type="text/markdown" href="cli.md">', page)
            self.assertIn('data-markdown="cli.md" data-title="CLI" data-canonical="https://d.example/articles/cli.html"', page)
            self.assertIn('<a class="markus-action-link" data-action="view" href="cli.md">View as Markdown</a>', page)
            for name, label, base in (
                ("chatgpt", "Open in ChatGPT", "https://chatgpt.com/?q="),
                ("claude", "Open in Claude", "https://claude.ai/new?q="),
                ("perplexity", "Open in Perplexity", "https://www.perplexity.ai/search?q="),
            ):
                self.assertIn(f'data-action="{name}" href="{base}Read%20https%3A%2F%2Fd.example%2Farticles%2Fcli.html', page)
                self.assertIn(label, page)
            self.assertIn('href="../_plugins/papyrus-page-actions.css"', page)
            self.assertIn('<script src="../_plugins/papyrus-page-actions-v1.js" defer>', page)
            self.assertIn('href="_plugins/papyrus-page-actions.css"', (out / "index.html").read_text())
            self.assertIn(".markus-page-actions {", (out / "_plugins" / "papyrus-page-actions.css").read_text())
            self.assertTrue((out / "_plugins" / "papyrus-page-actions-v1.js").is_file())
            self.assertNotIn("page-actions", (out / "404.html").read_text())


class DocsMarkdownDialectTests(unittest.TestCase):
    def test_mkdocs_admonition_becomes_callout_with_title_and_body(self) -> None:
        converted = convert_markdown_dialects('!!! warning "Careful"\n    Mind the gap.\n\nAfter.')
        self.assertIn(':::callout{kind="warning" title="Careful"}\nMind the gap.\n:::', converted)
        self.assertTrue(converted.rstrip().endswith("After."))

    def test_admonition_kinds_map_to_the_four_markus_callout_kinds(self) -> None:
        self.assertIn('kind="tip"', convert_markdown_dialects("!!! hint\n    x"))
        self.assertIn('kind="caution"', convert_markdown_dialects("!!! danger\n    x"))
        self.assertIn('kind="note"', convert_markdown_dialects("!!! info\n    x"))

    def test_collapsible_admonition_becomes_details(self) -> None:
        converted = convert_markdown_dialects('???+ note "More"\n    hidden')
        self.assertIn(':::details{summary="More" open=true}', converted)
        self.assertIn(':::details{summary="More"}', convert_markdown_dialects('??? note "More"\n    hidden'))

    def test_tab_group_becomes_tabs_with_longer_outer_fence(self) -> None:
        converted = convert_markdown_dialects('=== "Python"\n    one\n\n=== "Lua"\n    two\n')
        self.assertIn('::::tabs\n:::tab{label="Python"}\none\n:::\n:::tab{label="Lua"}\ntwo\n:::\n::::', converted)

    def test_fenced_code_inside_a_callout_is_kept_as_a_body(self) -> None:
        converted = convert_markdown_dialects('!!! note\n    ```bash\n    echo hi\n    ```\n')
        self.assertIn(':::callout{kind="note"}\n```bash\necho hi\n```\n:::', converted)

    def test_admonition_syntax_inside_a_code_fence_is_not_converted(self) -> None:
        text = '```markdown\n!!! note\n    example\n=== "Tab"\n```\n'
        self.assertEqual(convert_markdown_dialects(text), text)

    def test_github_alert_and_bold_label_quotes_become_callouts(self) -> None:
        self.assertIn(':::callout{kind="tip"}\nDo it\n:::', convert_markdown_dialects("> [!TIP]\n> Do it"))
        self.assertIn(':::callout{kind="warning"}\nCareful here\n:::', convert_markdown_dialects("> **Warning:** Careful here"))

    def test_ordinary_quotes_are_left_alone(self) -> None:
        text = "> **The fundamental problem:** nothing to convert\n> still a quote"
        self.assertEqual(convert_markdown_dialects(text), text)

    def test_html_details_block_becomes_details_directive(self) -> None:
        converted = convert_markdown_dialects("<details>\n<summary>More <b>info</b></summary>\n\ninside\n\n</details>\n")
        self.assertIn(':::details{summary="More info"}', converted)
        self.assertIn("inside", converted)
        self.assertNotIn("<details>", converted)

    def test_html_img_tag_becomes_markdown_image_but_inline_code_is_kept(self) -> None:
        converted = convert_markdown_dialects('<img src="diagrams/a.svg" alt="A diagram"> and `<img src="x">`')
        self.assertEqual(converted, '![A diagram](diagrams/a.svg) and `<img src="x">`')


class DocsImageAndLinkTests(unittest.TestCase):
    def test_images_resolve_from_subfolders_and_other_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            documentation = Path(temporary_name)
            (documentation / "images").mkdir()
            (documentation / "images" / "a.png").write_bytes(b"x")
            (documentation / "diagrams").mkdir()
            (documentation / "diagrams" / "b.svg").write_text("<svg/>", encoding="utf-8")
            (documentation / "guides").mkdir()
            text = "![a](../images/a.png) ![b](../diagrams/b.svg) ![r](https://example.com/r.png) ![m](missing.png)"
            rewritten, needed = rewrite_image_references(text, "guides/setup.md", documentation)
            self.assertIn("](../assets/a.png)", rewritten)
            self.assertIn("](../assets/diagrams/b.svg)", rewritten)
            self.assertIn("](https://example.com/r.png)", rewritten)
            self.assertIn("](missing.png)", rewritten)
            self.assertEqual(needed, {"images/a.png", "diagrams/b.svg"})
            index_text, _ = rewrite_image_references("![a](images/a.png)", "index.md", documentation)
            self.assertEqual(index_text, "![a](assets/a.png)")

    def test_staging_copies_images_from_outside_the_images_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary_directory = Path(temporary_name)
            documentation = temporary_directory / "docs"
            (documentation / "diagrams").mkdir(parents=True)
            (documentation / "diagrams" / "flow.svg").write_text("<svg/>", encoding="utf-8")
            (documentation / "index.md").write_text('# Home\n\n<img src="diagrams/flow.svg" alt="Flow">\n', encoding="utf-8")
            staging_directory = temporary_directory / "staging"
            staging_directory.mkdir()
            stage_docs_content(DocsSiteConfig("Demo", "tag", documentation, "https://x"), staging_directory)
            self.assertTrue((staging_directory / "assets" / "diagrams" / "flow.svg").is_file())
            self.assertIn("![Flow](assets/diagrams/flow.svg)", (staging_directory / "index.md").read_text())

    def test_directory_links_point_at_the_directory_readme_page(self) -> None:
        known_pages = {"index.md", "topic/README.md"}
        self.assertEqual(
            rewrite_links_between_pages("[topic](topic/)", "index.md", known_pages),
            "[topic](articles/topic-readme.html)",
        )

    def test_dark_theme_gets_a_light_sibling_that_follows_the_reader(self) -> None:
        chrome = docs_site_chrome(DocsSiteConfig("Demo", "tag", Path("docs"), "https://x"))
        self.assertIn("catppuccin-latte", chrome.head_html)
        self.assertIn("prefers-color-scheme: light", chrome.head_html)
        self.assertIn("mermaid", chrome.footer_html)


if __name__ == "__main__":
    unittest.main()
