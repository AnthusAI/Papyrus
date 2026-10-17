"""Private S3 media store for ``import-markus``, ``export-published`` and ``videos attach``.

Objects live under the ``media/*`` prefix of the Amplify Storage bucket. The
bucket stays private: readers get signed ``getUrl`` links resolved from the
``storagePath`` that ``MediaAsset`` rows keep. Credentials come only from the
caller's AWS profile or the Lambda role, never from stored keys.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .env import PAPYRUS_ROOT, amplify_outputs_path, storage_bucket_from_amplify_outputs

MEDIA_KEY_PREFIX = "media/"
NOT_FOUND_CODES = ("404", "NoSuchKey", "NotFound")
BUCKET_ENVIRONMENT_VARIABLES = ("PAPYRUS_MEDIA_BUCKET", "PAPYRUS_STORAGE_BUCKET")


def storage_region_from_amplify_outputs(filepath: str | Path | None = None) -> str | None:
    path = Path(filepath) if filepath else amplify_outputs_path()
    if not path.is_absolute():
        path = PAPYRUS_ROOT / path
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    storage = parsed.get("storage") or {}
    return storage.get("aws_region") or storage.get("region")


def configured_media_bucket(explicit_bucket: str | None = None) -> str | None:
    if explicit_bucket:
        return explicit_bucket
    for name in BUCKET_ENVIRONMENT_VARIABLES:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return storage_bucket_from_amplify_outputs()


class S3MediaStore:
    def __init__(self, bucket: str | None = None, *, region: str | None = None, client: Any = None) -> None:
        resolved_bucket = configured_media_bucket(bucket)
        if not resolved_bucket:
            raise ValueError(
                "No media bucket configured: pass --bucket, set PAPYRUS_MEDIA_BUCKET, "
                "or provide amplify_outputs.json with a storage bucket."
            )
        self.bucket = resolved_bucket
        if client is not None:
            self._client = client
            return
        try:
            import boto3
        except ImportError as error:
            raise RuntimeError("boto3 is required for S3 media: install papyrus-newsroom[markus].") from error
        resolved_region = region or storage_region_from_amplify_outputs()
        self._client = boto3.client("s3", region_name=resolved_region) if resolved_region else boto3.client("s3")

    def _require_media_key(self, storage_path: str) -> None:
        if not storage_path.startswith(MEDIA_KEY_PREFIX) or ".." in storage_path.split("/"):
            raise ValueError(f"Media storage path must live under '{MEDIA_KEY_PREFIX}': {storage_path}")

    def _stored_sha256(self, storage_path: str) -> str | None:
        from botocore.exceptions import ClientError

        try:
            head = self._client.head_object(Bucket=self.bucket, Key=storage_path)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in NOT_FOUND_CODES:
                return None
            raise
        return (head.get("Metadata") or {}).get("sha256")

    def has(self, storage_path: str, sha256: str) -> bool:
        return self._stored_sha256(storage_path) == sha256

    def put(self, storage_path: str, local_path: Path, *, content_type: str, sha256: str) -> str:
        self._require_media_key(storage_path)
        if self.has(storage_path, sha256):
            return "unchanged"
        with Path(local_path).open("rb") as body:
            self._client.put_object(
                Bucket=self.bucket,
                Key=storage_path,
                Body=body,
                ContentType=content_type,
                Metadata={"sha256": sha256},
            )
        return "uploaded"

    def get(self, storage_path: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self.bucket, storage_path, str(dest))
