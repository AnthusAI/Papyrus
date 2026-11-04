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
import mimetypes
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
MEDIA_SETTINGS_KEY = "media"
ORIGINALS_SETTING = "originals"
ORIGINAL_CACHE_CONTROL = "public, max-age=0, s-maxage=60"
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


#: What a site gets without declaring ``images``: the pipeline's own defaults (widths, WebP, a 1024 px fallback, lazy loading).
#: ``::image`` is rendered from renditions; plain Markdown images are left as the author wrote them, so a page without
#: ``::image`` renders byte for byte as it did before images were on by default. A site that declares ``images`` as an object
#: also has its plain images upgraded (``upgrade_plain_images``), as it always did.
DEFAULT_IMAGE_SETTINGS = RenditionSettings(pipeline=ImagePipeline(upgrade_plain_images=False))


def images_from_projection(raw: dict) -> RenditionSettings | None:
    """The image settings of a ``projection.json`` mapping: on with the defaults when ``images`` is absent, ``true`` or ``null``;
    ``false`` turns them off (``None``); an object declares them."""
    value = raw.get(IMAGES_SETTINGS_KEY)
    if value is False:
        return None
    if value is None or value is True:
        return DEFAULT_IMAGE_SETTINGS
    if not isinstance(value, dict):
        raise ValueError('projection.json "images" must be true, false or an object of image settings')
    return settings_from_mapping(value)


def settings_from_static_directory(static_directory: Path | None) -> RenditionSettings | None:
    """The site's image settings (see ``images_from_projection``); a site without a ``projection.json`` has the defaults."""
    settings_path = static_directory / "projection.json" if static_directory is not None else None
    raw = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path is not None and settings_path.is_file() else {}
    return images_from_projection(raw)


def media_key_for_source(source: str) -> str:
    """The one place a picture's S3 key is made from its ``srcPath`` (the inverse of ``source_from_media_key``).

    A story picture's ``srcPath`` (``assets/<slug>/<file>``) is what its body says, what its ``MediaAsset`` row records, and the
    source the renditions are made and looked up under. Its object is always ``media/<srcPath>``: the newsroom editor, ``stories
    save-version --images`` and the renditions function all agree on that, with no tenant in the key. A tenant is told apart by its
    rows (``tenantId``) and by its backend and site bucket, never by the key, because the renditions are read by ``srcPath`` alone.
    """
    return MEDIA_KEY_PREFIX + assert_safe_asset_src(source)


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
    known = CONTENT_TYPES_BY_SUFFIX.get(PurePosixPath(key).suffix.lower())
    if known is not None:
        return known
    guessed, _encoding = mimetypes.guess_type(key)
    return guessed or "application/octet-stream"


def base_path_from_static_directory(static_directory: Path | None) -> str:
    """``urls.basePath`` of the site's ``projection.json`` without slashes (``""`` for a site at the root): the prefix of every site store key."""
    settings_path = static_directory / "projection.json" if static_directory is not None else None
    if settings_path is None or not settings_path.is_file():
        return ""
    urls = json.loads(settings_path.read_text(encoding="utf-8")).get("urls")
    return str((urls or {}).get("basePath") or "").strip("/") if isinstance(urls, dict) else ""


def media_originals_enabled(static_directory: Path | None) -> bool:
    settings_path = static_directory / "projection.json" if static_directory is not None else None
    if settings_path is None or not settings_path.is_file():
        return False
    media = json.loads(settings_path.read_text(encoding="utf-8")).get(MEDIA_SETTINGS_KEY)
    return isinstance(media, dict) and media.get(ORIGINALS_SETTING) is True


def original_site_key(media_key: str) -> str | None:
    """The site store key a media object is published at: its key without the ``media/`` prefix."""
    if not media_key.startswith(MEDIA_KEY_PREFIX) or media_key.endswith("/"):
        return None
    try:
        return assert_safe_asset_src(media_key[len(MEDIA_KEY_PREFIX) :])
    except ImagePipelineError:
        return None


class RenditionStore(Protocol):
    def get(self, key: str) -> bytes | None: ...

    def keys(self, prefix: str) -> list[str]: ...

    def put(self, key: str, body: bytes, *, cache_control: str) -> None: ...


