"""A Story's address on the published site, read from the site's own sitemap (PPY-1905cc).

``item_front_matter.item_path`` rebuilds an address from the section, the slug and the URL style, but a site's projection may put a type under its own segment
(Machines on Machines serves Articles at ``/articles/<slug>/``), and only the projection's settings know that. The published sitemap does: this reads it once
per process (and again after ``CACHE_SECONDS``) and finds the one page whose last segment is the Story's slug. When the sitemap cannot be read, or no single
page matches, the rebuilt address is kept, so nothing gets worse than it was. Standard library only: the image service function and the runner both import it.
"""
from __future__ import annotations

import re
import time
import urllib.request
from typing import Callable
from urllib.parse import urlsplit

CACHE_SECONDS = 600
MAX_CHILD_SITEMAPS = 20
TIMEOUT_SECONDS = 10
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")

_cache: dict[str, tuple[float, tuple[str, ...]]] = {}


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "papyrus-announcements"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:   # noqa: S310 (the site's own https origin)
        return response.read().decode("utf-8", "replace")


def sitemap_paths(origin: str, fetch: Callable[[str], str] = fetch_text) -> tuple[str, ...]:
    """The path of every page the site's sitemap lists, following a sitemap index one level down."""
    root = origin.rstrip("/")
    text = fetch(f"{root}/sitemap.xml")
    locations = LOC.findall(text)
    if "<sitemapindex" in text:
        locations = [location for child in locations[:MAX_CHILD_SITEMAPS] for location in LOC.findall(fetch(child))]
    return tuple(urlsplit(location).path or "/" for location in locations)


def slug_of(path: str) -> str:
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return last[:-5] if last.endswith(".html") else last


def published_path(origin: str, slug: str, rebuilt: str, *, fetch: Callable[[str], str] = fetch_text, now: Callable[[], float] = time.monotonic) -> str:
    """The Story's path as the site publishes it, or ``rebuilt`` when the sitemap cannot say."""
    if not origin or not slug:
        return rebuilt
    try:
        cached = _cache.get(origin)
        if cached is None or now() - cached[0] > CACHE_SECONDS:
            cached = (now(), sitemap_paths(origin, fetch))
            _cache[origin] = cached
    except Exception:   # an unreachable or malformed sitemap leaves the rebuilt address, never a failed run
        return rebuilt
    matches = [path for path in cached[1] if slug_of(path) == slug]
    if rebuilt in matches or not matches:
        return rebuilt
    # A language edition repeats a page under its prefix; the primary language's page is the shortest path.
    shortest = min(matches, key=len)
    return shortest if sum(1 for path in matches if len(path) == len(shortest)) == 1 else rebuilt
