"""Tests for ``ImagePipeline(gatsby_parity=True)``: gatsby-plugin-image's behaviour.

Covers breakpoints, format choice (alpha vs opaque), the blurred placeholder,
eager-first-N, the aspect-ratio frame, the wrap hook's placeholder, and AVIF
failing loudly. AVIF encoding itself needs Pillow >= 11.3; the cases that
really encode skip on older Pillow, and the fail-loud case does not.
"""

from __future__ import annotations

import base64
import io
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, features

from papyrus_content.markus_renderer.images import (
    FADE_IN_SCRIPT,
    ImageBuilder,
    ImagePipeline,
    ImagePipelineError,
    ImageRequest,
    gatsby_sizes,
    gatsby_widths,
    image_has_alpha,
)

try:
    HAS_AVIF = bool(features.check("avif"))
except ValueError:
    HAS_AVIF = False
needs_avif = unittest.skipUnless(HAS_AVIF, "Pillow without AVIF (needs >= 11.3)")

#: AVIF-free configuration, so most cases run on any Pillow.
WEBP_ONLY = {"formats": ("webp",)}


def _photo(path: Path, size=(2000, 1000), mode="RGB") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new(mode, size, (30, 90, 160, 255) if mode == "RGBA" else (30, 90, 160))
    image.save(path)


def _builder(tmp: Path, **kwargs: object) -> ImageBuilder:
    content = tmp / "content"
    kwargs.setdefault("formats", ("webp",))
    pipeline = ImagePipeline(gatsby_parity=True, **kwargs)  # type: ignore[arg-type]
    return ImageBuilder(pipeline, content_dir=content, out_dir=tmp / "dist")


class BreakpointTests(unittest.TestCase):
    def test_source_width_displays_at_quarter_half_and_full(self) -> None:
        # What anth.us ships: a 2048px source gets 512/1024/2048.
        self.assertEqual(gatsby_widths(2048), ([512, 1024, 2048], 2048))
        self.assertEqual(gatsby_widths(1200), ([300, 600, 1200], 1200))

    def test_retina_density_needs_a_larger_source(self) -> None:
        widths, display = gatsby_widths(2000, display_width=800)
        self.assertEqual((widths, display), ([200, 400, 800, 1600], 800))

    def test_display_width_is_capped_at_the_source(self) -> None:
        widths, display = gatsby_widths(500, display_width=800)
        self.assertEqual((widths, display), ([125, 250, 500], 500))

    def test_max_width_is_a_hard_ceiling(self) -> None:
        self.assertEqual(gatsby_widths(4096, max_width=1366), ([342, 683, 1366], 1366))

    def test_sizes_match_gatsbys_constrained_layout(self) -> None:
        self.assertEqual(gatsby_sizes(2048), "(min-width: 2048px) 2048px, 100vw")

    def test_markup_uses_density_widths_and_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _photo(tmp / "content/images/p.png", (2000, 1000))
            html = _builder(tmp).render(ImageRequest(src="images/p.png", alt="P"))
            self.assertIn('sizes="(min-width: 2000px) 2000px, 100vw"', html)
            for width in (500, 1000, 2000):
                self.assertIn(f"p-{width}.webp {width}w", html)
                self.assertIn(f"p-{width}.jpg {width}w", html)
            self.assertNotIn("p-480", html)
            # The <img src> is the full-size (1x) rendition.
            self.assertRegex(html, r'<img [^>]*src="[^"]*p-2000\.jpg"')


class FormatTests(unittest.TestCase):
    def test_opaque_png_falls_back_to_jpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _photo(tmp / "content/images/p.png", mode="RGBA")  # RGBA but fully opaque
            html = _builder(tmp).render(ImageRequest(src="images/p.png"))
            self.assertIn("p-2000.jpg", html)
            self.assertNotIn(".png", html.split("<img", 1)[1].split("srcset")[0])

    def test_real_transparency_falls_back_to_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            path = tmp / "content/images/logo.png"
            path.parent.mkdir(parents=True)
            image = Image.new("RGBA", (800, 400), (0, 0, 0, 0))
            image.paste((255, 0, 0, 255), (0, 0, 400, 400))
            image.save(path)
            html = _builder(tmp).render(ImageRequest(src="images/logo.png"))
            self.assertIn("logo-800.png 800w", html)
            self.assertNotIn(".jpg", html)

    def test_alpha_detection(self) -> None:
        self.assertFalse(image_has_alpha(Image.new("RGB", (4, 4))))
        self.assertFalse(image_has_alpha(Image.new("RGBA", (4, 4), (1, 2, 3, 255))))
        self.assertTrue(image_has_alpha(Image.new("RGBA", (4, 4), (1, 2, 3, 0))))

    def test_source_order_is_modern_first_then_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _photo(tmp / "content/images/p.jpg")
            html = _builder(tmp).render(ImageRequest(src="images/p.jpg"))
            order = re.findall(r'<source type="(image/\w+)"|<img [^>]*data-main-image', html)
            self.assertEqual(order[0], "image/webp")

    @needs_avif
    def test_avif_then_webp_then_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _photo(tmp / "content/images/p.png")
            html = _builder(tmp, formats=None).render(ImageRequest(src="images/p.png"))
            types = re.findall(r'<source type="(image/\w+)"', html)
            self.assertEqual(types, ["image/avif", "image/webp"])
            self.assertTrue(list((tmp / "dist").rglob("p-1000.avif")))

    def test_avif_configured_but_unavailable_fails_loudly(self) -> None:
        real = features.check

        def no_avif(name: str) -> bool:
            return False if name == "avif" else real(name)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _photo(tmp / "content/images/p.png")
            with mock.patch.object(features, "check", no_avif):
                with self.assertRaises(ImagePipelineError) as ctx:
                    _builder(tmp, formats=None)
            self.assertIn("avif", str(ctx.exception))
            self.assertIn("Pillow", str(ctx.exception))

    def test_unavailable_format_fails_in_legacy_mode_too(self) -> None:
        real = features.check
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                features, "check", lambda n: False if n == "avif" else real(n)
            ):
                with self.assertRaises(ImagePipelineError):
                    ImageBuilder(
                        ImagePipeline(formats=("avif", "webp")),
                        content_dir=Path(tmp),
                        out_dir=Path(tmp) / "dist",
                    )

    def test_parity_defaults_to_avif_and_webp(self) -> None:
        self.assertEqual(ImagePipeline(gatsby_parity=True).resolved_formats(), ("avif", "webp"))
        self.assertEqual(ImagePipeline().resolved_formats(), ("webp",))
        self.assertEqual(ImagePipeline(gatsby_parity=True).resolved_quality(), 70)
        self.assertEqual(ImagePipeline().resolved_quality(), 82)


