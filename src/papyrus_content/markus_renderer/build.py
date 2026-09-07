"""Build a Markus static site from committed Markdown sources."""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..env import PAPYRUS_ROOT
from .convert import convert_fragment
from .security import assert_markus_version
from .shell import DEFAULT_CHROME, NavItem, SiteChrome, render_page
from .vendor_css import vendor_markus_css

DEFAULT_CONTENT_DIR = PAPYRUS_ROOT / "web" / "content"
DEFAULT_OUT_DIR = PAPYRUS_ROOT / "web" / "dist"
DEFAULT_THEME = "hackerman"
DEFAULT_SITE_CSS = PAPYRUS_ROOT / "web" / "css" / "site-theme.css"

_ARTICLE_SLUG = re.compile(r"^([a-z0-9][a-z0-9-]*)\.md$")


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
    articles: list[tuple[str, Path]] = []
    for path in sorted(articles_dir.glob("*.md")):
        match = _ARTICLE_SLUG.match(path.name)
        if not match:
            continue
        articles.append((match.group(1), path))
    if not articles:
        raise RuntimeError(f"No article Markdown files found in {articles_dir}")
    return articles


def _discover_section(content_dir: Path, section: str) -> list[tuple[str, Path]]:
    """Discover ``<content>/<section>/*.md``. Returns [] when the dir is absent.

    Unlike ``_discover_articles`` this never raises: extra sections are
    optional. A publication with only ``articles/`` behaves exactly as before.
    """
    section_dir = content_dir / section
    if not section_dir.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for path in sorted(section_dir.glob("*.md")):
        match = _ARTICLE_SLUG.match(path.name)
        if match:
            found.append((match.group(1), path))
    return found


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
) -> BuildResult:
    """Build a Markus static site.

    ``site_css`` and ``chrome`` are what let a publication (Pilobol.us, say)
    render through this shared renderer instead of forking its own build
    script. Defaults reproduce Papyrus's own site exactly.
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

    nav_items = _build_nav_items(articles)
    built_pages: list[Path] = []

    for slug, source in articles:
        fragment = convert_fragment(source, theme=theme, markus_executable=markus_executable)
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
            fragment = convert_fragment(
                source, theme=theme, markus_executable=markus_executable
            )
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
        index_fragment = convert_fragment(index_md, theme=theme, markus_executable=markus_executable)
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
