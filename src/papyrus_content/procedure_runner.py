"""The cloud procedure runner: executes a newsroom's published Tactus procedure for one request.

A request names the publication (its AppSync endpoint and the SSM parameter holding its OpenAI key), the
procedure key and the input. The runner loads the published version with its code and skill attachments,
records a ProcedureRun through the newsroom's external-execution path, runs the procedure in a child process
with a deadline inside the Lambda's own, and records the outcome. See docs/procedure-runner.md.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from . import agent_wakes, request_meter, run_continuation, run_outcomes, run_settle, unusual_cost, wake_keys
from .agent_gate import review_answers, run_context, run_end
from .cloud_procedures import (
    START_PROCEDURE_RUN_MUTATION, current_cloud_procedure_version, get_cloud_procedure_definition_by_key,
    normalize_graphql_json_value, update_cloud_procedure_run_record)
from .agent_policy import Gate, PolicyGate, PolicyNotLocated, PolicyUnreadable, UnlocatedPolicy
from .agent_policy.run_gate import RunDecision
from .spend_brake import SpendBrake
from .spend_stop import SpendStop, runner_timers
from .policy_location import S3_BUCKET
from .model_cost import estimate_cost
from .site_procedures import SKILL_SORT_KEY_PREFIX
from .tenancy import TENANT_ID_ENVIRONMENT_VARIABLE, TenantError, validate_tenant_id

SECONDS_KEPT_FOR_RECORDING = 60
MAX_TIMEOUT_SECONDS = 840          # the Lambda's 15 minutes less the recording margin; an automation's limit is capped here
MAX_RECORDED_CALLS = 200
MAX_SUMMARY_CHARACTERS = 500
OUTPUT_SUMMARY_FIELDS = ("title", "summary", "next_step", "story")
APPSYNC_ENDPOINT = re.compile(r"^https://[a-z0-9]+\.appsync-api\.[a-z0-9-]+\.amazonaws\.com/graphql$")
DUPLICATE = "duplicate"   # a wake whose key already has a run record: reported, never run
SSM_PARAMETER = re.compile(r"^/[A-Za-z0-9_./-]{1,1000}$")


class ProcedureNotRunnable(Exception):
    """The request cannot run. `run_id` names the run record when one was already made (it is then marked failed)."""

    run_id: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_request(request: dict) -> dict:
    endpoint = str(request.get("appsyncEndpoint") or "")
    key = str(request.get("procedureKey") or "")
    parameter = str(request.get("openaiKeyParameter") or "")
    if not APPSYNC_ENDPOINT.match(endpoint):
        raise ProcedureNotRunnable("appsyncEndpoint must be an AppSync GraphQL URL")
    if not key:
        raise ProcedureNotRunnable("procedureKey is required")
    if parameter and not SSM_PARAMETER.match(parameter):
        raise ProcedureNotRunnable("openaiKeyParameter must be an SSM parameter name")
    try:
        wake_key = wake_keys.checked(request.get("wakeKey"))
    except wake_keys.InvalidWakeKey as invalid:
        raise ProcedureNotRunnable(str(invalid)) from invalid
    if not isinstance(request.get("input") or {}, dict):
        raise ProcedureNotRunnable("input must be an object")
    tenant_id, site_bucket = request.get("tenantId"), str(request.get("siteBucket") or "")
    if tenant_id is not None:   # present means a publication tenant: a string that is a valid tenant id, never an empty or coerced value
        try:
            if not isinstance(tenant_id, str):
                raise ValueError("tenant must be a string")
            tenant_id = validate_tenant_id(tenant_id)
        except (TenantError, ValueError) as invalid:
            raise ProcedureNotRunnable("tenantId must be a valid publication tenant id") from invalid
    if site_bucket and not S3_BUCKET.match(site_bucket):
        raise ProcedureNotRunnable("siteBucket must be an S3 bucket name")
    site_origin = request.get("siteOrigin")
    if site_origin is not None and not is_plain_https_origin(site_origin):
        raise ProcedureNotRunnable("siteOrigin must be a plain https origin")
    timeout = request.get("timeoutSeconds")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1):
        raise ProcedureNotRunnable("timeoutSeconds must be a positive whole number")
    return {"appsyncEndpoint": endpoint, "procedureKey": key, "wakeKey": wake_key, "openaiKeyParameter": parameter or None,
            "timeoutSeconds": None if timeout is None else min(timeout, MAX_TIMEOUT_SECONDS),
            "input": dict(request.get("input") or {}), "publicationId": str(request.get("publicationId") or ""),
            "tenantId": tenant_id or None, "siteBucket": site_bucket or None, "siteOrigin": site_origin or None,
            "actorLabel": str(request.get("actorLabel") or "Papyrus procedure runner"),
            "trigger": request.get("trigger") if isinstance(request.get("trigger"), dict) else None}


def load_published_procedure(client, procedure_key: str, version_id: str | None = None) -> dict[str, Any]:
    from .model_attachments import download_attachment_buffer

    try:
        definition = get_cloud_procedure_definition_by_key(client, procedure_key)
    except Exception as error:
        raise ProcedureNotRunnable(f"procedure {procedure_key} was not found: {error}") from error
    if not definition:
        raise ProcedureNotRunnable(f"procedure {procedure_key} was not found")
    if definition.get("enabled") is False:
        raise ProcedureNotRunnable(f"procedure {procedure_key} is disabled")
    version = current_cloud_procedure_version(definition)
    if not version or version.get("status") != "published":
        raise ProcedureNotRunnable(f"procedure {procedure_key} has no published current version")
    if version_id and version["id"] != version_id:
        raise ProcedureNotRunnable(f"procedure {procedure_key} was republished while the run was starting; the run record names version {version_id}")
    attachments = [entry for entry in client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", version["id"], limit=100)
                   if str(entry.get("status") or "active") == "active"]
    source = str(version.get("tactusSource") or "")
    if source.strip().startswith("attachment://"):
        code = next((entry for entry in attachments
                     if entry.get("role") == "code" and str(entry.get("sortKey") or "code") == "code"), None)
        if code is None:
            raise ProcedureNotRunnable(f"procedure {procedure_key} version {version['id']} has no code attachment")
        source = (download_attachment_buffer(client, code) or b"").decode("utf-8")
    if not re.search(r"\bProcedure\s*\{", source):
        raise ProcedureNotRunnable(f"procedure {procedure_key} version {version['id']} has no Tactus Procedure")
    skills = []
    for entry in attachments:
        sort_key = str(entry.get("sortKey") or "")
        if entry.get("role") == "code" and sort_key.startswith(SKILL_SORT_KEY_PREFIX):
            skills.append((sort_key.removeprefix(SKILL_SORT_KEY_PREFIX), download_attachment_buffer(client, entry) or b""))
    return {"definition": definition, "version": version, "source": source, "skills": skills}


def materialize(workdir: Path, source: str, skills: list[tuple[str, bytes]]) -> Path:
    """Writes the skills at their registered relative paths, so the procedure's `skills = {...}` resolve from `workdir`."""
    for relative_path, body in skills:
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ProcedureNotRunnable(f"skill path {relative_path} escapes the working directory")
        target = workdir.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    source_path = workdir / "procedure.tac"
    source_path.write_text(source, encoding="utf-8")
    return source_path


