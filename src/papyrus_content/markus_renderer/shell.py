"""HTML page shell for Markus static output.

The shell is deliberately *configurable* rather than hardcoded. Every knob
lives on :class:`SiteChrome` and every knob defaults to the shape Papyrus's
own site (and Pilobol.us) already emits, so adding one is inert for existing
callers. The reason the knobs exist at all: a publication whose stylesheet
targets a different DOM (Anth.us, rebuilt from a Gatsby site that must stay
pixel-identical) previously had no way in and had to monkeypatch
``shell.render_page`` wholesale. Replacing a module-level function in another
package is not an API; ``render_masthead`` / ``render_body`` are.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field


_GA_ID_RE = re.compile(r"G-[A-Z0-9]{4,20}")


def render_ga4_snippet(measurement_id: str) -> str:
    """Google's standard gtag.js GA4 snippet (async loader + config call)."""
    if not isinstance(measurement_id, str) or not _GA_ID_RE.fullmatch(measurement_id):
        raise ValueError(
            f"ga_measurement_id must look like 'G-XXXXXXXXXX', got {measurement_id!r}"
        )
    # The pattern admits only [A-Z0-9-], so the id is safe in a URL, an HTML
    # attribute and a JS string literal as-is; escape anyway for defence.
    safe = html.escape(measurement_id, quote=True)
    return (
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={safe}"></script>\n'
        "<script>\n"
        "window.dataLayer = window.dataLayer || [];\n"
        "function gtag(){dataLayer.push(arguments);}\n"
        "gtag('js', new Date());\n"
        f"gtag('config', {json.dumps(measurement_id)});\n"
        "</script>"
    )


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

    Layout fields (all defaulted to today's output, so an existing caller that
    constructs ``SiteChrome`` the old way gets byte-identical HTML):

    ``lang``
        ``<html lang="...">``.
    ``body_class``
        ``<body class="...">``.
    ``stylesheets``
        Stylesheet hrefs, each prefixed and cache-busted like today's two.
        An empty tuple emits no ``<link rel="stylesheet">`` at all.
    ``head_html``
        Raw markup emitted immediately after ``</title>`` -- meta/OG tags,
        preloads, a publication's own font links.
    ``ga_measurement_id``
        Optional Google Analytics 4 measurement id (``G-XXXXXXXXXX``). When
        set, the standard gtag.js snippet is emitted in ``<head>`` on every
        page, after ``head_html`` and before the stylesheets. ``None`` (the
        default) emits nothing. Set by publication build code only, never from
        content; an id that does not match the GA4 pattern raises ``ValueError``.
    ``title_template`` / ``same_title_template``
        ``str.format`` templates over ``{title}`` and ``{site}`` (both already
        HTML-escaped). ``same_title_template`` is used when the page title
        equals the site name, which is why the default drops the suffix: see
        the note in :func:`render_page`.
    ``asset_root``
        ``None`` keeps today's depth-relative ``"../" * depth`` prefix. A
        string (``"/"``) makes every asset, script and nav href site-absolute
        instead -- what a publication deployed at a domain root wants, and the
        only way to share one rendered fragment across depths.
    ``render_masthead`` / ``render_body``
        Publication-supplied overrides. ``render_masthead(ctx)`` returns the
        masthead block; ``render_body(ctx, parts)`` returns everything between
        ``<body ...>`` and ``</body>``, given the default parts it can reuse,
        reorder or discard. ``render_masthead`` runs first and its result is
        handed to ``render_body`` in ``parts.masthead``, so a publication can
        replace only the masthead and still let the default body assembly run.
    """

    site_name: str = "Papyrus Markus"
    tagline: str | None = None
    footer_html: str | None = None
    scripts: tuple[str, ...] = field(default_factory=tuple)
    lang: str = "en"
    body_class: str = "markus-body markus-site"
    stylesheets: tuple[str, ...] = ("css/markus-vendor.css", "css/site-theme.css")
    head_html: str = ""
    ga_measurement_id: str | None = None
    title_template: str = "{title} · {site}"
    same_title_template: str = "{site}"
    asset_root: str | None = None
    render_masthead: Callable[["PageContext"], str] | None = None
    render_body: Callable[["PageContext", "BodyParts"], str] | None = None


@dataclass(frozen=True)
class PageContext:
    """Everything a publication hook needs to render its own chrome.

    Passed to ``SiteChrome.render_masthead`` / ``render_body``. ``prefix`` and
    ``asset_suffix`` are the *resolved* values the default shell itself uses,
    so a hook that builds its own hrefs stays consistent with the ones the
    shell emits (depth-relative or ``asset_root``-absolute, cache-busted or
    not) without recomputing them and drifting.
    """

    title: str
    site_name: str
    active_href: str
    nav_items: tuple[NavItem, ...]
    depth: int
    prefix: str
    asset_suffix: str
    fragment: str
    chrome: "SiteChrome"


@dataclass(frozen=True)
class BodyParts:
    """The four default body blocks, pre-rendered.

    Handed to ``SiteChrome.render_body`` so an override is additive: reuse
    ``main`` and ``scripts`` verbatim while replacing the wrapper, rather than
    reimplementing fragment indentation and script cache-busting.
    """

    masthead: str
    main: str
    footer: str
    scripts: str


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

    # `asset_root` of None preserves the depth-relative behaviour this shell
    # has always had; a string replaces it outright. Everything downstream
    # (stylesheets, scripts, wordmark, nav) goes through this one value, so
    # there is no way for half a page to be relative and half absolute.
    prefix = "../" * depth if chrome.asset_root is None else chrome.asset_root

    nav_links = []
    for item in nav_items:
        href = f"{prefix}{item.href}"
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
    template = (
        chrome.same_title_template
        if title.strip() == resolved_site_name.strip()
        else chrome.title_template
    )
    title_tag = template.format(title=safe_title, site=safe_site)

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

    ctx = PageContext(
        title=title,
        site_name=resolved_site_name,
        active_href=active_href,
        nav_items=tuple(nav_items),
        depth=depth,
        prefix=prefix,
        asset_suffix=suffix,
        fragment=fragment,
        chrome=chrome,
    )

    default_masthead = (
        '  <header class="markus-site-masthead">\n'
        f'    <p class="markus-site-wordmark">'
        f'<a href="{prefix}index.html">{safe_site}</a></p>{tagline_html}\n'
        '    <nav class="markus-site-nav" aria-label="Site">\n'
        f"      {nav_html}\n"
        "    </nav>\n"
        "  </header>"
    )
    # Masthead first, unconditionally: `render_body` receives the *resolved*
    # masthead in `parts`, so overriding only the masthead still works when
    # the default body assembly runs, and overriding both does not render the
    # masthead twice.
    masthead = (
        chrome.render_masthead(ctx)
        if chrome.render_masthead is not None
        else default_masthead
    )

    main = f"  <main>\n{fragment}\n  </main>"
    footer = (
        '  <footer class="markus-site-footer">\n'
        f"    {footer_inner}\n"
        "  </footer>"
    )
    parts = BodyParts(
        masthead=masthead, main=main, footer=footer, scripts=script_html
    )

    if chrome.render_body is not None:
        body_inner = chrome.render_body(ctx, parts)
    else:
        body_inner = f"{masthead}\n{main}\n{footer}{script_html}"

    head_lines = [
        "<!DOCTYPE html>",
        f'<html lang="{html.escape(chrome.lang, quote=True)}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title_tag}</title>{chrome.head_html}",
    ]
    if chrome.ga_measurement_id is not None:
        head_lines.append(render_ga4_snippet(chrome.ga_measurement_id))
    head_lines.extend(
        f'<link rel="stylesheet" href="{prefix}{sheet}{suffix}">'
        for sheet in chrome.stylesheets
    )
    head_lines.append("</head>")
    head = "\n".join(head_lines)

    return (
        f"{head}\n"
        f'<body class="{html.escape(chrome.body_class, quote=True)}">\n'
        f"{body_inner}\n"
        "</body>\n"
        "</html>\n"
    )
