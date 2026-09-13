"""HTML page shell for Markus static output."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NavItem:
    label: str
    href: str


@dataclass(frozen=True)
class SiteChrome:
    """Per-publication identity for the static page shell.

    A publication supplies this so it can render through the shared Markus
    renderer without forking the build. Everything here is publication-level
    (masthead, footer, decorative scripts); none of it is article content.

    ``scripts`` are emitted as ``<script src=...>`` just before ``</body>``,
    path-prefixed for page depth exactly like nav links. They exist for site
    chrome -- theme toggles, decorative canvases. They are NEVER derived from
    article Markdown: keeping author content unable to introduce script tags is
    precisely why Markus runs with raw HTML disabled.
    """

    site_name: str = "Papyrus Markus"
    tagline: str | None = None
    footer_html: str | None = None
    scripts: tuple[str, ...] = field(default_factory=tuple)


DEFAULT_CHROME = SiteChrome()

_DEFAULT_FOOTER = (
    "<p>Static Markus output from "
    "<code>poetry run papyrus renderers markus-build</code>.</p>"
)


def render_page(
    *,
    title: str,
    fragment: str,
    active_href: str,
    nav_items: list[NavItem],
    depth: int = 0,
    site_name: str | None = None,
    chrome: SiteChrome | None = None,
    css_version: str | None = None,
) -> str:
    chrome = chrome or DEFAULT_CHROME
    # `site_name` stays an explicit override so existing callers keep working.
    resolved_site_name = site_name if site_name is not None else chrome.site_name

    prefix = "../" * depth
    nav_links = []
    for item in nav_items:
        href = item.href if depth == 0 else f"{prefix}{item.href}"
        current = ' aria-current="page"' if item.href == active_href else ""
        nav_links.append(
            f'<a href="{html.escape(href, quote=True)}"{current}>{html.escape(item.label)}</a>'
        )
    nav_html = "\n      ".join(nav_links)
    safe_title = html.escape(title)
    safe_site = html.escape(resolved_site_name)
    # Avoid "<title>Pilobolus · Pilobolus</title>" when a page's own title
    # (e.g. a homepage front-matter title matching the site name) is
    # identical to the site name -- the " · site" suffix exists to
    # disambiguate a page from the site, which is meaningless when they're
    # the same string.
    title_tag = safe_site if title.strip() == resolved_site_name.strip() else f"{safe_title} · {safe_site}"

    # Cache-busting query on the stylesheets. Without it a browser serves a
    # stale theme and a CSS fix silently appears not to have worked.
    suffix = f"?v={html.escape(css_version, quote=True)}" if css_version else ""

    tagline_html = ""
    if chrome.tagline:
        tagline_html = (
            f'\n    <p class="markus-site-tagline">{html.escape(chrome.tagline)}</p>'
        )

    script_html = ""
    if chrome.scripts:
        tags = [
            f'<script src="{html.escape(prefix + src, quote=True)}{suffix}"></script>'
            for src in chrome.scripts
        ]
        script_html = "\n" + "\n".join(tags)
        # Exposed so a chrome script that itself picks and injects a *further*
        # script at runtime (background-manager.js choosing one of the
        # effect scripts) can carry the same cache-busting version onto that
        # dynamic src -- otherwise only the scripts named here are versioned,
        # and anything they load themselves keeps getting served stale.
        if css_version:
            version_json = json.dumps(css_version)
            script_html = (
                f"\n<script>window.__markusAssetVersion = {version_json};</script>"
                + script_html
            )

    footer_inner = chrome.footer_html or _DEFAULT_FOOTER

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_tag}</title>
<link rel="stylesheet" href="{prefix}css/markus-vendor.css{suffix}">
<link rel="stylesheet" href="{prefix}css/site-theme.css{suffix}">
</head>
<body class="markus-body markus-site">
  <header class="markus-site-masthead">
    <p class="markus-site-wordmark"><a href="{prefix}index.html">{safe_site}</a></p>{tagline_html}
    <nav class="markus-site-nav" aria-label="Site">
      {nav_html}
    </nav>
  </header>
  <main>
{fragment}
  </main>
  <footer class="markus-site-footer">
    {footer_inner}
  </footer>{script_html}
</body>
</html>
"""