def execute_in_child(workdir: Path, source_path: Path, inputs: dict, *, timeout_seconds: float, environment: dict) -> dict:
    input_path, result_path = workdir / "input.json", workdir / "result.json"
    input_path.write_text(json.dumps(inputs), encoding="utf-8")
    command = [sys.executable, "-m", "papyrus_content.procedure_runner_child", str(source_path), str(input_path), str(result_path)]
    started = time.monotonic()
    try:
        completed = subprocess.run(command, cwd=workdir, env=environment, capture_output=True, text=True,
                                   timeout=max(timeout_seconds, 1))
    except subprocess.TimeoutExpired as error:
        return {"success": False, "error": f"timed out after {int(timeout_seconds)} s",
                "logTail": str(error.stderr or "")[-4000:], "seconds": round(time.monotonic() - started, 1)}
    seconds = round(time.monotonic() - started, 1)
    print(completed.stdout[-20000:])
    print(completed.stderr[-20000:], file=sys.stderr)
    if result_path.is_file():
        return {**json.loads(result_path.read_text(encoding="utf-8")), "seconds": seconds}
    return {"success": False, "error": f"the procedure process exited {completed.returncode} without a result",
            "logTail": completed.stderr[-4000:], "seconds": seconds}


def summarize_output(output: Any, seconds: float) -> str:
    details = []
    if isinstance(output, dict):
        details = [f"{field}: {output[field]}" for field in OUTPUT_SUMMARY_FIELDS if output.get(field)]
    return "; ".join([f"Completed in {seconds:g} s", *details])[:MAX_SUMMARY_CHARACTERS]


