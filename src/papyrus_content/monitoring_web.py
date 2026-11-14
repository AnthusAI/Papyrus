"""Web-search monitors: a monitor's queries asked of the configured web-search chain (Tavily unless `WEB_SEARCH_PROVIDERS` or the
monitor's own `searchProviders` says otherwise; see `web_search`), newest news since the monitor's last complete pass.

Tavily's search has no result offset: one request returns at most `TAVILY_PAGE_LIMIT` (its own maximum) results.
So the way to read *everything* it has is to narrow the date range: a window whose answer fills the page is split
in two (`start_date` / `end_date`, a day at a time) and each half is asked again, down to a single day. Nothing here
caps a pass; the real bounds are the Lambda's time (the pass hands back resume cursors) and Tavily's rate limit
(a 429 is waited out for its Retry-After, see `monitoring_paging`).

Recency comes from each query's own high-water mark (`highWater` on its `QUERY#` record: the start of the last pass that
read it to its end), never from a fixed window. A query that has no mark yet asks once with the config's `startDate`
when it has one, else with Tavily's own default recency.

Only Tavily (and Perplexity) can bound a search by date. When another provider answers, the window is asked once and never split
(`dateBounded` is false in its answer): splitting would only repeat the same results.

Imports stay light on purpose: stdlib, `web_search` (stdlib) and `monitoring` / `monitoring_paging`.
"""
from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import re
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .monitoring import SourceItem, canonical_url
from .monitoring_candidates import url_hash
from .monitoring_paging import RateLimited
from .web_search import UNAVAILABLE, ProviderFailure, SearchChain, SearchChainFailed, SearchError, SearchRequest, parse_names

WEB_SEARCH = "web-search"
TAVILY_SOURCE_URL = "https://api.tavily.com/search"   # the monitor config's sourceUrl (its host is the source type's)
TAVILY_PAGE_LIMIT = 20          # Tavily's own maximum max_results; a full page means there may be more in the window
TOPICS = ("news", "general")
DEFAULT_INTERVAL_SECONDS = 3600
TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 4_000_000


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
            "candidateGroup": group.strip() if group else None,
            "searchProviders": search_providers(raw.get("searchProviders")),
            "excludeDomains": domain_list(raw.get("excludeDomains"), "Config excludeDomains")}


def search_providers(value) -> list[str]:
    """The monitor's own provider chain (`searchProviders`: a list or a comma string), or [] to use the deployment's."""
    if value is None or value == "" or value == []:
        return []
    if not isinstance(value, (str, list, tuple)):
        raise ValueError("Config searchProviders must be a list or a comma separated string of provider names")
    names = parse_names(value, strict=True)
    if not names:
        raise ValueError("Config searchProviders must name at least one provider")
    return names


def domain_list(value, label: str) -> list[str]:
    """A list of bare domains (`example.org`, no scheme or path) for the providers' include / exclude filters."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be a list of domains")
    domains = []
    for entry in value:
        domain = str(entry or "").strip().lower()
        if not domain or "/" in domain or ":" in domain or " " in domain or "." not in domain:
            raise ValueError(f"{label} entries must be bare domains such as example.org, not {entry!r}")
        if domain not in domains:
            domains.append(domain)
    return domains


def web_source_id(url: str) -> str:
    return "w" + url_hash(url)[:32]


def search_fetch(config: dict, chain: SearchChain | None = None) -> Callable[[dict], dict]:
    """The monitor's search call: one request through its provider chain, answered in the Tavily result shape the feed reads
    (`results`, `usage`) plus `provider`, `skipped` (why earlier providers were passed over) and `dateBounded`. A 429 that every
    provider answered raises `RateLimited` (with the longest Retry-After), so the pass waits as it always has; no usable key
    raises `SearchUnavailable`; any other failure is a `ValueError` naming each provider's failure kind."""
    chain = chain or SearchChain(config.get("searchProviders") or None, remember_refusals=True)

    def fetch(payload: dict) -> dict:
        request = SearchRequest(payload["query"], limit=int(payload.get("max_results") or TAVILY_PAGE_LIMIT), topic=payload.get("topic"),
                                start_date=payload.get("start_date"), end_date=payload.get("end_date"),
                                include_domains=tuple(payload.get("include_domains") or ()),
                                exclude_domains=tuple(payload.get("exclude_domains") or ()))
        try:
            response = chain.run(request)
        except SearchChainFailed as error:
            if error.rate_limited:
                limited = RateLimited(str(error), error.retry_after)
                limited.skipped = [skip.as_record() for skip in error.skipped]
                raise limited from None
            failure = ValueError(f"Web search failed: {error}")
            failure.skipped = [skip.as_record() for skip in error.skipped]   # the feed counts what each provider answered
            raise failure from None
        except ProviderFailure as error:   # pragma: no cover - the chain wraps these
            raise ValueError(f"Web search failed: {error}") from None
        return {"results": [{"url": h.url, "title": h.title, "content": h.snippet, "score": h.score, "published_date": h.published}
                            for h in response.hits],
                "usage": response.usage, "provider": response.provider, "skipped": response.skipped_records(),
                "dateBounded": response.date_bounded}

    return fetch


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


