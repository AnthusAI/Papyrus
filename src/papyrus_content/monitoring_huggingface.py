"""Hugging Face Hub model source for monitors (`sourceType: huggingface-models`).

Reads the public model list (https://huggingface.co/api/models, no key). The Hub cannot filter on date or
on likes, so a monitor's config describes a few *queries* and the reader pages each one until it reaches models
it already collected, goes past the window or the metric's minimum, or the Hub has no more. It has no page or
item limit of its own: it is bound by the collector's time and the Hub's rate limit (monitoring_paging.py):

* one query per watchlisted `authors` entry, newest first;
* one per `search` term, newest first;
* one per `pipelineTags` entry, in the configured `sort` (newest first by default).

A model is kept when it falls inside the window (`createdAt`), matches `pipelineTags` (when given), and is
either from a watchlisted author or reaches `minLikes` / `minDownloads` (when neither is set, every match
is kept). The same rule, as `hf_accepts`, can run again at routing time (docs/monitoring-cloud.md).

The rule may also *exclude* repackaged copies of existing models (quantisations, uncensored variants, wrappers):
`excludeTags`, `excludeBaseRelations` and `excludeIdPatterns` (empty by default). An excluded model is not
collected; the run receipt counts them per reason in `read.skipped`.

Each item carries the Hub's own fields as `details` (model id, author, createdAt, lastModified,
pipeline tag, tags, license, library, likes, downloads, `sha`, and `baseModels`: the models it was built
on, with the relation the Hub records). Only whitelisted fields are kept; model card text never is.

Imports stay light on purpose: stdlib and `papyrus_content.monitoring`.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import time
from typing import Callable
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .monitoring import SourceItem, USER_AGENT, _iso
from .monitoring_paging import RateLimited, Reading as BaseReading, retry_after_seconds

HF_MODELS_URL = "https://huggingface.co/api/models"
HF_HOST = "huggingface.co"
MAX_PAGE_BYTES = 16_000_000
MAX_PAGE_SIZE = 1000
HF_SORTS = ("createdAt", "trendingScore", "likes", "downloads")
#: What a list row must carry. `cardData` is requested for `base_model` and `license`; only those
#: two keys are ever read from it (gated model cards embed pages of license text).
EXPAND = ("author", "createdAt", "lastModified", "pipeline_tag", "tags", "library_name", "likes", "downloads",
          "sha", "cardData", "trendingScore", "gated")
MODEL_ID = re.compile(r"^[A-Za-z0-9_.-]{1,96}(/[A-Za-z0-9_.-]{1,96})?$")
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
TAG = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
SOURCE_ID = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
BASE_RELATIONS = ("finetune", "quantized", "adapter", "merge")
MAX_TAGS, MAX_BASE_MODELS = 80, 10
EXCLUDE_RELATIONS = BASE_RELATIONS + ("declared",)
EXCLUDE_REASONS = ("tag", "baseRelation", "idPattern")
MAX_ID_PATTERNS, MAX_PATTERN_LENGTH = 50, 100


def _parse_time(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _count(value) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


# --- config ----------------------------------------------------------------------------------------

def _string_list(raw, name: str, pattern: re.Pattern, limit: int) -> list[str]:
    values = raw if isinstance(raw, list) else []
    if raw is not None and not isinstance(raw, list):
        raise ValueError(f"Config {name} must be a list")
    out = []
    for value in values:
        if not isinstance(value, str) or not pattern.match(value.strip()):
            raise ValueError(f"Config {name} has an invalid entry: {value!r}")
        if value.strip() not in out:
            out.append(value.strip())
    if len(out) > limit:
        raise ValueError(f"Config {name} may list at most {limit} entries")
    return out


def validate_rule(raw: dict, *, name: str = "Config") -> dict:
    """`pipelineTags`, `authors`, `minLikes`, `minDownloads`: the acceptance rule, shared by the collector and the router."""
    thresholds = {}
    for key in ("minLikes", "minDownloads"):
        if raw.get(key) is not None:
            value = raw[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} {key} must be a whole number of 0 or more")
            thresholds[key] = value
    relations = _string_list(raw.get("excludeBaseRelations"), f"{name} excludeBaseRelations", TAG, len(EXCLUDE_RELATIONS))
    for relation in relations:
        if relation not in EXCLUDE_RELATIONS:
            raise ValueError(f"{name} excludeBaseRelations entries must be among {', '.join(EXCLUDE_RELATIONS)}")
    patterns = _string_list(raw.get("excludeIdPatterns"), f"{name} excludeIdPatterns",
                            re.compile(r"^[^\x00-\x1f]{1,%d}$" % MAX_PATTERN_LENGTH), MAX_ID_PATTERNS)
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(f"{name} excludeIdPatterns has an invalid regular expression {pattern!r}: {error}") from error
    exclusions = {"excludeTags": _string_list(raw.get("excludeTags"), f"{name} excludeTags", TAG, 50),
                  "excludeBaseRelations": relations, "excludeIdPatterns": patterns}
    return {"pipelineTags": _string_list(raw.get("pipelineTags"), f"{name} pipelineTags", TAG, 20),
            "authors": _string_list(raw.get("authors"), f"{name} authors", NAME, 200), **thresholds,
            **{key: value for key, value in exclusions.items() if value}}   # absent when empty: rules keep their old shape


def validate_hf_config(raw: dict) -> dict:
    """The huggingface-models part of a monitor CONFIG (the common fields are validated by the caller).
    `pageSize` is the Hub API's page size, not a total: the reader pages until it has everything."""
    source = urlsplit(str(raw.get("sourceUrl") or ""))
    if source.path != "/api/models":
        raise ValueError(f"Config sourceUrl must be {HF_MODELS_URL} for a huggingface-models monitor")
    rule = validate_rule(raw)
    search = _string_list(raw.get("search"), "Config search", re.compile(r"^[^\x00-\x1f]{1,64}$"), 10)
    if not (rule["pipelineTags"] or rule["authors"] or search):
        raise ValueError("Config needs at least one of pipelineTags, authors or search")
    sort = str(raw.get("sort") or "createdAt")
    if sort not in HF_SORTS:
        raise ValueError(f"Config sort must be one of {', '.join(HF_SORTS)}")
    lookback, page_size = int(raw.get("lookbackDays", 7)), int(raw.get("pageSize", 200))
    if not 1 <= lookback <= 366:
        raise ValueError("Config lookbackDays must be between 1 and 366")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"Config pageSize must be between 1 and {MAX_PAGE_SIZE}")
    return {**rule, "search": search, "sort": sort, "lookbackDays": lookback, "pageSize": page_size}


