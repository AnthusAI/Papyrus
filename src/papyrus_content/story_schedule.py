"""Scheduled publishing: one version of a Story goes live at a chosen moment (docs/scheduled-publishing.md; plan: docs/plans/scheduled-publishing-and-announcements.md).

The schedule lives on the Item row of the version it publishes: ``scheduledPublishAt`` (a UTC instant), ``scheduledBy``, ``scheduledAt``, ``scheduleName`` (the
EventBridge Scheduler schedule) and ``scheduleState`` (``scheduled``, ``publishing`` or ``blocked``; present only while a schedule exists, so the index
``scheduleState`` + ``scheduledPublishAt`` stays sparse). Each scheduled version has one one-off Scheduler schedule that invokes content-actions at that moment with
``{"projectionTask": {"task": "publish-scheduled", "itemId", "scheduledPublishAt"}}``.

* **Exactly once.** The run first claims the row with a conditional update (``scheduled`` at exactly the time the event names -> ``publishing``). A duplicate run, or a
  run for a time the editor has since changed, fails the condition and stops without touching anything.
* **Pinned version.** Versions are immutable, so the schedule is the reviewed text. If a newer version was saved after scheduling, nothing is published: the row
  becomes ``blocked`` and the site's editors get a review request in the Notification Center.
* **Time zones.** Only the UTC instant is stored. A time typed without an offset is read in the publication's time zone; a wall-clock time that does not exist
  (the spring-forward gap) is refused and one that happens twice (fall back) asks which.

The operations ``OPERATIONS`` are the one table the content-actions Lambda, the ``papyrus stories schedule`` / ``schedule-list`` commands and the MCP tools
``stories_schedule`` / ``stories_schedule_list`` all use.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .content_item_lifecycle import UNTYPED_ITEM_TYPE, is_story_item_type

SCHEDULE_FIELDS = ("scheduledPublishAt", "scheduledBy", "scheduledAt", "scheduleState", "scheduleName")
SCHEDULED, PUBLISHING, BLOCKED = "scheduled", "publishing", "blocked"
STATES = (SCHEDULED, PUBLISHING, BLOCKED)
OVERDUE = "overdue"
#: The task the Scheduler event carries (inside ``projectionTask``, as every other scheduled content-actions task does).
TASK_NAME = "publish-scheduled"
ZONE_ENV = "PAPYRUS_PUBLICATION_TIME_ZONE"
FUNCTION_ARN_ENV = "PAPYRUS_SCHEDULE_FUNCTION_ARN"
ROLE_ARN_ENV = "PAPYRUS_SCHEDULER_ROLE_ARN"
DEAD_LETTER_ARN_ENV = "PAPYRUS_SCHEDULER_DEAD_LETTER_ARN"
NAME_PREFIX_ENV = "PAPYRUS_SCHEDULE_NAME_PREFIX"
#: Who may schedule: the groups that may call ``publishItem`` (amplify/data/schema.ts ``contentWriteGroups``).
PUBLISH_GROUPS = ("editor", "admin")
BLOCKED_MESSAGE = "A newer version was saved after this was scheduled. Schedule it again."
REVIEW_REQUEST_RAISED_BY = "scheduled-publishing"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


class ScheduleError(Exception):
    """A refusal the caller is told in plain words. ``code`` is stable; ``details`` carries machine-readable extras (the two choices of an ambiguous time)."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_response(self) -> dict[str, Any]:
        return {"ok": False, "errors": [{"code": self.code, "message": self.message, **self.details}]}


# --- time -------------------------------------------------------------------------------------------------------------------------------------------


def utc_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(TIME_FORMAT)


def parse_utc(text: str) -> datetime:
    return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=timezone.utc)


