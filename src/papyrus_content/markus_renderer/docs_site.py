"""Build a documentation site from a repository's ``docs/`` Markdown.

One builder for every Anthus docs site. A repository supplies a
:class:`DocsSiteConfig`; the builder stages its Markdown into the Papyrus
content layout (``index.md`` plus a flat ``articles/`` directory), rewrites
the links between pages and the image paths to match, and renders the result
with :func:`build_markus_site` and a masthead carrying the site's name.
"""

from __future__ import annotations

import argparse
import html
import posixpath
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .build import BuildResult, build_markus_site
from .shell import SiteChrome

RELATIVE_LINK_PATTERN = re.compile(r"\]\((?!https?:|mailto:|#|/)([^)\s#]+)(#[^)\s]*)?\)")
MARKDOWN_LINK_PATTERN = re.compile(r"\]\(([^)\s#]+\.(?:md|html))(#[^)\s]*)?\)")
IMAGE_DIRECTORY_NAME = "images"
PUBLISHED_ASSET_DIRECTORY_NAME = "assets"
INDEX_PAGE_PATH = "index.md"
DEFAULT_SITE_STYLESHEET = Path(__file__).with_name("docs_site.css")


@dataclass(frozen=True)
class DocsSiteConfig:
    """What differs between one documentation site and the next."""

    site_name: str
    tagline: str
    documentation_directory: Path
    source_repository_url: str
    theme: str = "catppuccin"
    navigation: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    """Sidebar groups as (group label, ((published .html path, label), ...)); empty keeps the flat page list."""
    site_stylesheet: Path | None = None
    redirect_former_directory_urls: bool = False
    """Write an index.html redirect at each page's former directory URL (for example from MkDocs)."""


def published_page_path(documentation_relative_path: str) -> str:
    """Where a documentation page lands in the staged Papyrus content layout."""
    if documentation_relative_path == INDEX_PAGE_PATH:
        return INDEX_PAGE_PATH
    return f"articles/{published_page_slug(documentation_relative_path)}.md"


def published_page_slug(documentation_relative_path: str) -> str:
    """The page's published file stem: lowercase words joined by hyphens, as the build names its pages."""
    stem = documentation_relative_path.removesuffix(".md").replace("/", "-")
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")


def rewrite_links_between_pages(
    page_text: str, documentation_relative_path: str, known_pages: set[str]
) -> str:
    """Point ``](other.md)`` links at the published ``.html`` of the same page."""
    source_directory = posixpath.dirname(documentation_relative_path)
    published_directory = posixpath.dirname(published_page_path(documentation_relative_path))

    def rewrite(match: re.Match[str]) -> str:
        target_path = posixpath.normpath(posixpath.join(source_directory, match.group(1)))
        if target_path.endswith(".html"):
            target_path = target_path.removesuffix(".html") + ".md"
        if target_path not in known_pages:
            return match.group(0)
        published_target = published_page_path(target_path).removesuffix(".md") + ".html"
        relative_target = posixpath.relpath(published_target, published_directory or ".")
        return f"]({relative_target}{match.group(2) or ''})"

    return MARKDOWN_LINK_PATTERN.sub(rewrite, page_text)


def rewrite_repository_links(page_text: str, documentation_relative_path: str, config: DocsSiteConfig) -> str:
    """Point relative links to files in the repository (source, README, diagrams) at their GitHub pages."""
    source_directory = posixpath.dirname(documentation_relative_path)
    repository_root = config.documentation_directory.parent

    def rewrite(match: re.Match[str]) -> str:
        target = match.group(1)
        if target.startswith(("articles/", "../assets/", "assets/")) or target.endswith(".html"):
            return match.group(0)
        docs_relative = posixpath.normpath(posixpath.join(source_directory, target))
        documentation_target = config.documentation_directory / docs_relative
        repository_relative = posixpath.normpath(posixpath.join(config.documentation_directory.name, docs_relative))
        repository_target = repository_root / repository_relative
        if documentation_target.exists() and docs_relative.endswith(".md") and not docs_relative.startswith(".."):
            return match.group(0)
        if repository_target.exists():
            kind = "tree" if repository_target.is_dir() else "blob"
            return f"]({config.source_repository_url}/{kind}/HEAD/{repository_relative}{match.group(2) or ''})"
        return match.group(0)

    return RELATIVE_LINK_PATTERN.sub(rewrite, page_text)


def stage_docs_content(config: DocsSiteConfig, staging_directory: Path) -> int:
    """Write the staged content layout and return the number of pages staged."""
    (staging_directory / "articles").mkdir()
    source_pages = sorted(config.documentation_directory.rglob("*.md"))
    known_pages = {
        page.relative_to(config.documentation_directory).as_posix() for page in source_pages
    }
    for source_page in source_pages:
        relative_path = source_page.relative_to(config.documentation_directory).as_posix()
        page_text = rewrite_links_between_pages(
            source_page.read_text(encoding="utf-8"), relative_path, known_pages
        )
        page_text = page_text.replace(
            f"]({IMAGE_DIRECTORY_NAME}/", f"](../{PUBLISHED_ASSET_DIRECTORY_NAME}/"
        )
        page_text = rewrite_repository_links(page_text, relative_path, config)
        (staging_directory / published_page_path(relative_path)).write_text(
            page_text, encoding="utf-8"
        )
    image_directory = config.documentation_directory / IMAGE_DIRECTORY_NAME
    if image_directory.is_dir():
        shutil.copytree(image_directory, staging_directory / PUBLISHED_ASSET_DIRECTORY_NAME)
    return len(source_pages)


def page_title(source_page: Path) -> str:
    for line in source_page.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return source_page.stem.replace("_", " ").replace("-", " ").title()


