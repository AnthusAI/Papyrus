"""The schedule trigger: an agent runs on a clock that comes from its definition (``papyrus agents schedules``; slice C1, PPY-2a53cd).

A definition may name a schedule, a cron expression of five fields and a time zone (``wakes.schedule``). The registered copy on the agent's
``Automation`` record carries it (``registered_schedules``). This module makes the site's EventBridge Scheduler group agree with those records:

* One entry for each agent that is **live**: registered with a schedule, not retired (``definitionRetiredAt``) and switched on. An entry is named
  from the agent's id (``agent-<id>``), lives in the site's schedule group and has one target, the site's wake queue.
* The entry's message is a wake (``agent_wakes.message_body``) whose key is ``<agent>|schedule|<scheduled time>``. The scheduler fills in the time
  the entry was scheduled for (``<aws.scheduler.scheduled-time>``), so a tick that is delivered twice is one wake: the queue drops the second
  and, after the queue's five minutes, the run record's own condition does (wake_keys.py).
* A timer does nothing else. The run that follows re-reads the site's policy, the pause, the definition and every record, as for any wake.
* The entry carries the local cron expression and the time zone by name, never an offset from UTC. Daylight saving time is the scheduler's.
* An entry in the group that begins ``agent-`` and that no live agent names is deleted, so no schedule exists that a definition does not name.
  Entries with any other name (the one-shot follow-up helper's, slice C2) are not this module's and are never touched.

The reconciler runs in the deploy step beside ``papyrus agents apply`` and is safe to run again: a second run with nothing changed writes nothing.
It checks everything before it writes anything and stops with one message that names every problem. It creates nothing by hand: the group and the
role the scheduler assumes are in the site's ``agents`` stack (amplify/agents/schedule-group.ts), and this module only writes entries into that group.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .. import agent_wakes, wake_keys
from ..automations import read_record
from ..policy_location import policy_location
from .cron import CronError, scheduler_expression
from .release import registered_schedules

GROUP_PREFIX, GROUP_SUFFIX = "papyrus-", "-agent-schedules"
ROLE_SUFFIX = "-agent-scheduler"
ENTRY_PREFIX = "agent-"
MAX_ENTRY_NAME = 64
MAX_DESCRIPTION = 512
SCHEDULED_TIME = "<aws.scheduler.scheduled-time>"   # the scheduler's context attribute: the time the entry was scheduled for, in UTC


class ScheduleError(ValueError):
    """The schedules cannot be reconciled; nothing was written. The message names every problem."""


# --- names -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Names:
    site: str
    group: str
    role: str
    queue: str


def names_for(site: str) -> Names:
    """The group, the role and the queue of a site, from its site id (the brand id) exactly as amplify/agents/schedule-group.ts and wake-queue.ts name them."""
    site_id = agent_wakes.site_id(site)
    return Names(site_id, f"{GROUP_PREFIX}{site_id}{GROUP_SUFFIX}", f"{GROUP_PREFIX}{site_id}{ROLE_SUFFIX}", agent_wakes.queue_name(site))


def entry_name(automation_id: str) -> str:
    """``agent-<id>``, or when that is longer than the scheduler's 64 characters, the start of the id and a digest of all of it (so two long ids never meet)."""
    name = f"{ENTRY_PREFIX}{automation_id}"
    if len(name) <= MAX_ENTRY_NAME:
        return name
    tail = hashlib.sha256(automation_id.encode("utf-8")).hexdigest()[:12]
    return f"{name[:MAX_ENTRY_NAME - len(tail) - 1]}-{tail}"


# --- the wake each entry sends ------------------------------------------------------------------------------------


def wake_request(record: dict, schedule: dict, publication: dict) -> dict[str, Any]:
    """The runner's request for one tick of this agent, with the wake key the scheduler completes with the scheduled time."""
    automation_id = record["id"]
    owner = wake_keys.owner(automation_id, record["procedureKey"])
    limits = record.get("limits") or {}
    cron_words = f"{schedule['cron']} {schedule['timeZone']}"
    request: dict[str, Any] = {
        "wakeKey": wake_keys.schedule_key(owner, SCHEDULED_TIME), "publicationId": publication["publicationId"],
        "appsyncEndpoint": publication["appsyncEndpoint"], "procedureKey": record["procedureKey"],
        **policy_location(publication), "input": dict(record.get("inputTemplate") or {}),
        "actorLabel": f"{automation_id} (schedule)"[:200],
        "trigger": {"kind": "schedule", "automationId": automation_id, "monitorId": record["trigger"]["config"]["monitorId"],
                    "title": f"{record['procedureKey']}: scheduled run of {automation_id}"[:200],
                    "summary": f"Scheduled run of {automation_id} ({cron_words})"[:500]}}
    if publication.get("openaiKeyParameter"):
        request["openaiKeyParameter"] = publication["openaiKeyParameter"]
    if limits.get("timeoutSeconds"):
        request["timeoutSeconds"] = limits["timeoutSeconds"]
    return request


