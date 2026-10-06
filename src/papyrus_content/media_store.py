"""Media object stores shared by the Markus importer and exporter."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

from .env import storage_bucket_from_amplify_outputs


class MediaStore(Protocol):
    def put(self, storage_path: str, local_path: Path, *, content_type: str, sha256: str) -> str:
        """Store a file; return "uploaded" or "unchanged"."""

    def get(self, storage_path: str, dest: Path) -> None:
        """Download an object to ``dest``, creating parent directories."""


class S3MediaStore:
    def __init__(self, bucket: str | None = None) -> None:
        self._configured_bucket = bucket
        self._client = None

    @property
    def bucket(self) -> str:
        resolved = self._configured_bucket or storage_bucket_from_amplify_outputs()
        if not resolved:
            raise ValueError("No storage bucket: pass --bucket or provide amplify_outputs.json.")
        return resolved

    def _s3(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as error:
                raise RuntimeError("boto3 is required: install papyrus-newsroom[newsroom]") from error
            self._client = boto3.client("s3")
        return self._client

    def put(self, storage_path: str, local_path: Path, *, content_type: str, sha256: str) -> str:
        client = self._s3()
        try:
            head = client.head_object(Bucket=self.bucket, Key=storage_path)
            if (head.get("Metadata") or {}).get("sha256") == sha256:
                return "unchanged"
        except client.exceptions.ClientError as error:
            code = str(error.response.get("Error", {}).get("Code"))
            if code not in ("404", "NoSuchKey", "NotFound"):
                raise
        client.upload_file(
            str(local_path),
            self.bucket,
            storage_path,
            ExtraArgs={"ContentType": content_type, "Metadata": {"sha256": sha256}},
        )
        return "uploaded"

    def get(self, storage_path: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._s3().download_file(self.bucket, storage_path, str(dest))


class DirMediaStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, storage_path: str) -> Path:
        return self.root / storage_path

    def put(self, storage_path: str, local_path: Path, *, content_type: str, sha256: str) -> str:
        target = self._path(storage_path)
        if target.exists() and target.read_bytes() == Path(local_path).read_bytes():
            return "unchanged"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, target)
        return "uploaded"

    def get(self, storage_path: str, dest: Path) -> None:
        source = self._path(storage_path)
        if not source.is_file():
            raise FileNotFoundError(f"No stored media object {storage_path}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
