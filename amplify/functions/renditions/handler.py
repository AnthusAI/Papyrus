from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from papyrus_content.projection.runtime import SITE_BUCKET_ENV, SITE_STATIC_DIRECTORY_ENV
from papyrus_content.renditions import (
    RenditionSettings,
    S3RenditionStore,
    make_renditions,
    media_originals_enabled,
    meta_key,
    original_site_key,
    ORIGINAL_CACHE_CONTROL,
    settings_from_static_directory,
    source_from_media_key,
)

_loaded: dict[str, Any] = {}


def configured_settings() -> RenditionSettings | None:
    if "settings" not in _loaded:
        static_directory = (os.environ.get(SITE_STATIC_DIRECTORY_ENV) or "").strip()
        _loaded["settings"] = settings_from_static_directory(Path(static_directory) if static_directory else None)
    return _loaded["settings"]


def originals_enabled() -> bool:
    if "originals" not in _loaded:
        static_directory = (os.environ.get(SITE_STATIC_DIRECTORY_ENV) or "").strip()
        _loaded["originals"] = media_originals_enabled(Path(static_directory) if static_directory else None)
    return _loaded["originals"]


def site_store() -> S3RenditionStore:
    if "store" not in _loaded:
        _loaded["store"] = S3RenditionStore(os.environ[SITE_BUCKET_ENV])
    return _loaded["store"]


def s3_client():
    if "s3" not in _loaded:
        import boto3

        _loaded["s3"] = boto3.client("s3")
    return _loaded["s3"]


def media_objects(event: dict) -> list[tuple[str, str]]:
    if event.get("source") == "aws.s3" and "detail" in event:
        detail = event["detail"]
        return [(detail["bucket"]["name"], detail["object"]["key"])]
    if "bucket" in event and "key" in event:
        return [(event["bucket"], event["key"])]
    raise ValueError("The event is neither an S3 object event nor a {bucket, key} request.")


def render_media_object(
    settings: RenditionSettings | None,
    bucket: str,
    key: str,
    *,
    originals: bool = False,
    skip_existing: bool = False,
    dry_run: bool = False,
) -> dict:
    source = source_from_media_key(key) if settings is not None else None
    original_key = original_site_key(key) if originals else None
    if source is None and original_key is None:
        return {"key": key, "action": "ignored", "reason": "not an image under media/"}
    if skip_existing:
        renditions_exist = source is None or site_store().get(meta_key(settings.pipeline, source)) is not None
        original_exists = original_key is None or site_store().get(original_key) is not None
        if renditions_exist and original_exists:
            return {"key": key, "source": source or original_key, "action": "skipped-existing"}
    if dry_run:
        return {"key": key, "source": source or original_key, "action": "would-render" if source else "would-copy"}
    started = time.perf_counter()
    data = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
    downloaded = time.perf_counter()
    if original_key is not None:
        site_store().put(original_key, data, cache_control=ORIGINAL_CACHE_CONTROL)
    if source is None:
        return {"key": key, "source": original_key, "action": "copied", "written": 1, "sourceBytes": len(data)}
    result = make_renditions(settings, site_store(), source, data)
    finished = time.perf_counter()
    return {
        "key": key,
        "source": source,
        "action": "rendered",
        "kind": result["kind"],
        "written": result["written"] + (1 if original_key is not None else 0),
        "sourceBytes": len(data),
        "downloadMilliseconds": round((downloaded - started) * 1000),
        "renditionMilliseconds": round((finished - downloaded) * 1000),
    }


def handler(event, context):
    settings = configured_settings()
    originals = originals_enabled()
    if settings is None and not originals:
        return {"ok": True, "results": [], "skipped": "this site has no images or media settings in projection.json"}
    results = [
        render_media_object(
            settings,
            bucket,
            key,
            originals=originals,
            skip_existing=event.get("skipExisting") is True,
            dry_run=event.get("dryRun") is True,
        )
        for bucket, key in media_objects(event)
    ]
    print(json.dumps({"renditions": results}))
    return {"ok": True, "results": results}