def start_run_record(client, request: dict) -> dict[str, Any]:
    """Makes the run's record from its wake key, as `started`, before anything is loaded. The newsroom derives the record's id from the
    key and creates it with a condition, so a wake already recorded comes back as `duplicate` and is not run again."""
    trigger = request.get("trigger") or {}
    try:
        data = client.graphql(START_PROCEDURE_RUN_MUTATION, {
            "procedureKey": request["procedureKey"], "wakeKey": request["wakeKey"],
            "title": trigger.get("title") or request["procedureKey"],
            "summary": trigger.get("summary") or "Started by the Papyrus procedure runner",
            "actorLabel": request["actorLabel"],
            "input": json.dumps({**request["input"], "__papyrusExecutionMode": "external_cli"})})
    except Exception as error:   # the newsroom refused: an unknown or disabled procedure. No record exists, and none is claimed.
        raise ProcedureNotRunnable(f"procedure {request['procedureKey']} could not be started: {error}") from error
    started = normalize_graphql_json_value(data.get("startNewsroomProcedureRun")) or {}
    if not started.get("runId"):
        raise ProcedureNotRunnable("the newsroom did not return a run id")
    return {"runId": started["runId"], "duplicate": bool(started.get("duplicate")), "versionId": started.get("procedureVersionId")}


def refuse_run(client, run_id: str, error: Exception, request: dict, *, now: Callable[[], str], reason: str = run_outcomes.NOT_RUNNABLE) -> None:
    """The run record exists but the run cannot begin (the procedure cannot be loaded, the policy cannot be read, or the request names no policy):
    the record says so, so it never stays `started` for a run that never began, and it names the automation and the subject the wake was for, so
    the automation's run list shows the refusal."""
    stamp, trigger = now(), request.get("trigger") or {}
    update_cloud_procedure_run_record(client, {
        "id": run_id, "runStatus": "failed", "outcome": "failed", "outcomeReason": reason,
        "automationId": trigger.get("automationId"), **run_outcomes.run_subject(trigger),
        "startedAt": stamp, "finishedAt": stamp, "errorSummary": str(error)[:MAX_SUMMARY_CHARACTERS],
        "error": {"message": str(error)}, "attempt": 1, **kept_wake(request)})


def child_timeout(request: dict, seconds_available: float) -> float:
    """The child's deadline: what the Lambda has left less the recording margin, or the request's own limit if shorter."""
    room = seconds_available - SECONDS_KEPT_FOR_RECORDING
    return min(room, request["timeoutSeconds"]) if request.get("timeoutSeconds") else room


def tool_counts(tools_used: Any) -> dict[str, int]:
    """Tool name -> number of calls, from the child's `toolsUsed`. Names and counts only: never arguments or results."""
    counts: dict[str, int] = {}
    for entry in tools_used if isinstance(tools_used, list) else []:
        name = entry if isinstance(entry, str) else (entry.get("name") or entry.get("tool") or entry.get("tool_name")) if isinstance(entry, dict) else None
        if isinstance(name, str) and name:
            counts[name[:100]] = counts.get(name[:100], 0) + 1
    return counts


def usage_record(outcome: dict) -> tuple[dict | None, float | None]:
    """The usage to store on the ProcedureRun (calls plus the estimate, and the tools used by name and count) and the
    estimated cost, or (None, None) when the procedure made no model call and used no tool."""
    calls = [call for call in (outcome.get("usage") or []) if isinstance(call, dict)]
    tools = tool_counts(outcome.get("toolsUsed"))
    extra = {"toolsUsed": tools} if tools else {}
    if not calls:
        return (extra or None), None
    estimate = estimate_cost(calls)
    summary = {key: estimate[key] for key in ("complete", "unpricedModels", "unpricedCalls", "calls", "promptTokens", "completionTokens", "models")}
    tiers: dict[str, int] = {}
    for call in calls:
        if call.get("tier"):
            tiers[str(call["tier"])] = tiers.get(str(call["tier"]), 0) + 1
    if tiers:
        summary["tiers"] = tiers   # the tier each model call was made for; the model is in `models` and on every call in `perCall`
    return {**summary, "perCall": calls[:MAX_RECORDED_CALLS], **extra}, estimate["costUsd"]


def spend_of(request: dict, decision, usage: dict | None, cost_usd: float | None) -> dict | None:
    """What the ledger needs to count this run: the site, the agent that made it, the budget period of the site's policy, the model calls with their cost, and
    the owner's per-run budget for the agent (``agents.<responsibility>.budgetUsdPerRun``, which only flags). None when the run made no model call. A site
    with no budget in its policy is counted by the month."""
    if not usage or not usage.get("calls") or not request.get("tenantId"):
        return None
    document = decision.state.document if decision.state is not None else {}
    site, agent = document.get("site") or {}, (document.get("agents") or {}).get(decision.responsibility or "") or {}
    return {"tenantId": request["tenantId"], "responsibility": decision.responsibility, "period": (site.get("budget") or {}).get("period", "month"),
            "costUsd": cost_usd, "calls": usage["calls"], "unpricedCalls": usage.get("unpricedCalls", 0), "budgetUsdPerRun": agent.get("budgetUsdPerRun")}


