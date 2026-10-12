"""Image renditions made once, at media upload, and read by page renders.

A media object uploaded to ``media/<srcPath>`` is turned into the same
derivatives the full Markus build makes (``ImageBuilder`` does the work, with
the site's pipeline settings), written to the site store at the deterministic
``assets/responsive/<dir>/<stem>-<width>.<format>`` paths, plus
``<stem>.meta.json`` (a plain-data description of the set) and, when the site
asks for it, a downscaled listing copy under ``assets/content/``. The
``meta.json`` is written last, so its presence means the whole set exists.

The projector never opens or encodes an image: ``StoredRenditionImageBuilder``
reads the ``meta.json`` instead and fails loudly when it is missing.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, fields, replace
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .markus_renderer.images import (
    PASSTHROUGH_SUFFIXES,
    RASTER_SUFFIXES,
    ImageBuilder,
    ImagePipeline,
    ImagePipelineError,
    Rendition,
    _GatsbyMeta,
    assert_safe_asset_src,
)

MEDIA_KEY_PREFIX = "media/"
LISTING_COPY_DIRECTORY = "assets/content"
META_SUFFIX = ".meta.json"
RECORD_VERSION = 1
RENDITION_CACHE_CONTROL = "public, max-age=31536000, immutable"
META_CACHE_CONTROL = "public, max-age=0, s-maxage=60"
IMAGES_SETTINGS_KEY = "images"
LISTING_WIDTH_SETTING = "listing_max_width"
NON_DATA_PIPELINE_FIELDS = frozenset({"source_dir", "cache_dir", "wrap"})
CONTENT_TYPES_BY_SUFFIX = {
    ".avif": "image/avif",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".json": "application/json",
}
HANDLED_SUFFIXES = RASTER_SUFFIXES | PASSTHROUGH_SUFFIXES


class MissingRenditionsError(ImagePipelineError):
    """A page references an image whose renditions were never made."""


@dataclass(frozen=True)
class RenditionSettings:
    """The site's image pipeline settings as the rendition function and the projector share them."""

    pipeline: ImagePipeline
    listing_max_width: int | None = None


def settings_from_mapping(raw: dict) -> RenditionSettings:
    allowed = {field.name for field in fields(ImagePipeline)} - NON_DATA_PIPELINE_FIELDS
    unknown = set(raw) - allowed - {LISTING_WIDTH_SETTING}
    if unknown:
        raise ValueError(f"Unknown image settings: {', '.join(sorted(unknown))}")
    pipeline_values = {name: value for name, value in raw.items() if name != LISTING_WIDTH_SETTING}
    for tuple_field in ("widths", "formats"):
        if pipeline_values.get(tuple_field) is not None:
            pipeline_values[tuple_field] = tuple(pipeline_values[tuple_field])
    return RenditionSettings(
        pipeline=ImagePipeline(**pipeline_values),
        listing_max_width=raw.get(LISTING_WIDTH_SETTING),
    )


def settings_from_static_directory(static_directory: Path | None) -> RenditionSettings | None:
    settings_path = static_directory / "projection.json" if static_directory is not None else None
    if settings_path is None or not settings_path.is_file():
        return None
    raw = json.loads(settings_path.read_text(encoding="utf-8")).get(IMAGES_SETTINGS_KEY)
    return None if raw is None else settings_from_mapping(raw)


def source_from_media_key(media_key: str) -> str | None:
    if not media_key.startswith(MEDIA_KEY_PREFIX) or media_key.endswith("/"):
        return None
    source = media_key[len(MEDIA_KEY_PREFIX) :]
    if PurePosixPath(source).suffix.lower() not in HANDLED_SUFFIXES:
        return None
    try:
        return assert_safe_asset_src(source)
    except ImagePipelineError:
        return None


def rendition_directory(pipeline: ImagePipeline, source: str) -> str:
    directory = f"{pipeline.out_subdir}/{PurePosixPath(source).parent.as_posix()}".rstrip("/.")
    return directory if directory.endswith("/") else directory + "/"


