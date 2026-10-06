"""Sync a built static site to the private ``preview/`` S3 prefix (PPY-f00c89)."""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PREVIEW_PREFIX = "preview/"
NOT_FOUND_CODES = ("404", "NoSuchKey", "NotFound")


class PreviewUploadError(Exception):
    pass


@dataclass
class PreviewUploadReport:
    bucket: str
    prefix: str
    uploaded: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "prefix": self.prefix,
            "uploaded": len(self.uploaded),
            "unchanged": len(self.unchanged),
            "deleted": len(self.deleted),
        }


def sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_type_for(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def collect_local_files(directory: Path, prefix: str) -> dict[str, Path]:
    files = {
        f"{prefix}{path.relative_to(directory).as_posix()}": path
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }
    if not files:
        raise PreviewUploadError(f"Refusing to upload an empty directory: {directory}.")
    return files


def list_remote_keys(client: Any, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    token: str | None = None
    while True:
        arguments: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            arguments["ContinuationToken"] = token
        page = client.list_objects_v2(**arguments)
        keys.extend(entry["Key"] for entry in page.get("Contents", []))
        if not page.get("IsTruncated"):
            return keys
        token = page["NextContinuationToken"]


def stored_sha256(client: Any, bucket: str, key: str) -> str | None:
    from botocore.exceptions import ClientError

    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in NOT_FOUND_CODES:
            return None
        raise
    return (head.get("Metadata") or {}).get("sha256")


def upload_preview(client: Any, bucket: str, directory: Path, prefix: str = PREVIEW_PREFIX) -> PreviewUploadReport:
    if prefix != PREVIEW_PREFIX:
        raise PreviewUploadError(f'Refusing prefix "{prefix}": only "{PREVIEW_PREFIX}" may be synced.')
    if not directory.is_dir():
        raise PreviewUploadError(f"Not a directory: {directory}.")
    local_files = collect_local_files(directory, prefix)
    report = PreviewUploadReport(bucket=bucket, prefix=prefix)
    remote_keys = set(list_remote_keys(client, bucket, prefix))
    for key, path in local_files.items():
        digest = sha256_of_file(path)
        if key in remote_keys and stored_sha256(client, bucket, key) == digest:
            report.unchanged.append(key)
            continue
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=path.read_bytes(),
            ContentType=content_type_for(path),
            CacheControl="no-store",
            Metadata={"sha256": digest},
        )
        report.uploaded.append(key)
    stale_keys = sorted(remote_keys - set(local_files))
    for start in range(0, len(stale_keys), 1000):
        batch = stale_keys[start : start + 1000]
        client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": key} for key in batch]})
    report.deleted.extend(stale_keys)
    return report
