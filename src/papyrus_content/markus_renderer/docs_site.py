"""Build a documentation site from a repository's ``docs/`` Markdown.

One builder for every Anthus docs site. A repository supplies a
:class:`DocsSiteConfig`; the builder stages its Markdown into the Papyrus
content layout (``index.md`` plus a flat ``articles/`` directory), rewrites
the links between pages and the image paths to match, and renders the result
with :func:`build_markus_site` and a masthead carrying the site's name.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .build import BuildResult, build_markus_site
from .shell import SiteChrome

MARKDOWN_LINK_PATTERN = re.compile(r"\]\(([^)\s#]+\.md)(#[^)\s]*)?\)")
IMAGE_DIRECTORY_NAME = "images"
PUBLISHED_ASSET_DIRECTORY_NAME = "assets"
INDEX_PAGE_PATH = "index.md"


@dataclass(frozen=True)
class DocsSiteConfig:
    """What differs between one documentation site and the next."""

    site_name: str
    tagline: str
    documentation_directory: Path
    source_repository_url: str
    theme: str = "catppuccin"


def published_page_path(documentation_relative_path: str) -> str:
    """Where a documentation page lands in the staged Papyrus content layout."""
    if documentation_relative_path == INDEX_PAGE_PATH:
        return INDEX_PAGE_PATH
    return f"articles/{documentation_relative_path.replace('/', '-')}"


def rewrite_links_between_pages(
    page_text: str, documentation_relative_path: str, known_pages: set[str]
) -> str:
    """Point ``](other.md)`` links at the published ``.html`` of the same page."""
    source_directory = posixpath.dirname(documentation_relative_path)
    published_directory = posixpath.dirname(published_page_path(documentation_relative_path))

    def rewrite(match: re.Match[str]) -> str:
        target_path = posixpath.normpath(posixpath.join(source_directory, match.group(1)))
        if target_path not in known_pages:
            return match.group(0)
        published_target = published_page_path(target_path).removesuffix(".md") + ".html"
        relative_target = posixpath.relpath(published_target, published_directory or ".")
        return f"]({relative_target}{match.group(2) or ''})"

    return MARKDOWN_LINK_PATTERN.sub(rewrite, page_text)


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
        (staging_directory / published_page_path(relative_path)).write_text(
            page_text, encoding="utf-8"
        )
    image_directory = config.documentation_directory / IMAGE_DIRECTORY_NAME
    if image_directory.is_dir():
        shutil.copytree(image_directory, staging_directory / PUBLISHED_ASSET_DIRECTORY_NAME)
    return len(source_pages)


def docs_site_chrome(config: DocsSiteConfig) -> SiteChrome:
    def render_site_banner(page_context) -> str:
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


def build_docs_site(config: DocsSiteConfig, output_directory: Path) -> BuildResult:
    with tempfile.TemporaryDirectory(prefix="papyrus-docs-site-") as staging_name:
        staging_directory = Path(staging_name)
        stage_docs_content(config, staging_directory)
        return build_markus_site(
            content_dir=staging_directory,
            out_dir=output_directory,
            theme=config.theme,
            chrome=docs_site_chrome(config),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a documentation site with Papyrus.")
    parser.add_argument("--docs", type=Path, default=Path("docs"))
    parser.add_argument("--out", type=Path, default=Path("_site"))
    parser.add_argument("--name", required=True)
    parser.add_argument("--tagline", default="")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--theme", default="catppuccin")
    arguments = parser.parse_args(argv)
    result = build_docs_site(
        DocsSiteConfig(
            site_name=arguments.name,
            tagline=arguments.tagline,
            documentation_directory=arguments.docs,
            source_repository_url=arguments.source_url,
            theme=arguments.theme,
        ),
        arguments.out,
    )
    print(f"Built {len(result.pages)} pages into {result.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
