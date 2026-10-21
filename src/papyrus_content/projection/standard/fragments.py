"""Helpers for working with a converted Markus fragment; hooks import these too."""

from __future__ import annotations

import datetime as dt
import html
import re

LEDE_PATTERN = re.compile(r'<p(?![^>]*\bmarkus-(?:band-eyebrow|actions)\b)[^>]*>(.*?)</p>', re.S)
TAG_PATTERN = re.compile(r"<[^>]+>")
FIRST_IMAGE_PATTERN = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"')
MARKUS_HEADER_PATTERN = re.compile(r'<header class="markus-header">.*?</header>', re.S)
MARKUS_ARTICLE_OPEN_PATTERN = re.compile(r'^\s*<article class="markus-document">')
MARKUS_ARTICLE_CLOSE_PATTERN = re.compile(r"</article>\s*$")


def article_body(fragment: str) -> str:
    """The Markus article without its ``<article>`` wrapper and ``<header>``; for hooks that supply their own."""
    fragment = MARKUS_HEADER_PATTERN.sub("", fragment, count=1)
    fragment = MARKUS_ARTICLE_OPEN_PATTERN.sub("", fragment, count=1)
    return MARKUS_ARTICLE_CLOSE_PATTERN.sub("", fragment, count=1).strip()


LISTING_PLACEHOLDER = "<p>{{ section listing }}</p>"


def with_listing(fragment: str, listing_html: str) -> str:
    """Place a generated listing in a section introduction: at the ``{{ section listing }}`` line, else at the end."""
    if LISTING_PLACEHOLDER in fragment:
        return fragment.replace(LISTING_PLACEHOLDER, listing_html, 1)
    closing = MARKUS_ARTICLE_CLOSE_PATTERN.search(fragment)
    if closing is not None:
        return fragment[: closing.start()] + listing_html + fragment[closing.start():]
    return fragment + listing_html


LEDE_PARAGRAPH = re.compile(r'<p class="markus-lede">.*?</p>', re.S)
ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def with_lede(fragment: str, text) -> str:
    """Print ``text`` as the article's lede (``<p class="markus-lede">``): it replaces the header's lede, else ends the header.

    A fragment with no header or an empty text is returned as it is."""
    text = str(text).strip() if text is not None and not isinstance(text, (list, dict)) else ""
    match = MARKUS_HEADER_PATTERN.search(fragment)
    if not text or match is None:
        return fragment
    lede = f'<p class="markus-lede">{html.escape(text, quote=False)}</p>'
    header = match.group(0)
    header = LEDE_PARAGRAPH.sub(lambda _found: lede, header, count=1) if "markus-lede" in header else header[: -len("</header>")] + lede + "</header>"
    return fragment[: match.start()] + header + fragment[match.end():]


def with_date_format(fragment: str, date_format: str) -> str:
    """Write the dates of the article header (``YYYY-MM-DD``) with ``date_format`` (``site.dateFormat``)."""
    match = MARKUS_HEADER_PATTERN.search(fragment)
    if not date_format or match is None:
        return fragment

    def shown(found: re.Match) -> str:
        try:
            return dt.date.fromisoformat(found.group(1)).strftime(date_format)
        except ValueError:
            return found.group(0)

    return fragment[: match.start()] + ISO_DATE.sub(shown, match.group(0)) + fragment[match.end():]


def plain_text(fragment_html: str) -> str:
    return " ".join(html.unescape(TAG_PATTERN.sub(" ", fragment_html)).split())


def lede_of(fragment: str, limit: int = 200) -> str:
    body = MARKUS_HEADER_PATTERN.sub("", fragment, count=1)
    match = LEDE_PATTERN.search(body)
    if not match:
        return ""
    text = plain_text(match.group(1))
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def first_image_of(fragment: str) -> str | None:
    match = FIRST_IMAGE_PATTERN.search(fragment)
    return match.group(1) if match else None


