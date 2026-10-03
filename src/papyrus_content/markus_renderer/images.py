"""Build-time responsive image pipeline for Markus static sites.

Why this exists
---------------
Markus emits a bare ``<img src=... alt=...>`` for a Markdown image and for
``:::figure{src=...}``. That is correct but naive: one file at one size, no
intrinsic dimensions, so every image costs a full-resolution download and
shifts the layout as it loads.

Gatsby publications solved this with ``gatsby-plugin-image`` /
``childImageSharp.gatsbyImageData`` -- multiple widths, modern formats, a
``srcset``/``sizes`` pair, and width/height baked in. Porting such a
publication onto Papyrus means Papyrus needs the same capability, and it
needs it as a *renderer* feature rather than a per-site script, so the next
publication gets it for free.

Design constraints this module respects
---------------------------------------
* **Default-inert.** ``build_markus_site`` takes ``images=None`` by default
  and then does not touch fragments at all. Publications that have not opted
  in (Pilobol.us) get byte-identical output.
* **No publication names in here.** Layout names are generic editorial words
  (``full``, ``centered``, ``right``); widths, formats, ``sizes`` and the CSS
  class scheme are all configuration.
* **Pass-through for vector/animated.** ``.svg`` and ``.gif`` are never
  re-encoded or resized; they are emitted as a single ``<img>`` (with
  intrinsic dimensions when they can be read) exactly like Gatsby's
  ``publicURL`` fallback.
* **Never upscale.** Requested widths wider than the source are dropped.
"""

from __future__ import annotations

import html
import re
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable, Mapping

# Formats Pillow can resize/re-encode for us. Everything else is pass-through.
RASTER_SUFFIXES: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp", ".avif"})
PASSTHROUGH_SUFFIXES: frozenset[str] = frozenset({".gif", ".svg"})

_SUFFIX_FOR_FORMAT = {
    "webp": ".webp",
    "avif": ".avif",
    "jpeg": ".jpg",
    "png": ".png",
}
_MIME_FOR_FORMAT = {
    "webp": "image/webp",
    "avif": "image/avif",
    "jpeg": "image/jpeg",
    "png": "image/png",
}
_PILLOW_FORMAT_FOR_SUFFIX = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".avif": "AVIF",
}

# A publication's own CSS may key on bare layout words (``.full``). That is a
# porting affordance, not the framework default -- see
# ``ImagePipeline.emit_layout_class_verbatim``.
DEFAULT_LAYOUT_SIZES: Mapping[str, str] = {
    "full": "(max-width: 48rem) 100vw, 48rem",
    "wide": "(max-width: 64rem) 100vw, 64rem",
    "centered": "(max-width: 32rem) 100vw, 32rem",
    "center-small-image": "(max-width: 24rem) 100vw, 24rem",
    "center-full-image": "(max-width: 48rem) 100vw, 48rem",
    "left": "(max-width: 40rem) 50vw, 20rem",
    "right": "(max-width: 40rem) 50vw, 20rem",
    "right-aligned": "(max-width: 40rem) 50vw, 20rem",
    "inline": "(max-width: 48rem) 100vw, 48rem",
}

DEFAULT_LAYOUT = "inline"


class ImagePipelineError(RuntimeError):
    """Raised for an unusable image reference or an unknown layout name."""


def assert_safe_asset_src(src: str) -> str:
    """Reject anything that is not a relative path or an http(s) URL.

    The renderer deliberately runs Markus without ``--allow-html``; an author
    must not be able to smuggle a ``javascript:`` or ``data:`` URL back in
    through an image reference either.
    """
    value = (src or "").strip()
    if not value:
        raise ImagePipelineError("Image src is empty")
    lowered = value.lower()
    if lowered.startswith(("http://", "https://")):
        return value
    if ":" in value.split("/", 1)[0]:
        raise ImagePipelineError(
            f"Image src {src!r} must be a relative path or an http(s) URL"
        )
    if value.startswith("/"):
        raise ImagePipelineError(
            f"Image src {src!r} must be relative to the content directory, not absolute"
        )
    if ".." in Path(value).parts:
        raise ImagePipelineError(f"Image src {src!r} may not escape the content directory")
    return value


