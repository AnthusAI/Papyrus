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


def sitemap_files(style: str, environment: SiteEnvironment, urls: list[SitemapUrl], *, lastmod: bool = True, root: str = "",
                  languages: list[tuple[str, list[SitemapUrl]]] = ()) -> dict[str, bytes]:
    """``root`` is the base path with a trailing slash (``posts/``): the files live under it.

    ``languages`` are the other language editions' ``(root, urls)`` (``es/``, ``posts/es/``): with the ``index`` style each gets its own
    ``sitemap-0.xml`` under its root, listed in the one index; with the ``single`` style their URLs join the one ``sitemap.xml``. A ``<loc>`` is the
    page's percent-encoded URL, as every address Papyrus writes is (url_paths.py)."""
    if style == "index":
        files = {root + INDEXED_KEY: _urlset(environment.origin, urls, lastmod).encode("utf-8")}
        for language_root, language_urls in languages:
            files[language_root + INDEXED_KEY] = _urlset(environment.origin, language_urls, lastmod).encode("utf-8")
        listed = "".join(f"<sitemap><loc>{escape((environment.origin or '') + '/' + key)}</loc></sitemap>" for key in files)
        index = f'{XML_DECLARATION}<sitemapindex xmlns="{SITEMAP_NS}">{listed}</sitemapindex>\n'.encode("utf-8")
        return {root + INDEX_KEY: index, **files}
    every = list(urls) + [url for _language_root, language_urls in languages for url in language_urls]
    return {root + SINGLE_KEY: _urlset(environment.origin, every, lastmod).encode("utf-8")}


def robots_text(style: str, environment: SiteEnvironment, extra: tuple[str, ...] = (), *, root: str = "") -> str:
    """robots.txt stays at the bucket root (crawlers read only that one); its sitemap line names the sitemap under ``root``."""
    if environment.guarded:
        return "User-agent: *\nDisallow: /\n"
    sitemap_key = INDEX_KEY if style == "index" else SINGLE_KEY
    sitemap_line = f"Sitemap: {environment.origin}/{root}{sitemap_key}\n" if environment.origin else ""
    extras = "".join(f"{line}\n" for line in extra)
    return f"User-agent: *\nAllow: /\n{extras}{sitemap_line}"