class PlaceholderTests(unittest.TestCase):
    def _html(self, tmp: Path, **kwargs: object) -> str:
        _photo(tmp / "content/images/p.png", (2000, 1000))
        return _builder(tmp, **kwargs).render(ImageRequest(src="images/p.png", alt="P"))

    def test_blurred_placeholder_is_a_tiny_inline_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html = self._html(Path(tmp))
            match = re.search(
                r'<img aria-hidden="true" data-placeholder-image="" alt="" '
                r'src="data:image/jpeg;base64,([^"]+)"',
                html,
            )
            self.assertIsNotNone(match)
            tiny = Image.open(io.BytesIO(base64.b64decode(match.group(1))))
            self.assertEqual(tiny.size, (20, 10))
            self.assertLess(len(match.group(1)), 2000)

    def test_placeholder_none_reserves_the_box_but_draws_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html = self._html(Path(tmp), placeholder=None)
            self.assertNotIn('data-placeholder-image=""', html)
            self.assertIn("aspect-ratio:2000 / 1000", html)

    def test_unknown_placeholder_is_rejected(self) -> None:
        with self.assertRaises(ImagePipelineError):
            ImagePipeline(gatsby_parity=True, placeholder="dominantColor")

    def test_wrap_hook_receives_the_placeholder(self) -> None:
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _photo(tmp / "content/images/p.png")

            def wrap(w):
                seen.append(w)
                return f"<div>{w.inner}</div>"

            builder = _builder(tmp, wrap=wrap)
            html = builder.render(ImageRequest(src="images/p.png"))
        self.assertTrue(seen[0].placeholder.startswith("data:image/jpeg;base64,"))
        self.assertEqual((seen[0].width, seen[0].height), (2000, 1000))
        self.assertEqual(seen[0].display_width, 2000)
        # The hook owns the DOM: no frame and no support block from Papyrus.
        self.assertNotIn("papyrus-image-frame", html)
        self.assertNotIn("<script>", html)
        self.assertIn('data-main-image=""', html)


class FrameAndFadeTests(unittest.TestCase):
    def test_default_figure_has_an_aspect_ratio_frame_and_fade_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _photo(tmp / "content/images/p.png", (2000, 1000))
            html = _builder(tmp).render(ImageRequest(src="images/p.png", layout="full"))
            self.assertIn("data-papyrus-image-frame", html)
            self.assertIn("max-width:2000px;aspect-ratio:2000 / 1000", html)
            self.assertIn(FADE_IN_SCRIPT, html)
            self.assertIn("<noscript><style>", html)
            self.assertIn("opacity:0", html)

    def test_support_block_is_emitted_once_per_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _photo(tmp / "content/images/p.png")
            builder = _builder(tmp)
            first = builder.render(ImageRequest(src="images/p.png"))
            second = builder.render(ImageRequest(src="images/p.png"))
            self.assertIn("<script>", first)
            self.assertNotIn("<script>", second)
            builder.start_page()
            self.assertIn("<script>", builder.render(ImageRequest(src="images/p.png")))

    def test_bare_images_get_no_frame_and_stay_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _photo(tmp / "content/images/p.png")
            html = _builder(tmp).render(ImageRequest(src="images/p.png", bare=True))
            self.assertNotIn("data-main-image", html)
            self.assertNotIn("frame", html)


class EagerLoadingTests(unittest.TestCase):
    def test_first_n_images_per_page_are_eager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _photo(tmp / "content/images/p.png")
            builder = _builder(tmp, eager_first=2)
            loads = [
                re.search(r'loading="(\w+)"', builder.render(ImageRequest(src="images/p.png"))).group(1)
                for _ in range(4)
            ]
            self.assertEqual(loads, ["eager", "eager", "lazy", "lazy"])
            builder.start_page()
            again = builder.render(ImageRequest(src="images/p.png"))
            self.assertIn('loading="eager" fetchpriority="high"', again)

    def test_explicit_request_loading_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _photo(tmp / "content/images/p.png")
            html = _builder(tmp, eager_first=5).render(
                ImageRequest(src="images/p.png", loading="lazy")
            )
            self.assertIn('loading="lazy"', html)

    def test_legacy_mode_ignores_eager_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            _photo(tmp / "content/images/p.png")
            builder = ImageBuilder(
                ImagePipeline(eager_first=5), content_dir=tmp / "content", out_dir=tmp / "dist"
            )
            self.assertIn('loading="lazy"', builder.render(ImageRequest(src="images/p.png")))


if __name__ == "__main__":
    unittest.main()
