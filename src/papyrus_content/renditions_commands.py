"""CLI entry for ``papyrus ops content renditions``: back-fill or request upload-time image renditions."""

from __future__ import annotations

import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .options import normalize_string, parse_options, resolve_mutation_apply
from .renditions import MEDIA_KEY_PREFIX, media_key_for_source, source_from_media_key

MEDIA_BUCKET_ENV = "PAPYRUS_MEDIA_BUCKET_NAME"
RENDITIONS_FUNCTION_ENV = "PAPYRUS_RENDITIONS_FUNCTION_NAME"
DEFAULT_WORKERS = 8
INVOCATION_READ_TIMEOUT_SECONDS = 330


def media_image_keys(s3_client: Any, bucket: str, *, originals: bool = False) -> list[str]:
    keys: list[str] = []
    for page in s3_client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=MEDIA_KEY_PREFIX):
        for entry in page.get("Contents", []):
            if source_from_media_key(entry["Key"]) is not None or (originals and not entry["Key"].endswith("/")):
                keys.append(entry["Key"])
    return sorted(keys)


def invoke_for_key(lambda_client: Any, function_name: str, bucket: str, key: str, *, skip_existing: bool, dry_run: bool) -> dict:
    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps({"bucket": bucket, "key": key, "skipExisting": skip_existing, "dryRun": dry_run}).encode("utf-8"),
    )
    payload = json.loads(response["Payload"].read() or b"{}")
    if response.get("FunctionError") or not payload.get("ok"):
        return {"key": key, "action": "failed", "error": json.dumps(payload)[:500]}
    return payload["results"][0] if payload.get("results") else {"key": key, "action": "skipped"}


def run_renditions(
    lambda_client: Any,
    s3_client: Any,
    *,
    function_name: str,
    media_bucket: str,
    keys: list[str] | None,
    skip_existing: bool,
    dry_run: bool,
    workers: int = DEFAULT_WORKERS,
    originals: bool = False,
) -> dict:
    selected = keys if keys is not None else media_image_keys(s3_client, media_bucket, originals=originals)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(selected) or 1))) as executor:
        results = list(
            executor.map(
                lambda key: invoke_for_key(
                    lambda_client, function_name, media_bucket, key, skip_existing=skip_existing, dry_run=dry_run
                ),
                selected,
            )
        )
    counts = Counter(result.get("action", "unknown") for result in results)
    return {"ok": counts.get("failed", 0) == 0, "dryRun": dry_run, "images": len(selected), "counts": dict(sorted(counts.items())), "results": results}


def request_renditions_signed_in(store: Any, *, source: str | None, dry_run: bool, tenant_id: str | None = None) -> dict:
    """Asks for renditions without an AWS login: the editor's own bucket access writes each picture over itself, unchanged.

    The bucket announces a new object and the site's renditions function makes the renditions, exactly as for an upload (the
    function is the same one; no AWS credentials or function name are needed). ``source`` is a picture's ``srcPath``; with
    none, every image under ``media/`` is requested. An object that is not at ``media/<srcPath>`` is reported as missing, and
    when it is found under the tenant key an older save-version used, the result says which command moves it.
    """
    from .tenancy import tenant_media_path

    keys = [media_key_for_source(source)] if source else [key for key in store.keys(MEDIA_KEY_PREFIX) if source_from_media_key(key) is not None]
    results: list[dict] = []
    for key in keys:
        if not store.exists(key):
            result = {"key": key, "action": "missing", "error": f"There is no object at {key}."}
            legacy = tenant_media_path(tenant_id, key) if tenant_id else key
            if legacy != key and store.exists(legacy):
                result["error"] += (
                    f" It is stored at {legacy}, the tenant key older save-versions used. Move it with: "
                    "papyrus stories repair-image-paths --story <lineage id> --write"
                )
            results.append(result)
        elif dry_run:
            results.append({"key": key, "action": "would-request"})
        else:
            store.touch(key)
            results.append({"key": key, "action": "requested"})
    counts = Counter(result["action"] for result in results)
    return {"ok": counts.get("missing", 0) == 0, "dryRun": dry_run, "images": len(keys), "counts": dict(sorted(counts.items())), "results": results}


def _signed_in_lane() -> bool:
    from .user_auth_mode import user_auth_requested

    return user_auth_requested()


def _report(report: dict, options: dict) -> None:
    if options.get("json"):
        print(json.dumps(report, indent=2))
    else:
        verb = "Would make" if report["dryRun"] else "Made"
        print(f"{verb} renditions for {report['images']} image(s): " + ", ".join(f"{count} {action}" for action, count in report["counts"].items()))
        for result in report["results"]:
            if result.get("action") in ("failed", "missing"):
                print(f"error: {result['key']}: {result.get('error')}")
    if not report["ok"]:
        raise SystemExit(1)


def content_renditions(flags: list[str]) -> None:
    options = parse_options(flags)
    source = normalize_string(options.get("source"))
    if bool(options.get("backfill")) == bool(source):
        raise ValueError("Pass exactly one of --backfill or --source <srcPath>.")
    apply = resolve_mutation_apply(options, "content renditions")
    media_bucket = normalize_string(options.get("media-bucket")) or normalize_string(os.environ.get(MEDIA_BUCKET_ENV))
    function_name = normalize_string(options.get("function-name")) or normalize_string(os.environ.get(RENDITIONS_FUNCTION_ENV))
    if not (media_bucket and function_name) and _signed_in_lane():
        from .story_images import open_media_store
        from .tenancy import configured_tenant_id

        try:
            tenant_id = configured_tenant_id()
        except Exception:  # noqa: BLE001 - the tenant only improves a hint
            tenant_id = None
        store = open_media_store(media_bucket, normalize_string(options.get("identity-pool-id")))
        _report(request_renditions_signed_in(store, source=source, dry_run=not apply, tenant_id=tenant_id), options)
        return
    if not media_bucket or not function_name:
        raise ValueError(f"Set --media-bucket and --function-name (or {MEDIA_BUCKET_ENV} and {RENDITIONS_FUNCTION_ENV}).")
    import boto3
    from botocore.config import Config

    lambda_client = boto3.client("lambda", config=Config(read_timeout=INVOCATION_READ_TIMEOUT_SECONDS, retries={"max_attempts": 2}))
    s3_client = boto3.client("s3")
    keys = [f"{MEDIA_KEY_PREFIX}{source}"] if source else None
    report = run_renditions(
        lambda_client,
        s3_client,
        function_name=function_name,
        media_bucket=media_bucket,
        keys=keys,
        skip_existing=bool(options.get("backfill")),
        dry_run=not apply,
        workers=int(options.get("workers") or DEFAULT_WORKERS),
        originals=bool(options.get("originals")),
    )
    _report(report, options)
