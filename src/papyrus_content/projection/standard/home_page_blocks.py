"""The ``::include{kind="references"}`` component: a grid of Reference cards drawn from the home-page snapshot.

``select`` names one of three orderings of the snapshot's References (``recent`` and ``confident`` take accepted ones, ``recommended``
takes the ones not yet accepted). Several includes on one page share a :class:`~.page_ledger.PageLedger`: the first component to
place a Reference keeps it, and a later one refills up to its ``count`` from its own ordering. ``count`` defaults to
``homePage.references.defaultCount``. A missing or empty snapshot draws the ``empty`` text, or nothing when there is none.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...home_page.export import clip_summary
from ...home_page.settings import HomePageSettings
from . import home_page_components as parts
from .knowledge_components import esc, safe_href
from .page_ledger import PageLedger

KIND = "references"
THREADS_KIND = "threads"
THREADS_ATTRIBUTES = {"select", "count", "layout", "heading", "empty"}
THREAD_SELECTIONS = ("recent",)
THREAD_LAYOUTS = ("list", "grid")
THREAD_LEDGER_PREFIX = "thread:"
ATTRIBUTES = {"select", "count", "section", "card", "heading", "more", "empty"}
SELECTIONS = ("recent", "confident", "recommended")
CARDS = ("tile", "row")
DEFAULT_COUNT = 6
MISSING_CONFIDENCE = 0.5
LEDGER_PREFIX = "reference:"
NOT_CONFIGURED = "homePage is not configured in projection.json"


def is_home_page_include(attributes: Mapping) -> bool:
    return attributes.get("kind") == KIND


def is_threads_include(attributes: Mapping) -> bool:
    return attributes.get("kind") == THREADS_KIND


def check(attributes: Mapping, source: str) -> None:
    """Validate a references include's attributes; ``source`` names the file for the error."""
    unknown = set(attributes) - ATTRIBUTES - {"kind"}
    if unknown:
        raise ValueError(f"{source}: ::include references has unknown attributes: {', '.join(sorted(unknown))}")
    if attributes.get("select") not in SELECTIONS:
        raise ValueError(f"{source}: ::include references needs select to be one of {', '.join(SELECTIONS)}, got {attributes.get('select')!r}")
    if "count" in attributes and not str(attributes["count"]).isdigit():
        raise ValueError(f"{source}: ::include references count must be a whole number, got {attributes['count']!r}")
    if attributes.get("card", "tile") not in CARDS:
        raise ValueError(f"{source}: ::include references card must be one of {', '.join(CARDS)}, got {attributes['card']!r}")
    if "more" in attributes and not safe_href(attributes["more"]):
        raise ValueError(f"{source}: ::include references more must be a site path or an http(s) address, got {attributes['more']!r}")


def count_of(attributes: Mapping, settings: HomePageSettings | None) -> int:
    if "count" in attributes:
        return int(attributes["count"])
    return settings.references.default_count if settings is not None else DEFAULT_COUNT


def _text(record: Mapping, name: str) -> str:
    value = record.get(name)
    return value if isinstance(value, str) else ""


def _confidence(record: Mapping) -> float:
    value = record.get("confidence")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else MISSING_CONFIDENCE


def ordered(records: list[Mapping], selection: str) -> list[Mapping]:
    """The records of one selection in its order; ties fall to the newest arrival, then to the key."""
    wanted = "recommended" if selection == "recommended" else "accepted"
    chosen = [record for record in records if isinstance(record, Mapping) and record.get("status") == wanted and record.get("key")]
    chosen.sort(key=lambda record: _text(record, "key"))
    chosen.sort(key=lambda record: _text(record, "arrivedAt"), reverse=True)
    if selection == "recent":
        chosen.sort(key=lambda record: _text(record, "acceptedAt"), reverse=True)
    else:
        chosen.sort(key=_confidence, reverse=True)
    return chosen


def _in_section(record: Mapping, section: str, labels: Mapping[str, str]) -> bool:
    wanted = {section.casefold(), labels.get(section, "").casefold()} - {""}
    return _text(record, "section").casefold() in wanted