def hf_exclusion(details: dict, rule: dict) -> str | None:
    """Why the rule's exclusions drop this model (`tag`, `baseRelation` or `idPattern`), or None."""
    excluded_tags = {t.lower() for t in rule.get("excludeTags") or []}
    if excluded_tags and any(str(t).lower() in excluded_tags for t in details.get("tags") or []):
        return "tag"
    relations = set(rule.get("excludeBaseRelations") or [])
    if relations and any(b.get("relation") in relations for b in details.get("baseModels") or []):
        return "baseRelation"
    model_id = str(details.get("modelId") or "")
    if any(re.search(p, model_id, re.IGNORECASE) for p in rule.get("excludeIdPatterns") or []):
        return "idPattern"
    return None


def hf_accepts(details: dict, rule: dict) -> bool:
    """Not excluded, and passes the inclusion rule (`hf_includes`)."""
    return hf_exclusion(details, rule) is None and hf_includes(details, rule)


def hf_includes(details: dict, rule: dict) -> bool:
    """Tag filter first, then: a watchlisted author, or a threshold reached, or no thresholds at all."""
    tags = rule.get("pipelineTags") or []
    if tags and details.get("pipelineTag") not in tags:
        return False
    if str(details.get("author") or "").lower() in {a.lower() for a in rule.get("authors") or []}:
        return True
    min_likes, min_downloads = rule.get("minLikes"), rule.get("minDownloads")
    if min_likes is None and min_downloads is None:
        return True
    return ((min_likes is not None and _count(details.get("likes")) >= min_likes)
            or (min_downloads is not None and _count(details.get("downloads")) >= min_downloads))


# --- one model -------------------------------------------------------------------------------------

def hf_source_id(model_id: str) -> str:
    """`org/name` as an id safe for table keys and Cyclotron item ids; hashed when it had to change."""
    base = model_id.replace("/", "--")
    if SOURCE_ID.match(base):
        return base
    import hashlib
    safe = re.sub(r"[^0-9A-Za-z_-]", "_", base)[:55]
    return f"{safe}-{hashlib.sha256(model_id.encode()).hexdigest()[:8]}"


