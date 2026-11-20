"""Operator command: move a site's newsletter subscribers into its notifications table (PPY-6b2d35; steps in ``migration.py``).

    python -m papyrus_content.notifications.migration_cli plan   --newsletter-table <table>
    python -m papyrus_content.notifications.migration_cli run    --newsletter-table <table> --old-links-until <YYYY-MM-DD> --sends-frozen [--dry-run]
    python -m papyrus_content.notifications.migration_cli verify --newsletter-table <table>

The environment is the notifications function's own (``TABLE_NAME``, ``RECIPIENT_KEY_PARAMETER``, ``LISTS_JSON`` and the rest of
``Settings``): export the router function's configuration, so the audience this builds is the one readers will use. ``plan`` and
``run --dry-run`` only read and print. ``run`` writes, so it refuses without ``--sends-frozen`` (the operator's statement that the
agreed freeze of the site's newsletter sends is on) and refuses while the plan has problems. It sends no mail. Run it once per
site, never against a site until the freeze is agreed with the owner; ``verify`` afterwards must print "every count matches".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from papyrus_content.newsletter.store import Store

from . import migration
from .settings import Settings


def end_of_day(text: str) -> int:
    """``2027-03-31`` -> the last second of that day, UTC. The alias rows expire then."""
    day = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(day.timestamp()) + 24 * 3600 - 1


def live_runtime() -> Any:
    from .runtime import build_runtime

    return build_runtime()


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] = os.environ,
    store_factory: Callable[[str], Store] = Store,
    runtime_factory: Callable[[], Any] = live_runtime,
    now: Callable[[], float] = time.time,
    out: Any = None,
) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="python -m papyrus_content.notifications.migration_cli", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run", "verify"):
        sub = commands.add_parser(name)
        sub.add_argument("--newsletter-table", required=True, help="the site's newsletter DynamoDB table")
        sub.add_argument("--json", action="store_true", help="print JSON instead of text")
        if name == "run":
            sub.add_argument("--old-links-until", help="the last day (YYYY-MM-DD, UTC) old newsletter links keep working")
            sub.add_argument("--sends-frozen", action="store_true", help="the agreed freeze of the site's newsletter sends is on")
            sub.add_argument("--dry-run", action="store_true", help="read and print only")
    args = parser.parse_args(argv)

    declared = [entry["id"] for entry in Settings.from_environment(environment).lists]
    snapshot = migration.read_source(store_factory(args.newsletter_table), now())
    plan = migration.build_plan(snapshot, declared)

    def emit(text: str, data: Mapping[str, Any]) -> None:
        out.write((json.dumps(data, indent=2, sort_keys=True) if args.json else text) + "\n")

    if args.command == "plan" or (args.command == "run" and args.dry_run):
        emit(migration.render_plan(plan), plan.as_dict())
        return 1 if plan.problems else 0

    runtime = runtime_factory()
    target = migration.Target(runtime.audience, runtime.recipient_key)
    if args.command == "verify":
        report = migration.verify(plan, target, declared_lists=declared)
        emit(migration.render_verification(report), report.as_dict())
        return 0 if report.ok else 1

    if not args.sends_frozen or not args.old_links_until:
        parser.error("run writes: it needs --sends-frozen and --old-links-until (or --dry-run)")
    try:
        result = migration.apply(plan, snapshot, target, old_links_until=end_of_day(args.old_links_until), declared_lists=declared)
    except migration.Refused as problem:
        out.write(f"Refused: {problem}\n")
        return 1
    emit(f"Imported {result.imported}, unchanged {result.unchanged}, refused {len(result.refused)}, settled {result.settled}, aliases {result.aliases}", result.as_dict())
    return 1 if result.refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
