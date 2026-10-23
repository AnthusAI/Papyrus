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

from .cloud_procedures import (
    START_PROCEDURE_RUN_MUTATION, current_cloud_procedure_version, get_cloud_procedure_definition_by_key,
    normalize_graphql_json_value, update_cloud_procedure_run_record)
from .model_cost import estimate_cost
from .site_procedures import SKILL_SORT_KEY_PREFIX

SECONDS_KEPT_FOR_RECORDING = 60
MAX_TIMEOUT_SECONDS = 840          # the Lambda's 15 minutes less the recording margin; an automation's limit is capped here
MAX_RECORDED_CALLS = 200
MAX_SUMMARY_CHARACTERS = 500
OUTPUT_SUMMARY_FIELDS = ("title", "summary", "next_step", "story")
APPSYNC_ENDPOINT = re.compile(r"^https://[a-z0-9]+\.appsync-api\.[a-z0-9-]+\.amazonaws\.com/graphql$")
SSM_PARAMETER = re.compile(r"^/[A-Za-z0-9_./-]{1,1000}$")


class ProcedureNotRunnable(Exception):
    pass


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
    if not isinstance(request.get("input") or {}, dict):
        raise ProcedureNotRunnable("input must be an object")
    timeout = request.get("timeoutSeconds")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1):
        raise ProcedureNotRunnable("timeoutSeconds must be a positive whole number")
    return {"appsyncEndpoint": endpoint, "procedureKey": key, "openaiKeyParameter": parameter or None,
            "timeoutSeconds": None if timeout is None else min(timeout, MAX_TIMEOUT_SECONDS),
            "input": dict(request.get("input") or {}), "publicationId": str(request.get("publicationId") or ""),
            "actorLabel": str(request.get("actorLabel") or "Papyrus procedure runner"),
            "trigger": request.get("trigger") if isinstance(request.get("trigger"), dict) else None}


def load_published_procedure(client, procedure_key: str) -> dict[str, Any]:
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


def start_run_record(client, request: dict, version: dict) -> str:
    trigger = request.get("trigger") or {}
    data = client.graphql(START_PROCEDURE_RUN_MUTATION, {
        "procedureKey": request["procedureKey"], "procedureVersionId": version["id"],
        "title": trigger.get("title") or request["procedureKey"],
        "summary": trigger.get("summary") or "Started by the Papyrus procedure runner",
        "actorLabel": request["actorLabel"],
        "input": json.dumps({**request["input"], "__papyrusExecutionMode": "external_cli"})})
    started = normalize_graphql_json_value(data.get("startNewsroomProcedureRun")) or {}
    if not started.get("runId"):
        raise ProcedureNotRunnable("the newsroom did not return a run id")
    return started["runId"]


def child_timeout(request: dict, seconds_available: float) -> float:
    """The child's deadline: what the Lambda has left less the recording margin, or the request's own limit if shorter."""
    room = seconds_available - SECONDS_KEPT_FOR_RECORDING
    return min(room, request["timeoutSeconds"]) if request.get("timeoutSeconds") else room


def usage_record(outcome: dict) -> tuple[dict | None, float | None]:
    """The usage to store on the ProcedureRun (calls plus the estimate) and the estimated cost, or (None, None)
    when the procedure made no model call."""
    calls = [call for call in (outcome.get("usage") or []) if isinstance(call, dict)]
    if not calls:
        return None, None
    estimate = estimate_cost(calls)
    summary = {key: estimate[key] for key in ("complete", "unpricedModels", "calls", "promptTokens", "completionTokens", "models")}
    return {**summary, "perCall": calls[:MAX_RECORDED_CALLS]}, estimate["costUsd"]


