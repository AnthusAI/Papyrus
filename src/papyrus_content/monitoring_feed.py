"""General RSS 2.0 and Atom feed source for monitors (`sourceType: feed`), and the paper-id rule shared with
the Hugging Face papers source (`monitoring_hf_papers.py`).

The feed address is configuration (`sourceUrl`), so a new feed needs a monitor config and no code. What the code
holds is the list of hosts a feed may come from (`FEED_HOSTS`: adding one is one line), the safety limits and the
few per-host rules (`HOST_RULES`), because a host's feed has conventions no general reader can guess.

Safety, as for the Hacker News reader: https only, no credentials, a response size limit, and a document that
declares a DOCTYPE or an ENTITY is refused (the standard library parser would expand entity declarations).

Each entry becomes a `SourceItem`: the source id is the entry's stable id (an arXiv paper: the bare arXiv id), the
canonical URL is the entry's link, and `details` carries what the feed says about the entry (title, publication date,
abstract or description, authors, categories). A decision can therefore use the feed's abstract without fetching the
paper (docs/monitoring-cloud.md, "Feed monitors").

arXiv (`rss.arxiv.org`, `export.arxiv.org`): the feed lists new papers (`announce_type` new), cross-lists (`cross`) and
revisions of old papers (`replace`, `replace-cross`). A revision is not news, so it is skipped. The abstract is the
feed's description without its leading "arXiv:ID vN Announce Type: ..." line and "Abstract:" label; LaTeX is kept as is.

Imports stay light on purpose: stdlib, `papyrus_content.monitoring` and `papyrus_content.monitoring_web`.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .monitoring import SourceItem, USER_AGENT, canonical_url
from .monitoring_paging import RateLimited, retry_after_seconds
from .monitoring_web import arxiv_paper_id

#: Hosts a `feed` monitor may read, with the name shown for the source. Adding a host is one line.
FEED_HOSTS = {
    "rss.arxiv.org": "arXiv",
    "export.arxiv.org": "arXiv",
}
#: Larger than the 2 MB of the Hacker News feed: arXiv's combined daily feed for five categories is about 3.6 MB.
MAX_FEED_DOCUMENT_BYTES = 8_000_000
FEED_PAGE_ITEMS = 100          # entries committed between two cursor positions; not a total (the whole feed is read)
MAX_ABSTRACT_CHARACTERS = 20_000
MAX_AUTHORS = 50
MAX_CATEGORIES = 20
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
SOURCE_ID = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
ARXIV_SKIPPED_ANNOUNCE_TYPES = frozenset({"replace", "replace-cross"})
_ARXIV_GUID = re.compile(r"^oai:arxiv\.org:(.+?)(?:v\d+)?$", re.IGNORECASE)
_ARXIV_ID = re.compile(r"^(?:[a-z\-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})$")
_ARXIV_PREFIX = re.compile(r"\A\s*arXiv:\S+\s+Announce Type:\s*\S+\s*\n?\s*(?:Abstract:\s*)?", re.IGNORECASE)
_ABSTRACT_LABEL = re.compile(r"\A\s*Abstract:\s*")


# --- identifiers -----------------------------------------------------------------------------------

def safe_source_id(value: str) -> str:
    """A feed entry's id as a key-safe source id: used as is when it fits, otherwise its safe characters and a hash."""
    value = value.strip()
    if SOURCE_ID.match(value):
        return value
    safe = re.sub(r"[^0-9A-Za-z_-]", "_", value)[:55]
    return f"{safe}-{hashlib.sha256(value.encode()).hexdigest()[:8]}"


def paper_source_id(arxiv_id: str) -> str:
    """A bare arXiv id as a source id: `2611.00159` is `2611_00159`, `cs/0112017` is `cs--0112017`. Reversible, and the same
    for the same paper wherever it is read (arXiv's feed, Hugging Face), so a source id never differs for one paper."""
    return safe_source_id(arxiv_id.replace("/", "--").replace(".", "_"))


def paper_url(arxiv_id: str) -> str:
    """The one address of a paper: `https://arxiv.org/abs/<id>`. Intake keys a Reference on it, so the same paper from arXiv and
    from Hugging Face is one Reference."""
    return f"https://arxiv.org/abs/{arxiv_id}"


