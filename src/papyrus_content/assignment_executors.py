from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .accession import execute_reference_accession_assignment
from .assignments import assignment_metadata
from .corpora import maybe_sync_corpus_from_cloud_before_analysis
from .biblicus_runner import BiblicusRunner
from .env import PAPYRUS_ROOT
from .options import normalize_string
from .steering import require_steering_config
from .graphql_authoring import PapyrusGraphQLAuthoringClient
from .ids import hash_short
from .model_attachments import build_json_model_payload_attachment, upload_attachment_body
from .newsroom_summary import read_json_model_payload
from .reference_assignments import execute_reference_text_extraction_assignment
from .relation_types import semantic_relation_type_fields_for_predicate
from papyrus_newsroom.reference_curation_signals import reference_title_subtitle_resolve
from .model_defaults import DEFAULT_LLM_MODEL, DEFAULT_SMALL_LLM_MODEL


def execute_assignment_by_type(
    client: PapyrusGraphQLAuthoringClient,
    assignment_id: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assignment = client.get_record("Assignment", assignment_id)
    if not assignment:
        raise ValueError(f"Assignment {assignment_id} was not found.")
    assignment_type = assignment.get("assignmentTypeKey")
    merged_options = dict(options or {})
    if assignment_type == "analysis.reindex":
        return execute_analysis_reindex_assignment(client, assignment, merged_options)
    if assignment_type == "reference.corpus-accession":
        return execute_reference_accession_assignment(client, assignment, merged_options)
    if assignment_type == "reference.text-extraction":
        return execute_reference_text_extraction_assignment(client, assignment, merged_options)
    if assignment_type in {"reference.identifier-backfill", "reference.doi-backfill"}:
        return execute_reference_identifier_backfill_assignment(client, assignment, merged_options)
    if assignment_type == "curation.reference-refresh":
        return execute_reference_curation_refresh_assignment(client, assignment, merged_options)
    raise ValueError(f"No executor is registered for assignment type {assignment_type}.")


def execute_analysis_reindex_assignment(
    client: PapyrusGraphQLAuthoringClient,
    assignment: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    metadata = assignment_metadata(client, assignment)
    corpus_key = normalize_string(metadata.get("corpusKey"))
    if corpus_key:
        steering_config = require_steering_config(
            normalize_string(options.get("config")) or normalize_string(metadata.get("steeringConfigPath"))
        )
        maybe_sync_corpus_from_cloud_before_analysis(
            steering_config=steering_config,
            corpus_key=corpus_key,
            options=options,
            log_prefix="analysis-execute",
        )
    command_plan = metadata.get("commandPlan") if isinstance(metadata.get("commandPlan"), list) else []
    if not command_plan and isinstance(options.get("__commandPlan"), list):
        command_plan = options.get("__commandPlan") or []
    if assignment.get("status") != "claimed":
        raise ValueError(
            f"Assignment {assignment['id']} must be claimed before execution (current={assignment.get('status')})."
        )
    run_id = str(options.get("run-id") or metadata.get("planRunId") or f"analysis-reindex-{assignment['id']}")
    run_dir = PAPYRUS_ROOT / ".papyrus-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    max_runtime_seconds = _analysis_max_runtime_seconds(metadata, options)
    command_results: list[dict[str, Any]] = []
    run_started = time.monotonic()
    total_commands = sum(1 for command in command_plan if command.get("arguments"))
    for index, command in enumerate(command_plan, start=1):
        biblicus_arguments = [str(part) for part in command.get("arguments") or []]
        if not biblicus_arguments:
            continue
        cwd_value = command.get("cwd")
        runner = BiblicusRunner.from_environment(workdir=cwd_value if isinstance(cwd_value, str) and cwd_value else None)
        argv = runner.command(biblicus_arguments)
        cwd = runner.workdir
        label = str(command.get("label") or f"command-{index:02d}")
        stdout_log = run_dir / f"{label}.stdout.log"
        stderr_log = run_dir / f"{label}.stderr.log"
        elapsed_before = time.monotonic() - run_started
        timeout_seconds = _analysis_command_timeout_seconds(max_runtime_seconds, elapsed_before)
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise RuntimeError(
                "Analysis reindex runtime budget exhausted before command start. "
                f"assignment={assignment['id']} run_id={run_id} command={label}. "
                f"Next: poetry run papyrus analysis execute-assignment --assignment {assignment['id']} --run-id {run_id}"
            )
        print(
            "analysis-reindex\tphase\tcommand\tstart\t"
            f"assignment={assignment['id']}\trun={run_id}\tindex={index}\ttotal={total_commands}"
            f"\tlabel={label}\telapsedMs={int(elapsed_before * 1000)}\ttimeoutSeconds={timeout_seconds or '-'}",
            flush=True,
        )
        completed = _execute_streamed_command(
            argv=argv,
            cwd=cwd,
            environment=runner.environment,
            timeout_seconds=timeout_seconds,
            label=label,
        )
        if completed["timedOut"]:
            stdout_log.write_text(completed["stdout"], encoding="utf-8")
            stderr_log.write_text(completed["stderr"], encoding="utf-8")
            elapsed_after = time.monotonic() - run_started
            print(
                "analysis-reindex\tphase\tcommand\tfailed\t"
                f"assignment={assignment['id']}\trun={run_id}\tindex={index}\ttotal={total_commands}"
                f"\tlabel={label}\treason=timeout\ttimeoutSeconds={timeout_seconds or '-'}"
                f"\telapsedMs={int(elapsed_after * 1000)}",
                flush=True,
            )
            _write_analysis_execution_manifest(
                run_dir=run_dir,
                run_id=run_id,
                assignment=assignment,
                command_results=command_results,
                failed_command={
                    "label": label,
                    "argv": argv,
                    "cwd": str(cwd),
                    "exitStatus": None,
                    "stdoutLogPath": str(stdout_log),
                    "stderrLogPath": str(stderr_log),
                    "timeoutSeconds": timeout_seconds,
                    "failureReason": "timeout",
                },
                status="failed",
            )
            raise RuntimeError(
                "Analysis reindex command timed out. "
                f"assignment={assignment['id']} run_id={run_id} command={label} timeoutSeconds={timeout_seconds or '-'} "
                f"stdoutLog={stdout_log} stderrLog={stderr_log}. "
                f"Next: poetry run papyrus analysis execute-assignment --assignment {assignment['id']} --run-id {run_id}"
            )
        stdout_log.write_text(completed["stdout"], encoding="utf-8")
        stderr_log.write_text(completed["stderr"], encoding="utf-8")
        elapsed_after = time.monotonic() - run_started
        command_result = {
            "label": label,
            "argv": argv,
            "cwd": str(cwd),
            "exitStatus": int(completed["returncode"] or 0),
            "stdoutLogPath": str(stdout_log),
            "stderrLogPath": str(stderr_log),
            "timeoutSeconds": timeout_seconds,
            "elapsedMs": int(elapsed_after * 1000),
        }
        command_results.append(command_result)
        print(
            "analysis-reindex\tphase\tcommand\tcomplete\t"
            f"assignment={assignment['id']}\trun={run_id}\tindex={index}\ttotal={total_commands}"
            f"\tlabel={label}\texit={command_result['exitStatus']}\telapsedMs={command_result['elapsedMs']}",
            flush=True,
        )
        if completed["returncode"] != 0:
            _write_analysis_execution_manifest(
                run_dir=run_dir,
                run_id=run_id,
                assignment=assignment,
                command_results=command_results,
                failed_command=command_result,
                status="failed",
            )
            print(
                "analysis-reindex\tphase\tcommand\tfailed\t"
                f"assignment={assignment['id']}\trun={run_id}\tindex={index}\ttotal={total_commands}"
                f"\tlabel={label}\treason=exit-nonzero\texit={command_result['exitStatus']}",
                flush=True,
            )
            raise RuntimeError(
                "Analysis reindex command failed. "
                f"assignment={assignment['id']} run_id={run_id} command={label} exit={command_result['exitStatus']} "
                f"stdoutLog={stdout_log} stderrLog={stderr_log}. "
                f"Next: poetry run papyrus analysis execute-assignment --assignment {assignment['id']} --run-id {run_id}"
            )
    manifest_path = run_dir / "execution-manifest.json"
    manifest = {
        "runId": run_id,
        "assignmentId": assignment["id"],
        "assignmentTypeKey": assignment["assignmentTypeKey"],
        "status": "executed",
        "commandResults": command_results,
        "maxRuntimeSeconds": max_runtime_seconds,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "assignmentId": assignment["id"],
        "runId": run_id,
        "runDir": str(run_dir),
        "manifestPath": str(manifest_path),
        "commandResults": command_results,
    }


def _analysis_max_runtime_seconds(metadata: dict[str, Any], options: dict[str, Any]) -> int | None:
    override = options.get("max-runtime-seconds")
    if override not in {None, ""}:
        value = int(str(override))
        if value <= 0:
            raise ValueError("--max-runtime-seconds must be a positive integer.")
        return value
    execution = metadata.get("execution") if isinstance(metadata.get("execution"), dict) else {}
    raw = execution.get("maxRuntimeSeconds")
    if raw in {None, ""}:
        return None
    value = int(str(raw))
    return value if value > 0 else None


def _analysis_command_timeout_seconds(max_runtime_seconds: int | None, elapsed_seconds: float) -> int | None:
    if max_runtime_seconds is None:
        return None
    remaining = max_runtime_seconds - int(elapsed_seconds)
    return remaining if remaining > 0 else 0


def _execute_streamed_command(
    *,
    argv: list[str],
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int | None,
    label: str,
) -> dict[str, Any]:
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _pump(stream, sink: list[str], stream_name: str) -> None:
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            sink.append(line)
            rendered = line.rstrip("\n")
            if rendered:
                print(
                    "analysis-reindex\tphase\tcommand-output\t"
                    f"{stream_name}\tlabel={label}\t{rendered}",
                    flush=True,
                )
        stream.close()

    stdout_thread = threading.Thread(target=_pump, args=(process.stdout, stdout_lines, "stdout"), daemon=True)
    stderr_thread = threading.Thread(target=_pump, args=(process.stderr, stderr_lines, "stderr"), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    started = time.monotonic()
    timed_out = False
    while True:
        return_code = process.poll()
        if return_code is not None:
            break
        if timeout_seconds is not None and (time.monotonic() - started) >= timeout_seconds:
            timed_out = True
            process.kill()
            break
        time.sleep(0.1)
    return_code = process.wait()
    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)
    return {
        "returncode": return_code,
        "stdout": "".join(stdout_lines),
        "stderr": "".join(stderr_lines),
        "timedOut": timed_out,
    }


def _write_analysis_execution_manifest(
    *,
    run_dir: Path,
    run_id: str,
    assignment: dict[str, Any],
    command_results: list[dict[str, Any]],
    failed_command: dict[str, Any],
    status: str,
) -> None:
    manifest_path = run_dir / "execution-manifest.json"
    manifest = {
        "runId": run_id,
        "assignmentId": assignment["id"],
        "assignmentTypeKey": assignment["assignmentTypeKey"],
        "status": status,
        "failedCommand": failed_command,
        "commandResults": command_results,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def execute_reference_identifier_backfill_assignment(
    client: PapyrusGraphQLAuthoringClient,
    assignment: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    metadata = assignment_metadata(client, assignment)
    if assignment.get("status") != "claimed":
        raise ValueError(
            f"Assignment {assignment['id']} must be claimed before execution (current={assignment.get('status')})."
        )
    corpus_key = str(metadata.get("corpusKey") or "").strip()
    if not corpus_key:
        raise ValueError(f"Assignment {assignment['id']} metadata is missing corpusKey.")
    run_id = str(options.get("run-id") or metadata.get("runId") or f"reference-identifier-backfill-{assignment['id']}")
    run_dir = PAPYRUS_ROOT / ".papyrus-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    max_count = int(options.get("max-count") or metadata.get("maxCount") or 200)
    scan_limit = int(options.get("scan-limit") or max(max_count * 4, 2000))
    model = str(options.get("llm-model") or metadata.get("llmModel") or DEFAULT_LLM_MODEL)
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    args = [
        "poetry",
        "run",
        "papyrus",
        "references",
        "curate-recent",
        "--corpus-key",
        corpus_key,
        "--all",
        "--max-count",
        str(max_count),
        "--scan-limit",
        str(scan_limit),
        "--model",
        model,
        "--json",
    ]
    completed = subprocess.run(args, cwd=PAPYRUS_ROOT, capture_output=True, text=True, check=False)
    stdout_log = run_dir / "identifier-backfill.stdout.log"
    stderr_log = run_dir / "identifier-backfill.stderr.log"
    stdout_log.write_text(completed.stdout or "", encoding="utf-8")
    stderr_log.write_text(completed.stderr or "", encoding="utf-8")
    payload = _extract_last_json(completed.stdout or "")
    summary = payload.get("summary") if isinstance(payload, dict) else {}
    manifest_path = run_dir / "execution-manifest.json"
    manifest = {
        "runId": run_id,
        "assignmentId": assignment["id"],
        "assignmentTypeKey": assignment["assignmentTypeKey"],
        "status": "executed" if completed.returncode == 0 else "failed",
        "startedAt": started_at,
        "completedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stdoutLogPath": str(stdout_log),
        "stderrLogPath": str(stderr_log),
        "summary": summary,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"Identifier backfill execution failed for assignment {assignment['id']}.")
    return {
        "assignmentId": assignment["id"],
        "runId": run_id,
        "runDir": str(run_dir),
        "manifestPath": str(manifest_path),
        "summary": summary,
    }


REFERENCE_CURATION_DEFAULT_POLICY: dict[str, bool] = {
    "recomputeIdentifier": True,
    "recomputePublicationDate": True,
    "recomputeTitle": True,
    "recomputeSubtitle": True,
    "recomputeSummary": True,
    "recomputeTopicPredictions": True,
    "recomputeQuality": False,
    "recomputeCorpus": False,
}
REFERENCE_CURATION_STAGE_KEYS = (
    "identifier",
    "publicationDate",
    "titleSubtitle",
    "summary",
    "topicPredictions",
)


def execute_reference_curation_refresh_assignment(
    client: PapyrusGraphQLAuthoringClient,
    assignment: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    if assignment.get("status") != "claimed":
        raise ValueError(
            f"Assignment {assignment['id']} must be claimed before execution (current={assignment.get('status')})."
        )
    now = _now_iso()
    status_payload = read_json_model_payload(
        client,
        "assignment",
        str(assignment["id"]),
        "metadata",
        "reference_curation_status",
    ) or {}
    metadata = assignment_metadata(client, assignment)
    run_id = str(
        options.get("run-id")
        or status_payload.get("runId")
        or metadata.get("runId")
        or f"reference-curation-refresh-{assignment['id']}"
    )
    run_dir = PAPYRUS_ROOT / ".papyrus-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    policy = _normalize_reference_curation_policy(status_payload.get("curationPolicy") or metadata.get("curationPolicy"))
    reference_id = (
        _clean_string(status_payload.get("referenceId"))
        or _clean_string(metadata.get("referenceId"))
        or _reference_id_from_assignment_queue(assignment)
    )
    if not reference_id:
        raise ValueError(f"Assignment {assignment['id']} does not include referenceId in curation metadata.")
    reference = client.get_record("Reference", reference_id)
    if not reference:
        raise ValueError(f"Reference {reference_id} was not found for assignment {assignment['id']}.")
    reference_lineage_id = str(reference.get("lineageId") or reference["id"])
    stage_statuses = _default_reference_curation_stage_statuses(status="queued")
    changed_outputs: dict[str, Any] = {}
    errors: list[dict[str, Any]] = []
    lifecycle_status = "running"
    _write_reference_curation_status(
        client,
        assignment=assignment,
        payload={
            **status_payload,
            "kind": "reference.curation.status",
            "runId": run_id,
            "assignmentId": assignment["id"],
            "referenceId": reference["id"],
            "referenceLineageId": reference_lineage_id,
            "corpusId": reference.get("corpusId"),
            "curationPolicy": policy,
            "lifecycleStatus": lifecycle_status,
            "status": lifecycle_status,
            "stageStatuses": stage_statuses,
            "changedOutputs": changed_outputs,
            "error": None,
        },
    )

    reference_metadata = read_json_model_payload(
        client,
        "reference",
        str(reference["id"]),
        "metadata",
        "metadata",
    ) or {}

    if policy.get("recomputeIdentifier"):
        try:
            identifier_result = _refresh_reference_identifiers(
                client,
                reference=reference,
                metadata=reference_metadata,
            )
            reference_metadata = identifier_result.get("metadata") or reference_metadata
            stage_statuses["identifier"] = {
                "status": "completed",
                "updatedAt": _now_iso(),
                "detail": {
                    "updated": bool(identifier_result.get("updated")),
                    "identifiers": identifier_result.get("identifiers") or {},
                },
            }
            changed_outputs["identifier"] = {
                "updated": bool(identifier_result.get("updated")),
                "identifiers": identifier_result.get("identifiers") or {},
            }
        except Exception as error:  # pragma: no cover - live assignment path
            stage_statuses["identifier"] = {
                "status": "failed",
                "updatedAt": _now_iso(),
                "detail": {"error": str(error)},
            }
            errors.append({"stage": "identifier", "message": str(error)})
    else:
        stage_statuses["identifier"] = {
            "status": "skipped",
            "updatedAt": _now_iso(),
            "detail": {"reason": "recomputeIdentifier=false"},
        }

    _write_reference_curation_status(
        client,
        assignment=assignment,
        payload={
            **status_payload,
            "kind": "reference.curation.status",
            "runId": run_id,
            "assignmentId": assignment["id"],
            "referenceId": reference["id"],
            "referenceLineageId": reference_lineage_id,
            "corpusId": reference.get("corpusId"),
            "curationPolicy": policy,
            "lifecycleStatus": lifecycle_status,
            "status": lifecycle_status,
            "stageStatuses": stage_statuses,
            "changedOutputs": changed_outputs,
            "error": errors[-1] if errors else None,
        },
    )

    if policy.get("recomputePublicationDate"):
        try:
            publication_result = _refresh_reference_publication_dates(
                client,
                reference=reference,
                metadata=reference_metadata,
            )
            reference = publication_result.get("reference") or reference
            stage_statuses["publicationDate"] = {
                "status": "completed",
                "updatedAt": _now_iso(),
                "detail": publication_result.get("detail") or {},
            }
            changed_outputs["publicationDate"] = publication_result.get("detail") or {}
        except Exception as error:  # pragma: no cover - live assignment path
            stage_statuses["publicationDate"] = {
                "status": "failed",
                "updatedAt": _now_iso(),
                "detail": {"error": str(error)},
            }
            errors.append({"stage": "publicationDate", "message": str(error)})
    else:
        stage_statuses["publicationDate"] = {
            "status": "skipped",
            "updatedAt": _now_iso(),
            "detail": {"reason": "recomputePublicationDate=false"},
        }

    _write_reference_curation_status(
        client,
        assignment=assignment,
        payload={
            **status_payload,
            "kind": "reference.curation.status",
            "runId": run_id,
            "assignmentId": assignment["id"],
            "referenceId": reference["id"],
            "referenceLineageId": reference_lineage_id,
            "corpusId": reference.get("corpusId"),
            "curationPolicy": policy,
            "lifecycleStatus": lifecycle_status,
            "status": lifecycle_status,
            "stageStatuses": stage_statuses,
            "changedOutputs": changed_outputs,
            "error": errors[-1] if errors else None,
        },
    )

    title_stage_requested = policy.get("recomputeTitle") or policy.get("recomputeSubtitle")
    summary_stage_requested = policy.get("recomputeSummary")
    if title_stage_requested or summary_stage_requested:
        try:
            title_result = reference_title_subtitle_resolve(
                reference_id=str(reference["id"]),
                model=str(options.get("model") or DEFAULT_SMALL_LLM_MODEL),
                apply=True,
                refresh=True,
                summary=bool(summary_stage_requested),
                summary_max_tokens=int(options.get("summary-max-tokens") or 500),
                refresh_summary=True,
                web_search=True,
                persist_local_metadata=False,
                vector_sync=True,
                source_text="",
                source_text_file="",
            )
            reference = client.get_record("Reference", str(reference["id"])) or reference
            reference_metadata = read_json_model_payload(
                client,
                "reference",
                str(reference["id"]),
                "metadata",
                "metadata",
            ) or reference_metadata
            if title_stage_requested:
                stage_statuses["titleSubtitle"] = {
                    "status": "completed",
                    "updatedAt": _now_iso(),
                    "detail": {
                        "action": title_result.get("action"),
                        "title": (title_result.get("resolution") or {}).get("title") or title_result.get("title"),
                        "subtitle": (title_result.get("resolution") or {}).get("subtitle") or title_result.get("subtitle"),
                    },
                }
                changed_outputs["titleSubtitle"] = stage_statuses["titleSubtitle"]["detail"]
            else:
                stage_statuses["titleSubtitle"] = {
                    "status": "skipped",
                    "updatedAt": _now_iso(),
                    "detail": {"reason": "recomputeTitle=false and recomputeSubtitle=false"},
                }
            if summary_stage_requested:
                summary_detail = {
                    "action": title_result.get("action"),
                    "summary": (title_result.get("resolution") or {}).get("summary") or title_result.get("summary") or "",
                }
                stage_statuses["summary"] = {
                    "status": "completed",
                    "updatedAt": _now_iso(),
                    "detail": summary_detail,
                }
                changed_outputs["summary"] = summary_detail
            else:
                stage_statuses["summary"] = {
                    "status": "skipped",
                    "updatedAt": _now_iso(),
                    "detail": {"reason": "recomputeSummary=false"},
                }
        except Exception as error:  # pragma: no cover - live assignment path
            if title_stage_requested:
                stage_statuses["titleSubtitle"] = {
                    "status": "failed",
                    "updatedAt": _now_iso(),
                    "detail": {"error": str(error)},
                }
                errors.append({"stage": "titleSubtitle", "message": str(error)})
            else:
                stage_statuses["titleSubtitle"] = {
                    "status": "skipped",
                    "updatedAt": _now_iso(),
                    "detail": {"reason": "recomputeTitle=false and recomputeSubtitle=false"},
                }
            if summary_stage_requested:
                stage_statuses["summary"] = {
                    "status": "failed",
                    "updatedAt": _now_iso(),
                    "detail": {"error": str(error)},
                }
                errors.append({"stage": "summary", "message": str(error)})
            else:
                stage_statuses["summary"] = {
                    "status": "skipped",
                    "updatedAt": _now_iso(),
                    "detail": {"reason": "recomputeSummary=false"},
                }
    else:
        stage_statuses["titleSubtitle"] = {
            "status": "skipped",
            "updatedAt": _now_iso(),
            "detail": {"reason": "recomputeTitle=false and recomputeSubtitle=false"},
        }
        stage_statuses["summary"] = {
            "status": "skipped",
            "updatedAt": _now_iso(),
            "detail": {"reason": "recomputeSummary=false"},
        }

    _write_reference_curation_status(
        client,
        assignment=assignment,
        payload={
            **status_payload,
            "kind": "reference.curation.status",
            "runId": run_id,
            "assignmentId": assignment["id"],
            "referenceId": reference["id"],
            "referenceLineageId": reference_lineage_id,
            "corpusId": reference.get("corpusId"),
            "curationPolicy": policy,
            "lifecycleStatus": lifecycle_status,
            "status": lifecycle_status,
            "stageStatuses": stage_statuses,
            "changedOutputs": changed_outputs,
            "error": errors[-1] if errors else None,
        },
    )

    if policy.get("recomputeTopicPredictions"):
        try:
            topic_result = _refresh_reference_topic_predictions(
                client,
                reference=reference,
                metadata=reference_metadata,
                run_id=run_id,
            )
            stage_statuses["topicPredictions"] = {
                "status": "completed",
                "updatedAt": _now_iso(),
                "detail": topic_result,
            }
            changed_outputs["topicPredictions"] = topic_result
        except Exception as error:  # pragma: no cover - live assignment path
            stage_statuses["topicPredictions"] = {
                "status": "failed",
                "updatedAt": _now_iso(),
                "detail": {"error": str(error)},
            }
            errors.append({"stage": "topicPredictions", "message": str(error)})
    else:
        stage_statuses["topicPredictions"] = {
            "status": "skipped",
            "updatedAt": _now_iso(),
            "detail": {"reason": "recomputeTopicPredictions=false"},
        }

    if errors:
        failed_stages = {entry["stage"] for entry in errors}
        complete_stages = {
            key
            for key, value in stage_statuses.items()
            if str((value or {}).get("status") or "").strip().lower() == "completed"
        }
        lifecycle_status = "failed" if failed_stages and not complete_stages else "degraded"
    else:
        lifecycle_status = "completed"
    final_payload = {
        **status_payload,
        "kind": "reference.curation.status",
        "runId": run_id,
        "assignmentId": assignment["id"],
        "referenceId": reference["id"],
        "referenceLineageId": reference_lineage_id,
        "corpusId": reference.get("corpusId"),
        "curationPolicy": policy,
        "lifecycleStatus": lifecycle_status,
        "status": lifecycle_status,
        "stageStatuses": stage_statuses,
        "changedOutputs": changed_outputs,
        "error": {"code": "curation_refresh_degraded", "message": "; ".join(entry["message"] for entry in errors)}
        if errors
        else None,
    }
    _write_reference_curation_status(client, assignment=assignment, payload=final_payload)
    manifest_path = run_dir / "execution-manifest.json"
    manifest = {
        "runId": run_id,
        "assignmentId": assignment["id"],
        "assignmentTypeKey": assignment["assignmentTypeKey"],
        "status": lifecycle_status,
        "referenceId": reference.get("id"),
        "referenceLineageId": reference_lineage_id,
        "stageStatuses": stage_statuses,
        "changedOutputs": changed_outputs,
        "error": final_payload.get("error"),
        "completedAt": _now_iso(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "assignmentId": assignment["id"],
        "runId": run_id,
        "runDir": str(run_dir),
        "manifestPath": str(manifest_path),
        "status": lifecycle_status,
        "stageStatuses": stage_statuses,
        "changedOutputs": changed_outputs,
        "error": final_payload.get("error"),
    }


def _write_reference_curation_status(
    client: PapyrusGraphQLAuthoringClient,
    *,
    assignment: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    now = _now_iso()
    attachment = build_json_model_payload_attachment(
        {
            "ownerKind": "assignment",
            "ownerId": assignment["id"],
            "ownerLineageId": assignment["id"],
            "role": "metadata",
            "sortKey": "reference_curation_status",
            "filename": "reference-curation-status.json",
            "content": {**payload, "updatedAt": now},
            "importRunId": assignment.get("importRunId"),
            "status": "active",
            "now": now,
        }
    )
    upload_attachment_body(client, attachment["attachment"], attachment["body"])
    client.upsert("ModelAttachment", attachment["attachment"])


def _normalize_reference_curation_policy(value: Any) -> dict[str, bool]:
    policy = dict(REFERENCE_CURATION_DEFAULT_POLICY)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = None
    if not isinstance(value, dict):
        return policy
    for key in REFERENCE_CURATION_DEFAULT_POLICY:
        candidate = value.get(key)
        if isinstance(candidate, bool):
            policy[key] = candidate
    return policy


def _default_reference_curation_stage_statuses(*, status: str) -> dict[str, dict[str, Any]]:
    return {
        key: {
            "status": status,
            "updatedAt": _now_iso(),
            "detail": {},
        }
        for key in REFERENCE_CURATION_STAGE_KEYS
    }


def _reference_id_from_assignment_queue(assignment: dict[str, Any]) -> str | None:
    queue_key = _clean_string(assignment.get("queueKey")) or ""
    prefix = "curation:reference-refresh:"
    if not queue_key.startswith(prefix):
        return None
    return queue_key[len(prefix) :] or None


def _refresh_reference_identifiers(
    client: PapyrusGraphQLAuthoringClient,
    *,
    reference: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    source_uri = _clean_string(reference.get("sourceUri")) or ""
    existing = metadata.get("identifiers") if isinstance(metadata.get("identifiers"), dict) else {}
    identifiers: dict[str, str] = {}
    for key, value in existing.items():
        cleaned = _clean_string(value)
        if cleaned:
            identifiers[str(key)] = cleaned
    doi_match = re.search(r"(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", source_uri)
    if doi_match:
        identifiers["doi"] = doi_match.group(1).rstrip(").,;")
    arxiv_match = re.search(r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:)(\d{4}\.\d{4,5}(?:v\d+)?)", source_uri, flags=re.IGNORECASE)
    if arxiv_match:
        identifiers["arxiv_id"] = arxiv_match.group(1)
    updated = identifiers != existing
    if updated:
        next_metadata = {**metadata, "identifiers": identifiers}
        _upsert_reference_metadata_payload(client, reference=reference, metadata=next_metadata)
        return {"updated": True, "identifiers": identifiers, "metadata": next_metadata}
    return {"updated": False, "identifiers": identifiers, "metadata": metadata}


def _refresh_reference_publication_dates(
    client: PapyrusGraphQLAuthoringClient,
    *,
    reference: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    structured = _extract_structured_date_candidates(reference=reference, metadata=metadata)
    extracted = {"published": None, "updated": None}
    if not structured["published"] and not structured["updated"]:
        extracted = _extract_dates_from_source_content(_clean_string(reference.get("sourceUri")) or "")
    published = structured["published"] or extracted.get("published")
    updated = structured["updated"] or extracted.get("updated")
    updates: dict[str, Any] = {"id": reference["id"]}
    detail: dict[str, Any] = {
        "source": "structured" if structured["published"] or structured["updated"] else ("content" if extracted.get("published") or extracted.get("updated") else "unresolved"),
        "published": published,
        "updated": updated,
        "updatedFields": [],
    }
    if published and _normalize_datetime(_clean_string(reference.get("sourcePublishedAt")) or "") != published:
        updates["sourcePublishedAt"] = published
        detail["updatedFields"].append("sourcePublishedAt")
    if updated and _normalize_datetime(_clean_string(reference.get("sourceUpdatedAt")) or "") != updated:
        updates["sourceUpdatedAt"] = updated
        detail["updatedFields"].append("sourceUpdatedAt")
    if len(updates) > 1:
        updates["updatedAt"] = _now_iso()
        client.upsert("Reference", updates)
        reference = client.get_record("Reference", str(reference["id"])) or reference
    return {"reference": reference, "detail": detail}


def _extract_structured_date_candidates(
    *,
    reference: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, str | None]:
    metadata_dates = metadata.get("dates") if isinstance(metadata.get("dates"), dict) else {}
    published_candidates = [
        reference.get("sourcePublishedAt"),
        metadata.get("sourcePublishedAt"),
        metadata.get("publishedAt"),
        metadata.get("published_at"),
        metadata_dates.get("publishedAt"),
        metadata_dates.get("published_at"),
    ]
    updated_candidates = [
        reference.get("sourceUpdatedAt"),
        metadata.get("sourceUpdatedAt"),
        metadata.get("updatedAt"),
        metadata.get("updated_at"),
        metadata_dates.get("updatedAt"),
        metadata_dates.get("updated_at"),
    ]
    return {
        "published": _first_datetime(published_candidates),
        "updated": _first_datetime(updated_candidates),
    }


def _extract_dates_from_source_content(source_uri: str) -> dict[str, str | None]:
    if not source_uri:
        return {"published": None, "updated": None}
    request = urllib.request.Request(
        source_uri,
        headers={"User-Agent": "Papyrus reference curation refresh"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError):
        return {"published": None, "updated": None}
    published_patterns = [
        r"(?:article:published_time|citation_publication_date|dc\.date|datePublished)[\"'\s:=>]+([^\"'<>\s]+)",
        r"\"datePublished\"\s*:\s*\"([^\"]+)\"",
        r"<time[^>]+datetime=[\"']([^\"']+)[\"']",
    ]
    updated_patterns = [
        r"(?:article:modified_time|citation_online_date|dateModified|lastmod)[\"'\s:=>]+([^\"'<>\s]+)",
        r"\"dateModified\"\s*:\s*\"([^\"]+)\"",
    ]
    return {
        "published": _first_datetime(_regex_matches(body, published_patterns)),
        "updated": _first_datetime(_regex_matches(body, updated_patterns)),
    }


def _refresh_reference_topic_predictions(
    client: PapyrusGraphQLAuthoringClient,
    *,
    reference: dict[str, Any],
    metadata: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    now = _now_iso()
    subject_lineage_id = str(reference.get("lineageId") or reference["id"])
    subject_state_key = f"reference#{subject_lineage_id}#current"
    current_predictions = [
        relation
        for relation in client.list_semantic_relations_by_subject_state(subject_state_key)
        if str(relation.get("relationState") or "").lower() == "current"
        and str(relation.get("relationTypeKey") or relation.get("predicate") or "") == "classified_as"
    ]
    superseded = 0
    for relation in current_predictions:
        updated = {
            **relation,
            "relationState": "superseded",
            "updatedAt": now,
        }
        if isinstance(updated.get("metadata"), dict):
            updated["metadata"] = json.dumps(updated["metadata"], sort_keys=True)
        client.upsert("SemanticRelation", updated)
        superseded += 1

    categories = [
        category
        for category in client.list_records("Category")
        if str(category.get("corpusId") or "") == str(reference.get("corpusId") or "")
        and str(category.get("versionState") or "") == "current"
        and str(category.get("status") or "").lower() not in {"deprecated", "archived"}
    ]
    content = " ".join(
        [
            str(reference.get("title") or ""),
            str(metadata.get("subtitle") or ""),
            str(metadata.get("summary") or ""),
            str(reference.get("externalItemId") or ""),
        ]
    ).lower()
    scored = _score_topic_prediction_candidates(categories=categories, content=content)
    created = 0
    for rank, candidate in enumerate(scored, start=1):
        relation = _build_classified_as_relation(
            reference=reference,
            category=candidate["category"],
            rank=rank,
            score=candidate["score"],
            run_id=run_id,
            imported_at=now,
        )
        client.upsert("SemanticRelation", relation)
        created += 1
    return {
        "supersededPredictions": superseded,
        "createdPredictions": created,
        "candidateCount": len(scored),
    }


def _score_topic_prediction_candidates(
    *,
    categories: list[dict[str, Any]],
    content: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    content_tokens = set(re.findall(r"[a-z0-9][a-z0-9_\-]{2,}", content.lower()))
    for category in categories:
        tokens = {
            token
            for token in re.findall(
                r"[a-z0-9][a-z0-9_\-]{2,}",
                " ".join(
                    [
                        str(category.get("categoryKey") or ""),
                        str(category.get("displayName") or ""),
                        str(category.get("shortTitle") or ""),
                        " ".join(str(entry) for entry in (category.get("aliases") or []) if entry),
                    ]
                ).lower(),
            )
        }
        overlap = sorted(content_tokens.intersection(tokens))
        if not overlap:
            continue
        score = float(len(overlap))
        results.append({"category": category, "score": score, "overlap": overlap})
    results.sort(
        key=lambda entry: (
            entry["score"],
            -int(entry["category"].get("depth") or 0),
            str(entry["category"].get("displayName") or ""),
        ),
        reverse=True,
    )
    return results[:5]


def _build_classified_as_relation(
    *,
    reference: dict[str, Any],
    category: dict[str, Any],
    rank: int,
    score: float,
    run_id: str,
    imported_at: str,
) -> dict[str, Any]:
    subject_lineage_id = str(reference.get("lineageId") or reference["id"])
    object_lineage_id = str(category.get("lineageId") or category["id"])
    subject_state_key = f"reference#{subject_lineage_id}#current"
    object_state_key = f"category#{object_lineage_id}#current"
    relation_id = f"semantic-relation-{hash_short([subject_state_key, 'classified_as', object_state_key, 'curation-reference-refresh'])}"
    return {
        "id": relation_id,
        "relationState": "current",
        "predicate": "classified_as",
        **semantic_relation_type_fields_for_predicate("classified_as"),
        "subjectKind": "reference",
        "subjectId": reference["id"],
        "subjectLineageId": subject_lineage_id,
        "subjectVersionNumber": reference.get("versionNumber"),
        "objectKind": "category",
        "objectId": category["id"],
        "objectLineageId": object_lineage_id,
        "objectVersionNumber": category.get("versionNumber"),
        "subjectStateKey": subject_state_key,
        "objectStateKey": object_state_key,
        "objectSubjectStateKey": f"{object_state_key}#reference",
        "predicateObjectStateKey": f"classified_as#{object_state_key}",
        "subjectVersionKey": f"reference#{reference['id']}",
        "objectVersionKey": f"category#{category['id']}",
        "score": score,
        "confidence": None,
        "rank": rank,
        "classifierId": "curation.reference-refresh",
        "modelVersion": "deterministic-v1",
        "reviewRecommended": True,
        "sourceSnapshotId": None,
        "importRunId": run_id,
        "importedAt": imported_at,
        "createdAt": imported_at,
        "updatedAt": imported_at,
        "newsroomFeedKey": "semanticRelations",
        "metadata": json.dumps(
            {
                "kind": "reference.curation.topic_prediction",
                "runId": run_id,
                "source": "deterministic_token_overlap",
                "categoryKey": category.get("categoryKey"),
                "displayName": category.get("displayName"),
            },
            sort_keys=True,
        ),
    }


def _upsert_reference_metadata_payload(
    client: PapyrusGraphQLAuthoringClient,
    *,
    reference: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    now = _now_iso()
    attachment = build_json_model_payload_attachment(
        {
            "ownerKind": "reference",
            "ownerId": reference["id"],
            "ownerLineageId": reference.get("lineageId") or reference["id"],
            "ownerVersionNumber": reference.get("versionNumber"),
            "ownerVersionKey": f"reference#{reference['id']}",
            "role": "metadata",
            "sortKey": "metadata",
            "filename": "metadata.json",
            "content": metadata,
            "importRunId": reference.get("importRunId"),
            "status": "active",
            "now": now,
        }
    )
    upload_attachment_body(client, attachment["attachment"], attachment["body"])
    client.upsert("ModelAttachment", attachment["attachment"])


def _regex_matches(text: str, patterns: list[str]) -> list[str]:
    values: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            if isinstance(match, tuple):
                for entry in match:
                    cleaned = _clean_string(entry)
                    if cleaned:
                        values.append(cleaned)
            else:
                cleaned = _clean_string(match)
                if cleaned:
                    values.append(cleaned)
    return values


def _first_datetime(values: list[Any]) -> str | None:
    for value in values:
        normalized = _normalize_datetime(_clean_string(value) or "")
        if normalized:
            return normalized
    return None


def _normalize_datetime(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f"{text}T00:00:00Z"
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        pass
    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        return f"{match.group(1)}T00:00:00Z"
    return None


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed if trimmed else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_last_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
