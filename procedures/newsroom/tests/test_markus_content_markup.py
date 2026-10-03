"""Tests for the Markus renderer's opt-in content capabilities.

Matches the conventions of ``test_markus_renderer_build.py``: ``unittest``
cases run by the repo's pytest config, with the real ``markus`` CLI used for
the end-to-end cases (the renderer pins its version, so a build that cannot
shell out to it is already broken).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from papyrus_content.markus_renderer.build import build_markus_site, render_fragment
from papyrus_content.markus_renderer.citations import (
    CitationCollector,
    CitationError,
    CitationRendering,
    format_apa,
)
from papyrus_content.markus_renderer.content_markup import (
    ContentMarkupError,
    parse_attrs,
    prepare_page,
    read_citation_entries,
)
from papyrus_content.markus_renderer.images import (
    ImageBuilder,
    ImagePipeline,
    ImagePipelineError,
    ImageRequest,
    assert_safe_asset_src,
)

CSL_JOURNAL = {
    "type": "article-journal",
    "title": "The Price of Progress: Price Performance and the Future of AI",
    "author": ["Hans Gundlach", "Jayson Lynch", "Matthias Mertens", "Neil Thompson"],
    "container-title": "arXiv",
    "DOI": "10.48550/arXiv.2511.23455",
    "URL": "https://arxiv.org/abs/2511.23455",
    "issued": {"date-parts": [[2025, 11]]},
    "accessed": {"date-parts": [[2026, 8, 16]]},
}

CSL_WEBPAGE = {
    "type": "webpage",
    "container-title": "OpenAI Developers",
    "title": "Run long horizon tasks with Codex",
    "URL": "https://developers.openai.com/blog/run-long-horizon-tasks-with-codex",
    "accessed": {"date-parts": [[2026, 8, 16]]},
}


def _write_images(images_dir: Path) -> None:
    from PIL import Image

    images_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2400, 1350), (30, 90, 160)).save(images_dir / "chart.png")
    Image.new("RGB", (640, 480), (200, 60, 120)).save(images_dir / "small.jpg")
    Image.new("P", (64, 64)).save(images_dir / "spin.gif")
    (images_dir / "logo.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60">'
        '<rect width="120" height="60"/></svg>',
        encoding="utf-8",
    )


class AttributeParsingTests(unittest.TestCase):
    def test_parses_quoted_and_bare_values(self) -> None:
        parsed = parse_attrs("""src="a b.png" layout=full alt='It\\'s fine' sizes="100vw" """)
        self.assertEqual(parsed["src"], "a b.png")
        self.assertEqual(parsed["layout"], "full")
        self.assertEqual(parsed["sizes"], "100vw")


