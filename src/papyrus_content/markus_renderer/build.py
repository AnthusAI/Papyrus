"""Build a Markus static site from committed Markdown sources."""

from __future__ import annotations

import re
import shutil
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..env import PAPYRUS_ROOT
from .citations import CitationRendering
from .content_markup import prepare_page, resolve_fragment
from .convert import convert_fragment
from .images import ImageBuilder, ImagePipeline
from .pages import (
    build_nav_items,
    generated_home_fragment,
    read_title,
    render_content_page,
    render_home_page,
    title_from_slug,
    version_token,
)
from .security import assert_markus_version
from .shell import DEFAULT_CHROME, NavItem, SiteChrome
from .transforms import FragmentTransform
from .vendor_css import vendor_markus_css

DEFAULT_CONTENT_DIR = PAPYRUS_ROOT / "web" / "content"
DEFAULT_OUT_DIR = PAPYRUS_ROOT / "web" / "dist"
DEFAULT_THEME = "hackerman"
DEFAULT_SITE_CSS = PAPYRUS_ROOT / "web" / "css" / "site-theme.css"


def slugify(name: str) -> str:
    """The one canonical URL slug for a content file name (without ``.md``).

    ASCII-fold, lowercase, collapse every run of non-alphanumerics (whitespace,
    underscores, punctuation) to a single hyphen, strip leading/trailing
    hyphens. Returns ``""`` when nothing survives.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


def _discover_markdown(directory: Path) -> list[tuple[str, Path]]:
    """``(slug, path)`` for every page in ``directory``, sorted by file name.

    Any ``*.md`` is a page and its slug is ``slugify(stem)``. Names starting
    with ``_`` or ``.`` are not pages (drafts / hidden files), as before.
    Two files deriving the same slug, or a name with no usable slug, fail the
    build rather than silently dropping or overwriting a page (PPY-8e6068).
    """
    found: list[tuple[str, Path]] = []
    seen: dict[str, Path] = {}
    for path in sorted(directory.glob("*.md")):
        if path.name.startswith(("_", ".")):
            continue
        slug = slugify(path.stem)
        if not slug:
            raise RuntimeError(f"{path} has no usable URL slug (nothing left after slugify).")
        if slug in seen:
            raise RuntimeError(
                f"Slug collision in {directory}: {seen[slug].name} and {path.name} "
                f"both become '{slug}'. Rename one."
            )
        seen[slug] = path
        found.append((slug, path))
    return found


@dataclass(frozen=True)
class BuildResult:
    content_dir: Path
    out_dir: Path
    pages: list[Path]


def _read_title(markdown_path: Path, fallback: str) -> str:
    return read_title(markdown_path.read_text(encoding="utf-8"), fallback)


def _discover_articles(content_dir: Path) -> list[tuple[str, Path]]:
    articles_dir = content_dir / "articles"
    if not articles_dir.is_dir():
        raise RuntimeError(f"Missing articles directory: {articles_dir}")
    articles = _discover_markdown(articles_dir)
    if not articles:
        raise RuntimeError(f"No article Markdown files found in {articles_dir}")
    return articles


def _discover_section(content_dir: Path, section: str) -> list[tuple[str, Path]]:
    """Discover ``<content>/<section>/*.md``. Returns [] when the dir is absent.

    Unlike ``_discover_articles`` this does not raise for a missing or empty
    section: extra sections are optional. A publication with only ``articles/`` behaves exactly as before.
    """
    section_dir = content_dir / section
    if not section_dir.is_dir():
        return []
    return _discover_markdown(section_dir)


def _build_nav_items(articles: list[tuple[str, Path]]) -> list[NavItem]:
    """One nav link per article, or one entry for a hand-authored ``index.md``.

    One link per article is fine for a handful of articles (Papyrus's own site
    has 2), but floods the header once a publication has a real archive. If
    the articles directory has its own ``index.md`` (a hand-authored
    archive/"Stories" page), that is the one nav entry for articles instead;
    the index page is where individual stories get linked from.
    """
    return build_nav_items(
        [(slug, read_title(source.read_text(encoding="utf-8"), None)) for slug, source in articles]
    )


def render_fragment_text(
    text: str,
    *,
    convert: Callable[[str], str],
    depth: int = 0,
    images: ImagePipeline | None = None,
    image_builder: ImageBuilder | None = None,
    citations: CitationRendering | None = None,
    transform: FragmentTransform | None = None,
) -> str:
    """Convert one Markdown text, resolving Papyrus content markup around it.

    ``convert`` turns Markus source into a fragment: the pinned CLI for the
    full build, Markus in this process for the projector. With neither
    ``image_builder`` nor ``citations`` supplied the text goes to ``convert``
    untouched.

    When a capability *is* enabled, the Papyrus vocabulary is lowered to
    sentinels before Markus runs, because Markus validates directive names and
    attributes strictly and would reject anything it does not own. See
    ``content_markup`` for the full rationale.
    """
    if image_builder is None and citations is None:
        fragment = convert(text)
        return fragment if transform is None else transform.apply(fragment)

    page = prepare_page(text, images=images, citations=citations)
    fragment = convert(page.markdown)
    if image_builder is not None:
        image_builder.start_page()
    resolved = resolve_fragment(
        fragment,
        page,
        depth=depth,
        image_builder=image_builder,
        citations=citations,
    )
    # Last, so a publication's transform sees the final markup, images and
    # bibliography included.
    return resolved if transform is None else transform.apply(resolved)


def render_fragment(
    source: Path,
    *,
    theme: str | None = None,
    markus_executable: str = "markus",
    depth: int = 0,
    images: ImagePipeline | None = None,
    image_builder: ImageBuilder | None = None,
    citations: CitationRendering | None = None,
    transform: FragmentTransform | None = None,
) -> str:
    """Convert one Markdown file with the ``markus`` CLI, resolving Papyrus content markup.

    With neither ``image_builder`` nor ``citations`` supplied this is exactly
    ``convert_fragment(source, ...)`` -- same subprocess, same bytes. That is
    the contract publications relying on the pre-existing behaviour depend on
    (see ``build_markus_site``).
    """
    text = source.read_text(encoding="utf-8")

    def convert_with_cli(markdown: str) -> str:
        if markdown == text:
            return convert_fragment(
                source, theme=theme, markus_executable=markus_executable
            )
        with tempfile.TemporaryDirectory(prefix="papyrus-markus-") as tmp:
            staged = Path(tmp) / source.name
            staged.write_text(markdown, encoding="utf-8")
            return convert_fragment(
                staged, theme=theme, markus_executable=markus_executable
            )

    return render_fragment_text(
        text,
        convert=convert_with_cli,
        depth=depth,
        images=images,
        image_builder=image_builder,
        citations=citations,
        transform=transform,
    )


def _copy_tree(source: Path, dest: Path) -> None:
    if not source.exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        target = dest / entry.name
        if entry.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)


def _clean_out_dir(out_dir: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)


def build_markus_site(
    *,
    content_dir: Path | None = None,
    out_dir: Path | None = None,
    theme: str | None = DEFAULT_THEME,
    markus_executable: str = "markus",
    site_css: Path | None = None,
    chrome: SiteChrome | None = None,
    sections: tuple[str, ...] = (),
    images: ImagePipeline | None = None,
    citations: CitationRendering | None = None,
    transform: FragmentTransform | None = None,
    vendor_css: bool = True,
) -> BuildResult:
    """Build a Markus static site.

    ``site_css`` and ``chrome`` are what let a publication (Pilobol.us, say)
    render through this shared renderer instead of forking its own build
    script. Defaults reproduce Papyrus's own site exactly.

    ``images`` and ``citations`` are **opt-in content capabilities**. Both
    default to ``None``, and when both are ``None`` no fragment is inspected or
    rewritten at all -- a publication that has not opted in gets byte-identical
    output to before these parameters existed. Pass ``images=ImagePipeline()``
    for responsive ``srcset``/``sizes``/intrinsic-dimension images and the
    ``::image{}`` directive; pass ``citations=CitationRendering()`` for
    ``[@key]`` inline markers and the ``::citations{}`` bibliography. The
    authoring syntax both of those accept is specified in
    ``docs/markus-content-markup.md``.

    ``transform`` post-processes every converted fragment (see
    ``transforms.py``). ``vendor_css=False`` skips writing
    ``css/markus-vendor.css``, for publications whose shell does not link it.
    """
    content_root = (content_dir or DEFAULT_CONTENT_DIR).resolve()
    output_root = (out_dir or DEFAULT_OUT_DIR).resolve()
    site_css = (site_css or DEFAULT_SITE_CSS).resolve()
    chrome = chrome or DEFAULT_CHROME

    assert_markus_version(markus_executable)

    articles = _discover_articles(content_root)
    _clean_out_dir(output_root)
    (output_root / "articles").mkdir(parents=True)
    (output_root / "css").mkdir(parents=True)

    if vendor_css:
        vendor_markus_css(output_root / "css" / "markus-vendor.css", theme=theme)
    if site_css.is_file():
        shutil.copy2(site_css, output_root / "css" / "site-theme.css")
    else:
        (output_root / "css" / "site-theme.css").write_text(
            "/* Site theme layer — unlayered so it wins over @layer markus */\n",
            encoding="utf-8",
        )

    _copy_tree(content_root / "assets", output_root / "assets")

    # Derived from the emitted stylesheets AND scripts so any change to
    # either yields a new URL (see _css_version's docstring).
    css_version = _css_version(output_root / "css", output_root / "assets")

    image_builder = (
        ImageBuilder(images, content_dir=content_root, out_dir=output_root)
        if images is not None
        else None
    )

    def _fragment(source: Path, *, depth: int) -> str:
        return render_fragment(
            source,
            theme=theme,
            markus_executable=markus_executable,
            depth=depth,
            images=images,
            image_builder=image_builder,
            citations=citations,
            transform=transform,
        )

    nav_items = _build_nav_items(articles)
    built_pages: list[Path] = []

    def _write_content_pages(section: str, entries: list[tuple[str, Path]]) -> None:
        for slug, source in entries:
            fragment = _fragment(source, depth=1)
            href, page_html = render_content_page(
                section=section,
                slug=slug,
                text=source.read_text(encoding="utf-8"),
                fragment=fragment,
                nav_items=nav_items,
                chrome=chrome,
                css_version=css_version,
            )
            page_path = output_root / href
            page_path.write_text(page_html, encoding="utf-8")
            built_pages.append(page_path)

    _write_content_pages("articles", articles)

    for section in sections:
        entries = _discover_section(content_root, section)
        if not entries:
            continue
        (output_root / section).mkdir(parents=True, exist_ok=True)
        _write_content_pages(section, entries)

    index_md = content_root / "index.md"
    if index_md.is_file():
        index_fragment = _fragment(index_md, depth=0)
        index_title = _read_title(index_md, "Home")
    else:
        index_fragment = generated_home_fragment(
            [
                (slug, _read_title(path, title_from_slug(slug)))
                for slug, path in articles
            ]
        )
        index_title = "Home"

    index_path = output_root / "index.html"
    index_path.write_text(
        render_home_page(
            fragment=index_fragment,
            title=index_title,
            nav_items=nav_items,
            chrome=chrome,
            css_version=css_version,
        ),
        encoding="utf-8",
    )
    built_pages.insert(0, index_path)

    return BuildResult(content_dir=content_root, out_dir=output_root, pages=built_pages)


def _css_version(css_dir: Path, assets_dir: Path | None = None) -> str:
    """Cache-busting token: a short hash of the emitted stylesheets' AND
    scripts' CONTENT.

    Deliberately not an mtime. Second-granularity mtimes collide when two
    builds land in the same second, and the browser then keeps serving the
    stale stylesheet from cache while the URL looks unchanged -- which is
    exactly how a real CSS fix appeared not to work during development.
    Hashing content means the URL changes if and only if the content did.

    This same token versions every <script> tag the shell emits (see
    shell.py's render_page and its window.__markusAssetVersion), not just
    stylesheets -- it was CSS-only at first, which meant a JS-only edit left
    the version unchanged and browsers kept serving stale cached copies of
    the exact scripts that had just been fixed. assets_dir is walked
    recursively so it also covers scripts under subdirectories.
    """
    stylesheet_entries = [(path.name, path.read_bytes()) for path in css_dir.glob("*.css")]
    asset_entries = []
    if assets_dir is not None and assets_dir.is_dir():
        asset_entries = [
            (path.relative_to(assets_dir).as_posix(), path.read_bytes())
            for path in assets_dir.rglob("*")
            if path.is_file()
        ]
    return version_token(stylesheet_entries, asset_entries)
