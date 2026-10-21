"""The head builder: every ``<head>`` tag a page needs, from one description of the page."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field

from .config import StandardSettings
from .environment import SiteEnvironment

NOINDEX_CONTENT = "noindex, nofollow"


def _q(value: str) -> str:
    return html.escape(value, quote=True)


def json_ld_script(data: dict) -> str:
    """Compact JSON-LD; ``</`` is escaped so no value can close the script element."""
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'<script type="application/ld+json">{encoded}</script>'


@dataclass(frozen=True)
class PageHead:
    """What the head builder needs to know about one page."""

    title: str
    path: str                      # site path of the page, e.g. "/articles/x/"
    description: str = ""
    og_type: str = "website"
    image: str | None = None       # absolute URL or site path
    image_size: tuple[int, int] | None = None
    canonical: str | None = None   # explicit canonical (absolute); default is the page's own address
    published: str = ""            # ISO date
    modified: str = ""
    authors: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    noindex: bool = False
    json_ld_type: str | None = None   # "Article", "NewsArticle", ... or None for no JSON-LD
    breadcrumbs: tuple[tuple[str, str], ...] = ()   # (name, site path)
    extra: str = ""                # raw head markup appended last (the head_extra hook)


class HeadBuilder:
    def __init__(self, settings: StandardSettings, environment: SiteEnvironment) -> None:
        self.settings = settings
        self.environment = environment

    def absolute(self, path_or_url: str | None) -> str | None:
        if not path_or_url:
            return None
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        if self.environment.origin is None:
            return None
        return self.environment.origin + (path_or_url if path_or_url.startswith("/") else "/" + path_or_url)

    def build(self, page: PageHead) -> str:
        settings, seo, identity = self.settings, self.settings.seo, self.settings.identity
        lines: list[str] = []
        fonts = settings.fonts
        if fonts.stylesheet:
            for origin in fonts.preconnect:
                crossorigin = " crossorigin" if "gstatic" in origin else ""
                lines.append(f'<link rel="preconnect" href="{_q(origin)}"{crossorigin}>')
            lines.append(f'<link rel="stylesheet" href="{_q(fonts.stylesheet)}">')
        icons = settings.icons
        if icons.icon:
            lines.append(f'<link rel="icon" href="{_q(icons.icon)}" type="{_q(icons.icon_type)}">')
        if icons.apple_touch:
            lines.append(f'<link rel="apple-touch-icon" href="{_q(icons.apple_touch)}">')
        if icons.manifest:
            lines.append(f'<link rel="manifest" href="{_q(icons.manifest)}">')
        if icons.theme_color:
            lines.append(f'<meta name="theme-color" content="{_q(icons.theme_color)}">')
        if icons.theme_color_dark:
            lines.append(f'<meta name="theme-color" content="{_q(icons.theme_color_dark)}" media="(prefers-color-scheme: dark)">')
        feeds = settings.feeds
        if "rss" in feeds.formats:
            lines.append(f'<link rel="alternate" type="application/rss+xml" title="{_q(feeds.title)}" href="/{_q(feeds.rss_path)}">')
        if "atom" in feeds.formats:
            lines.append(f'<link rel="alternate" type="application/atom+xml" title="{_q(feeds.title)}" href="/{_q(feeds.atom_path)}">')
        sitemap_path = "sitemap-index.xml" if settings.sitemap_style == "index" else "sitemap.xml"
        lines.append(f'<link rel="sitemap" type="application/xml" href="/{sitemap_path}">')
        if page.noindex or self.environment.guarded:
            lines.append(f'<meta name="robots" content="{NOINDEX_CONTENT}">')

        # Pilobol.us's Open Graph block, in its order, so the two are comparable byte for byte.
        own_url = self.absolute(page.path)
        canonical = page.canonical or own_url
        image = self.absolute(page.image or seo.default_image)
        title = page.title or identity.name
        description = page.description or identity.description
        if description:
            lines.append(f'<meta name="description" content="{_q(description)}">')
        if canonical:
            lines.append(f'<link rel="canonical" href="{_q(canonical)}">')
        lines.append(f'<meta property="og:site_name" content="{_q(identity.short_name or identity.name)}">')
        lines.append(f'<meta property="og:type" content="{_q(page.og_type)}">')
        lines.append(f'<meta property="og:title" content="{_q(title)}">')
        if description:
            lines.append(f'<meta property="og:description" content="{_q(description)}">')
        if own_url:
            lines.append(f'<meta property="og:url" content="{_q(canonical or own_url)}">')
        size = page.image_size or ((seo.image_width, seo.image_height) if seo.image_width and seo.image_height else None)
        if image:
            lines.append(f'<meta property="og:image" content="{_q(image)}">')
            if size:
                lines.append(f'<meta property="og:image:width" content="{size[0]}">')
                lines.append(f'<meta property="og:image:height" content="{size[1]}">')
        lines.append(f'<meta name="twitter:card" content="{"summary_large_image" if image else "summary"}">')
        lines.append(f'<meta name="twitter:title" content="{_q(title)}">')
        if description:
            lines.append(f'<meta name="twitter:description" content="{_q(description)}">')
        if image:
            lines.append(f'<meta name="twitter:image" content="{_q(image)}">')
        if seo.twitter_site:
            lines.append(f'<meta name="twitter:site" content="{_q(seo.twitter_site)}">')
        if seo.twitter_creator:
            lines.append(f'<meta name="twitter:creator" content="{_q(seo.twitter_creator)}">')
        if page.og_type == "article":
            if page.published:
                lines.append(f'<meta property="article:published_time" content="{_q(page.published)}">')
            if page.modified:
                lines.append(f'<meta property="article:modified_time" content="{_q(page.modified)}">')
            for tag in page.tags:
                lines.append(f'<meta property="article:tag" content="{_q(tag)}">')
        if page.json_ld_type:
            lines.append(json_ld_script(self._article_json_ld(page, canonical or own_url, image, description, title)))
        if page.breadcrumbs and seo.breadcrumbs_json_ld and self.environment.origin:
            lines.append(json_ld_script(self._breadcrumb_json_ld(page.breadcrumbs)))
        if page.extra:
            lines.append(page.extra)
        return "\n" + "\n".join(lines)

    def _article_json_ld(self, page: PageHead, url: str | None, image: str | None, description: str, title: str) -> dict:
        data: dict = {"@context": "https://schema.org", "@type": page.json_ld_type, "headline": title}
        if description:
            data["description"] = description
        if page.published:
            data["datePublished"] = page.published
        if page.modified:
            data["dateModified"] = page.modified
        if page.authors:
            data["author"] = [{"@type": "Person", "name": name} for name in page.authors]
        data["publisher"] = {"@type": "Organization", "name": self.settings.seo.publisher_name}
        if url:
            data["mainEntityOfPage"] = url
        if image:
            data["image"] = image
        return data

    def _breadcrumb_json_ld(self, crumbs) -> dict:
        return {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": position, "name": name, "item": self.absolute(path)}
                for position, (name, path) in enumerate(crumbs, start=1)
            ],
        }
