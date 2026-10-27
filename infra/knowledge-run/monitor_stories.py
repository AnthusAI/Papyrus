"""Optional step of the scheduled knowledge run, after trend-drafts: write up the items the site's monitors found (docs/knowledge-cloud-run.md).

Runs `papyrus ideas monitor-stories --site <publication> --store proposals --limit <N> --json` once. It files private `story_draft`
Proposals (one per chosen item, each citing its source and naming the monitor) and raises one soft review request; nothing is published. The
command picks the items itself, from the References the site's monitors delivered, ranked by the relevance Cyclotron's verdict, and never
drafts the same Reference twice, so the step can run on every execution.

It records its cost in the run ledger like a stage: one row, `<ISO week>#<execution>#monitor-stories`, with `details.cost` (Fargate compute
for the step plus the model calls the command made, priced from the usage the API returned). The run's own total, written by `projection`,
does not include it (it is written before this step runs); `papyrus knowledge runs` shows the row.

This script never fails the run: every problem is logged as `monitor-stories: skipped: <reason>` or `monitor-stories: failed: <reason>` and
the exit status is 0. It reads the OpenAI key from SSM at run time and hands it to the child process only; the key is never printed. Accounting
that goes wrong never gets in the way: the step still succeeds and the row has no `cost`.

Environment: KNOWLEDGE_PUBLICATION, KNOWLEDGE_CORPUS_KEY (optional), KNOWLEDGE_EXECUTION_NAME, KNOWLEDGE_EXECUTION_START (ISO time), KNOWLEDGE_OPENAI_KEY_PARAMETER,
KNOWLEDGE_LEDGER_TABLE, MONITOR_STORIES_ENDPOINT, and optionally MONITOR_STORIES_LIMIT (3).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Callable, Mapping

STAGE = "monitor-stories"
DEFAULT_LIMIT = 3
ENDPOINT_PATTERN = re.compile(r"^https://[a-z0-9]+\.appsync-api\.[a-z0-9-]+\.amazonaws\.com/graphql$")


class Skip(Exception):
    """A reason to do nothing this run; logged, never an error."""


def start_time(started: str) -> dt.datetime:
    text = started.strip()
    if not text:
        raise Skip("KNOWLEDGE_EXECUTION_START is not set")
    moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment.astimezone(dt.timezone.utc) if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


def exclude_flags(environment: Mapping[str, str]) -> list[str]:
    """``--exclude-host HOST`` for each host in KNOWLEDGE_EXCLUDED_SOURCE_HOSTS (comma-separated; the site's `knowledgeRun.excludedSourceHosts`)."""
    hosts = [host.strip() for host in (environment.get("KNOWLEDGE_EXCLUDED_SOURCE_HOSTS") or "").split(",") if host.strip()]
    return [flag for host in hosts for flag in ("--exclude-host", host)]


def command_for(publication: str, limit: int, corpus_key: str = "", excluded_hosts: list[str] | None = None) -> list[str]:
    """``corpus_key`` is the knowledge corpus the site's References live in; empty means the corpus named like the publication."""
    corpus = ["--corpus-key", corpus_key] if corpus_key and corpus_key != publication else []
    return ["papyrus", "ideas", "monitor-stories", "--site", publication, *corpus, "--store", "proposals", "--limit", str(limit), *(excluded_hosts or []), "--json"]


def read_openai_key(parameter: str) -> str:
    import boto3  # in the image; imported late so the module loads without it

    value = boto3.client("ssm").get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"].strip()
    if not value:
        raise Skip(f"SSM parameter {parameter} is empty")
    return value


def open_ledger(environment: Mapping[str, str], started: dt.datetime) -> Any:
    import boto3

    from papyrus_content.knowledge_cloud.config import iso_week
    from papyrus_content.knowledge_cloud.ledger import RunLedger

    table = boto3.resource("dynamodb", region_name=(environment.get("AWS_REGION") or "us-east-1").strip()).Table(environment["KNOWLEDGE_LEDGER_TABLE"])
    return RunLedger(table, environment["KNOWLEDGE_PUBLICATION"].strip(), iso_week(started.date()), (environment.get("KNOWLEDGE_EXECUTION_NAME") or "manual").strip())


def execute_command(args: list[str], environment: Mapping[str, str]) -> tuple[int, str]:
    finished = subprocess.run(args, env=dict(environment), check=False, stdout=subprocess.PIPE, text=True)
    return finished.returncode, finished.stdout


def parse_run(output: str) -> dict[str, Any]:
    """The run record from the command's `--json` output (the line the JSON starts on and what follows)."""
    start = output.find("{")
    if start < 0:
        raise ValueError("the command printed no JSON")
    document, _end = json.JSONDecoder().raw_decode(output[start:])
    return document["run"]


def summary_of(run: dict[str, Any]) -> dict[str, Any]:
    inputs = run.get("inputs") or {}
    return {
        "filed": len(run.get("drafts") or []), "attempted": run.get("attempted", 0), "candidates": inputs.get("candidates", 0),
        "alreadyDrafted": inputs.get("alreadyDrafted", 0), "excludedHost": inputs.get("excludedHost", 0), "handledByAutomation": inputs.get("handledByAutomation", 0), "failedTheCheck": len(run.get("invalid") or []), "skipped": len(run.get("skipped") or []),
        "duplicates": len(run.get("duplicates") or []), "review": (run.get("review") or {}).get("status"),
    }


def cost_of(run: dict[str, Any] | None, environment: Mapping[str, str], started_at: float, attempt: int, ledger: Any, task_info: Callable[[], Any] | None = None) -> dict[str, Any] | None:
    """The step's cost record, or None when the accounting itself fails (it must never get in the way)."""
    try:
        from papyrus_content.knowledge_cloud import cost

        latest = cost.stage_cost(
            elapsed_seconds=time.monotonic() - started_at, task=(task_info or (lambda: cost.task_resources(environment)))(),
            now=dt.datetime.now(dt.timezone.utc), calls=list((run or {}).get("modelCalls") or []),
        )
        return cost.add_attempt(ledger.cost(STAGE) if attempt > 1 else None, latest)
    except Exception as error:  # noqa: BLE001
        print(f"monitor-stories: cost accounting skipped: {type(error).__name__}: {error}", flush=True)
        return None


def run(environment: Mapping[str, str], *, read_key: Callable[[str], str] = read_openai_key, execute: Callable[[list[str], Mapping[str, str]], tuple[int, str]] = execute_command,
        ledger: Any = None, task_info: Callable[[], Any] | None = None) -> str:
    """Does the step; returns a one-line outcome. Raises Skip for a reason not to run and any other exception for a failure."""
    publication = (environment.get("KNOWLEDGE_PUBLICATION") or "").strip()
    endpoint = (environment.get("MONITOR_STORIES_ENDPOINT") or "").strip()
    key_parameter = (environment.get("KNOWLEDGE_OPENAI_KEY_PARAMETER") or "").strip()
    if not publication:
        raise Skip("KNOWLEDGE_PUBLICATION is not set")
    if not ENDPOINT_PATTERN.match(endpoint):
        raise Skip("MONITOR_STORIES_ENDPOINT is not an AppSync GraphQL address")
    if not key_parameter:
        raise Skip("KNOWLEDGE_OPENAI_KEY_PARAMETER is not set")
    try:
        limit = int(environment.get("MONITOR_STORIES_LIMIT") or DEFAULT_LIMIT)
    except ValueError as error:
        raise Skip("MONITOR_STORIES_LIMIT is not a whole number") from error
    if limit < 1:
        raise Skip("MONITOR_STORIES_LIMIT must be at least 1")
    started = start_time(environment.get("KNOWLEDGE_EXECUTION_START", ""))
    child_environment = dict(environment)
    child_environment.update(PAPYRUS_GRAPHQL_AUTH="iam", PAPYRUS_GRAPHQL_ENDPOINT=endpoint, OPENAI_API_KEY=read_key(key_parameter))
    ledger = ledger or open_ledger(environment, started)
    attempt, clock = ledger.begin(STAGE), time.monotonic()
    run_record: dict[str, Any] | None = None
    try:
        command = command_for(publication, limit, (environment.get("KNOWLEDGE_CORPUS_KEY") or "").strip(), exclude_flags(environment))
        print("+ " + " ".join(command), flush=True)
        status, output = execute(command, child_environment)
        if status != 0:
            raise RuntimeError(f"`papyrus ideas monitor-stories` exited with {status}")
        run_record = parse_run(output)
    except Exception as error:
        ledger.fail(STAGE, f"{type(error).__name__}: {error}", cost_of(run_record, environment, clock, attempt, ledger, task_info))
        raise
    result = summary_of(run_record)
    spent = cost_of(run_record, environment, clock, attempt, ledger, task_info)
    ledger.finish(STAGE, {"result": result, **({"cost": spent} if spent else {})})
    return f"filed {result['filed']} of {result['candidates']} candidates ({result['attempted']} attempted, {result['failedTheCheck']} failed the check)" + (
        f", cost ${spent['totalUsd']}" if spent else ""
    )


def main() -> int:
    try:
        outcome = run(os.environ)
    except Skip as skip:
        print(f"monitor-stories: skipped: {skip}", flush=True)
    except Exception as error:  # noqa: BLE001 - this step must never fail the knowledge run
        print(f"monitor-stories: failed: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
    else:
        print(f"monitor-stories: ok: {outcome}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
