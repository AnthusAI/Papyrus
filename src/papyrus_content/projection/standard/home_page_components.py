"""Reference cards for the home page: a tile (the grid card) and a row (one line, with a compact confidence), as server-rendered markup that needs no script.

State is always written in words and drawn as an icon, never colour alone: a recommended Reference carries the chip "Recommended by
Cyclotron, not yet accepted" with a Lucide ``sparkles`` icon, and Cyclotron's confidence is the text "93% confidence" beside a Lucide
``gauge`` icon and a five-segment meter whose segments differ in shape (filled or outlined). Cards use flat tones and rounded
rectangles; the stylesheet draws no borders.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from datetime import datetime

from .knowledge_components import esc, safe_href

METER_SEGMENTS = 5
STATUS_RECOMMENDED = "recommended"
RECOMMENDED_LABEL = "Recommended by Cyclotron, not yet accepted"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DATE_PREFIX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
SVG_ATTRIBUTES = 'xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"'
GAUGE_ICON = f'<svg class="home-page-icon" data-icon="gauge" {SVG_ATTRIBUTES}><path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/></svg>'
SPARKLES_ICON = (
    f'<svg class="home-page-icon" data-icon="sparkles" {SVG_ATTRIBUTES}>'
    '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>'
    '<path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/></svg>'
)
LINK_ICON = f'<svg class="home-page-icon" data-icon="link" {SVG_ATTRIBUTES}><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>'
FILE_TEXT_ICON = (
    f'<svg class="home-page-icon" data-icon="file-text" {SVG_ATTRIBUTES}><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
    '<path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>'
)
USER_ICON = f'<svg class="home-page-icon" data-icon="user" {SVG_ATTRIBUTES}><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>'
BADGE_CHECK_ICON = (
    f'<svg class="home-page-icon" data-icon="badge-check" {SVG_ATTRIBUTES}>'
    '<path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z"/>'
    '<path d="m9 12 2 2 4-4"/></svg>'
)
PENCIL_ICON = (
    f'<svg class="home-page-icon" data-icon="pencil" {SVG_ATTRIBUTES}>'
    '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/></svg>'
)
VIDEO_ICON = (
    f'<svg class="home-page-icon" data-icon="video" {SVG_ATTRIBUTES}><path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5"/>'
    '<rect x="2" y="6" width="14" height="12" rx="2"/></svg>'
)
MEDIUM_LABELS = {"video": ("Video", VIDEO_ICON)}
MESSAGE_SQUARE_ICON = f'<svg class="home-page-icon" data-icon="message-square" {SVG_ATTRIBUTES}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'


def date_text(value) -> str:
    """``2026-10-20`` as ``20 Oct 2026``; empty when the value does not start with a date."""
    match = DATE_PREFIX.match(str(value or ""))
    if match is None:
        return ""
    year, month, day = (int(part) for part in match.groups())
    try:
        datetime(year, month, day)
    except ValueError:
        return ""
    return f"{day} {MONTHS[month - 1]} {year}"


def time_markup(value) -> str:
    text = date_text(value)
    return f'<time datetime="{esc(value)}">{esc(text)}</time>' if text else ""


def confidence_percent(confidence) -> int | None:
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    return round(max(0.0, min(1.0, float(confidence))) * 100)


def meter(percent: int) -> str:
    """Five segments, filled for each fifth reached: the shape (a solid block or an outline) carries the value."""
    filled = min(METER_SEGMENTS, (percent * METER_SEGMENTS + 50) // 100)
    segments = "".join(
        f'<rect class="home-page-meter-segment{" home-page-meter-segment--filled" if index < filled else ""}" x="{index * 7 + 1}" y="1" width="6" height="10" rx="1.5"/>'
        for index in range(METER_SEGMENTS)
    )
    return f'<svg class="home-page-meter" xmlns="http://www.w3.org/2000/svg" width="{METER_SEGMENTS * 7 + 1}" height="12" viewBox="0 0 {METER_SEGMENTS * 7 + 1} 12" aria-hidden="true" focusable="false">{segments}</svg>'


STAR_COUNT = 5
STAR_PATH = (
    '<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14'
    'a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755'
    'a2.122 2.122 0 0 0 1.597-1.16z"/>'
)
STAR_ATTRIBUTES = SVG_ATTRIBUTES.replace('width="16" height="16"', 'width="14" height="14"')


def star_count(reference: Mapping) -> int | None:
    """The editors' rating (1 to 5) an accepted Reference shows; None for a pending one, an unrated one, or a file written before the count was published."""
    value = reference.get("stars")
    if reference.get("status") == STATUS_RECOMMENDED or isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= STAR_COUNT:
        return None
    return value


