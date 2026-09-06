"""HTML page shell for Markus static output."""

from __future__ import annotations

import html
from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    label: str
    href: str


def render_page(
    *,
    title: str,
    fragment: str,
    active_href: str,
    nav_items: list[NavItem],
    depth: int = 0,
    site_name: str = "Papyrus Markus",
) -> str:
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
    safe_site = html.escape(site_name)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title} · {safe_site}</title>
<link rel="stylesheet" href="{prefix}css/markus-vendor.css">
<link rel="stylesheet" href="{prefix}css/site-theme.css">
</head>
<body class="markus-body markus-site">
  <header class="markus-site-masthead">
    <p class="markus-site-wordmark"><a href="{prefix}index.html">{safe_site}</a></p>
    <nav class="markus-site-nav" aria-label="Site">
      {nav_html}
    </nav>
  </header>
  <main>
{fragment}
  </main>
  <footer class="markus-site-footer">
    <p>Static Markus output from <code>poetry run papyrus renderers markus-build</code>.</p>
  </footer>
</body>
</html>
"""
