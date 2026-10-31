"""Public thread pages: one static, read-only page per public thread at ``<homePage.forum.threadBase>/<key>/``.

A page is drawn from the per-thread document ``_data/home-page/threads/<key>.json`` that the home-page snapshot writes, and from nothing
else but that Thread's anchor Reference when the snapshot holds it. The Messages come in sequence, one flat block each, by their public
handle (a Lucide ``user`` icon) or their role label (``badge-check``); an edited Message says so in words beside a ``pencil`` icon. Text
is escaped and set as paragraphs: the snapshot already stripped raw HTML and anything shaped like an email address, an id or a site
subject. The stylesheet draws no borders.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ...home_page.export import KEY_LENGTH, clip_summary
from . import home_page_components as parts
from .head import PageHead
from .knowledge_components import esc

if TYPE_CHECKING:
    from .page import StandardPage

THREAD_KEY = re.compile(f"[0-9a-f]{{{KEY_LENGTH}}}")
DESCRIPTION_CHARACTERS = 200


def is_thread_key(value: Any) -> bool:
    return isinstance(value, str) and THREAD_KEY.fullmatch(value) is not None


def thread_site_path(thread_base: str, key: str) -> str:
    """The site-relative directory path of a thread page: ``/conversations/<key>/``."""
    return f"/{thread_base}/{key}/"


def thread_site_key(thread_base: str, key: str) -> str:
    return f"{thread_base}/{key}/index.html"


def thread_keys(threads_document: Mapping | None) -> list[str]:
    """The keys of the threads that ``threads.json`` lists, in file order; a key that is not an opaque thread key is skipped."""
    entries = (threads_document or {}).get("threads") or []
    return [entry["key"] for entry in entries if isinstance(entry, Mapping) and is_thread_key(entry.get("key"))]


def messages_of(thread: Mapping) -> list[Mapping]:
    return [message for message in thread.get("messages") or [] if isinstance(message, Mapping)]


def thread_head(thread: Mapping, path: str) -> PageHead:
    messages = messages_of(thread)
    first = parts.plain_text(str(messages[0].get("text") or "")) if messages else ""
    return PageHead(title=str(thread.get("title") or "Conversation"), path=path, description=clip_summary(first, DESCRIPTION_CHARACTERS) or "")


def text_markup(text: Any) -> str:
    paragraphs = [block for block in re.split(r"\n\s*\n", str(text or "").strip()) if block.strip()]
    return "".join(f"<p>{esc(block.strip()).replace(chr(10), '<br>')}</p>" for block in paragraphs)


def author_markup(author: Mapping) -> str:
    handle = author.get("handle")
    icon, kind = (parts.USER_ICON, "handle") if handle else (parts.BADGE_CHECK_ICON, "label")
    return f'<span class="home-page-author-name" data-author-kind="{kind}">{icon}<span>{esc(parts.author_text(author) or "Editor")}</span></span>'


def message_markup(message: Mapping) -> str:
    edited = f'<span class="home-page-edited">{parts.PENCIL_ICON}<span>edited</span></span>' if message.get("edited") else ""
    when = parts.time_markup(message.get("at"))
    return (
        f'<article class="home-page-message" id="m-{esc(message.get("key"))}">'
        f'<header class="home-page-message-head">{author_markup(message.get("author") or {})}{when}{edited}</header>'
        f'<div class="home-page-message-text">{text_markup(message.get("text"))}</div></article>'
    )


def anchor_block(anchor: Mapping, reference: Mapping | None) -> str:
    """A Reference anchor is the Reference's own row card when the snapshot still holds it; a Story anchor is a line with a link."""
    if anchor.get("kind") == "reference" and reference is not None:
        return f'<div class="home-page-thread-anchor" data-kind="reference">{parts.row(reference)}</div>'
    return f'<div class="home-page-thread-anchor" data-kind="{esc(anchor.get("kind"))}">{parts.anchor_markup(anchor)}</div>'


def thread_fragment(thread: Mapping, reference: Mapping | None) -> str:
    messages = messages_of(thread)
    count = parts.message_count_text(len(messages))
    items = "".join(f"<li>{message_markup(message)}</li>" for message in messages)
    return (
        '<div class="markus-document home-page-thread-page">'
        f'<header class="home-page-thread-header">{anchor_block(thread.get("anchor") or {}, reference)}'
        f'<h1 class="home-page-thread-title">{esc(thread.get("title") or "Conversation")}</h1>'
        f'<p class="home-page-thread-meta"><span class="home-page-count">{parts.MESSAGE_SQUARE_ICON}<span>{count}</span></span></p></header>'
        f'<ol class="home-page-message-list">{items}</ol></div>'
    )


def thread_markdown(thread: Mapping, canonical: str | None, anchor_line: str) -> str:
    lines = [f"# {thread.get('title') or 'Conversation'}", ""]
    if anchor_line:
        lines += [anchor_line, ""]
    if canonical:
        lines += [f"Canonical: {canonical}", ""]
    for message in messages_of(thread):
        author = parts.author_text(message.get("author") or {}) or "Editor"
        when = parts.date_text(message.get("at"))
        edited = " (edited)" if message.get("edited") else ""
        lines += [f"## {author}" + (f", {when}" if when else "") + edited, "", str(message.get("text") or "").strip(), ""]
    return "\n".join(lines).rstrip() + "\n"


def anchor_markdown_line(anchor: Mapping, absolute_url) -> str:
    """``Reference: Title`` or ``Story: [Title](url)``; a Story link is made absolute with ``absolute_url``."""
    kind = "Story" if anchor.get("kind") == "story" else "Reference"
    title = str(anchor.get("title") or kind)
    href = absolute_url(anchor.get("url")) if kind == "Story" and anchor.get("url") else None
    return f"{kind}: [{title}]({href})" if href else f"{kind}: {title}"


def thread_page(projector: Any, site: Any, listed: list, thread: Mapping, reference: Mapping | None, thread_base: str) -> "StandardPage":
    """The page of one public thread, ready for the projector's render and Markdown paths."""
    path = projector.policy.path(thread_site_path(thread_base, str(thread["key"])))
    return projector._page(
        "thread", thread_head(thread, path), site, entries=tuple(listed),
        fragment=thread_fragment(thread, reference), thread=thread, thread_reference=reference,
    )
