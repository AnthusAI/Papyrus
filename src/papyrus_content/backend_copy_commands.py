"""CLI entry for ``papyrus ops content copy-backend`` (PPY-26f158)."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .backend_copy import (
    DEFAULT_S3_PREFIXES,
    CopyPlan,
    apply_plan,
    build_plan,
    parse_selection,
    render_table,
    write_manifests,
)
from .backend_copy_aws import (
    SERVER_SIDE_TRANSFER,
    STREAM_TRANSFER,
    GraphQLRowBackend,
    ReadOnlyS3Client,
    S3ObjectStore,
    resolve_location,
)
from .options import normalize_positive_integer, normalize_string, parse_options

NO_PREFIXES_KEYWORD = "none"
AUTO_TRANSFER = "auto"
TRANSFER_CHOICES = (AUTO_TRANSFER, SERVER_SIDE_TRANSFER, STREAM_TRANSFER)
PROGRESS_INTERVAL_SECONDS = 15.0


def make_boto3_session(profile: str | None) -> Any:
    import boto3

    return boto3.Session(profile_name=profile) if profile else boto3.Session()


def open_side_session(
    side: str,
    profile: str | None,
    expected_account: str | None,
    session_factory: Callable[[str | None], Any],
) -> tuple[Any, str | None]:
    if not profile and not expected_account:
        return None, None
    session = session_factory(profile)
    account = str(session.client("sts").get_caller_identity()["Account"])
    if expected_account and account != expected_account:
        raise ValueError(
            f"The {side} credentials belong to account {account}, not the expected {expected_account}. "
            "Nothing was read or written."
        )
    return session, account


def resolve_transfer_mode(option: str | None, source_profile: str | None, target_profile: str | None) -> str:
    chosen = option or AUTO_TRANSFER
    if chosen not in TRANSFER_CHOICES:
        raise ValueError(f"--s3-transfer must be one of {', '.join(TRANSFER_CHOICES)}.")
    if chosen == AUTO_TRANSFER:
        return STREAM_TRANSFER if (source_profile or target_profile) else SERVER_SIDE_TRANSFER
    return chosen


def resolve_s3_selection(prefix_option: str | None, keys_option: str | None) -> tuple[list[str], list[str]]:
    keys = parse_selection(keys_option, []) if keys_option else []
    if prefix_option == NO_PREFIXES_KEYWORD:
        return [], keys
    if prefix_option is None and keys:
        return [], keys
    return parse_selection(prefix_option, DEFAULT_S3_PREFIXES), keys


def parse_key_field_defaults(option: str | None) -> dict[str, str]:
    defaults: dict[str, str] = {}
    for assignment in parse_selection(option, []):
        name, separator, value = assignment.partition("=")
        if not separator or "." not in name or not value:
            raise ValueError(f"--key-field-defaults entries must look like Model.field=value, got {assignment}.")
        defaults[name] = value
    return defaults


def make_progress_reporter() -> Callable[[int, int, int], None]:
    lock = threading.Lock()
    state = {"last": time.monotonic()}

    def report(done: int, total: int, copied_bytes: int) -> None:
        with lock:
            now = time.monotonic()
            if done != total and now - state["last"] < PROGRESS_INTERVAL_SECONDS:
                return
            state["last"] = now
        print(f"s3 copy progress: {done}/{total} objects, {copied_bytes / 1_000_000:.1f} MB", file=sys.stderr)

    return report


def content_copy_backend(flags: list[str], session_factory: Callable[[str | None], Any] = make_boto3_session) -> None:
    options = parse_options(flags)
    source_spec = normalize_string(options.get("source-outputs"))
    target_spec = normalize_string(options.get("target-outputs"))
    if not source_spec or not target_spec:
        raise ValueError("--source-outputs and --target-outputs are required.")
    apply = bool(options.get("apply"))
    if apply and options.get("dry-run"):
        raise ValueError("Pass either --apply or --dry-run, not both.")
    source_profile = normalize_string(options.get("source-profile"))
    target_profile = normalize_string(options.get("target-profile"))
    transfer = resolve_transfer_mode(normalize_string(options.get("s3-transfer")), source_profile, target_profile)
    workers = normalize_positive_integer(options.get("s3-workers"), "--s3-workers") or 1
    source_session, source_account = open_side_session(
        "source", source_profile, normalize_string(options.get("expect-source-account")), session_factory
    )
    target_session, target_account = open_side_session(
        "target", target_profile, normalize_string(options.get("expect-target-account")), session_factory
    )
    source_location = resolve_location(source_spec, source_session)
    target_location = resolve_location(target_spec, target_session)
    if source_location.endpoint == target_location.endpoint or (
        source_location.bucket and source_location.bucket == target_location.bucket
    ):
        raise ValueError("The source and the target must be different backends.")

    requested_models = parse_selection(normalize_string(options.get("models")), []) if options.get("models") else None
    prefixes, keys = resolve_s3_selection(
        normalize_string(options.get("s3-prefixes")), normalize_string(options.get("s3-keys"))
    )
    key_field_defaults = parse_key_field_defaults(normalize_string(options.get("key-field-defaults")))

    source = GraphQLRowBackend(source_location.endpoint, read_only=True, session=source_session)
    target = GraphQLRowBackend(target_location.endpoint, read_only=False, session=target_session)
    source_store = target_store = None
    if source_location.bucket and target_location.bucket:
        source_store = S3ObjectStore(source_location.bucket, source_location.region, session=source_session)
        source_store.client = ReadOnlyS3Client(source_store.client)
        target_store = S3ObjectStore(
            target_location.bucket, target_location.region, session=target_session, transfer=transfer
        )

    plan = build_plan(
        source,
        target,
        requested_models=requested_models,
        source_store=source_store,
        target_store=target_store,
        selected_prefixes=prefixes,
        selected_keys=keys,
        key_field_defaults=key_field_defaults,
        source_account=source_account,
        target_account=target_account,
    )
    if apply:
        apply_plan(plan, target, source_store, target_store, workers=workers, progress=make_progress_reporter())
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
                selected_keys=keys,
                key_field_defaults=key_field_defaults,
                source_account=source_account,
                target_account=target_account,
            )
        write_manifests(Path(manifest_directory), manifest_plan)

    if options.get("json"):
        print(json.dumps(plan.to_dict(), indent=2))
    else:
        print(f"content copy-backend ({'applied' if apply else 'dry run, nothing written'}): ok={plan.ok}")
        print(render_table(plan))
        for message in plan.errors:
            print(f"  error: {message}")
        for entry in plan.models:
            for invalid in entry.invalid:
                print(f"  invalid {entry.model} {invalid['id']}: {','.join(invalid['problems'])}")
            for message in entry.errors:
                print(f"  error {entry.model}: {message}")
        for entry in plan.prefixes:
            for message in entry.errors:
                print(f"  error {entry.prefix}: {message}")
            for message in entry.warnings:
                print(f"  warning {entry.prefix}: {message}")
    if not plan.ok:
        raise SystemExit(1)

