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

from ..edge_invalidation import InvalidationCapped, invalidate_distribution, invalidate_exact_paths
from ..page_refresh.paths import paths_for_page_keys

STATE_PREFIX = "_papyrus/"
HEAD_WORKERS = 16
PUT_WORKERS = 16
S3_MAX_POOL_CONNECTIONS = 32   # above HEAD_WORKERS and PUT_WORKERS, so parallel requests never wait for a pooled connection ("Connection pool is full")
DEFAULT_HTML_S_MAXAGE_SECONDS = 300
FALLBACK_HTML_S_MAXAGE_SECONDS = 60
HTML_STALE_WHILE_REVALIDATE_SECONDS = 60
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
ERROR_PAGE_KEY = "404.html"
ERROR_PAGE_CONTENT_TYPE = "text/html"
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
    ".md": "text/markdown; charset=utf-8",
}


class OutputPrefixError(ValueError):
    """A key a prefixed writer refuses: it would land outside the writer's output prefix."""


def normalize_output_prefix(prefix: str | None) -> str:
    """``""`` (no prefix: the site owns its whole bucket) or a relative folder ending in ``/`` ("sites/alpha/")."""
    text = (prefix or "").strip()
    if not text:
        return ""
    if text.startswith("/"):
        raise OutputPrefixError(f"The output prefix {prefix!r} must be relative to the bucket; it starts with '/'.")
    segments = text.rstrip("/").split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise OutputPrefixError(f"The output prefix {prefix!r} has an empty, '.' or '..' folder name.")
    return "/".join(segments) + "/"


def prefixed_key(output_prefix: str, key: str) -> str:
    """The stored key of a site key. With no prefix the key is returned untouched; with one, a key that is absolute or climbs out of the
    prefix (``..``) is refused, so nothing a prefixed writer writes, reads or deletes is outside its folder."""
    if not output_prefix:
        return key
    if key.startswith("/") or ".." in key.split("/"):
        raise OutputPrefixError(f"The key {key!r} is outside the output prefix {output_prefix!r}; a prefixed writer only touches keys under its prefix.")
    return output_prefix + key


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
    last_modified: str | None = None   # ISO time the store wrote it (S3 LastModified), where the store says


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

    def __init__(self, root: Path, output_prefix: str = "") -> None:
        self._root = Path(root)
        self._output_prefix = normalize_output_prefix(output_prefix)
        self._metadata: dict[str, tuple[int | None, str | None]] = {}

    def put(self, key: str, body: bytes, *, version: int | None = None, inputs: str | None = None) -> None:
        target = self._root / prefixed_key(self._output_prefix, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        self._metadata[key] = (version, inputs)

    def delete(self, key: str) -> None:
        target = self._root / prefixed_key(self._output_prefix, key)
        if target.is_file():
            target.unlink()
        self._metadata.pop(key, None)

    def get(self, key: str) -> bytes | None:
        target = self._root / prefixed_key(self._output_prefix, key)
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
        under = [key[len(self._output_prefix) :] for key in found if key.startswith(self._output_prefix)]
        return [self.head(key) for key in under if key.startswith(prefix)]


class S3PageWriter:
    source_markers = True   # item pages end with the papyrus-source-version marker (page_refresh/marker.py)

    def __init__(
        self, bucket: str, s3_client: Any = None, html_s_maxage_seconds: int = DEFAULT_HTML_S_MAXAGE_SECONDS, output_prefix: str = ""
    ) -> None:
        if s3_client is None:
            import boto3
            from botocore.config import Config

            s3_client = boto3.client("s3", config=Config(max_pool_connections=S3_MAX_POOL_CONNECTIONS))
        self._bucket = bucket
        self._output_prefix = normalize_output_prefix(output_prefix)   # "" for a site that owns its bucket; keys are then untouched
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
            last_modified=headers["LastModified"].isoformat() if hasattr(headers.get("LastModified"), "isoformat") else None,
        )

    def head(self, key: str) -> StoredObject | None:
        try:
            return self._stored_object(key, self._s3.head_object(Bucket=self._bucket, Key=prefixed_key(self._output_prefix, key)))
        except Exception as error:  # noqa: BLE001 - only "not found" is an expected absence
            if self._error_code(error) in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def get(self, key: str) -> bytes | None:
        try:
            return self._s3.get_object(Bucket=self._bucket, Key=prefixed_key(self._output_prefix, key))["Body"].read()
        except Exception as error:  # noqa: BLE001 - only "not found" is an expected absence
            if self._error_code(error) in ("NoSuchKey", "404", "NotFound"):
                return None
            raise

    def list(self, prefix: str = "") -> list[StoredObject]:
        objects: list[StoredObject] = []
        token: str | None = None
        while True:
            arguments: dict[str, Any] = {"Bucket": self._bucket, "Prefix": self._output_prefix + prefix}
            if token:
                arguments["ContinuationToken"] = token
            page = self._s3.list_objects_v2(**arguments)
            objects.extend(
                StoredObject(key=entry["Key"][len(self._output_prefix) :], etag=str(entry.get("ETag", "")).strip('"') or None)
                for entry in page.get("Contents", [])
            )
            if not page.get("IsTruncated"):
                return objects
            token = page.get("NextContinuationToken")

    def head_many(self, keys: list[str]) -> dict[str, StoredObject | None]:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=HEAD_WORKERS) as pool:
            return dict(zip(keys, pool.map(self.head, keys)))

    def _headers_for(self, key: str) -> dict[str, str]:
        """CloudFront serves the stored 404 page through its error-response path, where no viewer-response
        function runs, so the page carries the headers it must have on its own: plain ``text/html`` and no
        ``Cache-Control``."""
        if key == ERROR_PAGE_KEY:
            return {"ContentType": ERROR_PAGE_CONTENT_TYPE}
        return {
            "ContentType": content_type_for(key),
            "CacheControl": cache_control_for(key, self._html_s_maxage_seconds),
        }

    def put(self, key: str, body: bytes, *, version: int | None = None, inputs: str | None = None) -> None:
        arguments: dict[str, Any] = {"Bucket": self._bucket, "Key": prefixed_key(self._output_prefix, key), "Body": body, **self._headers_for(key)}
        metadata: dict[str, str] = {}
        if version is not None:
            metadata[VERSION_METADATA_KEY] = str(version)
        if inputs is not None:
            metadata[INPUTS_METADATA_KEY] = inputs
        if metadata:
            arguments["Metadata"] = metadata
        self._s3.put_object(**arguments)

    def put_many(self, pages: list[tuple[str, bytes, int | None, str | None]]) -> None:
        """Write ``(key, body, version, inputs)`` with up to ``PUT_WORKERS`` requests at once. Sitemaps and feeds (``.xml``) go after every
        other page of the batch, as the engine orders them, so a sitemap never names a page that is not written yet. Raises the first failure."""
        from concurrent.futures import ThreadPoolExecutor

        phases = [[page for page in pages if not page[0].endswith(".xml")], [page for page in pages if page[0].endswith(".xml")]]
        with ThreadPoolExecutor(max_workers=PUT_WORKERS) as pool:
            for phase in phases:
                for future in [pool.submit(self.put, key, body, version=version, inputs=inputs) for key, body, version, inputs in phase]:
                    future.result()

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self._bucket, Key=prefixed_key(self._output_prefix, key))


