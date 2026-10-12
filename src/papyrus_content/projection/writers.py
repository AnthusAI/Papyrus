"""Where projected pages go: a local directory, an S3 bucket behind CloudFront, a redirect store."""

from __future__ import annotations

import hashlib
import mimetypes
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from ..edge_invalidation import invalidate_distribution

STATE_PREFIX = "_papyrus/"
HEAD_WORKERS = 16
DEFAULT_HTML_S_MAXAGE_SECONDS = 300
FALLBACK_HTML_S_MAXAGE_SECONDS = 60
HTML_STALE_WHILE_REVALIDATE_SECONDS = 60
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
IMMUTABLE_KEY_PREFIXES = ("assets/responsive/", "_next/static/")
HASHED_FILE_NAME = re.compile(r"[.-][0-9a-f]{8,}\.[A-Za-z0-9]+$")
VERSION_METADATA_KEY = "papyrus-version"
INPUTS_METADATA_KEY = "papyrus-inputs"
KEY_VALUE_STORE_BATCH_SIZE = 50
CONTENT_TYPES_BY_SUFFIX = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".xml": "application/xml",
    ".txt": "text/plain; charset=utf-8",
}


def content_type_for(key: str) -> str:
    known = CONTENT_TYPES_BY_SUFFIX.get(PurePosixPath(key).suffix.lower())
    if known is not None:
        return known
    guessed, _encoding = mimetypes.guess_type(key)
    return guessed or "application/octet-stream"


def html_cache_control(s_maxage_seconds: int = DEFAULT_HTML_S_MAXAGE_SECONDS) -> str:
    return (
        f"public, max-age=0, s-maxage={s_maxage_seconds}, "
        f"stale-while-revalidate={HTML_STALE_WHILE_REVALIDATE_SECONDS}"
    )


def is_immutable_key(key: str) -> bool:
    """Renditions and content-hashed files never change under the same name; everything else can."""
    if key.startswith(IMMUTABLE_KEY_PREFIXES) and not key.endswith(".meta.json"):
        return True
    return HASHED_FILE_NAME.search(PurePosixPath(key).name) is not None


def cache_control_for(key: str, html_s_maxage_seconds: int = DEFAULT_HTML_S_MAXAGE_SECONDS) -> str:
    if is_immutable_key(key):
        return IMMUTABLE_CACHE_CONTROL
    return html_cache_control(html_s_maxage_seconds)


@dataclass(frozen=True)
class StoredObject:
    """What the site store knows about one page: the version or inputs digest it was rendered from."""

    key: str
    etag: str | None = None
    version: int | None = None
    inputs: str | None = None


def body_etag(body: bytes) -> str:
    return hashlib.md5(body).hexdigest()  # noqa: S324 - the store's own ETag algorithm, not a security use


class PageWriter(Protocol):
    def put(self, key: str, body: bytes, *, version: int | None = None, inputs: str | None = None) -> None: ...

    def delete(self, key: str) -> None: ...

    def get(self, key: str) -> bytes | None: ...

    def head(self, key: str) -> StoredObject | None: ...

    def list(self, prefix: str = "") -> list[StoredObject]: ...