def automatic_navigation(config: DocsSiteConfig) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """Sidebar groups from the documentation tree: top-level pages together, then one group per directory."""
    groups: dict[str, list[tuple[str, str]]] = {"Overview": [("index.html", "Overview")]}
    for source_page in sorted(config.documentation_directory.rglob("*.md")):
        relative_path = source_page.relative_to(config.documentation_directory).as_posix()
        if relative_path == INDEX_PAGE_PATH:
            continue
        directory = posixpath.dirname(relative_path)
        label = directory.replace("-", " ").replace("_", " ").title() if directory else "Guides"
        groups.setdefault(label, []).append((f"articles/{published_page_slug(relative_path)}.html", page_title(source_page)))
    return tuple((label, tuple(entries)) for label, entries in groups.items())


def render_navigation_groups(navigation_groups, page_context) -> str:
    groups = []
    for group_label, entries in navigation_groups:
        items = "".join(
            f'<li><a href="{page_context.prefix}{href}"'
            + (' aria-current="page"' if href == page_context.active_href else "")
            + f">{html.escape(label)}</a></li>"
            for href, label in entries
        )
        groups.append(
            f'<div class="site-nav-group"><p class="site-nav-label">{html.escape(group_label)}</p>'
            f'<ul class="site-nav-list">{items}</ul></div>'
        )
    return "".join(groups)


def docs_site_chrome(config: DocsSiteConfig) -> SiteChrome:
    def render_site_banner(page_context) -> str:
        navigation_groups = config.navigation or automatic_navigation(config)
        if navigation_groups:
            return (
                '<header class="site-banner"><div class="site-topbar">'
                f'<a class="site-wordmark" href="{page_context.prefix}index.html">{config.site_name}</a>'
                f'<p class="site-tagline">{config.tagline}</p>'
                f'<nav class="site-links" aria-label="Project"><a href="{config.source_repository_url}">GitHub</a></nav>'
                '</div><details class="site-menu" open><summary>Contents</summary>'
                f'<nav class="site-sidebar" aria-label="Documentation">{render_navigation_groups(navigation_groups, page_context)}</nav>'
                "</details></header>"
            )
        navigation_links = "".join(
            f'<a href="{page_context.prefix}{item.href}"'
            + (' aria-current="page"' if item.href == page_context.active_href else "")
            + f">{item.label}</a>"
            for item in page_context.nav_items
        )
        return (
            '<header class="site-banner">'
            f'<a class="site-wordmark" href="{page_context.prefix}index.html">{config.site_name}</a>'
            f'<p class="site-tagline">{config.tagline}</p>'
            '<div class="site-nav-container">'
            f'<nav class="site-nav" aria-label="Documentation">{navigation_links}</nav></div>'
            "</header>"
        )

    return SiteChrome(
        site_name=config.site_name,
        head_html=(
            f"<script>document.documentElement.setAttribute('data-theme','{config.theme}')</script>"
        ),
        render_masthead=render_site_banner,
        footer_html=(
            '<p>Built with <a href="https://github.com/AnthusAI/Papyrus">Papyrus</a>. '
            f'Source on <a href="{config.source_repository_url}">GitHub</a>.</p>'
        ),
    )


def write_redirects_from_former_urls(config: DocsSiteConfig, output_directory: Path) -> None:
    for source_page in sorted(config.documentation_directory.rglob("*.md")):
        relative_path = source_page.relative_to(config.documentation_directory).as_posix()
        if relative_path == INDEX_PAGE_PATH:
            continue
        published_target = f"articles/{published_page_slug(relative_path)}.html"
        former_stem = relative_path.removesuffix(".md")
        depth_prefix = "../" * (former_stem.count("/") + 1)
        former_directory = output_directory / former_stem
        former_directory.mkdir(parents=True, exist_ok=True)
        (former_directory / "index.html").write_text(
            '<!DOCTYPE html><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0; url={depth_prefix}{published_target}">'
            f'<link rel="canonical" href="{depth_prefix}{published_target}">'
            f'<a href="{depth_prefix}{published_target}">Moved to {published_target}</a>',
            encoding="utf-8",
        )


def build_docs_site(config: DocsSiteConfig, output_directory: Path) -> BuildResult:
    with tempfile.TemporaryDirectory(prefix="papyrus-docs-site-") as staging_name:
        staging_directory = Path(staging_name)
        stage_docs_content(config, staging_directory)
        result = build_markus_site(
            content_dir=staging_directory,
            out_dir=output_directory,
            theme=config.theme,
            site_css=config.site_stylesheet or DEFAULT_SITE_STYLESHEET,
            chrome=docs_site_chrome(config),
        )
    if config.redirect_former_directory_urls:
        write_redirects_from_former_urls(config, output_directory)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a documentation site with Papyrus.")
    parser.add_argument("--docs", type=Path, default=Path("docs"))
    parser.add_argument("--out", type=Path, default=Path("_site"))
    parser.add_argument("--name", required=True)
    parser.add_argument("--tagline", default="")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--theme", default="catppuccin")
    parser.add_argument("--redirect-former-urls", action="store_true", help="Write redirects from former directory-style URLs.")
    arguments = parser.parse_args(argv)
    result = build_docs_site(
        DocsSiteConfig(
            site_name=arguments.name,
            tagline=arguments.tagline,
            documentation_directory=arguments.docs,
            source_repository_url=arguments.source_url,
            theme=arguments.theme,
            redirect_former_directory_urls=arguments.redirect_former_urls,
        ),
        arguments.out,
    )
    print(f"Built {len(result.pages)} pages into {result.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
