"""Today v2: what only a person can move, then what is due today (PPY-b6d5ad, slice H2 of docs/design/always-on-agents-architecture.md).

The top of Today is the list of things only a person can move, each with its one action beside it:

* **Waiting for you**: every open hard gate and soft review (a question for a person), hard gates first. Its action is Answer: the request opens
  in the Notification Center, where it is approved, rejected or answered with feedback.
* **Needs attention**: runs whose outcome is unknown (action Settle) and failures nobody has acknowledged (action Acknowledge), both read from
  the sparse attention index of `run_attention`; records that are Overdue (`overdue`, action Wake now); and open flags (action Open). A flag the
  overdue check raised for a record already listed as Overdue is not listed twice. Invariant alerts (slice J6) are raised as flags, so they show here.

Then **Due today**: every time in the site's day that something will happen unless a person acts, in the site's time zone: a Delivery's lock,
release and next attempt (the Delivery due index), a Story scheduled to publish (the schedule index), an agent's scheduled wake (the schedule in
its registered definition, on the Automation records Today already reads) and a soft review's deadline (from the open requests read above).

Every read is an index: the open partition of the review request state index, the attention index, the Delivery due index and the Story schedule
index. Nothing here writes; acknowledging and settling are `run_attention.acknowledge`, behind the `acknowledgeRun` mutation and
`papyrus automations acknowledge`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from . import run_attention
from .cron_fires import fires_between
from .announcements.deliveries import INDEX_BY_DUE
from .announcements.records import due_key, pending_named_times
from .automations import read_record
from .overdue import settled_before
from .responsibilities import BY_KEY as RESPONSIBILITIES
from .run_outcomes import OUTCOME_SHOWN
from .tenancy import rows_for_tenant

SITE_TIME_ZONE_ENV = "PAPYRUS_PUBLICATION_TIME_ZONE"   # the site's publication.timeZone, the same setting scheduled publishing reads

WAITING_MODES = ("hard_gate", "soft_review")
MODE_WORDS = {"hard_gate": "Hard gate: nothing proceeds without an answer", "soft_review": "Soft review", "flag": "Flag"}
QUESTION_MARK, FLAG_MARK = "?", "⚑"
ACTIONS = {
    "answer": "Answer", "settle": "Settle", "acknowledge": "Acknowledge", "wake_now": "Wake now", "open": "Open",
}
SETTLE_NOTE = "Look at what it wrote, then settle it: the run leaves this list and stays in the history as Outcome unknown."
WAKE_NOW_NOTE = "Wake now is the agents wake operation. Until it is there, the operations check sends this wake again on its daily run."

DUE_WORDS = {
    "lockAt": "Locks", "releaseAt": "Goes out", "nextAttemptAt": "Next attempt", "scheduledPublishAt": "Publishes",
    "schedule": "Scheduled wake", "deadline": "Review deadline: goes on without review",
}
SCHEDULED_STATE = "scheduled"


def site_time_zone(environment: Mapping[str, str]) -> str | None:
    """The site's own time zone (its publication.timeZone), or None when the site names none."""
    return (environment.get(SITE_TIME_ZONE_ENV) or "").strip() or None


# --- times in words ------------------------------------------------------------------------------------------------


def _moment(value: Any) -> datetime:
    text = str(value).strip()
    moment = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def local_time(value: Any, time_zone: str, day: str) -> str | None:
    """A stored UTC time as a person in the site reads it: ``3:30 AM`` on the day Today shows, ``Tuesday 17 November, 3:30 AM`` on another."""
    if not value:
        return None
    local = _moment(value).astimezone(ZoneInfo(time_zone))
    clock = f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"
    if local.date().isoformat() == day:
        return clock
    return f"{local.strftime('%A')} {local.day} {local.strftime('%B')}, {clock}"


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- waiting for you ------------------------------------------------------------------------------------------------


def _subject_words(subject: Mapping[str, Any]) -> str:
    kind, ident = str(subject.get("type") or "item").replace("_", " "), subject.get("id")
    return f"{kind} {ident}" if ident else kind


def review_line(request: Mapping[str, Any], time_zone: str, day: str) -> dict[str, Any]:
    """One open review request as Today lists it, with its mark, its words and its one action."""
    mode = request.get("mode")
    action = "open" if mode == "flag" else "answer"
    return {
        "kind": "review", "id": request["id"], "mode": mode, "modeWords": MODE_WORDS.get(str(mode), str(mode)),
        "mark": FLAG_MARK if mode == "flag" else QUESTION_MARK, "reason": request.get("reason") or "", "ask": request.get("ask") or None,
        "subject": dict(request.get("subject") or {}), "subjectWords": _subject_words(request.get("subject") or {}),
        "raisedBy": request.get("raisedBy"), "raisedAt": request.get("raisedAt"),
        "deadline": request.get("deadline") or None, "deadlineLocal": local_time(request.get("deadline"), time_zone, day),
        "action": {"kind": action, "words": ACTIONS[action], "requestId": request["id"],
                   "command": f"papyrus reviews show --id {request['id']}" if action == "open" else f"papyrus reviews answer --id {request['id']} --decision approve|reject"},
    }


