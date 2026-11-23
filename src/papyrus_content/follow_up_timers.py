"""Follow-up timers: a due time on a record raises one wake (PPY-3ff011, slice C2 of docs/design/always-on-agents-architecture.md).

Every wait is a named time on the record that waits: ``dueAt``, with ``waitingFor`` (a Delivery already carries both). This module is the one
helper that turns such a time into a timer. Nothing polls.

* ``OneShotSchedules`` is the mechanism: one EventBridge Scheduler entry that fires once at a UTC instant and deletes itself (``ActionAfterCompletion``
  ``DELETE``). Setting a time creates the entry, or moves the existing one (the entry keeps its name, so there is never a second entry for one record);
  clearing deletes it. An entry the service already deleted after it fired is not an error to clear. Scheduled publishing
  (``story_schedule.EventBridgeScheduler``) uses this class for its per-version entries and nothing else of it changes.
* ``FollowUpTimers`` is a follow-up: the entry's target is the site's wake queue, in the site's schedule group, and its message is a wake whose key is
  ``<owner>|<record id>|<due time>|due`` (wake_keys.change_key). The key names the record and the time, so a record due at a new time is a different wake,
  and the same time delivered twice is one. The entry is named ``follow-up-<digest of the record>``: it does not start with ``agent-``, so the schedule
  reconciler (agent_definitions/schedules.py) never touches it.
* ``check_wake`` is what the run does first: the timer only puts a wake on the queue, and the run re-reads the record. A record whose ``dueAt`` is no
  longer the time the wake names (moved, cleared, or the record is gone) does not wait any more, and the wake does nothing.

The group, the role the scheduler assumes and the helper's own permission (create, update and delete entries named ``follow-up-*`` in that group, and pass
the scheduler role) are in amplify/agents/schedule-group.ts. The contract is described once, for both sides, in docs/follow-up-timers.md.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping

from . import agent_wakes, wake_keys
from .newsletter.scheduler import at_expression

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
ENTRY_PREFIX = "follow-up-"
DIGEST_CHARACTERS = 32      # the scheduler allows 64 characters in a name: the prefix and 32 characters of a digest fit with room to spare
WHAT = "due"                # the last part of a follow-up's wake key: what happened to the record (its time came)
GROUP_PREFIX, GROUP_SUFFIX, ROLE_SUFFIX = "papyrus-", "-agent-schedules", "-agent-scheduler"
KIND = "follow-up"          # the trigger kind of a follow-up's wake


class FollowUpError(ValueError):
    """A follow-up that cannot be set: a time that is not a UTC instant, or a record the key cannot name."""


def parse_utc(text: object) -> datetime:
    try:
        return datetime.strptime(str(text), TIME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError as invalid:
        raise FollowUpError(f"a due time is a UTC instant written like 2026-11-17T09:00:00Z (got {text!r})") from invalid


class OneShotSchedules:
    """One-off Scheduler entries in one group (the account's default group when ``group`` is None): create or move, delete, and nothing else.

    The target is the caller's: ``set`` takes the whole ``Target`` the entry delivers to (a function and its role, or a queue and its role)."""

    def __init__(self, client: Any = None, *, group: str | None = None) -> None:
        self._client = client
        self.group = group

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3  # provided by the Lambda runtime and the operator's environment

            self._client = boto3.client("scheduler")
        return self._client

    def set(self, name: str, at: str, target: Mapping[str, Any], *, description: str | None = None) -> None:
        """Create the entry, or move it to the new time (the entry keeps its name). It fires once at ``at`` and the service then deletes it."""
        parameters: dict[str, Any] = {
            "Name": name,
            **({"GroupName": self.group} if self.group else {}),
            **({"Description": description[:512]} if description else {}),
            "ScheduleExpression": at_expression(parse_utc(at).timestamp()),
            "ScheduleExpressionTimezone": "UTC",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "ActionAfterCompletion": "DELETE",
            "State": "ENABLED",
            "Target": dict(target),
        }
        try:
            self.client.create_schedule(**parameters)
        except self.client.exceptions.ConflictException:
            self.client.update_schedule(**parameters)

    def clear(self, name: str) -> None:
        """Delete the entry. One the service already deleted after it fired is not an error."""
        try:
            self.client.delete_schedule(Name=name, **({"GroupName": self.group} if self.group else {}))
        except self.client.exceptions.ResourceNotFoundException:
            pass


# --- follow-ups ------------------------------------------------------------------------------------------------------------


def entry_name(record_kind: str, record_id: str) -> str:
    """``follow-up-<digest>``: one entry for each record, named from its kind and id (ids are long and share prefixes, so the name is a digest)."""
    text = f"{record_kind}:{record_id}"
    if not record_kind or not record_id:
        raise FollowUpError("a follow-up is for a record, which needs a kind and an id")
    return ENTRY_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()[:DIGEST_CHARACTERS]


def follow_up_key(owner: str, record_id: str, due_at: str) -> str:
    """The wake key: the owner (automation or procedure), the record, the due time and the word ``due``."""
    parse_utc(due_at)
    try:
        return wake_keys.change_key(owner, record_id, due_at, WHAT)
    except wake_keys.InvalidWakeKey as invalid:
        raise FollowUpError(str(invalid)) from invalid


def follow_up_request(base: Mapping[str, Any], *, owner: str, record_id: str, due_at: str, waiting_for: str | None) -> dict[str, Any]:
    """The runner's request for the wake: ``base`` (the procedure, the publication and the policy location, as for any start) with the wake key and a trigger that
    says in words what the record waited for."""
    what = f" ({waiting_for})" if waiting_for else ""
    request = {name: value for name, value in dict(base).items() if name != "wakeKey"}
    request["wakeKey"] = follow_up_key(owner, record_id, due_at)
    request["trigger"] = {**(request.get("trigger") if isinstance(request.get("trigger"), dict) else {}), "kind": KIND, "dueAt": due_at,
                          "waitingFor": waiting_for, "recordId": record_id,
                          "summary": f"{record_id} was waiting until {due_at}{what}"[:500]}
    return request


class FollowUpTimers:
    """The follow-ups of one site: entries in the site's schedule group whose target is the site's wake queue."""

    def __init__(self, schedules: OneShotSchedules, *, queue_arn: str, role_arn: str) -> None:
        self.schedules, self.queue_arn, self.role_arn = schedules, queue_arn, role_arn

    @classmethod
    def for_site(cls, site: str, *, account: str, region: str, partition: str = "aws", client: Any = None) -> FollowUpTimers:
        """The follow-ups of a site, with the group, the role and the queue named from the site id exactly as amplify/agents/schedule-group.ts and wake-queue.ts name them."""
        site_id = agent_wakes.site_id(site)
        return cls(OneShotSchedules(client, group=f"{GROUP_PREFIX}{site_id}{GROUP_SUFFIX}"),
                   queue_arn=f"arn:{partition}:sqs:{region}:{account}:{agent_wakes.queue_name(site)}",
                   role_arn=f"arn:{partition}:iam::{account}:role/{GROUP_PREFIX}{site_id}{ROLE_SUFFIX}")

    def sync(self, record_kind: str, record_id: str, due_at: str | None, *, owner: str, base: Mapping[str, Any], waiting_for: str | None = None) -> str | None:
        """Make the record's entry agree with its due time and return the wake key it will send, or None when there is no time.

        A time sets the entry (a new time moves it); no time deletes it. Call it wherever a record's ``dueAt`` is written."""
        name = entry_name(record_kind, record_id)
        if not due_at:
            self.schedules.clear(name)
            return None
        request = follow_up_request(base, owner=owner, record_id=record_id, due_at=due_at, waiting_for=waiting_for)
        wake = agent_wakes.wake_of(request)
        target = {"Arn": self.queue_arn, "RoleArn": self.role_arn, "Input": agent_wakes.message_body(request),
                  "SqsParameters": {"MessageGroupId": agent_wakes.group_id(wake)}}
        self.schedules.set(name, due_at, target, description=f"Wakes {owner} for {record_kind} {record_id} at {due_at}")
        return request["wakeKey"]


    def schedule_continuation(self, request: Mapping[str, Any], *, due_at: str, record_id: str) -> str:
        """Set the one timer for a continuation of a run (slice A6): ``record_id`` is the run that asked, and ``request`` is the next run's request with its own key."""
        parse_utc(due_at)
        wake = agent_wakes.wake_of(dict(request))
        target = {"Arn": self.queue_arn, "RoleArn": self.role_arn, "Input": agent_wakes.message_body(dict(request)),
                  "SqsParameters": {"MessageGroupId": agent_wakes.group_id(wake)}}
        self.schedules.set(entry_name("continuation", record_id), due_at, target, description=f"Continues {wake['agent']} from run {record_id} at {due_at}")
        return str(request["wakeKey"])


    def wake_again_at(self, record_kind: str, record_id: str, request: Mapping[str, Any], *, due_at: str) -> str:
        """Set the one timer of a record whose message is a wake that already has its run record (``request``, with its own key), due at ``due_at``. A later call
        for the same record moves the entry and replaces its message. The budget's cycle timer (spend_stop.py, PPY-9376f8) is one per site and cycle."""
        parse_utc(due_at)
        wake = agent_wakes.wake_of(dict(request))
        target = {"Arn": self.queue_arn, "RoleArn": self.role_arn, "Input": agent_wakes.message_body(dict(request)),
                  "SqsParameters": {"MessageGroupId": agent_wakes.group_id(wake)}}
        self.schedules.set(entry_name(record_kind, record_id), due_at, target, description=f"Wakes {wake['agent']} for {record_kind} {record_id} at {due_at}")
        return str(request["wakeKey"])


class SiteNotNamed(FollowUpError):
    """This process was not told which site's schedule group and wake queue its follow-ups go to."""


def site_follow_ups(environment: Mapping[str, str], *, appsync_endpoint: str, procedure_key: str, actor_label: str, needed_for: str,
                    require_policy_location: bool = False, client: Any = None) -> tuple[FollowUpTimers, dict[str, Any]]:
    """The follow-up timers of the site this process works for, and the base of the runner request each wake carries, named as the site's functions name them.

    ``PAPYRUS_AGENT_PUBLICATION_ID``, ``PAPYRUS_AWS_ACCOUNT_ID`` and ``AWS_REGION`` are required; ``PAPYRUS_AWS_PARTITION`` defaults to ``aws``. The tenant
    (``PAPYRUS_AGENT_TENANT_ID``, else ``PAPYRUS_TENANT_ID``) and the site bucket (``PAPYRUS_SITE_BUCKET``) say where the run finds the site's agent policy. With
    ``require_policy_location`` they are required too, because the runner refuses a wake that does not name them. ``needed_for`` says in words what needs the timers.
    A function that must not read and write as a tenant carries the tenant as ``PAPYRUS_AGENT_TENANT_ID`` (the image service)."""
    def value(name: str) -> str:
        return str(environment.get(name) or "").strip()

    tenant = value("PAPYRUS_AGENT_TENANT_ID") or value("PAPYRUS_TENANT_ID")
    names = ["PAPYRUS_AGENT_PUBLICATION_ID", "PAPYRUS_AWS_ACCOUNT_ID", "AWS_REGION"]
    missing = [name for name in names if not value(name)]
    if require_policy_location:
        missing += [name for name, given in (("PAPYRUS_TENANT_ID", tenant), ("PAPYRUS_SITE_BUCKET", value("PAPYRUS_SITE_BUCKET"))) if not given]
    if missing:
        raise SiteNotNamed(f"{needed_for} sets a follow-up timer on the site's schedule group, which needs {', '.join(missing)}")
    publication = value("PAPYRUS_AGENT_PUBLICATION_ID")
    timers = FollowUpTimers.for_site(publication, account=value("PAPYRUS_AWS_ACCOUNT_ID"), region=value("AWS_REGION"),
                                     partition=value("PAPYRUS_AWS_PARTITION") or "aws", client=client)
    base: dict[str, Any] = {"publicationId": publication, "appsyncEndpoint": appsync_endpoint, "procedureKey": procedure_key, "actorLabel": actor_label}
    if tenant:
        base["tenantId"] = tenant
    if value("PAPYRUS_SITE_BUCKET"):
        base["siteBucket"] = value("PAPYRUS_SITE_BUCKET")
    return timers, base


# --- the run's first check -----------------------------------------------------------------------------------------------------


def due_time_of(wake_key: str) -> str:
    """The due time a follow-up's wake key names."""
    parts = wake_keys.checked(wake_key).split(wake_keys.SEPARATOR)
    if len(parts) != 4 or parts[3] != WHAT:
        raise FollowUpError(f"{wake_key!r} is not a follow-up's wake key: <owner>|<record id>|<due time>|{WHAT}")
    return parts[2]


def record_id_of(wake_key: str) -> str:
    """The record a follow-up's wake key names."""
    due_time_of(wake_key)
    return wake_keys.checked(wake_key).split(wake_keys.SEPARATOR)[1]


def check_wake(wake_key: str, row: Mapping[str, Any] | None) -> dict[str, Any]:
    """Whether the record still waits for the time this wake names. ``row`` is the record as the run just read it (None when it is gone).

    The record waits when its ``dueAt`` is exactly that time. Moved, cleared, the record done or deleted: it does not, and the wake does nothing."""
    due = due_time_of(wake_key)
    current = None if row is None else row.get("dueAt")
    if current == due:
        return {"waiting": True, "dueAt": due, "waitingFor": row.get("waitingFor")}
    if row is None:
        reason = "the record is gone"
    elif not current:
        reason = "the record waits for nothing now"
    else:
        reason = f"the record now waits until {current}, which has its own wake"
    return {"waiting": False, "dueAt": due, "reason": f"Nothing to do: this wake was for {due} and {reason}."}

