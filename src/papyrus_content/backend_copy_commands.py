"""CLI entry for ``papyrus ops content copy-backend`` (PPY-26f158)."""

from __future__ import annotations

import json
from pathlib import Path

from .backend_copy import (
    DEFAULT_S3_PREFIXES,
    CopyPlan,
    apply_plan,
    build_plan,
    parse_selection,
    render_table,
    write_manifests,
)
from .backend_copy_aws import GraphQLRowBackend, S3ObjectStore, resolve_location
from .options import normalize_string, parse_options

NO_PREFIXES_KEYWORD = "none"


def content_copy_backend(flags: list[str]) -> None:
    options = parse_options(flags)
    source_spec = normalize_string(options.get("source-outputs"))
    target_spec = normalize_string(options.get("target-outputs"))
    if not source_spec or not target_spec:
        raise ValueError("--source-outputs and --target-outputs are required.")
    apply = bool(options.get("apply"))
    if apply and options.get("dry-run"):
        raise ValueError("Pass either --apply or --dry-run, not both.")
    source_location = resolve_location(source_spec)
    target_location = resolve_location(target_spec)
    if source_location.endpoint == target_location.endpoint or (
        source_location.bucket and source_location.bucket == target_location.bucket
    ):
        raise ValueError("The source and the target must be different backends.")

    requested_models = parse_selection(normalize_string(options.get("models")), []) if options.get("models") else None
    prefix_option = normalize_string(options.get("s3-prefixes"))
    prefixes = [] if prefix_option == NO_PREFIXES_KEYWORD else parse_selection(prefix_option, DEFAULT_S3_PREFIXES)

    source = GraphQLRowBackend(source_location.endpoint, read_only=True)
    target = GraphQLRowBackend(target_location.endpoint, read_only=False)
    source_store = target_store = None
    if source_location.bucket and target_location.bucket:
        source_store = S3ObjectStore(source_location.bucket, source_location.region)
        target_store = S3ObjectStore(target_location.bucket, target_location.region)

    plan = build_plan(
        source,
        target,
        requested_models=requested_models,
        source_store=source_store,
        target_store=target_store,
        selected_prefixes=prefixes,
    )
    if apply:
        apply_plan(plan, target, source_store, target_store)
    manifest_directory = normalize_string(options.get("manifest-dir"))
    if manifest_directory:
        manifest_plan: CopyPlan = plan
        if apply:
            manifest_plan = build_plan(
                source,
                target,
                requested_models=requested_models,
                source_store=source_store,
                target_store=target_store,
                selected_prefixes=prefixes,
            )
        write_manifests(Path(manifest_directory), manifest_plan)

    if options.get("json"):
        print(json.dumps(plan.to_dict(), indent=2))
    else:
        print(f"content copy-backend ({'applied' if apply else 'dry run, nothing written'}): ok={plan.ok}")
        print(render_table(plan))
        for entry in plan.models:
            for invalid in entry.invalid:
                print(f"  invalid {entry.model} {invalid['id']}: {','.join(invalid['problems'])}")
            for message in entry.errors:
                print(f"  error {entry.model}: {message}")
        for entry in plan.prefixes:
            for message in entry.errors:
                print(f"  error {entry.prefix}: {message}")
    if not plan.ok:
        raise SystemExit(1)