def waiting_for_you(open_requests: Iterable[Mapping[str, Any]], time_zone: str, day: str) -> list[dict[str, Any]]:
    """The open hard gates first, oldest first; then the open soft reviews, the soonest deadline first and those with none after, oldest first."""
    requests = [request for request in open_requests if request.get("mode") in WAITING_MODES]
    gates = sorted((request for request in requests if request["mode"] == "hard_gate"), key=lambda request: str(request.get("raisedAt") or ""))
    reviews = sorted((request for request in requests if request["mode"] == "soft_review"),
                     key=lambda request: (0, str(request["deadline"])) if request.get("deadline") else (1, str(request.get("raisedAt") or "")))
    return [review_line(request, time_zone, day) for request in (*gates, *reviews)]


# --- needs attention ------------------------------------------------------------------------------------------------


def _responsibility_title(run: Mapping[str, Any]) -> str:
    responsibility = run.get("responsibility")
    if responsibility and str(responsibility) in RESPONSIBILITIES:
        return RESPONSIBILITIES[str(responsibility)].title
    return str(run.get("automationId") or run.get("procedureKey") or "unknown procedure")


def attention_run_line(run: Mapping[str, Any], time_zone: str, day: str) -> dict[str, Any]:
    """A run on the attention list: Outcome unknown is settled, a failure is acknowledged. Either takes it off the list."""
    outcome = str(run.get("outcome"))
    action = "settle" if outcome == "unknown" else "acknowledge"
    mark, words = OUTCOME_SHOWN.get(outcome, ("!", outcome))
    subject = {"type": run.get("subjectKind"), "id": run.get("subjectId")} if run.get("subjectId") else None
    return {
        "kind": "run", "id": run["id"], "outcome": outcome, "mark": mark, "words": words, "reason": run.get("outcomeReason") or None,
        "title": _responsibility_title(run), "automationId": run.get("automationId") or None, "procedureKey": run.get("procedureKey"),
        "subject": subject, "subjectWords": _subject_words(subject) if subject else None,
        "neededAt": run.get("dueAt") or run.get("finishedAt"), "neededLocal": local_time(run.get("dueAt") or run.get("finishedAt"), time_zone, day),
        "error": str(run["errorSummary"])[:300] if run.get("errorSummary") else None,
        "action": {"kind": action, "words": ACTIONS[action], "runId": run["id"], "command": f"papyrus automations acknowledge --run {run['id']}",
                   "note": SETTLE_NOTE if action == "settle" else None},
    }


def overdue_line(entry: Mapping[str, Any], time_zone: str, day: str) -> dict[str, Any]:
    """An Overdue record (`overdue.read`), with its due time in the site's zone. Its action is Wake now, which the agents wake operation provides."""
    return {**entry, "kind": "overdue", "record": entry["kind"], "dueLocal": local_time(entry["dueAt"], time_zone, day),
            "action": {"kind": "wake_now", "words": ACTIONS["wake_now"], "record": entry["kind"], "recordId": entry["id"], "available": False, "note": WAKE_NOW_NOTE}}


def needs_attention(attention_runs: Iterable[Mapping[str, Any]], overdue_entries: Iterable[Mapping[str, Any]], open_requests: Iterable[Mapping[str, Any]],
                    time_zone: str, day: str) -> list[dict[str, Any]]:
    """Outcome unknown first, then failures, then Overdue records, then open flags, each oldest first."""
    runs = [run for run in attention_runs if run_attention.needs_attention(run)]
    overdue = list(overdue_entries)
    listed_as_overdue = {entry["flagId"] for entry in overdue}
    flags = sorted((request for request in open_requests if request.get("mode") == "flag" and request["id"] not in listed_as_overdue),
                   key=lambda request: str(request.get("raisedAt") or ""))
    unknown = [attention_run_line(run, time_zone, day) for run in runs if run.get("outcome") == "unknown"]
    failed = [attention_run_line(run, time_zone, day) for run in runs if run.get("outcome") == "failed"]
    return [*unknown, *failed, *(overdue_line(entry, time_zone, day) for entry in overdue), *(review_line(request, time_zone, day) for request in flags)]


# --- due today ------------------------------------------------------------------------------------------------------


def _due_entry(kind: str, what: str, at: str, time_zone: str, day: str, *, title: str, record_id: str, detail: str | None = None) -> dict[str, Any]:
    return {"kind": kind, "what": what, "words": DUE_WORDS[what], "at": at, "local": local_time(at, time_zone, day), "title": title, "id": record_id, "detail": detail}