def base_models(tags: list[str], card_base) -> list[dict]:
    """Models this one was built on: `{"modelId", "relation"}` from the Hub's `base_model:*` tags
    (relation finetune, quantized, adapter or merge), then any `cardData.base_model` they do not already name
    (relation `declared`)."""
    found: dict[str, str] = {}
    declared = [card_base] if not isinstance(card_base, list) else list(card_base)
    for tag in tags:
        if tag.startswith("base_model:"):
            relation, _, rest = tag[len("base_model:"):].partition(":")
            if relation in BASE_RELATIONS and rest:
                found.setdefault(rest, relation)
            else:
                declared.append(tag[len("base_model:"):])   # the bare tag the Hub adds beside a typed one
    for model in declared:
        if isinstance(model, str):
            found.setdefault(model.strip(), "declared")
    found = {model: relation for model, relation in found.items() if MODEL_ID.match(model)}
    return [{"modelId": model, "relation": relation} for model, relation in list(found.items())[:MAX_BASE_MODELS]]


def hf_details(row: dict) -> dict | None:
    """The structured fields the knowledge map needs, or None for a row that is not a usable model."""
    model_id = row.get("id") or row.get("modelId")
    created = _parse_time(row.get("createdAt"))
    if not isinstance(model_id, str) or not MODEL_ID.match(model_id) or created is None:
        return None
    all_tags = [t for t in row.get("tags") or [] if isinstance(t, str) and 0 < len(t) <= 120]
    tags = all_tags[:MAX_TAGS]   # base_model relations are read from every tag: the typed one can sit past the 80th
    card = row.get("cardData") if isinstance(row.get("cardData"), dict) else {}
    license_id = next((t[len("license:"):] for t in tags if t.startswith("license:")), None)
    if license_id is None and isinstance(card.get("license"), str):
        license_id = card["license"]
    details = {"modelId": model_id, "author": str(row.get("author") or model_id.partition("/")[0]),
               "createdAt": str(row["createdAt"]), "lastModified": str(row["lastModified"]) if row.get("lastModified") else None,
               "pipelineTag": row.get("pipeline_tag") if isinstance(row.get("pipeline_tag"), str) else None,
               "tags": tags, "license": license_id,
               "libraryName": row.get("library_name") if isinstance(row.get("library_name"), str) else None,
               "likes": _count(row.get("likes")), "downloads": _count(row.get("downloads")),
               "sha": row.get("sha") if isinstance(row.get("sha"), str) else None,
               "baseModels": base_models(all_tags, card.get("base_model"))}
    if row.get("trendingScore") is not None:
        details["trendingScore"] = _count(row["trendingScore"])
    if row.get("gated"):
        details["gated"] = str(row["gated"])
    return {k: v for k, v in details.items() if v is not None}


def hf_item(details: dict) -> SourceItem:
    model_id = details["modelId"]
    url = f"https://{HF_HOST}/{model_id}"
    title = f"{model_id}: {details['pipelineTag']} model" if details.get("pipelineTag") else model_id
    return SourceItem(hf_source_id(model_id), title[:1000], url, url, details["createdAt"], details=details)


def parse_hf_models(body: bytes) -> list[dict]:
    """The usable rows of one list response, as `details`. An error object is refused."""
    import json
    if len(body) > MAX_PAGE_BYTES:
        raise ValueError("Hugging Face model list response is oversized")
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise ValueError("Hugging Face model list did not return JSON") from error
    if not isinstance(payload, list):
        raise ValueError("Expected a Hugging Face model list, not an error response")
    return [d for d in (hf_details(row) for row in payload if isinstance(row, dict)) if d]


# --- the Hub ---------------------------------------------------------------------------------------

def check_hub_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != HF_HOST or parts.username or parts.password or parts.path != "/api/models":
        raise ValueError("Only https://huggingface.co/api/models URLs are accepted")
    return url


def fetch_hf_page(url: str) -> tuple[bytes, str | None]:
    """One list page and the `next` URL from its Link header (a cursor). Paced; a 429 raises RateLimited
    carrying the Hub's `Retry-After`."""
    check_hub_url(url)
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
        raise ValueError("Hugging Face model list exceeds the response size bound")
    match = re.search(r'<([^>]+)>;\s*rel="next"', link)
    return body, check_hub_url(match.group(1)) if match else None


def list_url(base: str, query: dict, page_size: int) -> str:
    params = [("limit", page_size), ("direction", -1), ("sort", query["sort"])]
    params += [(key, query[key]) for key in ("author", "search", "pipeline_tag") if query.get(key)]
    params += [("expand", field) for field in EXPAND]
    return f"{check_hub_url(base)}?{urlencode(params)}"