def run_procedure_request(request: dict, *, client, execute: Callable[..., dict], seconds_available: float,
                          environment: dict, now: Callable[[], str] = utc_now, workroot: Path | None = None,
                          run_started: Callable[[str], None] | None = None) -> dict:
    request = validate_request(request)
    procedure = load_published_procedure(client, request["procedureKey"])
    run_id = start_run_record(client, request, procedure["version"])
    started_at = now()
    if run_started is not None:
        try:
            run_started(run_id)   # lets the trigger row name its run while it is still running
        except Exception:
            pass
    workdir = Path(tempfile.mkdtemp(prefix="papyrus-procedure-", dir=workroot))
    try:
        source_path = materialize(workdir, procedure["source"], procedure["skills"])
        outcome = execute(workdir, source_path, request["input"],
                          timeout_seconds=child_timeout(request, seconds_available), environment=environment)
    except Exception as error:
        outcome = {"success": False, "error": f"{type(error).__name__}: {error}", "seconds": 0}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    succeeded = bool(outcome.get("success"))
    usage, cost_usd = usage_record(outcome)
    record = {
        "id": run_id, "runStatus": "completed" if succeeded else "failed", "startedAt": started_at,
        "finishedAt": now(), "attempt": 1,
        "resultSummary": summarize_output(outcome.get("output"), outcome.get("seconds", 0)) if succeeded else None,
        "errorSummary": None if succeeded else str(outcome.get("error") or "failed")[:MAX_SUMMARY_CHARACTERS],
        "output": outcome.get("output") if succeeded else None,
        "error": None if succeeded else {"message": outcome.get("error"), "logTail": outcome.get("logTail")}}
    cost_recorded = usage is not None
    try:
        update_cloud_procedure_run_record(client, {**record, "usage": usage, "costUsd": cost_usd} if cost_recorded else record)
    except Exception:
        if not cost_recorded:
            raise
        # A site backend that predates the usage fields refuses them; the run's outcome must still be recorded.
        cost_recorded = False
        update_cloud_procedure_run_record(client, record)
    return {"runId": run_id, "procedureKey": request["procedureKey"], "versionId": procedure["version"]["id"],
            "runStatus": "completed" if succeeded else "failed", "seconds": outcome.get("seconds"),
            "error": None if succeeded else outcome.get("error"), "costUsd": cost_usd, "costRecorded": cost_recorded}


def child_environment(request: dict, openai_api_key: str | None) -> dict:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PAPYRUS_GRAPHQL_")}
    environment.update(PAPYRUS_GRAPHQL_ENDPOINT=request["appsyncEndpoint"], PAPYRUS_GRAPHQL_AUTH="iam", HOME="/tmp",
                       PYTHONUNBUFFERED="1")
    if openai_api_key:
        environment["OPENAI_API_KEY"] = openai_api_key
    return environment


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
                      UpdateExpression="SET #s = :s, runId = :r, finishedAt = :f, runError = :e",
                      ExpressionAttributeNames={"#s": "status"},
                      ExpressionAttributeValues={":s": result.get("runStatus") or "failed", ":r": result.get("runId"),
                                                 ":f": utc_now(), ":e": result.get("error")})


def handler(event, context):
    """Lambda entry point, invoked asynchronously (by the monitoring router) with one request."""
    import boto3  # provided by the Lambda image

    from .graphql_authoring import PapyrusGraphQLAuthoringClient

    table_name = os.environ.get("TRIGGER_TABLE_NAME")
    table = boto3.resource("dynamodb").Table(table_name) if table_name else None
    trigger = (event or {}).get("trigger") if isinstance(event, dict) else None
    try:
        request = validate_request(event if isinstance(event, dict) else {})
        openai_api_key = None
        if request["openaiKeyParameter"]:
            openai_api_key = boto3.client("ssm").get_parameter(Name=request["openaiKeyParameter"],
                                                               WithDecryption=True)["Parameter"]["Value"]
        os.environ.update(PAPYRUS_GRAPHQL_ENDPOINT=request["appsyncEndpoint"], PAPYRUS_GRAPHQL_AUTH="iam")
        client = PapyrusGraphQLAuthoringClient()
        seconds_available = context.get_remaining_time_in_millis() / 1000 if hasattr(context, "get_remaining_time_in_millis") else 840
        result = run_procedure_request(request, client=client, execute=execute_in_child,
                                       seconds_available=seconds_available,
                                       environment=child_environment(request, openai_api_key), workroot=Path("/tmp"),
                                       run_started=lambda run_id: record_trigger_run(table, trigger, run_id))
    except ProcedureNotRunnable as error:
        result = {"runStatus": "notRunnable", "runId": None, "error": str(error)}
    print(json.dumps(result, default=str))
    record_trigger_outcome(table, trigger, result)
    return result