ARXIV_API = "https://export.arxiv.org/api/query"
_ARXIV_PATH = re.compile(r"^/(?:abs|pdf|html)/([a-z\-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?$")
_ATOM = "{http://www.w3.org/2005/Atom}"


def arxiv_paper_id(url: str) -> str | None:
    parts = urlsplit(url)
    if not (parts.hostname or "").lower().endswith("arxiv.org"):
        return None
    match = _ARXIV_PATH.match(parts.path)
    return match.group(1) if match else None


def arxiv_titles(ids: list[str]) -> dict[str, str]:
    """Paper titles from arXiv's own API, by id, in one request. Empty on any failure: the search engine's title then stands."""
    if not ids:
        return {}
    request = Request(f"{ARXIV_API}?{urlencode({'id_list': ','.join(ids), 'max_results': len(ids)})}",
                      headers={"User-Agent": "papyrus-monitoring"})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:   # noqa: S310 - fixed https endpoint
            feed = ElementTree.fromstring(response.read(MAX_RESPONSE_BYTES))
    except (HTTPError, URLError, TimeoutError, ElementTree.ParseError, OSError):
        return {}
    titles = {}
    for entry in feed.findall(f"{_ATOM}entry"):
        found = arxiv_paper_id(entry.findtext(f"{_ATOM}id") or "")
        title = " ".join((entry.findtext(f"{_ATOM}title") or "").split())
        if found and title:
            titles[found] = title[:1000]
    return titles


def with_paper_titles(items: list[SourceItem], lookup: Callable[[list[str]], dict[str, str]]) -> list[SourceItem]:
    """arXiv's HTML pages are titled after their first section ("1 Introduction"), so the search engine reports that. An arXiv
    result takes the paper's own title from arXiv instead."""
    ids = {item.canonical_url: arxiv_paper_id(item.canonical_url) for item in items}
    titles = lookup(sorted({paper for paper in ids.values() if paper}))
    return [dataclasses.replace(item, title=titles[ids[item.canonical_url]]) if titles.get(ids[item.canonical_url] or "") else item
            for item in items]


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
                 approved_by: str | None = None, exclude_domains=None, include_domains=None) -> dict:
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
            **({"approvedBy": approved_by, "approvedAt": now_iso} if approved_by else {}),
            **({"excludeDomains": domain_list(exclude_domains, "Query excludeDomains")} if exclude_domains else {}),
            **({"includeDomains": domain_list(include_domains, "Query includeDomains")} if include_domains else {})}


def searchable(record: dict) -> bool:
    """Only an approved, active query is searched."""
    return record.get("status") == "active" and bool(record.get("approvedBy")) and bool(str(record.get("text") or "").strip())


def storable_row(row: dict) -> dict:
    """A search result as the cursor stores it in DynamoDB: no floats (the score becomes integer basis points)."""
    score = row.get("score")
    kept = {k: row.get(k) for k in ("url", "title", "content", "published_date") if row.get(k) is not None}
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        kept["scoreBp"] = int(round(float(score) * 10000))
    return kept


def stored_row(row: dict) -> dict:
    return {**{k: v for k, v in row.items() if k != "scoreBp"}, **({"score": row["scoreBp"] / 10000} if "scoreBp" in row else {})}


