"""Reference cards for the home page: a tile (the grid card) and a row (one line), as server-rendered markup that needs no script.

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


def confidence_markup(reference: Mapping) -> str:
    percent = confidence_percent(reference.get("confidence"))
    if percent is None:
        return ""
    return f'<p class="home-page-confidence">{GAUGE_ICON}<span class="home-page-confidence-value">{percent}% confidence</span>{meter(percent)}</p>'


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


def tile(reference: Mapping) -> str:
    recommended = reference.get("status") == STATUS_RECOMMENDED
    image_source = safe_href(reference.get("image"))
    image = f'<img class="home-page-image" src="{esc(image_source)}" alt="" loading="lazy">' if image_source else ""
    host = f'<p class="home-page-eyebrow">{esc(reference["host"])}</p>' if reference.get("host") else ""
    chips = []
    if recommended:
        chips.append(f'<span class="home-page-chip" data-kind="recommended">{SPARKLES_ICON}<span>{html.escape(RECOMMENDED_LABEL)}</span></span>')
    if reference.get("section"):
        chips.append(f'<span class="home-page-chip" data-kind="section">{esc(reference["section"])}</span>')
    chip_row = f'<p class="home-page-chips">{"".join(chips)}</p>' if chips else ""
    actor = actor_text(reference)
    actor_line = f'<p class="home-page-actor">{esc(actor)}</p>' if actor else ""
    return (
        f'<article class="home-page-tile" data-status="{esc(reference.get("status"))}">{image}'
        f'<div class="home-page-body">{host}<h3 class="home-page-title">{_link(reference)}</h3>'
        f'{chip_row}{_dates(reference)}{confidence_markup(reference)}{actor_line}</div></article>'
    )


def row(reference: Mapping) -> str:
    host = f'<span class="home-page-eyebrow">{esc(reference["host"])}</span>' if reference.get("host") else ""
    when = time_markup(reference.get("acceptedAt") if reference.get("status") != STATUS_RECOMMENDED else None) or time_markup(reference.get("sourceDate"))
    recommended = (
        f'<span class="home-page-chip" data-kind="recommended">{SPARKLES_ICON}<span>{html.escape(RECOMMENDED_LABEL)}</span></span>'
        if reference.get("status") == STATUS_RECOMMENDED
        else ""
    )
    return (
        f'<div class="home-page-row" data-status="{esc(reference.get("status"))}">{host}'
        f'<span class="home-page-title">{_link(reference)}</span>{recommended}{when}</div>'
    )
