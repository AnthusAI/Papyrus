"""CLI entry for ``papyrus content upload-preview`` (PPY-f00c89)."""

from __future__ import annotations

import json
from pathlib import Path

from .env import storage_bucket_from_amplify_outputs
from .options import normalize_string, parse_options
from .preview_upload import PREVIEW_PREFIX, PreviewUploadError, upload_preview


def content_upload_preview(flags: list[str]) -> None:
    options = parse_options(flags)
    directory_raw = normalize_string(options.get("dir"))
    if not directory_raw:
        raise ValueError("Pass --dir <built site directory>.")
    bucket = normalize_string(options.get("bucket")) or storage_bucket_from_amplify_outputs()
    if not bucket:
        raise ValueError("Pass --bucket or provide amplify_outputs.json with storage.bucket_name.")
    prefix = normalize_string(options.get("prefix")) or PREVIEW_PREFIX
    try:
        import boto3
    except ImportError as error:
        raise RuntimeError("boto3 is required: install papyrus-newsroom[newsroom].") from error
    try:
        report = upload_preview(boto3.client("s3"), bucket, Path(directory_raw), prefix)
    except PreviewUploadError as error:
        payload = {"ok": False, "error": str(error)}
        print(json.dumps(payload, indent=2) if options.get("json") else f"upload-preview failed: {error}")
        raise SystemExit(1)
    if options.get("json"):
        print(json.dumps({"ok": True, **report.to_dict()}, indent=2))
    else:
        counts = report.to_dict()
        print(
            f"Synced {directory_raw} to s3://{bucket}/{prefix}: "
            f"{counts['uploaded']} uploaded, {counts['unchanged']} unchanged, {counts['deleted']} deleted"
        )
