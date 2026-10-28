"""Web-search monitors: a monitor's queries asked of Tavily, newest news since the monitor's last complete pass.

Tavily's search has no result offset: one request returns at most `TAVILY_PAGE_LIMIT` (its own maximum) results.
So the way to read *everything* it has is to narrow the date range: a window whose answer fills the page is split
in two (`start_date` / `end_date`, a day at a time) and each half is asked again, down to a single day. Nothing here
caps a pass; the real bounds are the Lambda's time (the pass hands back resume cursors) and Tavily's rate limit
(a 429 is waited out for its Retry-After, see `monitoring_paging`).

Recency comes from the monitor's high-water mark (`watermark` in its STATE: the start of the last pass that read
every query to its end), never from a fixed window. A monitor that has no mark yet asks once per query with the
config's `startDate` when it has one, else with Tavily's own default recency.

Imports stay light on purpose: stdlib, `link_search` (stdlib) and `monitoring` / `monitoring_paging`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from typing import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .link_search import TAVILY_ENDPOINT, SearchUnavailable, TavilySearch
from .monitoring import SourceItem, canonical_url
from .monitoring_paging import RateLimited, retry_after_seconds

WEB_SEARCH = "web-search"
TAVILY_SOURCE_URL = "https://api.tavily.com/search"   # the monitor config's sourceUrl (its host is the source type's)
TAVILY_PAGE_LIMIT = 20          # Tavily's own maximum max_results; a full page means there may be more in the window
TOPICS = ("news", "general")
DEFAULT_INTERVAL_SECONDS = 3600
TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 4_000_000
_tavily = TavilySearch()        # reads the key lazily (TAVILY_API_KEY or the SSM parameter in PAPYRUS_TAVILY_KEY_PARAMETER)


def validate_web_config(raw: dict) -> dict:
    queries = raw.get("queries", [])
    if (not isinstance(queries, (list, tuple)) or not all(isinstance(q, str) and q.strip() for q in queries)
            or len({q.strip() for q in queries}) != len(queries)):
        raise ValueError("Config queries must be a list of distinct non-empty strings")
    enabled = raw.get("enabled", True) is not False
    if enabled and not queries:
        raise ValueError("An enabled web-search monitor needs at least one query")
    topic = str(raw.get("topic") or "news")
    if topic not in TOPICS:
        raise ValueError(f"Config topic must be one of {', '.join(TOPICS)}")
    start = raw.get("startDate")
    if start is not None:
        try:
            date.fromisoformat(str(start))
        except ValueError as error:
            raise ValueError("Config startDate must be YYYY-MM-DD") from error
    return {"queries": [q.strip() for q in queries], "topic": topic, "startDate": str(start) if start else None,
            "dedupeAgainstWebMonitors": raw.get("dedupeAgainstWebMonitors") is True}


def url_hash(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:40]


def web_source_id(url: str) -> str:
    return "w" + url_hash(url)[:32]


def tavily_fetch(payload: dict) -> dict:
    """One Tavily search. A 429 raises `RateLimited` (with Retry-After); no key raises `SearchUnavailable`."""
    request = Request(TAVILY_ENDPOINT, data=json.dumps(payload).encode(), method="POST",
                      headers={"Authorization": f"Bearer {_tavily.api_key()}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:   # noqa: S310 - fixed https endpoint
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        if error.code == 429:
            raise RateLimited("Tavily rate limit reached", retry_after_seconds(error.headers.get("Retry-After"))) from error
        raise ValueError(f"Tavily search failed: HTTP {error.code}") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Tavily response exceeds the size bound")
    try:
        parsed = json.loads(body)
    except ValueError as error:
        raise ValueError("Tavily did not return JSON") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("results"), list):
        raise ValueError("Expected a Tavily result list, not an error response")
    return parsed


def _published(value) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            moment = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_results(query: str, results: list) -> list[SourceItem]:
    """One item per result with a usable URL and title; a repeated URL within the answer is one item."""
    items, seen = [], set()
    for row in results:
        if not isinstance(row, dict):
            continue
        try:
            url = canonical_url(str(row.get("url") or ""))
        except ValueError:
            continue
        title = " ".join(str(row.get("title") or "").split())[:1000]
        if not title or url in seen:
            continue
        seen.add(url)
        details = {"query": query, "snippet": " ".join(str(row.get("content") or "").split())[:2000]}
        items.append(SourceItem(web_source_id(url), title, url, url, _published(row.get("published_date")),
                                details=details))
    return items


def _day(moment: float) -> date:
    return datetime.fromtimestamp(moment, timezone.utc).date()


def pass_window(config: dict, watermark: float | None, until: float) -> list[str | None]:
    """The date range one pass reads: from the day before the high-water mark (Tavily's bounds may exclude the
    boundary day; collected URLs are skipped, so the overlap costs nothing) to today. Without a mark: the config's
    `startDate`, else unbounded (Tavily's default recency)."""
    end = _day(until).isoformat()
    if watermark is not None:
        return [(_day(watermark) - timedelta(days=1)).isoformat(), end]
    if config.get("startDate"):
        return [config["startDate"], end]
    return [None, None]


def _split(start: str, end: str) -> tuple[list[str], list[str]]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    middle = first + (last - first) // 2
    return [first.isoformat(), middle.isoformat()], [(middle + timedelta(days=1)).isoformat(), last.isoformat()]


def web_feed(config: dict, now: float, watermark: float | None, fetch: Callable[[dict], dict] | None,
             known: Callable[[SourceItem], bool]) -> dict:
    """All of a monitor's queries as one feed (see `monitoring_paging.read_feed`). The cursor is self-contained
    (JSON): the pass's end time, its date window, the current query with its windows still to read, and the queries
    after it, so a resumed pass needs nothing but the cursor."""
    fetch = fetch or tavily_fetch

    def fetch_page(cursor):
        if cursor is None:
            if not config["queries"]:
                return ("", []), None
            cursor = {"until": now, "win": pass_window(config, watermark, now), "q": config["queries"][0],
                      "rest": config["queries"][1:], "stack": None}
            cursor["stack"] = [cursor["win"]]
        stack, query = [list(w) for w in cursor["stack"]], cursor["q"]
        start, end = stack.pop()
        payload = {"query": query, "topic": config["topic"], "search_depth": "basic", "include_answer": False,
                   "max_results": TAVILY_PAGE_LIMIT}
        if start:
            payload.update(start_date=start, end_date=end)
        results = fetch(payload)["results"]
        if len(results) >= TAVILY_PAGE_LIMIT and start and start < end:   # a full page: there may be more in this window
            older, newer = _split(start, end)
            stack += [older, newer]
        rest = list(cursor["rest"])
        if not stack and rest:
            stack, query, rest = [list(cursor["win"])], rest[0], rest[1:]
        following = {"until": cursor["until"], "win": cursor["win"], "q": query, "rest": rest, "stack": stack} if stack else None
        return (cursor["q"], results), following

    def items(rows):
        query, results = rows
        return parse_results(query, results), False

    return {"key": "web", "fetch_page": fetch_page, "items": items, "stop_at_seen": False, "known": known}
