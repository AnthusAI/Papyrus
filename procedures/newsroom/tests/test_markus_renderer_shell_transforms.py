from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from papyrus_content.markus_renderer.build import build_markus_site
from papyrus_content.markus_renderer.convert import convert_fragment
from papyrus_content.markus_renderer.shell import (
    BodyParts,
    NavItem,
    PageContext,
    SiteChrome,
    render_page,
)
from papyrus_content.markus_renderer.transforms import (
    BLOCK_CLOSE,
    BLOCK_OPEN,
    FragmentTransform,
    FragmentTransformError,
    block_sentinel,
    inline_sentinel,
)

FIXTURES = Path(__file__).parent / "fixtures" / "markus_shell"
HAS_MARKUS = shutil.which("markus") is not None


def _home_nav() -> list[NavItem]:
    return [NavItem("Home", "index.html")]


def _alpha_nav() -> list[NavItem]:
    return [NavItem("Home", "index.html"), NavItem("Alpha", "articles/alpha.html")]


def _render_depth0(chrome: SiteChrome) -> str:
    # A title equal to the site name selects ``same_title_template``.
    return render_page(
        title=chrome.site_name,
        fragment="<p>Home.</p>",
        active_href="index.html",
        nav_items=_home_nav(),
        chrome=chrome,
    )


class DefaultShellGoldenTests(unittest.TestCase):
    """Golden strings captured from develop @ d0b00b3, before the shell seams."""

    def test_depth0_default_chrome_is_unchanged(self) -> None:
        html = _render_depth0(SiteChrome(site_name="Test Site"))
        self.assertEqual(html, (FIXTURES / "depth0.html").read_text(encoding="utf-8"))

    def test_depth1_with_tagline_scripts_and_version_is_unchanged(self) -> None:
        html = render_page(
            title="Alpha",
            fragment="<p>Body.</p>",
            active_href="articles/alpha.html",
            nav_items=_alpha_nav(),
            depth=1,
            chrome=SiteChrome(
                site_name="Test Site", tagline="A tagline", scripts=("assets/x.js",)
            ),
            css_version="abc123",
        )
        self.assertEqual(html, (FIXTURES / "depth1.html").read_text(encoding="utf-8"))


class ShellSeamTests(unittest.TestCase):
    def test_lang_and_body_class(self) -> None:
        html = _render_depth0(SiteChrome(site_name="S", lang="fr", body_class="layout"))
        self.assertIn('<html lang="fr">', html)
        self.assertIn('<body class="layout">', html)

    def test_stylesheets_replace_the_defaults(self) -> None:
        html = _render_depth0(SiteChrome(site_name="S", stylesheets=("css/a.css",)))
        self.assertIn('<link rel="stylesheet" href="css/a.css">', html)
        self.assertNotIn("markus-vendor.css", html)
        self.assertNotIn("site-theme.css", html)

    def test_head_html_follows_title(self) -> None:
        html = _render_depth0(SiteChrome(site_name="S", head_html='<meta name="x">'))
        self.assertIn('</title><meta name="x">\n', html)

    def test_title_templates(self) -> None:
        chrome = SiteChrome(
            site_name="S", title_template="{title} | {site}", same_title_template="{site}!"
        )
        self.assertIn("<title>S!</title>", _render_depth0(chrome))
        article = render_page(
            title="Alpha",
            fragment="",
            active_href="articles/alpha.html",
            nav_items=_alpha_nav(),
            depth=1,
            chrome=chrome,
        )
        self.assertIn("<title>Alpha | S</title>", article)

    def test_asset_root_makes_links_site_absolute(self) -> None:
        html = render_page(
            title="Alpha",
            fragment="",
            active_href="articles/alpha.html",
            nav_items=_alpha_nav(),
            depth=1,
            chrome=SiteChrome(site_name="S", asset_root="/"),
        )
        self.assertIn('href="/css/site-theme.css"', html)
        self.assertIn('href="/index.html"', html)
        self.assertNotIn("../", html)

    def test_render_masthead_and_body_hooks(self) -> None:
        seen: dict[str, object] = {}

        def masthead(ctx: PageContext) -> str:
            seen["ctx"] = ctx
            return "<header>custom</header>"

        def body(ctx: PageContext, parts: BodyParts) -> str:
            seen["parts"] = parts
            return f"<div class=wrap>{parts.masthead}<main>{ctx.fragment}</main></div>"

        html = render_page(
            title="Alpha",
            fragment="<p>Body.</p>",
            active_href="articles/alpha.html",
            nav_items=_alpha_nav(),
            depth=1,
            chrome=SiteChrome(site_name="S", render_masthead=masthead, render_body=body),
            css_version="v1",
        )
        ctx = seen["ctx"]
        assert isinstance(ctx, PageContext)
        self.assertEqual(ctx.prefix, "../")
        self.assertEqual(ctx.asset_suffix, "?v=v1")
        self.assertEqual(ctx.depth, 1)
        self.assertEqual(ctx.nav_items, tuple(_alpha_nav()))
        parts = seen["parts"]
        assert isinstance(parts, BodyParts)
        self.assertEqual(parts.masthead, "<header>custom</header>")
        self.assertIn(
            "<div class=wrap><header>custom</header><main><p>Body.</p></main></div>", html
        )
        self.assertNotIn("markus-site-masthead", html)
        self.assertNotIn("markus-site-footer", html)


