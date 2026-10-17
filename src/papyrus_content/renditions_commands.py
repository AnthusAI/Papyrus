"""CLI entry for ``papyrus ops content renditions``: back-fill or request upload-time image renditions."""

from __future__ import annotations

import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .options import normalize_string, parse_options, resolve_mutation_apply
from .renditions import MEDIA_KEY_PREFIX, source_from_media_key

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


def content_renditions(flags: list[str]) -> None:
    options = parse_options(flags)
    source = normalize_string(options.get("source"))
    if bool(options.get("backfill")) == bool(source):
        raise ValueError("Pass exactly one of --backfill or --source <srcPath>.")
    apply = resolve_mutation_apply(options, "content renditions")
    media_bucket = normalize_string(options.get("media-bucket")) or normalize_string(os.environ.get(MEDIA_BUCKET_ENV))
    function_name = normalize_string(options.get("function-name")) or normalize_string(os.environ.get(RENDITIONS_FUNCTION_ENV))
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
    if options.get("json"):
        print(json.dumps(report, indent=2))
    else:
        verb = "Would make" if report["dryRun"] else "Made"
        print(f"{verb} renditions for {report['images']} image(s): " + ", ".join(f"{count} {action}" for action, count in report["counts"].items()))
        for result in report["results"]:
            if result.get("action") == "failed":
                print(f"error: {result['key']}: {result.get('error')}")
    if not report["ok"]:
        raise SystemExit(1)