@dataclass(frozen=True)
class ImageWrap:
    """What a publication's ``ImagePipeline.wrap`` hook receives for one image.

    ``inner`` is the finished ``<picture>`` (or bare ``<img>``) the pipeline
    built; ``classes`` is what the default ``<figure>`` would have carried.
    ``width``/``height`` are the source's intrinsic pixel size when known, which
    is what a publication needs to reserve an aspect-ratio box.
    """

    request: "ImageRequest"
    layout: str
    classes: str
    inner: str
    width: int | None
    height: int | None


@dataclass(frozen=True)
class ImagePipeline:
    """Configuration for the responsive-image build step.

    ``source_dir`` is where a ``src`` such as ``images/chart.png`` resolves
    from; it defaults to the build's content directory. ``out_subdir`` is
    where derivatives are written inside the built site.
    """

    source_dir: Path | None = None
    #: Where generated derivatives are kept between builds. ``build_markus_site``
    #: wipes its output directory on every run, so without a cache outside that
    #: tree every build would re-encode every rendition of every image -- for a
    #: corpus the size of a real blog that is thousands of encodes per deploy.
    #: Defaults to ``<content_dir>/.papyrus-image-cache``; put it on the CI
    #: cache path (or commit it) to make rebuilds cheap.
    cache_dir: Path | None = None
    out_subdir: str = "assets/responsive"
    widths: tuple[int, ...] = (480, 768, 1024, 1366, 1920)
    #: Hard ceiling on rendition width. The source's own intrinsic width is
    #: always offered (so a 900px source still gets a 900w rendition rather
    #: than being capped at 768w) which means a 6000px original would
    #: otherwise ship a 6000w rendition. ``None`` means no ceiling.
    max_width: int | None = None
    #: Modern formats offered through ``<source>`` elements, best first.
    #: ``avif`` is silently dropped when the local Pillow cannot encode it.
    formats: tuple[str, ...] = ("webp",)
    quality: int = 82
    #: Width of the ``<img src=...>`` fallback (the largest rendition at or
    #: below this width is used).
    fallback_width: int = 1024
    layout_sizes: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_LAYOUT_SIZES))
    default_layout: str = DEFAULT_LAYOUT
    figure_class: str = "papyrus-image"
    layout_class_template: str = "papyrus-image--{layout}"
    #: Also emit the bare layout word as a class (``class="... full"``). Off by
    #: default; publications porting from a site whose CSS already keys on
    #: those words turn it on instead of rewriting their stylesheet.
    emit_layout_class_verbatim: bool = False
    default_loading: str = "lazy"
    #: Upgrade plain Markdown images and ``:::figure`` images too, not only
    #: explicit ``::image{}`` directives.
    upgrade_plain_images: bool = True
    #: Fail the build when a referenced image file is missing. Off means the
    #: original ``<img>`` is left untouched.
    strict: bool = True
    #: Replaces the default ``<figure>`` wrapper. Papyrus still owns the
    #: renditions, ``srcset`` and ``sizes``; the publication owns only the
    #: element around them -- for a port whose stylesheet expects a specific
    #: image DOM (an aspect-ratio sizer, a wrapper ``<div>``) that classes
    #: alone cannot produce. Not called for ``bare`` (inline) images.
    wrap: Callable[[ImageWrap], str] | None = None

    def resolved_source_dir(self, content_dir: Path) -> Path:
        return (self.source_dir or content_dir).resolve()

    def resolved_cache_dir(self, content_dir: Path) -> Path:
        return (self.cache_dir or (content_dir / ".papyrus-image-cache")).resolve()

    def sizes_for(self, layout: str) -> str:
        if layout in self.layout_sizes:
            return self.layout_sizes[layout]
        raise ImagePipelineError(
            f"Unknown image layout {layout!r}. Known layouts: "
            f"{', '.join(sorted(self.layout_sizes))}."
        )

    def classes_for(self, layout: str) -> str:
        parts = [self.figure_class, self.layout_class_template.format(layout=layout)]
        if self.emit_layout_class_verbatim:
            parts.append(layout)
        return " ".join(part for part in parts if part)


