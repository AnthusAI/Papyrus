"""Draws a shared Story: the real public page renderer, then the DRAFT shell (docs/story-share-links.md).

The page comes from the site's own projector (``item_pages``), so it is the public layout of every site that has a standard front end. It is rendered on demand into the
response; nothing here has a writer, so nothing can reach the live site's prefix or bucket. Then one function, ``shape_share_page``, does what makes it a draft for every site
at once: the DRAFT band (the site's own colour tokens, an icon and the word DRAFT), ``DRAFT: `` in the title, no indexing, no analytics, no consent banner, no canonical
or sharing address, links and stylesheets pointed at the public site, and every picture sent through the link's own media route.
"""

from __future__ import annotations

import copy
import dataclasses
import html
import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from .projection.source import projected_item_from_row
from .story_shares import ShareRefused

BAND_ATTRIBUTE = "data-papyrus-share-band"
DRAFT_TITLE_PREFIX = "DRAFT: "

# Lucide "file-pen" (ISC licence), inlined so the page needs no icon font or script.
_ICON = (
    '<svg class="papyrus-share-band__icon" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
    '<path d="M12.5 22H18a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v9.5"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
    '<path d="M13.378 15.626a1 1 0 1 0-3.004-3.004l-5.01 5.012a2 2 0 0 0-.506.854l-.837 2.87a.5.5 0 0 0 .62.62l2.87-.837a2 2 0 0 0 .854-.506z"/></svg>'
)

# Flat fills, no outlines. The band takes the page's own ink and background (tokens a Papyrus site defines) and swaps them, so it reads against any site's page in light and dark;
# a site without the tokens gets the browser's system colours, which swap the same way.
_BAND_STYLE = """<style data-papyrus-share-style>
.papyrus-share-band{position:sticky;top:0;z-index:2147483000;display:flex;flex-wrap:wrap;align-items:center;gap:.5rem .75rem;box-sizing:border-box;width:100%;padding:.65rem 1rem;
background:var(--papyrus-ink,CanvasText);color:var(--papyrus-bg,Canvas);font:600 .95rem/1.35 system-ui,-apple-system,"Segoe UI",sans-serif}
.papyrus-share-band__word{padding:.1rem .6rem;border-radius:var(--papyrus-radius,.375rem);background:var(--papyrus-bg,Canvas);color:var(--papyrus-ink,CanvasText);font-weight:800;letter-spacing:.14em}
.papyrus-share-band__text{font-weight:500}
.papyrus-share-band__icon{flex:none}
</style>"""

_ANALYTICS_SCRIPT = re.compile(r"<script\b[^>]*>(?:(?!</script>).)*?(?:googletagmanager|gtag\(|dataLayer|papyrusConsent|papyrus-consent)(?:(?!</script>).)*?</script>\s*", re.S | re.I)
_ANALYTICS_SRC = re.compile(r"<script\b[^>]*\bsrc=\"[^\"]*(?:googletagmanager|google-analytics)[^\"]*\"[^>]*></script>\s*", re.I)
_CONSENT_BLOCK = re.compile(r"<div id=\"papyrus-consent-banner\".*?</div>\s*</div>\s*", re.S)
_CONSENT_STYLE = re.compile(r"<style>\s*\.papyrus-consent\{.*?</style>\s*", re.S)
_LD_JSON = re.compile(r"<script\b[^>]*type=\"application/ld\+json\"[^>]*>.*?</script>\s*", re.S | re.I)
_HEAD_LINK = re.compile(r"<link\b[^>]*\brel=\"(?:canonical|alternate|sitemap|amphtml|prev|next)\"[^>]*>\s*", re.I)
_SOCIAL_META = re.compile(r"<meta\b[^>]*\b(?:property|name)=\"(?:og|twitter|article):[^\"]*\"[^>]*>\s*", re.I)
_PAGE_ACTIONS = re.compile(r"<div class=\"markus-page-actions[^>]*>.*?</span></div>\s*", re.S)
_PAGE_ACTIONS_SCRIPT = re.compile(r"<script\b[^>]*papyrus-page-actions[^>]*></script>\s*", re.I)
_TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_BODY_OPEN = re.compile(r"<body\b[^>]*>", re.I)
_IMAGE_TAG = re.compile(r"<(?:img|source)\b[^>]*>", re.I)
_ATTRIBUTE = re.compile(r"\b(src|srcset)=\"([^\"]*)\"", re.I)
_LINK_ATTRIBUTE = re.compile(r"(<(?:a|link|script)\b[^>]*?\b(?:href|src)=\")(/[^/\"][^\"]*|/)(\")", re.I)
_SRCSET_ENTRY = re.compile(r"\s*([^\s,][^\s]*)(\s+[0-9.]+[wx])?\s*(?:,|$)")