def entry_for(record: dict, schedule: dict, publication: dict, names: Names, *, queue_arn: str, role_arn: str) -> dict[str, Any]:
    """The arguments of ``create_schedule`` for this agent: the local expression and zone, the wake queue as the only target, the wake as the message."""
    request = wake_request(record, schedule, publication)
    wake = agent_wakes.wake_of(request)
    return {
        "Name": entry_name(record["id"]), "GroupName": names.group,
        "Description": f"Wakes {record['id']}: {schedule['cron']} in {schedule['timeZone']}"[:MAX_DESCRIPTION],
        "ScheduleExpression": scheduler_expression(schedule["cron"]), "ScheduleExpressionTimezone": schedule["timeZone"],
        "FlexibleTimeWindow": {"Mode": "OFF"}, "State": "ENABLED",
        "Target": {"Arn": queue_arn, "RoleArn": role_arn, "Input": agent_wakes.message_body(request),
                   "SqsParameters": {"MessageGroupId": agent_wakes.group_id(wake)}}}


# --- what should exist ------------------------------------------------------------------------------------------


def live_schedules(rows: Iterable[dict[str, Any]]) -> dict[str, tuple[dict, dict]]:
    """``{automation id: (record, schedule)}`` for each agent that must have an entry: a registered schedule that is not retired, on a record that is switched on."""
    rows = list(rows)
    schedules = registered_schedules(rows)
    records = {record["id"]: record for record in (read_record(row) for row in rows)}
    return {agent: (records[agent], schedule) for agent, schedule in schedules.items() if records[agent]["enabled"]}


def desired_entries(rows: Iterable[dict[str, Any]], names: Names, *, publication_for: Callable[[dict], dict], queue_arn: str, role_arn: str,
                    endpoint: str | None = None) -> dict[str, dict[str, Any]]:
    """The entry each live agent needs, by entry name. Raises one ``ScheduleError`` naming every agent that cannot have one."""
    entries: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for agent, (record, schedule) in sorted(live_schedules(rows).items()):
        config = record["trigger"]["config"]
        if not (config.get("monitorId") and config.get("publicationId")):
            problems.append(f"{agent} is switched on with a schedule but names no router publication: give it one with papyrus automations update {agent} --monitor <monitor> --publication <publication>, "
                            "so the tick carries the site's endpoint, model key and policy location.")
            continue
        if agent_wakes.site_id(config["publicationId"]) != names.site:
            problems.append(f"{agent} belongs to another site: it names the publication {config['publicationId']}, and this deploy is for {names.site}.")
            continue
        try:
            publication = publication_for(record)
            if endpoint and publication.get("appsyncEndpoint") != endpoint:
                raise ScheduleError(f"{agent} belongs to another site: its router publication delivers to a different endpoint.")
            missing = [field for field in ("appsyncEndpoint", "tenantId", "siteBucket") if not publication.get(field)]
            if missing:
                raise ScheduleError(f"{agent}: the router publication {config['publicationId']} names no {', '.join(missing)}, so the runner would refuse every tick.")
            entry = entry_for(record, schedule, publication, names, queue_arn=queue_arn, role_arn=role_arn)
        except (ScheduleError, CronError, agent_wakes.WakeError, wake_keys.InvalidWakeKey) as error:
            problems.append(f"{agent}: {error}" if not str(error).startswith(agent) else str(error))
            continue
        if entry["Name"] in entries:
            problems.append(f"{agent} and another agent would share the schedule name {entry['Name']}.")
            continue
        entries[entry["Name"]] = entry
    if problems:
        raise ScheduleError("The agent schedules cannot be reconciled. Nothing was written.\n" + "\n".join(f"  {problem}" for problem in problems))
    return entries


# --- the scheduler ----------------------------------------------------------------------------------------------


def error_code(error: BaseException) -> str:
    return str(((getattr(error, "response", None) or {}).get("Error") or {}).get("Code") or "")


def existing_names(scheduler, group: str) -> list[str] | None:
    """The names of the entries this module manages in the group (``agent-...``), or None when the group is not deployed yet."""
    names: list[str] = []
    token: str | None = None
    while True:
        arguments: dict[str, Any] = {"GroupName": group, "NamePrefix": ENTRY_PREFIX, **({"NextToken": token} if token else {})}
        try:
            page = scheduler.list_schedules(**arguments)
        except Exception as error:
            if error_code(error) == "ResourceNotFoundException":
                return None
            raise
        names += [entry["Name"] for entry in page.get("Schedules", []) if entry["Name"].startswith(ENTRY_PREFIX)]
        token = page.get("NextToken")
        if not token:
            return sorted(names)