def collapse_whitespace(value: str | None) -> str:
    """Flatten author-wrapped prose into a single attribute-safe line.

    A long ``alt`` is routinely wrapped across source lines; a literal newline
    inside an HTML attribute is legal but renders as noise in the output and in
    anything that reads the file back.
    """
    return re.sub(r"\s+", " ", value).strip() if value else ""


@dataclass(frozen=True)
class ImageRequest:
    """One image to render, as parsed from the Markdown or from an ``<img>``."""

    src: str
    alt: str = ""
    layout: str | None = None
    caption: str | None = None
    credit: str | None = None
    sizes: str | None = None
    loading: str | None = None
    #: When true the image is emitted bare (no wrapping ``<figure>``), which
    #: is what an inline Markdown image inside a sentence needs.
    bare: bool = False


@dataclass(frozen=True)
class Rendition:
    width: int
    height: int
    href: str
    fmt: str


def _available_formats(formats: Iterable[str]) -> tuple[str, ...]:
    """Drop formats the installed Pillow cannot actually encode."""
    from PIL import features  # local import: Pillow is only needed when opted in

    usable: list[str] = []
    for fmt in formats:
        key = fmt.lower()
        if key not in _SUFFIX_FOR_FORMAT:
            raise ImagePipelineError(
                f"Unsupported image format {fmt!r}. Supported: "
                f"{', '.join(sorted(_SUFFIX_FOR_FORMAT))}."
            )
        try:
            supported = bool(features.check(key)) if key in {"webp", "avif"} else True
        except ValueError:
            supported = False
        if supported:
            usable.append(key)
    return tuple(usable)


