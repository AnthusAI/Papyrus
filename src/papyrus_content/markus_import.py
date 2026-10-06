"""Import a directory of Markus files into the CMS (PPY-22a3b4).

Front matter and body are stored verbatim on an ``Item``; images referenced by
the content become ``MediaAsset`` rows plus S3 objects. The import validates
every file before writing anything, is idempotent, never overwrites an item
that was edited in the CMS (unless forced), and never deletes or unpublishes.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .markus_renderer.build import slugify
from .markus_renderer.content_markup import split_front_matter
from .markus_renderer.derive import derive_body
from .publishing import (
    ItemFields,
    PublishError,
    _load_front_matter,
    _parse_json_object,
    _source_content_hash,
    item_id_for,
    publish_item,
    save_item,
)
from .record_helpers import to_aws_json

IMPORT_ACTOR = "papyrus-import"
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg")
SKIPPED_DIRECTORY_NAMES = {"assets", "node_modules", ".git"}
IMAGE_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".svg": "image/svg+xml",
}
_EXTENSION_PATTERN = "|".join(re.escape(extension) for extension in IMAGE_EXTENSIONS)
BODY_IMAGE_PATH_RE = re.compile(
    r"""(?:src\s*=\s*|poster\s*=\s*|\]\(\s*)["']?([^"'()\s}]+(?:%s))(?=["')\s}]|$)""" % _EXTENSION_PATTERN,
    re.IGNORECASE,
)


@dataclass
class ImportOptions:
    content_dir: Path
    article_dirs: tuple[str, ...] = ("articles",)
    draft_dirs: dict[str, str] = field(default_factory=dict)
    aliases_file: Path | None = None
    publish: bool = True
    force: bool = False
    image_source_dir: Path | None = None


class MediaStore(Protocol):
    def put(self, storage_path: str, local_path: Path, *, content_type: str, sha256: str) -> str: ...

    def get(self, storage_path: str, dest: Path) -> None: ...

    def has(self, storage_path: str, sha256: str) -> bool: ...


class S3MediaStore:
    def __init__(self, bucket: str) -> None:
        try:
            import boto3
        except ImportError as error:
            raise RuntimeError("boto3 is required for S3 media: install papyrus-newsroom[newsroom].") from error
        self.bucket = bucket
        self._client = boto3.client("s3")

    def _stored_sha256(self, storage_path: str) -> str | None:
        from botocore.exceptions import ClientError

        try:
            head = self._client.head_object(Bucket=self.bucket, Key=storage_path)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        return (head.get("Metadata") or {}).get("sha256")

    def has(self, storage_path: str, sha256: str) -> bool:
        return self._stored_sha256(storage_path) == sha256

    def put(self, storage_path: str, local_path: Path, *, content_type: str, sha256: str) -> str:
        if self.has(storage_path, sha256):
            return "unchanged"
        self._client.put_object(
            Bucket=self.bucket,
            Key=storage_path,
            Body=local_path.read_bytes(),
            ContentType=content_type,
            Metadata={"sha256": sha256},
        )
        return "uploaded"

    def get(self, storage_path: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self.bucket, storage_path, str(dest))


class DirMediaStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, storage_path: str) -> Path:
        return self.root / storage_path

    def has(self, storage_path: str, sha256: str) -> bool:
        target = self._path(storage_path)
        return target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == sha256

    def put(self, storage_path: str, local_path: Path, *, content_type: str, sha256: str) -> str:
        if self.has(storage_path, sha256):
            return "unchanged"
        target = self._path(storage_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(local_path.read_bytes())
        return "uploaded"

    def get(self, storage_path: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self._path(storage_path).read_bytes())


class AbsentMediaStore:
    """Dry-run stand-in when no bucket is configured: every media object counts as new."""

    def has(self, storage_path: str, sha256: str) -> bool:
        return False

    def put(self, storage_path: str, local_path: Path, *, content_type: str, sha256: str) -> str:
        raise RuntimeError("No media store is configured; pass --bucket.")

    def get(self, storage_path: str, dest: Path) -> None:
        raise RuntimeError("No media store is configured; pass --bucket.")


@dataclass
class SourceFile:
    path: Path
    relative_path: str
    section: str | None
    slug: str
    item_type: str
    status: str
    front_matter_yaml: str
    body_markus: str

    @property
    def item_id(self) -> str:
        return item_id_for(self.section, self.slug)

    @property
    def canonical_path(self) -> str:
        return f"/{self.section}/{self.slug}.html" if self.section else f"/{self.slug}.html"


@dataclass
class PlannedMedia:
    source_path: str
    local_path: Path
    row: dict
    sha256: str
    content_type: str
    storage_path: str


@dataclass
class PlannedItem:
    source: SourceFile
    fields: ItemFields
    content_hash: str
    media: list[PlannedMedia]
    action: str
    existing: dict | None = None
    media_changed: bool = False
    needs_publish: bool = False


@dataclass
class ImportPlan:
    items: list[PlannedItem]
    errors: list[str]
    reader_owned_assets: int
    not_in_source: list[str]
    options: ImportOptions


@dataclass
class ImportReport:
    ok: bool
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_edited_in_cms: list[str] = field(default_factory=list)
    published: int = 0
    media_uploaded: int = 0
    media_unchanged: int = 0
    reader_owned_assets: int = 0
    not_in_source: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "dryRun": self.dry_run,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skippedEditedInCms": len(self.skipped_edited_in_cms),
            "skippedEditedInCmsIds": list(self.skipped_edited_in_cms),
            "published": self.published,
            "mediaUploaded": self.media_uploaded,
            "mediaUnchanged": self.media_unchanged,
            "readerOwnedAssets": self.reader_owned_assets,
            "notInSource": self.not_in_source,
            "errors": list(self.errors),
        }


def _is_skipped_name(name: str) -> bool:
    return name.startswith("_") or name.startswith(".")


def discover(options: ImportOptions) -> list[SourceFile]:
    root = Path(options.content_dir)
    sources: list[SourceFile] = []
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = sorted(
            name for name in subdirectories if not _is_skipped_name(name) and name not in SKIPPED_DIRECTORY_NAMES
        )
        relative_directory = Path(directory).relative_to(root).as_posix()
        relative_directory = "" if relative_directory == "." else relative_directory
        draft_section = options.draft_dirs.get(relative_directory) if relative_directory else None
        section = draft_section if draft_section is not None else (relative_directory or None)
        for filename in sorted(filenames):
            if _is_skipped_name(filename) or not filename.endswith(".md"):
                continue
            path = Path(directory) / filename
            front_matter_yaml, body_markus = split_front_matter(path.read_text(encoding="utf-8"))
            sources.append(
                SourceFile(
                    path=path,
                    relative_path=path.relative_to(root).as_posix(),
                    section=section,
                    slug=slugify(Path(filename).stem),
                    item_type="article" if section in options.article_dirs else "page",
                    status="draft" if draft_section is not None else "published",
                    front_matter_yaml=front_matter_yaml.lstrip("\n"),
                    body_markus=body_markus,
                )
            )
    return sources


def _front_matter_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for entry in value.values() for text in _front_matter_strings(entry)]
    if isinstance(value, list):
        return [text for entry in value for text in _front_matter_strings(entry)]
    return []


def _is_local_image_reference(reference: str) -> bool:
    lowered = reference.lower()
    if lowered.startswith(("http://", "https://", "data:", "//", "/")):
        return False
    return lowered.endswith(IMAGE_EXTENSIONS)


def referenced_image_paths(front_matter_yaml: str, body_markus: str) -> tuple[list[str], list[str]]:
    """Return ``(front_matter_paths, body_paths)`` in order of first appearance."""
    try:
        front_matter = _load_front_matter(front_matter_yaml)
    except Exception:
        front_matter = {}
    cover_paths: list[str] = []
    for text in _front_matter_strings(front_matter):
        candidate = text.strip()
        if _is_local_image_reference(candidate) and candidate not in cover_paths:
            cover_paths.append(candidate)
    body_paths: list[str] = []
    for match in BODY_IMAGE_PATH_RE.finditer(body_markus):
        candidate = match.group(1)
        if _is_local_image_reference(candidate) and candidate not in body_paths and candidate not in cover_paths:
            body_paths.append(candidate)
    return cover_paths, body_paths


def _image_dimensions(local_path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(local_path) as image:
            return image.width, image.height
    except Exception:
        return None


def _resolve_image(image_root: Path, source_path: str) -> Path | None:
    root = image_root.resolve()
    candidate = (root / source_path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def _plan_media(
    source: SourceFile, item_id: str, image_root: Path, errors: list[str], envelope_sources: list[str]
) -> list[PlannedMedia]:
    cover_paths, body_paths = referenced_image_paths(source.front_matter_yaml, source.body_markus)
    ordered = [(path, "cover") for path in cover_paths] + [(path, "body") for path in body_paths]
    known = {path for path, _ in ordered}
    for envelope_source in envelope_sources:
        if envelope_source not in known:
            ordered.append((envelope_source, "body"))
            known.add(envelope_source)
    planned: list[PlannedMedia] = []
    for source_path, role in ordered:
        local_path = _resolve_image(image_root, source_path)
        if local_path is None:
            if source_path in envelope_sources:
                errors.append(f"{source.relative_path}: image-missing: {source_path} not found under {image_root}")
            continue
        content = local_path.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()
        content_type = IMAGE_CONTENT_TYPES.get(
            local_path.suffix.lower(), mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        )
        row = {
            "id": f"media-{item_id}-{hashlib.sha256(source_path.encode('utf-8')).hexdigest()[:10]}",
            "itemId": item_id,
            "type": "image",
            "role": role,
            "sortKey": f"{len(planned) + 1:03d}#{source_path}",
            "storagePath": f"media/{source_path}",
            "alt": Path(source_path).name,
            "metadata": to_aws_json(
                {"srcPath": source_path, "sha256": sha256, "bytes": len(content), "contentType": content_type}
            ),
        }
        dimensions = _image_dimensions(local_path)
        if dimensions is not None:
            row["width"], row["height"] = dimensions
        planned.append(PlannedMedia(source_path, local_path, row, sha256, content_type, row["storagePath"]))
    return planned


def _load_aliases_file(path: Path | None) -> dict[str, list[str]]:
    if path is None:
        return {}
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("The aliases file must be a JSON object of {key: [paths]}.")
    return {str(key): list(value) for key, value in loaded.items()}


def _front_matter_aliases(front_matter_yaml: str) -> list[str]:
    try:
        value = _load_front_matter(front_matter_yaml).get("aliases")
    except Exception:
        return []
    if isinstance(value, str):
        return [value]
    return [str(entry) for entry in value] if isinstance(value, list) else []


def _validate_aliases(sources: list[SourceFile], by_source: dict[str, list[str]], errors: list[str]) -> None:
    canonical = {source.canonical_path: source.relative_path for source in sources}
    claimed: dict[str, str] = {}
    for source in sources:
        for alias in by_source[source.relative_path]:
            if not alias.startswith("/"):
                errors.append(f"{source.relative_path}: alias {alias!r} must start with /")
            elif alias in canonical:
                errors.append(f"{source.relative_path}: alias {alias} shadows the page {canonical[alias]}")
            elif alias in claimed:
                errors.append(f"{source.relative_path}: alias {alias} is already used by {claimed[alias]}")
            else:
                claimed[alias] = source.relative_path


def _content_hash_for_plan(fields: ItemFields) -> str:
    return _source_content_hash(fields)


def _imported_hash(existing: dict) -> str | None:
    return (_parse_json_object(existing.get("metadata")).get("source") or {}).get("importedContentHash")


def _media_differs(client, item_id: str, planned: list[PlannedMedia]) -> bool:
    existing = {row["id"]: row for row in client.list_by_index("mediaAssetsByItemAndSortKey", item_id)}
    wanted = {entry.row["id"]: entry.row for entry in planned}
    if set(existing) != set(wanted):
        return True
    return any(
        any(existing[row_id].get(name) != value for name, value in row.items()) for row_id, row in wanted.items()
    )


def plan_import(options: ImportOptions, client, store: MediaStore) -> ImportPlan:
    errors: list[str] = []
    sources = discover(options)
    image_root = Path(options.image_source_dir or options.content_dir)

    seen: dict[str, SourceFile] = {}
    for source in sources:
        if not source.slug:
            errors.append(f"{source.relative_path}: the file name produces an empty slug")
            continue
        earlier = seen.get(source.item_id)
        if earlier is not None:
            errors.append(
                f"slug collision: {earlier.relative_path} and {source.relative_path} both become {source.item_id}"
            )
        else:
            seen[source.item_id] = source

    try:
        aliases_by_key = _load_aliases_file(options.aliases_file)
    except (OSError, ValueError) as error:
        errors.append(f"aliases file: {error}")
        aliases_by_key = {}
    keys_in_use: set[str] = set()
    aliases_by_source: dict[str, list[str]] = {}
    for source in sources:
        key = f"{source.section}/{source.slug}" if source.section else source.slug
        keys_in_use.add(key)
        combined = _front_matter_aliases(source.front_matter_yaml)
        for alias in aliases_by_key.get(key, []):
            if alias not in combined:
                combined.append(alias)
        aliases_by_source[source.relative_path] = combined
    for key in aliases_by_key:
        if key not in keys_in_use:
            errors.append(f"aliases file: key {key!r} matches no imported file")
    _validate_aliases(sources, aliases_by_source, errors)

    planned_items: list[PlannedItem] = []
    for source in sources:
        if not source.slug or seen.get(source.item_id) is not source:
            continue
        derivation = derive_body(source.front_matter_yaml, source.body_markus)
        if not derivation.ok:
            for body_error in derivation.errors:
                errors.append(f"{source.relative_path}: {body_error.code}: {body_error.message}")
            continue
        envelope_sources = [
            image.get("src")
            for image in derivation.body_ir["papyrus"]["images"].values()
            if image.get("src") and not str(image["src"]).startswith(("http://", "https://"))
        ]
        fields = ItemFields(
            type=source.item_type,
            slug=source.slug,
            section=source.section,
            front_matter_yaml=source.front_matter_yaml,
            body_markus=source.body_markus,
            aliases=aliases_by_source[source.relative_path],
            id=source.item_id,
            source_path=source.relative_path,
        )
        media = _plan_media(source, source.item_id, image_root, errors, envelope_sources)
        planned_items.append(
            PlannedItem(source, fields, _content_hash_for_plan(fields), media, action="create")
        )

    not_in_source: list[str] = []
    if not errors:
        for planned in planned_items:
            _classify(planned, options, client)
        wanted_ids = {planned.source.item_id for planned in planned_items}
        for row in client.list_records("Item"):
            if row.get("type") in ("article", "page") and row.get("id") not in wanted_ids:
                not_in_source.append(row["id"])

    return ImportPlan(planned_items, errors, _count_reader_owned_assets(options.content_dir, planned_items), not_in_source, options)


def _classify(planned: PlannedItem, options: ImportOptions, client) -> None:
    existing = client.get_record("Item", planned.source.item_id)
    planned.existing = existing
    desired_published = planned.source.status == "published" and options.publish
    if existing is None:
        planned.action = "create"
        planned.needs_publish = desired_published
        planned.media_changed = bool(planned.media)
        return
    planned.media_changed = _media_differs(client, planned.source.item_id, planned.media)
    needs_publish = desired_published and existing.get("status") != "published"
    if existing.get("contentHash") == planned.content_hash:
        planned.needs_publish = needs_publish
        planned.action = "update" if (planned.media_changed or needs_publish) else "unchanged"
        return
    if existing.get("contentHash") != _imported_hash(existing) and not options.force:
        planned.action = "skip-edited"
        return
    planned.action = "update"
    planned.needs_publish = desired_published


def _count_reader_owned_assets(content_dir: Path, planned_items: list[PlannedItem]) -> int:
    assets_dir = Path(content_dir) / "assets"
    if not assets_dir.is_dir():
        return 0
    imported = {entry.local_path.resolve() for planned in planned_items for entry in planned.media}
    return sum(1 for path in assets_dir.rglob("*") if path.is_file() and path.resolve() not in imported)


def _unique_media(plan: ImportPlan) -> dict[str, PlannedMedia]:
    unique: dict[str, PlannedMedia] = {}
    for planned in plan.items:
        if planned.action == "skip-edited":
            continue
        for entry in planned.media:
            unique.setdefault(entry.storage_path, entry)
    return unique


def run_import(plan: ImportPlan, client, store: MediaStore, *, apply: bool) -> ImportReport:
    report = ImportReport(ok=not plan.errors, errors=list(plan.errors), dry_run=not apply)
    report.reader_owned_assets = plan.reader_owned_assets
    if plan.errors:
        return report
    report.not_in_source = len(plan.not_in_source)

    for storage_path, entry in _unique_media(plan).items():
        if apply:
            outcome = store.put(storage_path, entry.local_path, content_type=entry.content_type, sha256=entry.sha256)
        else:
            outcome = "unchanged" if store.has(storage_path, entry.sha256) else "uploaded"
        if outcome == "uploaded":
            report.media_uploaded += 1
        else:
            report.media_unchanged += 1

    for planned in plan.items:
        if planned.action == "skip-edited":
            report.skipped_edited_in_cms.append(planned.source.item_id)
            continue
        if planned.action == "unchanged":
            report.unchanged += 1
            continue
        if planned.action == "create":
            report.created += 1
        else:
            report.updated += 1
        if planned.needs_publish:
            report.published += 1
        if apply:
            _apply_item(planned, client)
    return report


def _apply_item(planned: PlannedItem, client) -> None:
    item_id = planned.source.item_id
    if planned.media_changed:
        wanted_ids = set()
        for entry in planned.media:
            client.upsert("MediaAsset", entry.row)
            wanted_ids.add(entry.row["id"])
        for row in client.list_by_index("mediaAssetsByItemAndSortKey", item_id):
            if row["id"] not in wanted_ids:
                client.delete_record("MediaAsset", row["id"])
    if planned.existing is None or planned.existing.get("contentHash") != planned.content_hash:
        record = save_item(client, planned.fields, actor=IMPORT_ACTOR, now=None)
        metadata = _parse_json_object(record.get("metadata"))
        metadata["source"] = {"path": planned.source.relative_path, "importedContentHash": planned.content_hash}
        client.update_record("Item", {"id": item_id, "metadata": to_aws_json(metadata)})
    if planned.needs_publish:
        try:
            publish_item(client, item_id, actor=IMPORT_ACTOR, now=None)
        except PublishError as error:
            raise RuntimeError(f"{planned.source.relative_path}: publish failed [{error.code}] {error.message}") from error