def meta_key(pipeline: ImagePipeline, source: str) -> str:
    return f"{rendition_directory(pipeline, source)}{PurePosixPath(source).stem}{META_SUFFIX}"


def listing_copy_key(source: str) -> str:
    return f"{LISTING_COPY_DIRECTORY}/{source}"


def content_type_for_key(key: str) -> str:
    return CONTENT_TYPES_BY_SUFFIX.get(PurePosixPath(key).suffix.lower(), "application/octet-stream")


class RenditionStore(Protocol):
    def get(self, key: str) -> bytes | None: ...

    def put(self, key: str, body: bytes, *, cache_control: str) -> None: ...


class DirectoryRenditionStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def get(self, key: str) -> bytes | None:
        path = self._root / key
        return path.read_bytes() if path.is_file() else None

    def put(self, key: str, body: bytes, *, cache_control: str) -> None:
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


class S3RenditionStore:
    def __init__(self, bucket: str, s3_client: Any = None) -> None:
        if s3_client is None:
            import boto3

            s3_client = boto3.client("s3")
        self._bucket = bucket
        self._s3 = s3_client

    def get(self, key: str) -> bytes | None:
        try:
            return self._s3.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except self._s3.exceptions.NoSuchKey:
            return None

    def put(self, key: str, body: bytes, *, cache_control: str) -> None:
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type_for_key(key),
            CacheControl=cache_control,
        )