class ContentMarkupLoweringTests(unittest.TestCase):
    SOURCE = """---
title: Demo
citations:
  gundlach-2025:
    type: article-journal
    title: Price of Progress
    URL: https://example.org/a
---

Falling costs [@gundlach-2025] and again [@gundlach-2025].

::image{src="images/chart.png" layout="full" alt="Chart"}

Literal in code: `::image{src="x.png"}` and `[@nope]`.

```
::image{src="never.png"}
[@never]
```

::citations{format="apa"}
"""

    def test_both_capabilities_off_leaves_markdown_identical(self) -> None:
        page = prepare_page(self.SOURCE, images=None, citations=None)
        self.assertEqual(page.markdown, self.SOURCE)
        self.assertFalse(page.touched)

    def test_lowers_directives_and_refs_to_sentinels(self) -> None:
        page = prepare_page(
            self.SOURCE, images=ImagePipeline(), citations=CitationRendering()
        )
        self.assertEqual(len(page.images), 1)
        self.assertEqual(len(page.citation_keys), 2)
        self.assertEqual(len(page.citation_lists), 1)
        request = next(iter(page.images.values()))
        self.assertEqual(request.src, "images/chart.png")
        self.assertEqual(request.layout, "full")
        self.assertEqual(request.alt, "Chart")
        self.assertNotIn("::image{src=\"images/chart.png\"", page.markdown)
        self.assertNotIn("[@gundlach-2025]", page.markdown)

    def test_code_spans_and_fences_are_not_lowered(self) -> None:
        page = prepare_page(
            self.SOURCE, images=ImagePipeline(), citations=CitationRendering()
        )
        self.assertIn('`::image{src="x.png"}`', page.markdown)
        self.assertIn("[@nope]", page.markdown)
        self.assertIn('::image{src="never.png"}', page.markdown)
        self.assertIn("[@never]", page.markdown)

    def test_front_matter_is_preserved_verbatim(self) -> None:
        page = prepare_page(
            self.SOURCE, images=ImagePipeline(), citations=CitationRendering()
        )
        self.assertTrue(page.markdown.startswith("---\ntitle: Demo\n"))

    def test_reads_citation_entries_from_front_matter(self) -> None:
        entries = read_citation_entries(self.SOURCE)
        self.assertEqual(list(entries), ["gundlach-2025"])
        self.assertEqual(entries["gundlach-2025"]["URL"], "https://example.org/a")

    def test_unknown_image_attribute_is_rejected(self) -> None:
        with self.assertRaises(ContentMarkupError) as ctx:
            prepare_page(
                '::image{src="a.png" width="400"}\n',
                images=ImagePipeline(),
                citations=None,
            )
        self.assertIn("width", str(ctx.exception))

    def test_image_directive_requires_src(self) -> None:
        with self.assertRaises(ContentMarkupError):
            prepare_page('::image{alt="no src"}\n', images=ImagePipeline(), citations=None)

    def test_attribute_block_may_wrap_across_lines(self) -> None:
        page = prepare_page(
            '::image{\n  src="images/chart.png"\n  layout="full"\n'
            '  alt="A long alt text\n  wrapped by the author"\n}\n',
            images=ImagePipeline(),
            citations=None,
        )
        request = next(iter(page.images.values()))
        self.assertEqual(request.src, "images/chart.png")
        self.assertEqual(request.layout, "full")
        self.assertIn("wrapped by the author", request.alt)

    def test_multiple_keys_in_one_bracket(self) -> None:
        page = prepare_page(
            "Both [@a; @b] here.\n", images=None, citations=CitationRendering()
        )
        self.assertEqual(list(page.citation_keys.values()), [["a", "b"]])


class CitationNumberingTests(unittest.TestCase):
    def _collector(self) -> CitationCollector:
        return CitationCollector(
            {"j": CSL_JOURNAL, "w": CSL_WEBPAGE}, CitationRendering()
        )

    def test_numbers_follow_first_reference_order_and_dedupe(self) -> None:
        collector = self._collector()
        self.assertIn('href="#citation-1"', collector.marker_html("w") or "")
        self.assertIn('href="#citation-2"', collector.marker_html("j") or "")
        self.assertIn('href="#citation-1"', collector.marker_html("w") or "")

    def test_marker_markup_matches_the_ported_contract(self) -> None:
        collector = self._collector()
        self.assertEqual(
            collector.marker_html("j"),
            '<span class="citation"><a href="#citation-1">1</a></span>',
        )

    def test_list_has_one_entry_per_cited_key_with_matching_anchors(self) -> None:
        collector = self._collector()
        collector.marker_html("j")
        collector.marker_html("w")
        collector.marker_html("j")
        listing = collector.list_html()
        self.assertEqual(listing.count("<li "), 2)
        self.assertIn('<li id="citation-1">', listing)
        self.assertIn('<li id="citation-2">', listing)
        self.assertTrue(listing.startswith('<ol class="citationslist">'))

    def test_url_is_stripped_from_text_and_appended_as_a_link(self) -> None:
        collector = self._collector()
        collector.marker_html("j")
        listing = collector.list_html()
        self.assertIn(
            '<a href="https://arxiv.org/abs/2511.23455" target="_blank" '
            'rel="noopener noreferrer">',
            listing,
        )
        self.assertEqual(listing.count("https://arxiv.org/abs/2511.23455"), 2)

    def test_uncited_entries_are_omitted(self) -> None:
        collector = self._collector()
        collector.marker_html("j")
        self.assertEqual(collector.list_html().count("<li "), 1)

    def test_no_citations_yields_no_list(self) -> None:
        self.assertEqual(self._collector().list_html(), "")

    def test_unknown_key_is_a_build_error_when_strict(self) -> None:
        collector = CitationCollector({}, CitationRendering(strict=True))
        with self.assertRaises(CitationError):
            collector.marker_html("missing")

    def test_unknown_key_is_tolerated_when_not_strict(self) -> None:
        collector = CitationCollector({}, CitationRendering(strict=False))
        self.assertIsNone(collector.marker_html("missing"))

    def test_unknown_format_names_the_known_ones(self) -> None:
        with self.assertRaises(CitationError) as ctx:
            CitationRendering().formatter("mla")
        self.assertIn("apa", str(ctx.exception))

    def test_custom_formatter_can_be_injected(self) -> None:
        config = CitationRendering(formatters={"shout": lambda e: str(e["title"]).upper()})
        collector = CitationCollector({"j": CSL_JOURNAL}, config)
        collector.marker_html("j")
        self.assertIn("THE PRICE OF PROGRESS", collector.list_html(fmt="shout"))


