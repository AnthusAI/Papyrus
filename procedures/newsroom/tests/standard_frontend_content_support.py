"""Helpers for the collection, include and hook tests of the standard front end: build a content tree, project it, read the cards."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

import yaml

from papyrus_content.projection.directory_source import DirectoryContentSource
from papyrus_content.projection.engine import ProjectionContext, project_all
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from papyrus_content.projection.writers import LocalDirectoryWriter
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite, static_directory

SITE = {"name": "Example", "productionUrl": "https://example.org", "description": "An example."}
CARD_LINK = re.compile(r'<h2 class="markus-card-title"><a href="([^"]+)">')
FEATURED = re.compile(r'<div class="markus-featured">(.*?)</div><div class="markus-card-grid">', re.S)


def settings(**extra) -> dict:
    return {"site": dict(SITE), **extra}


def item(slug: str, *, section: str | None = "posts", body: str | None = None, **front) -> tuple[str, dict, str]:
    """``(relative path, front matter, body)`` of one content item; ``title`` defaults to the slug in capitals."""
    front.setdefault("title", slug.upper())
    path = f"{section}/{slug}.md" if section else f"{slug}.md"
    return path, front, body if body is not None else f"Body of {slug}.\n"


def write_items(root: Path, items) -> Path:
    for path, front, body in items:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n" + body, encoding="utf-8")
    return root


def cms_site(settings_: dict, items, files: dict[str, str] | None = None, *, environ: dict | None = None) -> ProjectedSite:
    """The items published into a fake CMS and projected; the caller cleans up."""
    scratch = Path(tempfile.mkdtemp(prefix="std-content-"))
    try:
        site = ProjectedSite(settings=settings_, content=write_items(scratch / "content", items), extra_files=files, environ=environ)
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    site.scratch = scratch
    original = site.cleanup
    site.cleanup = lambda: (original(), shutil.rmtree(scratch, ignore_errors=True))[0]
    return site


class DirectorySite:
    """Items read from a directory (the CMS save path would reject some of the syntax tested here)."""

    def __init__(self, settings_: dict, items, files: dict[str, str] | None = None, *, environ: dict | None = None) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="std-dir-"))
        self.content = write_items(self.work / "content", items)
        self.static = static_directory(self.work, settings_, files)
        self.out = self.work / "out"
        self.environ = {"PAPYRUS_SITE_PUBLIC_URL": "", **(environ or {})}

    def project_all(self):
        projector = StandardMarkusProjector.from_static_directory(self.static, environ=self.environ)
        context = ProjectionContext(source=DirectoryContentSource(self.content), projector=projector, writer=LocalDirectoryWriter(self.out))
        return project_all(context)

    def text(self, key: str) -> str:
        return (self.out / key).read_text(encoding="utf-8")

    def keys(self) -> set[str]:
        return {path.relative_to(self.out).as_posix() for path in self.out.rglob("*") if path.is_file()}

    def cleanup(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)


def slug_of(href: str) -> str:
    """``/posts/n01.html`` and ``/posts/n01/`` are both ``n01``."""
    path = PurePosixPath(href.split("?")[0])
    return path.stem if path.suffix else path.name


def cards(page: str) -> list[str]:
    """The slugs of every card of a page, in document order (featured first)."""
    return [slug_of(href) for href in CARD_LINK.findall(page)]


def featured(page: str) -> list[str]:
    found = FEATURED.search(page)
    return [slug_of(href) for href in CARD_LINK.findall(found.group(1))] if found else []


def title_of(page: str) -> str:
    return re.search(r"<title>(.*?)</title>", page, re.S).group(1)


def html_written(keys) -> set[str]:
    return {key for key in keys if key.endswith(".html")}