def record_spend(table, client, result: dict, *, moment: datetime | None = None) -> dict | None:
    """Add a finished run's cost to the spend ledger, once, after judging it against its agent's history: an unusual cost, or one over the owner's per-run
    budget, raises one flag and stops nothing (unusual_cost.py). A run that made no model call adds nothing."""
    return unusual_cost.watch_run(table, client, result, moment=moment)


def kept_wake(request: dict) -> dict[str, Any]:
    """An agent's change wake stays on its run record (``wake``), whatever came of it, so a person can send it again: resuming sends once each subject's
    latest wake a pause stopped, and wake now sends a subject's latest wake again (``agent_poke_in.py``). A timer's tick or a person's Run now is never sent
    again, so it keeps nothing."""
    trigger = request.get("trigger") or {}
    if trigger.get("kind") != "event" or not trigger.get("automationId"):
        return {}
    return {"wake": request}


def skip_run(client, run_id: str, request: dict, decision, *, now: Callable[[], str]) -> dict:
    """The site's policy says this wake starts nothing: the record says so (a finished run that did nothing, with the reason code), names
    the responsibility, policy version and rung it was decided under, and the words say why. Nothing of the procedure is loaded."""
    stamp, trigger = now(), request.get("trigger") or {}
    update_cloud_procedure_run_record(client, {
        "id": run_id, "runStatus": "completed", "outcome": "nothing", "outcomeReason": decision.reason_code,
        "automationId": trigger.get("automationId"), **run_outcomes.run_subject(trigger), **decision.run_fields(),
        "startedAt": stamp, "finishedAt": stamp, "attempt": 1, "resultSummary": decision.reason[:MAX_SUMMARY_CHARACTERS], **kept_wake(request)})
    return {"runId": run_id, "procedureKey": request["procedureKey"], "wakeKey": request["wakeKey"], "skipped": True,
            "runStatus": "completed", "outcome": "nothing", "outcomeReason": decision.reason_code, "reason": decision.reason,
            "responsibility": decision.responsibility, "rung": decision.rung, "policyVersion": decision.policy_version, "error": None}


def stop_for_answer(client, run_id: str, request: dict, decision, answer: review_answers.ReviewAnswer, *, now: Callable[[], str]) -> dict:
    """A person's answer means this wake runs nothing: it was a rejection, or the answer was already used. The record says so (a finished run that did
    nothing, with the reason code and the person's words), and a rejection is written on the request as used by this run. Nothing of the procedure is loaded."""
    reason_code, words = answer.stop_reason()
    stamp, trigger = now(), request.get("trigger") or {}
    update_cloud_procedure_run_record(client, {
        "id": run_id, "runStatus": "completed", "outcome": "nothing", "outcomeReason": reason_code,
        "automationId": trigger.get("automationId"), **run_outcomes.run_subject(trigger), **decision.run_fields(),
        "startedAt": stamp, "finishedAt": stamp, "attempt": 1, "resultSummary": words[:MAX_SUMMARY_CHARACTERS]})
    if not answer.applied_in:
        review_answers.record_used(client, answer, run_id, decision.responsibility)
    return {"runId": run_id, "procedureKey": request["procedureKey"], "wakeKey": request["wakeKey"], "skipped": True,
            "runStatus": "completed", "outcome": "nothing", "outcomeReason": reason_code, "reason": words,
            "responsibility": decision.responsibility, "rung": decision.rung, "policyVersion": decision.policy_version, "error": None}


def policy_for(request: dict, client, s3: Callable[[], Any]) -> Gate:
    """The gate that reads this request's site policy. A request that does not say where the policy is gets the gate that refuses it: the run
    record is made first, and the refusal is recorded on it (`no_site_policy`), so the automation's run list shows it."""
    if not (request.get("tenantId") and request.get("siteBucket")):
        return UnlocatedPolicy()   # the run is refused and recorded as a failed run, not raised before it has a record
    return PolicyGate.for_site(client, s3=s3(), bucket=request["siteBucket"], tenant_id=request["tenantId"])


def handoff_of(request: dict) -> dict[str, str] | None:
    """The Assignment this wake is the work of and the agent doing it, or None (agent_assignments.assignment_of_request)."""
    from . import agent_assignments

    assignment, agent = agent_assignments.assignment_of_request(request), (request.get("trigger") or {}).get("automationId")
    return {"assignment": assignment, "agent": str(agent)} if assignment and agent else None


