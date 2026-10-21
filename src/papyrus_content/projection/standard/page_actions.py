"""Page actions: copy the page as Markdown, view it as Markdown, open it in an AI assistant.

The markup works without JavaScript: a labelled list of links ("View as Markdown", and "Open in ..." when configured).
``_plugins/papyrus-page-actions-v1.js`` enhances it: it adds a "Copy Markdown" button, turns the links into a menu
button following the ARIA menu pattern, and confirms a copy in a polite live region.

Copying fetches the page's own ``.md`` twin (the file the edge serves) and prefixes the title and canonical URL when the
twin does not already carry them. The AI links carry only a short prompt with the page's URL; the page body is never
put in a URL. Opening one is an explicit user action; the only reporting is a ``page_action`` event through the site's
existing ``gtag`` (so consent mode applies).
"""

from __future__ import annotations

import html
from urllib.parse import quote

from .config import AI_DESTINATIONS, PageActionSettings

SCRIPT_PATH = "_plugins/papyrus-page-actions-v1.js"


def _q(value) -> str:
    return html.escape(str(value), quote=True)


def ai_links(settings: PageActionSettings, canonical: str | None) -> list[tuple[str, str, str]]:
    """``[(id, label, url)]`` for the configured destinations; none when the page has no absolute URL to point at."""
    if not canonical:
        return []
    prompt = quote(settings.prompt.replace("{url}", canonical), safe="")
    return [(name, AI_DESTINATIONS[name][0], AI_DESTINATIONS[name][1] + prompt) for name in settings.ai]


def render_page_actions(settings: PageActionSettings, *, markdown_path: str, title: str, canonical: str | None) -> str:
    items = []
    if "view" in settings.actions:
        items.append(f'<li><a class="markus-action-link" data-action="view" href="{_q(markdown_path)}">View as Markdown</a></li>')
    for name, label, url in ai_links(settings, canonical):
        items.append(
            f'<li><a class="markus-action-link" data-action="{_q(name)}" href="{_q(url)}" target="_blank" rel="noopener noreferrer">{_q(label)}</a></li>'
        )
    if not items and "copy" not in settings.actions:
        return ""
    copy = (
        '<button type="button" class="markus-copy-md" data-action="copy">Copy Markdown</button>'
        if "copy" in settings.actions
        else ""
    )
    links = f'<ul class="markus-actions-links" aria-label="More ways to read this page">{"".join(items)}</ul>' if items else ""
    return (
        f'<div class="markus-page-actions markus-page-actions-{settings.placement}" role="group" aria-label="Page actions" '
        f'data-papyrus-page-actions data-markdown="{_q(markdown_path)}" data-title="{_q(title)}" data-canonical="{_q(canonical or "")}">'
        f'{copy}{links}<span class="markus-actions-status" role="status" aria-live="polite"></span></div>'
    )
