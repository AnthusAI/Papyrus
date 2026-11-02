"""A story with images, projected locally and through the cloud path, for the base-path image tests and scenarios.

The story uses the paths the editor stores: ``assets/draft-unsectioned-<hash>/<file>``. Locally those files sit in the content
directory (where ``export-published`` puts them); in the cloud they are the media objects ``media/<the same path>``.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from papyrus_content.project_commands import content_project
from papyrus_content.projection.directory_source import DirectoryContentSource
from papyrus_content.projection.engine import ProjectionContext, project_all
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from papyrus_content.projection.writers import LocalDirectoryWriter
from papyrus_content.renditions import DirectoryRenditionStore

from .renditions_fixtures import FakeMediaBucket, load_renditions_handler

FOLDER = "assets/draft-unsectioned-a1b2c3d4"
CHART = f"{FOLDER}/chart.png"
CHART_DARK = f"{FOLDER}/chart.dark.png"
LONE = f"{FOLDER}/lone.png"
PHOTO = f"{FOLDER}/photo.png"
PICTURES = {CHART: (800, 400), CHART_DARK: (800, 400), LONE: (300, 200), PHOTO: (600, 300)}
STORY = f"""---
title: Hello
date: '2026-10-01'
description: A first article.
---

::image{{src="{CHART}" srcDark="{CHART_DARK}" alt="A chart" caption="The chart"}}

Some words between the pictures.

::image{{src="{LONE}" alt="A lone picture"}}

![A photo]({PHOTO})
"""
IMAGE_SETTINGS = {"formats": ["webp"], "widths": [200, 400]}


def picture(size: tuple[int, int], shade: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (shade, 90, 200 - shade)).save(buffer, format="PNG")
    return buffer.getvalue()


def pictures() -> dict[str, bytes]:
    return {source: picture(size, 40 + 30 * index) for index, (source, size) in enumerate(PICTURES.items())}


def settings(base_path: str | None) -> dict:
    urls: dict = {"style": "directory"}
    if base_path:
        urls["basePath"] = base_path
    return {
        "site": {"name": "Example", "productionUrl": "https://example.com"},
        "urls": urls,
        "images": dict(IMAGE_SETTINGS),
        "media": {"originals": True},
    }


class BasedImageSite:
    """One working directory: content with its pictures, a static directory, and the outputs of the two ways to project it."""

    def __init__(self, base_path: str | None) -> None:
        self.base_path = base_path
        self.work = Path(tempfile.mkdtemp(prefix="based-images-"))
        self.content = self.work / "content"
        self.static = self.work / "web"
        self.out = self.work / "out"
        self.site_store = self.work / "site-store"
        self.cloud_out = self.work / "cloud-out"
        self.pictures = pictures()
        self.content.mkdir()
        (self.content / "hello.md").write_text(STORY, encoding="utf-8")
        for source, data in self.pictures.items():
            (self.content / source).parent.mkdir(parents=True, exist_ok=True)
            (self.content / source).write_bytes(data)
        (self.static / "css").mkdir(parents=True)
        (self.static / "css" / "site-theme.css").write_text("/* theme */\n", encoding="utf-8")
        self.write_settings(settings(base_path))
        self.handler = None
        self.media = FakeMediaBucket({})
        self.error: Exception | None = None

    def write_settings(self, raw: dict) -> None:
        (self.static / "projection.json").write_text(json.dumps(raw), encoding="utf-8")

    def cleanup(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    # ------------------------------------------------------------------ the local command

    def project_locally(self) -> None:
        previous = os.environ.get("PAPYRUS_SITE_PUBLIC_URL")
        os.environ["PAPYRUS_SITE_PUBLIC_URL"] = ""
        try:
            content_project(["--all", "--from-dir", str(self.content), "--static-dir", str(self.static), "--out", str(self.out)])
        finally:
            if previous is None:
                os.environ.pop("PAPYRUS_SITE_PUBLIC_URL", None)
            else:
                os.environ["PAPYRUS_SITE_PUBLIC_URL"] = previous

    # ------------------------------------------------------------------ the cloud path

    def configure_function(self) -> None:
        """The renditions function reading this site's projection.json, writing to a directory standing in for the site bucket."""
        os.environ["PAPYRUS_SITE_STATIC_DIR"] = str(self.static)
        self.handler = load_renditions_handler()
        self.handler._loaded["store"] = DirectoryRenditionStore(self.site_store)
        self.handler._loaded["s3"] = self.media

    def release_function(self) -> None:
        os.environ.pop("PAPYRUS_SITE_STATIC_DIR", None)

    def upload(self, key: str, data: bytes | None = None) -> dict:
        self.media.objects[key] = data if data is not None else self.pictures[key.removeprefix("media/")]
        event = {"source": "aws.s3", "detail-type": "Object Created", "detail": {"bucket": {"name": "media"}, "object": {"key": key}}}
        return self.handler.handler(event, None)

    def upload_all(self) -> None:
        for source in self.pictures:
            self.upload(f"media/{source}")

    def render_from_store(self) -> None:
        """The content-actions render: the projector reads the renditions from the site store."""
        self.error = None
        try:
            projector = StandardMarkusProjector.from_static_directory(
                self.static, renditions=DirectoryRenditionStore(self.site_store), environ={"PAPYRUS_SITE_PUBLIC_URL": ""}
            )
            context = ProjectionContext(source=DirectoryContentSource(self.content), projector=projector, writer=LocalDirectoryWriter(self.cloud_out), keep_state=False)
            report = project_all(context)
            if not report.ok:
                raise RuntimeError("; ".join(str(error) for error in report.errors))
        except Exception as error:  # noqa: BLE001 - the scenario asserts on the message
            self.error = error


def tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def pages(root: Path) -> dict[str, bytes]:
    """The projected pages and Markdown twins: what a render of the story produces apart from the image files."""
    return {key: body for key, body in tree(root).items() if key.endswith((".html", ".md", ".xml", ".txt")) or "/_data/" in key}
