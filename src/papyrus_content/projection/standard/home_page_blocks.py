"""The ``::include{kind="references"}`` component: a grid of Reference cards drawn from the home-page snapshot.

``select`` names one of three orderings of the snapshot's References (``recent`` and ``confident`` take accepted ones, ``recommended``
takes the ones not yet accepted). ``confident`` and ``recommended`` use the shared order, an editor's rating and then the Cyclotron's confidence
(``home_page/ordering.py``); ``recent`` is newest accepted first. ``bucket="day"`` or ``bucket="week"`` puts the newest bucket first and the shared
order inside each bucket, on any selection. Several includes on one page share a :class:`~.page_ledger.PageLedger`: the first component to
place a Reference keeps it, and a later one refills up to its ``count`` from its own ordering. ``count`` defaults to
``homePage.references.defaultCount``. A missing or empty snapshot draws the ``empty`` text, or nothing when there is none.

``medium="video"`` keeps only the References whose medium is video (a videos block or page): accepted ones with ``select="recent"``. The cards
show the video's own thumbnail (a copy in the site's storage, published as ``image``; never an address on the platform) and link out to the source (no per-card "Video" label: every card is one); nothing is embedded and no third-party
script is loaded.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ...home_page.export import clip_summary
from ...home_page.ordering import BUCKETS, order_in_buckets, order_public_records
from ...home_page.settings import HomePageSettings
from ...reference_medium import MEDIUMS
from . import home_page_components as parts
from .knowledge_components import esc, safe_href
from .page_ledger import PageLedger

KIND = "references"
THREADS_KIND = "threads"
THREADS_ATTRIBUTES = {"select", "count", "layout", "heading", "empty"}
THREAD_SELECTIONS = ("recent",)
THREAD_LAYOUTS = ("list", "grid")
THREAD_LEDGER_PREFIX = "thread:"
ATTRIBUTES = {"select", "count", "section", "card", "heading", "more", "empty", "bucket", "medium"}
SELECTIONS = ("recent", "confident", "recommended")
CARDS = ("tile", "row")
DEFAULT_COUNT = 6
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
    if "bucket" in attributes and attributes["bucket"] not in BUCKETS:
        raise ValueError(f"{source}: ::include references bucket must be one of {', '.join(BUCKETS)}, got {attributes['bucket']!r}")
    if "medium" in attributes and attributes["medium"] not in MEDIUMS:
        raise ValueError(f"{source}: ::include references medium must be one of {', '.join(MEDIUMS)}, got {attributes['medium']!r}")
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


def ordered(records: list[Mapping], selection: str, bucket: str | None = None) -> list[Mapping]:
    """The records of one selection in its order. ``recent`` is newest accepted first (then newest arrival, then key); ``confident`` and ``recommended``
    are the shared order of ``home_page/ordering.py``. With a ``bucket`` the newest bucket comes first and the shared order applies inside each."""
    wanted = "recommended" if selection == "recommended" else "accepted"
    chosen = [record for record in records if isinstance(record, Mapping) and record.get("status") == wanted and record.get("key")]
    if bucket:
        return order_in_buckets(chosen, bucket)
    if selection == "recent":
        chosen.sort(key=lambda record: _text(record, "key"))
        chosen.sort(key=lambda record: _text(record, "arrivedAt"), reverse=True)
        chosen.sort(key=lambda record: _text(record, "acceptedAt"), reverse=True)
        return chosen
    return order_public_records(chosen)


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
    candidates = ordered(records, attributes["select"], attributes.get("bucket"))
    if attributes.get("medium"):   # only the References whose address certainly says this medium; a record with no `medium` field never matches
        candidates = [record for record in candidates if record.get("medium") == attributes["medium"]]
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
    asset_href: Callable[[str], str] | None = None,
) -> str:
    ledger.home_page_used = True
    chosen = select_references(source_doc, attributes, ledger, count_of({}, settings), section_labels)
    if asset_href is not None:   # an image of ours is a site path ("/assets/..."); under urls.basePath it lives below the base path
        chosen = [{**record, "image": asset_href(record["image"])} if _text(record, "image").startswith("/") else record for record in chosen]
    empty = attributes.get("empty", "")
    if not chosen:
        return f'<p class="home-page-empty">{esc(empty)}</p>' if empty else ""
    card = attributes.get("card", "tile")
    heading = f'<h2 class="home-page-heading">{esc(attributes["heading"])}</h2>' if attributes.get("heading") else ""
    draw = parts.tile if card == "tile" else parts.row
    show_medium = not attributes.get("medium")   # a block of one medium needs no label on every card; a block that mixes media keeps it
    cards = "".join(f"<li>{draw(reference, show_medium=show_medium)}</li>" for reference in chosen)
    more = f'<p class="home-page-more"><a href="{esc(safe_href(attributes["more"]))}">More</a></p>' if attributes.get("more") else ""
    medium_attribute = f' data-medium="{esc(attributes["medium"])}"' if attributes.get("medium") else ""
    return (
        f'<section class="home-page-references" data-select="{esc(attributes["select"])}" data-card="{esc(card)}"{medium_attribute}>{heading}'
        f'<ul class="home-page-grid" data-card="{esc(card)}">{cards}</ul>{more}</section>'
    )


def _link_text(value: Any, fallback: str) -> str:
    return " ".join(str(value or fallback).replace("[", "(").replace("]", ")").split())


def render_markdown(
    attributes: Mapping,
    source_doc: Mapping | None,
    ledger: PageLedger,
    settings: HomePageSettings,
    section_labels: Mapping[str, str] | None = None,
    absolute: Callable[[str], str] = lambda path: path,
) -> str:
    """What :func:`render` places, for the Markdown twin: an optional heading and one list item per Reference, a title linked to its source.

    The References are the ones :func:`select_references` chooses (same ordering, same ledger rules), so the twin lists what the page shows.
    Only the title, the address and, for a Reference no editor has accepted yet, the words that say so are written."""
    chosen = select_references(source_doc, attributes, ledger, count_of({}, settings), section_labels)
    if not chosen:
        return attributes.get("empty", "")
    lines = [f"## {attributes['heading']}", ""] if attributes.get("heading") else []
    for reference in chosen:
        title = _link_text(reference.get("title"), reference.get("url") or "Untitled")
        href = safe_href(reference.get("url"))
        line = f"- [{title}]({href})" if href else f"- {title}"
        if reference.get("status") == parts.STATUS_RECOMMENDED:
            line += f" ({parts.RECOMMENDED_LABEL})"
        lines.append(line)
    more = safe_href(attributes.get("more"))
    if more:
        lines += ["", f"[More]({absolute(more) if more.startswith('/') else more})"]
    return "\n".join(lines)


def render_threads_markdown(
    attributes: Mapping,
    source_doc: Mapping | None,
    ledger: PageLedger,
    settings: HomePageSettings,
    thread_href: Callable[[str], str] | None = None,
) -> str:
    """What :func:`render_threads` places, for the Markdown twin: one list item per conversation, its title linked to its page when the site has one."""
    chosen = select_threads(source_doc, attributes, ledger, count_of({}, settings))
    if not chosen:
        return attributes.get("empty", "")
    lines = [f"## {attributes['heading']}", ""] if attributes.get("heading") else []
    for thread in chosen:
        title = _link_text(thread.get("title"), "Conversation")
        count = thread.get("messages") if isinstance(thread.get("messages"), int) else 0
        link = f"[{title}]({thread_href(thread['key'])})" if thread_href else title
        lines.append(f"- {link} ({parts.message_count_text(count)})")
    return "\n".join(lines)


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


def render_threads(attributes: Mapping, source_doc: Mapping | None, ledger: PageLedger, settings: HomePageSettings, thread_href: Callable[[str], str] | None = None) -> str:
    ledger.home_page_used = True
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
        cards += f"<li>{parts.thread_card(thread, excerpt, thread_href(thread['key']) if thread_href else None)}</li>"
    return f'<section class="home-page-threads" data-layout="{esc(layout)}">{heading}<ul class="home-page-grid" data-layout="{esc(layout)}">{cards}</ul></section>'