def run_procedure_request(request: dict, *, client, policy: Gate, execute: Callable[..., dict], seconds_available: float,
                          environment: dict, now: Callable[[], str] = utc_now, workroot: Path | None = None,
                          run_started: Callable[[str], None] | None = None, receive_count: int = 1,
                          schedule_continuation: Callable[[dict, str, str], None] | None = None, spend_brake: Any = None,
                          spend_stop: Any = None) -> dict:
    request = validate_request(request)
    started = start_run_record(client, request)   # the record exists, `started`, before any procedure is loaded
    run_id = started["runId"]
    attempt = 1
    waiting = False   # this wake waited for the budget cycle and has come again (spend_stop.py, PPY-9376f8)
    if started["duplicate"]:   # this wake already has its run: nothing more happens for it, unless the queue says the first attempt died or it waited
        reads_record = receive_count >= run_settle.SETTLING_RECEIPT or spend_stop is not None
        existing_run = client.get_record(run_settle.RUN_MODEL, run_id) if reads_record else None
        waiting = spend_stop is not None and spend_stop.is_waiting(existing_run)
    if started["duplicate"] and not waiting:
        if not run_settle.first_attempt_died(existing_run, receive_count):
            return {"runId": run_id, "procedureKey": request["procedureKey"], "wakeKey": request["wakeKey"], "duplicate": True,
                    "runStatus": DUPLICATE, "outcome": None, "outcomeReason": None, "error": None}
        if not run_settle.safe_to_repeat(request):
            return run_settle.record_unknown(client, run_id, existing_run, request, now=now)
        attempt = run_settle.REPEAT_ATTEMPT
    try:
        decision = policy.decide(request)   # the site's policy is read here, before anything is loaded or run
    except PolicyUnreadable as error:
        refuse_run(client, run_id, error, request, now=now,
                   reason=run_outcomes.NO_SITE_POLICY if isinstance(error, PolicyNotLocated) else run_outcomes.POLICY_UNREADABLE)
        not_started = ProcedureNotRunnable(str(error))
        not_started.run_id = run_id
        raise not_started from error
    if not decision.start:
        if waiting:
            spend_stop.clear_wait(client, run_id)
        return skip_run(client, run_id, request, decision, now=now)
    answer = None
    if decision.state is not None and decision.responsibility:   # an agent woken by a person's answer to its review request reads the answer again (PPY-ecf852)
        try:
            answer = review_answers.answer_of(client, request)
        except review_answers.AnswerUnreadable as error:
            refuse_run(client, run_id, error, request, now=now, reason=review_answers.ANSWER_UNREADABLE)
            not_started = ProcedureNotRunnable(str(error))
            not_started.run_id = run_id
            raise not_started from error
        if answer is not None and not answer.continues_the_work:
            return stop_for_answer(client, run_id, request, decision, answer, now=now)
        if answer is not None:
            request = {**request, "input": {**request["input"], review_answers.REVIEW_INPUT_KEY: answer.as_input()}}
    stop = spend_brake.stop_for(request, decision) if spend_brake is not None else None
    held = spend_stop.settle(client, run_id, request, decision, stop, waiting=waiting) if spend_stop is not None else None
    if held is not None:   # at the budget a paid wake waits for the next cycle, or this wake released the waiting ones
        return held
    if stop is not None:
        print(json.dumps({"spendBrake": stop.reason_code, "tenantId": request.get("tenantId"), "runId": run_id, "wakeKey": request.get("wakeKey")}))
        return skip_run(client, run_id, request, RunDecision(False, decision.responsibility, decision.rung, decision.policy_version, stop.reason_code, stop.reason), now=now)
    started_at = now()
    handoff = handoff_of(request) if decision.state is not None else None   # an agent's run for an Assignment another responsibility filed (PPY-51f96f)
    if handoff:
        from . import agent_assignments

        agent_assignments.begin(client, handoff["assignment"], handoff["agent"], now=started_at)   # the run record is the claim; this makes it visible on the Assignment
    if run_started is not None:
        try:
            run_started(run_id)   # lets the trigger row name its run while it is still running
        except Exception:
            pass
    try:
        procedure = load_published_procedure(client, request["procedureKey"], started["versionId"])
    except ProcedureNotRunnable as error:
        refuse_run(client, run_id, error, request, now=now)
        if handoff:   # the claimed Assignment must not be left looking in hand
            agent_assignments.finish(client, handoff["assignment"], handoff["agent"], run_id=run_id, outcome="failed", reason=run_outcomes.NOT_RUNNABLE,
                                     summary=None, error=str(error), now=now())
        error.run_id = run_id
        raise
    workdir = Path(tempfile.mkdtemp(prefix="papyrus-procedure-", dir=workroot))
    try:
        source_path = materialize(workdir, procedure["source"], procedure["skills"])
        timeout = child_timeout(request, seconds_available)
        if decision.state is not None and decision.responsibility:   # an agent's run: the child gets the policy it was decided under and its deadline
            environment = {**environment, **run_context.to_environment(run_id, decision.responsibility, decision.state, time.time() + timeout)}
        outcome = execute(workdir, source_path, request["input"], timeout_seconds=timeout, environment=environment)
    except Exception as error:
        outcome = {"success": False, "error": f"{type(error).__name__}: {error}", "seconds": 0}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    output = outcome.get("output")
    gate = None
    if outcome.get("success") and decision.state is not None and decision.responsibility:
        gate = run_end.settle(client, decision.state, decision.responsibility, run_id, output,   # the gate's answers; a person's needed answer is `asked`
                              approvals=answer.approvals if answer is not None else None)
    if gate is not None:
        output = {**output, "gate": gate.record}   # every answer, in order, on the run record
    if gate is not None and gate.error:
        ended = run_outcomes.finished_outcome(False, None, gate.error) | {"outcomeReason": run_end.REVIEW_REQUEST_FAILED}
    elif gate is not None and gate.blocked and gate.declaration is None:
        ended = run_outcomes.finished_outcome(False, None, f"The run asked for {', '.join(gate.blocked)}, which no agent may do.") | {"outcomeReason": run_end.GATE_BLOCKED}
    else:
        ended = run_outcomes.finished_outcome(bool(outcome.get("success")), {**output, **gate.declaration} if gate and gate.declaration else output, outcome.get("error"))
    ended = continue_or_fail(ended, output, request, run_id, schedule_continuation)
    succeeded = ended["runStatus"] == "completed"
    usage, cost_usd = usage_record(outcome)
    trigger = request.get("trigger") or {}
    record = {
        "id": run_id, "runStatus": ended["runStatus"], "outcome": ended["outcome"], "outcomeReason": ended["outcomeReason"],
        "automationId": trigger.get("automationId"), **run_outcomes.run_subject(trigger), **decision.run_fields(),
        "startedAt": started_at, "finishedAt": now(), "attempt": attempt,
        "resultSummary": summarize_output(output, outcome.get("seconds", 0)) if succeeded else None,
        "errorSummary": None if succeeded else ended["error"][:MAX_SUMMARY_CHARACTERS],
        "output": output if succeeded or gate is not None else None,   # a run the gate stopped keeps its answers
        "error": None if succeeded else {"message": ended["error"], "logTail": outcome.get("logTail")}, **kept_wake(request)}
    cost_recorded = usage is not None
    try:
        update_cloud_procedure_run_record(client, {**record, "usage": usage, "costUsd": cost_usd} if cost_recorded else record)
    except Exception:
        if not cost_recorded:
            raise
        # A site backend that predates the usage fields refuses them; the run's outcome must still be recorded.
        cost_recorded = False
        update_cloud_procedure_run_record(client, record)
    if answer is not None and succeeded:
        review_answers.record_used(client, answer, run_id, decision.responsibility)   # the request names the run that used its answer
    if handoff:
        agent_assignments.finish(client, handoff["assignment"], handoff["agent"], run_id=run_id, outcome=ended["outcome"], reason=ended["outcomeReason"],
                                 summary=record["resultSummary"], error=None if succeeded else ended["error"], now=record["finishedAt"])
    return {"runId": run_id, "procedureKey": request["procedureKey"], "wakeKey": request["wakeKey"], "versionId": procedure["version"]["id"],
            **decision.run_fields(), "responsibility": decision.responsibility, "spend": spend_of(request, decision, usage, cost_usd),
            "runStatus": ended["runStatus"], "outcome": ended["outcome"], "outcomeReason": ended["outcomeReason"],
            "seconds": outcome.get("seconds"),
            "error": None if succeeded else ended["error"], "costUsd": cost_usd, "costRecorded": cost_recorded and "calls" in (usage or {}),
            "output": output if succeeded or gate is not None else None}