class ApaFormattingTests(unittest.TestCase):
    def test_string_author_list_is_inverted_with_initials(self) -> None:
        text = format_apa(CSL_JOURNAL)
        self.assertTrue(
            text.startswith(
                "Gundlach, H., Lynch, J., Mertens, M., & Thompson, N. (2025, November)."
            ),
            text,
        )

    def test_structured_author_names_are_supported(self) -> None:
        text = format_apa(
            {
                "type": "book",
                "title": "A Book",
                "author": [{"family": "Hofstadter", "given": "Douglas R."}],
                "publisher": "Basic Books",
                "issued": {"date-parts": [[1979]]},
            }
        )
        self.assertIn("Hofstadter, D. R. (1979). A Book. Basic Books.", text)

    def test_literal_author_is_passed_through(self) -> None:
        text = format_apa(
            {"type": "report", "title": "T", "author": [{"literal": "OpenAI"}]}
        )
        self.assertTrue(text.startswith("OpenAI. (n.d.). T."), text)

    def test_authorless_entry_leads_with_the_title_and_n_d(self) -> None:
        text = format_apa(CSL_WEBPAGE)
        self.assertTrue(
            text.startswith("Run long horizon tasks with Codex. (n.d.)."), text
        )

    def test_journal_volume_issue_and_pages(self) -> None:
        text = format_apa(
            {
                "type": "article-journal",
                "title": "T",
                "container-title": "Nature",
                "volume": "521",
                "issue": "7553",
                "page": "436-444",
                "issued": {"date-parts": [[2015, 5, 28]]},
                "author": [{"family": "LeCun", "given": "Yann"}],
            }
        )
        self.assertIn("(2015, May 28)", text)
        self.assertIn("Nature, 521(7553), 436-444.", text)

    def test_doi_becomes_a_resolver_url_when_there_is_no_url(self) -> None:
        entry = dict(CSL_JOURNAL)
        entry.pop("URL")
        self.assertIn("https://doi.org/10.48550/arXiv.2511.23455", format_apa(entry))


class AssetSrcSafetyTests(unittest.TestCase):
    def test_relative_paths_and_http_urls_are_allowed(self) -> None:
        self.assertEqual(assert_safe_asset_src("images/a.png"), "images/a.png")
        self.assertEqual(
            assert_safe_asset_src("https://cdn.example/a.png"), "https://cdn.example/a.png"
        )

    def test_script_and_data_urls_are_rejected(self) -> None:
        for bad in ("javascript:alert(1)", "data:image/png;base64,AAAA", "vbscript:x"):
            with self.subTest(src=bad), self.assertRaises(ImagePipelineError):
                assert_safe_asset_src(bad)

    def test_absolute_and_escaping_paths_are_rejected(self) -> None:
        for bad in ("/etc/passwd", "../../secrets/a.png", ""):
            with self.subTest(src=bad), self.assertRaises(ImagePipelineError):
                assert_safe_asset_src(bad)


