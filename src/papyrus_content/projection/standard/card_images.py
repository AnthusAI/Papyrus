"""Pictures of cards and other ``<img>`` tags that name a stored picture by its front-matter path.

A story's ``image`` is the path its picture was stored under (``assets/<slug>/<file>``). The file at that path exists only when the
upload was announced to the renditions function after the site began to keep originals (``media.originals``), and when the story still
holds that exact path; the renditions the article page itself shows exist whenever the picture was uploaded at all. A card that
names the original can therefore be coverless while its article shows the picture. Every page is passed through :func:`use_renditions`,
which points an ``<img>`` whose address is a stored picture with renditions at the same file the article page uses. Web addresses,
pictures with no renditions, and every tag that is not an ``<img>`` (``og:image``, feeds) are left as written.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable

from ...renditions import picture_href

IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
SRC_ATTRIBUTE = re.compile(r'(\bsrc=")([^"]*)(")')


def hrefs_by_source(records: Iterable[dict], pipeline) -> dict[str, str]:
    """``source -> site-relative file`` for each record that has a file to show (a record of the site store, see ``picture_href``)."""
    found: dict[str, str] = {}
    for record in records:
        href = picture_href(record, record["source"], pipeline)
        if href:
            found[record["source"]] = href
    return found


def _source_of(address: str, hrefs: dict[str, str]) -> tuple[str, str] | None:
    """``(prefix, source)`` when ``address`` is a stored picture's path, with whatever (``/``, ``../``) precedes it."""
    path = address.split("?", 1)[0].split("#", 1)[0]
    if not path or "://" in path or path.startswith("//") or path.startswith("data:"):
        return None
    cut = 0
    while True:
        if path[cut:] in hrefs:
            return path[:cut], path[cut:]
        cut = path.find("/", cut) + 1
        if cut == 0:
            return None


def use_renditions(markup: str, hrefs: Callable[[], dict[str, str]], root: str) -> str:
    """``markup`` with each ``<img src>`` that is a stored picture pointing at that picture's rendition.

    ``hrefs`` is read only when the markup has such an ``<img>`` (it reads the site store), and ``root`` is the base path with a trailing
    slash (``"articles/"``) or ``""``: an address that starts at the site root, or names the path with nothing before it, is rewritten to
    start at the site root (the one address that works on every page); one that climbs (``../``) keeps its climb."""
    if "<img" not in markup:
        return markup
    table: dict[str, str] | None = None

    def rewrite(tag: re.Match) -> str:
        nonlocal table
        match = SRC_ATTRIBUTE.search(tag.group(0))
        if match is None or "/responsive/" in match.group(2):
            return tag.group(0)
        address = html.unescape(match.group(2))
        if table is None:
            table = hrefs()
        found = _source_of(address, table)
        if found is None:
            return tag.group(0)
        prefix, source = found
        target = table[source]
        if target == source:
            return tag.group(0)
        shown = ("/" + root if prefix in ("", "/") else prefix) + target   # an address from the site root stays one, whatever page shows the card
        return tag.group(0)[: match.start(2)] + html.escape(shown, quote=True) + tag.group(0)[match.end(2):]

    return IMG_TAG.sub(rewrite, markup)
