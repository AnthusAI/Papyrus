"""The ``::include{kind="references"}`` component: a grid of Reference cards drawn from the home-page snapshot.

``select`` names one of three orderings of the snapshot's References (``recent`` and ``confident`` take accepted ones, ``recommended``
takes the ones not yet accepted). ``confident`` and ``recommended`` use the shared order, an editor's rating and then the Cyclotron's confidence
(``home_page/ordering.py``); ``recent`` is newest accepted first. ``bucket="day"`` or ``bucket="week"`` puts the newest bucket first and the shared
order inside each bucket, on any selection. A bucket is a ROLLING window counted back from the UTC day of the render (``as_of``), as for Stories. Several includes on one page share a :class:`~.page_ledger.PageLedger`: the first component to
place a Reference keeps it, and a later one refills up to its ``count`` from its own ordering. ``count`` defaults to
``homePage.references.defaultCount``. A missing or empty snapshot draws the ``empty`` text, or nothing when there is none.

``medium="video"`` keeps only the References whose medium is video (a videos block or page): accepted ones with ``select="recent"``. The cards
show the video's own thumbnail (a copy in the site's storage, published as ``image``; never an address on the platform) and link out to the source (no per-card "Video" label: every card is one); nothing is embedded and no third-party
script is loaded.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from ...home_page.export import clip_summary
from ...home_page.ordering import BUCKETS, order_in_buckets, order_public_records
from ...home_page.settings import HomePageSettings
from ...reference_medium import MEDIUMS
from . import home_page_components as parts
from . import home_page_lists as lists
from .knowledge_components import esc, safe_href
from .page_ledger import PageLedger

KIND = "references"
LEAD_CLASS = "papyrus-has-lead"   # a counted list whose first card is the best, so the largest
REFERENCES_LEAD_CLASS = "home-page-has-lead"
IMAGES = ("none", "any")
THREADS_KIND = "threads"
THREADS_ATTRIBUTES = {"select", "count", "layout", "heading", "empty"}
THREAD_SELECTIONS = ("recent",)
THREAD_LAYOUTS = ("list", "grid")
THREAD_LEDGER_PREFIX = "thread:"
ATTRIBUTES = {"select", "count", "section", "card", "heading", "more", "empty", "bucket", "medium", "paged", "id", "image", "counts", "explainer", "explainerKicker", "explainerBody"}
LIST_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
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
    if attributes.get("image", "any") not in IMAGES:
        raise ValueError(f"{source}: ::include references image must be one of {', '.join(IMAGES)}, got {attributes['image']!r}")
    if attributes.get("counts", "false") not in ("true", "false"):
        raise ValueError(f"{source}: ::include references counts must be \"true\" or \"false\", got {attributes['counts']!r}")
    if ("explainerKicker" in attributes or "explainerBody" in attributes) and not attributes.get("explainer"):
        raise ValueError(f"{source}: ::include references explainerKicker and explainerBody go with explainer (the card's heading)")
    if is_paged(attributes) and ("explainer" in attributes or "counts" in attributes):
        raise ValueError(f"{source}: ::include references cannot be paged and have an explainer or counts: a paged list is the whole selection")
    if attributes.get("paged", "false") not in ("true", "false"):
        raise ValueError(f"{source}: ::include references paged must be \"true\" or \"false\", got {attributes['paged']!r}")
    if "id" in attributes and (attributes.get("paged") != "true" or not LIST_ID.match(attributes["id"])):
        raise ValueError(f"{source}: ::include references id names a paged list (paged=\"true\") and is lowercase words joined by hyphens, got {attributes['id']!r}")
    if is_paged(attributes) and "more" in attributes:
        raise ValueError(f"{source}: ::include references cannot be paged and have a more link: the list is complete")


def is_paged(attributes: Mapping) -> bool:
    """True for an include that opted in to loading more as the reader scrolls (``paged="true"``; the site must also set ``homePage.references.paging``)."""
    return attributes.get("paged") == "true"


def count_of(attributes: Mapping, settings: HomePageSettings | None) -> int:
    if "count" in attributes:
        return int(attributes["count"])
    return settings.references.default_count if settings is not None else DEFAULT_COUNT


def _text(record: Mapping, name: str) -> str:
    value = record.get(name)
    return value if isinstance(value, str) else ""


def ordered(records: list[Mapping], selection: str, bucket: str | None = None, as_of: date | None = None) -> list[Mapping]:
    """The records of one selection in its order. ``recent`` is newest accepted first (then newest arrival, then key); ``confident`` and ``recommended``
    are the shared order of ``home_page/ordering.py``. With a ``bucket`` the newest bucket comes first and the shared order applies inside each."""
    wanted = "recommended" if selection == "recommended" else "accepted"
    chosen = [record for record in records if isinstance(record, Mapping) and record.get("status") == wanted and record.get("key")]
    if bucket:
        return order_in_buckets(chosen, bucket, as_of)
    if selection == "recent":
        chosen.sort(key=lambda record: _text(record, "key"))
        chosen.sort(key=lambda record: _text(record, "arrivedAt"), reverse=True)
        chosen.sort(key=lambda record: _text(record, "acceptedAt"), reverse=True)
        return chosen
    return order_public_records(chosen)


def _in_section(record: Mapping, section: str, labels: Mapping[str, str]) -> bool:
    wanted = {section.casefold(), labels.get(section, "").casefold()} - {""}
    return _text(record, "section").casefold() in wanted


def candidates_of(document: Mapping | None, attributes: Mapping, section_labels: Mapping[str, str] | None = None, as_of: date | None = None) -> list[Mapping[str, Any]]:
    """Every Reference an include's selection could place, in the order it places them: no ledger, no count."""
    records = (document or {}).get("references") or []
    candidates = ordered(records, attributes["select"], attributes.get("bucket"), as_of)
    if attributes.get("medium"):   # only the References whose address certainly says this medium; a record with no `medium` field never matches
        candidates = [record for record in candidates if record.get("medium") == attributes["medium"]]
    if attributes.get("image") == "none":   # only the References with no picture: text-only cards
        candidates = [record for record in candidates if not _text(record, "image")]
    elif attributes.get("image") == "any":   # only the References with a picture
        candidates = [record for record in candidates if _text(record, "image")]
    if attributes.get("section"):
        candidates = [record for record in candidates if _in_section(record, attributes["section"], section_labels or {})]
    return candidates


