"""Hugging Face daily papers source for monitors (`sourceType: huggingface-papers`).

Reads the public list of papers the Hugging Face community picks each day (https://huggingface.co/api/daily_papers, no
key). A row is `{paper: {id, title, summary, authors, upvotes, ...}, publishedAt, title, summary, numComments, submittedBy,
organization}`; `paper.id` is an arXiv id. The list is newest first by the day a paper was picked, in pages of at most 100
rows (`limit`), and each response names the next page in its `Link` header; an empty page is the end.

Like the models source it has no item or page limit: it pages from the newest row until it reaches papers already collected
(the high-water mark), leaves the window (`lookbackDays`, the day the paper was picked) or the list ends, bound only by the
collector's time and the Hub's rate limit (monitoring_paging.py).

The item is the paper itself: its canonical URL is `https://arxiv.org/abs/<id>` and its source id is the same function of the
id as the arXiv feed's (`monitoring_feed.paper_source_id`), so a paper read from arXiv and from Hugging Face is one Reference at
intake. `details` keeps the title, abstract, authors, upvotes and comment count, who submitted it and for which organization.

Imports stay light on purpose: stdlib, `papyrus_content.monitoring`, `monitoring_feed` and `monitoring_paging`.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import time
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .monitoring import SourceItem, USER_AGENT
from .monitoring_feed import MAX_ABSTRACT_CHARACTERS, MAX_AUTHORS, is_arxiv_id, paper_source_id, paper_url
from .monitoring_paging import RateLimited, retry_after_seconds

HF_PAPERS_URL = "https://huggingface.co/api/daily_papers"
HF_HOST = "huggingface.co"
MAX_PAGE_BYTES = 16_000_000
MAX_PAGE_SIZE = 100            # the API refuses a larger `limit` (400)
DEFAULT_LOOKBACK_DAYS = 7


def _parse_time(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _count(value) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def validate_papers_config(raw: dict) -> dict:
    """The huggingface-papers part of a monitor CONFIG. `pageSize` is the API's page size (at most 100), not a total."""
    if urlsplit(str(raw.get("sourceUrl") or "")).path != "/api/daily_papers":
        raise ValueError(f"Config sourceUrl must be {HF_PAPERS_URL} for a huggingface-papers monitor")
    lookback, page_size = int(raw.get("lookbackDays", DEFAULT_LOOKBACK_DAYS)), int(raw.get("pageSize", MAX_PAGE_SIZE))
    if not 1 <= lookback <= 366:
        raise ValueError("Config lookbackDays must be between 1 and 366")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"Config pageSize must be between 1 and {MAX_PAGE_SIZE}")
    return {"lookbackDays": lookback, "pageSize": page_size}


# --- one paper -------------------------------------------------------------------------------------

def paper_details(row: dict) -> dict | None:
    """The fields kept from one row, or None for a row that is not a usable paper (no arXiv id or no title)."""
    paper = row.get("paper") if isinstance(row.get("paper"), dict) else {}
    arxiv_id = paper.get("id")
    title = " ".join(str(paper.get("title") or row.get("title") or "").split())[:1000]
    if not is_arxiv_id(arxiv_id) or not title:
        return None
    abstract = str(paper.get("summary") or row.get("summary") or "").strip()[:MAX_ABSTRACT_CHARACTERS]
    authors = [a["name"].strip() for a in paper.get("authors") or [] if isinstance(a, dict) and isinstance(a.get("name"), str) and a["name"].strip()]
    submitter = row.get("submittedBy") if isinstance(row.get("submittedBy"), dict) else {}
    organization = row.get("organization") if isinstance(row.get("organization"), dict) else {}
    details = {"arxivId": arxiv_id, "title": title,
               "publishedAt": paper.get("publishedAt") or row.get("publishedAt"),
               "submittedOnDailyAt": paper.get("submittedOnDailyAt"),
               "abstract": abstract or None, "authors": authors[:MAX_AUTHORS] or None,
               "upvotes": _count(paper.get("upvotes")), "comments": _count(row.get("numComments")),
               "submittedBy": submitter.get("name") if isinstance(submitter.get("name"), str) else None,
               "organization": (organization.get("fullname") or organization.get("name"))
               if isinstance(organization.get("fullname") or organization.get("name"), str) else None}
    return {k: v for k, v in details.items() if v is not None}


def paper_item(details: dict) -> SourceItem:
    url = paper_url(details["arxivId"])
    return SourceItem(paper_source_id(details["arxivId"]), details["title"], url, url, details.get("publishedAt"), details=details)


def parse_papers(body: bytes) -> list[dict]:
    """The usable rows of one response, as `details`. An error object or a page that is not JSON is refused."""
    if len(body) > MAX_PAGE_BYTES:
        raise ValueError("Hugging Face daily papers response is oversized")
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise ValueError("Hugging Face daily papers did not return JSON") from error
    if not isinstance(payload, list):
        raise ValueError("Expected a Hugging Face daily papers list, not an error response")
    return [d for d in (paper_details(row) for row in payload if isinstance(row, dict)) if d]


# --- the API ---------------------------------------------------------------------------------------

def check_papers_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != HF_HOST or parts.username or parts.password or parts.path != "/api/daily_papers":
        raise ValueError("Only https://huggingface.co/api/daily_papers URLs are accepted")
    return url


def fetch_papers_page(url: str) -> tuple[bytes, str | None]:
    """One page and the `next` URL from its Link header (a cursor). Paced; a 429 raises RateLimited carrying `Retry-After`."""
    check_papers_url(url)
    time.sleep(0.15)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=25) as response:
            body, link = response.read(MAX_PAGE_BYTES + 1), response.headers.get("Link", "")
    except HTTPError as error:
        if error.code == 429:
            raise RateLimited("Hugging Face rate limit reached", retry_after_seconds(error.headers.get("Retry-After"))) from error
        raise
    if len(body) > MAX_PAGE_BYTES:
        raise ValueError("Hugging Face daily papers response exceeds the size bound")
    match = re.search(r'<([^>]+)>;\s*rel="next"', link)
    return body, check_papers_url(match.group(1)) if match else None


def first_page_url(config: dict) -> str:
    return f"{check_papers_url(config['sourceUrl'])}?{urlencode({'limit': config['pageSize']})}"


def window_start(config: dict, now: float) -> datetime:
    return datetime.fromtimestamp(now - config["lookbackDays"] * 86400, timezone.utc)


def papers_feed(config: dict, now: float, fetch: Callable | None) -> dict:
    """The live read as a feed for `monitoring_paging.read_feed`: newest first, so a page that holds a collected paper is the
    high-water mark. The list is over once a page's oldest paper was picked before the window, or a page is empty."""
    fetch, since = fetch or fetch_papers_page, window_start(config, now)

    def fetch_page(cursor):
        body, following = fetch(cursor or first_page_url(config))
        return parse_papers(body), following

    def items(rows):
        picked = [_parse_time(d.get("submittedOnDailyAt") or d.get("publishedAt")) for d in rows]
        inside = [paper_item(d) for d, when in zip(rows, picked) if when is None or when >= since]
        over = not rows or (picked[-1] is not None and picked[-1] < since)
        return inside, over

    return {"key": "papers", "fetch_page": fetch_page, "items": items, "stop_at_seen": True}
