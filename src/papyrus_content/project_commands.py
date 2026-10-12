"""CLI entry for ``papyrus ops content project``: re-project published content onto the site store."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_options
from .projection.engine import (
    ProjectionContext,
    project,
    project_all,
    project_item_pages,
    project_listings,
    reconcile,
)
from .projection.runtime import (
    SITE_BUCKET_ENV,
    SITE_STATIC_DIRECTORY_ENV,
    context_from_environment,
    load_projector,
)
from .projection.source import PublishedContentSource
from .projection.writers import LocalDirectoryWriter


def _projection_environment(options: dict) -> dict[str, str]:
    environment = dict(os.environ)
    bucket = normalize_string(options.get("bucket"))
    if bucket:
        environment[SITE_BUCKET_ENV] = bucket
    static_directory = normalize_string(options.get("static-dir"))
    if static_directory:
        environment[SITE_STATIC_DIRECTORY_ENV] = static_directory
    return environment


def _context_for(client, options: dict) -> ProjectionContext:
    environment = _projection_environment(options)
    output_directory = normalize_string(options.get("out"))
    if output_directory:
        return ProjectionContext(
            source=PublishedContentSource(client),
            projector=load_projector(environment),
            writer=LocalDirectoryWriter(Path(output_directory)),
            keep_state=False,
        )
    return context_from_environment(client, environment)


def content_project(flags: list[str]) -> None:
    options = parse_options(flags)
    item_id = normalize_string(options.get("item"))
    modes = [
        bool(options.get("all")),
        bool(options.get("listings")),
        bool(options.get("reconcile")),
        bool(options.get("item-pages")),
        bool(item_id),
    ]
    if sum(modes) != 1:
        raise ValueError("Pass exactly one of --all, --listings, --reconcile, --item-pages or --item <item-id>.")
    client, _claims = create_authoring_client()
    context = _context_for(client, options)
    if options.get("reconcile"):
        _run_reconcile(context, options)
        return
    if options.get("all"):
        report = project_all(context)
    elif options.get("item-pages"):
        report = project_item_pages(context)
    elif options.get("listings"):
        report = project_listings(context)
    else:
        report = project(context, item_id, unpublished=bool(options.get("unpublished")))
    payload = report.to_dict()
    if options.get("json"):
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"Projected: {payload['written']} written, {payload['deleted']} deleted, "
            f"{payload['redirectsWritten']} redirects, {payload['invalidated']} invalidation paths"
        )
        for error in report.errors:
            print(f"error: {error}")
    if not report.ok:
        raise SystemExit(1)


def _run_reconcile(context: ProjectionContext, options: dict) -> None:
    report = reconcile(context, dry_run=bool(options.get("dry-run")))
    payload = report.to_dict()
    if options.get("json"):
        print(json.dumps(payload, indent=2))
    else:
        verb = "Found" if report.dry_run else "Repaired"
        print(
            f"{verb}: {len(report.stale_items)} stale items, {len(report.removed_items)} removed items, "
            f"{len(report.stale_listings)} stale listings, {len(report.orphan_pages)} orphan pages, "
            f"{report.redirects_repaired} redirects"
        )
        for error in report.errors:
            print(f"error: {error}")
    if not report.ok or (report.dry_run and report.drift):
        raise SystemExit(1)