@dataclass(frozen=True)
class SharePage:
    html: str
    title: str
    images: tuple[str, ...]  # every picture address the page asked for, exactly as the renderer wrote it: the whole of what the media route may serve


@dataclass(frozen=True)
class ShareShell:
    """What the shell needs to know about the link, none of it secret."""

    token: str
    public_origin: str | None
    media_path: str  # e.g. /api/share/<token>/media
    note: str  # the sentence next to DRAFT


def public_origin_of(projector) -> str | None:
    environment = getattr(projector, "environment", None)
    origin = getattr(environment, "origin", None)
    return str(origin).rstrip("/") if origin else None


def without_analytics(projector):
    """A copy of the projector whose chrome carries no analytics id and no consent banner. The live projector is not touched."""
    settings = getattr(projector, "_settings", None)
    chrome = getattr(settings, "chrome", None)
    if chrome is None or not dataclasses.is_dataclass(chrome):
        return projector
    quiet = copy.copy(projector)
    quiet._settings = dataclasses.replace(settings, chrome=dataclasses.replace(chrome, ga_measurement_id=None, ga_owner_opt_out=False, consent_mode=None))
    return quiet


def render_story_page(projector, row: dict, site) -> str:
    """The Story's page in the public layout, as HTML. ``row`` is a version of the Story (a draft is fine); ``site`` is the published site index."""
    item = projected_item_from_row(row)
    quiet = without_analytics(projector)
    keys = quiet.item_page_paths(item.summary)
    if not keys:
        raise ShareRefused("This Story's type has no page on the public site, so there is nothing to show.")
    pages = quiet.item_pages(item, site)
    page = pages.get(keys[0])
    if page is None:
        raise ShareRefused("The public site did not draw a page for this Story.")
    return page.decode("utf-8")


def _site_path(url: str, origin: str | None) -> str | None:
    """The root-relative path of a picture on the public site, or None when it is somebody else's address or not a path at all."""
    candidate = url.strip()
    if not candidate or candidate.startswith(("data:", "blob:", "#", "//")):
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", candidate):
        if origin and candidate.startswith(origin + "/"):
            return candidate[len(origin):]
        return None
    return candidate


def _media_url(shell: ShareShell, original: str) -> str:
    return f"{shell.media_path}?u={quote(original, safe='')}"


def _rewrite_srcset(value: str, rewrite) -> str:
    entries = []
    position = 0
    while position < len(value):
        match = _SRCSET_ENTRY.match(value, position)
        if not match or match.end() == position:
            break
        entries.append(rewrite(match.group(1)) + (match.group(2) or ""))
        position = match.end()
    return ", ".join(entries)


def _route_images(page: str, shell: ShareShell) -> tuple[str, tuple[str, ...]]:
    images: list[str] = []

    def rewrite_url(url: str) -> str:
        if _site_path(url, shell.public_origin) is None:
            return url
        if url not in images:
            images.append(url)
        return _media_url(shell, url)

    def rewrite_tag(tag: re.Match) -> str:
        def attribute(match: re.Match) -> str:
            name, value = match.group(1).lower(), html.unescape(match.group(2))
            replaced = rewrite_url(value) if name == "src" else _rewrite_srcset(value, rewrite_url)
            return f'{match.group(1)}="{html.escape(replaced, quote=True)}"'

        return _ATTRIBUTE.sub(attribute, tag.group(0))

    return _IMAGE_TAG.sub(rewrite_tag, page), tuple(images)