def stars_markup(reference: Mapping, *, compact: bool = False) -> str:
    """The rating as five Lucide ``star`` icons, filled for each star given and outlined for the rest (the shape carries the value, never the colour), and the
    words "4 of 5 stars" for a screen reader. Empty when the Reference has no rating."""
    count = star_count(reference)
    if count is None:
        return ""
    icons = "".join(
        f'<svg class="home-page-star{" home-page-star--filled" if index < count else ""}" data-icon="star" {STAR_ATTRIBUTES}>{STAR_PATH}</svg>' for index in range(STAR_COUNT)
    )
    kind = " home-page-stars--compact" if compact else ""
    return f'<span class="home-page-stars{kind}" data-stars="{count}">{icons}<span class="home-page-visually-hidden">{count} of {STAR_COUNT} stars</span></span>'


def rating_or_confidence(reference: Mapping) -> str:
    """A rated accepted Reference shows its stars (a person's judgement stands in for the prediction); a Reference nobody rated shows the Cyclotron's confidence when it has one."""
    return stars_markup(reference) or confidence_markup(reference)


def editor_accepted(reference: Mapping) -> bool:
    """True for a Reference an editor accepted (``actor`` is ``human``). Once a person has accepted it the Cyclotron's confidence no longer matters, so no
    card shows it; one accepted by a Cyclotron or a rule keeps it, and so does a recommended one (nobody has accepted it yet)."""
    return reference.get("status") != STATUS_RECOMMENDED and reference.get("actor") == "human"


def confidence_markup(reference: Mapping) -> str:
    if editor_accepted(reference):
        return ""
    percent = confidence_percent(reference.get("confidence"))
    if percent is None:
        return ""
    return f'<p class="home-page-confidence">{GAUGE_ICON}<span class="home-page-confidence-value">{percent}% confidence</span>{meter(percent)}</p>'


def row_confidence_markup(reference: Mapping) -> str:
    """The compact confidence of a row: gauge icon, the number, a visually hidden "confidence" label, and the meter."""
    if editor_accepted(reference):
        return ""
    percent = confidence_percent(reference.get("confidence"))
    if percent is None:
        return ""
    return (
        f'<span class="home-page-confidence home-page-confidence--compact">{GAUGE_ICON}'
        f'<span class="home-page-confidence-value">{percent}%<span class="home-page-visually-hidden"> confidence</span></span>{meter(percent)}</span>'
    )


def actor_text(reference: Mapping) -> str:
    """Who accepted it, without naming anyone: an editor, or the system."""
    if reference.get("status") == STATUS_RECOMMENDED or not reference.get("actor"):
        return ""
    return "Accepted by an editor" if reference.get("actor") == "human" else "Accepted automatically"


def _link(reference: Mapping) -> str:
    title = esc(reference.get("title") or reference.get("url") or "Untitled")
    href = safe_href(reference.get("url"))
    return f'<a href="{esc(href)}" rel="noopener">{title}</a>' if href else title


def _dates(reference: Mapping) -> str:
    parts = []
    published = time_markup(reference.get("sourceDate"))
    if published:
        parts.append(f"<span>Published {published}</span>")
    accepted = time_markup(reference.get("acceptedAt"))
    if accepted and reference.get("status") != STATUS_RECOMMENDED:
        parts.append(f"<span>Accepted {accepted}</span>")
    return f'<p class="home-page-dates">{" ".join(parts)}</p>' if parts else ""


def medium_chip(reference: Mapping) -> str:
    """The medium in words with its Lucide icon (never colour alone); empty when the Reference has none."""
    label = MEDIUM_LABELS.get(str(reference.get("medium") or ""))
    return f'<span class="home-page-chip" data-kind="medium">{label[1]}<span>{html.escape(label[0])}</span></span>' if label else ""


