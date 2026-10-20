"""Bounded HN collection through existing intake; never curates or trains."""
from __future__ import annotations

from dataclasses import dataclass
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
MAX_FEED_BYTES = 2_000_000


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

    @property
    def fingerprint(self) -> str:
        return _digest([self.title, self.canonical_url, self.published_at])


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
                "endpoint": self.endpoint, "sourceUrl": HN_FEED}


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


def fetch_hn_feed() -> bytes:
    request = Request(HN_FEED, headers={"User-Agent": "Papyrus-Monitor/0.1", "Accept": "application/rss+xml, application/xml"})
    with urlopen(request, timeout=25) as response:
        body = response.read(MAX_FEED_BYTES + 1)
    if len(body) > MAX_FEED_BYTES:
        raise ValueError("HN feed exceeds the response size bound")
    return body


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
