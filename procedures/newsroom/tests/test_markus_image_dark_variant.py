"""Tests for ``srcDark`` / ``.dark`` pairing on ``::image{}``."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from papyrus_content.markus_renderer.content_markup import ContentMarkupError, prepare_page
from papyrus_content.markus_renderer.images import (
    DARK_VARIANT_CSS,
    ImageBuilder,
    ImagePipeline,
    ImagePipelineError,
    ImageRequest,
    dark_sibling_candidates,
)


def _png(path: Path, size=(800, 600)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 20, 30)).save(path)


def _builder(tmp: Path, **kwargs: object) -> ImageBuilder:
    kwargs.setdefault("formats", ("webp",))
    kwargs.setdefault("widths", (200, 400))
    return ImageBuilder(ImagePipeline(**kwargs), content_dir=tmp / "content", out_dir=tmp / "dist")  # type: ignore[arg-type]


class DarkVariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        _png(self.tmp / "content/a.png")
        _png(self.tmp / "content/a.dark.png")

    def test_candidates_prefer_same_suffix(self) -> None:
        names = dark_sibling_candidates("x/a.png")
        self.assertEqual(names[0], "x/a.dark.png")
        self.assertIn("x/a.dark.svg", names)

    def test_pair_emits_two_variants_and_css_once_per_page(self) -> None:
        builder = _builder(self.tmp)
        html = builder.render(ImageRequest(src="a.png", alt="x", src_dark="a.dark.png"))
        self.assertEqual(html.count('class="papyrus-image-light"'), 1)
        self.assertEqual(html.count('class="papyrus-image-dark"'), 1)
        self.assertIn(DARK_VARIANT_CSS, html)
        again = builder.render(ImageRequest(src="a.png", alt="x", src_dark="a.dark.png"))
        self.assertNotIn("<style>", again)
        builder.start_page()
        self.assertIn("<style>", builder.render(ImageRequest(src="a.png", alt="x", src_dark="a.dark.png")))

    def test_dark_images_are_lazy_even_when_light_is_eager(self) -> None:
        builder = _builder(self.tmp)
        html = builder.render(ImageRequest(src="a.png", src_dark="a.dark.png", loading="eager"))
        dark = html.split('class="papyrus-image-dark"', 1)[1]
        self.assertIn('loading="lazy"', dark)
        self.assertNotIn("eager", dark)

    def test_gatsby_parity_pair_has_a_frame_per_variant(self) -> None:
        builder = _builder(self.tmp, gatsby_parity=True)
        html = builder.render(ImageRequest(src="a.png", src_dark="a.dark.png"))
        self.assertEqual(html.count('data-papyrus-image-frame=""'), 2)
        self.assertEqual(html.count("<script>"), 1)
        self.assertEqual(html.count("aspect-ratio:800 / 600"), 2)

    def test_pairing_by_name_only_for_directives(self) -> None:
        builder = _builder(self.tmp)
        plain = builder.render(ImageRequest(src="a.png"))
        self.assertNotIn("papyrus-image-dark", plain)
        paired = builder.render(ImageRequest(src="a.png", pair_by_name=True))
        self.assertIn("papyrus-image-dark", paired)

    def test_srcdark_none_opts_out(self) -> None:
        html = _builder(self.tmp).render(ImageRequest(src="a.png", src_dark="none", pair_by_name=True))
        self.assertNotIn("papyrus-image-dark", html)

    def test_bare_pair_uses_spans(self) -> None:
        html = _builder(self.tmp).render(ImageRequest(src="a.png", src_dark="a.dark.png", bare=True))
        self.assertIn('<span class="papyrus-image-dark">', html)
        self.assertNotIn("<figure", html)

    def test_one_pixel_rounding_is_tolerated(self) -> None:
        _png(self.tmp / "content/b.png", (2364, 3552))
        _png(self.tmp / "content/b.dark.png", (2364, 3551))
        self.assertIn("papyrus-image-dark", _builder(self.tmp).render(ImageRequest(src="b.png", src_dark="b.dark.png")))

    def test_errors_name_the_image(self) -> None:
        builder = _builder(self.tmp)
        with self.assertRaisesRegex(ImagePipelineError, r"'a.png'.*gone.png"):
            builder.render(ImageRequest(src="a.png", src_dark="gone.png"))
        _png(self.tmp / "content/c.png", (800, 400))
        with self.assertRaisesRegex(ImagePipelineError, r"'a.png'.*aspect ratio"):
            builder.render(ImageRequest(src="a.png", src_dark="c.png"))
        with self.assertRaisesRegex(ImagePipelineError, "not a URL"):
            builder.render(ImageRequest(src="a.png", src_dark="https://example.com/x.png"))
        with self.assertRaises(ImagePipelineError):
            builder.render(ImageRequest(src="a.png", src_dark="/etc/passwd"))

    def test_svg_pair_is_passed_through(self) -> None:
        for name in ("s.svg", "s.dark.svg"):
            (self.tmp / "content" / name).write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="5"/>')
        html = _builder(self.tmp).render(ImageRequest(src="s.svg", pair_by_name=True))
        self.assertIn("s.dark.svg", html)
        self.assertNotIn("<picture>", html)


class StoredRenditionTests(unittest.TestCase):
    """The projector path: renditions made at upload, read back without opening images."""

    def _store(self, tmp: Path, sizes: dict[str, tuple[int, int]]):
        from papyrus_content.renditions import DirectoryRenditionStore, make_renditions, settings_from_mapping

        settings = settings_from_mapping({"formats": ["webp"], "widths": [200, 400]})
        store = DirectoryRenditionStore(tmp / "site")
        for name, size in sizes.items():
            _png(tmp / name, size)
            make_renditions(settings, store, name, (tmp / name).read_bytes())
        return settings, store

    def test_pair_by_name_and_errors_from_stored_records(self) -> None:
        from papyrus_content.renditions import RenditionCatalog, StoredRenditionImageBuilder

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings, store = self._store(
                tmp, {"a.png": (800, 600), "a.dark.png": (800, 600), "w.png": (800, 400)}
            )
            builder = StoredRenditionImageBuilder(settings.pipeline, RenditionCatalog(store, settings.pipeline))
            html = builder.render(ImageRequest(src="a.png", pair_by_name=True))
            self.assertIn("papyrus-image-dark", html)
            self.assertIn("a.dark-", html)
            with self.assertRaisesRegex(ImagePipelineError, "aspect ratio"):
                builder.render(ImageRequest(src="a.png", src_dark="w.png"))
            with self.assertRaisesRegex(ImagePipelineError, "'a.png'.*nope.png"):
                builder.render(ImageRequest(src="a.png", src_dark="nope.png"))
            self.assertNotIn("papyrus-image-dark", builder.render(ImageRequest(src="w.png", pair_by_name=True)))


class DirectiveTests(unittest.TestCase):
    def test_srcdark_attribute_is_parsed(self) -> None:
        page = prepare_page('::image{src="a.png" srcDark="a.dark.png" alt="x"}\n', images=ImagePipeline(), citations=None)
        request = next(iter(page.images.values()))
        self.assertEqual(request.src_dark, "a.dark.png")
        self.assertTrue(request.pair_by_name)

    def test_unknown_attributes_still_rejected_and_list_srcdark(self) -> None:
        with self.assertRaisesRegex(ContentMarkupError, "srcDark"):
            prepare_page('::image{src="a.png" bogus="1"}\n', images=ImagePipeline(), citations=None)


if __name__ == "__main__":
    unittest.main()