def web_feed(config: dict, queries: list[dict], now: float, fetch: Callable[[dict], dict] | None,
             known: Callable[[SourceItem], bool], stats: dict,
             paper_titles: Callable[[list[str]], dict[str, str]] = arxiv_titles) -> dict:
    """All of a monitor's searchable queries as one feed (see `monitoring_paging.read_feed`). The cursor is self-contained
    (JSON): the pass's end time, the current query with its date window and the windows still to read, and the queries after
    it (each with its window), so a resumed pass needs nothing but the cursor. `stats[queryId]` collects what each query's
    QueryRun records: requests, results returned, credits, the windows asked."""
    fetch = fetch or search_fetch(config)

    def plan(record: dict) -> dict:
        excluded = domain_list([*(config.get("excludeDomains") or []), *(record.get("excludeDomains") or [])], "excludeDomains")
        included = domain_list(record.get("includeDomains"), "Query includeDomains")
        return {"id": record["id"], "text": record["text"], "win": query_window(config, record.get("highWater"), now),
                **({"exclude": excluded} if excluded else {}), **({"include": included} if included else {})}

    spent = {"requests": 0, "providers": {}, "failures": {}}   # this pass's paid searches; the cursor carries them across runs
    loaded, initial, last, base = [False], {}, {"bounded": True}, {"requests": 0, "providers": {}, "failures": {}}

    def snapshot() -> dict:
        return {"requests": spent["requests"], "providers": dict(spent["providers"]), "failures": dict(spent["failures"])}

    def note_failures(skips):
        for skip in skips or []:
            if skip.get("kind") != UNAVAILABLE:   # a provider that was reached and refused or failed (a missing key is not a failure)
                label = ":".join(str(x) for x in (skip["provider"], skip["kind"], skip.get("status")) if x)
                spent["failures"][label] = spent["failures"].get(label, 0) + 1

    def fetch_page(cursor):
        if cursor is None:
            if not queries:
                return ("", "", []), None
            plans = [plan(r) for r in queries]
            cursor = {"until": int(now), "all": [p["id"] for p in plans], "q": plans[0], "rest": plans[1:],
                      "stack": [plans[0]["win"]], "asked": [], "spent": snapshot()}
            initial.update(cursor)
        if not loaded[0]:
            loaded[0] = True
            earlier = cursor.get("spent") or {}
            spent.update(requests=earlier.get("requests", 0), providers=dict(earlier.get("providers") or {}),
                         failures=dict(earlier.get("failures") or {}))
            base.update(snapshot())
        stack, current = [list(w) for w in cursor["stack"]], cursor["q"]
        asked = [list(a) for a in cursor.get("asked") or []]
        start, end = stack.pop()
        payload = {"query": current["text"], "topic": config["topic"], "search_depth": "basic", "include_answer": False,
                   "max_results": TAVILY_PAGE_LIMIT}
        if current.get("exclude"):
            payload["exclude_domains"] = current["exclude"]
        if current.get("include"):
            payload["include_domains"] = current["include"]
        if start:   # Tavily refuses a range that starts and ends on one day, so a one-day window also asks the day before
            first = (date.fromisoformat(start) - timedelta(days=1)).isoformat() if start == end else start
            payload.update(start_date=first, end_date=end)
        key = [current["id"], payload.get("start_date"), payload.get("end_date")]
        if cursor.get("page") is not None:   # paid for by an earlier run that could not write it: read it, do not ask again
            results, last["bounded"] = [stored_row(row) for row in cursor["page"]], cursor.get("bounded", True)
            asked.append(key)
        else:
            if key in asked:   # the same search (query and dates) was already paid for in this pass: its answer is already read
                results, last["bounded"] = [], True
            else:
                try:
                    response = fetch(payload)
                except Exception as error:
                    note_failures(getattr(error, "skipped", None))
                    raise
                results, last["bounded"] = response["results"], response.get("dateBounded", True)
                asked.append(key)
                used = stats.setdefault(current["id"], {"requests": 0, "resultsReturned": 0, "credits": 0, "windows": []})
                used["requests"] += 1
                used["resultsReturned"] += len(results)
                credits = (response.get("usage") or {}).get("credits")
                used["credits"] += int(round(credits)) if isinstance(credits, (int, float)) and not isinstance(credits, bool) else 1
                used["windows"].append([start, end])
                spent["requests"] += 1
                provider = response.get("provider")
                if provider:
                    used.setdefault("providers", {}).setdefault(provider, 0)
                    used["providers"][provider] += 1
                    spent["providers"][provider] = spent["providers"].get(provider, 0) + 1
                for skip in response.get("skipped") or []:
                    if skip["message"] not in used.setdefault("skipped", []):
                        used["skipped"].append(skip["message"])
                note_failures(response.get("skipped"))
        if len(results) >= TAVILY_PAGE_LIMIT and start and start < end and last["bounded"]:   # a full page: there may be more here
            older, newer = _split(start, end)
            stack += [older, newer]
        rest = list(cursor["rest"])
        if not stack and rest:
            current, rest = rest[0], rest[1:]
            stack = [list(current["win"])]
        following = ({"until": cursor["until"], "all": cursor["all"], "q": current, "rest": rest, "stack": stack, "asked": asked,
                      "spent": snapshot()} if stack else None)
        return (cursor["q"]["id"], cursor["q"]["text"], results), following

    def paid() -> dict:
        """What the pass paid for in all: `pass` over every run so far, `run` since this run took the cursor."""
        def minus(now_, before):
            return {"requests": now_["requests"] - before["requests"],
                    "providers": {k: n - before["providers"].get(k, 0) for k, n in now_["providers"].items() if n - before["providers"].get(k, 0)},
                    "failures": {k: n - before["failures"].get(k, 0) for k, n in now_["failures"].items() if n - before["failures"].get(k, 0)}}
        return {"run": minus(snapshot(), base), "pass": snapshot()}

    def keep(cursor, rows):
        """The cursor to resume with when a page could not be written in time: the same page with its paid answer attached, so
        the next run reads it instead of asking again."""
        return {**(cursor if cursor is not None else initial), "page": [storable_row(row) for row in rows[2] if isinstance(row, dict)],
                "bounded": last["bounded"], "spent": snapshot()}

    def items(rows):
        query_id, text, results = rows
        return with_paper_titles(parse_results(text, results, query_id), paper_titles), False

    return {"key": "web", "fetch_page": fetch_page, "items": items, "stop_at_seen": False, "known": known, "keep": keep,
            "spent": paid}


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
