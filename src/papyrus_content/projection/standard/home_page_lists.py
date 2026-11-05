"""Reference lists that load more as the reader scrolls: the files behind ``::include{kind="references" paged="true"}``.

A site opts in with ``homePage.references.paging`` in ``projection.json`` and, on each list, ``paged="true"``. The include's ``count`` is then the size of
the first page, which is in the page itself and so works without a script and for crawlers; there is no other limit. The rest of the list, in the same
order, is cut into chunks (``home_page/chunks.py``) and each chunk is written twice, from one render:

``reference-lists/<page>/<list>/<chunk>/index.html``   a real page with the site's chrome: the cards, "Previous" and "Next" links. This is how a reader
                                                      without a script reaches the rest, and how a crawler does.
``reference-lists/<page>/<list>/<chunk>.json``         the data file the script fetches: the same cards as an HTML string, and the address of the next chunk.

The cards of a chunk are drawn once, by the page render, so the site's own hooks (``page_finish`` redraws stock tiles in Machines on Machines) apply to
a page of cards and to a data file alike: the data file is the part of the rendered page between two markers, and there is no second renderer to keep in step.
Nothing private is in either file: the cards are drawn from the public snapshot record, and a card never carries a position, a total or a time of reading.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ...home_page.chunks import Chunk, split
from ...home_page.ordering import RANK_FIELD
from . import home_page_components as parts
from .knowledge_components import esc

LIST_DIRECTORY = "reference-lists"
CARDS_OPEN = "<!--papyrus:cards-->"
CARDS_CLOSE = "<!--/papyrus:cards-->"
DATA_FORMAT = 1
HOME_SLUG = "_home"
SCRIPT_PATH = "js/papyrus-reference-list.js"
CHEVRONS_DOWN_ICON = (
    '<svg class="home-page-icon" data-icon="chevrons-down" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="m7 6 5 5 5-5"/><path d="m7 13 5 5 5-5"/></svg>'
)


def page_slug(path: str) -> str:
    """The directory name of the page a list is on: its path with the slashes joined by ``--``; ``_home`` for the home page."""
    return "--".join(part for part in path.strip("/").split("/") if part) or HOME_SLUG


def _word(text: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in text.casefold()).strip("-")


def list_id(attributes: Mapping) -> str:
    """The name of a list on its page: ``id`` when the include gives one, else what its selection says (``recent``, ``recommended-tools``)."""
    if attributes.get("id"):
        return attributes["id"]
    words = [_word(attributes[name]) for name in ("select", "section", "medium", "bucket") if attributes.get(name)]
    return "-".join(word for word in words if word) or "list"


@dataclass(frozen=True)
class ListAddress:
    """Where a list's files are: ``directory`` is site-relative (``reference-lists/wire/recent``); ``path`` adds ``urls.basePath`` to a site path."""

    directory: str
    path: Callable[[str], str]

    def data_key(self, name: str) -> str:
        return f"{self.directory}/{name}.json"

    def page_base(self, name: str) -> str:
        return f"{self.directory}/{name}"

    def data_href(self, name: str) -> str:
        return self.path("/" + self.data_key(name))

    def page_href(self, name: str) -> str:
        return self.path("/" + self.page_base(name) + "/")


@dataclass(frozen=True)
class PagedList:
    """One paged list as the snapshot lays it out now: the first page, and the chunks after it."""

    attributes: Mapping[str, str]
    page_path: str
    page_title: str
    address: ListAddress
    first: tuple[Mapping[str, Any], ...]
    chunks: tuple[Chunk, ...]
    records: Mapping[str, Mapping[str, Any]]

    @property
    def id(self) -> str:
        return list_id(self.attributes)

    @property
    def card(self) -> str:
        return self.attributes.get("card", "tile")

    @property
    def show_medium(self) -> bool:
        return not self.attributes.get("medium")

    @property
    def first_chunk(self) -> Chunk | None:
        return self.chunks[0] if self.chunks else None

    def previous_of(self, index: int) -> str | None:
        return self.chunks[index - 1].name if index > 0 else None


def build(
    candidates: Sequence[Mapping[str, Any]], attributes: Mapping[str, str], *, page_path: str, page_title: str, count: int, page_size: int,
    path: Callable[[str], str],
) -> PagedList:
    """The layout of a list: ``candidates`` (the include's whole selection in its order) cut into the first ``count`` and the chunks after them."""
    first, rest = tuple(candidates[:count]), candidates[count:]
    directory = f"{LIST_DIRECTORY}/{page_slug(page_path)}/{list_id(attributes)}"
    return PagedList(
        attributes=dict(attributes), page_path=page_path, page_title=page_title, address=ListAddress(directory, path), first=first,
        chunks=tuple(split([record["key"] for record in rest], page_size)), records={record["key"]: record for record in rest},
    )


def check_unique(lists: Sequence[PagedList], source: str) -> None:
    seen: set[str] = set()
    for found in lists:
        if found.address.directory in seen:
            raise ValueError(f"{source}: two paged references lists on one page are both named {found.id!r}; give each its own id=\"...\"")
        seen.add(found.address.directory)


