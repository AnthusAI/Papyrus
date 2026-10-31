"""CLI: ``papyrus home-page snapshot``."""

from __future__ import annotations

import json
import sys
from contextlib import nullcontext
from typing import Any

from ..options import normalize_string, parse_options, resolve_mutation_apply
from .settings import HomePageSettings
from .task import home_page_settings_of, run_home_page_snapshot

CLI_WORKERS = 8


class _NoStore:
    """A dry run with no destination: nothing to compare with, nothing to write."""

    class _Writer:
        def get(self, key: str) -> None:
            return None

    projector = None
    invalidate = None
    writer = _Writer()

    def leased(self) -> Any:
        return nullcontext()


def home_page_snapshot(flags: list[str]) -> None:
    """``papyrus home-page snapshot [--site KEY] [--site-bucket B | --out DIR] [--static-dir DIR] [--dry-run] [--json]``.

    Writes ``_data/home-page/references.json`` of the site's accepted and recommended References when it changed, then re-renders
    the pages that read it. ``--site KEY`` names the publication when ``homePage.references.corpus`` is not set. ``--dry-run`` writes
    nothing: it prints the counts and the size of the file.
    """
    from ..graphql_authoring import create_authoring_client
    from ..knowledge_snapshot.commands import authoring_client

    options = parse_options(flags)
    write = resolve_mutation_apply(options, "home-page snapshot")
    site = normalize_string(options.get("site"))
    if options.get("out") and options.get("site-bucket"):
        raise ValueError("Pass --out or --site-bucket, not both.")
    has_store = bool(options.get("out") or options.get("site-bucket"))
    if write and not has_store:
        raise ValueError("Pass --out DIR (a local directory) or --site-bucket NAME (the site store), or --dry-run.")
    client = authoring_client(options)
    if options.get("site-bucket"):
        options["bucket"] = options["site-bucket"]
    if has_store:
        from ..project_commands import _context_for

        context = _context_for(client, options)
    else:
        context = _NoStore()
    settings = home_page_settings_of(context.projector) or HomePageSettings()
    report = run_home_page_snapshot(
        context,
        client,
        settings,
        site=site,
        dry_run=not write,
        client_factory=lambda: create_authoring_client()[0],
        workers=CLI_WORKERS,
    )
    if options.get("json"):
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"home-page\tsnapshot\t{report['references']} references\t{report['bytes']} bytes")
        print(
            f"home-page\tsnapshot\t{len(report['written'])} written\t{len(report['unchanged'])} unchanged\t"
            f"{report['pagesRewritten']} pages rewritten\t{len(report['purged'])} purged"
        )
    for error in report.get("errors", ()):
        print(f"error: {error}", file=sys.stderr)
    if report.get("errors"):
        raise SystemExit(1)


HOME_PAGE_COMMANDS = {"snapshot": home_page_snapshot}
