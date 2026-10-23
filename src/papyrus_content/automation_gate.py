"""What an Automation record decides before a procedure starts (PPY-112007).

Both starters use this one module: the monitoring router (for a monitor trigger) and "run now" (the CLI and the
console). It reads the record and the table rows, and says start, skip or refuse. It must stay light: stdlib only,
and no import of the router, because the router's Lambda zip is built from the router's imports.

The rules:

* **No record, or a record that cannot be read: start exactly as before.** The router's `procedureTriggers` entry
  stays authoritative, so a missing or unreadable record never stops a run and adds nothing to the request.
* **Disabled: start nothing**, and record `skipped` with the reason "automation disabled".
* **maxConcurrent: refuse** a new start while that many runs of the automation are in flight, and record `refused`
  with the reason. A run is in flight while its row says `starting`, `started` or `running` and it began less than its timeout
  plus a grace period ago, so a run whose outcome was never recorded cannot block the automation for ever.
* **timeoutSeconds** goes to the runner with the request, which caps it at the Lambda's limit.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

STATUS_SKIPPED = "skipped"
STATUS_REFUSED = "refused"
REASON_DISABLED = "automation disabled"
IN_FLIGHT = frozenset({"starting", "started", "running"})
MAX_TIMEOUT_SECONDS = 840           # the runner Lambda's 15 minutes less its recording margin
DEFAULT_TIMEOUT_SECONDS = MAX_TIMEOUT_SECONDS
GRACE_SECONDS = 120                 # beyond the timeout, for the runner to record its outcome
MAX_QUERY_PAGES = 5
MANUAL_PREFIX = "MANUAL#"


@dataclass(frozen=True)
class Gate:
    action: str                      # "start", "skip" or "refuse"
    reason: str | None = None
    automation_id: str | None = None
    timeout_seconds: int | None = None

    @property
    def status(self) -> str | None:
        return {"skip": STATUS_SKIPPED, "refuse": STATUS_REFUSED}.get(self.action)


START_AS_BEFORE = Gate("start")


def parse_json(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default if value is None else value


def trigger_prefix(publication_id: str, procedure_key: str) -> str:
    return f"TRIGGER#{publication_id}#{procedure_key}#"


def manual_prefix(automation_id: str) -> str:
    return f"{MANUAL_PREFIX}{automation_id}#"


def query_prefix(table, monitor_id: str, prefix: str, *, pages: int = MAX_QUERY_PAGES) -> list[dict]:
    """The rows of `MONITOR#<monitor_id>` whose sort key starts with `prefix` (Query on the base table)."""
    rows, start = [], None
    for _ in range(pages):
        extra = {"ExclusiveStartKey": start} if start else {}
        result = table.query(KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                             ExpressionAttributeValues={":pk": f"MONITOR#{monitor_id}", ":prefix": prefix}, **extra)
        rows += result.get("Items", [])
        start = result.get("LastEvaluatedKey")
        if not start:
            break
    return rows


def matching_automation(rows: list[dict] | None, *, monitor_id: str, publication_id: str, procedure_key: str) -> dict | None:
    """The monitor automation for this monitor, publication and procedure, from the site's Automation rows.

    A row that cannot be read is not a match, so it behaves like no record. Several matches: the lowest id."""
    found = []
    for row in rows or []:
        trigger = parse_json(row.get("trigger"), {})
        config = trigger.get("config") if isinstance(trigger, dict) else None
        if not (isinstance(trigger, dict) and trigger.get("kind") == "monitor" and isinstance(config, dict)):
            continue
        if (config.get("monitorId"), config.get("publicationId"), row.get("procedureKey")) != (monitor_id, publication_id, procedure_key):
            continue
        if not isinstance(row.get("id"), str):
            continue
        found.append(row)
    if not found:
        return None
    row = min(found, key=lambda item: item["id"])
    return {"id": row["id"], "enabled": row.get("enabled") is not False, "limits": limits_of(row)}


def limits_of(row: dict) -> dict[str, Any]:
    """The usable limits of a record: a value that is not a positive whole number is ignored, never an error."""
    raw = parse_json(row.get("limits"), {})
    limits = {}
    for key in ("timeoutSeconds", "maxConcurrent"):
        value = raw.get(key) if isinstance(raw, dict) else None
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            limits[key] = value
    budget = raw.get("budgetUsdPerRun") if isinstance(raw, dict) else None
    if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget >= 0:
        limits["budgetUsdPerRun"] = budget
    return limits


def _epoch(stamp: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def in_flight_count(rows: list[dict], *, now: float, window_seconds: float) -> int:
    """Rows whose run is still in flight: `starting` or `started`, begun inside the window."""
    count = 0
    for row in rows:
        if row.get("status") not in IN_FLIGHT:
            continue
        began = _epoch(row.get("startedAt") or row.get("createdAt"))
        if began is None or now - began < window_seconds:
            count += 1
    return count


def effective_timeout(limits: dict[str, Any]) -> int:
    return min(limits.get("timeoutSeconds", DEFAULT_TIMEOUT_SECONDS), MAX_TIMEOUT_SECONDS)


def decide(automation: dict | None, rows_in_flight: list[dict] | None, *, now: float) -> Gate:
    """`rows_in_flight` are the automation's trigger and manual rows (any status); only the in-flight ones count."""
    if automation is None:
        return START_AS_BEFORE
    base = {"automation_id": automation["id"]}
    if not automation["enabled"]:
        return Gate("skip", REASON_DISABLED, **base)
    limits = automation["limits"]
    timeout = effective_timeout(limits)
    maximum = limits.get("maxConcurrent")
    if maximum is not None:
        running = in_flight_count(rows_in_flight or [], now=now, window_seconds=timeout + GRACE_SECONDS)
        if running >= maximum:
            return Gate("refuse", f"automation at its limit: {running} running, at most {maximum} at a time", **base)
    return Gate("start", None, timeout_seconds=timeout, **base)
