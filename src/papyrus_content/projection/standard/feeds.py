"""RSS 2.0 and Atom 1.0 from one selection.

Both formats are rendered from the same ordered list of entries, so they can
never disagree about what is in the feed. Withdrawal: an entry that is
unpublished, loses feed eligibility (``feed: false``, a section with ``feed:
false``) or is a draft leaves the selection, and the next projection removes it
from both files (the feed's input digest is the selection itself). Feed
identities are the permanent URLs, so an item that comes back keeps its id.
"""

from __future__ import annotations

import datetime as dt
from xml.sax.saxutils import escape, quoteattr

from ...authors import absolute_author_url
from .config import StandardSettings
from .entries import StandardEntry, newest_first
from .environment import SiteEnvironment
from .sitemap import XML_DECLARATION

ATOM_NS = "http://www.w3.org/2005/Atom"
DC_NS = "http://purl.org/dc/elements/1.1/"


def feed_selection(entries, settings: StandardSettings) -> list[StandardEntry]:
    eligible = [entry for entry in entries if entry.feed_eligible]
    return newest_first(eligible)[: settings.feeds.count]


def _midnight_utc(date: str) -> dt.datetime | None:
    try:
        return dt.datetime.combine(dt.date.fromisoformat(date), dt.time(0, 0), tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def rfc822(date: str) -> str:
    moment = _midnight_utc(date)
    return f"{moment:%a, %d %b %Y} 00:00:00 +0000" if moment else ""


def rfc3339(date: str) -> str:
    moment = _midnight_utc(date)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ") if moment else ""


def _link(environment: SiteEnvironment, path: str) -> str:
    return (environment.origin or "") + path


def _atom_author(author, environment: SiteEnvironment) -> str:
    uri = absolute_author_url(author.url, environment.origin)
    return f"<author><name>{escape(author.name)}</name>" + (f"<uri>{escape(uri)}</uri>" if uri else "") + "</author>"


def _root(settings: StandardSettings) -> str:
    """The base path with a trailing slash (``posts/``), or "" for a site at the root."""
    return f"{settings.base_path}/" if settings.base_path else ""


def _latest(selection: list[StandardEntry]) -> str:
    return max((entry.updated or entry.date for entry in selection), default="")


def rss_bytes(selection: list[StandardEntry], settings: StandardSettings, environment: SiteEnvironment) -> bytes:
    identity = settings.identity
    items = []
    for entry in selection:
        link = escape(_link(environment, entry.url))
        parts = [
            f"<title>{escape(entry.title)}</title>",
            f"<link>{link}</link>",
            f'<guid isPermaLink="true">{link}</guid>',
            f"<description>{escape(entry.summary_text)}</description>",
        ]
        if entry.date and rfc822(entry.date):
            parts.append(f"<pubDate>{rfc822(entry.date)}</pubDate>")
        parts.extend(f"<dc:creator>{escape(author.name)}</dc:creator>" for author in entry.author_details)
        parts.extend(f"<category>{escape(tag)}</category>" for tag in entry.tags)
        items.append("<item>" + "".join(parts) + "</item>")
    channel = [
        f"<title>{escape(settings.feeds.title)}{(' — ' + escape(identity.tagline)) if identity.tagline else ''}</title>",
        f"<link>{escape(_link(environment, '/'))}</link>",
        f"<description>{escape(identity.description or identity.tagline or identity.name)}</description>",
        f"<language>{escape(identity.language)}</language>",
    ]
    if rfc822(_latest(selection)):
        channel.append(f"<lastBuildDate>{rfc822(_latest(selection))}</lastBuildDate>")
    if environment.origin:
        channel.append(
            f'<atom:link href={quoteattr(_link(environment, "/" + _root(settings) + settings.feeds.rss_path))} rel="self" type="application/rss+xml"/>'
        )
    dc_namespace = f' xmlns:dc="{DC_NS}"' if any(entry.author_details for entry in selection) else ""
    return (
        f'{XML_DECLARATION}\n<rss version="2.0" xmlns:atom="{ATOM_NS}"{dc_namespace}><channel>'
        + "".join(channel)
        + "".join(items)
        + "</channel></rss>\n"
    ).encode("utf-8")


def atom_bytes(selection: list[StandardEntry], settings: StandardSettings, environment: SiteEnvironment) -> bytes:
    identity = settings.identity
    updated = rfc3339(_latest(selection)) or "1970-01-01T00:00:00Z"
    author_name = identity.author or identity.publisher or identity.name
    home = _link(environment, "/")
    header = [
        f"<title>{escape(settings.feeds.title)}</title>",
        f"<id>{escape(home)}</id>",
        f"<updated>{updated}</updated>",
        f'<link rel="alternate" type="text/html" href={quoteattr(home)}/>',
    ]
    if environment.origin:
        header.append(f'<link rel="self" type="application/atom+xml" href={quoteattr(_link(environment, "/" + _root(settings) + settings.feeds.atom_path))}/>')
    header.append(f"<author><name>{escape(author_name)}</name></author>")
    if identity.description or identity.tagline:
        header.append(f"<subtitle>{escape(identity.description or identity.tagline)}</subtitle>")
    entries = []
    for entry in selection:
        link = _link(environment, entry.url)
        parts = [
            f"<title>{escape(entry.title)}</title>",
            f"<id>{escape(link)}</id>",
            f'<link rel="alternate" type="text/html" href={quoteattr(link)}/>',
            f"<updated>{rfc3339(entry.updated or entry.date) or updated}</updated>",
        ]
        if rfc3339(entry.date):
            parts.append(f"<published>{rfc3339(entry.date)}</published>")
        if entry.summary_text:
            parts.append(f"<summary>{escape(entry.summary_text)}</summary>")
        parts.extend(_atom_author(author, environment) for author in entry.author_details)
        parts.extend(f"<category term={quoteattr(tag)}/>" for tag in entry.tags)
        entries.append("<entry>" + "".join(parts) + "</entry>")
    return (
        f'{XML_DECLARATION}\n<feed xmlns="{ATOM_NS}" xml:lang={quoteattr(identity.language)}>'
        + "".join(header)
        + "".join(entries)
        + "</feed>\n"
    ).encode("utf-8")


def feed_files(selection, settings: StandardSettings, environment: SiteEnvironment) -> dict[str, bytes]:
    files = {}
    if "rss" in settings.feeds.formats:
        files[_root(settings) + settings.feeds.rss_path] = rss_bytes(selection, settings, environment)
    if "atom" in settings.feeds.formats:
        files[_root(settings) + settings.feeds.atom_path] = atom_bytes(selection, settings, environment)
    return files
