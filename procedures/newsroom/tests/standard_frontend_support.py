"""Helpers for the standard front end tests: publish a fixture tree, project it, read the result."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import yaml

from papyrus_content.env import PAPYRUS_ROOT
from papyrus_content.projection.engine import ProjectionContext, project_all
from papyrus_content.projection.source import PublishedContentSource
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from papyrus_content.projection.writers import LocalDirectoryWriter
from papyrus_content.publishing import ItemFields, publish_item, save_item
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from procedures.newsroom.tests.projection_fixtures import ACTOR, NOW, RecordingWriter, tree_digests

FIXTURES = PAPYRUS_ROOT / "features_backend" / "fixtures" / "standard-site"
PRODUCTION = {"PAPYRUS_SITE_PUBLIC_URL": ""}


class FakeRedirects:
    def __init__(self) -> None:
        self.mapping: dict[str, str] = {}

    def put_all(self, redirects):
        self.mapping.update(redirects)

    def delete_all(self, sources):
        for source in sources:
            self.mapping.pop(source, None)

    def list_all(self):
        return dict(self.mapping)

    def get(self, source):
        return self.mapping.get(source)


def split_front_matter(text: str) -> tuple[dict, str, str | None]:
    if not text.startswith("---\n"):
        return {}, text, None
    end = text.index("\n---\n", 3)
    raw = text[4:end] + "\n"
    return yaml.safe_load(raw) or {}, text[end + 5 :], raw


def fields_for(content_root: Path, path: Path) -> ItemFields:
    relative = path.relative_to(content_root)
    section = relative.parts[0] if len(relative.parts) > 1 else None
    data, body, raw = split_front_matter(path.read_text(encoding="utf-8"))
    item_type = str(data.pop("type", "article"))
    aliases = [str(alias) for alias in data.pop("aliases", [])]
    front_matter_yaml = yaml.safe_dump(data, sort_keys=False, allow_unicode=True) if data else None
    return ItemFields(
        type=item_type,
        slug=path.stem,
        section=section,
        front_matter_yaml=front_matter_yaml,
        body_markus=body,
        aliases=aliases,
        id=f"item-{(section + '-') if section else ''}{path.stem}",
        source_path=relative.as_posix(),
    )


def publish_tree(client, content_root: Path) -> list[str]:
    ids = []
    for path in sorted(content_root.rglob("*.md")):
        fields = fields_for(content_root, path)
        save_item(client, fields, actor=ACTOR, now=NOW)
        publish_item(client, fields.id, actor=ACTOR, now=NOW)
        ids.append(fields.id)
    return ids


def static_directory(work: Path, settings: dict, extra_files: dict[str, str | bytes] | None = None) -> Path:
    directory = work / "static"
    (directory / "css").mkdir(parents=True, exist_ok=True)
    (directory / "css" / "site-theme.css").write_text("/* theme */\n", encoding="utf-8")
    (directory / "projection.json").write_text(json.dumps(settings), encoding="utf-8")
    for name, content in (extra_files or {}).items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return directory


def fixture_settings(name: str) -> dict:
    return json.loads((FIXTURES / name / "projection.json").read_text(encoding="utf-8"))


class ProjectedSite:
    """A fixture published into a fake CMS and projected by the standard front end into a local directory."""

    def __init__(self, name: str | None = None, *, settings: dict | None = None, environ: dict | None = None, extra_files=None, content: Path | None = None, seed: dict[str, bytes] | None = None, plugins: tuple[str, ...] = ()) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="standard-frontend-"))
        self.settings = settings if settings is not None else fixture_settings(name)
        self.content_root = content or (FIXTURES / name / "content")
        self.client = FakeAuthoringClient()
        self.environ = {"PAPYRUS_SITE_PUBLIC_URL": "", **(environ or {})}
        self.static = static_directory(self.work, self.settings, extra_files)
        self.projector = StandardMarkusProjector.from_static_directory(self.static, environ=self.environ, plugins=plugins)
        self.redirects = FakeRedirects()
        self.ids = publish_tree(self.client, self.content_root)
        self.out = self.work / "out"
        for key, body in (seed or {}).items():
            (self.out / key).parent.mkdir(parents=True, exist_ok=True)
            (self.out / key).write_bytes(body)
        self.writer = RecordingWriter(self.out)
        self.context = ProjectionContext(
            source=PublishedContentSource(self.client), projector=self.projector, writer=self.writer, redirect_store=self.redirects
        )
        self.report = project_all(self.context)
        assert self.report.ok, self.report.errors

    def cleanup(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    @property
    def tree(self) -> dict[str, bytes]:
        return {path.relative_to(self.out).as_posix(): path.read_bytes() for path in sorted(self.out.rglob("*")) if path.is_file()}

    def text(self, key: str) -> str:
        return (self.out / key).read_text(encoding="utf-8")

    def digests(self) -> dict[str, str]:
        return tree_digests(self.out)


# ------------------------------------------------------------------ feed validation

def validate_rss(data: bytes) -> list[str]:
    """Structural RSS 2.0 validation (the rules feedparser and the W3C validator enforce that matter here); returns problems."""
    from email.utils import parsedate_to_datetime
    from xml.etree import ElementTree

    problems: list[str] = []
    root = ElementTree.fromstring(data)
    if root.tag != "rss" or root.get("version") != "2.0":
        return ["root is not <rss version=2.0>"]
    channel = root.find("channel")
    if channel is None:
        return ["no <channel>"]
    for name in ("title", "link", "description"):
        if channel.find(name) is None or not (channel.findtext(name) or "").strip():
            problems.append(f"channel missing {name}")
    seen = set()
    for item in channel.findall("item"):
        if item.find("title") is None and item.find("description") is None:
            problems.append("item needs title or description")
        guid = item.findtext("guid")
        if guid in seen:
            problems.append(f"duplicate guid {guid}")
        seen.add(guid)
        if not (item.findtext("link") or "").startswith("http"):
            problems.append("item link is not absolute")
        pub = item.findtext("pubDate")
        if pub:
            try:
                if parsedate_to_datetime(pub).tzinfo is None:
                    problems.append(f"pubDate without zone: {pub}")
            except (TypeError, ValueError):
                problems.append(f"bad RFC 822 date: {pub}")
    return problems


def validate_atom(data: bytes) -> list[str]:
    """Structural Atom 1.0 validation (RFC 4287 section 4.1); returns problems."""
    import datetime as dt
    from xml.etree import ElementTree

    ns = "{http://www.w3.org/2005/Atom}"
    problems: list[str] = []
    root = ElementTree.fromstring(data)
    if root.tag != ns + "feed":
        return ["root is not atom:feed"]
    for name in ("id", "title", "updated"):
        if root.find(ns + name) is None:
            problems.append(f"feed missing {name}")
    feed_author = root.find(ns + "author") is not None
    if not any(link.get("rel") == "self" for link in root.findall(ns + "link")):
        problems.append("feed has no rel=self link")
    seen = set()
    for entry in root.findall(ns + "entry"):
        for name in ("id", "title", "updated"):
            if entry.find(ns + name) is None:
                problems.append(f"entry missing {name}")
        if not feed_author and entry.find(ns + "author") is None:
            problems.append("entry has no author and the feed has none")
        entry_id = entry.findtext(ns + "id")
        if entry_id in seen:
            problems.append(f"duplicate id {entry_id}")
        seen.add(entry_id)
        for name in ("updated", "published"):
            value = entry.findtext(ns + name)
            if value:
                try:
                    dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    problems.append(f"bad RFC 3339 {name}: {value}")
    return problems


def edit_item(site: "ProjectedSite", item_id: str, *, title: str | None = None, body: str | None = None, front_matter: dict | None = None):
    """Re-save and re-publish one fixture item with a changed title or body, then project it; returns the report."""
    import dataclasses

    from papyrus_content.projection.engine import project

    path = next(p for p in site.content_root.rglob("*.md") if fields_for(site.content_root, p).id == item_id)
    fields = fields_for(site.content_root, path)
    if title is not None or front_matter:
        data = yaml.safe_load(fields.front_matter_yaml or "") or {}
        if title is not None:
            data["title"] = title
        data.update(front_matter or {})
        fields = dataclasses.replace(fields, front_matter_yaml=yaml.safe_dump(data, sort_keys=False))
    if body is not None:
        fields = dataclasses.replace(fields, body_markus=body)
    save_item(site.client, fields, actor=ACTOR, now=NOW)
    publish_item(site.client, item_id, actor=ACTOR, now=NOW)
    site.writer.operations.clear()
    return project(site.context, item_id)


def written_keys(site: "ProjectedSite") -> set[str]:
    return {key for kind, key in site.writer.operations if kind == "put"}
