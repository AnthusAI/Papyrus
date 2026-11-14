"""Page actions: copy the page as Markdown, view it as Markdown, open it in an AI assistant, post or share it.

The markup works without JavaScript: a labelled list of links ("View as Markdown", and "Open in ..." when configured).
``_plugins/papyrus-page-actions-v1.js`` enhances it: it adds a "Copy Markdown" button, turns the links into a menu
button following the ARIA menu pattern, and confirms a copy in a polite live region.

Copying fetches the page's own ``.md`` twin (the file the edge serves) and prefixes the title and canonical URL when the
twin does not already carry them. The AI links carry only a short prompt with the page's URL; the page body is never
put in a URL. Opening one is an explicit user action; the only reporting is a ``page_action`` event through the site's
existing ``gtag`` (so consent mode applies).

``pageActions.display: "icons"`` is the compact form: Lucide icon buttons instead of text, plus the opt-in actions ``x``
and ``reddit`` (plain links that carry only the page title and its address) and ``share`` (the script adds a popup,
built as the same ARIA menu button, that shares the web page or its Markdown). Without JavaScript the icon links still
work and the share button is simply absent. Core places the markup; a site that composes its own body places it with
``page.article_actions()``.
"""

from __future__ import annotations

import html
from urllib.parse import quote, urlencode

from .config import AI_DESTINATIONS, PageActionSettings

SCRIPT_PATH = "_plugins/papyrus-page-actions-v1.js"
STYLESHEET_PATH = "_plugins/papyrus-page-actions.css"
#: Class-name stems of the page-actions rules in ``markus-components.css``. A site that does not link the whole component
#: stylesheet (``site.componentsCss: false``) gets just these lines (see :func:`stylesheet_text`).
STYLESHEET_MARKERS = ("markus-page-actions", "markus-actions-", "markus-copy-md", "markus-icon-action", "markus-action-icon")

# Lucide icons (lucide.dev, ISC licence) on the 24 px grid, drawn in currentColor.
_LUCIDE = (
    '<svg class="markus-action-icon" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false" '
    'data-icon="{name}">{body}</svg>'
)
FILE_TEXT_ICON = _LUCIDE.format(
    name="file-text",
    body='<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/>'
    '<path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
)
COPY_ICON = _LUCIDE.format(
    name="copy",
    body='<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
)
# Lucide has no brand marks. These are the simple X and Reddit marks Machines on Machines already uses.
X_MARK = (
    '<svg class="markus-action-icon" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" '
    'focusable="false" data-icon="x"><path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 '
    '21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>'
)
REDDIT_MARK = (
    '<svg class="markus-action-icon" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" '
    'focusable="false" data-icon="reddit"><path fill="currentColor" d="M12 0C5.373 0 0 5.373 0 12c0 3.314 1.343 6.314 3.515 8.485l-2.286 '
    '2.286C.775 23.225 1.097 24 1.738 24H12c6.627 0 12-5.373 12-12S18.627 0 12 0Zm4.388 3.199c1.104 0 1.999.895 1.999 1.999 0 1.105-.895 '
    '2-1.999 2-.946 0-1.739-.657-1.947-1.539v.002c-1.147.162-2.032 1.15-2.032 2.341v.007c1.776.067 3.4.567 4.686 1.363.473-.363 1.064-.58 '
    '1.707-.58 1.547 0 2.802 1.254 2.802 2.802 0 1.117-.655 2.081-1.601 2.531-.088 3.256-3.637 5.876-7.997 5.876-4.361 0-7.905-2.617-7.998-5.87'
    '-.954-.447-1.614-1.415-1.614-2.538 0-1.548 1.255-2.802 2.803-2.802.645 0 1.239.218 1.712.585 1.275-.79 2.881-1.291 4.64-1.365v-.01c0-1.663 '
    '1.263-3.034 2.88-3.207.188-.911.993-1.595 1.959-1.595Zm-8.085 8.376c-.784 0-1.459.78-1.506 1.797-.047 1.016.64 1.429 1.426 1.429.786 0 '
    '1.371-.369 1.418-1.385.047-1.017-.553-1.841-1.338-1.841Zm7.406 0c-.786 0-1.385.824-1.338 1.841.047 1.017.634 1.385 1.418 1.385.785 0 '
    '1.473-.413 1.426-1.429-.047-1.017-.721-1.797-1.506-1.797Zm-3.703 4.013c-.974 0-1.907.048-2.77.135-.147.015-.241.168-.183.305.483 1.154 '
    '1.622 1.964 2.953 1.964 1.33 0 2.47-.81 2.953-1.964.057-.137-.037-.29-.184-.305-.863-.087-1.795-.135-2.769-.135Z"/></svg>'
)