def _svg_dimensions(path: Path) -> tuple[int, int] | None:
    """Best-effort intrinsic size for an SVG (``width``/``height`` or viewBox)."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return None
    width = re.search(r'\bwidth="([0-9.]+)(?:px)?"', head)
    height = re.search(r'\bheight="([0-9.]+)(?:px)?"', head)
    if width and height:
        return int(float(width.group(1))), int(float(height.group(1)))
    box = re.search(r'\bviewBox="\s*[-0-9.]+[ ,]+[-0-9.]+[ ,]+([0-9.]+)[ ,]+([0-9.]+)', head)
    if box:
        return int(float(box.group(1))), int(float(box.group(2)))
    return None


class ImageBuilder:
    """Generates derivatives into an output tree and emits the markup.

    One instance per build. ``depth`` differs per page, so hrefs are produced
    relative to the site root and prefixed at emit time -- the same convention
    ``shell.render_page`` uses for stylesheets and nav links.
    """

    def __init__(
        self,
        pipeline: ImagePipeline,
        *,
        content_dir: Path,
        out_dir: Path,
    ) -> None:
        self.pipeline = pipeline
        self.content_dir = content_dir.resolve()
        self.source_dir = pipeline.resolved_source_dir(content_dir)
        self.cache_dir = pipeline.resolved_cache_dir(content_dir)
        self.out_dir = out_dir.resolve()
        self._formats = _available_formats(pipeline.formats)
        self._cache: dict[str, list[Rendition]] = {}
        self._intrinsic: dict[str, tuple[int, int]] = {}
        self._copied: set[str] = set()

    def _publish(self, href: str, built: Path) -> None:
        """Copy one cached derivative into the output tree (once per build)."""
        if href in self._copied:
            return
        dest = self.out_dir / href
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not (dest.is_file() and dest.stat().st_mtime >= built.stat().st_mtime):
            shutil.copy2(built, dest)
        self._copied.add(href)

    # -- source resolution -------------------------------------------------

    def _locate(self, src: str) -> Path | None:
        candidate = (self.source_dir / src).resolve()
        try:
            candidate.relative_to(self.source_dir)
        except ValueError:
            raise ImagePipelineError(
                f"Image src {src!r} resolves outside {self.source_dir}"
            ) from None
        return candidate if candidate.is_file() else None

    # -- derivative generation --------------------------------------------

    def _renditions(self, src: str, path: Path) -> list[Rendition]:
        cached = self._cache.get(src)
        if cached is not None:
            return cached

        from PIL import Image

        rel = Path(src)
        stem = rel.stem
        build_root = self.cache_dir / self.pipeline.out_subdir / rel.parent
        build_root.mkdir(parents=True, exist_ok=True)
        href_dir = f"{self.pipeline.out_subdir}/{rel.parent.as_posix()}".rstrip("/.")
        href_dir = href_dir if href_dir.endswith("/") else href_dir + "/"

        with Image.open(path) as opened:
            intrinsic_w, intrinsic_h = opened.size
            source_format = _PILLOW_FORMAT_FOR_SUFFIX.get(
                path.suffix.lower(), opened.format or "PNG"
            )

            candidates = {w for w in self.pipeline.widths if w < intrinsic_w} | {intrinsic_w}
            ceiling = self.pipeline.max_width
            if ceiling is not None:
                capped = {min(w, ceiling) for w in candidates}
                candidates = {w for w in capped if w <= ceiling} or {min(intrinsic_w, ceiling)}
            widths = sorted(candidates)
            formats = list(self._formats)
            # The original format is always emitted so the <img> fallback works
            # in browsers that understand neither webp nor avif.
            original_key = {
                "JPEG": "jpeg",
                "PNG": "png",
                "WEBP": "webp",
                "AVIF": "avif",
            }.get(source_format, "png")
            if original_key not in formats:
                formats.append(original_key)

            out: list[Rendition] = []
            for fmt in formats:
                suffix = _SUFFIX_FOR_FORMAT[fmt]
                for width in widths:
                    height = max(1, round(intrinsic_h * width / intrinsic_w))
                    name = f"{stem}-{width}{suffix}"
                    dest = build_root / name
                    href = f"{href_dir}{name}"
                    if not (
                        dest.is_file()
                        and dest.stat().st_mtime >= path.stat().st_mtime
                    ):
                        frame = opened.copy()
                        if width != intrinsic_w:
                            frame = frame.resize((width, height), Image.LANCZOS)
                        if fmt in {"jpeg"} and frame.mode in {"RGBA", "P", "LA"}:
                            frame = frame.convert("RGB")
                        save_kwargs: dict[str, object] = {}
                        if fmt in {"webp", "avif", "jpeg"}:
                            save_kwargs["quality"] = self.pipeline.quality
                        frame.save(dest, format=fmt.upper(), **save_kwargs)
                    self._publish(href, dest)
                    out.append(
                        Rendition(width=width, height=height, href=href, fmt=fmt)
                    )

        self._cache[src] = out
        self._intrinsic[src] = (intrinsic_w, intrinsic_h)
        return out

    def _passthrough_href(self, src: str, path: Path) -> str:
        """Copy a vector/animated asset verbatim and return its site href."""
        rel = Path(src)
        href = f"{self.pipeline.out_subdir}/{rel.as_posix()}"
        self._publish(href, path)
        return href

    # -- markup ------------------------------------------------------------

    def render(self, request: ImageRequest, *, depth: int = 0) -> str:
        """HTML for one image request, or ``""`` when it cannot be rendered."""
        src = assert_safe_asset_src(request.src)
        layout = request.layout or self.pipeline.default_layout
        sizes = request.sizes or self.pipeline.sizes_for(layout)
        loading = request.loading or self.pipeline.default_loading
        prefix = "../" * depth

        if src.lower().startswith(("http://", "https://")):
            return self._figure(
                request,
                layout=layout,
                inner=self._img_tag(
                    src=src, alt=request.alt, loading=loading, width=None, height=None
                ),
                size=None,
            )

        path = self._locate(src)
        if path is None:
            if self.pipeline.strict:
                raise ImagePipelineError(
                    f"Image not found: {self.source_dir / src} (referenced as {src!r})"
                )
            return ""

        suffix = path.suffix.lower()
        if suffix in PASSTHROUGH_SUFFIXES or suffix not in RASTER_SUFFIXES:
            href = self._passthrough_href(src, path)
            dims = _svg_dimensions(path) if suffix == ".svg" else self._raster_size(path)
            img = self._img_tag(
                src=prefix + href,
                alt=request.alt,
                loading=loading,
                width=dims[0] if dims else None,
                height=dims[1] if dims else None,
            )
            return self._figure(request, layout=layout, inner=img, size=dims)

        renditions = self._renditions(src, path)
        intrinsic_w, intrinsic_h = self._intrinsic[src]
        by_format: dict[str, list[Rendition]] = {}
        for rendition in renditions:
            by_format.setdefault(rendition.fmt, []).append(rendition)

        original_key = next(
            (
                key
                for key in by_format
                if _SUFFIX_FOR_FORMAT[key] == (".jpg" if suffix == ".jpeg" else suffix)
            ),
            None,
        )
        if original_key is None:
            original_key = list(by_format)[-1]

        fallback_pool = sorted(by_format[original_key], key=lambda r: r.width)
        fallback = next(
            (r for r in reversed(fallback_pool) if r.width <= self.pipeline.fallback_width),
            fallback_pool[0],
        )

        sources = []
        for fmt, group in by_format.items():
            if fmt == original_key:
                continue
            srcset = ", ".join(
                f"{prefix}{r.href} {r.width}w" for r in sorted(group, key=lambda r: r.width)
            )
            sources.append(
                f'<source type="{_MIME_FOR_FORMAT[fmt]}" '
                f'srcset="{html.escape(srcset, quote=True)}" '
                f'sizes="{html.escape(sizes, quote=True)}">'
            )

        fallback_srcset = ", ".join(
            f"{prefix}{r.href} {r.width}w" for r in fallback_pool
        )
        img = self._img_tag(
            src=prefix + fallback.href,
            alt=request.alt,
            loading=loading,
            width=intrinsic_w,
            height=intrinsic_h,
            srcset=fallback_srcset,
            sizes=sizes,
        )
        inner = f'<picture>{"".join(sources)}{img}</picture>' if sources else img
        return self._figure(
            request, layout=layout, inner=inner, size=(intrinsic_w, intrinsic_h)
        )

    def _raster_size(self, path: Path) -> tuple[int, int] | None:
        try:
            from PIL import Image

            with Image.open(path) as opened:
                return opened.size
        except Exception:  # noqa: BLE001 - dimensions are an optimisation
            return None

    @staticmethod
    def _img_tag(
        *,
        src: str,
        alt: str,
        loading: str,
        width: int | None,
        height: int | None,
        srcset: str | None = None,
        sizes: str | None = None,
    ) -> str:
        bits = [f'<img src="{html.escape(src, quote=True)}"']
        if srcset:
            bits.append(f'srcset="{html.escape(srcset, quote=True)}"')
        if sizes:
            bits.append(f'sizes="{html.escape(sizes, quote=True)}"')
        bits.append(f'alt="{html.escape(collapse_whitespace(alt), quote=True)}"')
        if width and height:
            bits.append(f'width="{width}" height="{height}"')
        if loading == "eager":
            bits.append('loading="eager" fetchpriority="high" decoding="async"')
        else:
            bits.append('loading="lazy" decoding="async"')
        return " ".join(bits) + ">"

    def _figure(
        self,
        request: ImageRequest,
        *,
        layout: str,
        inner: str,
        size: tuple[int, int] | None,
    ) -> str:
        if request.bare:
            return inner
        if self.pipeline.wrap is not None:
            width, height = size if size else (None, None)
            return self.pipeline.wrap(
                ImageWrap(
                    request=request,
                    layout=layout,
                    classes=self.pipeline.classes_for(layout),
                    inner=inner,
                    width=width,
                    height=height,
                )
            )
        caption_bits = []
        if request.caption:
            caption_bits.append(html.escape(collapse_whitespace(request.caption)))
        if request.credit:
            credit = html.escape(collapse_whitespace(request.credit))
            caption_bits.append(f'<span class="papyrus-image-credit">{credit}</span>')
        caption = (
            f'<figcaption>{" · ".join(caption_bits)}</figcaption>' if caption_bits else ""
        )
        classes = html.escape(self.pipeline.classes_for(layout), quote=True)
        return f'<figure class="{classes}">{inner}{caption}</figure>'


def with_layouts(pipeline: ImagePipeline, extra: Mapping[str, str]) -> ImagePipeline:
    """Return ``pipeline`` with additional/overridden layout ``sizes`` entries."""
    merged = dict(pipeline.layout_sizes)
    merged.update(extra)
    return replace(pipeline, layout_sizes=merged)