def continue_or_fail(ended: dict, output: Any, request: dict, run_id: str, schedule_continuation: Callable[[dict, str, str], None] | None) -> dict:
    """A finished run that asked for a continuation has its timer set before its record is written. A run that asked for one it cannot have is `failed`."""
    if ended["outcome"] != "acted":
        return ended
    try:
        due_at = run_continuation.requested_time(output)
        if due_at is None:
            return ended
        following = run_continuation.next_request(request, run_id, due_at)
        if schedule_continuation is None:
            raise run_continuation.ContinuationError(run_continuation.NOT_SCHEDULED, "this runner has no timer service to continue the run with")
        try:
            schedule_continuation(following, due_at, run_id)
        except Exception as error:
            raise run_continuation.ContinuationError(run_continuation.NOT_SCHEDULED, f"the continuation could not be scheduled: {error}") from error
    except run_continuation.ContinuationError as refused:
        return run_outcomes.finished_outcome(False, None, str(refused)) | {"outcomeReason": refused.reason}
    return ended


def continuation_scheduler(request: dict, context: Any) -> Callable[[dict, str, str], None]:
    """The runner's way to set a continuation's timer, built when a run asks for one: the account and partition come from the function's own ARN."""
    from .follow_up_timers import FollowUpTimers

    def schedule(following: dict, due_at: str, run_id: str) -> None:
        arn_parts = context.invoked_function_arn.split(":")
        timers = FollowUpTimers.for_site(request["publicationId"], account=arn_parts[4], region=arn_parts[3], partition=arn_parts[1])
        timers.schedule_continuation(following, due_at=due_at, record_id=run_id)

    return schedule