class ImagePipelineTests(unittest.TestCase):
    def _builder(self, tmp: Path, **kwargs: object) -> ImageBuilder:
        content = tmp / "content"
        _write_images(content / "images")
        pipeline = ImagePipeline(**kwargs)  # type: ignore[arg-type]
        return ImageBuilder(pipeline, content_dir=content, out_dir=tmp / "dist")

    def test_raster_gets_srcset_sizes_and_intrinsic_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            html = builder.render(
                ImageRequest(src="images/chart.png", alt="Chart", layout="full")
            )
            self.assertIn('width="2400" height="1350"', html)
            self.assertIn('sizes="(max-width: 48rem) 100vw, 48rem"', html)
            self.assertIn('type="image/webp"', html)
            self.assertIn("chart-480.webp 480w", html)
            self.assertIn("chart-1920.png 1920w", html)
            self.assertIn('loading="lazy" decoding="async"', html)
            self.assertIn('class="papyrus-image papyrus-image--full"', html)

    def test_never_upscales_beyond_the_source_width(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            html = builder.render(ImageRequest(src="images/small.jpg", alt="S"))
            self.assertIn("small-480.jpg 480w", html)
            self.assertIn("small-640.jpg 640w", html)
            for too_wide in ("small-768", "small-1024", "small-1920"):
                self.assertNotIn(too_wide, html)

    def test_max_width_caps_the_largest_rendition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp), max_width=1024)
            html = builder.render(ImageRequest(src="images/chart.png", alt="C"))
            self.assertIn("chart-1024", html)
            self.assertNotIn("chart-1366", html)
            self.assertNotIn("chart-2400", html)

    def test_svg_passes_through_without_renditions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            html = builder.render(ImageRequest(src="images/logo.svg", alt="Logo"))
            self.assertIn("assets/responsive/images/logo.svg", html)
            self.assertNotIn("srcset", html)
            self.assertIn('width="120" height="60"', html)
            self.assertTrue(
                (Path(tmp) / "dist" / "assets" / "responsive" / "images" / "logo.svg").is_file()
            )

    def test_gif_passes_through_without_renditions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            html = builder.render(ImageRequest(src="images/spin.gif", alt="Spin"))
            self.assertIn("assets/responsive/images/spin.gif", html)
            self.assertNotIn("srcset", html)
            self.assertTrue(
                (Path(tmp) / "dist" / "assets" / "responsive" / "images" / "spin.gif").is_file()
            )

    def test_depth_prefixes_every_asset_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            html = builder.render(ImageRequest(src="images/chart.png", alt="C"), depth=1)
            self.assertIn('src="../assets/responsive/images/chart-1024.png"', html)
            self.assertNotIn('src="assets/', html)

    def test_eager_loading_requests_high_fetch_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            html = builder.render(
                ImageRequest(src="images/chart.png", alt="C", loading="eager")
            )
            self.assertIn('loading="eager" fetchpriority="high"', html)

    def test_caption_and_credit_render_a_figcaption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            html = builder.render(
                ImageRequest(
                    src="images/chart.png", alt="C", caption="Cap", credit="Anthus"
                )
            )
            self.assertIn("<figcaption>Cap · ", html)
            self.assertIn('<span class="papyrus-image-credit">Anthus</span>', html)

    def test_bare_request_emits_no_figure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            html = builder.render(ImageRequest(src="images/chart.png", alt="C", bare=True))
            self.assertNotIn("<figure", html)

    def test_verbatim_layout_class_is_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            off = self._builder(Path(tmp) / "a").render(
                ImageRequest(src="images/chart.png", layout="centered")
            )
            on = self._builder(Path(tmp) / "b", emit_layout_class_verbatim=True).render(
                ImageRequest(src="images/chart.png", layout="centered")
            )
            self.assertIn('class="papyrus-image papyrus-image--centered"', off)
            self.assertIn('class="papyrus-image papyrus-image--centered centered"', on)

    def test_unknown_layout_lists_the_known_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            with self.assertRaises(ImagePipelineError) as ctx:
                builder.render(ImageRequest(src="images/chart.png", layout="sideways"))
            self.assertIn("centered", str(ctx.exception))

    def test_missing_file_fails_the_build_when_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            with self.assertRaises(ImagePipelineError):
                builder.render(ImageRequest(src="images/absent.png"))

    def test_missing_file_is_skipped_when_not_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp), strict=False)
            self.assertEqual(builder.render(ImageRequest(src="images/absent.png")), "")

    def test_remote_url_is_emitted_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            html = builder.render(ImageRequest(src="https://cdn.example/a.png", alt="R"))
            self.assertIn('src="https://cdn.example/a.png"', html)
            self.assertNotIn("srcset", html)

    def test_alt_text_is_escaped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            html = builder.render(
                ImageRequest(src="images/chart.png", alt='Evil" onload="x')
            )
            self.assertNotIn('onload="x"', html)
            self.assertIn("&quot;", html)

    def test_wrapped_alt_and_caption_collapse_to_one_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            html = builder.render(
                ImageRequest(
                    src="images/chart.png",
                    alt="A long alt\n  wrapped by the author",
                    caption="A caption\nalso wrapped",
                )
            )
            self.assertIn('alt="A long alt wrapped by the author"', html)
            self.assertIn("<figcaption>A caption also wrapped</figcaption>", html)
            self.assertNotIn("\n", html)

    def test_derivatives_live_in_a_cache_outside_the_output_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            builder = self._builder(Path(tmp))
            builder.render(ImageRequest(src="images/chart.png"))
            cached = builder.cache_dir / "assets" / "responsive" / "images" / "chart-480.webp"
            published = (
                Path(tmp) / "dist" / "assets" / "responsive" / "images" / "chart-480.webp"
            )
            self.assertTrue(cached.is_file(), cached)
            self.assertTrue(published.is_file(), published)