def select_references(
    document: Mapping | None,
    attributes: Mapping,
    ledger: PageLedger,
    default_count: int = DEFAULT_COUNT,
    section_labels: Mapping[str, str] | None = None,
    as_of: date | None = None,
) -> list[Mapping[str, Any]]:
    """The References one include places: its ordering, minus what the page already shows, up to ``count``; each one is claimed in the ledger."""
    candidates = candidates_of(document, attributes, section_labels, as_of)
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
    paged_list: lists.PagedList | None = None,
    as_of: date | None = None,
) -> str:
    ledger.home_page_used = True
    if paged_list is not None:
        return render_paged(attributes, ledger, paged_list, asset_href)
    chosen = select_references(source_doc, attributes, ledger, count_of({}, settings), section_labels, as_of)
    if asset_href is not None:   # an image of ours is a site path ("/assets/..."); under urls.basePath it lives below the base path
        chosen = [{**record, "image": asset_href(record["image"])} if _text(record, "image").startswith("/") else record for record in chosen]
    empty = attributes.get("empty", "")
    if not chosen:
        return f'<p class="home-page-empty">{esc(empty)}</p>' if empty else ""
    card = attributes.get("card", "tile")
    heading = f'<h2 class="home-page-heading">{esc(attributes["heading"])}</h2>' if attributes.get("heading") else ""
    draw = parts.tile if card == "tile" else parts.row
    show_medium = not attributes.get("medium")   # a block of one medium needs no label on every card; a block that mixes media keeps it
    cards = explainer_item(attributes) + "".join(f"<li>{draw(reference, show_medium=show_medium)}</li>" for reference in chosen)
    counted = attributes.get("counts") == "true"
    more = f'<p class="home-page-more"><a href="{esc(safe_href(attributes["more"]))}">More</a></p>' if attributes.get("more") else ""
    medium_attribute = f' data-medium="{esc(attributes["medium"])}"' if attributes.get("medium") else ""
    data = f' data-count="{len(chosen)}"' if counted else ""
    lead = f" {REFERENCES_LEAD_CLASS}" if counted else ""
    return (
        f'<section class="home-page-references" data-select="{esc(attributes["select"])}" data-card="{esc(card)}"{medium_attribute}{data}>{heading}'
        f'<ul class="home-page-grid{lead}" data-card="{esc(card)}"{data}>{cards}</ul>{more}</section>'
    )


def explainer_item(attributes: Mapping) -> str:
    """The explainer card, first in the grid: a heading, an optional kicker and body, all from the include (plain text). It is not a Reference and is never counted."""
    if not attributes.get("explainer"):
        return ""
    kicker = f'<p class="home-page-eyebrow">{esc(attributes["explainerKicker"])}</p>' if attributes.get("explainerKicker") else ""
    body = f'<p class="home-page-explainer-body">{esc(attributes["explainerBody"])}</p>' if attributes.get("explainerBody") else ""
    return f'<li class="home-page-explainer"><div class="home-page-explainer-card">{kicker}<h3 class="home-page-title">{esc(attributes["explainer"])}</h3>{body}</div></li>'