def tile(reference: Mapping, *, show_medium: bool = True) -> str:
    recommended = reference.get("status") == STATUS_RECOMMENDED
    image_source = safe_href(reference.get("image"))
    image = f'<img class="home-page-image" src="{esc(image_source)}" alt="" loading="lazy">' if image_source else ""
    host = f'<p class="home-page-eyebrow">{esc(reference["host"])}</p>' if reference.get("host") else ""
    chips = [chip for chip in (medium_chip(reference) if show_medium else "",) if chip]
    if recommended:
        chips.append(f'<span class="home-page-chip" data-kind="recommended">{SPARKLES_ICON}<span>{html.escape(RECOMMENDED_LABEL)}</span></span>')
    if reference.get("section"):
        chips.append(f'<span class="home-page-chip" data-kind="section">{esc(reference["section"])}</span>')
    chip_row = f'<p class="home-page-chips">{"".join(chips)}</p>' if chips else ""
    actor = actor_text(reference)
    actor_line = f'<p class="home-page-actor">{esc(actor)}</p>' if actor else ""
    stars = star_count(reference)
    rated = f' data-stars="{stars}"' if stars is not None else ""
    return (
        f'<article class="home-page-tile" data-status="{esc(reference.get("status"))}"{rated}>{image}'
        f'<div class="home-page-body">{host}<h3 class="home-page-title">{_link(reference)}</h3>'
        f'{chip_row}{_dates(reference)}{rating_or_confidence(reference)}{actor_line}</div></article>'
    )


def row(reference: Mapping, *, show_medium: bool = True) -> str:
    host = f'<span class="home-page-eyebrow">{esc(reference["host"])}</span>' if reference.get("host") else ""
    when = time_markup(reference.get("acceptedAt") if reference.get("status") != STATUS_RECOMMENDED else None) or time_markup(reference.get("sourceDate"))
    recommended = (
        f'<span class="home-page-chip" data-kind="recommended">{SPARKLES_ICON}<span>{html.escape(RECOMMENDED_LABEL)}</span></span>'
        if reference.get("status") == STATUS_RECOMMENDED
        else ""
    )
    stars = star_count(reference)
    rated = f' data-stars="{stars}"' if stars is not None else ""
    return (
        f'<div class="home-page-row" data-status="{esc(reference.get("status"))}"{rated}>{host}'
        f'<span class="home-page-title">{_link(reference)}</span>{medium_chip(reference) if show_medium else ""}{recommended}'
        f'{stars_markup(reference, compact=True) or row_confidence_markup(reference)}{when}</div>'
    )


MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
MARKDOWN_MARKS = re.compile(r"[*_`#>~]+")


def plain_text(markdown: str) -> str:
    """A Message's Markdown as plain running text: link labels kept, marks and line breaks dropped."""
    text = MARKDOWN_LINK.sub(r"\1", markdown)
    text = MARKDOWN_MARKS.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def message_count_text(count: int) -> str:
    return f"{count} message" if count == 1 else f"{count} messages"


def author_text(author: Mapping) -> str:
    """The public author of a Message: the handle when there is one, otherwise the role label."""
    name = author.get("handle") or author.get("label") or ""
    return str(name)


def anchor_markup(anchor: Mapping) -> str:
    """The thread's anchor as an eyebrow: the kind in words and a Lucide icon (``link`` for a Reference, ``file-text`` for a Story)."""
    story = anchor.get("kind") == "story"
    icon = FILE_TEXT_ICON if story else LINK_ICON
    kind = "Story" if story else "Reference"
    href = safe_href(anchor.get("url")) if story else None
    title = esc(anchor.get("title") or kind)
    label = f'<a href="{esc(href)}">{title}</a>' if href else title
    return f'<p class="home-page-eyebrow home-page-anchor" data-kind="{kind.lower()}">{icon}<span>{kind}: {label}</span></p>'


def thread_card(thread: Mapping, excerpt: str, href: str | None = None) -> str:
    """One thread: anchor eyebrow, title, message count and last activity, the latest Message clipped, and who wrote it.

    With ``href`` (a site has ``homePage.forum``) the title links to the thread's own page."""
    latest = thread.get("latest") if isinstance(thread.get("latest"), Mapping) else {}
    count = thread.get("messages") if isinstance(thread.get("messages"), int) else 0
    when = time_markup(thread.get("lastAt"))
    author = author_text(latest.get("author") or {})
    quote = f'<p class="home-page-excerpt">{esc(excerpt)}</p>' if excerpt else ""
    by = f'<p class="home-page-author">by {esc(author)}</p>' if author else ""
    title = esc(thread.get("title") or "Conversation")
    title = f'<a href="{esc(href)}">{title}</a>' if href else title
    return (
        f'<article class="home-page-thread" data-anchor="{esc((thread.get("anchor") or {}).get("kind"))}">'
        f'<div class="home-page-body">{anchor_markup(thread.get("anchor") or {})}'
        f'<h3 class="home-page-title">{title}</h3>'
        f'<p class="home-page-thread-meta"><span class="home-page-count">{MESSAGE_SQUARE_ICON}<span>{message_count_text(count)}</span></span>{when}</p>'
        f'{quote}{by}</div></article>'
    )
