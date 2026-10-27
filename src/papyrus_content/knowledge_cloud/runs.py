"""``papyrus knowledge runs --site <site> [--last N]``: the recent cloud knowledge runs, with what each stage took and cost.

Reads the run ledger (DynamoDB) the stages write. The table is found from the ``LedgerTableName`` output of the CloudFormation
stack ``KnowledgeRun-<site>`` unless ``--table`` names it. Uses the caller's AWS credentials (set ``AWS_PROFILE``).
"""

from __future__ import annotations

import json
from typing import Any

from ..options import normalize_string, parse_options
from .config import POST_RUN_STEPS, STAGES
from .cost import duration_seconds, run_total
from .ledger import RUN_TOTAL_STAGE, query_rows

DEFAULT_LAST = 5


def group_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group ledger rows into executions, newest first: ``{week, execution, startedAt, rows, cost}``."""
    by_run: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        parts = str(row.get("runKey") or "").split("#")
        if len(parts) == 3:
            by_run.setdefault((parts[0], parts[1]), []).append({**row, "stage": parts[2]})
    runs = []
    for (week, execution), members in by_run.items():
        stage_rows = [row for row in members if row["stage"] != RUN_TOTAL_STAGE]
        started = min((row["startedAt"] for row in stage_rows if row.get("startedAt")), default="")
        runs.append({"week": week, "execution": execution, "startedAt": started, "rows": stage_rows, "cost": run_total(stage_rows, STAGES)})
    return sorted(runs, key=lambda run: run["startedAt"], reverse=True)


def clock(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m{rest:02d}s" if minutes else f"{rest}s"


def dollars(value: Any) -> str:
    return "-" if value is None else f"${value:.4f}"


def render(runs: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for run in runs:
        cost = run["cost"]
        note = " (partial: some figures are unknown)" if cost.get("partial") else ""
        lines.append(f"{run['week']}  {run['execution']}  {cost['status']}  {clock(cost['durationSeconds'])}  total {dollars(cost['totalUsd'])} "
                     f"(compute {dollars(cost['computeUsd'])}, model {dollars(cost['llm']['usd'])}, {cost['llm']['calls']} model calls){note}")
        lines.append(f"  {'stage':<18}{'status':<11}{'time':>8}{'compute':>11}{'model':>11}{'total':>11}")
        by_stage = {row["stage"]: row for row in run["rows"]}
        for stage in (*STAGES, *POST_RUN_STEPS):
            row = by_stage.get(stage)
            if row is None:
                continue
            spent = (row.get("details") or {}).get("cost") or {}
            llm = spent.get("llm") or {}
            lines.append(f"  {stage:<18}{row.get('status', '-'):<11}{clock(duration_seconds(row)):>8}"
                         f"{dollars(spent.get('computeUsd')) if spent else '-':>11}{dollars(llm.get('usd')) if spent else '-':>11}{dollars(spent.get('totalUsd')) if spent else '-':>11}")
        lines.append("")
    return "\n".join(lines).rstrip() or "No runs in the ledger."


def ledger_table(site: str, region: str, table: str | None, *, session: Any = None):
    import boto3  # noqa: PLC0415

    session = session or boto3.session.Session(region_name=region)
    if not table:
        outputs = session.client("cloudformation").describe_stacks(StackName=f"KnowledgeRun-{site}")["Stacks"][0].get("Outputs", [])
        table = next((out["OutputValue"] for out in outputs if out["OutputKey"] == "LedgerTableName"), None)
        if not table:
            raise ValueError(f"The stack KnowledgeRun-{site} has no LedgerTableName output; pass --table.")
    return session.resource("dynamodb").Table(table)


def knowledge_runs(flags: list[str], *, table: Any = None, out=print) -> None:
    options = parse_options(flags)
    site = normalize_string(options.get("site"))
    if not site:
        raise ValueError("--site <publication> is required.")
    try:
        last = int(options.get("last") or DEFAULT_LAST)
    except (TypeError, ValueError):
        raise ValueError("--last must be a whole number.") from None
    if last < 1:
        raise ValueError("--last must be at least 1.")
    region = normalize_string(options.get("region")) or "us-east-1"
    table = table or ledger_table(site, region, normalize_string(options.get("table")) or None)
    runs = group_runs(query_rows(table, site))[:last]
    if options.get("json"):
        out(json.dumps([{"week": run["week"], "execution": run["execution"], **run["cost"]} for run in runs], indent=2))
    else:
        out(render(runs))