class FragmentTransformTests(unittest.TestCase):
    def test_default_transform_is_identity(self) -> None:
        fragment = '<div class="markus-document"><p class="x">hi</p></div>'
        self.assertEqual(FragmentTransform().apply(fragment), fragment)

    def test_inline_round_trip(self) -> None:
        fragment = f"<p>a {inline_sentinel('mark', 'hey')} b</p>"
        self.assertEqual(FragmentTransform().apply(fragment), "<p>a <mark>hey</mark> b</p>")

    def test_disallowed_inline_element_raises(self) -> None:
        with self.assertRaises(ValueError):
            inline_sentinel("script", "x")

    def test_inline_text_containing_a_sentinel_raises(self) -> None:
        with self.assertRaises(ValueError):
            inline_sentinel("mark", inline_sentinel("mark", "x"))

    def test_block_sentinel_requires_passthrough(self) -> None:
        fragment = f"<div>{block_sentinel('<svg></svg>')}</div>"
        with self.assertRaises(FragmentTransformError):
            FragmentTransform().apply(fragment)

    def test_block_passthrough_unwraps_sole_paragraph(self) -> None:
        markup = '<svg viewBox="0 0 1 1"><path d="M0 0"/></svg>'
        fragment = f"<p>{block_sentinel(markup)}</p>"
        out = FragmentTransform(allow_block_passthrough=True).apply(fragment)
        self.assertEqual(out, markup)

    def test_block_markup_is_not_reclassed(self) -> None:
        markup = '<table class="markus-table"><tr><td colspan="2">x</td></tr></table>'
        fragment = f'<div class="markus-table">{block_sentinel(markup)}</div>'
        out = FragmentTransform(
            class_map={"markus-table": "t"}, allow_block_passthrough=True
        ).apply(fragment)
        self.assertEqual(out, f'<div class="t">{markup}</div>')

    def test_surviving_sentinel_raises(self) -> None:
        with self.assertRaises(FragmentTransformError):
            FragmentTransform().apply(f"<p>{BLOCK_OPEN}not-base32{BLOCK_CLOSE}</p>")

    def test_class_map_and_prefix_drop(self) -> None:
        transform = FragmentTransform(
            class_map={"markus-document": "post post--body", "gone": ""},
            drop_unmapped_classes=("markus-",),
        )
        fragment = '<div class="markus-document keep markus-x"><p class="gone">a</p></div>'
        self.assertEqual(
            transform.apply(fragment), '<div class="post post--body keep"><p>a</p></div>'
        )


@unittest.skipUnless(HAS_MARKUS, "markus CLI not installed")
class MarkusPipelineTests(unittest.TestCase):
    """Sentinels must survive a real ``markus convert`` run, not just ``apply``."""

    def test_sentinels_survive_markus_convert(self) -> None:
        svg = '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>'
        source = (
            "# Title\n\n"
            f"Some {inline_sentinel('mark', 'highlighted *words*')} here.\n\n"
            f"{block_sentinel(svg)}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.md"
            path.write_text(source, encoding="utf-8")
            out = convert_fragment(
                path, transform=FragmentTransform(allow_block_passthrough=True)
            )
        self.assertIn("<mark>highlighted <em>words</em></mark>", out)
        self.assertIn(svg, out)
        self.assertNotIn(f"<p>{svg}", out)

    def test_build_threads_transform_and_skips_vendor_css(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "content"
            (content / "articles").mkdir(parents=True)
            (content / "articles" / "alpha.md").write_text(
                f"---\ntitle: Alpha\n---\n\nA {inline_sentinel('mark', 'm')}.\n",
                encoding="utf-8",
            )
            (content / "index.md").write_text(
                f"# Home\n\n{inline_sentinel('sup', '1')}\n", encoding="utf-8"
            )
            out = Path(tmp) / "dist"
            build_markus_site(
                content_dir=content, out_dir=out, transform=FragmentTransform(), vendor_css=False
            )
            self.assertFalse((out / "css" / "markus-vendor.css").exists())
            self.assertIn("<mark>m</mark>", (out / "articles" / "alpha.html").read_text("utf-8"))
            self.assertIn("<sup>1</sup>", (out / "index.html").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
