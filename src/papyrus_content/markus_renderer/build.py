"""Build a Markus static site from committed Markdown sources."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..env import PAPYRUS_ROOT
from .convert import convert_fragment
from .security import assert_markus_version
from .shell import NavItem, render_page
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


def _build_nav_items(articles: list[tuple[str, Path]]) -> list[NavItem]:
    nav_items = [NavItem("Home", "index.html")]
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
) -> BuildResult:
    content_root = (content_dir or DEFAULT_CONTENT_DIR).resolve()
    output_root = (out_dir or DEFAULT_OUT_DIR).resolve()
    site_css = DEFAULT_SITE_CSS

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
        ),
        encoding="utf-8",
    )
    built_pages.insert(0, index_path)

    return BuildResult(content_dir=content_root, out_dir=output_root, pages=built_pages)


def html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