def _band(shell: ShareShell) -> str:
    return (
        f'<div class="papyrus-share-band" role="region" aria-label="Draft notice" {BAND_ATTRIBUTE}>{_ICON}'
        f'<span class="papyrus-share-band__word">DRAFT</span><span class="papyrus-share-band__text">{html.escape(shell.note)}</span></div>'
    )


def shape_share_page(page: str, shell: ShareShell) -> SharePage:
    """Makes a rendered public page a draft. Every site gets it from here."""
    title_match = _TITLE.search(page)
    title = html.unescape(title_match.group(1)).strip() if title_match else ""
    page = _TITLE.sub(lambda _m: f"<title>{html.escape(DRAFT_TITLE_PREFIX + title)}</title>", page, count=1)
    for pattern in (_PAGE_ACTIONS, _PAGE_ACTIONS_SCRIPT, _ANALYTICS_SRC, _ANALYTICS_SCRIPT, _CONSENT_BLOCK, _CONSENT_STYLE, _LD_JSON, _HEAD_LINK, _SOCIAL_META):
        page = pattern.sub("", page)
    if shell.public_origin:
        origin = shell.public_origin
        page = _LINK_ATTRIBUTE.sub(lambda m: f"{m.group(1)}{html.escape(origin, quote=True)}{m.group(2)}{m.group(3)}", page)
    page, images = _route_images(page, shell)
    head_additions = '<meta name="robots" content="noindex, nofollow">\n<meta name="referrer" content="no-referrer">\n' + _BAND_STYLE + "\n"
    if "</head>" in page:
        page = page.replace("</head>", head_additions + "</head>", 1)
    else:
        page = head_additions + page
    body = _BODY_OPEN.search(page)
    band = _band(shell)
    page = page[: body.end()] + "\n" + band + page[body.end():] if body else band + page
    return SharePage(html=page, title=DRAFT_TITLE_PREFIX + title, images=images)


def share_note(version_number: int | None, follows_current: bool, signed_in_only: bool) -> str:
    who = "Shared with signed-in newsroom members only." if signed_in_only else "Shared by link, for review."
    shown = f"Version {version_number}" if version_number is not None else "The current version"
    suffix = " (follows new versions)" if follows_current else ""
    return f"Not published. {who} {shown}{suffix}."


def notice_page(heading: str, lines: list[str], *, link: tuple[str, str] | None = None) -> str:
    """A small plain page for the answers that are not a Story: used by the route, kept here with the other markup so one place owns what a stranger sees."""
    body = "".join(f"<p>{html.escape(line)}</p>" for line in lines)
    anchor = f'<p><a href="{html.escape(link[0], quote=True)}">{html.escape(link[1])}</a></p>' if link else ""
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow"><meta name="referrer" content="no-referrer">'
        f"<title>{html.escape(heading)}</title>"
        "<style>:root{color-scheme:light dark}body{margin:0;display:grid;min-height:100vh;place-items:center;font:1rem/1.5 system-ui,sans-serif;background:Canvas;color:CanvasText}"
        "main{max-width:32rem;padding:1.5rem}h1{font-size:1.4rem;margin:0 0 .75rem}a{color:inherit}</style></head>"
        f"<body><main><h1>{html.escape(heading)}</h1>{body}{anchor}</main></body></html>"
    )


def is_safe_media_reference(url: str) -> bool:
    """A picture address the media route will even consider: no scheme tricks, no parent segments, no control characters."""
    if not url or len(url) > 2048 or re.search(r"[\x00-\x1f\\]", url):
        return False
    parts = urlsplit(url)
    if parts.scheme or parts.netloc:
        return False
    return ".." not in [segment for segment in parts.path.split("/")]
