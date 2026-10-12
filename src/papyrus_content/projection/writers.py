"""Where projected pages go: a local directory, an S3 bucket behind CloudFront, a redirect store."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

HTML_CACHE_CONTROL = "public, max-age=0, s-maxage=86400"
STATIC_CACHE_CONTROL = "public, max-age=31536000, immutable"
VERSION_METADATA_KEY = "papyrus-version"
MAXIMUM_INVALIDATION_PATHS = 100
KEY_VALUE_STORE_BATCH_SIZE = 50
WHOLE_SITE_INVALIDATION_PATH = "/*"
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


def cache_control_for(key: str) -> str:
    return HTML_CACHE_CONTROL if key.endswith(".html") else STATIC_CACHE_CONTROL


class PageWriter(Protocol):
    def put(self, key: str, body: bytes, *, version: int | None = None) -> None: ...

    def delete(self, key: str) -> None: ...


class LocalDirectoryWriter:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def put(self, key: str, body: bytes, *, version: int | None = None) -> None:
        target = self._root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

    def delete(self, key: str) -> None:
        target = self._root / key
        if target.is_file():
            target.unlink()


class S3PageWriter:
    def __init__(self, bucket: str, s3_client: Any = None) -> None:
        if s3_client is None:
            import boto3

            s3_client = boto3.client("s3")
        self._bucket = bucket
        self._s3 = s3_client

    def put(self, key: str, body: bytes, *, version: int | None = None) -> None:
        arguments: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": body,
            "ContentType": content_type_for(key),
            "CacheControl": cache_control_for(key),
        }
        if version is not None:
            arguments["Metadata"] = {VERSION_METADATA_KEY: str(version)}
        self._s3.put_object(**arguments)

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self._bucket, Key=key)


def invalidation_paths_for(keys: list[str]) -> list[str]:
    paths: list[str] = []
    for key in keys:
        paths.append("/" + key)
        if PurePosixPath(key).name == "index.html":
            directory = str(PurePosixPath(key).parent)
            paths.append("/" if directory == "." else f"/{directory}/")
    unique = list(dict.fromkeys(paths))
    if len(unique) > MAXIMUM_INVALIDATION_PATHS:
        return [WHOLE_SITE_INVALIDATION_PATH]
    return unique


class CloudFrontInvalidator:
    def __init__(self, distribution_id: str, cloudfront_client: Any = None) -> None:
        if cloudfront_client is None:
            import boto3

            cloudfront_client = boto3.client("cloudfront")
        self._distribution_id = distribution_id
        self._cloudfront = cloudfront_client

    def invalidate(self, keys: list[str]) -> list[str]:
        paths = invalidation_paths_for(keys)
        if not paths:
            return []
        self._cloudfront.create_invalidation(
            DistributionId=self._distribution_id,
            InvalidationBatch={
                "Paths": {"Quantity": len(paths), "Items": paths},
                "CallerReference": uuid.uuid4().hex,
            },
        )
        return paths


class RedirectStore(Protocol):
    def put_all(self, redirects: dict[str, str]) -> None: ...

    def delete_all(self, sources: list[str]) -> None: ...


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
        etag = self._etag()
        arguments: dict[str, Any] = {"KvsARN": self._arn, "IfMatch": etag}
        if puts:
            arguments["Puts"] = puts
        if deletes:
            arguments["Deletes"] = deletes
        self._kvs.update_keys(**arguments)

    def put_all(self, redirects: dict[str, str]) -> None:
        entries = [{"Key": source, "Value": target} for source, target in redirects.items()]
        for start in range(0, len(entries), KEY_VALUE_STORE_BATCH_SIZE):
            self._update(puts=entries[start : start + KEY_VALUE_STORE_BATCH_SIZE], deletes=[])

    def delete_all(self, sources: list[str]) -> None:
        entries = [{"Key": source} for source in sources]
        for start in range(0, len(entries), KEY_VALUE_STORE_BATCH_SIZE):
            self._update(puts=[], deletes=entries[start : start + KEY_VALUE_STORE_BATCH_SIZE])