def is_arxiv_id(value) -> bool:
    return isinstance(value, str) and bool(_ARXIV_ID.match(value))


# --- config and fetch ------------------------------------------------------------------------------

def check_feed_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in FEED_HOSTS or parts.username or parts.password or parts.fragment:
        raise ValueError(f"A feed must be an https URL on one of: {', '.join(sorted(FEED_HOSTS))}")
    return url


def validate_feed_config(raw: dict) -> dict:
    """The feed part of a monitor CONFIG (the common fields are validated by the caller): the address only. A feed is read
    whole each pass and has no window, page size or item limit of its own."""
    try:
        check_feed_url(str(raw.get("sourceUrl") or ""))
    except ValueError as error:
        raise ValueError(f"Config sourceUrl: {error} (for a feed monitor)") from error
    return {}


def fetch_feed(url: str) -> bytes:
    check_feed_url(url)
    request = Request(url, headers={"User-Agent": USER_AGENT,
                                    "Accept": "application/rss+xml, application/atom+xml, application/xml"})
    try:
        with urlopen(request, timeout=25) as response:
            body = response.read(MAX_FEED_DOCUMENT_BYTES + 1)
    except HTTPError as error:
        if error.code == 429:
            raise RateLimited("Feed host rate limit reached", retry_after_seconds(error.headers.get("Retry-After"))) from error
        raise
    if len(body) > MAX_FEED_DOCUMENT_BYTES:
        raise ValueError("Feed exceeds the response size bound")
    return body


# --- reading a document ----------------------------------------------------------------------------