class RenderFragmentTests(unittest.TestCase):
    """End-to-end, through the real ``markus`` CLI."""

    def _page(self, body: str) -> tuple[Path, Path]:
        tmp = Path(tempfile.mkdtemp())
        content = tmp / "content"
        _write_images(content / "images")
        source = content / "page.md"
        source.write_text(body, encoding="utf-8")
        return tmp, source

    def test_capabilities_off_is_plain_markus_output(self) -> None:
        tmp, source = self._page(
            "---\ntitle: T\n---\n\n![A](images/small.jpg)\n\nCite [@x].\n"
        )
        fragment = render_fragment(source, theme=None)
        self.assertIn('<img src="images/small.jpg" alt="A" />', fragment)
        self.assertIn("[@x]", fragment)
        self.assertNotIn("srcset", fragment)
        self.assertFalse((tmp / "content" / ".papyrus-image-cache").exists())

    def test_full_pipeline_renders_images_and_citations(self) -> None:
        tmp, source = self._page(
            """---
title: T
citations:
  j:
    type: article-journal
    title: Price of Progress
    author: ["Hans Gundlach"]
    container-title: arXiv
    URL: https://arxiv.org/abs/2511.23455
    issued: {date-parts: [[2025, 11]]}
  w:
    type: webpage
    title: Codex
    container-title: OpenAI Developers
    URL: https://developers.openai.com/x
---

Claim one [@j] and claim two [@w] and claim three [@j].

::image{src="images/chart.png" layout="full" alt="Chart" caption="Cap"}

![Plain](images/small.jpg)

::citations{format="apa"}
"""
        )
        pipeline = ImagePipeline()
        builder = ImageBuilder(
            pipeline, content_dir=tmp / "content", out_dir=tmp / "dist"
        )
        fragment = render_fragment(
            source,
            theme=None,
            depth=1,
            images=pipeline,
            image_builder=builder,
            citations=CitationRendering(),
        )
        # Citations: first-reference order, repeat reuses the number.
        self.assertIn('<span class="citation"><a href="#citation-1">1</a></span>', fragment)
        self.assertIn('<span class="citation"><a href="#citation-2">2</a></span>', fragment)
        self.assertEqual(fragment.count('href="#citation-1"'), 2)
        self.assertIn('<ol class="citationslist">', fragment)
        self.assertIn('<li id="citation-1">', fragment)
        self.assertIn("Gundlach, H. (2025, November).", fragment)
        # The bibliography replaced the sentinel paragraph, not nested in one.
        self.assertNotIn('<p><ol class="citationslist">', fragment)
        # Images: directive figure plus an upgraded plain Markdown image.
        self.assertIn('class="papyrus-image papyrus-image--full"', fragment)
        self.assertIn("<figcaption>Cap</figcaption>", fragment)
        self.assertIn("../assets/responsive/images/chart-480.webp 480w", fragment)
        self.assertIn('class="papyrus-image papyrus-image--inline"', fragment)
        self.assertIn("../assets/responsive/images/small-480.webp 480w", fragment)
        self.assertNotIn("PAPYRUSMARKUP", fragment)

    def test_inline_markdown_image_is_upgraded_without_a_figure(self) -> None:
        tmp, source = self._page(
            "---\ntitle: T\n---\n\nAn ![inline](images/small.jpg) image mid-sentence.\n"
        )
        pipeline = ImagePipeline()
        builder = ImageBuilder(
            pipeline, content_dir=tmp / "content", out_dir=tmp / "dist"
        )
        fragment = render_fragment(
            source, theme=None, images=pipeline, image_builder=builder
        )
        self.assertIn("srcset=", fragment)
        self.assertIn("<p>An <picture>", fragment)
        self.assertNotIn("<figure", fragment)

    def test_markus_figure_images_are_upgraded_in_place(self) -> None:
        tmp, source = self._page(
            '---\ntitle: T\n---\n\n:::figure{src="images/chart.png" alt="C" caption="K"}\n:::\n'
        )
        pipeline = ImagePipeline()
        builder = ImageBuilder(
            pipeline, content_dir=tmp / "content", out_dir=tmp / "dist"
        )
        fragment = render_fragment(
            source, theme=None, images=pipeline, image_builder=builder
        )
        self.assertIn('<figure class="markus-figure">', fragment)
        self.assertIn("srcset=", fragment)
        self.assertIn("<figcaption>K</figcaption>", fragment)
        self.assertNotIn("papyrus-image--", fragment)

    def test_plain_image_upgrade_can_be_disabled(self) -> None:
        tmp, source = self._page("---\ntitle: T\n---\n\n![A](images/small.jpg)\n")
        pipeline = ImagePipeline(upgrade_plain_images=False)
        builder = ImageBuilder(
            pipeline, content_dir=tmp / "content", out_dir=tmp / "dist"
        )
        fragment = render_fragment(
            source, theme=None, images=pipeline, image_builder=builder
        )
        self.assertNotIn("srcset", fragment)


