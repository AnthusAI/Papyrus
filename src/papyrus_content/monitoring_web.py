"""Web-search monitors: a monitor's queries asked of Tavily, newest news since the monitor's last complete pass.

Tavily's search has no result offset: one request returns at most `TAVILY_PAGE_LIMIT` (its own maximum) results.
So the way to read *everything* it has is to narrow the date range: a window whose answer fills the page is split
in two (`start_date` / `end_date`, a day at a time) and each half is asked again, down to a single day. Nothing here
caps a pass; the real bounds are the Lambda's time (the pass hands back resume cursors) and Tavily's rate limit
(a 429 is waited out for its Retry-After, see `monitoring_paging`).

Recency comes from each query's own high-water mark (`highWater` on its `QUERY#` record: the start of the last pass that
read it to its end), never from a fixed window. A query that has no mark yet asks once with the config's `startDate`
when it has one, else with Tavily's own default recency.

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
from .monitoring_candidates import url_hash
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
    """The monitor's CONFIG. Its queries are `QUERY#` records (docs/search-monitors.md), not part of the config."""
    topic = str(raw.get("topic") or "news")
    if topic not in TOPICS:
        raise ValueError(f"Config topic must be one of {', '.join(TOPICS)}")
    start = raw.get("startDate")
    if start is not None:
        try:
            date.fromisoformat(str(start))
        except ValueError as error:
            raise ValueError("Config startDate must be YYYY-MM-DD") from error
    group = raw.get("candidateGroup")
    if group is not None and (not isinstance(group, str) or not group.strip()):
        raise ValueError("Config candidateGroup must be a non-empty string")
    return {"topic": topic, "startDate": str(start) if start else None,
            "candidateGroup": group.strip() if group else None}


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


def parse_results(query: str, results: list, query_id: str = "") -> list[SourceItem]:
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
        if query_id:
            details["queryId"] = query_id
        score = row.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            details["tavilyScoreBp"] = int(round(float(score) * 10000))   # integer basis points: DynamoDB takes no floats
        items.append(SourceItem(web_source_id(url), title, url, url, _published(row.get("published_date")),
                                details=details))
    return items


def _day(moment: float) -> date:
    return datetime.fromtimestamp(moment, timezone.utc).date()


def query_window(config: dict, high_water: int | None, until: float) -> list[str | None]:
    """The date range one pass reads for a query: from the day before its high-water mark (Tavily's bounds may exclude the
    boundary day; collected URLs are skipped, so the overlap costs nothing) to today. Without a mark: the config's
    `startDate`, else unbounded (Tavily's default recency)."""
    end = _day(until).isoformat()
    if high_water is not None:
        return [(_day(high_water) - timedelta(days=1)).isoformat(), end]
    if config.get("startDate"):
        return [config["startDate"], end]
    return [None, None]


def _split(start: str, end: str) -> tuple[list[str], list[str]]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    middle = first + (last - first) // 2
    return [first.isoformat(), middle.isoformat()], [(middle + timedelta(days=1)).isoformat(), last.isoformat()]


def query_record(monitor_id: str, text: str, rationale: str, *, origin: str, created_by: str, now_iso: str,
                 approved_by: str | None = None) -> dict:
    """A `QUERY#` record (docs/search-monitors.md). The id is stable for a monitor and text, so seeding twice is one record."""
    if origin not in ("drafted", "editor"):
        raise ValueError("Query origin must be drafted or editor")
    text = " ".join(text.split())
    if not text:
        raise ValueError("A query needs text")
    query_id = "q" + hashlib.sha256(f"{monitor_id}\n{text}".encode()).hexdigest()[:12]
    return {"pk": f"MONITOR#{monitor_id}", "sk": f"QUERY#{query_id}", "id": query_id, "text": text, "rationale": rationale.strip(),
            "origin": origin, "createdBy": created_by, "createdAt": now_iso, "status": "active",
            "history": [{"at": now_iso, "by": created_by, "change": "created", "after": text, "reason": rationale.strip()}],
            **({"approvedBy": approved_by, "approvedAt": now_iso} if approved_by else {})}


def searchable(record: dict) -> bool:
    """Only an approved, active query is searched."""
    return record.get("status") == "active" and bool(record.get("approvedBy")) and bool(str(record.get("text") or "").strip())


def web_feed(config: dict, queries: list[dict], now: float, fetch: Callable[[dict], dict] | None,
             known: Callable[[SourceItem], bool], stats: dict) -> dict:
    """All of a monitor's searchable queries as one feed (see `monitoring_paging.read_feed`). The cursor is self-contained
    (JSON): the pass's end time, the current query with its date window and the windows still to read, and the queries after
    it (each with its window), so a resumed pass needs nothing but the cursor. `stats[queryId]` collects what each query's
    QueryRun records: requests, results returned, credits, the windows asked."""
    fetch = fetch or tavily_fetch

    def plan(record: dict) -> dict:
        return {"id": record["id"], "text": record["text"], "win": query_window(config, record.get("highWater"), now)}

    def fetch_page(cursor):
        if cursor is None:
            if not queries:
                return ("", "", []), None
            plans = [plan(r) for r in queries]
            cursor = {"until": int(now), "all": [p["id"] for p in plans], "q": plans[0], "rest": plans[1:],
                      "stack": [plans[0]["win"]]}
        stack, current = [list(w) for w in cursor["stack"]], cursor["q"]
        start, end = stack.pop()
        payload = {"query": current["text"], "topic": config["topic"], "search_depth": "basic", "include_answer": False,
                   "max_results": TAVILY_PAGE_LIMIT}
        if start:
            payload.update(start_date=start, end_date=end)
        response = fetch(payload)
        results = response["results"]
        used = stats.setdefault(current["id"], {"requests": 0, "resultsReturned": 0, "credits": 0, "windows": []})
        used["requests"] += 1
        used["resultsReturned"] += len(results)
        credits = (response.get("usage") or {}).get("credits")
        used["credits"] += int(round(credits)) if isinstance(credits, (int, float)) and not isinstance(credits, bool) else 1
        used["windows"].append([start, end])
        if len(results) >= TAVILY_PAGE_LIMIT and start and start < end:   # a full page: there may be more in this window
            older, newer = _split(start, end)
            stack += [older, newer]
        rest = list(cursor["rest"])
        if not stack and rest:
            current, rest = rest[0], rest[1:]
            stack = [list(current["win"])]
        following = ({"until": cursor["until"], "all": cursor["all"], "q": current, "rest": rest, "stack": stack}
                     if stack else None)
        return (cursor["q"]["id"], cursor["q"]["text"], results), following

    def items(rows):
        query_id, text, results = rows
        return parse_results(text, results, query_id), False

    return {"key": "web", "fetch_page": fetch_page, "items": items, "stop_at_seen": False, "known": known}


def finished_query_ids(queries: list[dict], carry: list, resume: list) -> list[str]:
    """Which queries the pass read to their end. The pass planned the queries named in its cursor (`all`), or, if it began
    fresh, the ones it was given: a query added meanwhile is not finished. With a cursor left to resume, the unfinished query
    and those after it (named in the cursor) are not finished."""
    cursor = (carry or resume or [None])[0]
    planned = list(cursor["all"]) if cursor else [q["id"] for q in queries]
    if not carry:
        return planned
    unfinished = {cursor["q"]["id"], *(q["id"] for q in cursor["rest"])}
    return [query_id for query_id in planned if query_id not in unfinished]


def pass_started_at(resume: list, now: float) -> int:
    """When the pass being read began: the resumed cursor's `until`, else now."""
    return int(resume[0]["until"]) if resume else int(now)