_COMPARED = ("ScheduleExpression", "ScheduleExpressionTimezone", "FlexibleTimeWindow", "State")
_COMPARED_TARGET = ("Arn", "RoleArn", "Input", "SqsParameters")


def differs(current: dict[str, Any], wanted: dict[str, Any]) -> bool:
    """Whether the stored entry is not the one wanted. Only what this module sets is compared."""
    if any(current.get(field) != wanted[field] for field in _COMPARED):
        return True
    target = current.get("Target") or {}
    return any(target.get(field) != wanted["Target"][field] for field in _COMPARED_TARGET)


def reconcile(scheduler, names: Names, desired: dict[str, dict[str, Any]], *, apply: bool) -> dict[str, Any]:
    """Make the group's agent entries the ``desired`` ones. Returns what was (or with ``apply`` False, would be) created, updated and deleted.

    A group that is not deployed yet holds nothing: that is fine when nothing is desired, and an error when something is, because the entry has nowhere to go."""
    present = existing_names(scheduler, names.group)
    if present is None:
        if desired:
            raise ScheduleError(f"The schedule group {names.group} is not deployed yet, and {', '.join(sorted(desired))} need it. "
                                "The group is in the site's agents stack, which the first deploy leaves out; deploy the site again and run this step once more.")
        return {"group": names.group, "groupDeployed": False, "created": [], "updated": [], "deleted": [], "unchanged": []}
    created, updated, deleted, unchanged = [], [], [], []
    for name, entry in sorted(desired.items()):
        if name not in present:
            created.append(name)
            if apply:
                scheduler.create_schedule(**entry)
        elif differs(scheduler.get_schedule(Name=name, GroupName=names.group), entry):
            updated.append(name)
            if apply:
                scheduler.update_schedule(**entry)
        else:
            unchanged.append(name)
    for name in present:
        if name not in desired:
            deleted.append(name)
            if apply:
                scheduler.delete_schedule(Name=name, GroupName=names.group)
    return {"group": names.group, "groupDeployed": True, "created": created, "updated": updated, "deleted": deleted, "unchanged": unchanged}


def queue_facts(sqs, names: Names) -> tuple[str, str]:
    """The wake queue's ARN and the scheduler role's ARN, from the queue's own URL (``https://sqs.<region>.amazonaws.com/<account>/<name>``)."""
    url = sqs.get_queue_url(QueueName=names.queue)["QueueUrl"]
    match = re.fullmatch(r"https://sqs\.([a-z0-9-]+)\.amazonaws\.com(?:\.cn)?/(\d{12})/" + re.escape(names.queue), url)
    if not match:
        raise ScheduleError(f"The wake queue's address {url} is not an SQS queue address of the form https://sqs.<region>.amazonaws.com/<account>/{names.queue}.")
    region, account = match.groups()
    partition = "aws-cn" if region.startswith("cn-") else "aws-us-gov" if region.startswith("us-gov-") else "aws"
    return f"arn:{partition}:sqs:{region}:{account}:{names.queue}", f"arn:{partition}:iam::{account}:role/{names.role}"


def router_publication(reader, config: dict) -> dict:
    """The router publication an agent's trigger names: where the tick finds the site's endpoint, model key and policy location."""
    router = reader.router_config(config["monitorId"])
    publication = next((entry for entry in (router or {}).get("publications") or [] if entry.get("publicationId") == config["publicationId"]), None)
    if publication is None:
        raise ScheduleError(f"the router of the monitor {config['monitorId']} does not deliver to the publication {config['publicationId']}.")
    return publication


def reconcile_site(sqs, scheduler, rows: Iterable[dict[str, Any]], site: str, *, reader, endpoint: str | None, apply: bool) -> dict[str, Any]:
    """Everything the deploy step does: find the site's queue, work out the entries from the records, make the group agree."""
    names = names_for(site)
    rows = list(rows)
    live = live_schedules(rows)
    if live and reader is None:
        raise ScheduleError("The schedules need the monitoring table (the router publication of each agent), which is not connected to this account.")
    queue_arn, role_arn = queue_facts(sqs, names) if live else ("", "")
    desired = desired_entries(rows, names, publication_for=lambda record: router_publication(reader, record["trigger"]["config"]),
                              queue_arn=queue_arn, role_arn=role_arn, endpoint=endpoint)
    return reconcile(scheduler, names, desired, apply=apply)
