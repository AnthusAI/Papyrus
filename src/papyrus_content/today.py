"""Today: what the system did on one day, what it decided to do nothing about, and what it cost (PPY-5bcf42, slice H1).

One read path for the newsroom home's Today section, the `papyrus today` command and the site's `todayOverview` query
(docs/design/always-on-agents-architecture.md section 7.1). It is read only and it reads by index:

* the day's runs are one key-condition query per run status on the `ProcedureRun` status index (`runStatus` + `requestedAt`,
  `listProcedureRunsByStatusAndRequestedAt`): only the rows requested inside the day are read, never the whole table;
* the agents that did not run are the site's Automation records, read through the Automation `tenantId` index (a handful of
  configuration rows, not a log).

`RUN_STATUSES` is every status a run can have. A status added later has to be named here, or its runs would be missing from Today;
`today_test.py` holds the list against the statuses the runner writes.

A responsibility's row is keyed by the run's `responsibility` (slice A1); a run without one is keyed by its automation, and a run
with neither by its procedure. Outcomes are the five words of `run_outcomes`, each shown with its mark; a run that has no outcome is
counted in words too (`Not finished yet`, `Recorded before outcomes`), so every run is in exactly one count.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import overdue, run_outcomes
from .responsibilities import BY_KEY as RESPONSIBILITIES
from .automations import ENABLED_NOTE, NOT_SUPPORTED, read_record
from .run_outcomes import OUTCOME_SHOWN
from .tenancy import rows_for_tenant
from .announcements.sends import NO_COST, sends_of_day

#: Every `runStatus` the runner writes. Each is one index query for the day.
RUN_STATUSES = ("queued", "started", "running", "completed", "failed", "notRunnable")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_TIME_ZONE = "UTC"
SORT_KEY = "requestedAt"

#: The count that holds a run which has no outcome, with the words it is shown in.
COUNT_KEYS = ("acted", "nothing", "asked", "failed", "unknown", "notFinished", "beforeOutcomes")
OTHER_SHOWN = {"notFinished": ("…", run_outcomes.NOT_FINISHED), "beforeOutcomes": ("", run_outcomes.BEFORE_OUTCOMES)}

DID_NOT_RUN = "Did not run"
WHY_DISABLED = f"Disabled: {ENABLED_NOTE}"
WHY_UNSUPPORTED = f"{NOT_SUPPORTED}: nothing starts this kind of agent"
WHY_NO_WAKE = "Nothing woke it today"


class TodayError(ValueError):
    """The request names a day or a time zone that does not exist."""


def day_bounds(day: str | None, time_zone: str | None, now: datetime) -> dict[str, str]:
    """The day (default: today in `time_zone`) as the UTC instants it starts and ends, in the form `requestedAt` is stored in."""
    zone_name = time_zone or DEFAULT_TIME_ZONE
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as error:
        raise TodayError(f"{zone_name!r} is not a time zone name such as America/New_York.") from error
    if day is None:
        first = now.astimezone(zone).date()
    elif DAY.match(day):
        try:
            first = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError as error:
            raise TodayError(f"{day!r} is not a date.") from error
    else:
        raise TodayError(f"{day!r} is not a date written YYYY-MM-DD.")
    start = datetime.combine(first, time.min, zone)
    end = datetime.combine(first + timedelta(days=1), time.min, zone)
    return {"day": first.isoformat(), "timeZone": zone_name, "start": _instant(start), "end": _instant(end)}


def _instant(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read_day(client, bounds: dict[str, str]) -> list[dict[str, Any]]:
    """The runs requested inside the day, newest last. One key-condition query per status; the end of the day is exclusive."""
    runs: list[dict[str, Any]] = []
    for status in RUN_STATUSES:
        rows = client.list_by_index("procedureRunsByStatus", status, sort_condition={"between": [bounds["start"], bounds["end"]]})
        runs.extend(row for row in rows_for_tenant("ProcedureRun", getattr(client, "tenant_id", None), rows)
                    if bounds["start"] <= str(row.get(SORT_KEY) or "") < bounds["end"])
    return sorted(runs, key=lambda row: str(row.get(SORT_KEY)))


def _cost(row: dict[str, Any]) -> float | None:
    cost = row.get("costUsd")
    return float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None


def _bucket(row: dict[str, Any]) -> str:
    outcome = row.get("outcome")
    if outcome in OUTCOME_SHOWN:
        return str(outcome)
    return "beforeOutcomes" if row.get("runStatus") in run_outcomes.FINISHED_STATUSES else "notFinished"


def run_line(row: dict[str, Any]) -> dict[str, Any]:
    """One run as Today lists it: its outcome in words with its mark, why, what it was for and what it cost."""
    return {
        "runId": row.get("id"), "procedureKey": row.get("procedureKey"), "automationId": row.get("automationId") or None,
        "requestedAt": row.get("requestedAt"), "finishedAt": row.get("finishedAt"), "runStatus": row.get("runStatus"),
        "outcome": row.get("outcome") or None, "outcomeReason": row.get("outcomeReason") or None,
        "outcomeShown": run_outcomes.outcome_shown(row), "rung": row.get("rung") or None,
        "subjectKind": row.get("subjectKind") or None, "subjectId": row.get("subjectId") or None, "costUsd": _cost(row),
        "error": (str(row["errorSummary"])[:300] if row.get("errorSummary") else None),
    }


def _group_of(row: dict[str, Any], titles: dict[str, str]) -> tuple[str, str, str]:
    """(key, kind, title) of the row a run is counted in."""
    responsibility = row.get("responsibility")
    if responsibility:
        entry = RESPONSIBILITIES.get(str(responsibility))
        return f"responsibility:{responsibility}", "responsibility", entry.title if entry else str(responsibility)
    automation = row.get("automationId")
    if automation:
        return f"automation:{automation}", "automation", titles.get(str(automation)) or str(automation)
    return f"procedure:{row.get('procedureKey')}", "procedure", str(row.get("procedureKey") or "unknown procedure")


def _empty_group(key: str, kind: str, title: str) -> dict[str, Any]:
    return {"key": key, "kind": kind, "title": title, "counts": dict.fromkeys(COUNT_KEYS, 0), "reasons": {}, "automationIds": [],
            "costUsd": 0.0, "costKnownRuns": 0, "costUnknownRuns": 0, "runs": []}


def _count(group: dict[str, Any], row: dict[str, Any]) -> None:
    bucket = _bucket(row)
    group["counts"][bucket] += 1
    reason = row.get("outcomeReason")
    if reason and bucket in ("nothing", "asked", "failed", "unknown"):
        by_outcome = group["reasons"].setdefault(bucket, {})
        by_outcome[str(reason)] = by_outcome.get(str(reason), 0) + 1
    cost = _cost(row)
    if cost is None:
        group["costUnknownRuns"] += 1
    else:
        group["costKnownRuns"] += 1
        group["costUsd"] += cost
    if row.get("automationId") and row["automationId"] not in group["automationIds"]:
        group["automationIds"].append(row["automationId"])
    group["runs"].append(run_line(row))


def did_not_run(records: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The site's agents that started nothing in the day, each with why in words. A run with no automation id counts for the automation
    that owns its procedure."""
    ran_ids = {row.get("automationId") for row in runs if row.get("automationId")}
    ran_procedures = {row.get("procedureKey") for row in runs if not row.get("automationId")}
    found = []
    for record in sorted(records, key=lambda item: str(item.get("title") or item.get("id"))):
        if record["id"] in ran_ids or record.get("procedureKey") in ran_procedures:
            continue
        if not record["enabled"]:
            code, why = "disabled", WHY_DISABLED
        elif not record["supported"]:
            code, why = "unsupported", WHY_UNSUPPORTED
        else:
            code, why = "no_wake", WHY_NO_WAKE
        found.append({"automationId": record["id"], "title": record.get("title") or record["id"], "state": DID_NOT_RUN,
                      "whyCode": code, "why": why})
    return found


