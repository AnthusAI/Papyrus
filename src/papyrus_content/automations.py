"""Automation records: a named, bound "when X happens, run procedure Y" (PPY-9ff95b).

An Automation is a record in a site's own backend. A monitor automation *mirrors* the `procedureTriggers` entry
that the monitoring router reads from `CONFIG#router` (`docs/monitoring-cloud.md`, `docs/procedure-runner.md`),
and the router's entry stays authoritative: it is what starts a run. Since step 2 (PPY-112007) the router also
reads the record before it starts one (`automation_gate.py`): `enabled` and the limits are real, the cost of a run
is recorded and shown, and "Run now" starts a run by hand (`run_now`, from the CLI and the console).

Run history joins two sources the site backend alone cannot see together:

* the `TRIGGER#<publication>#<procedureKey>#<sourceId>` rows in the monitoring table (`MONITOR#<monitorId>`),
  which say what started, for which item, and how it ended; and
* the `ProcedureRun` records in the site backend, which hold timing, error and the procedure's output
  (the story it created is `output.story`).

Both readers are injected, so the CLI (operator credentials), the console's Lambda (its own IAM role) and the
tests share one implementation. Nothing here writes to the monitoring table.
"""
from __future__ import annotations

import json
import os
import re
import string
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .automation_gate import (
    MANUAL_PREFIX, decide, limits_of, manual_prefix, query_prefix, trigger_prefix)
from .story_triggers import MAX_HOPS, STAGE_ENTERED, is_stage_trigger
from .monitoring_router import (
    PROCEDURE_INPUT_NAME,
    PROCEDURE_KEY,
    PUBLICATION_ID,
    TRIGGER_PLACEHOLDERS,
)

KINDS = ("monitor", "schedule", "event", "manual")
ACTIVE_KINDS = frozenset({"monitor"})
AUTOMATION_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
MONITOR_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ENABLED_NOTE = "the router starts nothing for a disabled automation"
LIMITS_NOTE = "the timeout and the number at a time (when set) are enforced when a run starts; the budget is advisory and only flagged"
COST_NOTE = "not recorded for this run"
RUNNER_FUNCTION = "papyrus-procedure-runner"
OUTSIDE_FETCH = 25
RUN_COST_FIELDS = "usage costUsd"
NOT_SUPPORTED = "not yet supported"
ROUTER_CONFIG_SK = "CONFIG#router"
DEFAULT_LIMITS = {"timeoutSeconds": 840}   # no maxConcurrent: no limit on how many run at once, as before slice 2
MAX_TIMEOUT_SECONDS = 840          # the runner Lambda's 15 minutes less its recording margin
MAX_TRIGGER_PAGES = 5
DEFAULT_RUN_LIMIT = 10
MAX_RUN_LIMIT = 50
MAX_TEXT = 500


class AutomationError(ValueError):
    """A request the record rules refuse; the message is safe to show an editor."""


# --- the record -------------------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default if value is None else value


def _text(value: Any, label: str, *, required: bool = False, limit: int = MAX_TEXT) -> str | None:
    cleaned = str(value).strip() if value is not None and value is not True else ""
    if not cleaned:
        if required:
            raise AutomationError(f"{label} is required.")
        return None
    if len(cleaned) > limit:
        raise AutomationError(f"{label} is longer than {limit} characters.")
    return cleaned