def select_references(
    document: Mapping | None,
    attributes: Mapping,
    ledger: PageLedger,
    default_count: int = DEFAULT_COUNT,
    section_labels: Mapping[str, str] | None = None,
) -> list[Mapping[str, Any]]:
    """The References one include places: its ordering, minus what the page already shows, up to ``count``; each one is claimed in the ledger."""
    records = (document or {}).get("references") or []
    candidates = ordered(records, attributes["select"])
    if attributes.get("section"):
        candidates = [record for record in candidates if _in_section(record, attributes["section"], section_labels or {})]
    count = int(attributes["count"]) if "count" in attributes else default_count
    chosen: list[Mapping[str, Any]] = []
    for record in candidates:
        if len(chosen) >= count:
            break
        if ledger.claim(LEDGER_PREFIX + record["key"]):
            chosen.append(record)
    return chosen


def render(
    attributes: Mapping,
    source_doc: Mapping | None,
    ledger: PageLedger,
    settings: HomePageSettings,
    section_labels: Mapping[str, str] | None = None,
) -> str:
    chosen = select_references(source_doc, attributes, ledger, count_of({}, settings), section_labels)
    empty = attributes.get("empty", "")
    if not chosen:
        return f'<p class="home-page-empty">{esc(empty)}</p>' if empty else ""
    card = attributes.get("card", "tile")
    heading = f'<h2 class="home-page-heading">{esc(attributes["heading"])}</h2>' if attributes.get("heading") else ""
    draw = parts.tile if card == "tile" else parts.row
    cards = "".join(f"<li>{draw(reference)}</li>" for reference in chosen)
    more = f'<p class="home-page-more"><a href="{esc(safe_href(attributes["more"]))}">More</a></p>' if attributes.get("more") else ""
    return (
        f'<section class="home-page-references" data-select="{esc(attributes["select"])}" data-card="{esc(card)}">{heading}'
        f'<ul class="home-page-grid" data-card="{esc(card)}">{cards}</ul>{more}</section>'
    )


def check_threads(attributes: Mapping, source: str) -> None:
    """Validate a threads include's attributes; ``source`` names the file for the error."""
    unknown = set(attributes) - THREADS_ATTRIBUTES - {"kind"}
    if unknown:
        raise ValueError(f"{source}: ::include threads has unknown attributes: {', '.join(sorted(unknown))}")
    if attributes.get("select") not in THREAD_SELECTIONS:
        raise ValueError(f"{source}: ::include threads needs select to be one of {', '.join(THREAD_SELECTIONS)}, got {attributes.get('select')!r}")
    if "count" in attributes and not str(attributes["count"]).isdigit():
        raise ValueError(f"{source}: ::include threads count must be a whole number, got {attributes['count']!r}")
    if attributes.get("layout", "list") not in THREAD_LAYOUTS:
        raise ValueError(f"{source}: ::include threads layout must be one of {', '.join(THREAD_LAYOUTS)}, got {attributes['layout']!r}")


def select_threads(document: Mapping | None, attributes: Mapping, ledger: PageLedger, default_count: int = DEFAULT_COUNT) -> list[Mapping[str, Any]]:
    """The threads one include places: most recently active first, minus what the page already shows, up to ``count``; each one is claimed in the ledger."""
    candidates = [thread for thread in (document or {}).get("threads") or [] if isinstance(thread, Mapping) and thread.get("key")]
    candidates.sort(key=lambda thread: _text(thread, "key"))
    candidates.sort(key=lambda thread: _text(thread, "lastAt"), reverse=True)
    count = int(attributes["count"]) if "count" in attributes else default_count
    chosen: list[Mapping[str, Any]] = []
    for thread in candidates:
        if len(chosen) >= count:
            break
        if ledger.claim(THREAD_LEDGER_PREFIX + thread["key"]):
            chosen.append(thread)
    return chosen


def render_threads(attributes: Mapping, source_doc: Mapping | None, ledger: PageLedger, settings: HomePageSettings) -> str:
    chosen = select_threads(source_doc, attributes, ledger, count_of({}, settings))
    empty = attributes.get("empty", "")
    if not chosen:
        return f'<p class="home-page-empty">{esc(empty)}</p>' if empty else ""
    layout = attributes.get("layout", "list")
    heading = f'<h2 class="home-page-heading">{esc(attributes["heading"])}</h2>' if attributes.get("heading") else ""
    characters = settings.references.summary_characters
    cards = ""
    for thread in chosen:
        latest = thread.get("latest") if isinstance(thread.get("latest"), Mapping) else {}
        excerpt = clip_summary(parts.plain_text(_text(latest, "text")), characters) or ""
        cards += f"<li>{parts.thread_card(thread, excerpt)}</li>"
    return f'<section class="home-page-threads" data-layout="{esc(layout)}">{heading}<ul class="home-page-grid" data-layout="{esc(layout)}">{cards}</ul></section>'