class LocalDirectoryWriter:
    """A directory as a site store; version and inputs metadata live in memory, beside the files."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._metadata: dict[str, tuple[int | None, str | None]] = {}

    def put(self, key: str, body: bytes, *, version: int | None = None, inputs: str | None = None) -> None:
        target = self._root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        self._metadata[key] = (version, inputs)

    def delete(self, key: str) -> None:
        target = self._root / key
        if target.is_file():
            target.unlink()
        self._metadata.pop(key, None)

    def get(self, key: str) -> bytes | None:
        target = self._root / key
        return target.read_bytes() if target.is_file() else None

    def head(self, key: str) -> StoredObject | None:
        body = self.get(key)
        if body is None:
            return None
        version, inputs = self._metadata.get(key, (None, None))
        return StoredObject(key=key, etag=body_etag(body), version=version, inputs=inputs)

    def list(self, prefix: str = "") -> list[StoredObject]:
        found = [
            path.relative_to(self._root).as_posix()
            for path in sorted(self._root.rglob("*"))
            if path.is_file()
        ]
        return [self.head(key) for key in found if key.startswith(prefix)]


class S3PageWriter:
    def __init__(
        self, bucket: str, s3_client: Any = None, html_s_maxage_seconds: int = DEFAULT_HTML_S_MAXAGE_SECONDS
    ) -> None:
        if s3_client is None:
            import boto3

            s3_client = boto3.client("s3")
        self._bucket = bucket
        self._s3 = s3_client
        self._html_s_maxage_seconds = html_s_maxage_seconds

    @staticmethod
    def _error_code(error: Exception) -> str:
        return str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))

    def _stored_object(self, key: str, headers: dict) -> StoredObject:
        metadata = headers.get("Metadata") or {}
        version = metadata.get(VERSION_METADATA_KEY)
        return StoredObject(
            key=key,
            etag=str(headers.get("ETag", "")).strip('"') or None,
            version=int(version) if version not in (None, "") else None,
            inputs=metadata.get(INPUTS_METADATA_KEY),
        )

    def head(self, key: str) -> StoredObject | None:
        try:
            return self._stored_object(key, self._s3.head_object(Bucket=self._bucket, Key=key))
        except Exception as error:  # noqa: BLE001 - only "not found" is an expected absence
            if self._error_code(error) in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def get(self, key: str) -> bytes | None:
        try:
            return self._s3.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except Exception as error:  # noqa: BLE001 - only "not found" is an expected absence
            if self._error_code(error) in ("NoSuchKey", "404", "NotFound"):
                return None
            raise

    def list(self, prefix: str = "") -> list[StoredObject]:
        objects: list[StoredObject] = []
        token: str | None = None
        while True:
            arguments: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                arguments["ContinuationToken"] = token
            page = self._s3.list_objects_v2(**arguments)
            objects.extend(
                StoredObject(key=entry["Key"], etag=str(entry.get("ETag", "")).strip('"') or None)
                for entry in page.get("Contents", [])
            )
            if not page.get("IsTruncated"):
                return objects
            token = page.get("NextContinuationToken")

    def head_many(self, keys: list[str]) -> dict[str, StoredObject | None]:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=HEAD_WORKERS) as pool:
            return dict(zip(keys, pool.map(self.head, keys)))

    def put(self, key: str, body: bytes, *, version: int | None = None, inputs: str | None = None) -> None:
        arguments: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": body,
            "ContentType": content_type_for(key),
            "CacheControl": cache_control_for(key, self._html_s_maxage_seconds),
        }
        metadata: dict[str, str] = {}
        if version is not None:
            metadata[VERSION_METADATA_KEY] = str(version)
        if inputs is not None:
            metadata[INPUTS_METADATA_KEY] = inputs
        if metadata:
            arguments["Metadata"] = metadata
        self._s3.put_object(**arguments)

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self._bucket, Key=key)


def request_paths_for_key(key: str) -> tuple[str, ...]:
    """The request paths a page answers to; the first is the canonical one (a redirect's target)."""
    if key == "index.html":
        return ("/",)
    if key.endswith("/index.html"):
        directory = "/" + key[: -len("index.html")]
        return (directory, directory.rstrip("/"))
    return ("/" + key,)


def invalidation_paths_for(keys: list[str]) -> list[str]:
    paths: list[str] = []
    for key in keys:
        paths.append("/" + key)
        if PurePosixPath(key).name == "index.html":
            directory = str(PurePosixPath(key).parent)
            paths.append("/" if directory == "." else f"/{directory}/")
    return list(dict.fromkeys(paths))


class CloudFrontInvalidator:
    def __init__(self, distribution_id: str, cloudfront_client: Any = None) -> None:
        self._distribution_id = distribution_id
        self._cloudfront = cloudfront_client

    def invalidate(self, keys: list[str]) -> list[str]:
        return invalidate_distribution(self._distribution_id, invalidation_paths_for(keys), self._cloudfront)


class RedirectStore(Protocol):
    def put_all(self, redirects: dict[str, str]) -> None: ...

    def delete_all(self, sources: list[str]) -> None: ...

    def list_all(self) -> dict[str, str]: ...

    def get(self, source: str) -> str | None: ...


KEY_VALUE_STORE_CONFLICT_CODES = frozenset({"ConflictException", "PreconditionFailed", "PreconditionFailedException"})
KEY_VALUE_STORE_CONFLICT_ATTEMPTS = 8


def key_value_store_conflict(error: Exception) -> bool:
    """A concurrent update moved the store's ETag: the service answers ValidationException "Pre-Condition failed"."""
    details = getattr(error, "response", {}).get("Error", {})
    if str(details.get("Code", "")) in KEY_VALUE_STORE_CONFLICT_CODES:
        return True
    return str(details.get("Code", "")) == "ValidationException" and "Pre-Condition" in str(details.get("Message", error))


class KeyValueStoreRedirects:
    """CloudFront KeyValueStore: request path to redirect target, read by the edge function."""

    def __init__(self, key_value_store_arn: str, kvs_client: Any = None) -> None:
        if kvs_client is None:
            import boto3

            kvs_client = boto3.client("cloudfront-keyvaluestore")
        self._arn = key_value_store_arn
        self._kvs = kvs_client

    def _etag(self) -> str:
        return self._kvs.describe_key_value_store(KvsARN=self._arn)["ETag"]

    def _update(self, *, puts: list[dict[str, str]], deletes: list[dict[str, str]]) -> None:
        for attempt in range(KEY_VALUE_STORE_CONFLICT_ATTEMPTS):
            arguments: dict[str, Any] = {"KvsARN": self._arn, "IfMatch": self._etag()}
            if puts:
                arguments["Puts"] = puts
            if deletes:
                arguments["Deletes"] = deletes
            try:
                self._kvs.update_keys(**arguments)
                return
            except Exception as error:  # noqa: BLE001 - a concurrent writer moved the ETag; retry with a fresh one
                if not key_value_store_conflict(error) or attempt == KEY_VALUE_STORE_CONFLICT_ATTEMPTS - 1:
                    raise
                time.sleep(random.random() * 0.05 * (attempt + 1))

    def put_all(self, redirects: dict[str, str]) -> None:
        entries = [{"Key": source, "Value": target} for source, target in redirects.items()]
        for start in range(0, len(entries), KEY_VALUE_STORE_BATCH_SIZE):
            self._update(puts=entries[start : start + KEY_VALUE_STORE_BATCH_SIZE], deletes=[])

    def delete_all(self, sources: list[str]) -> None:
        entries = [{"Key": source} for source in sources]
        for start in range(0, len(entries), KEY_VALUE_STORE_BATCH_SIZE):
            self._update(puts=[], deletes=entries[start : start + KEY_VALUE_STORE_BATCH_SIZE])

    def get(self, source: str) -> str | None:
        try:
            return str(self._kvs.get_key(KvsARN=self._arn, Key=source)["Value"])
        except Exception as error:  # noqa: BLE001 - only "no such key" is an expected absence
            if str(getattr(error, "response", {}).get("Error", {}).get("Code", "")) == "ResourceNotFoundException":
                return None
            raise

    def list_all(self) -> dict[str, str]:
        found: dict[str, str] = {}
        token: str | None = None
        while True:
            arguments: dict[str, Any] = {"KvsARN": self._arn}
            if token:
                arguments["NextToken"] = token
            page = self._kvs.list_keys(**arguments)
            found.update({entry["Key"]: entry["Value"] for entry in page.get("Items", [])})
            token = page.get("NextToken")
            if not token:
                return found
