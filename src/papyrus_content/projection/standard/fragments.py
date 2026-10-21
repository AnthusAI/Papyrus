"""Helpers for working with a converted Markus fragment; hooks import these too."""

from __future__ import annotations

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


