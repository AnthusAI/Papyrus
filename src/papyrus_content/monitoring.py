"""Bounded monitor collection through existing intake; never curates or trains.

A monitor reads one source type (`SOURCE_TYPES`): the Hacker News RSS feed, the USPTO TTAB
Reading Room's decision search, or the Hugging Face Hub model list (`monitoring_huggingface.py`). Each type turns its source into `SourceItem`s; everything after
that (fingerprints, revisions, routing, intake) is shared.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Callable
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

HN_FEED = "https://news.ycombinator.com/rss"
TTAB_DECISIONS_URL = "https://ttab-reading-room.uspto.gov/ttab-efoia-api/decision/search"
TTAB_DOCUMENT_ROOT = "https://ttab-reading-room.uspto.gov/ttab-document"
MAX_FEED_BYTES = 2_000_000
USER_AGENT = "Papyrus-Monitor/0.2 (+https://github.com/AnthusAI/Papyrus)"


def canonical_url(value: str) -> str:
    url = urlsplit(value.strip())
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
        raise ValueError("An HTTP(S) source URL without credentials is required")
    query = [(k, v) for k, v in parse_qsl(url.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((url.scheme.lower(), url.netloc.lower(), url.path or "/", urlencode(query), ""))


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SourceItem:
    source_id: str
    title: str
    canonical_url: str
    source_item_url: str
    published_at: str | None
    media_type: str = "text/html"
    aliases: tuple[str, ...] = ()       # other URLs of the same source document; intake treats them as one
    #: Structured fields of the source record (a Hugging Face model's license, tags, base models, ...),
    #: carried into the discovery. A `sha` here is the source's own revision: a new one is a new fingerprint.
    details: dict | None = field(default=None, compare=False, hash=False)

    @property
    def fingerprint(self) -> str:
        revision = (self.details or {}).get("sha")
        return _digest([self.title, self.canonical_url, self.published_at] + ([revision] if revision else []))


@dataclass(frozen=True)
class Monitor:
    id: str
    publication: str
    corpus_id: str
    endpoint: str
    state: Path
    interval_seconds: int = 900
    limit: int = 10
    source_ids: tuple[str, ...] = ()
    source_url: str = HN_FEED
    source_name: str = "Hacker News"

    def __post_init__(self):
        endpoint = urlsplit(self.endpoint)
        if (not self.id or not self.publication or not self.corpus_id or endpoint.scheme != "https"
                or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
            raise ValueError("Monitor requires an explicit publication, corpus and HTTPS endpoint binding")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("Monitor limit must be between 1 and 100")
        if type(self.interval_seconds) is not int or self.interval_seconds < 60:
            raise ValueError("Monitor interval must be at least 60 seconds")

    @property
    def binding(self) -> dict:
        return {"monitorId": self.id, "publication": self.publication, "corpusId": self.corpus_id,
                "endpoint": self.endpoint, "sourceUrl": self.source_url}


def parse_hn_feed(body: bytes) -> list[SourceItem]:
    if len(body) > MAX_FEED_BYTES or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("HN feed is oversized or contains an unsupported XML declaration")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise ValueError("Invalid HN RSS XML") from error
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError("Expected an RSS channel, not an HTML/error response")
    items, seen = [], set()
    for row in channel.findall("item"):
        title, source = (row.findtext("title") or "").strip(), (row.findtext("link") or "").strip()
        item_url = (row.findtext("comments") or row.findtext("guid") or "").strip()
        parsed = urlsplit(item_url)
        source_id = (parse_qs(parsed.query).get("id") or [""])[0]
        if (parsed.hostname != "news.ycombinator.com" or parsed.path != "/item"
                or parsed.scheme != "https" or not source_id.isdigit() or not title or not source):
            raise ValueError("HN item is missing title, source URL or stable HN identity")
        if source_id in seen:
            continue
        seen.add(source_id)
        date = row.findtext("pubDate")
        try:
            published = parsedate_to_datetime(date).astimezone(timezone.utc).isoformat() if date else None
        except (ValueError, TypeError) as error:
            raise ValueError(f"Invalid publication date on HN item {source_id}") from error
        items.append(SourceItem(source_id, title, canonical_url(source),
                                f"https://news.ycombinator.com/item?id={source_id}", published))
    return items


def fetch_hn_feed(url: str = HN_FEED) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml"})
    with urlopen(request, timeout=25) as response:
        body = response.read(MAX_FEED_BYTES + 1)
    if len(body) > MAX_FEED_BYTES:
        raise ValueError("HN feed exceeds the response size bound")
    return body


def ttab_search_body(now: float, lookback_days: int, limit: int, *, precedential_only: bool = False) -> bytes:
    """The Reading Room search for decisions issued in the last `lookback_days`, newest first.

    The date filter key is `decisionDate`, but sorting must use `issueDate`: sorting by
    `decisionDate` silently returns nothing. `precedential_only` asks for decisions the Board
    has designated precedential, which it can do months after a decision issues.
    """
    end = datetime.fromtimestamp(now, timezone.utc).date()
    start = datetime.fromtimestamp(now - lookback_days * 86400, timezone.utc).date()
    return json.dumps({"dateRangeData": {"decisionDate": {"from": start.isoformat(), "to": end.isoformat()}},
                       "facetData": {}, "parameterData": {"precedentCitableIndicator": "Y"} if precedential_only else {},
                       "recordTotalQuantity": limit, "searchText": "",
                       "sortDataBag": [{"issueDate": "desc"}], "recordStartNumber": 0}).encode()


def fetch_ttab_decisions(url: str, body: bytes) -> bytes:
    request = Request(url, data=body, method="POST",
                      headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"})
    with urlopen(request, timeout=25) as response:
        payload = response.read(MAX_FEED_BYTES + 1)
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("TTAB decision search exceeds the response size bound")
    return payload


def parse_ttab_decisions(body: bytes, *, final_decisions_only: bool = True) -> list[SourceItem]:
    """One item per decision document. A redesignation as precedential changes the title,
    so the decision is collected again as a new revision."""
    if len(body) > MAX_FEED_BYTES:
        raise ValueError("TTAB decision search response is oversized")
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise ValueError("TTAB decision search did not return JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("Expected a TTAB decision search result, not an error response")
    items, seen = [], set()
    for row in payload["results"]:
        document = str(row.get("documentId") or "")
        proceeding = str(row.get("proceedingNumber") or "")
        party, decision = str(row.get("partyName") or "").strip(), str(row.get("decision") or "").strip()
        if not document.startswith("/legal-proceeding/") or not document.endswith(".pdf") or not proceeding.isdigit() or not party:
            raise ValueError("TTAB decision is missing its document, proceeding number or party")
        if final_decisions_only and row.get("decisionTypeCategory") != "Final Decision":
            continue
        source_id = f"{proceeding}-{document.rsplit('/', 1)[-1].removesuffix('.pdf')}"
        if source_id in seen:
            continue
        seen.add(source_id)
        precedential = " [precedential]" if row.get("precedentCitableIndicator") == "Y" else ""
        kind = str(row.get("proceedingTypeCd") or "").strip()
        issued = row.get("issueDate")
        published = _iso(issued / 1000) if isinstance(issued, (int, float)) else None
        title = " ".join(f"{party}: {decision}{precedential}".split())[:1000]
        items.append(SourceItem(source_id, title, f"{TTAB_DOCUMENT_ROOT}{document}",
                                f"https://ttabvue.uspto.gov/ttabvue/v?pno={proceeding}&pty={kind}", published,
                                "application/pdf", ttab_document_aliases(document)))
    return items


def ttab_document_aliases(document: str) -> tuple[str, ...]:
    """The same decision document at its other addresses: the Reading Room path with the double
    slash the site itself links, and the TTABVUE PDF (`/legal-proceeding/<n>/decision/<TYPE>_<entry>.pdf`
    is `ttabvue-<n>-<TYPE>-<entry>.pdf`)."""
    aliases = [f"{TTAB_DOCUMENT_ROOT}/{document}"]
    parts = document.strip("/").split("/")
    if len(parts) == 4 and parts[0] == "legal-proceeding" and parts[2] == "decision" and "_" in parts[3]:
        kind, entry = parts[3].removesuffix(".pdf").rsplit("_", 1)
        aliases.append(f"https://ttabvue.uspto.gov/ttabvue/ttabvue-{parts[1]}-{kind}-{entry}.pdf")
    return tuple(aliases)


def merge_source_items(*groups: list[SourceItem]) -> list[SourceItem]:
    """One item per source id across several result lists; a later list wins (its data is newer or more specific)."""
    merged: dict[str, SourceItem] = {}
    for group in groups:
        for item in group:
            merged[item.source_id] = item
    return list(merged.values())


#: Source types a monitor can read: the hosts its sourceUrl may name, its display name and how to read it.
SOURCE_TYPES = {
    "hn-rss": {"host": "news.ycombinator.com", "name": "Hacker News", "media": "rss"},
    "ttab-decisions": {"host": "ttab-reading-room.uspto.gov", "name": "TTAB Reading Room", "media": "json-search"},
    "huggingface-models": {"host": "huggingface.co", "name": "Hugging Face Hub", "media": "json-list"},
}


def collect(monitor: Monitor, intake: Callable[[SourceItem, dict], dict], *,
            fetch: Callable[[], bytes] = fetch_hn_feed, now: float | None = None, force: bool = False) -> dict:
    """Collect once when due. A retry-safe intake receipt precedes checkpointing.

    Successes commit individually; a later failure cannot erase earlier progress.
    Workers sharing this local checkpoint are serialized, not distributed-locked.
    """
    now = time.time() if now is None else now
    path = Path(monitor.state)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Monitor checkpoint must not be a symlink")
    fd = os.open(path.with_suffix(path.suffix + ".lock"), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("This Monitor checkpoint is already running") from error
        with sqlite3.connect(path) as db:
            os.chmod(path, 0o600)
            db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS current (source_id TEXT PRIMARY KEY, fingerprint TEXT, revision INTEGER, receipt TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS discoveries (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            binding = json.dumps(monitor.binding, sort_keys=True)
            previous = db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()
            if previous and previous[0] != binding:
                raise ValueError("Monitor checkpoint binding does not match publication/corpus/endpoint")
            db.execute("INSERT OR IGNORE INTO meta VALUES ('binding', ?)", (binding,))
            due = db.execute("SELECT value FROM meta WHERE key='next_due'").fetchone()
            result = {"monitorId": monitor.id, "publication": monitor.publication, "corpusId": monitor.corpus_id,
                      "observedAt": _iso(now), "discoveries": [], "unchanged": 0, "errors": [],
                      "status": "complete", "nextDueAt": _iso(float(due[0])) if due else _iso(now)}
            if due and float(due[0]) > now and not force:
                return {**result, "status": "not_due"}
            try:
                items = parse_hn_feed(fetch())
            except Exception as error:
                result["status"] = "failed"
                result["errors"].append({"stage": "fetch", "message": str(error)[:300]})
                items = []
            if monitor.source_ids:
                found = {item.source_id for item in items}
                if result["status"] != "failed":
                    for source_id in sorted(set(monitor.source_ids) - found):
                        result["errors"].append({"stage": "selection", "sourceId": source_id,
                                                 "message": "Selected HN item is no longer in the current feed"})
                items = [item for item in items if item.source_id in monitor.source_ids]
            for item in items[:monitor.limit]:
                old = db.execute("SELECT fingerprint, revision FROM current WHERE source_id=?", (item.source_id,)).fetchone()
                if old and old[0] == item.fingerprint:
                    result["unchanged"] += 1
                    continue
                provenance = {**monitor.binding, "sourceId": item.source_id, "sourceItemUrl": item.source_item_url,
                              "canonicalUrl": item.canonical_url, "sourcePublishedAt": item.published_at,
                              "observedAt": _iso(now), "fingerprint": item.fingerprint,
                              "revision": old[1] + 1 if old else 1}
                try:
                    receipt = intake(item, provenance)
                    if not isinstance(receipt, dict) or not receipt.get("referenceId") or not receipt.get("referenceLineageId"):
                        raise ValueError("Existing intake did not return a persisted Reference receipt")
                except Exception as error:
                    result["errors"].append({"stage": "intake", "sourceId": item.source_id, "message": str(error)[:300]})
                    continue
                discovery = {**provenance, **receipt}
                event_id = _digest([monitor.binding, item.source_id, item.fingerprint])
                db.execute("INSERT OR IGNORE INTO discoveries VALUES (?, ?)", (event_id, json.dumps(discovery, sort_keys=True)))
                db.execute("INSERT OR REPLACE INTO current VALUES (?, ?, ?, ?)",
                           (item.source_id, item.fingerprint, provenance["revision"], json.dumps(receipt)))
                db.commit()
                result["discoveries"].append(discovery)
            if result["errors"] and result["status"] != "failed":
                result["status"] = "partial"
            result["nextDueAt"] = _iso(now + monitor.interval_seconds)
            db.execute("INSERT OR REPLACE INTO meta VALUES ('next_due', ?)", (str(now + monitor.interval_seconds),))
            db.execute("INSERT OR REPLACE INTO meta VALUES ('last_result', ?)", (json.dumps(result, sort_keys=True),))
            db.commit()
            return result