def _text(element, *tags: str) -> str:
    for tag in tags:
        found = element.find(tag)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _date(value: str) -> str | None:
    """An RFC 822 (RSS) or ISO 8601 (Atom) date as UTC ISO 8601, or None when absent or unreadable (one odd date
    must not stop a feed of a thousand entries)."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value) if not re.match(r"^\d{4}-\d{2}-\d{2}", value) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _entries(root: ET.Element) -> list[dict]:
    """The entries of an RSS 2.0 or Atom document as plain dicts: id, title, link, published, summary, authors, categories,
    announce (arXiv's `announce_type`, when present)."""
    entries = []
    if root.tag == "rss" and root.find("channel") is not None:
        for row in root.find("channel").findall("item"):
            entries.append({
                "id": _text(row, "guid"), "title": _text(row, "title"), "link": _text(row, "link"),
                "published": _date(_text(row, "pubDate")),
                "summary": _text(row, "description", "{http://purl.org/rss/1.0/modules/content/}encoded"),
                "authors": [name.strip() for author in row.findall(f"{DC}creator") for name in (author.text or "").split(",") if name.strip()],
                "categories": [c.text.strip() for c in row.findall("category") if (c.text or "").strip()],
                "announce": _text(row, f"{ARXIV_NS}announce_type")})
    elif root.tag == f"{ATOM}feed":
        for row in root.findall(f"{ATOM}entry"):
            links = row.findall(f"{ATOM}link")
            alternate = next((link for link in links if link.get("rel", "alternate") == "alternate" and link.get("href")), None)
            entries.append({
                "id": _text(row, f"{ATOM}id"), "title": _text(row, f"{ATOM}title"),
                "link": (alternate.get("href") if alternate is not None else "") or _text(row, f"{ATOM}id"),
                "published": _date(_text(row, f"{ATOM}published", f"{ATOM}updated")),
                "summary": _text(row, f"{ATOM}summary", f"{ATOM}content"),
                "authors": [_text(author, f"{ATOM}name") for author in row.findall(f"{ATOM}author") if _text(author, f"{ATOM}name")],
                "categories": [c.get("term").strip() for c in row.findall(f"{ATOM}category") if (c.get("term") or "").strip()],
                "announce": _text(row, f"{ARXIV_NS}announce_type")})
    else:
        raise ValueError("Expected an RSS 2.0 channel or an Atom feed, not an HTML/error response")
    return entries


def _clean_text(value: str) -> str:
    return " ".join(value.split())[:1000]


# --- per-host rules --------------------------------------------------------------------------------

def arxiv_rule(entry: dict) -> dict | None:
    """arXiv: skip revisions, take the bare paper id, the canonical `arxiv.org/abs` address and the abstract without the feed's header."""
    if entry["announce"] in ARXIV_SKIPPED_ANNOUNCE_TYPES:
        return None
    paper = arxiv_paper_id(entry["link"])
    if not paper:
        match = _ARXIV_GUID.match(entry["id"])
        paper = match.group(1) if match and is_arxiv_id(match.group(1)) else None
    if not paper:
        return None
    return {"source_id": paper_source_id(paper), "url": paper_url(paper), "abstract": strip_arxiv_header(entry["summary"]),
            "extra": {"arxivId": paper, **({"announceType": entry["announce"]} if entry["announce"] else {})}}


def strip_arxiv_header(text: str) -> str:
    """The abstract as the feed gives it, less the leading "arXiv:ID vN Announce Type: new" line and the "Abstract:" label."""
    text = text.strip()
    stripped = _ARXIV_PREFIX.sub("", text, count=1) if _ARXIV_PREFIX.match(text) else _ABSTRACT_LABEL.sub("", text, count=1)
    return stripped.strip()


#: A host's own rule for its entries: `entry -> {"source_id", "url", "abstract", "extra"}` or None to skip the entry.
HOST_RULES: dict[str, Callable[[dict], dict | None]] = {
    "rss.arxiv.org": arxiv_rule,
    "export.arxiv.org": arxiv_rule,
}


def parse_feed(body: bytes, source_url: str) -> list[SourceItem]:
    """The entries of one RSS 2.0 or Atom document as items, newest first as the feed lists them, each once. An entry with no
    title or link, or one the host's rule skips (an arXiv revision), is left out. A document that is oversized, declares a
    DOCTYPE or ENTITY, or is not an RSS or Atom feed is an error; an empty feed is fine."""
    if len(body) > MAX_FEED_DOCUMENT_BYTES or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("Feed is oversized or contains an unsupported XML declaration")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise ValueError("Invalid feed XML") from error
    rule = HOST_RULES.get(urlsplit(source_url).hostname or "")
    items, seen = [], set()
    for entry in _entries(root):
        title, link = _clean_text(entry["title"]), entry["link"]
        if not title or not link:
            continue
        found = {"source_id": safe_source_id(entry["id"] or link), "url": None, "abstract": entry["summary"], "extra": {}}
        if rule:
            found = rule(entry)
            if found is None:
                continue
        url = found["url"] or canonical_url(link)
        if found["source_id"] in seen:
            continue
        seen.add(found["source_id"])
        details = {"title": title, **({"publishedAt": entry["published"]} if entry["published"] else {}),
                   **({"abstract": found["abstract"][:MAX_ABSTRACT_CHARACTERS]} if found["abstract"] else {}),
                   **({"authors": entry["authors"][:MAX_AUTHORS]} if entry["authors"] else {}),
                   **({"categories": entry["categories"][:MAX_CATEGORIES]} if entry["categories"] else {}), **found["extra"]}
        items.append(SourceItem(found["source_id"], title, url, url, entry["published"], details=details))
    return items


def feed_page_reader(items_of: Callable[[], list[SourceItem]]) -> Callable:
    """`fetch_page(cursor)` over a feed read whole once per pass: pages of `FEED_PAGE_ITEMS` entries, the cursor being the source
    id of the last entry of the previous page (an offset would skip entries if the feed were rebuilt between two passes; an id
    that is no longer in the feed starts over at the top, and entries already collected are unchanged)."""
    def fetch_page(cursor):
        items = items_of()
        start = 0
        if cursor:
            ids = [item.source_id for item in items]
            start = ids.index(cursor) + 1 if cursor in ids else 0
        page = items[start:start + FEED_PAGE_ITEMS]
        return page, (page[-1].source_id if page and start + len(page) < len(items) else None)
    return fetch_page


def feed_source(config: dict, fetch: Callable[[str], bytes] | None) -> dict:
    """The feed as one source for `monitoring_paging.read_feed`: downloaded once per pass, committed page by page."""
    cache: dict = {}

    def items_of():
        if "items" not in cache:
            cache["items"] = parse_feed((fetch or fetch_feed)(config["sourceUrl"]), config["sourceUrl"])
        return cache["items"]

    return {"key": "feed", "fetch_page": feed_page_reader(items_of), "items": lambda rows: (rows, False), "stop_at_seen": True}