def today_overview(client, *, day: str | None = None, time_zone: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Today for one day. Read only."""
    moment = now or datetime.now(timezone.utc)
    bounds = day_bounds(day, time_zone, moment)
    runs = read_day(client, bounds)
    records = [read_record(row) for row in client.list_tenant_rows("Automation", "id title description enabled trigger procedureKey inputTemplate limits")]
    titles = {record["id"]: record.get("title") for record in records}
    groups: dict[str, dict[str, Any]] = {}
    for row in runs:
        key, kind, title = _group_of(row, titles)
        _count(groups.setdefault(key, _empty_group(key, kind, title)), row)
    rows = sorted(groups.values(), key=lambda group: group["title"].lower())
    for group in rows:
        group["costUsd"] = round(group["costUsd"], 6)
    totals = dict.fromkeys(COUNT_KEYS, 0)
    for group in rows:
        for key in COUNT_KEYS:
            totals[key] += group["counts"][key]
    return {
        "state": "ready", "asOf": _instant(moment), **bounds, "overdue": overdue.read(client, moment), "rows": rows, "didNotRun": did_not_run(records, runs), "sends": sends_of_day(client, bounds),
        "totals": {"runs": len(runs), "counts": totals, "costUsd": round(sum(group["costUsd"] for group in rows), 6),
                   "costKnownRuns": sum(group["costKnownRuns"] for group in rows), "costUnknownRuns": sum(group["costUnknownRuns"] for group in rows)},
    }


# --- the words -------------------------------------------------------------------------------------------------------


def dollars(value: float) -> str:
    return f"${value:.2f}" if value == 0 or value >= 0.01 else f"${value:.4f}"


def cost_text(costs: dict[str, Any]) -> str:
    """`$0.41`, with how many runs recorded no cost when some did not."""
    unknown = costs["costUnknownRuns"]
    known = costs["costKnownRuns"]
    if not known and not unknown:
        return "no runs"
    if not known:
        return f"cost unknown for {unknown} run{'' if unknown == 1 else 's'}"
    base = dollars(costs["costUsd"])
    return base if not unknown else f"{base} (cost unknown for {unknown} run{'' if unknown == 1 else 's'})"


def counts_text(counts: dict[str, int]) -> str:
    """Every outcome that has runs, each as its mark, its words and its count: `✓ Did it 6, – Nothing to do 1`."""
    parts = []
    for outcome, (mark, words) in OUTCOME_SHOWN.items():
        if counts[outcome]:
            parts.append(f"{mark} {words} {counts[outcome]}")
    for key, (mark, words) in OTHER_SHOWN.items():
        if counts[key]:
            parts.append(f"{mark + ' ' if mark else ''}{words} {counts[key]}")
    return ", ".join(parts)


def send_text(send: dict[str, Any]) -> str:
    """One send as a line: where it stands, the lists, the items, the counts and the cost."""
    items = f"{send['items']} item{'' if send['items'] == 1 else 's'}"
    cost = dollars(float(send["cost"])) if send["cost"] is not None else NO_COST
    return f"{send['stateShown']} · {', '.join(send['lists']) or 'no lists'} · {items} · {send['countsText']} · {cost}"


def reasons_text(reasons: dict[str, int]) -> str:
    return ", ".join(f"{count} {code}" for code, count in sorted(reasons.items()))


def day_title(overview: dict[str, Any]) -> str:
    return f"{overview['day']} ({overview['timeZone']})"


def render(overview: dict[str, Any]) -> list[str]:
    """The plain text of Today: one line per responsibility, nothing-to-do reasons under it, then the agents that did not run."""
    lines = [f"TODAY · {day_title(overview)} · as of {overview['asOf']}"]
    totals = overview["totals"]
    if overview["overdue"]:   # what only a person can move comes first (slice C4)
        lines.append(f"NEEDS ATTENTION · {len(overview['overdue'])} overdue")
        lines.extend(f"  {entry['shown']}" for entry in overview["overdue"])
    lines.append(f"WHAT RAN · {totals['runs']} run{'' if totals['runs'] == 1 else 's'} · {cost_text(totals)}")
    if not overview["rows"]:
        lines.append("  Nothing ran in this day.")
    for group in overview["rows"]:
        lines.append(f"  {group['title']}: {counts_text(group['counts'])} · {cost_text(group)}")
        for outcome in ("nothing", "asked", "failed", "unknown"):
            if group["reasons"].get(outcome):
                mark, words = OUTCOME_SHOWN[outcome]
                lines.append(f"    {mark} {words}: {reasons_text(group['reasons'][outcome])}")
        for target in group["automationIds"]:
            lines.append(f"    runs: papyrus automations runs --id {target}")
    if overview["sends"]:
        lines.append(f"SENDS · {len(overview['sends'])} email send{'' if len(overview['sends']) == 1 else 's'}")
        lines.extend(f"  {send_text(send)}" for send in overview["sends"])
    if overview["didNotRun"]:
        lines.append("DID NOT RUN")
        for entry in overview["didNotRun"]:
            lines.append(f"  – {entry['title']}: {entry['state']}. {entry['why']}.")
    return lines


def print_runs(overview: dict[str, Any], out) -> None:
    for group in overview["rows"]:
        for run in group["runs"]:
            reason = run["error"] or ""
            cost = "cost unknown" if run["costUsd"] is None else dollars(run["costUsd"])
            print("\t".join(str(part) for part in ("run", group["title"], run["requestedAt"] or "", run["outcomeShown"], run["runId"] or "-", cost, reason)), file=out)


def command(options: dict[str, Any], *, as_json: bool, client=None, out=None, now: datetime | None = None) -> int:
    """`papyrus today [--day YYYY-MM-DD] [--time-zone ZONE] [--runs] [--json] [--site HOST]`. Asks the site's own `todayOverview` with the
    signed-in session (editors and admins); the server does the index reads."""
    from . import signed_in_lane as lane
    from .options import parse_boolean_option
    out = out or sys.stdout
    try:
        day = options.get("day") if isinstance(options.get("day"), str) else None
        zone = options.get("time-zone") if isinstance(options.get("time-zone"), str) else None
        site = options.get("site") if isinstance(options.get("site"), str) else None
        client = client or lane.client(site)
        overview = lane.fetch(client, OVERVIEW_QUERY, "todayOverview", {"day": day, "timeZone": zone}, noun="Today",
                              forbidden=lambda: lane.Refusal("Refused: Today is for editors and admins; your signed-in account does not have that access."))
        if overview.get("state") != "ready":
            raise lane.Refusal("Today is unavailable for this site right now." if overview.get("state") == "unavailable"
                               else f"Today refused the request: {overview.get('message') or overview.get('error') or 'bad request'}")
    except lane.Refusal as refusal:
        print(str(refusal), file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps({"ok": True, "command": "today", **overview}, indent=2, default=str), file=out)
        return 0
    for line in render(overview):
        print(line, file=out)
    if parse_boolean_option(options.get("runs"), False, "--runs"):
        print_runs(overview, out)
    return 0


OVERVIEW_QUERY = "query TodayOverview($day: String, $timeZone: String) { todayOverview(day: $day, timeZone: $timeZone) }"