def _boolean(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise AutomationError(f"{label} must be true or false.")


def validate_trigger(trigger: Any) -> dict[str, Any]:
    if not isinstance(trigger, dict):
        raise AutomationError("trigger must be an object with a kind and a config.")
    kind = str(trigger.get("kind") or "")
    if kind not in KINDS:
        raise AutomationError(f"trigger kind must be one of {', '.join(KINDS)}.")
    config = trigger.get("config") or {}
    if not isinstance(config, dict):
        raise AutomationError("trigger config must be an object.")
    if kind == "monitor":
        monitor_id, publication_id = str(config.get("monitorId") or ""), str(config.get("publicationId") or "")
        if not MONITOR_ID.match(monitor_id):
            raise AutomationError("a monitor trigger needs config.monitorId (for example ttab).")
        if not PUBLICATION_ID.match(publication_id):
            raise AutomationError("a monitor trigger needs config.publicationId, the router publication it delivers to.")
        config = {"monitorId": monitor_id, "publicationId": publication_id}
    if kind == "event" and config.get("event") == STAGE_ENTERED:
        from .content_item_lifecycle import CONTENT_ITEM_STAGES

        monitor_id, publication_id, stage = (str(config.get(key) or "") for key in ("monitorId", "publicationId", "onStage"))
        if stage not in CONTENT_ITEM_STAGES:
            raise AutomationError(f"a story-stage trigger needs config.onStage, one of {', '.join(CONTENT_ITEM_STAGES)}.")
        next_stage = config.get("nextStage")
        if next_stage is not None and (next_stage not in CONTENT_ITEM_STAGES or next_stage == stage):
            raise AutomationError(f"config.nextStage must be a different stage, one of {', '.join(CONTENT_ITEM_STAGES)}.")
        if not MONITOR_ID.match(monitor_id) or not PUBLICATION_ID.match(publication_id):
            raise AutomationError("a story-stage trigger needs config.monitorId and config.publicationId: the monitor partition "
                                  "that holds its run rows and the router publication that supplies the endpoint and model key.")
        config = {"event": STAGE_ENTERED, "onStage": stage, "monitorId": monitor_id, "publicationId": publication_id}
        if next_stage:
            config["nextStage"] = next_stage
    return {"kind": kind, "config": config}


def validate_input_template(template: Any, trigger: dict[str, Any]) -> dict[str, str]:
    if template is None:
        return {}
    if not isinstance(template, dict):
        raise AutomationError("inputTemplate must be an object of name to template text.")
    cleaned: dict[str, str] = {}
    for name, value in template.items():
        if not PROCEDURE_INPUT_NAME.match(str(name)):
            raise AutomationError(f"inputTemplate name {name!r} is not a valid procedure input name.")
        text = str(value)
        if is_stage_trigger(trigger) and "{" in text:
            raise AutomationError(f"inputTemplate {name}: a story-stage automation's input is static; the engine adds story, version, "
                                  "versionNumber, stage, runKey, automationId and hop.")
        if trigger["kind"] == "monitor":
            used = {field for _, field, _, _ in string.Formatter().parse(text) if field is not None}
            unknown = sorted(used - TRIGGER_PLACEHOLDERS)
            if unknown:
                raise AutomationError(
                    f"inputTemplate {name} uses unknown placeholder(s) {', '.join(unknown)}; "
                    f"available: {', '.join(sorted(TRIGGER_PLACEHOLDERS))}.")
        cleaned[str(name)] = text
    return cleaned


def validate_limits(limits: Any) -> dict[str, Any]:
    if limits is None:
        return dict(DEFAULT_LIMITS)
    if not isinstance(limits, dict):
        raise AutomationError("limits must be an object.")
    unknown = sorted(set(limits) - {"timeoutSeconds", "maxConcurrent", "budgetUsdPerRun", "maxHops"})
    if unknown:
        raise AutomationError(f"unknown limit(s): {', '.join(unknown)}.")
    merged = {**DEFAULT_LIMITS, **{key: value for key, value in limits.items() if value is not None}}
    for key, low, high in (("timeoutSeconds", 1, MAX_TIMEOUT_SECONDS), ("maxConcurrent", 1, 100), ("maxHops", 1, MAX_HOPS)):
        if key not in merged:
            continue
        value = merged[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise AutomationError(f"limits.{key} must be a whole number from {low} to {high}.")
    budget = merged.get("budgetUsdPerRun")
    if budget is not None and (isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget < 0):
        raise AutomationError("limits.budgetUsdPerRun must be a number of dollars, zero or more.")
    return merged


def build_record(fields: dict[str, Any], *, existing: dict[str, Any] | None = None, actor: str, now: str | None = None) -> dict[str, Any]:
    """The validated record to store. `fields` holds only what the caller set; `existing` (an update) supplies the rest."""
    now = now or _now()
    base = existing or {}
    record_id = _text(fields.get("id", base.get("id")), "id", required=True, limit=128)
    if not AUTOMATION_ID.match(record_id):
        raise AutomationError("id must be lowercase letters, digits, dots, dashes or underscores.")
    trigger = validate_trigger(fields.get("trigger", base.get("trigger")))
    procedure_key = _text(fields.get("procedureKey", base.get("procedureKey")), "procedureKey", required=True, limit=128)
    if not PROCEDURE_KEY.match(procedure_key):
        raise AutomationError("procedureKey must be lowercase letters, digits, dots, dashes or underscores.")
    record = {
        "id": record_id,
        "title": _text(fields.get("title", base.get("title")), "title", required=True, limit=200),
        "description": _text(fields.get("description", base.get("description")), "description"),
        "enabled": _boolean(fields.get("enabled", base.get("enabled", True)), "enabled"),
        "trigger": trigger,
        "procedureKey": procedure_key,
        "inputTemplate": validate_input_template(fields.get("inputTemplate", base.get("inputTemplate")), trigger),
        "limits": validate_limits(fields.get("limits", base.get("limits"))),
        "updatedBy": actor,
        "updatedAt": now,
    }
    if existing:
        record["createdBy"], record["createdAt"] = base.get("createdBy"), base.get("createdAt")
    else:
        record["createdBy"], record["createdAt"] = actor, now
    return record


def stored_payload(record: dict[str, Any]) -> dict[str, Any]:
    """The GraphQL input for a record: JSON fields travel as strings."""
    payload = {key: record.get(key) for key in ("id", "title", "description", "enabled", "procedureKey",
                                                 "createdBy", "createdAt", "updatedBy", "updatedAt")}
    for key in ("trigger", "inputTemplate", "limits"):
        payload[key] = json.dumps(record[key])
    return payload


def read_record(row: dict[str, Any]) -> dict[str, Any]:
    """A stored row as the record the CLI and console show, with what is and is not live said in words."""
    trigger = _parse(row.get("trigger"), {})
    kind = str(trigger.get("kind") or "")
    supported = kind in ACTIVE_KINDS or is_stage_trigger(trigger)
    return {
        "id": row.get("id"), "title": row.get("title"), "description": row.get("description"),
        "enabled": row.get("enabled") is not False,
        "enabledNote": ENABLED_NOTE,
        "trigger": {"kind": kind, "config": trigger.get("config") or {}},
        "onStage": (trigger.get("config") or {}).get("onStage") if is_stage_trigger(trigger) else None,
        "nextStage": (trigger.get("config") or {}).get("nextStage") if is_stage_trigger(trigger) else None,
        "maxHops": _parse(row.get("limits"), {}).get("maxHops") if is_stage_trigger(trigger) else None,
        "supported": supported,
        "supportNote": None if supported else NOT_SUPPORTED,
        "procedureKey": row.get("procedureKey"),
        "inputTemplate": _parse(row.get("inputTemplate"), {}),
        "limits": _parse(row.get("limits"), dict(DEFAULT_LIMITS)),
        "limitsNote": LIMITS_NOTE,
        "runNow": run_now_availability({"enabled": row.get("enabled") is not False, "kind": kind, "stageTrigger": is_stage_trigger(trigger),
                                        "template": _parse(row.get("inputTemplate"), {})}),
        "createdBy": row.get("createdBy"), "createdAt": row.get("createdAt"),
        "updatedBy": row.get("updatedBy"), "updatedAt": row.get("updatedAt"),
    }


def run_now_availability(info: dict[str, Any]) -> dict[str, Any]:
    """Whether Run now is offered, and whether the person must give the input (the template names item placeholders)."""
    template = info["template"] if isinstance(info["template"], dict) else {}
    placeholders = sorted({field for text in template.values() for _, field, _, _ in string.Formatter().parse(str(text)) if field})
    if info.get("stageTrigger"):
        return {"available": False, "reason": "starts when a story enters its stage, not by hand", "needsInput": False, "inputNames": []}
    if info["kind"] not in ACTIVE_KINDS:
        return {"available": False, "reason": NOT_SUPPORTED, "needsInput": False, "inputNames": []}
    if not info["enabled"]:
        return {"available": False, "reason": "disabled", "needsInput": False, "inputNames": []}
    return {"available": True, "reason": None, "needsInput": bool(placeholders), "inputNames": sorted(template)}


def create_automation(client, fields: dict[str, Any], *, actor: str, now: str | None = None) -> dict[str, Any]:
    record = build_record(fields, actor=actor, now=now)
    if client.get_record("Automation", record["id"]):
        raise AutomationError(f"automation {record['id']} already exists; use update.")
    client.create_record("Automation", stored_payload(record))
    return read_record(stored_payload(record))


def update_automation(client, record_id: str, fields: dict[str, Any], *, actor: str, now: str | None = None) -> dict[str, Any]:
    row = client.get_record("Automation", record_id)
    if not row:
        raise AutomationError(f"automation {record_id} does not exist.")
    existing = read_record(row)
    if fields.get("id") not in (None, record_id):
        raise AutomationError("an automation's id cannot change.")
    record = build_record({**fields, "id": record_id}, existing=existing, actor=actor, now=now)
    client.update_record("Automation", stored_payload(record))
    return read_record(stored_payload(record))


# --- the monitoring table (read only) ------------------------------------------------------------------


def _clean(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


class MonitoringReader:
    """GetItem and Query on the monitoring table, and nothing else."""

    def __init__(self, table):
        self.table = table

    def router_config(self, monitor_id: str) -> dict | None:
        item = self.table.get_item(Key={"pk": f"MONITOR#{monitor_id}", "sk": ROUTER_CONFIG_SK}).get("Item")
        return _clean(item) if item else None

    def trigger_rows(self, monitor_id: str, publication_id: str, procedure_key: str) -> list[dict]:
        return [_clean(item) for item in query_prefix(self.table, monitor_id, trigger_prefix(publication_id, procedure_key))]

    def rows_with_prefix(self, monitor_id: str, prefix: str) -> list[dict]:
        """Rows of the monitor's partition by sort-key prefix (the story-stage run rows)."""
        return [_clean(item) for item in query_prefix(self.table, monitor_id, prefix)]

    def manual_rows(self, monitor_id: str, automation_id: str) -> list[dict]:
        """The rows Run now wrote for this automation."""
        return [_clean(item) for item in query_prefix(self.table, monitor_id, manual_prefix(automation_id))]


class MonitoringWriter:
    """PutItem of a Run now row on the monitoring table, and nothing else."""

    def __init__(self, table):
        self.table = table

    def put(self, row: dict) -> None:
        self.table.put_item(Item=row)

    def claim(self, row: dict) -> bool:
        """Put the row only if its key is new. False when it exists already: someone else holds the claim."""
        try:
            self.table.put_item(Item=row, ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)")
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True


def monitoring_table_from_environment(env=None):
    """The monitoring table through the SSM parameter its stack writes (see monitoring_view). None when it is absent."""
    from .monitoring_view import default_store_factory

    store = default_store_factory(os.environ if env is None else env)()
    return store.table if store is not None else None


def monitoring_reader_from_environment(env=None) -> MonitoringReader | None:
    table = monitoring_table_from_environment(env)
    return MonitoringReader(table) if table is not None else None


# --- the router link --------------------------------------------------------------------------------------


def router_link(automation: dict[str, Any], router: dict | None) -> dict[str, Any]:
    """Whether the router's own `procedureTriggers` entry for this automation exists, and whether it agrees.

    The router config is the source; the record mirrors it. This only reads and compares."""
    if automation["trigger"]["kind"] != "monitor":
        return {"state": "not_applicable", "text": NOT_SUPPORTED}
    if router is None:
        return {"state": "router_not_found", "text": "The monitor has no router configuration."}
    config = automation["trigger"]["config"]
    publication = next((entry for entry in router.get("publications") or []
                        if entry.get("publicationId") == config.get("publicationId")), None)
    base = {"routerMode": router.get("mode"), "routerEnabled": router.get("enabled", True) is not False}
    if publication is None:
        return {**base, "state": "publication_not_in_router", "text": "The router does not deliver to this publication."}
    entry = next((trigger for trigger in publication.get("procedureTriggers") or []
                  if trigger.get("procedureKey") == automation["procedureKey"]), None)
    if entry is None:
        return {**base, "state": "trigger_not_found", "text": "The router has no procedure trigger for this procedure."}
    if (entry.get("input") or {}) != (automation.get("inputTemplate") or {}):
        return {**base, "state": "input_differs", "text": "The router's input template differs from this record.",
                "routerInput": entry.get("input") or {}}
    return {**base, "state": "linked", "text": "The router's trigger matches this record."}


# --- run history --------------------------------------------------------------------------------------------


def _seconds_between(start: str | None, end: str | None) -> float | None:
    try:
        first = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        last = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return round((last - first).total_seconds(), 1) if last >= first else None


def _run_error(row: dict, run: dict | None) -> str | None:
    error = (run or {}).get("errorSummary")
    if not error:
        detail = _parse((run or {}).get("error"), None)
        error = detail.get("message") if isinstance(detail, dict) else None
    error = error or row.get("runError") or row.get("error")
    return str(error)[:MAX_TEXT] if error else None


def read_run(client, run_id: str) -> dict | None:
    """A ProcedureRun with its usage and cost. A backend that predates those fields refuses the longer query;
    the run is then read without them (its cost shows as not recorded)."""
    with_fields = getattr(client, "get_record_with_fields", None)
    if with_fields is not None:
        try:
            return with_fields("ProcedureRun", run_id, RUN_COST_FIELDS)
        except Exception:
            pass
    return client.get_record("ProcedureRun", run_id)


def cost_fields(run: dict | None, budget: Any = None) -> dict[str, Any]:
    """The recorded cost of a run, what it was estimated from, and whether it went over the advisory budget."""
    cost = (run or {}).get("costUsd")
    cost = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None
    usage = _parse((run or {}).get("usage"), None)
    usage = usage if isinstance(usage, dict) else None
    if cost is None and usage is None:
        note = COST_NOTE if run else "no run record, so no cost"
    elif cost is None:
        note = "model usage recorded, but no model in it has a price: " + ", ".join(usage.get("unpricedModels") or ["unknown"])
    elif usage is not None and usage.get("complete") is False:
        note = "estimated, partly: " + ", ".join(usage.get("unpricedModels") or ["a model"]) + " has no price"
    else:
        note = "estimated from the model usage reported by the run"
    over = cost is not None and isinstance(budget, (int, float)) and not isinstance(budget, bool) and cost > budget
    return {"costUsd": cost, "costNote": note, "budgetUsd": budget if isinstance(budget, (int, float)) else None, "overBudget": bool(over),
            "usage": None if usage is None else {key: usage.get(key) for key in
                                                 ("calls", "promptTokens", "completionTokens", "models", "complete", "unpricedModels")}}


def run_entry(row: dict, run: dict | None, lookup_failed: bool = False, budget: Any = None) -> dict[str, Any]:
    """One trigger or Run now row joined with its ProcedureRun. The story is the procedure output's `story` (a lineage id)."""
    output = _parse((run or {}).get("output"), None)
    output = output if isinstance(output, dict) else {}
    started = (run or {}).get("startedAt") or row.get("startedAt") or row.get("createdAt")
    finished = (run or {}).get("finishedAt") or row.get("finishedAt")
    story = output.get("story")
    manual = str(row.get("sk") or "").startswith(MANUAL_PREFIX)
    return {
        "origin": "manual" if manual else "monitor",
        "requestedBy": row.get("requestedBy"),
        "sourceId": row.get("sourceId"), "referenceId": row.get("referenceId"),
        "triggerStatus": row.get("status"), "runId": row.get("runId"),
        "status": (run or {}).get("runStatus") or row.get("status"),
        "reason": row.get("reason"),
        "startedAt": started, "finishedAt": finished,
        "durationSeconds": _seconds_between((run or {}).get("startedAt"), (run or {}).get("finishedAt")),
        "error": _run_error(row, run),
        "runRecord": "found" if run else ("unavailable" if lookup_failed else ("missing" if row.get("runId") else "none")),
        "storyId": story if isinstance(story, str) and story else None,
        "storyVersionId": output.get("version_id") if isinstance(output.get("version_id"), str) else None,
        "storyTitle": output.get("title") if isinstance(output.get("title"), str) else None,
        **cost_fields(run, budget),
    }


def outside_entry(run: dict, budget: Any = None) -> dict[str, Any]:
    """A ProcedureRun of the same procedure that no trigger row of this automation links to."""
    entry = run_entry({"runId": run.get("id"), "startedAt": run.get("startedAt") or run.get("requestedAt"),
                       "requestedBy": run.get("requestedBy")}, run, False, budget)
    return {key: entry[key] for key in ("runId", "status", "startedAt", "finishedAt", "durationSeconds", "error", "requestedBy",
                                        "storyId", "storyVersionId", "storyTitle", "costUsd", "costNote", "overBudget")}


def _row_time(row: dict) -> str:
    return str(row.get("startedAt") or row.get("createdAt") or "")


def outside_runs(automation: dict[str, Any], client, linked_ids: set[str], limit: int, budget: Any) -> dict[str, Any]:
    """The procedure's newest runs that this automation did not start: `Started outside this automation`."""
    fetch = getattr(client, "recent_procedure_runs", None)
    if fetch is None:
        return {"runs": [], "notice": None}
    try:
        rows = fetch(automation["procedureKey"], OUTSIDE_FETCH)
    except Exception:   # the rest of the history still reads
        return {"runs": [], "notice": "outside_unavailable"}
    return {"runs": [outside_entry(run, budget) for run in rows if run.get("id") not in linked_ids][:limit], "notice": None}


def automation_history(automation: dict[str, Any], *, reader: MonitoringReader | None, client, limit: int = DEFAULT_RUN_LIMIT,
                       site_endpoint: str | None = None) -> dict[str, Any]:
    """Router link, recent runs (newest first), the last run and the procedure's other runs for one automation.

    `site_endpoint` confines a site's console to its own publication's rows: the router must list the
    automation's publication with this site's endpoint, so a record that names another publication gets no
    history, however an editor wrote it."""
    limit = max(1, min(int(limit), MAX_RUN_LIMIT))
    empty = {"link": None, "runs": [], "lastRun": None, "skippedAlreadyHadReference": 0, "notice": None,
             "outsideRuns": [], "outsideNotice": None}
    if automation["trigger"]["kind"] != "monitor":
        return {**empty, "link": router_link(automation, None), "notice": NOT_SUPPORTED}
    if reader is None:
        return {**empty, "notice": "monitoring_not_configured"}
    config = automation["trigger"]["config"]
    router = reader.router_config(config["monitorId"])
    link = router_link(automation, router)
    if site_endpoint is not None:
        publication = next((entry for entry in (router or {}).get("publications") or []
                            if entry.get("publicationId") == config.get("publicationId")), None)
        if publication is None:
            return {**empty, "link": link, "notice": "publication_not_routed"}
        if publication.get("appsyncEndpoint") != site_endpoint:
            return {**empty, "notice": "other_publication"}
    rows = reader.trigger_rows(config["monitorId"], config["publicationId"], automation["procedureKey"])
    rows += reader.manual_rows(config["monitorId"], automation["id"])
    budget = (automation.get("limits") or {}).get("budgetUsdPerRun")
    skipped = sum(1 for row in rows if row.get("status") == "notTriggered")
    started = sorted((row for row in rows if row.get("status") != "notTriggered"), key=_row_time, reverse=True)[:limit]
    runs = []
    for row in started:
        run, failed = None, False
        if row.get("runId"):
            try:
                run = read_run(client, row["runId"])
            except Exception:   # a lookup failure is shown on the row; the rest of the history still reads
                failed = True
        runs.append(run_entry(row, run, failed, budget))
    outside = outside_runs(automation, client, {row["runId"] for row in rows if row.get("runId")}, limit, budget)
    return {
        "link": link, "runs": runs, "lastRun": runs[0] if runs else None, "skippedAlreadyHadReference": skipped, "notice": None,
        "outsideRuns": outside["runs"], "outsideNotice": outside["notice"]}


def automation_overview(client, *, reader: MonitoringReader | None, limit: int = DEFAULT_RUN_LIMIT, automation_id: str | None = None,
                        site_endpoint: str | None = None, now: str | None = None) -> dict[str, Any]:
    """Every automation (or one) with its history. Read only."""
    rows = client.list_records("Automation")
    if automation_id:
        rows = [row for row in rows if row.get("id") == automation_id]
    automations = []
    for row in sorted(rows, key=lambda item: str(item.get("title") or item.get("id"))):
        record = read_record(row)
        try:
            history = automation_history(record, reader=reader, client=client, limit=limit, site_endpoint=site_endpoint)
        except Exception as error:   # the records still list when the monitoring table cannot be read
            history = {"link": None, "runs": [], "lastRun": None, "skippedAlreadyHadReference": 0,
                       "notice": "monitoring_unavailable", "noticeDetail": type(error).__name__,
                       "outsideRuns": [], "outsideNotice": None}
        automations.append({**record, **history})
    return {"state": "ready" if automations else "empty", "asOf": now or _now(), "automations": automations,
            "monitoring": "ready" if reader is not None else "not_configured"}


# --- run now --------------------------------------------------------------------------------------------------


def lambda_invoker(function_name: str | None = None):
    """Starts the procedure runner asynchronously, as the router does."""
    name = function_name or os.environ.get("PAPYRUS_PROCEDURE_RUNNER_FUNCTION") or RUNNER_FUNCTION

    def invoke(request: dict) -> None:
        import boto3  # provided by the Lambda runtime and the operator's environment
        boto3.client("lambda").invoke(FunctionName=name, InvocationType="Event", Payload=json.dumps(request).encode("utf-8"))
    return invoke


def resolve_manual_input(automation: dict[str, Any], supplied: Any) -> dict[str, Any]:
    """The input for a Run now: what the person gave, else the record's template when it names no item placeholder."""
    if supplied is not None:
        if not isinstance(supplied, dict):
            raise AutomationError("the input must be a JSON object of name to value.")
        for name in supplied:
            if not PROCEDURE_INPUT_NAME.match(str(name)):
                raise AutomationError(f"input name {name!r} is not a valid procedure input name.")
        return dict(supplied)
    availability = automation.get("runNow") or {}
    if availability.get("needsInput"):
        raise AutomationError("this automation's input uses placeholders for an item (" + ", ".join(availability.get("inputNames") or [])
                              + "); give the input for this run, for example --input '{\"name\": \"value\"}'.")
    return dict(automation.get("inputTemplate") or {})


def run_now(automation: dict[str, Any], *, reader: MonitoringReader | None, writer: MonitoringWriter | None, invoke, actor: str,
            supplied_input: Any = None, site_endpoint: str | None = None, now: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Starts a run of the automation's procedure by hand and links it to the automation's history.

    The run is linked by a `MANUAL#<automationId>#<timestamp>` row in the monitor's partition of the monitoring
    table, beside the trigger rows. The runner updates that row with the run id and the outcome, as it does a
    trigger row, so the history reads both the same way. A start is refused, with the reason and no row, when the
    automation is not a monitor automation, is disabled, has no router publication for this site, or is at its
    maxConcurrent (the router defers such a start and retries it; a person is told at once)."""
    if automation["trigger"]["kind"] not in ACTIVE_KINDS:
        raise AutomationError(f"only monitor automations can be run now; this one is {NOT_SUPPORTED}.")
    if not automation["enabled"]:
        raise AutomationError("this automation is disabled; enable it before running it.")
    if reader is None or (writer is None and not dry_run):
        raise AutomationError("Run now needs the monitoring table, which is not connected to this site's account.")
    config = automation["trigger"]["config"]
    router = reader.router_config(config["monitorId"])
    publication = next((entry for entry in (router or {}).get("publications") or []
                        if entry.get("publicationId") == config["publicationId"]), None)
    if publication is None:
        raise AutomationError("the router does not deliver to this automation's publication, so there is nothing to run it with.")
    if site_endpoint is not None and publication.get("appsyncEndpoint") != site_endpoint:
        raise AutomationError("this automation's publication belongs to another site.")
    if not publication.get("openaiKeyParameter"):
        raise AutomationError("the router publication has no openaiKeyParameter for the procedure's model calls.")
    input_values = resolve_manual_input(automation, supplied_input)
    rows = reader.trigger_rows(config["monitorId"], config["publicationId"], automation["procedureKey"]) \
        + reader.manual_rows(config["monitorId"], automation["id"])
    stamp = now or _now()
    gate = decide({"id": automation["id"], "enabled": True, "limits": limits_of({"limits": automation["limits"]})}, rows,
                  now=datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())
    if gate.action != "start":
        raise AutomationError(gate.reason or "the automation cannot start another run now.")
    key = f"{MANUAL_PREFIX}{automation['id']}#{stamp}"
    pk = f"MONITOR#{config['monitorId']}"
    request = {"publicationId": publication["publicationId"], "appsyncEndpoint": publication["appsyncEndpoint"],
               "openaiKeyParameter": publication["openaiKeyParameter"], "procedureKey": automation["procedureKey"],
               "input": input_values, "actorLabel": f"{actor} (run now)"[:200], "timeoutSeconds": gate.timeout_seconds,
               "trigger": {"kind": "manual", "automationId": automation["id"], "monitorId": config["monitorId"], "pk": pk, "sk": key,
                           "title": f"{automation['procedureKey']}: run now by {actor}"[:200],
                           "summary": f"Started by {actor} with Run now on automation {automation['id']}"[:500]}}
    result = {"started": not dry_run, "dryRun": dry_run, "automationId": automation["id"], "procedureKey": automation["procedureKey"],
              "input": input_values, "timeoutSeconds": gate.timeout_seconds, "requestedBy": actor, "key": key}
    if dry_run:
        return result
    row = {"pk": pk, "sk": key, "publicationId": publication["publicationId"], "procedureKey": automation["procedureKey"],
           "automationId": automation["id"], "requestedBy": actor, "createdAt": stamp, "startedAt": stamp, "status": "starting",
           "request": request}
    writer.put(row)
    try:
        invoke(request)
    except Exception as error:   # nothing started: the row says so, and the person is told
        writer.put({**row, "status": "startFailed", "error": f"{type(error).__name__}"})
        raise AutomationError(f"the procedure runner could not be started ({type(error).__name__}).") from error
    return result


# --- the command line -----------------------------------------------------------------------------------------


def _json_option(options: dict[str, Any], key: str) -> Any:
    if key not in options:
        return None
    try:
        return json.loads(str(options[key]))
    except json.JSONDecodeError as error:
        raise AutomationError(f"--{key} must be JSON: {error}") from error


def fields_from_options(options: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Only what the operator set, so an update leaves everything else alone."""
    fields: dict[str, Any] = {}
    for option, field in (("id", "id"), ("title", "title"), ("description", "description"),
                          ("procedure", "procedureKey"), ("enabled", "enabled")):
        if option in options:
            fields[field] = options[option]
    if "input" in options:
        fields["inputTemplate"] = _json_option(options, "input")
    kind = options.get("kind")
    if "on-stage" in options and kind is None:
        kind = "event"
    if kind or "monitor" in options or "publication" in options or "config" in options or "on-stage" in options or "next-stage" in options:
        current = (existing or {}).get("trigger") or {}
        config = dict(current.get("config") or {}) if (kind in (None, current.get("kind"))) else {}
        if "config" in options:
            config = _json_option(options, "config")
        if "monitor" in options:
            config["monitorId"] = options["monitor"]
        if "publication" in options:
            config["publicationId"] = options["publication"]
        if "on-stage" in options:
            config["event"], config["onStage"] = STAGE_ENTERED, options["on-stage"]
        if "next-stage" in options:
            config["nextStage"] = options["next-stage"]
        fields["trigger"] = {"kind": kind or current.get("kind") or ("monitor" if "monitor" in options else None), "config": config}
    limits, cleared = {}, set()
    for option, field, cast in (("timeout-seconds", "timeoutSeconds", int), ("max-concurrent", "maxConcurrent", int),
                                ("budget-usd", "budgetUsdPerRun", float),
                                ("max-hops", "maxHops", int)):
        if option in options:
            if option == "max-concurrent" and str(options[option]).lower() in {"none", "unlimited"}:
                cleared.add(field)
                continue
            try:
                limits[field] = cast(options[option])
            except (TypeError, ValueError) as error:
                raise AutomationError(f"--{option} must be a number.") from error
    if limits or cleared:
        fields["limits"] = {key: value for key, value in {**((existing or {}).get("limits") or {}), **limits}.items() if key not in cleared}
    return fields


def _line(record: dict[str, Any], history: dict[str, Any] | None = None) -> str:
    last = (history or {}).get("lastRun") or {}
    return "\t".join(["automations", record["id"], record["trigger"]["kind"] + ("" if record["supported"] else f" ({NOT_SUPPORTED})"),
                      record["procedureKey"] or "", "enabled" if record["enabled"] else "disabled", last.get("status") or "no runs"])


def cost_text(entry: dict[str, Any]) -> str:
    if entry.get("costUsd") is None:
        return "cost unknown"
    return f"${entry['costUsd']:.4f}" + (" OVER BUDGET" if entry.get("overBudget") else "")


def _print_runs(runs: list[dict[str, Any]]) -> None:
    for run in runs:
        who = f"run now by {run['requestedBy']}" if run.get("origin") == "manual" else (run["sourceId"] or "")
        print("\t".join(str(part) for part in (
            "run", run["startedAt"] or "", run["status"] or "", f"{run['durationSeconds']} s" if run["durationSeconds"] is not None else "-",
            who, run["runId"] or "-", run["storyId"] or "-", cost_text(run), run["reason"] or run["error"] or "")))


def _print_outside_runs(runs: list[dict[str, Any]]) -> None:
    if runs:
        print("outside\tStarted outside this automation:")
    for run in runs:
        print("\t".join(str(part) for part in (
            "outside", run["startedAt"] or "", run["status"] or "", f"{run['durationSeconds']} s" if run["durationSeconds"] is not None else "-",
            run["requestedBy"] or "", run["runId"] or "-", run["storyId"] or "-", cost_text(run), run["error"] or "")))


def noticeless(automation: dict[str, Any]) -> str:
    return str(automation.get("notice") or "")


def run_command(command: str, flags: list[str]) -> None:
    """`papyrus automations list|show|runs|run|create|update`. Reads use the selected GraphQL lane; the monitoring table uses AWS credentials."""
    from .graphql_authoring import create_authoring_client
    from .options import parse_boolean_option, parse_options, resolve_mutation_apply

    options = parse_options(flags)
    as_json = parse_boolean_option(options.get("json"), False, "--json")
    limit = int(options["limit"]) if isinstance(options.get("limit"), str) else DEFAULT_RUN_LIMIT
    if command in {"create", "update"}:
        apply = resolve_mutation_apply(options, f"automations {command}")
        client = create_authoring_client()[0]
        actor = os.environ.get("PAPYRUS_ACTOR_LABEL") or "papyrus-cli"
        if command == "create":
            fields = fields_from_options(options)
            if "enabled" not in fields:
                fields["enabled"] = True
            result = (create_automation(client, fields, actor=actor) if apply
                      else read_record(stored_payload(build_record(fields, actor=actor))))
        else:
            record_id = options.get("id")
            if not isinstance(record_id, str):
                raise AutomationError("papyrus automations update needs --id <automation id>.")
            row = client.get_record("Automation", record_id)
            if not row:
                raise AutomationError(f"automation {record_id} does not exist.")
            existing = read_record(row)
            fields = fields_from_options(options, existing=existing)
            result = (update_automation(client, record_id, fields, actor=actor) if apply
                      else read_record(stored_payload(build_record({**fields, "id": record_id}, existing=existing, actor=actor))))
        if as_json:
            print(json.dumps({"ok": True, "command": f"automations {command}", "dryRun": not apply, "automation": result}, indent=2))
        else:
            print(_line(result) + ("\t(dry run, nothing written)" if not apply else f"\t{command}d"))
        return
    if command == "run":
        record_id = options.get("id")
        if not isinstance(record_id, str):
            raise AutomationError("papyrus automations run needs --id <automation id>.")
        dry_run = not resolve_mutation_apply(options, "automations run")
        client = create_authoring_client()[0]
        row = client.get_record("Automation", record_id)
        if not row:
            raise AutomationError(f"automation {record_id} does not exist.")
        table = monitoring_table_from_environment()
        result = run_now(read_record(row), reader=MonitoringReader(table) if table is not None else None,
                         writer=MonitoringWriter(table) if table is not None else None, invoke=lambda_invoker(),
                         actor=os.environ.get("PAPYRUS_ACTOR_LABEL") or "papyrus-cli", supplied_input=_json_option(options, "input"),
                         dry_run=dry_run)
        if as_json:
            print(json.dumps({"ok": True, "command": "automations run", **result}, indent=2))
        else:
            print("\t".join(["automations", record_id, "dry run, nothing started" if dry_run else "started",
                             f"timeout {result['timeoutSeconds']} s", json.dumps(result["input"])]))
        return
    if command not in {"list", "show", "runs"}:
        raise ValueError(f"Unsupported papyrus automations command: {command}")
    client = create_authoring_client()[0]
    try:
        reader = monitoring_reader_from_environment()
        reader_error = None if reader is not None else "monitoring_not_configured"
    except Exception as error:   # no AWS credentials for the monitoring account: records still list
        reader, reader_error = None, f"monitoring unavailable: {type(error).__name__}"
    target = options.get("id") if isinstance(options.get("id"), str) else None
    if command in {"show", "runs"} and not target:
        raise AutomationError(f"papyrus automations {command} needs --id <automation id>.")
    if command == "runs" and reader is None:
        raise AutomationError(f"the run history needs the monitoring table: {reader_error}.")
    overview = automation_overview(client, reader=reader, limit=limit if command == "runs" else 1, automation_id=target)
    if target and not overview["automations"]:
        raise AutomationError(f"automation {target} does not exist.")
    if as_json:
        print(json.dumps({"ok": True, "command": f"automations {command}", "monitoring": reader_error or "ready", **overview}, indent=2, default=str))
        return
    for automation in overview["automations"]:
        if command == "list":
            print(_line(automation, automation))
        elif command == "show":
            print(_line(automation, automation))
            print(f"title\t{automation['title']}\nprocedure\t{automation['procedureKey']}\ntrigger\t{json.dumps(automation['trigger'])}")
            print(f"input\t{json.dumps(automation['inputTemplate'])}\nlimits\t{json.dumps(automation['limits'])} ({automation['limitsNote']})")
            print(f"enabled\t{automation['enabled']} ({ENABLED_NOTE})")
            link = automation["link"] or {"state": "not checked", "text": noticeless(automation)}
            print(f"router\t{link['state']}\t{link.get('text') or ''}")
            if reader_error:
                print(f"runs\t{reader_error}")
        else:
            _print_runs(automation["runs"])
            _print_outside_runs(automation["outsideRuns"])
            if automation["outsideNotice"]:
                print(f"outside\tthe procedure's other runs could not be read ({automation['outsideNotice']})")
            if automation["skippedAlreadyHadReference"]:
                print(f"skipped\t{automation['skippedAlreadyHadReference']} item(s) not started because the Reference already existed")
            known = [run["costUsd"] for run in automation["runs"] if run["costUsd"] is not None]
            print(f"cost\t${sum(known):.4f} over {len(known)} of {len(automation['runs'])} listed run(s) with a recorded cost (an estimate)")
