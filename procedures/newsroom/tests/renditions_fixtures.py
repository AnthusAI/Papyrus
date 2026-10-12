"""Fixtures for the rendition tests: generated images, a pictured article, a fake media store and function client."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
from pathlib import Path

from PIL import Image

from papyrus_content.env import PAPYRUS_ROOT
from papyrus_content.markus_renderer import CitationRendering, build_markus_site
from papyrus_content.markus_renderer.images import ImagePipeline
from papyrus_content.projection.projector import MarkusProjectorSettings, MarkusSiteProjector, read_static_files
from papyrus_content.renditions import settings_from_mapping

from .projection_fixtures import FIXTURE_ROOT, FIXTURE_SECTIONS

HANDLER_PATH = PAPYRUS_ROOT / "amplify" / "functions" / "renditions" / "handler.py"
GATSBY_IMAGE_SETTINGS = {"gatsby_parity": True, "placeholder": None, "eager_first": 1000, "listing_max_width": 600}
LEGACY_IMAGE_SETTINGS = {"listing_max_width": 600}
WIDE_IMAGE_PATH = "images/wide.jpg"
SMALL_IMAGE_PATH = "images/small.png"
DIAGRAM_IMAGE_PATH = "images/diagram.svg"
NOTE_MEDIA_KEY = "media/notes/readme.txt"
PICTURED_ARTICLE = """---
title: Pictured
date: 2026-10-01
---

An article with pictures.

::image{src="images/wide.jpg" alt="A wide gradient" layout="full" caption="Wide"}

Some text between the pictures.

::image{src="images/small.png" alt="A small badge"}

::image{src="images/diagram.svg" alt="A diagram"}
"""
DIAGRAM_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"><rect width="120" height="80" fill="#336"/></svg>\n'


def gradient_image(width: int, height: int, *, transparent: bool) -> Image.Image:
    image = Image.new("RGBA" if transparent else "RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            color = ((x * 255) // width, (y * 255) // height, ((x + y) * 255) // (width + height))
            if transparent:
                pixels[x, y] = (*color, 255 if x > width // 4 else 40)
            else:
                pixels[x, y] = color
    return image


def encoded(image: Image.Image, image_format: str) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def fixture_media() -> dict[str, bytes]:
    return {
        WIDE_IMAGE_PATH: encoded(gradient_image(1400, 700, transparent=False), "JPEG"),
        SMALL_IMAGE_PATH: encoded(gradient_image(300, 200, transparent=True), "PNG"),
        DIAGRAM_IMAGE_PATH: DIAGRAM_SVG.encode("utf-8"),
    }


def write_pictured_content(content_root: Path, media: dict[str, bytes]) -> None:
    (content_root / "articles" / "pictured.md").write_text(PICTURED_ARTICLE, encoding="utf-8")
    for source, data in media.items():
        target = content_root / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def full_build_with_images(content_root: Path, out_directory: Path, image_settings: dict) -> None:
    pipeline = settings_from_mapping(image_settings).pipeline
    build_markus_site(
        content_dir=content_root,
        out_dir=out_directory,
        site_css=FIXTURE_ROOT / "css" / "site-theme.css",
        sections=FIXTURE_SECTIONS,
        citations=CitationRendering(),
        images=pipeline,
    )


def projector_with_images(static_directory: Path, image_settings: dict, store) -> MarkusSiteProjector:
    settings = MarkusProjectorSettings(
        sections=FIXTURE_SECTIONS, citations=True, images=settings_from_mapping(image_settings)
    )
    return MarkusSiteProjector(settings, read_static_files(static_directory, settings.theme), renditions=store)


def write_projection_settings(static_directory: Path, image_settings: dict) -> None:
    (static_directory / "projection.json").write_text(json.dumps({"images": image_settings}), encoding="utf-8")


def rendition_files(root: Path) -> dict[str, bytes]:
    base = root / "assets" / "responsive"
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(base.rglob("*"))
        if path.is_file() and not path.name.endswith(".meta.json")
    }


def load_renditions_handler():
    specification = importlib.util.spec_from_file_location("renditions_handler_under_test", HANDLER_PATH)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class FakeMediaBucket:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)

    def get_object(self, Bucket: str, Key: str) -> dict:
        return {"Body": io.BytesIO(self.objects[Key])}

    def get_paginator(self, name: str):
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket: str, Prefix: str):
                yield {"Contents": [{"Key": key} for key in sorted(objects) if key.startswith(Prefix)]}

        return Paginator()


class FakeFunctionClient:
    """Invokes the renditions handler in process, as the Lambda service would."""

    def __init__(self, handler_module) -> None:
        self._handler = handler_module
        self.invocations = 0

    def invoke(self, FunctionName: str, InvocationType: str, Payload: bytes) -> dict:
        self.invocations += 1
        result = self._handler.handler(json.loads(Payload), None)
        return {"Payload": io.BytesIO(json.dumps(result).encode("utf-8"))}


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