class BuildIntegrationTests(unittest.TestCase):
    def _site(self, tmp: Path) -> Path:
        content = tmp / "content"
        (content / "articles").mkdir(parents=True)
        _write_images(content / "images")
        (content / "index.md").write_text(
            "---\ntitle: Home\n---\n\n# Home\n\n![Home shot](images/small.jpg)\n",
            encoding="utf-8",
        )
        (content / "articles" / "demo.md").write_text(
            """---
title: Demo
citations:
  j:
    type: webpage
    title: A Source
    URL: https://example.org/a
---

# Demo

Body [@j].

::image{src="images/chart.png" layout="full" alt="Chart"}

::citations{}
""",
            encoding="utf-8",
        )
        return content

    def test_opted_in_build_emits_responsive_assets_at_each_depth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            content = self._site(root)
            result = build_markus_site(
                content_dir=content,
                out_dir=root / "dist",
                theme=None,
                images=ImagePipeline(),
                citations=CitationRendering(),
            )
            article = (root / "dist" / "articles" / "demo.html").read_text(encoding="utf-8")
            index = (root / "dist" / "index.html").read_text(encoding="utf-8")

            self.assertIn('src="../assets/responsive/images/chart-1024.png"', article)
            self.assertIn('<ol class="citationslist">', article)
            self.assertIn('<span class="citation">', article)
            # depth 0: no ../ prefix on the home page's assets
            self.assertIn('src="assets/responsive/images/small-640.jpg"', index)
            self.assertNotIn('src="../assets/', index)
            self.assertTrue(
                (root / "dist" / "assets" / "responsive" / "images" / "chart-480.webp").is_file()
            )
            self.assertEqual(
                [p.relative_to(root / "dist").as_posix() for p in result.pages],
                ["index.html", "articles/demo.html"],
            )

    def test_default_build_is_untouched_by_the_new_capabilities(self) -> None:
        """The compatibility guarantee Pilobol.us depends on.

        A publication that never opts in keeps getting raw Markus output: no
        responsive derivatives, no citation rewriting, no image cache
        directory, and ``[@key]``-looking prose left exactly as written.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            content = root / "content"
            (content / "articles").mkdir(parents=True)
            _write_images(content / "images")
            (content / "articles" / "demo.md").write_text(
                "---\ntitle: Demo\n---\n\n# Demo\n\nProse with [@j] in it.\n\n"
                "![Plain](images/small.jpg)\n",
                encoding="utf-8",
            )
            build_markus_site(content_dir=content, out_dir=root / "dist", theme=None)
            article = (root / "dist" / "articles" / "demo.html").read_text(encoding="utf-8")
            self.assertIn("[@j]", article)
            self.assertIn('<img src="images/small.jpg" alt="Plain" />', article)
            self.assertNotIn("srcset", article)
            self.assertNotIn("citationslist", article)
            self.assertFalse((root / "dist" / "assets" / "responsive").exists())
            self.assertFalse((content / ".papyrus-image-cache").exists())

    def test_image_directive_without_the_pipeline_fails_loudly(self) -> None:
        """``::image{}`` is Papyrus markup; Markus rejects it if we never lower it.

        Documented behaviour rather than a silent downgrade -- a publication
        whose content uses the directive but whose build script forgot
        ``images=`` should hear about it, with Markus naming the directive.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            content = self._site(root)
            with self.assertRaises(RuntimeError) as ctx:
                build_markus_site(
                    content_dir=content, out_dir=root / "dist", theme=None
                )
            self.assertIn("Unknown directive 'image'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