def plan_queries(config: dict, *, sorts: tuple[str, ...] | None = None) -> list[dict]:
    """Author and search queries are always newest first (they are small); each pipeline tag runs once per sort."""
    queries = [{"key": f"author:{a}", "author": a, "sort": "createdAt"} for a in config["authors"]]
    queries += [{"key": f"search:{t}", "search": t, "sort": "createdAt"} for t in config["search"]]
    for tag in config["pipelineTags"]:
        queries += [{"key": f"tag:{tag}:{sort}", "pipeline_tag": tag, "sort": sort} for sort in sorts or (config["sort"],)]
    return queries


class Reading(BaseReading):
    """The paging totals of one read, plus the models its rule excluded."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.excluded: dict[str, str] = {}   # model id -> reason; a model seen by several queries counts once

    def skipped(self) -> dict[str, int]:
        """Models that would have been collected but for an exclusion, per reason (zero reasons left out)."""
        counts = {reason: sum(1 for r in self.excluded.values() if r == reason) for reason in EXCLUDE_REASONS}
        return {reason: n for reason, n in counts.items() if n}


def metric_floor(config: dict, sort: str) -> int | None:
    """Where a query sorted by a metric ends: under the configured minimum (at least 1, so the Hub's long tail of
    models nobody has liked, downloaded or trended is not paged through). None for a newest-first query."""
    if sort == "createdAt":
        return None
    minimum = {"likes": config.get("minLikes"), "downloads": config.get("minDownloads")}.get(sort)
    return max(int(minimum or 0), 1)


def page_reader(config: dict, query: dict, since: datetime, fetch: Callable, reading: Reading):
    """The two halves of reading one query page by page: `fetch_page(cursor)` (cursor None starts the query)
    and `screen(rows)`, which returns the accepted models inside the window and whether the query is over
    (a newest-first query once it passes the window, a metric-sorted one once the metric is under its floor)."""
    first = list_url(config["sourceUrl"], query, config["pageSize"])

    def fetch_page(cursor):
        body, following = fetch(cursor or first)
        return parse_hf_models(body), following

    def screen(rows):
        accepted = []
        for d in rows:
            if _parse_time(d["createdAt"]) >= since and hf_includes(d, config):
                reason = hf_exclusion(d, config)
                if reason:
                    reading.excluded.setdefault(d["modelId"], reason)
                else:
                    accepted.append(d)
        last, floor = (rows[-1] if rows else None), metric_floor(config, query["sort"])
        over = last is None or (_parse_time(last["createdAt"]) < since if floor is None else _count(last.get(query["sort"])) < floor)
        return accepted, over

    return fetch_page, screen


def read_query(config: dict, query: dict, since: datetime, fetch: Callable, reading: Reading, *,
               start_url: str | None = None, max_pages: int | None = None) -> dict:
    """Page one query from `start_url` (None: the start), at most `max_pages` pages when given (a checkpoint
    grain for the backfill, not a total). Returns `items` (details dicts, accepted, inside the window), `next`
    (the cursor URL to continue from, None at the end) and `done`. A 429 is waited out (`Reading.rate_limited`)."""
    fetch_page, screen = page_reader(config, query, since, fetch, reading)
    cursor, items, pages, done = start_url, [], 0, False
    while (cursor is not None or pages == 0) and (max_pages is None or pages < max_pages):
        if not reading.may_request():
            break
        try:
            rows, following = fetch_page(cursor)
        except RateLimited as error:
            if reading.rate_limited(error):
                continue
            break
        reading.succeeded()
        reading.requests += 1
        pages += 1
        accepted, over = screen(rows)
        items.extend(accepted)
        cursor = None if over else following
        done = over or following is None
        if done:
            break
    return {"items": items, "next": cursor, "done": done, "pages": pages}


def hf_window_start(config: dict, now: float) -> datetime:
    return datetime.fromtimestamp(now - config["lookbackDays"] * 86400, timezone.utc)


def hf_feeds(config: dict, now: float, fetch: Callable | None, reading: Reading) -> list[dict]:
    """The live read as feeds for `monitoring_paging.read_feed`: one per query over the lookback window.
    Each has a `key`, `fetch_page(cursor)`, `items(rows) -> (SourceItem list, over)` and `stop_at_seen`
    (true for a newest-first query; a metric-sorted one has no high-water mark and reads to its floor)."""
    fetch, since = fetch or fetch_hf_page, hf_window_start(config, now)
    feeds = []
    for query in plan_queries(config):
        fetch_page, screen = page_reader(config, query, since, fetch, reading)

        def items(rows, screen=screen):
            accepted, over = screen(rows)
            return [hf_item(d) for d in accepted], over

        feeds.append({"key": query["key"], "fetch_page": fetch_page, "items": items,
                      "stop_at_seen": query["sort"] == "createdAt", "labelled": True})
    return feeds
