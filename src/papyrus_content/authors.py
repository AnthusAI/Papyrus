"""One reading of an item's authors, shared by every place that renders or serialises them.

Front matter writes ``authors`` (or ``author``) three ways: a string (``"Ann, Bo"``), a list of strings, or a list of
``{name, url}`` objects. A list may mix them, and a lone object is accepted too. :func:`normalize_authors` turns any of
these into a tuple of :class:`Author`, in order, without duplicate names. Renderers read ``.name`` (and ``.url`` when
they can link); nothing should ever ``str()`` a raw author value.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Author:
    name: str
    url: str = ""

    def __str__(self) -> str:
        return self.name


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _item(value) -> list[Author]:
    """One list item: an object, an Author, or a string that is a single author (never split)."""
    if isinstance(value, Author):
        return [value] if value.name else []
    if isinstance(value, Mapping):
        name = _text(value.get("name"))
        return [Author(name, _text(value.get("url")))] if name else []
    return [Author(_text(value))] if _text(value) else []


def normalize_authors(raw) -> tuple[Author, ...]:
    """Authors from a string, a list of strings, a list of ``{name, url}`` objects, or a mix; empty when there are none.

    A bare string is split on commas (``"Ann, Bo"``); a list item is one author. The first url given for a name wins,
    and a later duplicate name is dropped."""
    if raw is None:
        return ()
    if isinstance(raw, (list, tuple)):
        found = [author for item in raw for author in _item(item)]
    elif isinstance(raw, str):
        found = [Author(part.strip()) for part in raw.split(",") if part.strip()]
    else:
        found = _item(raw)
    unique: dict[str, Author] = {}
    for author in found:
        if author.name not in unique or (author.url and not unique[author.name].url):
            unique[author.name] = author
    return tuple(unique.values())


def author_names(raw) -> tuple[str, ...]:
    return tuple(author.name for author in normalize_authors(raw))


def absolute_author_url(url: str, origin: str | None) -> str:
    """The author's url as an absolute URL: kept when it already is one, joined to the site origin when it is a path, and
    empty when it is a path and the site has no origin (a relative uri in a feed is wrong)."""
    if not url:
        return ""
    if "://" in url:
        return url
    if url.startswith("/") and origin:
        return origin.rstrip("/") + url
    return ""
