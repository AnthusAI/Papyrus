"""Story-state triggers: a bot acts when a story enters a stage (PPY-f0914799, under PPY-9ff95b).

An Automation whose trigger is ``{"kind": "event", "config": {"event": "story.stage_entered", "onStage": "copywriting",
"nextStage": "typesetting", "monitorId": ..., "publicationId": ...}}`` starts its procedure when a story enters
``onStage`` (any way: a person's move or save, a bot's move, or a story created there). The procedure writes a new
version and returns ``{"version": <id>}``; THE ENGINE then moves the story to ``nextStage`` as ``automation:<id>``, which
can start the next bot. Human input is never a state: when a person is wanted, a review request is raised.

The contract (Distinctive's procedures are written against it):

* Input: the record's static ``inputTemplate`` merged under ``{story, version, versionNumber, stage, runKey, automationId,
  hop}``, which win. ``version`` is the version that entered the stage; ``hop`` is the bot runs on this story so far,
  including this one.
* Output: ``{"version": <new version id>}``, optionally ``{"hold": true, "reason": "..."}`` (do not advance; a flag review
  request carries the reason).
* A bot that finds nothing to change returns the version it received (``{"version": <entering version>, "hold": false}``): that
  is success. The story advances, the trail says "no changes", and no version is labelled. Other keys in the output (corrections,
  unverifiable, remaining_findings) are not interpreted; the runner stores the whole output on the run record.
* A failed or timed-out run leaves the story where it is and raises a flag review request with the error. No ``nextStage``:
  the story stays.
* One run per (story, stage, version): the claim is a conditional put of ``STAGE#<automation>#<story>#<stage>#<version>`` in
  the monitor's partition of the monitoring table; the same row is the link the runner updates with the run and outcome.
* Bot actions are labelled: the runner's actor, the trail notes and the move are ``automation:<id>``, and the version the bot
  wrote gets ``metadata.botAction``.
* Hop limit: ``Item.metadata.botChain.hops`` counts bot runs started on the story. At the limit (record ``maxHops``,
  default 5) nothing starts, the story stays, and a hard-gate review request "bot hop limit reached" is raised.

Not here yet: the per-story budget cap (``botChain.costUsd`` is reserved, nothing writes it), a group lock, and moves made in
the console board (a browser move writes the Item directly; run ``papyrus stories fire-triggers`` for it).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .automation_gate import decide, limits_of

STAGE_ENTERED = "story.stage_entered"
DEFAULT_MAX_HOPS = 5
MAX_HOPS = 50
STAGE_ROW_PREFIX = "STAGE#"
CHAIN_KEY = "botChain"
BOT_ACTION_KEY = "botAction"


def bot_label(automation_id: str) -> str:
    return f"automation:{automation_id}"


def is_stage_trigger(trigger: Any) -> bool:
    config = trigger.get("config") if isinstance(trigger, dict) else None
    return isinstance(trigger, dict) and trigger.get("kind") == "event" and isinstance(config, dict) and config.get("event") == STAGE_ENTERED


def stage_prefix(automation_id: str) -> str:
    return f"{STAGE_ROW_PREFIX}{automation_id}#"


def stage_key(automation_id: str, story: str, stage: str, version: str) -> str:
    return f"{stage_prefix(automation_id)}{story}#{stage}#{version}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe(text: str, limit: int = 80) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-")[:limit]


def story_metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except json.JSONDecodeError:
            value = {}
    return dict(value) if isinstance(value, dict) else {}


def chain_of(row: dict[str, Any]) -> dict[str, Any]:
    chain = story_metadata(row).get(CHAIN_KEY)
    chain = chain if isinstance(chain, dict) else {}
    hops = chain.get("hops")
    return {**chain, "hops": hops if isinstance(hops, int) and not isinstance(hops, bool) and hops >= 0 else 0}


def _write_metadata(client, row: dict[str, Any], **changes: Any) -> None:
    from .record_helpers import to_aws_json

    client.update_record("Item", {"id": row["id"], "metadata": to_aws_json({**story_metadata(row), **changes})})


def stage_automations(client, stage: str) -> list[dict[str, Any]]:
    """The automations that fire when a story enters `stage`, enabled or not, lowest id first."""
    from .automations import read_record

    found = []
    for row in client.list_records("Automation"):
        record = read_record(row)
        if is_stage_trigger(record["trigger"]) and record["onStage"] == stage and record["id"]:
            found.append(record)
    return sorted(found, key=lambda record: record["id"])


def max_hops_of(automation: dict[str, Any]) -> int:
    value = automation.get("maxHops")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else DEFAULT_MAX_HOPS


def raise_hop_limit_review(client, *, story: str, stage: str, automation_id: str, hops: int, limit: int) -> dict[str, Any]:
    """ONE hard-gate review request for a story whose bot chain reached its limit (idempotent per story and limit)."""
    from .review_requests import raise_review

    return raise_review(
        client, subject={"type": "story", "id": story}, mode="hard_gate", raised_by=bot_label(automation_id),
        reason=f"bot hop limit reached: bots ran {hops} times on this story (limit {limit}); {automation_id} did not start on {stage}",
        ask="Read the latest version and move the story on yourself, or raise maxHops on the automation to let the bots continue.",
        request_id=f"rr-bot-hops-{_safe(story, 90)}-{limit}")


def raise_run_flag(client, *, story: str, automation_id: str, key: str, reason: str) -> dict[str, Any]:
    """A flag review request for a bot run that did not advance the story (failed, timed out, held, or returned nothing)."""
    from .review_requests import raise_review

    return raise_review(client, subject={"type": "story", "id": story}, mode="flag", raised_by=bot_label(automation_id),
                        reason=reason[:1000], ask="The story stayed where it was. Read it and move it on, or fix the cause.",
                        request_id=f"rr-bot-run-{_safe(key, 110)}")


def deliver_stage_entered(client, *, story: str, reader, writer, invoke, now: str | None = None, site_endpoint: str | None = None) -> list[dict[str, Any]]:
    """Fire every automation for the story's CURRENT stage and version. One outcome per automation.

    Safe to call again for the same story, stage and version: a claimed run is never started twice."""
    from .story_reporting import latest_story_version

    row = latest_story_version(client, story)
    stage = row.get("stage") or "idea"
    stamp = now or _now()
    outcomes = []
    for automation in stage_automations(client, stage):
        outcome = {"automationId": automation["id"], "story": story, "stage": stage, "version": row["id"]}
        outcomes.append(outcome)
        if not automation["enabled"]:
            outcome.update(status="skipped", reason="automation disabled")
            continue
        chain = chain_of(row)
        limit = max_hops_of(automation)
        if chain["hops"] >= limit:
            review = raise_hop_limit_review(client, story=story, stage=stage, automation_id=automation["id"], hops=chain["hops"], limit=limit)
            outcome.update(status="blocked", reason=f"bot hop limit reached ({chain['hops']} of {limit})", reviewRequestId=review["id"])
            continue
        outcome.update(_start(client, automation, row=row, chain=chain, reader=reader, writer=writer, invoke=invoke, stamp=stamp,
                              site_endpoint=site_endpoint))
        if outcome["status"] == "started":
            row = {**row, "metadata": json.dumps({**story_metadata(row), CHAIN_KEY: {**chain, "hops": chain["hops"] + 1}})}
    return outcomes


def _start(client, automation, *, row, chain, reader, writer, invoke, stamp, site_endpoint) -> dict[str, Any]:
    from .story_reporting import append_story_message

    config = automation["trigger"]["config"]
    story, stage, version = row["lineageId"], row.get("stage") or "idea", row["id"]
    if reader is None or writer is None:
        return {"status": "refused", "reason": "the monitoring table is not connected to this site's account"}
    router = reader.router_config(config["monitorId"])
    publication = next((entry for entry in (router or {}).get("publications") or []
                        if entry.get("publicationId") == config["publicationId"]), None)
    if publication is None or not publication.get("openaiKeyParameter"):
        return {"status": "refused", "reason": "the router has no publication with a model key for this automation"}
    if site_endpoint is not None and publication.get("appsyncEndpoint") != site_endpoint:
        return {"status": "refused", "reason": "this automation's publication belongs to another site"}
    rows = reader.rows_with_prefix(config["monitorId"], stage_prefix(automation["id"]))
    gate = decide({"id": automation["id"], "enabled": True, "limits": limits_of({"limits": automation["limits"]})}, rows,
                  now=datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())
    if gate.action != "start":
        return {"status": "deferred", "reason": gate.reason}
    pk, sk = f"MONITOR#{config['monitorId']}", stage_key(automation["id"], story, stage, version)
    hop = chain["hops"] + 1
    values = {"story": story, "version": version, "versionNumber": int(row.get("versionNumber") or 1), "stage": stage, "runKey": sk,
              "automationId": automation["id"], "hop": hop}
    request = {"publicationId": publication["publicationId"], "appsyncEndpoint": publication["appsyncEndpoint"],
               "openaiKeyParameter": publication["openaiKeyParameter"], "procedureKey": automation["procedureKey"],
               "input": {**(automation.get("inputTemplate") or {}), **values}, "actorLabel": bot_label(automation["id"]),
               "timeoutSeconds": gate.timeout_seconds,
               "trigger": {"kind": "event", "event": STAGE_ENTERED, "automationId": automation["id"], "monitorId": config["monitorId"],
                           "pk": pk, "sk": sk, "story": story, "stage": stage, "version": version,
                           "title": f"{automation['procedureKey']}: story entered {stage}"[:200],
                           "summary": f"Automation {automation['id']} started because story {story} entered {stage} (version {version})"[:500]}}
    claim = {"pk": pk, "sk": sk, "publicationId": publication["publicationId"], "procedureKey": automation["procedureKey"],
             "automationId": automation["id"], "storyId": story, "stage": stage, "version": version, "requestedBy": bot_label(automation["id"]),
             "createdAt": stamp, "startedAt": stamp, "status": "starting", "request": request}
    if not writer.claim(claim):
        return {"status": "duplicate", "reason": "this story, stage and version already started a run"}
    _write_metadata(client, row, **{CHAIN_KEY: {**chain, "hops": hop, "lastAutomation": automation["id"]}})
    try:
        append_story_message(client, story, body=f"Bot {automation['id']} started on {stage} (version {version}, hop {hop}).",
                             summary=f"Bot {automation['id']} started on {stage}", author_label=bot_label(automation["id"]),
                             message_kind="note", now=stamp)
    except Exception:   # the trail note is a label, never a reason to skip the run
        pass
    try:
        invoke(request)
    except Exception as error:   # nothing started: the claim row says so (the hop is not refunded)
        writer.put({**claim, "status": "startFailed", "error": type(error).__name__})
        return {"status": "startFailed", "reason": f"the procedure runner could not be started ({type(error).__name__})"}
    return {"status": "started", "key": sk, "hop": hop}


def finish_stage_run(client, trigger: dict[str, Any], result: dict[str, Any], *, reader, writer, invoke, now: str | None = None) -> dict[str, Any]:
    """After the runner records a stage-entry run: advance the story, or raise a review request and leave it.

    `result` is the runner's result (``runStatus``, ``error``, ``output``). Moves the story to the record's ``nextStage`` only when
    the run completed with a new version and no hold, and only if the story is still in the stage the run started from."""
    from .automations import read_record
    from .story_reporting import current_story_version, move_story_stage

    automation_id, story, stage, key = trigger["automationId"], trigger["story"], trigger["stage"], trigger["sk"]
    row = client.get_record("Automation", automation_id)
    if not row:
        return {"status": "stayed", "reason": "the automation no longer exists"}
    automation = read_record(row)
    if result.get("runStatus") != "completed":
        raise_run_flag(client, story=story, automation_id=automation_id, key=key,
                       reason=f"{automation_id} did not finish on {stage}: {result.get('error') or result.get('runStatus') or 'failed'}")
        return {"status": "failed"}
    output = result.get("output") if isinstance(result.get("output"), dict) else {}
    if output.get("hold"):
        raise_run_flag(client, story=story, automation_id=automation_id, key=key,
                       reason=f"{automation_id} held the story in {stage}: {output.get('reason') or 'no reason given'}")
        return {"status": "held"}
    version = output.get("version")
    if not isinstance(version, str) or not version:
        raise_run_flag(client, story=story, automation_id=automation_id, key=key,
                       reason=f"{automation_id} finished on {stage} without returning a new version")
        return {"status": "no_version"}
    unchanged = version == trigger.get("version")
    version_row = None if unchanged else client.get_record("Item", version)   # the entering version is not the bot's to label
    if unchanged:
        from .story_reporting import append_story_message

        try:
            append_story_message(client, story, body=f"Bot {automation_id} made no changes to version {version}.",
                                 summary=f"Bot {automation_id}: no changes", author_label=bot_label(automation_id),
                                 message_kind="note", now=now)
        except Exception:   # a label, never a reason to hold the story
            pass
    if version_row:
        _write_metadata(client, version_row, **{BOT_ACTION_KEY: {"automationId": automation_id, "at": now or _now(), "runKey": key}})
    target = automation.get("nextStage")
    extra = {"noChanges": True} if unchanged else {}
    if not target:
        return {"status": "stayed", "version": version, **extra}
    if (current_story_version(client, story).get("stage") or "idea") != stage:
        return {"status": "stayed", "version": version, "reason": "the story was moved by someone else while the bot ran", **extra}
    move_story_stage(client, story, target, actor=bot_label(automation_id), reason=f"{automation_id} finished" + (" (no changes)" if unchanged else ""), now=now)
    chained = deliver_stage_entered(client, story=story, reader=reader, writer=writer, invoke=invoke, now=now)
    return {"status": "moved", "version": version, "stage": target, "next": chained, **extra}


def deliver_from_environment(client, story: str) -> list[dict[str, Any]]:
    """What the CLI calls after a person changes a story's stage: deliver, print one line per automation, never fail the change.

    The monitoring table and the runner come from the operator's AWS credentials, as for `papyrus automations run`."""
    from .automations import MonitoringReader, MonitoringWriter, lambda_invoker, monitoring_table_from_environment
    from .story_reporting import latest_story_version

    try:
        if not stage_automations(client, latest_story_version(client, story).get("stage") or "idea"):
            return []
        table = monitoring_table_from_environment()
        outcomes = deliver_stage_entered(
            client, story=story, invoke=lambda_invoker(),
            reader=MonitoringReader(table) if table is not None else None, writer=MonitoringWriter(table) if table is not None else None)
    except Exception as error:   # a stage change is never undone or failed by its triggers
        print(f"stories\ttriggers\tnot delivered\t{type(error).__name__}")
        return []
    for outcome in outcomes:
        print("\t".join(["stories", "triggers", outcome["automationId"], outcome["status"], outcome.get("reason") or outcome.get("key") or ""]))
    return outcomes
