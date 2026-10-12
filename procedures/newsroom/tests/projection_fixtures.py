"""Shared fixtures for the projection tests: the fixture site, a full-build reference and recording stores."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from papyrus_content.env import PAPYRUS_ROOT
from papyrus_content.markus_renderer import CitationRendering, build_markus_site
from papyrus_content.projection.engine import ProjectionContext
from papyrus_content.projection.projector import MarkusProjectorSettings, MarkusSiteProjector, read_static_files
from papyrus_content.projection.source import PublishedContentSource
from papyrus_content.projection.writers import LocalDirectoryWriter
from papyrus_content.publishing import ItemFields, publish_item, save_item

FIXTURE_ROOT = PAPYRUS_ROOT / "features_backend" / "fixtures" / "projection-site"
FIXTURE_SECTIONS = ("notes",)
ACTOR = "projection-tests"
NOW = "2026-10-12T12:00:00Z"


def split_front_matter(text: str) -> tuple[str | None, str]:
    if text.startswith("---\n"):
        end = text.index("\n---\n", 3)
        return text[4:end] + "\n", text[end + 5 :]
    return None, text


def item_fields_for(content_root: Path, path: Path) -> ItemFields:
    relative = path.relative_to(content_root)
    section = relative.parts[0] if len(relative.parts) > 1 else None
    front_matter_yaml, body = split_front_matter(path.read_text(encoding="utf-8"))
    return ItemFields(
        type="page" if section is None else "article",
        slug=path.stem,
        section=section,
        front_matter_yaml=front_matter_yaml,
        body_markus=body,
        aliases=[],
        id=f"item-{section or 'root'}-{path.stem}",
        source_path=relative.as_posix(),
    )


def markdown_files(content_root: Path) -> list[Path]:
    return sorted(content_root.rglob("*.md"))


def save_and_publish(client, fields: ItemFields) -> str:
    save_item(client, fields, actor=ACTOR, now=NOW)
    publish_item(client, fields.id, actor=ACTOR, now=NOW)
    return fields.id


def publish_content_tree(client, content_root: Path) -> list[str]:
    return [save_and_publish(client, item_fields_for(content_root, path)) for path in markdown_files(content_root)]


def copy_fixture_content(destination: Path, *, with_home_page: bool = True) -> Path:
    content_root = destination / "content"
    shutil.copytree(FIXTURE_ROOT / "content", content_root)
    if not with_home_page:
        (content_root / "index.md").unlink()
    return content_root


def static_directory_for(content_root: Path, destination: Path) -> Path:
    static_directory = destination / "static"
    (static_directory / "css").mkdir(parents=True)
    shutil.copy(FIXTURE_ROOT / "css" / "site-theme.css", static_directory / "css" / "site-theme.css")
    shutil.copytree(content_root / "assets", static_directory / "assets")
    return static_directory


def fixture_projector(static_directory: Path) -> MarkusSiteProjector:
    settings = MarkusProjectorSettings(sections=FIXTURE_SECTIONS, citations=True)
    return MarkusSiteProjector(settings, read_static_files(static_directory, settings.theme))


def full_build(content_root: Path, out_directory: Path) -> None:
    build_markus_site(
        content_dir=content_root,
        out_dir=out_directory,
        site_css=FIXTURE_ROOT / "css" / "site-theme.css",
        sections=FIXTURE_SECTIONS,
        citations=CitationRendering(),
    )


def tree_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class RecordingWriter:
    """Writes to a local directory and remembers the order of operations."""

    def __init__(self, root: Path) -> None:
        self._inner = LocalDirectoryWriter(root)
        self.operations: list[tuple[str, str]] = []
        self.versions: dict[str, int | None] = {}

    def put(self, key: str, body: bytes, *, version: int | None = None) -> None:
        self._inner.put(key, body, version=version)
        self.operations.append(("put", key))
        self.versions[key] = version

    def delete(self, key: str) -> None:
        self._inner.delete(key)
        self.operations.append(("delete", key))


class WorkDirectory:
    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="projection-tests-"))

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def local_context(client, projector, root: Path) -> tuple[ProjectionContext, RecordingWriter]:
    writer = RecordingWriter(root)
    return ProjectionContext(source=PublishedContentSource(client), projector=projector, writer=writer), writer
