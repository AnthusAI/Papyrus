"""Cloud monitor collector: one due collection per invocation, state in DynamoDB.

Collect, dedupe, checkpoint and record receipts only. This stage has no
publication, AppSync or provider access; discoveries carry `routing: collected`
for a later router (docs/monitoring-cloud.md). It reuses the feed parsing,
fingerprints and event ids of the local SQLite collector (`monitoring.collect`).

Imports stay light on purpose: stdlib, boto3 (provided by the Lambda runtime)
and `papyrus_content.monitoring`.
"""
from __future__ import annotations

from decimal import Decimal
import json
import os
import time
import uuid
from typing import Callable
from urllib.parse import urlsplit

from .monitoring import (SOURCE_TYPES, _digest, _iso, fetch_hn_feed, fetch_ttab_decisions, parse_hn_feed,
                         parse_ttab_page, ttab_search_body)
from .monitoring_huggingface import Reading, hf_feeds, hf_window_start, validate_hf_config
from .monitoring_paging import READ_BUDGET_SECONDS, Page, read_feed
from .monitoring_web import WEB_SEARCH, DEFAULT_INTERVAL_SECONDS as WEB_INTERVAL_SECONDS, TAVILY_SOURCE_URL, url_hash, validate_web_config, web_feed

LEASE_SECONDS = 150          # longer than the 120 s Lambda timeout (LAMBDA_TIMEOUT_SECONDS); a crashed run's lease expires
DUE_SLACK_SECONDS = 60       # scheduler jitter must not skip a whole interval
RECEIPT_TTL_SECONDS = 30 * 86400
MAX_ERRORS_RECORDED = 10
ROUTING_COLLECTED = "collected"
TTAB_PAGE_SIZE = 100         # the Reading Room API's page size when the config names none; not a total
#: Config fields that capped how much a pass read. The collector pages until it meets items it has collected or the
#: source has no more, so a stored config that still has them loads and they are ignored (one log line).
RETIRED_CONFIG_FIELDS = ("limit", "maxItems", "pagesPerQuery")


class ConditionFailed(Exception):
    """A conditional write lost to an existing item."""


def pk(monitor_id: str) -> str:
    return f"MONITOR#{monitor_id}"


