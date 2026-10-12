"""Page composition for Markus static sites, shared by the full build and the projector.

Everything here is a pure function of in-memory text: no file is read and no
process is started. ``build_markus_site`` and ``papyrus_content.projection``
both call these, so a page rendered by an incremental projection is the same
page, byte for byte, that a full build writes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

from .shell import DEFAULT_CHROME, NavItem, SiteChrome, render_page

HOME_HREF = "index.html"
ARTICLES_SECTION = "articles"
ARTICLES_INDEX_SLUG = "index"


def html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def read_title(text: str, fallback: str | None) -> str | None:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                if line.startswith("title:"):
                    value = line.split(":", 1)[1].strip().strip('"').strip("'")
                    if value:
                        return value
    return fallback


def title_from_slug(slug: str) -> str:
    return slug.replace("-", " ").title()


def content_href(section: str, slug: str) -> str:
    return f"{section}/{slug}.html"


def build_nav_items(articles: Sequence[tuple[str, str | None]]) -> list[NavItem]:
    """Navigation for a site; ``articles`` is ``(slug, title or None)`` in file-name order.

    The title is what :func:`read_title` found in the article's front matter,
    ``None`` when it has none. An article named ``index`` is the hand-authored
    archive page and becomes the single articles entry; otherwise every
    article gets one link.
    """
    nav_items = [NavItem("Home", HOME_HREF)]
    index_entry = next((entry for entry in articles if entry[0] == ARTICLES_INDEX_SLUG), None)
    if index_entry is not None:
        slug, title = index_entry
        nav_items.append(NavItem(title or "Stories", content_href(ARTICLES_SECTION, slug)))
        return nav_items
    for slug, title in articles:
        nav_items.append(NavItem(title or title_from_slug(slug), content_href(ARTICLES_SECTION, slug)))
    return nav_items


def navigation_depends_on_articles(article_slugs: Iterable[str]) -> bool:
    return ARTICLES_INDEX_SLUG not in set(article_slugs)


def render_content_page(
    *,
    section: str,
    slug: str,
    text: str,
    fragment: str,
    nav_items: list[NavItem],
    chrome: SiteChrome | None = None,
    css_version: str | None = None,
) -> tuple[str, str]:
    href = content_href(section, slug)
    page_html = render_page(
        title=read_title(text, title_from_slug(slug)),
        fragment=fragment,
        active_href=href,
        nav_items=nav_items,
        depth=1,
        chrome=chrome or DEFAULT_CHROME,
        css_version=css_version,
    )
    return href, page_html


def generated_home_fragment(articles: Sequence[tuple[str, str]]) -> str:
    link_lines = [
        f'<p><a href="{content_href(ARTICLES_SECTION, slug)}">{html_escape(title)}</a></p>'
        for slug, title in articles
    ]
    return '<div class="markus-document"><h1>Articles</h1>\n' + "\n".join(link_lines) + "\n</div>"


def render_home_page(
    *,
    fragment: str,
    title: str,
    nav_items: list[NavItem],
    chrome: SiteChrome | None = None,
    css_version: str | None = None,
) -> str:
    return render_page(
        title=title,
        fragment=fragment,
        active_href=HOME_HREF,
        nav_items=nav_items,
        depth=0,
        chrome=chrome or DEFAULT_CHROME,
        css_version=css_version,
    )


def _path_order(entry: tuple[str, bytes]) -> tuple[str, ...]:
    return PurePosixPath(entry[0]).parts


def version_token(stylesheet_entries: Iterable[tuple[str, bytes]], asset_entries: Iterable[tuple[str, bytes]]) -> str:
    """Cache-busting token: a short hash of the stylesheets' and assets' content.

    Entries are ``(name, bytes)`` pairs: top-level stylesheet file names and
    asset paths relative to the assets directory. Order does not matter. The
    token changes if and only if the content did.
    """
    digest = hashlib.sha256()
    for name, content in sorted(stylesheet_entries, key=_path_order):
        digest.update(name.encode("utf-8"))
        digest.update(content)
    for name, content in sorted(asset_entries, key=_path_order):
        digest.update(name.encode("utf-8"))
        digest.update(content)
    return digest.hexdigest()[:12]