def render_paged(attributes: Mapping, ledger: PageLedger, found: lists.PagedList, asset_href: Callable[[str], str] | None = None) -> str:
    """A paged list: its first page as ordinary cards (so the page reads without a script), then the link to the next page and the live region the script uses.

    The list is the whole selection: it does not skip what an earlier component on the page placed (the data files are the same on every page that has the
    list), and the first page claims what it shows so a later component does not repeat it."""
    ledger.paged_lists_used = True
    for record in found.first:
        ledger.claim(LEDGER_PREFIX + record["key"])
    empty = attributes.get("empty", "")
    if not found.first:
        return f'<p class="home-page-empty">{esc(empty)}</p>' if empty else ""
    card = found.card
    heading = f'<h2 class="home-page-heading">{esc(attributes["heading"])}</h2>' if attributes.get("heading") else ""
    medium_attribute = f' data-medium="{esc(attributes["medium"])}"' if attributes.get("medium") else ""
    return (
        f'<section class="home-page-references" data-select="{esc(attributes["select"])}" data-card="{esc(card)}"{medium_attribute} data-paged="true">{heading}'
        f'<ul class="home-page-grid" data-card="{esc(card)}" data-reference-grid>{lists.first_page_items(found, asset_href)}</ul>{lists.more_control(found)}</section>'
    )


def _link_text(value: Any, fallback: str) -> str:
    return " ".join(str(value or fallback).replace("[", "(").replace("]", ")").split())


def markdown_lines(references: list[Mapping[str, Any]]) -> list[str]:
    """One list item per Reference: its title linked to its source, and for a Reference no editor has accepted yet, the words that say so."""
    lines = []
    for reference in references:
        title = _link_text(reference.get("title"), reference.get("url") or "Untitled")
        href = safe_href(reference.get("url"))
        line = f"- [{title}]({href})" if href else f"- {title}"
        if reference.get("status") == parts.STATUS_RECOMMENDED:
            line += f" ({parts.RECOMMENDED_LABEL})"
        lines.append(line)
    return lines


def render_chunk_markdown(found: lists.PagedList, index: int, absolute: Callable[[str], str]) -> str:
    """The Markdown twin of one chunk's page: its Reference list, then the links back and on (the twins chain, so an agent can read the whole list a page at a time)."""
    chunk = found.chunks[index]
    previous = found.previous_of(index)
    lines = markdown_lines([found.records[key] for key in chunk.keys])
    back = lists.markdown_href(found, previous) if previous else absolute(found.address.path(found.page_path))
    lines += ["", f"[{'Previous' if previous else 'Back to ' + found.page_title}]({absolute(back) if back.startswith('/') else back})"]
    if chunk.next:
        lines.append(f"[Next]({absolute(lists.markdown_href(found, chunk.next))})")
    return "\n".join(lines)


def render_markdown(
    attributes: Mapping,
    source_doc: Mapping | None,
    ledger: PageLedger,
    settings: HomePageSettings,
    section_labels: Mapping[str, str] | None = None,
    absolute: Callable[[str], str] = lambda path: path,
    paged_list: lists.PagedList | None = None,
    as_of: date | None = None,
) -> str:
    """What :func:`render` places, for the Markdown twin: an optional heading and one list item per Reference, a title linked to its source.

    The References are the ones :func:`select_references` chooses (same ordering, same ledger rules), so the twin lists what the page shows.
    Only the title, the address and, for a Reference no editor has accepted yet, the words that say so are written."""
    if paged_list is not None:   # the first page, then a link to the next page of cards: a twin that listed the whole corpus would grow with it
        chosen = list(paged_list.first)
        for reference in chosen:
            ledger.claim(LEDGER_PREFIX + reference["key"])
    else:
        chosen = select_references(source_doc, attributes, ledger, count_of({}, settings), section_labels, as_of)
    if not chosen:
        return attributes.get("empty", "")
    lines = [f"## {attributes['heading']}", ""] if attributes.get("heading") else []
    lines += markdown_lines(chosen)
    more = safe_href(attributes.get("more"))
    if more:
        lines += ["", f"[More]({absolute(more) if more.startswith('/') else more})"]
    if paged_list is not None and lists.markdown_more(paged_list, absolute):
        lines += ["", lists.markdown_more(paged_list, absolute)]
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
