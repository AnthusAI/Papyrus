"""Run state in S3, per publication: ``publications/<publication>/{config,corpus,runs/<week>}/``.

``config/`` holds what an operator maintains (vocabulary, stop words, review guidance, amplify_outputs.json); ``corpus/`` is
the long-lived Biblicus corpus with the previous run's identity state (``knowledge-run.json``); ``runs/<week>/`` is the
scratch folder of a run. A stage downloads what it needs into the work directory and uploads what it changed, so a
container keeps nothing between stages.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _md5(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - compared with the S3 ETag of a single-part upload, not a security check
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class StateStore:
    def __init__(self, client: Any, bucket: str, prefix: str) -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix

    def _objects(self, relative: str) -> dict[str, dict]:
        found: dict[str, dict] = {}
        paginator = self.client.get_paginator("list_objects_v2")
        root = self.prefix + relative
        for page in paginator.paginate(Bucket=self.bucket, Prefix=root):
            for entry in page.get("Contents", []):
                found[entry["Key"][len(root):]] = entry
        return found

    def download(self, relative: str, directory: Path) -> int:
        """Copy every object under ``relative`` into ``directory``; returns how many files were fetched."""
        fetched = 0
        directory.mkdir(parents=True, exist_ok=True)
        for name, entry in self._objects(relative).items():
            if not name or name.endswith("/"):
                continue
            target = directory / name
            if target.exists() and target.stat().st_size == entry["Size"] and entry["ETag"].strip('"') == _md5(target):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(self.bucket, self.prefix + relative + name, str(target))
            fetched += 1
        return fetched

    def upload(self, relative: str, directory: Path, *, prune: bool = False) -> int:
        """Copy every changed file of ``directory`` up. With ``prune`` the prefix mirrors the directory: objects whose file
        is gone get a delete marker (bucket versioning keeps the old version)."""
        if not directory.is_dir():
            return 0
        existing = self._objects(relative)
        sent = 0
        present = set()
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            name = path.relative_to(directory).as_posix()
            present.add(name)
            entry = existing.get(name)
            if entry and entry["Size"] == path.stat().st_size and entry["ETag"].strip('"') == _md5(path):
                continue
            self.client.upload_file(str(path), self.bucket, self.prefix + relative + name)
            sent += 1
        if prune:
            for name in set(existing) - present:
                if name and not name.endswith("/"):
                    self.client.delete_object(Bucket=self.bucket, Key=self.prefix + relative + name)
        return sent

    def read_text(self, relative: str) -> str | None:
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=self.prefix + relative)["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None
        return body.decode("utf-8")

    def write_text(self, relative: str, text: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self.prefix + relative, Body=text.encode("utf-8"))
