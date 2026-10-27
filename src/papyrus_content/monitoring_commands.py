"""Small local-worker command: due collection or explicit bounded watch.

SQLite is a local checkpoint, not a cloud storage/deployment architecture.
An existing scheduler can invoke `run` repeatedly; it skips runs before due.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import quote

from .monitoring import Monitor, collect


def load_monitor(path: str) -> Monitor:
    config_path = Path(path).resolve()
    raw = json.loads(config_path.read_text())
    allowed = {"schemaVersion", "monitorId", "publication", "corpusId", "endpoint", "state",
               "intervalSeconds", "limit", "sourceIds", "appId"}   # `limit` is retired: accepted, ignored
    if not isinstance(raw, dict) or raw.get("schemaVersion") != 1 or set(raw) - allowed:
        raise ValueError("Monitor config requires schemaVersion 1 and supported explicit binding fields")
    if "limit" in raw:   # the monitor reads the whole feed now; an old config still loads
        print(json.dumps({"monitor": "ignored_retired_config", "fields": ["limit"]}))
    state = Path(raw["state"])
    if not state.is_absolute():
        state = config_path.parent / state
    return Monitor(raw["monitorId"], raw["publication"], raw["corpusId"], raw["endpoint"], state,
                   raw.get("intervalSeconds", 900), tuple(raw.get("sourceIds") or ()))


def status(monitor: Monitor) -> dict:
    path = Path(monitor.state)
    if not path.exists():
        return {"monitorId": monitor.id, "publication": monitor.publication, "status": "not_run"}
    if path.is_symlink():
        raise ValueError("Monitor checkpoint must not be a symlink")
    with sqlite3.connect("file:" + quote(str(path.resolve()), safe="/") + "?mode=ro", uri=True) as db:
        binding = db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()
        if not binding or json.loads(binding[0]) != monitor.binding:
            raise ValueError("Monitor status binding does not match")
        result = db.execute("SELECT value FROM meta WHERE key='last_result'").fetchone()
        return json.loads(result[0]) if result else {"status": "not_run"}


def run_worker(monitor: Monitor, intake, *, watch=False, max_runs=None, force=False,
               clock=time.time, sleep=time.sleep, emit=print) -> int:
    if max_runs is not None and max_runs < 1:
        raise ValueError("max-runs must be positive")
    if force and watch:
        raise ValueError("force is for one explicit recovery run, not recurring polling")
    runs, failed = 0, False
    while True:
        result = collect(monitor, intake, now=clock(), force=force)
        emit(json.dumps(result, sort_keys=True))
        failed = failed or bool(result["errors"])
        if result["status"] != "not_due":
            runs += 1
        if not watch or (max_runs is not None and runs >= max_runs):
            return 1 if failed else 0
        due = datetime.fromisoformat(result["nextDueAt"].replace("Z", "+00:00")).timestamp()
        # Short waits permit prompt interruption and do not poll a source early.
        sleep(min(60, max(0.1, due - clock())))


def command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="papyrus monitors")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Collect one due HN batch through existing worker intake")
    run.add_argument("--config", required=True)
    run.add_argument("--auth", required=True, choices=["iam"], help="Explicit existing worker lane; no user-to-IAM fallback")
    run.add_argument("--watch", action="store_true", help="Explicit local worker loop; installs no scheduler")
    run.add_argument("--max-runs", type=int)
    run.add_argument("--force", action="store_true", help="One recovery run even before due")
    view = sub.add_parser("status", help="Read this local checkpoint without source or backend calls")
    view.add_argument("--config", required=True)
    local = sub.add_parser("collect-local", help="Collect public HN RSS into private review files; no app authentication or classification")
    local.add_argument("--directory", required=True, help="Private local queue directory outside publication content")
    local.add_argument("--interval-seconds", type=int, default=900)
    local.add_argument("--shown-records", help="Private JSON array of source/message presentation receipts; no labels")
    backfill = sub.add_parser("backfill-decision-relations",
                              help="Write the missing relevance_decision_is relations for References the router delivered before #517 (dry-run unless --apply)")
    backfill.add_argument("--monitor", default="hn")
    backfill.add_argument("--publication", action="append", help="Only this publication id (repeatable)")
    backfill.add_argument("--since", help="Only deliveries at or after this ISO timestamp (with timezone)")
    backfill.add_argument("--apply", action="store_true", help="Write the relations; without it nothing is written")
    backfill.add_argument("--dry-run", action="store_true", help="The default; accepted for clarity")
    window = sub.add_parser("backfill",
                            help="Load a Hugging Face monitor's history for its configured filters: pages the whole window, waits out rate limits, Ctrl-C safe and resumable (dry-run unless --apply)")
    window.add_argument("--monitor", required=True)
    window.add_argument("--since", required=True, help="Models created at or after this ISO timestamp (with timezone)")
    window.add_argument("--until", help="Only models created before this ISO timestamp (with timezone)")
    window.add_argument("--apply", action="store_true", help="Write discoveries and the checkpoint; without it nothing is written")
    args = parser.parse_args(argv)
    if args.command == "backfill":
        from .monitoring_backfill import collection_command
        return collection_command(args)
    if args.command == "backfill-decision-relations":
        if args.apply and args.dry_run:
            parser.error("--apply and --dry-run are mutually exclusive")
        from .monitoring_backfill import command as backfill_command
        return backfill_command(args)
    if args.command == "collect-local":
        from .monitoring_queue import collect_queue
        shown = json.loads(Path(args.shown_records).read_text()) if args.shown_records else ()
        result = collect_queue(args.directory, interval_seconds=args.interval_seconds, shown_records=shown)
        print(json.dumps(result, sort_keys=True))
        return 1 if result["status"] == "failed" else 0
    monitor = load_monitor(args.config)
    if args.command == "status":
        print(json.dumps(status(monitor), sort_keys=True))
        return 0
    os.environ["PAPYRUS_GRAPHQL_AUTH"] = args.auth
    from .graphql_authoring import PapyrusGraphQLAuthoringClient
    from .monitoring_intake import ReferenceIntake
    from .operator_errors import OperatorError
    from botocore.exceptions import BotoCoreError, ClientError
    client = PapyrusGraphQLAuthoringClient(endpoint=monitor.endpoint)
    try:
        intake = ReferenceIntake(client, monitor, auth_mode=args.auth)
    except (BotoCoreError, ClientError) as error:
        raise OperatorError(f"Monitor worker could not verify its configured publication: {error}") from error
    try:
        return run_worker(monitor, intake, watch=args.watch, max_runs=args.max_runs, force=args.force)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(command(__import__("sys").argv[1:]))