def child_environment(request: dict, openai_api_key: str | None) -> dict:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PAPYRUS_GRAPHQL_")
                   and key != TENANT_ID_ENVIRONMENT_VARIABLE}
    environment.update(PAPYRUS_GRAPHQL_ENDPOINT=request["appsyncEndpoint"], PAPYRUS_GRAPHQL_AUTH="iam", HOME="/tmp",
                       PYTHONUNBUFFERED="1")
    if request.get("tenantId"):
        environment[TENANT_ID_ENVIRONMENT_VARIABLE] = request["tenantId"]
    if request.get("procedureKey"):
        environment[request_meter.ENV_CALLER] = f"stage:{request['procedureKey']}"   # the stage's own requests are attributed to it
    if openai_api_key:
        environment["OPENAI_API_KEY"] = openai_api_key
    # Where the site's own store is, for a procedure that reads a site document (the announce agent reads the lists' settings). Never inherited from the runner's own process.
    environment.pop("PAPYRUS_SITE_BUCKET", None)   # the tenant id above is the request's own or absent; the bucket only goes with a tenant
    if request.get("tenantId") and request.get("siteBucket"):
        environment["PAPYRUS_SITE_BUCKET"] = request["siteBucket"]
    # The site's public address, for a procedure that links to a Story (the announce agent's X post). Only a plain https origin is passed on.
    # The site's broadcast function, for a procedure that posts to X (the announce agent): named after the publication, which is the notifications plugin's site id.
    environment.pop("X_BROADCAST_FUNCTION", None)
    publication = str(request.get("publicationId") or "")
    if re.fullmatch(r"[a-z0-9-]{1,40}", publication):
        environment["X_BROADCAST_FUNCTION"] = f"papyrus-notifications-broadcast-{publication}"
    # The site whose follow-up timers a procedure sets (a Delivery's release and lock times, a soft review's deadline): the schedule group and wake queue are named from it.
    # The account and partition come from the runner's own environment (papyrus-procedure-runner.yaml).
    environment.pop("PAPYRUS_AGENT_PUBLICATION_ID", None)
    if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", publication):
        environment["PAPYRUS_AGENT_PUBLICATION_ID"] = publication
    environment.pop("SITE_ORIGIN", None)
    if is_plain_https_origin(request.get("siteOrigin")):
        environment["SITE_ORIGIN"] = request["siteOrigin"]
    return environment


def is_plain_https_origin(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"https://[A-Za-z0-9.-]+(:[0-9]+)?", value) is not None


def record_trigger_run(table, trigger: dict | None, run_id: str) -> None:
    """Names the run on its trigger row as soon as it exists, so a run in progress is linked to its automation."""
    if table is None or not trigger or not trigger.get("pk") or not trigger.get("sk"):
        return
    table.update_item(Key={"pk": trigger["pk"], "sk": trigger["sk"]},
                      UpdateExpression="SET #s = :s, runId = :r, runStartedAt = :t", ExpressionAttributeNames={"#s": "status"},
                      ExpressionAttributeValues={":s": "running", ":r": run_id, ":t": utc_now()})


def record_trigger_outcome(table, trigger: dict | None, result: dict) -> None:
    if table is None or not trigger or not trigger.get("pk") or not trigger.get("sk"):
        return
    table.update_item(Key={"pk": trigger["pk"], "sk": trigger["sk"]},
                      UpdateExpression="SET #s = :s, runId = :r, finishedAt = :f, runError = :e, outcome = :o, outcomeReason = :w",
                      ExpressionAttributeNames={"#s": "status"},
                      ExpressionAttributeValues={":s": result.get("runStatus") or "failed", ":r": result.get("runId"),
                                                 ":f": utc_now(), ":e": result.get("error"),
                                                 ":o": result["outcome"], ":w": result.get("outcomeReason")})