def request_paths_for_key(key: str) -> tuple[str, ...]:
    """The request paths a page answers to; the first is the canonical one (a redirect's target)."""
    if key == "index.html":
        return ("/",)
    if key.endswith("/index.html"):
        directory = "/" + key[: -len("index.html")]
        return (directory, directory.rstrip("/"))
    return ("/" + key,)


def invalidation_paths_for(keys: list[str], url_style: str = "html") -> list[str]:
    """The request paths to invalidate for written page keys, every form a page is cached under (``page_refresh/paths.py``)."""
    return paths_for_page_keys(keys, url_style)


class CloudFrontInvalidator:
    def __init__(self, distribution_id: str, cloudfront_client: Any = None) -> None:
        self._distribution_id = distribution_id
        self._cloudfront = cloudfront_client

    def invalidate(self, keys: list[str]) -> list[str]:
        return invalidate_distribution(self._distribution_id, invalidation_paths_for(keys), self._cloudfront)


class TargetedCloudFrontInvalidator:
    """``cache.invalidation: "targeted"``: purge exactly the pages a publish wrote, in both URL forms, and never collapse to ``/*``.

    More than ``cap`` paths (``publication.cache.maxInvalidationPaths``) purge the first ``cap`` and raise ``InvalidationCapped`` naming the rest.
    """

    def __init__(self, distribution_id: str, cap: int, cloudfront_client: Any = None) -> None:
        self._distribution_id = distribution_id
        self._cap = cap
        self._cloudfront = cloudfront_client

    def invalidate(self, keys: list[str]) -> list[str]:
        paths = invalidation_paths_for(keys)
        listed, skipped = paths[: self._cap], paths[self._cap :]
        if listed:
            invalidate_exact_paths(self._distribution_id, listed, self._cloudfront)
        if skipped:
            raise InvalidationCapped(listed, skipped, self._cap)
        return listed


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
