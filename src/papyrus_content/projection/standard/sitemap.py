"""sitemap.xml (or an index plus ``sitemap-0.xml``) and robots.txt from one set of URLs."""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

from .environment import SiteEnvironment

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
SINGLE_KEY = "sitemap.xml"
INDEX_KEY = "sitemap-index.xml"
INDEXED_KEY = "sitemap-0.xml"
SITEMAP_KEYS = (SINGLE_KEY, INDEX_KEY, INDEXED_KEY)
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'


@dataclass(frozen=True)
class SitemapUrl:
    path: str
    lastmod: str = ""


def _urlset(origin: str | None, urls: list[SitemapUrl], lastmod: bool) -> str:
    if origin is None:
        body = ""   # no origin, no absolute URLs: an empty urlset rather than relative <loc>s
    else:
        entries = []
        for url in sorted(urls, key=lambda found: found.path):
            stamp = f"<lastmod>{escape(url.lastmod)}</lastmod>" if lastmod and url.lastmod else ""
            entries.append(f"<url><loc>{escape(origin + url.path)}</loc>{stamp}</url>")
        body = "".join(entries)
    return f'{XML_DECLARATION}<urlset xmlns="{SITEMAP_NS}">{body}</urlset>\n'


def sitemap_files(style: str, environment: SiteEnvironment, urls: list[SitemapUrl], *, lastmod: bool = True) -> dict[str, bytes]:
    urlset = _urlset(environment.origin, urls, lastmod).encode("utf-8")
    if style == "index":
        index = (
            f'{XML_DECLARATION}<sitemapindex xmlns="{SITEMAP_NS}"><sitemap>'
            f"<loc>{escape((environment.origin or '') + '/' + INDEXED_KEY)}</loc></sitemap></sitemapindex>\n"
        ).encode("utf-8")
        return {INDEX_KEY: index, INDEXED_KEY: urlset}
    return {SINGLE_KEY: urlset}


def robots_text(style: str, environment: SiteEnvironment, extra: tuple[str, ...] = ()) -> str:
    if environment.guarded:
        return "User-agent: *\nDisallow: /\n"
    sitemap_key = INDEX_KEY if style == "index" else SINGLE_KEY
    sitemap_line = f"Sitemap: {environment.origin}/{sitemap_key}\n" if environment.origin else ""
    extras = "".join(f"{line}\n" for line in extra)
    return f"User-agent: *\nAllow: /\n{extras}{sitemap_line}"