@request_meter.metered_handler("procedure-runner")
def handler(event, context):
    """Lambda entry point: the consumer of the site's wake queue (docs/procedure-runner.md), one message at a time. The message stays on the
    queue, hidden, for the whole run. Returning deletes it, and this returns only once the wake's run record exists and is finished, or is the
    record of an earlier delivery of the same wake. Raising leaves it: the queue delivers it once more, then moves it to the dead-letter queue."""
    import boto3  # provided by the Lambda image

    from .graphql_authoring import PapyrusGraphQLAuthoringClient

    request = agent_wakes.request_from_event(event)   # a message that is not a well-formed wake raises, and nothing is recorded
    table_name = os.environ.get("TRIGGER_TABLE_NAME")
    table = boto3.resource("dynamodb").Table(table_name) if table_name else None
    trigger = request.get("trigger") if isinstance(request.get("trigger"), dict) else None
    client = None   # a run that spent anything had a client; a wake refused before one existed has no spend to record
    try:
        request = validate_request(request)
        openai_api_key = None
        if request["openaiKeyParameter"]:
            openai_api_key = boto3.client("ssm").get_parameter(Name=request["openaiKeyParameter"],
                                                               WithDecryption=True)["Parameter"]["Value"]
        os.environ.update(PAPYRUS_GRAPHQL_ENDPOINT=request["appsyncEndpoint"], PAPYRUS_GRAPHQL_AUTH="iam")
        # A warm worker may have served a different publication. Scope parent reads
        # and post-run triggers too, and clear tenant context for dedicated sites.
        os.environ.pop(TENANT_ID_ENVIRONMENT_VARIABLE, None)
        if request.get("tenantId"):
            os.environ[TENANT_ID_ENVIRONMENT_VARIABLE] = request["tenantId"]
        client = PapyrusGraphQLAuthoringClient()
        policy = policy_for(request, client, lambda: boto3.client("s3"))
        seconds_available = context.get_remaining_time_in_millis() / 1000 if hasattr(context, "get_remaining_time_in_millis") else 840
        result = run_procedure_request(request, client=client, policy=policy, execute=execute_in_child,
                                       seconds_available=seconds_available,
                                       environment=child_environment(request, openai_api_key), workroot=Path("/tmp"),
                                       run_started=lambda run_id: record_trigger_run(table, trigger, run_id),
                                       receive_count=agent_wakes.receive_count(event),
                                       schedule_continuation=continuation_scheduler(request, context), spend_brake=SpendBrake(table),
                                       spend_stop=SpendStop(timers=runner_timers(context), send=agent_wakes.wake_sender()))
    except ProcedureNotRunnable as error:
        result = {"runStatus": "notRunnable", "runId": error.run_id, "outcome": "failed", "outcomeReason": run_outcomes.NOT_RUNNABLE,
                  "error": str(error)}
        if error.run_id is None:
            # No run record exists for this wake, so the message must not be deleted: the trigger row says why, and the error leaves the message on the queue.
            record_trigger_outcome(table, trigger, result)
            raise
    print(json.dumps(result, default=str))
    if result.get("duplicate"):
        return result   # the first delivery of this wake already recorded its trigger row and ran what follows a run
    record_trigger_outcome(table, trigger, result)
    record_spend(table, client, result)   # after the trigger row, so a ledger error never leaves a finished run's row looking unfinished
    if result.get("skipped") or result.get("settled") or result.get("waiting") or result.get("released"):
        return result   # the policy started nothing, or the run was settled unknown: no run happened: no story is advanced and no stage trigger fires for a run that did not happen
    if table is not None and isinstance(trigger, dict) and trigger.get("event") == "story.stage_entered":
        finish_story_stage_run(table, trigger, result)
    if table is not None:
        fire_story_triggers_after_run(table, trigger, result)
    return result


def fire_story_triggers_after_run(table, trigger: dict | None, result: dict) -> None:
    """A run completed and named a story (a tool may have created or moved it): deliver that story's stage triggers.
    Never raises: the run's outcome is already recorded."""
    try:
        from .automations import MonitoringReader, MonitoringWriter
        from .graphql_authoring import PapyrusGraphQLAuthoringClient
        from .story_triggers import deliver_after_run

        deliver_after_run(PapyrusGraphQLAuthoringClient(), trigger, result, reader=MonitoringReader(table),
                          writer=MonitoringWriter(table), invoke=agent_wakes.wake_sender())
    except Exception as error:
        print(f"story triggers could not be delivered after the run: {type(error).__name__}: {error}")


def finish_story_stage_run(table, trigger: dict, result: dict) -> None:
    """A story-stage run ended: the engine advances the story or raises a review request (story_triggers.finish_stage_run).
    Never raises: the run's outcome is already recorded."""
    try:
        from .automations import MonitoringReader, MonitoringWriter
        from .graphql_authoring import PapyrusGraphQLAuthoringClient
        from .story_triggers import finish_stage_run

        finish_stage_run(PapyrusGraphQLAuthoringClient(), trigger, result, reader=MonitoringReader(table), writer=MonitoringWriter(table),
                         invoke=agent_wakes.wake_sender())
    except Exception as error:
        print(f"story stage run could not be finished: {type(error).__name__}: {error}")
