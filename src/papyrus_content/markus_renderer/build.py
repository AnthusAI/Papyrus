"""Build a Markus static site from committed Markdown sources."""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..env import PAPYRUS_ROOT
from .citations import CitationRendering
from .content_markup import prepare_page, resolve_fragment
from .convert import convert_fragment
from .images import ImageBuilder, ImagePipeline
from .security import assert_markus_version
from .shell import DEFAULT_CHROME, NavItem, SiteChrome, render_page
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
    text = markdown_path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            front_matter = text[3:end]
            for line in front_matter.splitlines():
                if line.startswith("title:"):
                    value = line.split(":", 1)[1].strip().strip('"').strip("'")
                    if value:
                        return value
    return fallback


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
    """One nav link per article -- fine for a handful of articles (Papyrus's
    own site has 2), but floods the header once a publication has a real
    archive of stories. If the articles directory has its own ``index.md``
    (a hand-authored archive/"Stories" page), treat THAT as the one nav entry
    for articles instead of listing every single one -- the index page is
    where individual stories get linked from. Publications with no such
    index.md keep the original one-link-per-article behavior unchanged.
    """
    nav_items = [NavItem("Home", "index.html")]
    index_entry = next((a for a in articles if a[0] == "index"), None)
    if index_entry is not None:
        slug, source = index_entry
        title = _read_title(source, "Stories")
        nav_items.append(NavItem(title, f"articles/{slug}.html"))
        return nav_items
    for slug, source in articles:
        title = _read_title(source, slug.replace("-", " ").title())
        nav_items.append(NavItem(title, f"articles/{slug}.html"))
    return nav_items


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
    """Convert one Markdown file, resolving Papyrus content markup around it.

    With neither ``image_builder`` nor ``citations`` supplied this is exactly
    ``convert_fragment(source, ...)`` -- same subprocess, same bytes. That is
    the contract publications relying on the pre-existing behaviour depend on
    (see ``build_markus_site``).

    When a capability *is* enabled, the Papyrus vocabulary is lowered to
    sentinels before Markus runs, because the pinned ``markus`` CLI validates
    directive names and attributes strictly and would reject anything it does
    not own. See ``content_markup`` for the full rationale.
    """
    if image_builder is None and citations is None:
        return convert_fragment(
            source, theme=theme, markus_executable=markus_executable, transform=transform
        )

    text = source.read_text(encoding="utf-8")
    page = prepare_page(text, images=images, citations=citations)
    if page.markdown == text:
        fragment = convert_fragment(
            source, theme=theme, markus_executable=markus_executable
        )
    else:
        with tempfile.TemporaryDirectory(prefix="papyrus-markus-") as tmp:
            staged = Path(tmp) / source.name
            staged.write_text(page.markdown, encoding="utf-8")
            fragment = convert_fragment(
                staged, theme=theme, markus_executable=markus_executable
            )
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

    for slug, source in articles:
        fragment = _fragment(source, depth=1)
        title = _read_title(source, slug.replace("-", " ").title())
        href = f"articles/{slug}.html"
        page_path = output_root / href
        page_path.write_text(
            render_page(
                title=title,
                fragment=fragment,
                active_href=href,
                nav_items=nav_items,
                depth=1,
                chrome=chrome,
                css_version=css_version,
            ),
            encoding="utf-8",
        )
        built_pages.append(page_path)

    for section in sections:
        entries = _discover_section(content_root, section)
        if not entries:
            continue
        (output_root / section).mkdir(parents=True, exist_ok=True)
        for slug, source in entries:
            fragment = _fragment(source, depth=1)
            title = _read_title(source, slug.replace("-", " ").title())
            href = f"{section}/{slug}.html"
            page_path = output_root / href
            page_path.write_text(
                render_page(
                    title=title,
                    fragment=fragment,
                    active_href=href,
                    nav_items=nav_items,
                    depth=1,
                    chrome=chrome,
                    css_version=css_version,
                ),
                encoding="utf-8",
            )
            built_pages.append(page_path)

    index_md = content_root / "index.md"
    if index_md.is_file():
        index_fragment = _fragment(index_md, depth=0)
        index_title = _read_title(index_md, "Home")
    else:
        link_lines = []
        for slug, path in articles:
            title = _read_title(path, slug.replace("-", " ").title())
            link_lines.append(
                f'<p><a href="articles/{slug}.html">{html_escape(title)}</a></p>'
            )
        index_fragment = (
            '<div class="markus-document"><h1>Articles</h1>\n'
            + "\n".join(link_lines)
            + "\n</div>"
        )
        index_title = "Home"

    index_path = output_root / "index.html"
    index_path.write_text(
        render_page(
            title=index_title,
            fragment=index_fragment,
            active_href="index.html",
            nav_items=nav_items,
            depth=0,
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
    digest = hashlib.sha256()
    for path in sorted(css_dir.glob("*.css")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    if assets_dir is not None and assets_dir.is_dir():
        for path in sorted(assets_dir.rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(assets_dir)).encode("utf-8"))
                digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