def _q(value) -> str:
    return html.escape(str(value), quote=True)


def ai_links(settings: PageActionSettings, canonical: str | None) -> list[tuple[str, str, str]]:
    """``[(id, label, url)]`` for the configured destinations; none when the page has no absolute URL to point at."""
    if not canonical:
        return []
    prompt = quote(settings.prompt.replace("{url}", canonical), safe="")
    return [(name, AI_DESTINATIONS[name][0], AI_DESTINATIONS[name][1] + prompt) for name in settings.ai]


def social_links(title: str, canonical: str | None) -> list[tuple[str, str, str]]:
    """``[(id, label, url)]`` for X and Reddit. The link carries the page title and address, never the body."""
    if not canonical:
        return []
    return [
        ("x", "Post on X", "https://x.com/intent/post?" + urlencode({"text": title, "url": canonical}, quote_via=quote)),
        ("reddit", "Post on Reddit", "https://www.reddit.com/submit?" + urlencode({"url": canonical, "title": title}, quote_via=quote)),
    ]


def _icon_link(name: str, label: str, href: str, icon: str, *, external: bool = False) -> str:
    target = ' target="_blank" rel="noopener noreferrer"' if external else ""
    return (
        f'<li><a class="markus-action-link markus-icon-action" data-action="{_q(name)}" href="{_q(href)}"{target} '
        f'aria-label="{_q(label)}" title="{_q(label)}">{icon}</a></li>'
    )


def render_page_actions(settings: PageActionSettings, *, markdown_path: str, title: str, canonical: str | None) -> str:
    icons = settings.display == "icons"
    items = []
    icon_items = []
    if "view" in settings.actions:
        if icons:
            icon_items.append(_icon_link("view", "View as Markdown", markdown_path, FILE_TEXT_ICON))
        else:
            items.append(f'<li><a class="markus-action-link" data-action="view" href="{_q(markdown_path)}">View as Markdown</a></li>')
    if icons:
        icon_items.extend(
            _icon_link(name, label, url, X_MARK if name == "x" else REDDIT_MARK, external=True)
            for name, label, url in social_links(title, canonical)
            if name in settings.actions
        )
    for name, label, url in ai_links(settings, canonical):
        items.append(
            f'<li><a class="markus-action-link" data-action="{_q(name)}" href="{_q(url)}" target="_blank" rel="noopener noreferrer">{_q(label)}</a></li>'
        )
    share = icons and "share" in settings.actions and bool(canonical)
    if not items and not icon_items and "copy" not in settings.actions and not share:
        return ""
    copy = ""
    if "copy" in settings.actions:
        copy = (
            f'<button type="button" class="markus-copy-md markus-icon-action" data-action="copy" aria-label="Copy Markdown" title="Copy Markdown">{COPY_ICON}</button>'
            if icons
            else '<button type="button" class="markus-copy-md" data-action="copy">Copy Markdown</button>'
        )
    icon_list = f'<ul class="markus-actions-icons" aria-label="Read and post this page">{"".join(icon_items)}</ul>' if icon_items else ""
    links = f'<ul class="markus-actions-links" aria-label="More ways to read this page">{"".join(items)}</ul>' if items else ""
    classes = f"markus-page-actions markus-page-actions-{settings.placement}" + (" markus-page-actions-icons" if icons else "")
    return (
        f'<div class="{classes}" role="group" aria-label="Page actions" '
        f'data-papyrus-page-actions data-markdown="{_q(markdown_path)}" data-title="{_q(title)}" data-canonical="{_q(canonical or "")}"'
        f'{" data-share" if share else ""}>'
        f'{icon_list}{copy}{links}<span class="markus-actions-status" role="status" aria-live="polite"></span></div>'
    )


def stylesheet_text(components_css: str) -> str:
    """Just the page-actions rules of the component stylesheet, for a site that does not link the whole of it."""
    return "\n".join(line for line in components_css.splitlines() if any(marker in line for marker in STYLESHEET_MARKERS)) + "\n"
