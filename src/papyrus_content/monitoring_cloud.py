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
                         parse_ttab_decisions, ttab_search_body)

LEASE_SECONDS = 150          # longer than the 120 s Lambda timeout; a crashed run's lease expires
DUE_SLACK_SECONDS = 60       # scheduler jitter must not skip a whole interval
RECEIPT_TTL_SECONDS = 30 * 86400
MAX_ERRORS_RECORDED = 10
ROUTING_COLLECTED = "collected"


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

    def put_receipt(self, monitor_id, record):
        self.table.put_item(Item=record)

    def put_state(self, monitor_id, record):
        self.table.put_item(Item=record)


def _validate_config(raw: dict) -> dict:
    source_type = str(raw.get("sourceType") or "hn-rss")
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"Config sourceType must be one of {', '.join(sorted(SOURCE_TYPES))}")
    host = SOURCE_TYPES[source_type]["host"]
    source = urlsplit(str(raw.get("sourceUrl") or ""))
    interval, limit = raw.get("intervalSeconds"), raw.get("limit")
    if (source.scheme != "https" or source.hostname != host or source.username
            or source.password or source.query or source.fragment):
        raise ValueError(f"Config sourceUrl must be an https://{host} URL for a {source_type} monitor")
    interval, limit = int(interval), int(limit)
    if interval < 60:
        raise ValueError("Config intervalSeconds must be at least 60")
    if not 1 <= limit <= 100:
        raise ValueError("Config limit must be between 1 and 100")
    config = {"sourceType": source_type, "sourceUrl": raw["sourceUrl"], "intervalSeconds": interval, "limit": limit,
              "enabled": raw.get("enabled", True) is not False}
    if source_type == "ttab-decisions":
        lookback = int(raw.get("lookbackDays", 30))
        if not 1 <= lookback <= 180:
            raise ValueError("Config lookbackDays must be between 1 and 180")
        config.update(lookbackDays=lookback, finalDecisionsOnly=raw.get("finalDecisionsOnly", True) is not False)
    return config


def read_source(config: dict, now: float, fetch: Callable[..., bytes] | None = None) -> list:
    """Fetch and parse one source. `fetch` replaces the network call in tests."""
    if config["sourceType"] == "ttab-decisions":
        body = ttab_search_body(now, config["lookbackDays"], config["limit"])
        return parse_ttab_decisions((fetch or fetch_ttab_decisions)(config["sourceUrl"], body),
                                    final_decisions_only=config["finalDecisionsOnly"])
    return parse_hn_feed((fetch or fetch_hn_feed)(config["sourceUrl"]))


def run_collection(store, monitor_id: str = "hn", *, fetch: Callable[..., bytes] | None = None,
                   now: float | None = None, force: bool = False, owner: str | None = None,
                   run_id: str | None = None) -> dict:
    """Run one collection when due. Mirrors `monitoring.collect` without an intake step.

    Each item is committed on its own, so a later failure cannot erase earlier progress.
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
        binding = {"monitorId": monitor_id, "sourceUrl": config["sourceUrl"]}
        result = {"monitorId": monitor_id, "runId": run_id, "startedAt": _iso(now), "status": "complete",
                  "new": 0, "revised": 0, "unchanged": 0, "errors": []}
        try:
            items = read_source(config, now, fetch)
        except Exception as error:
            result["status"] = "failed"
            result["errors"].append({"stage": "fetch", "message": str(error)[:300]})
            items = []
        result["itemCount"] = len(items)
        for item in items[:config["limit"]]:
            try:
                old = store.get_item(monitor_id, item.source_id)
                if old and old["fingerprint"] == item.fingerprint:
                    result["unchanged"] += 1
                    continue
                revision = old["revision"] + 1 if old else 1
                observed = _iso(now)
                event_id = _digest([binding, item.source_id, item.fingerprint])
                fields = {"sourceId": item.source_id, "title": item.title, "canonicalUrl": item.canonical_url,
                          "sourceItemUrl": item.source_item_url, "sourcePublishedAt": item.published_at,
                          "fingerprint": item.fingerprint, "revision": revision, "eventId": event_id,
                          "observedAt": observed, "monitorId": monitor_id, "sourceUrl": config["sourceUrl"],
                          "mediaType": item.media_type if item.media_type != "text/html" else None}
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
                result["revised" if old else "new"] += 1
            except Exception as error:
                result["errors"].append({"stage": "store", "sourceId": item.source_id, "message": str(error)[:300]})
        if result["errors"] and result["status"] != "failed":
            result["status"] = "partial"
        finished = now if injected_clock else time.time()
        next_due = now + config["intervalSeconds"]
        result.update(finishedAt=_iso(finished), nextDueAt=_iso(next_due), errorCount=len(result["errors"]))
        store.put_receipt(monitor_id, {
            "pk": pk(monitor_id), "sk": f"RUN#{result['startedAt']}#{run_id}", "runId": run_id,
            "startedAt": result["startedAt"], "finishedAt": result["finishedAt"], "status": result["status"],
            "new": result["new"], "revised": result["revised"], "unchanged": result["unchanged"],
            "itemCount": result["itemCount"], "errorCount": result["errorCount"],
            "errors": result["errors"][:MAX_ERRORS_RECORDED], "nextDueAt": result["nextDueAt"],
            "ttl": int(now + RECEIPT_TTL_SECONDS)})
        store.put_state(monitor_id, {"pk": pk(monitor_id), "sk": "STATE", "nextDueAt": int(next_due),
                                     "lastRunId": run_id, "lastStatus": result["status"],
                                     "lastFinishedAt": result["finishedAt"]})
        return result
    finally:
        store.release_lock(monitor_id, owner)


def handler(event, context):
    """EventBridge Scheduler entry point. `{"force": true}` is for operator debugging only."""
    import boto3  # provided by the Lambda runtime

    event = event if isinstance(event, dict) else {}
    store = DynamoStore(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))
    result = run_collection(store, str(event.get("monitorId") or "hn"), force=event.get("force") is True)
    print(json.dumps({k: v for k, v in result.items() if k != "errors"} | {"errors": result.get("errors", [])[:3]}))
    if result["status"] == "failed":
        raise RuntimeError("Monitor collection failed; see the run receipt")
    return {k: result.get(k) for k in ("runId", "status", "new", "revised", "unchanged", "errorCount", "nextDueAt")}