class PrefixedRenditionStore:
    """A rendition store whose every key lives under a prefix: the site store of a site under ``urls.basePath``.

    The keys callers use are site-relative (``assets/responsive/...``); the store holds them at ``<base path>/assets/responsive/...``,
    so the renditions function, the local command and the projector agree on one layout and the page URLs
    (``/<base path>/assets/responsive/...``) resolve to the objects.
    """

    def __new__(cls, store: "RenditionStore", base_path: str):
        base_path = base_path.strip("/")
        if not base_path:
            return store
        return super().__new__(cls)

    def __init__(self, store: "RenditionStore", base_path: str) -> None:
        self._store = store
        self.prefix = f"{base_path.strip('/')}/"

    def get(self, key: str) -> bytes | None:
        return self._store.get(self.prefix + key)

    def put(self, key: str, body: bytes, *, cache_control: str) -> None:
        self._store.put(self.prefix + key, body, cache_control=cache_control)

    def keys(self, prefix: str) -> list[str]:
        return [key[len(self.prefix):] for key in self._store.keys(self.prefix + prefix)]


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

    def keys(self, prefix: str) -> list[str]:
        base = self._root / prefix
        return sorted(path.relative_to(self._root).as_posix() for path in base.rglob("*") if path.is_file()) if base.is_dir() else []


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

    def keys(self, prefix: str) -> list[str]:
        found: list[str] = []
        token = None
        while True:
            arguments = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                arguments["ContinuationToken"] = token
            page = self._s3.list_objects_v2(**arguments)
            found.extend(entry["Key"] for entry in page.get("Contents", []))
            if not page.get("IsTruncated"):
                return sorted(found)
            token = page.get("NextContinuationToken")


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


def make_directory_renditions(settings: RenditionSettings, store: RenditionStore, content_directory: Path, *, originals: bool = False) -> list[str]:
    """Renditions (and, with ``media.originals``, the originals) of every image under a content directory, for a local projection.

    The cloud makes these when an image is uploaded to ``media/<srcPath>``; a content directory holds the same files at
    ``<srcPath>`` (``papyrus ops content export-published`` puts them there), so the source of each is its path relative to
    the directory. A set whose description already matches the file is left as it is. Returns the sources made.
    """
    made: list[str] = []
    root = Path(content_directory)
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part.startswith(".") for part in relative.parts):
            continue
        source = source_from_media_key(MEDIA_KEY_PREFIX + relative.as_posix())
        if source is None:
            continue
        data = path.read_bytes()
        if originals:
            store.put(source, data, cache_control=ORIGINAL_CACHE_CONTROL)
        existing = store.get(meta_key(settings.pipeline, source))
        if existing is not None and json.loads(existing).get("sourceSha256") == hashlib.sha256(data).hexdigest():
            continue
        make_renditions(settings, store, source, data)
        made.append(source)
    return made


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

    def all_records(self, *, workers: int = 8) -> list[dict]:
        """Every record in the store, by source path: the images a site has, without a list kept in the repository."""
        keys = [key for key in self._store.keys(f"{self._pipeline.out_subdir}/") if key.endswith(META_SUFFIX)]
        if not keys:
            return []
        with ThreadPoolExecutor(max_workers=min(workers, len(keys))) as executor:
            raw = list(executor.map(self._store.get, keys))
        records = [json.loads(body) for body in raw if body is not None]
        for record in records:
            self._records[record["source"]] = record
        return sorted(records, key=lambda record: record["source"])

    def record(self, source: str) -> dict:
        if source not in self._records:
            self._records[source] = self._load(source)
        record = self._records[source]
        if record is None:
            raise MissingRenditionsError(
                f"Renditions for image {source!r} are missing: "
                f"{getattr(self._store, 'prefix', '')}{meta_key(self._pipeline, source)} is not in the site store. "
                f"They are made when the image is uploaded to {media_key_for_source(source)}, so that object has to exist. "
                f"Request them with: papyrus ops content renditions --source {source} "
                "(signed in, no AWS login is needed; if there is no object at that key it says so, and where the object is and which command moves it)"
            )
        return record


def _rendition_from_data(data: dict) -> Rendition:
    return Rendition(width=data["width"], height=data["height"], href=data["href"], fmt=data["format"])


class StoredRenditionImageBuilder(ImageBuilder):
    """An ``ImageBuilder`` that reads stored renditions instead of opening and encoding images."""

    def __init__(self, pipeline: ImagePipeline, catalog: RenditionCatalog, *, url_root: str | None = None) -> None:
        super().__init__(pipeline, content_dir=Path("."), out_dir=Path("."), url_root=url_root)
        self._catalog = catalog

    def _locate(self, src: str) -> Path | None:
        self._catalog.record(src)
        return Path(src)

    def _source_size(self, src: str, path: Path) -> tuple[int, int] | None:
        size = self._catalog.record(src)["size"]
        return tuple(size) if size else None

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