def due_deliveries(client: Any, bounds: Mapping[str, str], time_zone: str, overdue_before: str) -> list[dict[str, Any]]:
    """Each pending time of a Delivery (lock, release, next attempt) that falls in the day. One query on the sparse Delivery due index, up to the day's end:
    a Delivery whose earliest pending time is before the day can still lock or go out in it. A pending time at or before ``overdue_before`` is Overdue and
    listed under Needs attention instead."""
    start, end, day = _iso(_moment(bounds["start"])), _iso(_moment(bounds["end"])), bounds["day"]
    overdue_cut = _iso(_moment(overdue_before))
    rows = rows_for_tenant("Delivery", getattr(client, "tenant_id", None), client.list_by_index(INDEX_BY_DUE, due_key(), sort_condition={"lt": end}))
    found = []
    for row in rows:
        for name, at in pending_named_times(row):
            if start <= _iso(_moment(at)) < end and _iso(_moment(at)) > overdue_cut:
                detail = None
                if name == "lockAt":
                    detail = "approved" if row.get("approvedVersion") else "not yet approved"
                elif name == "nextAttemptAt" and row.get("waitingFor"):
                    detail = f"waiting for {row['waitingFor']}"
                found.append(_due_entry("delivery", name, _iso(_moment(at)), time_zone, day, title=f"{row.get('channel')} {row.get('accountId')}",
                                        record_id=row["id"], detail=detail))
    return found


def due_story_publishes(client: Any, bounds: Mapping[str, str], time_zone: str) -> list[dict[str, Any]]:
    """The Stories scheduled to publish in the day, from the sparse schedule index with the day as its range."""
    start, end, day = _iso(_moment(bounds["start"])), _iso(_moment(bounds["end"])), bounds["day"]
    rows = rows_for_tenant("Item", getattr(client, "tenant_id", None), client.list_schedule(SCHEDULED_STATE, start, end))
    return [_due_entry("story", "scheduledPublishAt", _iso(_moment(row["scheduledPublishAt"])), time_zone, day,
                       title=str(row.get("headline") or row.get("title") or row.get("lineageId") or row["id"]), record_id=str(row.get("lineageId") or row["id"]))
            for row in rows if row.get("scheduledPublishAt") and start <= _iso(_moment(row["scheduledPublishAt"])) < end]


def due_agent_wakes(automation_rows: list[dict[str, Any]], bounds: Mapping[str, str], time_zone: str) -> list[dict[str, Any]]:
    """Each time in the day an agent's registered schedule wakes it, for the agents that are switched on. A registered schedule was checked when it was
    registered, with the same refusals the scheduler's entry has."""
    start, end, day = _moment(bounds["start"]), _moment(bounds["end"]), bounds["day"]
    found = []
    for record in sorted((read_record(row) for row in automation_rows), key=lambda record: str(record["id"])):
        schedule = ((record.get("definition") or {}).get("wakes") or {}).get("schedule")   # the registered schedule, as agent_definitions.release reads it
        if not schedule or record.get("definitionRetiredAt") or not record["enabled"]:
            continue
        automation_id, title = record["id"], str(record.get("title") or record["id"])
        found.extend(_due_entry("schedule", "schedule", _iso(instant), time_zone, day, title=title, record_id=automation_id,
                                detail=f"{schedule['cron']} in {schedule['timeZone']}")
                     for instant in fires_between(str(schedule["cron"]), str(schedule["timeZone"]), start, end))
    return found


def due_review_deadlines(open_requests: Iterable[Mapping[str, Any]], bounds: Mapping[str, str], time_zone: str, overdue_before: str) -> list[dict[str, Any]]:
    """The open soft reviews whose deadline falls in the day: at the deadline the work goes on without review. A deadline at or before ``overdue_before``
    is Overdue and listed under Needs attention instead."""
    start, end, day = _iso(_moment(bounds["start"])), _iso(_moment(bounds["end"])), bounds["day"]
    overdue_cut = _iso(_moment(overdue_before))
    return [_due_entry("review", "deadline", _iso(_moment(request["deadline"])), time_zone, day, title=str(request.get("reason") or request["id"]), record_id=request["id"])
            for request in open_requests
            if request.get("mode") == "soft_review" and request.get("deadline") and start <= _iso(_moment(request["deadline"])) < end
            and _iso(_moment(request["deadline"])) > overdue_cut]


def due_today(client: Any, bounds: Mapping[str, str], time_zone: str, automation_rows: list[dict[str, Any]], open_requests: list[dict[str, Any]],
              now: datetime) -> list[dict[str, Any]]:
    """Everything due in the day, earliest first. What is already Overdue (`overdue.settled_before`) is under Needs attention, not here."""
    overdue_before = settled_before(now)
    found = [*due_deliveries(client, bounds, time_zone, overdue_before), *due_story_publishes(client, bounds, time_zone),
             *due_agent_wakes(automation_rows, bounds, time_zone), *due_review_deadlines(open_requests, bounds, time_zone, overdue_before)]
    return sorted(found, key=lambda entry: (entry["at"], entry["kind"], entry["id"]))