def asset_records(records: Sequence[Mapping[str, Any]], asset_href: Callable[[str], str] | None) -> list[Mapping[str, Any]]:
    if asset_href is None:   # an image of ours is a site path ("/assets/..."); under urls.basePath it lives below the base path
        return list(records)
    return [{**record, "image": asset_href(record["image"])} if isinstance(record.get("image"), str) and record["image"].startswith("/") else record for record in records]


def list_item(record: Mapping[str, Any], card: str, show_medium: bool) -> str:
    """One card of a paged list. The key is on the item so a script can skip a Reference it already shows."""
    draw = parts.tile if card == "tile" else parts.row
    return f'<li data-key="{esc(record["key"])}">{draw(record, show_medium=show_medium)}</li>'


def first_page_items(found: PagedList, asset_href: Callable[[str], str] | None) -> str:
    return "".join(list_item(record, found.card, found.show_medium) for record in asset_records(found.first, asset_href))


def chunk_items(found: PagedList, chunk: Chunk, asset_href: Callable[[str], str] | None) -> str:
    return "".join(list_item(record, found.card, found.show_medium) for record in asset_records([found.records[key] for key in chunk.keys], asset_href))


def more_control(found: PagedList) -> str:
    """Under the first page: the link to the next page of cards, which a script upgrades to a button that loads them in place, and the live region it announces in."""
    chunk = found.first_chunk
    if chunk is None:
        return ""
    return (
        f'<div class="home-page-more-links" data-reference-more data-src="{esc(found.address.data_href(chunk.name))}">'
        f'<a class="home-page-load-more" rel="next" href="{esc(found.address.page_href(chunk.name))}">{CHEVRONS_DOWN_ICON}<span>Load more</span></a></div>'
        '<p class="home-page-status" role="status" aria-live="polite" data-reference-status></p>'
    )


def chunk_signature(found: PagedList, index: int) -> list:
    """What one chunk's files are drawn from, as JSON-able data: the public record of each Reference in it (without its position, which every insertion
    shifts) and the names of its neighbours. A change elsewhere in the list leaves it as it was, so the files are not written again."""
    chunk = found.chunks[index]
    records = [{name: value for name, value in found.records[key].items() if name != RANK_FIELD} for key in chunk.keys]
    return [dict(found.attributes), found.page_path, found.page_title, records, found.previous_of(index), chunk.next]


def chunk_page_fragment(found: PagedList, index: int, items: str) -> str:
    """The body of a chunk's page: the cards between two markers (the data file is cut from between them), and the way back and on."""
    chunk = found.chunks[index]
    previous = found.previous_of(index)
    back = found.address.page_href(previous) if previous else found.address.path(found.page_path)
    back_label = "Previous" if previous else f"Back to {found.page_title}"
    onward = f'<a class="home-page-load-more" rel="next" href="{esc(found.address.page_href(chunk.next))}">Next</a>' if chunk.next else ""
    heading = found.attributes.get("heading") or "References"
    return (
        f'<div class="markus-document"><section class="home-page-references home-page-chunk" data-select="{esc(found.attributes["select"])}" data-card="{esc(found.card)}">'
        f'<h1 class="home-page-heading">{esc(heading)}</h1>'
        f'<p class="home-page-chunk-links"><a class="home-page-load-more" rel="prev" href="{esc(back)}">{esc(back_label)}</a></p>'
        f'{CARDS_OPEN}<ul class="home-page-grid" data-card="{esc(found.card)}">{items}</ul>{CARDS_CLOSE}'
        f'<p class="home-page-chunk-links">{onward}</p></section></div>'
    )


def cut_cards(rendered_page: str) -> tuple[str, str]:
    """``(page without the markers, the cards between them)`` for a rendered chunk page; the cards are what the data file carries."""
    start, end = rendered_page.find(CARDS_OPEN), rendered_page.find(CARDS_CLOSE)
    if start < 0 or end < start:
        raise ValueError("a rendered chunk page lost its card markers: a page_finish hook must keep HTML comments")
    inner = rendered_page[start + len(CARDS_OPEN):end]
    cards = inner[inner.find(">") + 1: inner.rfind("</ul>")]
    return rendered_page.replace(CARDS_OPEN, "").replace(CARDS_CLOSE, ""), cards


def data_file(found: PagedList, index: int, cards: str) -> bytes:
    chunk = found.chunks[index]
    document = {
        "format": DATA_FORMAT,
        "count": len(chunk.keys),
        "html": cards,
        "next": found.address.data_href(chunk.next) if chunk.next else None,
        "nextPage": found.address.page_href(chunk.next) if chunk.next else None,
    }
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def markdown_href(found: PagedList, name: str) -> str:
    """The site path of the Markdown twin of a chunk's page."""
    return found.address.page_href(name) + "index.md"


def markdown_more(found: PagedList, absolute: Callable[[str], str]) -> str:
    """The twin of a paged list ends with a link to the next page of its twin, not with the rest: see ``docs/home-page.md``."""
    chunk = found.first_chunk
    return f"[More]({absolute(markdown_href(found, chunk.name))})" if chunk is not None else ""
