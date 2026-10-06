"""Export CMS content as a Markus build input directory (PPY-1d0f3d)."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .markus_renderer.derive import compose_source
from .markus_import import MediaStore
from .publishing import utc_now_iso

EXPORT_CONTRACT = "papyrus-export/v1"
EXPORTED_TYPES = ("article", "page")
SIDE_FILES_DIR = "_papyrus"


class ExportError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class EmptyExportError(ExportError):
    pass


@dataclass
class ExportReport:
    mode: str
    out_dir: Path
    items: list[dict] = field(default_factory=list)
    media: list[dict] = field(default_factory=list)
    mediaDownloaded: int = 0
    mediaSkipped: int = 0
    redirects: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "mode": self.mode,
            "outDir": str(self.out_dir),
            "items": len(self.items),
            "media": len(self.media),
            "mediaDownloaded": self.mediaDownloaded,
            "mediaSkipped": self.mediaSkipped,
            "redirects": len(self.redirects),
        }


def _parse_metadata(row: dict) -> dict:
    value = row.get("metadata")
    if isinstance(value, str):
        value = json.loads(value) if value.strip() else {}
    return value if isinstance(value, dict) else {}


def _validate_relative_path(path: str, label: str, *, markdown: bool) -> None:
    posix = PurePosixPath(path)
    if not path or posix.is_absolute() or path.startswith(("/", "\\")):
        raise ValueError(f"{label} {path!r} must be relative")
    if ".." in posix.parts:
        raise ValueError(f"{label} {path!r} must not contain '..'")
    if markdown and posix.suffix != ".md":
        raise ValueError(f"{label} {path!r} must end in .md")


def item_output_path(item: dict) -> str:
    section = item.get("section") or None
    slug = item["slug"]
    source_path = (_parse_metadata(item).get("source") or {}).get("path")
    if source_path:
        _validate_relative_path(source_path, "source path", markdown=True)
        parts = PurePosixPath(source_path).parts
        if (section and parts[0] == section) or (not section and len(parts) == 1):
            return source_path
    path = f"{section}/{slug}.md" if section else f"{slug}.md"
    _validate_relative_path(path, "output path", markdown=True)
    return path


def canonical_url_path(item: dict) -> str:
    section = item.get("section") or None
    return f"/{section}/{item['slug']}.html" if section else f"/{item['slug']}.html"


def _source_rows(client, drafts: bool) -> list[dict]:
    model = "Item" if drafts else "PublishedItem"
    rows = [row for row in client.list_records(model) if row.get("type") in EXPORTED_TYPES]
    if not drafts:
        rows = [row for row in rows if row.get("status") == "published"]
    return rows


def _media_rows(client, item: dict, drafts: bool) -> list[dict]:
    if drafts:
        return client.list_by_index("mediaAssetsByItemAndSortKey", item["id"])
    return client.list_by_index("publishedMediaAssetsByItemAndSortKey", item["id"])


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _guard_clean_target(out_dir: Path) -> None:
    resolved = out_dir.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise ExportError([f"Refusing to clean {resolved}"])
    if (resolved / ".git").exists():
        raise ExportError([f"Refusing to clean {resolved}: it contains .git"])


def _plan_items(rows: list[dict]) -> list[tuple[str, dict]]:
    planned: list[tuple[str, dict]] = []
    errors: list[str] = []
    owners: dict[str, dict] = {}
    for row in rows:
        try:
            path = item_output_path(row)
        except ValueError as error:
            errors.append(f"{row.get('id')}: {error}")
            continue
        if path in owners:
            errors.append(f"Duplicate output path {path}: {owners[path].get('id')} and {row.get('id')}")
            continue
        owners[path] = row
        planned.append((path, row))
    if errors:
        raise ExportError(errors)
    return sorted(planned, key=lambda entry: entry[0])


def _content_hash(row: dict, drafts: bool) -> str | None:
    if drafts:
        return row.get("contentHash")
    return _parse_metadata(row).get("sourceContentHash")


def export_content(
    client,
    store: MediaStore,
    out_dir: Path,
    *,
    drafts: bool,
    clean: bool = False,
    allow_empty: bool = False,
    site: str | None = None,
    now: str | None = None,
) -> ExportReport:
    out_dir = Path(out_dir)
    mode = "drafts" if drafts else "published"
    planned = _plan_items(_source_rows(client, drafts))
    if not planned and not allow_empty:
        raise EmptyExportError([f"no items to export in {mode} mode"])

    media_by_item = {row["id"]: _media_rows(client, row, drafts) for _, row in planned}

    if clean:
        _guard_clean_target(out_dir)
        if out_dir.exists():
            shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    report = ExportReport(mode=mode, out_dir=out_dir)
    for path, row in planned:
        target = out_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        text = compose_source(_parse_metadata(row).get("frontMatterYaml"), row.get("bodyMarkus") or "")
        target.write_text(text, encoding="utf-8", newline="")
        report.items.append(
            {
                "id": row["id"],
                "slug": row["slug"],
                "section": row.get("section"),
                "path": path,
                "status": row.get("status"),
                "versionNumber": row.get("versionNumber"),
                "contentHash": _content_hash(row, drafts),
            }
        )
        for alias in row.get("aliases") or []:
            report.redirects.append({"from": alias, "to": canonical_url_path(row), "status": 301})

    seen_media: set[str] = set()
    for _, row in planned:
        for media in media_by_item[row["id"]]:
            metadata = _parse_metadata(media)
            src_path = metadata.get("srcPath")
            storage_path = media.get("storagePath")
            if not src_path or not storage_path or src_path in seen_media:
                continue
            _validate_relative_path(src_path, "media srcPath", markdown=False)
            seen_media.add(src_path)
            dest = out_dir / src_path
            expected = metadata.get("sha256")
            if expected and dest.is_file() and _sha256_of(dest) == expected:
                report.mediaSkipped += 1
            else:
                store.get(storage_path, dest)
                report.mediaDownloaded += 1
            report.media.append({"srcPath": src_path, "storagePath": storage_path, "sha256": expected})
    report.media.sort(key=lambda entry: entry["srcPath"])

    side_dir = out_dir / SIDE_FILES_DIR
    side_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "contract": EXPORT_CONTRACT,
        "mode": mode,
        "generatedAt": now or utc_now_iso(),
        "site": site,
        "items": report.items,
        "media": report.media,
    }
    (side_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (side_dir / "redirects.json").write_text(json.dumps(report.redirects, indent=2) + "\n", encoding="utf-8")
    return report