def write_listing_copy(source_file: Path, destination: Path, maximum_width: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source_file.suffix.lower() in PASSTHROUGH_SUFFIXES:
        shutil.copy2(source_file, destination)
        return
    try:
        from PIL import Image

        with Image.open(source_file) as image:
            if image.width <= maximum_width:
                shutil.copy2(source_file, destination)
                return
            height = round(image.height * maximum_width / image.width)
            resized = image.resize((maximum_width, height), Image.LANCZOS)
            if resized.mode in {"P", "RGBA"} and destination.suffix.lower() in {".jpg", ".jpeg"}:
                resized = resized.convert("RGB")
            resized.save(destination)
    except Exception:  # noqa: BLE001 - an unreadable file ships as the original, as the full build does
        shutil.copy2(source_file, destination)


@dataclass
class BuiltRenditions:
    files: dict[str, bytes]
    meta_key: str
    meta: dict

    @property
    def meta_bytes(self) -> bytes:
        return json.dumps(self.meta, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_renditions(settings: RenditionSettings, source: str, data: bytes) -> BuiltRenditions:
    pipeline = settings.pipeline
    work = Path(tempfile.mkdtemp(prefix="renditions-"))
    try:
        source_root = work / "source"
        source_file = source_root / source
        source_file.parent.mkdir(parents=True)
        source_file.write_bytes(data)
        out_root = work / "out"
        out_root.mkdir()
        builder = ImageBuilder(
            replace(pipeline, source_dir=source_root, cache_dir=work / "cache"),
            content_dir=source_root,
            out_dir=out_root,
        )
        record = builder.rendition_record(source, source_file.resolve())
        files = {
            path.relative_to(out_root).as_posix(): path.read_bytes()
            for path in sorted(out_root.rglob("*"))
            if path.is_file()
        }
        listing_width = settings.listing_max_width
        if listing_width is not None:
            listing_file = work / "listing" / source
            write_listing_copy(source_file, listing_file, listing_width)
            files[listing_copy_key(source)] = listing_file.read_bytes()
        meta = {
            "version": RECORD_VERSION,
            "source": source,
            "sourceBytes": len(data),
            "sourceSha256": hashlib.sha256(data).hexdigest(),
            "gatsbyParity": pipeline.gatsby_parity,
            "quality": pipeline.resolved_quality(),
            "listingCopy": listing_copy_key(source) if listing_width is not None else None,
            **record,
        }
        return BuiltRenditions(files=files, meta_key=meta_key(pipeline, source), meta=meta)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def store_renditions(store: RenditionStore, built: BuiltRenditions) -> list[str]:
    for key, body in built.files.items():
        store.put(key, body, cache_control=RENDITION_CACHE_CONTROL)
    store.put(built.meta_key, built.meta_bytes, cache_control=META_CACHE_CONTROL)
    return [*built.files, built.meta_key]


def make_renditions(settings: RenditionSettings, store: RenditionStore, source: str, data: bytes) -> dict:
    built = build_renditions(settings, source, data)
    written = store_renditions(store, built)
    return {"source": source, "kind": built.meta["kind"], "written": len(written), "keys": written}


class RenditionCatalog:
    """The ``meta.json`` records of one site store, read by page renders."""

    def __init__(self, store: RenditionStore, pipeline: ImagePipeline) -> None:
        self._store = store
        self._pipeline = pipeline
        self._records: dict[str, dict | None] = {}

    @staticmethod
    def _is_stored_source(source: str) -> bool:
        try:
            return not assert_safe_asset_src(source).lower().startswith(("http://", "https://"))
        except ImagePipelineError:
            return False

    def _load(self, source: str) -> dict | None:
        raw = self._store.get(meta_key(self._pipeline, source))
        return None if raw is None else json.loads(raw)

    def prefetch(self, sources: Iterable[str], *, workers: int = 8) -> None:
        pending = sorted({source for source in sources if source not in self._records and self._is_stored_source(source)})
        if not pending:
            return
        with ThreadPoolExecutor(max_workers=min(workers, len(pending))) as executor:
            for source, record in zip(pending, executor.map(self._load, pending)):
                self._records[source] = record

    def record(self, source: str) -> dict:
        if source not in self._records:
            self._records[source] = self._load(source)
        record = self._records[source]
        if record is None:
            raise MissingRenditionsError(
                f"Renditions for image {source!r} are missing: "
                f"{meta_key(self._pipeline, source)} is not in the site store. "
                f"They are made when the image is uploaded to {MEDIA_KEY_PREFIX}{source}. "
                f"Request them with: papyrus ops content renditions --source {source}"
            )
        return record


def _rendition_from_data(data: dict) -> Rendition:
    return Rendition(width=data["width"], height=data["height"], href=data["href"], fmt=data["format"])


class StoredRenditionImageBuilder(ImageBuilder):
    """An ``ImageBuilder`` that reads stored renditions instead of opening and encoding images."""

    def __init__(self, pipeline: ImagePipeline, catalog: RenditionCatalog) -> None:
        super().__init__(pipeline, content_dir=Path("."), out_dir=Path("."))
        self._catalog = catalog

    def _locate(self, src: str) -> Path | None:
        self._catalog.record(src)
        return Path(src)

    def _passthrough_href(self, src: str, path: Path) -> str:
        return self._catalog.record(src)["href"]

    def _passthrough_dimensions(self, path: Path, suffix: str) -> tuple[int, int] | None:
        size = self._catalog.record(path.as_posix())["size"]
        return tuple(size) if size else None

    def _expect_kind(self, src: str, kind: str) -> dict:
        record = self._catalog.record(src)
        if record["kind"] != kind:
            raise MissingRenditionsError(
                f"Renditions for image {src!r} were made as {record['kind']!r} but this site renders {kind!r}; "
                f"re-make them with: papyrus ops content renditions --source {src}"
            )
        return record

    def _gatsby_renditions(self, src: str, path: Path) -> _GatsbyMeta:
        cached = self._gatsby.get(src)
        if cached is not None:
            return cached
        record = self._expect_kind(src, "gatsby")
        meta = _GatsbyMeta(
            renditions=[_rendition_from_data(item) for item in record["renditions"]],
            intrinsic=tuple(record["size"]),
            display_width=record["displayWidth"],
            fallback_fmt=record["fallbackFormat"],
            placeholder=record["placeholder"],
        )
        self._gatsby[src] = meta
        return meta

    def _renditions(self, src: str, path: Path) -> list[Rendition]:
        cached = self._cache.get(src)
        if cached is not None:
            return cached
        record = self._expect_kind(src, "legacy")
        renditions = [_rendition_from_data(item) for item in record["renditions"]]
        self._cache[src] = renditions
        self._intrinsic[src] = tuple(record["size"])
        return renditions