class DynamoStore:
    """Key layout (single table, keys `pk` / `sk`, sparse GSI `routing`):

    pk=MONITOR#<id>  sk=CONFIG                  config as data
                     sk=STATE                   nextDueAt, lastRunId, lastStatus
                     sk=LOCK                    owner, expiresAt (lease)
                     sk=ITEM#<sourceId>         current fingerprint + revision
                     sk=DISC#<sourceId>#<rev>   one discovery per revision; routing field
                     sk=RUN#<startedAt>#<runId> receipt, expires via `ttl`
    GSI `routing` (gsi1pk=ROUTING#<id>#collected, gsi1sk=<observedAt>#...) lists
    discoveries still waiting for the router; the router removes both keys.
    """

    def __init__(self, table):
        self.table = table

    @staticmethod
    def _clean(value):
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else float(value)
        if isinstance(value, dict):
            return {k: DynamoStore._clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [DynamoStore._clean(v) for v in value]
        return value

    def _get(self, monitor_id, sk):
        item = self.table.get_item(Key={"pk": pk(monitor_id), "sk": sk}, ConsistentRead=True).get("Item")
        return self._clean(item) if item else None

    def _conditional_put(self, item, condition, values=None):
        kwargs = {"Item": item, "ConditionExpression": condition}
        if values:
            kwargs["ExpressionAttributeValues"] = values
        try:
            self.table.put_item(**kwargs)
        except Exception as error:  # botocore ClientError without importing botocore
            if getattr(error, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConditionFailed() from error
            raise

    def get_config(self, monitor_id):
        return self._get(monitor_id, "CONFIG")

    def get_state(self, monitor_id):
        return self._get(monitor_id, "STATE")

    def get_item(self, monitor_id, source_id):
        return self._get(monitor_id, f"ITEM#{source_id}")

    def acquire_lock(self, monitor_id, owner, now, lease=LEASE_SECONDS) -> bool:
        try:
            self._conditional_put({"pk": pk(monitor_id), "sk": "LOCK", "owner": owner,
                                   "acquiredAt": _iso(now), "expiresAt": int(now + lease)},
                                  "attribute_not_exists(pk) OR expiresAt < :now", {":now": int(now)})
            return True
        except ConditionFailed:
            return False

    def release_lock(self, monitor_id, owner):
        try:
            self.table.delete_item(Key={"pk": pk(monitor_id), "sk": "LOCK"},
                                   ConditionExpression="#o = :owner",
                                   ExpressionAttributeNames={"#o": "owner"},
                                   ExpressionAttributeValues={":owner": owner})
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise

    def put_discovery(self, monitor_id, record) -> bool:
        """Insert once; False when this revision's discovery already exists (retry after a crash)."""
        try:
            self._conditional_put(record, "attribute_not_exists(pk)")
            return True
        except ConditionFailed:
            return False

    def put_item(self, monitor_id, record):
        self.table.put_item(Item=record)

    def url_holders(self, digest: str) -> list[dict]:
        """The monitors that have collected this canonical URL (`URL#<hash>` / `MON#<monitorId>` records)."""
        rows, start = [], None
        while True:
            kwargs = {"ExclusiveStartKey": start} if start else {}
            page = self.table.query(KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                                    ExpressionAttributeValues={":pk": f"URL#{digest}", ":prefix": "MON#"}, **kwargs)
            rows += [self._clean(row) for row in page.get("Items", [])]
            start = page.get("LastEvaluatedKey")
            if not start:
                return rows

    def put_receipt(self, monitor_id, record):
        self.table.put_item(Item=record)

    def put_state(self, monitor_id, record):
        self.table.put_item(Item=record)


def _validate_config(raw: dict) -> dict:
    source_type = str(raw.get("sourceType") or "hn-rss")
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"Config sourceType must be one of {', '.join(sorted(SOURCE_TYPES))}")
    host = SOURCE_TYPES[source_type]["host"]
    if source_type == WEB_SEARCH:
        raw = {"sourceUrl": TAVILY_SOURCE_URL, "intervalSeconds": WEB_INTERVAL_SECONDS, **raw}
    source = urlsplit(str(raw.get("sourceUrl") or ""))
    if (source.scheme != "https" or source.hostname != host or source.username
            or source.password or source.query or source.fragment):
        raise ValueError(f"Config sourceUrl must be an https://{host} URL for a {source_type} monitor")
    interval = int(raw.get("intervalSeconds"))
    if interval < 60:
        raise ValueError("Config intervalSeconds must be at least 60")
    retired = sorted(key for key in RETIRED_CONFIG_FIELDS if key in raw)
    if retired:   # an old stored config still loads, so deploy and seed order do not matter
        print(json.dumps({"monitor": "ignored_retired_config", "fields": retired}))
    config = {"sourceType": source_type, "sourceUrl": raw["sourceUrl"], "intervalSeconds": interval,
              "enabled": raw.get("enabled", True) is not False}
    if source_type == "ttab-decisions":
        lookback = int(raw.get("lookbackDays", 30))
        if not 1 <= lookback <= 180:
            raise ValueError("Config lookbackDays must be between 1 and 180")
        recheck = int(raw.get("precedentialLookbackDays", 0))
        if recheck and not lookback < recheck <= 365:
            raise ValueError("Config precedentialLookbackDays must be 0 (off) or longer than lookbackDays, up to 365")
        page_size = int(raw.get("pageSize", TTAB_PAGE_SIZE))
        if not 1 <= page_size <= 1000:
            raise ValueError("Config pageSize must be between 1 and 1000")
        config.update(lookbackDays=lookback, finalDecisionsOnly=raw.get("finalDecisionsOnly", True) is not False,
                      precedentialLookbackDays=recheck, pageSize=page_size)
    if source_type == "huggingface-models":
        config.update(validate_hf_config(raw))
    if source_type == WEB_SEARCH:
        config.update(validate_web_config(raw))
    return config


def source_feeds(config: dict, now: float, fetch: Callable[..., bytes] | None, reading: Reading, *,
                 known: Callable | None = None, watermark: int | None = None) -> list[dict]:
    """The feeds one source is read through (see `monitoring_paging.read_feed`). Each is a dict with a `key`,
    `fetch_page(cursor) -> (rows, next_cursor)`, `items(rows) -> (SourceItem list, over)` and `stop_at_seen`
    (true when the feed is newest first, so a page of collected items is its high-water mark).
    `fetch` replaces the network call in tests. A feed may also carry `known(item)`: an item it returns True for
    was collected before (by this monitor or, for web search, another) and is skipped."""
    if config["sourceType"] == WEB_SEARCH:
        return [web_feed(config, int(now), watermark, fetch, known or (lambda item: False))]
    if config["sourceType"] == "huggingface-models":
        return hf_feeds(config, now, fetch, reading)
    if config["sourceType"] == "ttab-decisions":
        fetch = fetch or fetch_ttab_decisions
        feeds = [("recent", config["lookbackDays"], config["finalDecisionsOnly"], False)]
        # Precedential designations can come months after a decision issues. Every decision type
        # counts here: a precedential order on a motion matters as much as a final decision.
        if config["precedentialLookbackDays"]:
            feeds.append(("precedential", config["precedentialLookbackDays"], False, True))
        return [ttab_feed(config, now, fetch, *spec) for spec in feeds]

    def fetch_page(cursor):
        return parse_hn_feed((fetch or fetch_hn_feed)(config["sourceUrl"])), None   # an RSS feed is one page

    return [{"key": "feed", "fetch_page": fetch_page, "items": lambda rows: (rows, True), "stop_at_seen": True}]


def ttab_feed(config: dict, now: float, fetch: Callable, key: str, lookback_days: int, final_only: bool,
              precedential_only: bool) -> dict:
    """One Reading Room search, paged by result number until a page comes back empty (or repeats itself)."""
    seen_here: set[str] = set()

    def fetch_page(start):
        start = start or 0
        body = ttab_search_body(now, lookback_days, config["pageSize"], precedential_only=precedential_only, offset=start)
        items, results = parse_ttab_page(fetch(config["sourceUrl"], body), final_decisions_only=final_only)
        return (items, results), (start + results if results else None)

    def items(rows):
        page, results = rows
        fresh = [item for item in page if item.source_id not in seen_here]
        seen_here.update(item.source_id for item in page)
        # An empty page is the end of the search. A page that adds nothing is a server ignoring the offset.
        return page, results == 0 or (bool(page) and not fresh)

    return {"key": key, "fetch_page": fetch_page, "items": items, "stop_at_seen": True}


def register_url(store, monitor_id: str, config: dict, item, observed: str):
    """Record that this monitor collected the URL, so a web-search monitor can tell a story another source already found.
    Best effort: a failed write only means the story may be collected again elsewhere."""
    try:
        store.put_item(monitor_id, {"pk": f"URL#{url_hash(item.canonical_url)}", "sk": f"MON#{monitor_id}",
                                    "monitorId": monitor_id, "sourceType": config["sourceType"], "sourceId": item.source_id,
                                    "canonicalUrl": item.canonical_url, "firstObservedAt": observed})
    except Exception as error:   # noqa: BLE001
        print(json.dumps({"monitor": "url_registry_failed", "monitorId": monitor_id, "error": str(error)[:200]}))


def known_in_other_sources(store, monitor_id: str, config: dict):
    """The `known` test of a web-search feed: the URL is already an item of this monitor, or some other monitor collected
    it. Another web-search monitor counts only when the config says so (`dedupeAgainstWebMonitors`): each publication's
    web monitor routes only to its own publication, so one story can fairly be found for several."""
    def known(item) -> bool:
        if store.get_item(monitor_id, item.source_id):
            return True
        for holder in store.url_holders(url_hash(item.canonical_url)):
            if holder.get("monitorId") == monitor_id:
                return True
            if holder.get("sourceType") != WEB_SEARCH or config["dedupeAgainstWebMonitors"]:
                return True
        return False
    return known


def commit_item(store, monitor_id: str, config: dict, item, *, now: float, run_id: str) -> str:
    """Dedupe one source item against its current record and, when new or changed, write its discovery and
    current-item record (in that order, so a crash between them is repaired by the next run).
    Returns `new`, `revised` or `unchanged`. Shared by the collector and the Hugging Face backfill."""
    old = store.get_item(monitor_id, item.source_id)
    if old and old["fingerprint"] == item.fingerprint:
        return "unchanged"
    revision = old["revision"] + 1 if old else 1
    observed = _iso(now)
    binding = {"monitorId": monitor_id, "sourceUrl": config["sourceUrl"]}
    event_id = _digest([binding, item.source_id, item.fingerprint])
    fields = {"sourceId": item.source_id, "title": item.title, "canonicalUrl": item.canonical_url,
              "sourceItemUrl": item.source_item_url, "sourcePublishedAt": item.published_at,
              "fingerprint": item.fingerprint, "revision": revision, "eventId": event_id,
              "observedAt": observed, "monitorId": monitor_id, "sourceUrl": config["sourceUrl"],
              "mediaType": item.media_type if item.media_type != "text/html" else None,
              "aliases": list(item.aliases) or None, "details": item.details or None,
              "sourceType": config["sourceType"] if item.details else None}
    discovery = {k: v for k, v in fields.items() if v is not None}
    discovery.update(pk=pk(monitor_id), sk=f"DISC#{item.source_id}#{revision:06d}",
                     routing=ROUTING_COLLECTED, runId=run_id,
                     gsi1pk=f"ROUTING#{monitor_id}#{ROUTING_COLLECTED}",
                     gsi1sk=f"{observed}#{item.source_id}#{revision:06d}")
    store.put_discovery(monitor_id, discovery)  # already present after a crash: fine
    store.put_item(monitor_id, {"pk": pk(monitor_id), "sk": f"ITEM#{item.source_id}",
                                "sourceId": item.source_id, "fingerprint": item.fingerprint,
                                "revision": revision, "eventId": event_id,
                                "firstObservedAt": old.get("firstObservedAt", observed) if old else observed,
                                "lastChangedAt": observed})
    if not old:
        register_url(store, monitor_id, config, item, observed)
    return "revised" if old else "new"


def collect_source(store, monitor_id: str, config: dict, *, fetch, now: float, run_id: str, result: dict,
                   reading: Reading, resume: dict, watermark: int | None = None) -> dict:
    """Read every feed of the source, page by page, committing each page's items before asking for the next, so a
    stop (time, rate limit, a crash) loses nothing. Returns the resume cursors per feed key (empty: all read)."""
    known = known_in_other_sources(store, monitor_id, config) if config["sourceType"] == WEB_SEARCH else None
    feeds = source_feeds(config, now, fetch, reading, known=known, watermark=watermark)
    changed_now: set[str] = set()      # committed by this pass (an item two feeds both list is not "already seen")
    carry, failed = {}, 0
    for feed in feeds:
        def process(rows, feed=feed):
            items, over = feed["items"](rows)
            page = Page(end=over)
            for item in items:
                if not reading.may_write():
                    page.retry = True      # the Lambda is out of time: this page is read again next pass
                    break
                result["itemCount"] += 1
                try:
                    if feed.get("known") and feed["known"](item):
                        result["unchanged"] += 1
                        page.seen += 1
                        continue
                    outcome = commit_item(store, monitor_id, config, item, now=now, run_id=run_id)
                except Exception as error:
                    result["errors"].append({"stage": "store", "sourceId": item.source_id, "message": str(error)[:300]})
                    page.unseen += 1
                    continue
                result[outcome] += 1
                if outcome == "unchanged" and item.source_id not in changed_now:
                    page.seen += 1
                else:
                    changed_now.add(item.source_id)
                    page.unseen += 1
            return page

        try:
            left = read_feed(feed["fetch_page"], process, reading, resume.get(feed["key"]) or (),
                             stop_at_seen=feed["stop_at_seen"])
        except Exception as error:
            failed += 1
            left = resume.get(feed["key"]) or []      # an unreadable feed keeps its place for the next pass
            reading.errors.append({"stage": "fetch", **({"query": feed["key"]} if feed.get("labelled") else {}),
                                   "message": str(error)[:300]})
        if left:
            carry[feed["key"]] = left
    if failed == len(feeds):
        raise ValueError(reading.errors[0]["message"])
    return carry


def run_collection(store, monitor_id: str = "hn", *, fetch: Callable[..., bytes] | None = None,
                   now: float | None = None, force: bool = False, owner: str | None = None,
                   run_id: str | None = None, budget_seconds: float | None = READ_BUDGET_SECONDS,
                   clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Run one collection when due. Mirrors `monitoring.collect` without an intake step.

    The source is paged until the pass reaches items it already collected or the source has no more. It is bound
    only by the Lambda's time (`budget_seconds`, with the rest of the 120 s kept to finish) and the source's rate
    limit. A pass that stops early records where it stopped (`resume` in STATE) and is due again at once, so the
    next scheduled pass continues. Each item is committed on its own, so a later failure cannot erase earlier progress.
    """
    injected_clock, now = now is not None, time.time() if now is None else now
    owner, run_id = owner or uuid.uuid4().hex, run_id or uuid.uuid4().hex
    raw = store.get_config(monitor_id)
    if raw is None:
        return {"monitorId": monitor_id, "runId": run_id, "status": "not_configured"}
    config = _validate_config(raw)
    if not config["enabled"]:
        return {"monitorId": monitor_id, "runId": run_id, "status": "disabled"}
    if not store.acquire_lock(monitor_id, owner, now):
        return {"monitorId": monitor_id, "runId": run_id, "status": "locked"}
    try:
        state = store.get_state(monitor_id)
        if state and state["nextDueAt"] - DUE_SLACK_SECONDS > now and not force:
            return {"monitorId": monitor_id, "runId": run_id, "status": "not_due",
                    "nextDueAt": _iso(state["nextDueAt"])}
        result = {"monitorId": monitor_id, "runId": run_id, "startedAt": _iso(now), "status": "complete",
                  "new": 0, "revised": 0, "unchanged": 0, "errors": [], "itemCount": 0}
        reading = Reading(budget_seconds, clock=clock, sleep=sleep)
        resume = (state or {}).get("resume") or {}
        carry = resume
        watermark = (state or {}).get("watermark")
        try:
            carry = collect_source(store, monitor_id, config, fetch=fetch, now=now, run_id=run_id, result=result,
                                   reading=reading, resume=resume, watermark=watermark)
        except Exception as error:
            result["status"] = "failed"
            result["errors"].append({"stage": "fetch", "message": str(error)[:300]})
        for error in reading.errors:   # a feed that failed while others succeeded
            if error["message"] not in {e["message"] for e in result["errors"]}:
                result["errors"].append(error)
        if reading.stopped_by and result["status"] != "failed":   # not read to its end; the receipt says so and the next pass continues
            result["errors"].append({"stage": "fetch", "message": f"stopped early: {reading.stopped_by}"})
        if config["sourceType"] == "huggingface-models" or reading.stopped_by:
            result["read"] = {"requests": reading.requests, "stoppedBy": reading.stopped_by}
            if config["sourceType"] == "huggingface-models":
                result["read"]["window"] = _iso(hf_window_start(config, now).timestamp())
                if reading.excluded:
                    result["read"]["skipped"] = reading.skipped()
        if result["errors"] and result["status"] != "failed":
            result["status"] = "partial"
        finished = now if injected_clock else time.time()
        next_due = now if carry and result["status"] != "failed" else now + config["intervalSeconds"]
        if config["sourceType"] == WEB_SEARCH:
            # The high-water mark moves to the start of a pass that read every query to its end without an error.
            if result["status"] == "complete" and not carry and not reading.errors:
                watermark = int(((resume.get("web") or [{}])[0]).get("until") or now)
        result.update(finishedAt=_iso(finished), nextDueAt=_iso(next_due), errorCount=len(result["errors"]))
        store.put_receipt(monitor_id, {
            "pk": pk(monitor_id), "sk": f"RUN#{result['startedAt']}#{run_id}", "runId": run_id,
            "startedAt": result["startedAt"], "finishedAt": result["finishedAt"], "status": result["status"],
            "new": result["new"], "revised": result["revised"], "unchanged": result["unchanged"],
            "itemCount": result["itemCount"], "errorCount": result["errorCount"],
            "errors": result["errors"][:MAX_ERRORS_RECORDED], "nextDueAt": result["nextDueAt"],
            "ttl": int(now + RECEIPT_TTL_SECONDS), **({"read": result["read"]} if "read" in result else {})})
        store.put_state(monitor_id, {"pk": pk(monitor_id), "sk": "STATE", "nextDueAt": int(next_due),
                                     "lastRunId": run_id, "lastStatus": result["status"],
                                     "lastFinishedAt": result["finishedAt"], **({"resume": carry} if carry else {}),
                                     **({"watermark": int(watermark)} if watermark is not None else {})})
        return result
    finally:
        store.release_lock(monitor_id, owner)


def run_web_collections(store, monitor_ids, *, now: float | None = None, force: bool = False,
                        budget_seconds: float = READ_BUDGET_SECONDS, clock: Callable[[], float] = time.monotonic,
                        sleep: Callable[[float], None] = time.sleep, fetch=None) -> list[dict]:
    """Collect every web-search monitor in `monitor_ids` whose next-due time has passed, the longest-overdue first.

    One scheduled invocation serves all of them, so the pass's read time is shared: each monitor gets an equal share of
    what is left (a monitor that stops early is due again at once, and the next invocation continues it). Monitors that
    are not configured, disabled, of another source type or not yet due are left alone."""
    now = time.time() if now is None else now
    due = []
    for monitor_id in monitor_ids:
        raw = store.get_config(monitor_id)
        if raw is None or raw.get("sourceType") != WEB_SEARCH or raw.get("enabled") is False:
            continue
        state = store.get_state(monitor_id)
        next_due = (state or {}).get("nextDueAt", 0)
        if force or next_due - DUE_SLACK_SECONDS <= now:
            due.append((next_due, monitor_id))
    started, results = clock(), []
    for index, (_, monitor_id) in enumerate(sorted(due)):
        left = budget_seconds - (clock() - started)
        if left <= 0:
            break
        try:
            results.append(run_collection(store, monitor_id, now=now, force=force, budget_seconds=left / (len(due) - index),
                                          clock=clock, sleep=sleep, fetch=fetch))
        except Exception as error:   # one monitor's bad config must not stop the others
            results.append({"monitorId": monitor_id, "status": "failed", "errors": [{"stage": "config", "message": str(error)[:300]}]})
    return results


def handler(event, context):
    """EventBridge Scheduler entry point. `{"force": true}` is for operator debugging only."""
    import boto3  # provided by the Lambda runtime

    event = event if isinstance(event, dict) else {}
    store = DynamoStore(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))
    if event.get("sourceType") == WEB_SEARCH:   # {"sourceType": "web-search", "monitorIds": [...]}: every due web monitor
        results = run_web_collections(store, [str(m) for m in event.get("monitorIds") or []], force=event.get("force") is True)
        print(json.dumps([{k: v for k, v in r.items() if k != "errors"} | {"errors": r.get("errors", [])[:3]} for r in results]))
        if any(r["status"] == "failed" for r in results):
            raise RuntimeError("Web monitor collection failed; see the run receipts")
        return [{k: r.get(k) for k in ("monitorId", "runId", "status", "new", "unchanged", "errorCount", "nextDueAt")} for r in results]
    result = run_collection(store, str(event.get("monitorId") or "hn"), force=event.get("force") is True)
    print(json.dumps({k: v for k, v in result.items() if k != "errors"} | {"errors": result.get("errors", [])[:3]}))
    if result["status"] == "failed":
        raise RuntimeError("Monitor collection failed; see the run receipt")
    return {k: result.get(k) for k in ("runId", "status", "new", "revised", "unchanged", "errorCount", "nextDueAt")}