def zone_of(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ScheduleError("bad-time-zone", f"{name!r} is not a time zone name (for example America/New_York).") from error


def place_name(zone_name: str) -> str:
    """``America/New_York`` -> ``New York``: how a refusal names the publication's place."""
    return zone_name.split("/")[-1].replace("_", " ")


def _day_text(moment: datetime) -> str:
    return f"{moment.day} {MONTHS[moment.month - 1]}"


def _offset_text(moment: datetime) -> str:
    offset = moment.utcoffset() or timezone.utc.utcoffset(None)
    total = int(offset.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    return f"{sign}{abs(total) // 60:02d}:{abs(total) % 60:02d}"


def resolve_instant(text: str, zone_name: str) -> datetime:
    """The UTC instant a typed time means. A time with an offset (or ``Z``) is that instant. A time without one is a wall-clock time in ``zone_name``:
    one that does not exist there is refused, and one that happens twice is refused with both choices (type it again with an offset)."""
    typed = (text or "").strip()
    if not typed:
        raise ScheduleError("bad-time", "Give the time to publish at, for example 2026-11-13 09:00 or 2026-11-13T09:00-05:00.")
    try:
        parsed = datetime.fromisoformat(typed.replace("Z", "+00:00"))
    except ValueError as error:
        raise ScheduleError("bad-time", f"{typed!r} is not a time. Use 2026-11-13 09:00 (the publication's time zone) or 2026-11-13T14:00:00Z.") from error
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    zone = zone_of(zone_name)
    candidates: dict[Any, datetime] = {}
    for fold in (0, 1):
        local = parsed.replace(tzinfo=zone, fold=fold)
        instant = local.astimezone(timezone.utc)
        if instant.astimezone(zone).replace(tzinfo=None) == parsed:   # the wall-clock time survives the round trip, so it exists
            candidates[instant] = local
    if not candidates:
        raise ScheduleError("nonexistent-time", f"That time does not exist on {_day_text(parsed)} in {place_name(zone_name)}. Pick another time.")
    if len(candidates) > 1:
        choices = [{"label": f"{local.strftime('%H:%M')} {local.tzname()}", "offset": _offset_text(local), "at": utc_text(instant)} for instant, local in sorted(candidates.items())]
        raise ScheduleError(
            "ambiguous-time",
            f"That time happens twice on {_day_text(parsed)} in {place_name(zone_name)}: {choices[0]['label']} and {choices[1]['label']}. "
            f"Say which by typing the offset, for example {parsed.strftime('%Y-%m-%dT%H:%M:%S')}{choices[0]['offset']}.",
            {"choices": choices},
        )
    return next(iter(candidates))


def local_view(instant_text: str, zone_name: str | None) -> dict[str, str]:
    """The stored instant in the publication's zone: ``local`` (ISO with offset), ``label`` (``Fri 13 Nov 2026, 09:00 EST``) and the zone's name."""
    if not zone_name:
        return {}
    local = parse_utc(instant_text).astimezone(zone_of(zone_name))
    return {"local": local.isoformat(), "label": f"{local.strftime('%a')} {local.day} {local.strftime('%b %Y, %H:%M %Z')}", "zone": zone_name}


# --- the Scheduler -----------------------------------------------------------------------------------------------------------------------------------


def schedule_name(prefix: str, item_id: str) -> str:
    """``papyrus-pub-<siteId>-<digest>``: a digest of the version id, because version ids share long prefixes (the plan's 8 characters would collide)."""
    return prefix + hashlib.sha256(item_id.encode("utf-8")).hexdigest()[:16]


class EventBridgeScheduler:
    """One one-off schedule per scheduled version (``at()`` in UTC, deleted by the service after it runs), delivering to content-actions through the
    scheduler role. An undeliverable event goes to the dead letter queue the site's alarm watches."""

    def __init__(self, *, function_arn: str, role_arn: str, dead_letter_arn: str, name_prefix: str, client: Any = None) -> None:
        self.function_arn = function_arn
        self.role_arn = role_arn
        self.dead_letter_arn = dead_letter_arn
        self.name_prefix = name_prefix
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("scheduler")
        return self._client

    def name_for(self, item_id: str) -> str:
        return schedule_name(self.name_prefix, item_id)

    def upsert(self, name: str, item_id: str, at: str) -> None:
        """Create the schedule, or move it to the new time (rescheduling keeps its name)."""
        from .newsletter.scheduler import at_expression

        parameters = {
            "Name": name,
            "ScheduleExpression": at_expression(parse_utc(at).timestamp()),
            "ScheduleExpressionTimezone": "UTC",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "ActionAfterCompletion": "DELETE",
            "State": "ENABLED",
            "Target": {
                "Arn": self.function_arn,
                "RoleArn": self.role_arn,
                "Input": json.dumps({"projectionTask": {"task": TASK_NAME, "itemId": item_id, "scheduledPublishAt": at}}),
                "DeadLetterConfig": {"Arn": self.dead_letter_arn},
            },
        }
        try:
            self.client.create_schedule(**parameters)
        except self.client.exceptions.ConflictException:
            self.client.update_schedule(**parameters)

    def delete(self, name: str) -> None:
        try:
            self.client.delete_schedule(Name=name)
        except self.client.exceptions.ResourceNotFoundException:
            pass


def scheduler_from_environment(environment: Mapping[str, str] | None = None, *, invoked_function_arn: str | None = None, client: Any = None) -> EventBridgeScheduler | None:
    """The site's scheduler, or None when the site has not turned scheduling on (no time zone in its publication settings)."""
    env = os.environ if environment is None else environment
    if not (env.get(ZONE_ENV) or "").strip():
        return None
    missing = [name for name in (ROLE_ARN_ENV, DEAD_LETTER_ARN_ENV, NAME_PREFIX_ENV) if not (env.get(name) or "").strip()]
    function_arn = (env.get(FUNCTION_ARN_ENV) or invoked_function_arn or "").strip()
    if missing or not function_arn:
        raise ScheduleError("scheduling-misconfigured", "This site has a publication time zone but its scheduler is not wired (missing " + ", ".join(missing or ["the function ARN"]) + "). Deploy the backend again.")
    return EventBridgeScheduler(function_arn=function_arn, role_arn=env[ROLE_ARN_ENV].strip(), dead_letter_arn=env[DEAD_LETTER_ARN_ENV].strip(),
                                name_prefix=env[NAME_PREFIX_ENV].strip(), client=client)


# --- rows --------------------------------------------------------------------------------------------------------------------------------------------


def clearing_update(row: Mapping[str, Any]) -> dict[str, Any]:
    """The update that removes a schedule from its row. A null removes the attribute, so the row leaves the sparse index; the row's own ``updatedAt`` goes
    back so the update does not stamp the Story as freshly changed (AppSync sets ``updatedAt`` to now when the input has none)."""
    update: dict[str, Any] = {"id": row["id"], **{name: None for name in SCHEDULE_FIELDS}}
    if row.get("updatedAt"):
        update["updatedAt"] = row["updatedAt"]
    return update


def effective_state(row: Mapping[str, Any], now: datetime) -> str:
    """``overdue`` when the time has passed and the version is still ``scheduled`` or ``publishing``; otherwise the stored state."""
    state = str(row.get("scheduleState") or "")
    if state in (SCHEDULED, PUBLISHING) and row.get("scheduledPublishAt") and str(row["scheduledPublishAt"]) < utc_text(now):
        return OVERDUE
    return state


def _title(row: Mapping[str, Any]) -> str:
    return str(row.get("headline") or row.get("title") or row.get("slug") or row.get("lineageId") or row["id"])


def scheduled_versions(client: Any, lineage_id: str) -> list[dict[str, Any]]:
    """The versions of a Story that carry a schedule, read with one query of its lineage. A site without the schedule fields (the deploy that adds scheduled
    publishing has not reached it) has none."""
    if not client.has_schedule_fields():
        return []
    return [row for row in client.list_by_index("itemScheduleByLineage", lineage_id) if row.get("scheduleState")]


# --- the service ---------------------------------------------------------------------------------------------------------------------------------------


@dataclass
class Caller:
    """Who is asking: ``actor`` labels the schedule, ``person`` is the signed-in person's id (None for an IAM or direct caller), ``groups`` their Cognito groups
    (None when the call carries no identity, as a direct invocation)."""

    actor: str
    person: str | None = None
    groups: tuple[str, ...] | None = None

    def require_may_publish(self) -> None:
        if self.groups is not None and not set(self.groups) & set(PUBLISH_GROUPS):
            raise ScheduleError("not-allowed", "You can't publish on this site, so you can't schedule.")


class ScheduleService:
    def __init__(self, client: Any, *, zone_name: str | None, scheduler: EventBridgeScheduler | None, now: Callable[[], datetime] | None = None) -> None:
        self.client = client
        self.zone_name = (zone_name or "").strip() or None
        self.scheduler = scheduler
        self._now = now or (lambda: datetime.now(timezone.utc))

    # reads

    def now(self) -> datetime:
        return self._now().astimezone(timezone.utc).replace(microsecond=0)

    def lineage_rows(self, lineage_id: str) -> list[dict[str, Any]]:
        """Every version of the Story with its schedule fields, oldest first (one read of the lineage partition)."""
        return sorted(self.client.list_by_index("itemScheduleByLineage", lineage_id), key=lambda row: int(row.get("versionNumber") or 0))

    def _lineage_of(self, arguments: Mapping[str, Any]) -> tuple[str, str | None]:
        item_id, lineage_id = arguments.get("itemId"), arguments.get("storyLineageId")
        if not item_id and not lineage_id:
            raise ScheduleError("story-required", "Name the Story: storyLineageId (or itemId for one version).")
        if item_id:
            row = self.client.get_record("Item", str(item_id))
            if row is None:
                raise ScheduleError("not-found", f"No version {item_id} in this site.")
            return str(row.get("lineageId") or row["id"]), str(item_id)
        return str(lineage_id), None

    def _require_zone(self) -> str:
        if not self.zone_name:
            raise ScheduleError("scheduling-off", "This site has not turned scheduling on: set publication.timeZone in the site's backend settings and deploy.")
        return self.zone_name

    def _require_scheduler(self) -> EventBridgeScheduler:
        if self.scheduler is None:
            self._require_zone()
            raise ScheduleError("scheduling-misconfigured", "This site's scheduler is not wired. Deploy the backend again.")
        return self.scheduler

    def entry(self, row: Mapping[str, Any]) -> dict[str, Any]:
        state = effective_state(row, self.now())
        found = {
            "itemId": row["id"], "lineageId": row.get("lineageId") or row["id"], "versionNumber": row.get("versionNumber"), "title": _title(row),
            "state": state, "storedState": row.get("scheduleState"), "scheduledPublishAt": row.get("scheduledPublishAt"),
            "scheduledBy": row.get("scheduledBy"), "scheduledAt": row.get("scheduledAt"),
            **(local_view(str(row["scheduledPublishAt"]), self.zone_name) if row.get("scheduledPublishAt") else {}),
        }
        if state == BLOCKED:
            found["message"] = BLOCKED_MESSAGE
        if state == OVERDUE:
            found["message"] = "Overdue: this should have gone live at the scheduled time. Publish it now or schedule it again."
        return found

    # operations

    def schedule(self, arguments: Mapping[str, Any], caller: Caller) -> dict[str, Any]:
        """Pin a version of a Story to a moment (``at``), or remove the Story's schedule (``clear``). ``dryRun`` checks everything and writes nothing."""
        caller.require_may_publish()
        wants_clear, at_text = bool(arguments.get("clear")), arguments.get("at")
        if wants_clear == bool(at_text):
            raise ScheduleError("one-of", "Give either at (the time to publish) or clear (remove the schedule), not both and not neither.")
        lineage_id, pinned_id = self._lineage_of(arguments)
        rows = self.lineage_rows(lineage_id)
        if not rows:
            raise ScheduleError("not-found", f"No Story {lineage_id} in this site.")
        dry_run = bool(arguments.get("dryRun"))
        if wants_clear:
            return self._clear(lineage_id, rows, pinned_id, dry_run)
        return self._set(lineage_id, rows, pinned_id, str(at_text), caller, dry_run)

    def _set(self, lineage_id: str, rows: list[dict[str, Any]], pinned_id: str | None, at_text: str, caller: Caller, dry_run: bool) -> dict[str, Any]:
        zone_name = self._require_zone()
        scheduler = self._require_scheduler()
        newest = rows[-1]
        row = next((candidate for candidate in rows if candidate["id"] == pinned_id), newest) if pinned_id else newest
        if row["id"] != newest["id"]:
            raise ScheduleError("not-newest", f"Version {row.get('versionNumber')} is not the newest version of this Story. Schedule version {newest.get('versionNumber')}.")
        if not is_story_item_type(row.get("type")):
            raise ScheduleError("not-a-story", "Only Stories can be scheduled.")
        if row.get("type") == UNTYPED_ITEM_TYPE:
            raise ScheduleError("type-required", "This story has no type yet. Choose its type, then schedule it: the site decides where a page lives from it.")
        instant = resolve_instant(at_text, zone_name)
        if instant <= self.now():
            raise ScheduleError("time-passed", "That time has passed.")
        at = utc_text(instant)
        if row.get("scheduleState") == PUBLISHING:
            raise ScheduleError("publishing", "This version is being published right now.")
        item = self.client.get_record("Item", row["id"]) or row
        from .publish_gate import ensure_publish_approval
        from .publishing import PublishError

        replaced = [other for other in rows if other["id"] != row["id"] and other.get("scheduleState")]
        result: dict[str, Any] = {
            "ok": True, "scheduled": not dry_run, "dryRun": dry_run, "itemId": row["id"], "lineageId": lineage_id, "versionNumber": row.get("versionNumber"),
            "title": _title(row), "scheduledPublishAt": at, "scheduledBy": caller.actor, "replaced": [other["id"] for other in replaced], **local_view(at, zone_name),
        }
        from .item_stars import effective_rating

        if effective_rating(item)["stars"] == 0:
            result["notes"] = ["Unrated: it will publish but will not be listed or announced until it is rated."]
        if dry_run:
            return result
        try:
            ensure_publish_approval(self.client, item, approved_by=caller.person, actor=caller.actor)
        except PublishError as error:
            raise ScheduleError(error.code, error.message) from error
        for other in replaced:   # a Story has one schedule: scheduling this version replaces the earlier one
            self._remove(other)
        name = scheduler.name_for(row["id"])
        scheduler.upsert(name, row["id"], at)   # the timer first: a timer without a row fires harmlessly, a row without a timer would never fire
        written = self.client.update_record_if(
            "Item",
            {"id": row["id"], "scheduledPublishAt": at, "scheduledBy": caller.actor, "scheduledAt": utc_text(self.now()), "scheduleState": SCHEDULED, "scheduleName": name,
             **({"updatedAt": row["updatedAt"]} if row.get("updatedAt") else {})},
            {"or": [{"scheduleState": {"attributeExists": False}}, {"scheduleState": {"ne": PUBLISHING}}]},
        )
        if not written:
            raise ScheduleError("publishing", "This version started publishing while you were scheduling it.")
        return result

    def _clear(self, lineage_id: str, rows: list[dict[str, Any]], pinned_id: str | None, dry_run: bool) -> dict[str, Any]:
        scheduled = [row for row in rows if row.get("scheduleState") and (pinned_id is None or row["id"] == pinned_id)]
        if not scheduled:
            raise ScheduleError("not-scheduled", "This Story has no schedule.")
        busy = [row for row in scheduled if row.get("scheduleState") == PUBLISHING]
        if busy:
            raise ScheduleError("publishing", "This version is being published right now.")
        if not dry_run:
            for row in scheduled:
                self._remove(row)
        return {"ok": True, "cleared": not dry_run, "dryRun": dry_run, "lineageId": lineage_id, "itemIds": [row["id"] for row in scheduled]}

    def _remove(self, row: Mapping[str, Any]) -> None:
        """Delete the row's Scheduler schedule, then its fields (a timer that outlives its row only fires harmlessly)."""
        if row.get("scheduleName"):
            self._require_scheduler().delete(str(row["scheduleName"]))
        self.client.update_record("Item", clearing_update(row))

    def clear_through(self, lineage_id: str, version_number: int | None = None) -> list[str]:
        """Remove the schedules a publish or a takedown makes meaningless: every version's up to ``version_number`` (all of them when None). Returns the version ids."""
        removed: list[str] = []
        for row in self.lineage_rows(lineage_id):
            if row.get("scheduleState") and (version_number is None or int(row.get("versionNumber") or 0) <= version_number):
                self._remove(row)
                removed.append(row["id"])
        return removed

    def listing(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """The schedules, soonest first: of one Story, or (read from the index, one query per stored state and range) of the site between ``from`` and ``to``.
        ``states`` keeps the effective states asked for (``overdue`` is a scheduled or publishing version whose time has passed); the default is all four."""
        wanted = list(arguments.get("states") or (*STATES, OVERDUE))
        unknown = [state for state in wanted if state not in (*STATES, OVERDUE)]
        if unknown:
            raise ScheduleError("bad-state", f"Unknown state {unknown[0]!r}; use scheduled, publishing, blocked or overdue.")
        if arguments.get("storyLineageId"):
            found = [row for row in self.lineage_rows(str(arguments["storyLineageId"])) if row.get("scheduleState")]
        else:
            zone_name = self.zone_name or "UTC"
            start = utc_text(resolve_instant(str(arguments["from"]), zone_name)) if arguments.get("from") else None
            end = utc_text(resolve_instant(str(arguments["to"]), zone_name)) if arguments.get("to") else None
            if start and end and start > end:
                raise ScheduleError("bad-range", "from is after to.")
            stored = [state for state in STATES if state in wanted or (state != BLOCKED and OVERDUE in wanted)]
            found = [row for state in stored for row in self.client.list_schedule(state, start, end)]
        entries = [self.entry(row) for row in sorted(found, key=lambda row: str(row.get("scheduledPublishAt")))]
        return {"ok": True, "timeZone": self.zone_name, "now": utc_text(self.now()), "schedules": [entry for entry in entries if entry["state"] in wanted]}

    # the run at the scheduled time

    def run_scheduled_publish(self, item_id: str, scheduled_at: str, publish: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
        """What the Scheduler's event does. ``publish(row)`` publishes the version (the normal publish path) and returns its answer."""
        row = self.client.get_record("Item", item_id)
        if row is None or row.get("scheduleState") != SCHEDULED or row.get("scheduledPublishAt") != scheduled_at:
            return {"ok": True, "published": False, "reason": "no longer scheduled for this time", "itemId": item_id}
        claimed = self.client.update_record_if(
            "Item", {"id": item_id, "scheduleState": PUBLISHING, **({"updatedAt": row["updatedAt"]} if row.get("updatedAt") else {})},
            {"scheduleState": {"eq": SCHEDULED}, "scheduledPublishAt": {"eq": scheduled_at}},
        )
        if not claimed:
            return {"ok": True, "published": False, "reason": "another run claimed it or the schedule changed", "itemId": item_id}
        lineage_id = str(row.get("lineageId") or item_id)
        newest = max(int(other.get("versionNumber") or 0) for other in self.lineage_rows(lineage_id))
        if newest > int(row.get("versionNumber") or 0):
            self.client.update_record_if(
                "Item", {"id": item_id, "scheduleState": BLOCKED, **({"updatedAt": row["updatedAt"]} if row.get("updatedAt") else {})},
                {"scheduleState": {"eq": PUBLISHING}},
            )
            self._tell_editors(row, newest)
            return {"ok": True, "published": False, "blocked": True, "reason": BLOCKED_MESSAGE, "itemId": item_id}
        try:
            answer = publish(row)
        except Exception:
            # Nothing was published (or the publish is safe to repeat): hand the schedule back so the retry can claim it. It stays overdue until it publishes.
            self.client.update_record_if(
                "Item", {"id": item_id, "scheduleState": SCHEDULED, **({"updatedAt": row["updatedAt"]} if row.get("updatedAt") else {})}, {"scheduleState": {"eq": PUBLISHING}}
            )
            raise
        self.clear_through(lineage_id, int(row.get("versionNumber") or 0))
        return {"ok": True, "published": True, "itemId": item_id, "publish": answer}

    def _tell_editors(self, row: Mapping[str, Any], newest: int) -> None:
        """A flag in the Notification Center: the schedule did not publish. One request per version (raising it again returns the same one)."""
        from . import review_requests as rr

        lineage_id = str(row.get("lineageId") or row["id"])
        digest = hashlib.sha256(f"{row['id']}\n{row.get('scheduledPublishAt')}".encode("utf-8")).hexdigest()[:20]
        label = local_view(str(row.get("scheduledPublishAt")), self.zone_name).get("label") or str(row.get("scheduledPublishAt"))
        rr.raise_review(
            self.client, request_id=f"rr-schedule-blocked-{digest}", subject={"type": "story", "id": lineage_id}, mode="flag",
            reason=f"Not published as scheduled: {_title(row)}",
            ask=f"Version {row.get('versionNumber')} was scheduled for {label}, but version {newest} was saved after that. {BLOCKED_MESSAGE}",
            raised_by=REVIEW_REQUEST_RAISED_BY, links=[{"type": "story", "id": str(row["id"]), "label": f"version {row.get('versionNumber')}"}],
        )


# --- the operation table ---------------------------------------------------------------------------------------------------------------------------------


def _closed(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


_STR = {"type": "string"}
_TIME = {"type": "string", "description": "A time with an offset or Z (2026-11-13T09:00:00-05:00), or without one (2026-11-13 09:00), which is read in the publication's time zone."}


@dataclass(frozen=True)
class Operation:
    name: str                       # the field of the MCP tool name and the operation key in the scheduleItem mutation
    mcp: str                        # the MCP tool
    cli: str                        # the `papyrus stories ...` command
    writes: bool
    summary: str
    schema: dict[str, Any]


OPERATIONS: dict[str, Operation] = {
    "schedule": Operation(
        "schedule", "stories_schedule", "schedule", True,
        "Pins a Story's newest version to a time (at), or removes the Story's schedule (clear). The version is published at that time by the normal publish path, once; "
        "a time without an offset is read in the publication's time zone; a time that does not exist there is refused and one that happens twice asks which. "
        "If a newer version is saved first, nothing is published and the editors are told. dryRun checks and writes nothing.",
        _closed({"storyLineageId": _STR, "itemId": {"type": "string", "description": "One version's id (the newest); storyLineageId names the Story instead."},
                 "at": _TIME, "clear": {"type": "boolean"}, "dryRun": {"type": "boolean"}}),
    ),
    "schedule_list": Operation(
        "schedule_list", "stories_schedule_list", "schedule-list", False,
        "Read only. The scheduled, publishing, blocked and overdue versions soonest first, from the schedule index: of one Story (storyLineageId) or of the site between from and to. "
        "Each carries the stored state, the effective state (overdue when the time passed and it has not published), the UTC time and the publication-zone time.",
        _closed({"storyLineageId": _STR, "from": _TIME, "to": _TIME, "states": {"type": "array", "items": {"type": "string", "enum": [*STATES, OVERDUE]}}}),
    ),
}


def validate_arguments(operation: Operation, arguments: Mapping[str, Any]) -> None:
    properties = operation.schema["properties"]
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ScheduleError("bad-input", f"Unknown input {unknown[0]!r}; {operation.name} takes {', '.join(sorted(properties))}.")
    for name, value in arguments.items():
        kind = properties[name].get("type")
        ok = {"string": isinstance(value, str), "boolean": isinstance(value, bool), "array": isinstance(value, list)}.get(kind, True)
        if not ok:
            raise ScheduleError("bad-input", f"{name} must be a {kind}.")


def run_operation(name: str, arguments: Mapping[str, Any], service: ScheduleService, caller: Caller) -> dict[str, Any]:
    """Run one operation of the table. A refusal comes back as ``{"ok": False, "errors": [...]}``; nothing raises for a refusal."""
    operation = OPERATIONS.get(name)
    if operation is None:
        return ScheduleError("unknown-operation", f"Unknown schedule operation {name!r}; use {', '.join(OPERATIONS)}.").to_response()
    try:
        validate_arguments(operation, arguments)
        if name == "schedule":
            return service.schedule(arguments, caller)
        return service.listing(arguments)
    except ScheduleError as error:
        return error.to_response()


def call_remote(client: Any, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """The CLI's and the MCP tools' door: ask the site's ``scheduleItem`` mutation (content-actions) to run one operation of the table."""
    data = client.graphql("mutation Schedule($input: AWSJSON!) { scheduleItem(input: $input) }", {"input": json.dumps({"operation": name, "arguments": dict(arguments)})})
    response = data.get("scheduleItem")
    return json.loads(response) if isinstance(response, str) else (response or {})


def refused_message(response: Mapping[str, Any]) -> str:
    return "; ".join(f"[{error.get('code')}] {error.get('message')}" for error in response.get("errors") or []) or "the request was refused"
