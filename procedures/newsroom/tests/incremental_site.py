"""A tiny CMS next to an incrementally maintained site store, for the projection tests."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from papyrus_content.projection.engine import ProjectionContext, project, project_all
from papyrus_content.projection.projector import (
    DEFAULT_THEME,
    MarkusProjectorSettings,
    MarkusSiteProjector,
    read_static_files,
)
from papyrus_content.projection.public_data import PublicDataSettings
from papyrus_content.projection.item_state import ITEM_STATE_PREFIX
from papyrus_content.projection.source import PublishedContentSource
from papyrus_content.publishing import ItemFields, publish_item, save_item, unpublish_item
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from procedures.newsroom.tests.feed_projector import FeedSiteProjector
from procedures.newsroom.tests.projection_fixtures import ACTOR, NOW, RecordingWriter, tree_digests

SLUGS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet"]
SECTIONS = ["articles", "notes"]
OPERATION_NAMES = ("publish", "retitle", "retag-date", "edit-body", "unpublish", "rename", "alias", "hide")


class FakeRedirectStore:
    def __init__(self) -> None:
        self.mapping: dict[str, str] = {}

    def put_all(self, redirects: dict[str, str]) -> None:
        self.mapping.update(redirects)

    def delete_all(self, sources: list[str]) -> None:
        for source in sources:
            self.mapping.pop(source, None)

    def list_all(self) -> dict[str, str]:
        return dict(self.mapping)

    def get(self, source: str) -> str | None:
        return self.mapping.get(source)


@dataclass
class Draft:
    slug: str
    section: str
    title: str
    date: str
    description: str
    body: str
    aliases: list[str] = field(default_factory=list)
    hidden: bool = False

    def fields(self, item_id: str) -> ItemFields:
        feed = "feed: false\n" if self.hidden else ""
        return ItemFields(
            type="article",
            slug=self.slug,
            section=self.section,
            front_matter_yaml=f"title: {self.title}\ndate: '{self.date}'\ndescription: {self.description}\ntags: [month-{self.date[5:7]}, {self.slug}]\n{feed}",
            body_markus=self.body,
            aliases=list(self.aliases),
            id=item_id,
        )


def make_projector(kind: str):
    public_data = PublicDataSettings(latest_count=4, summary_characters=40) if kind == "public" else None
    settings = MarkusProjectorSettings(theme=DEFAULT_THEME, sections=("notes",), public_data=public_data)
    files = read_static_files(None, DEFAULT_THEME)
    return FeedSiteProjector(settings, files) if kind == "feed" else MarkusSiteProjector(settings, files)


class Site:
    """An incrementally maintained store next to the data it projects."""

    def __init__(self, kind: str, work: Path) -> None:
        self.kind = kind
        self.work = work
        self.client = FakeAuthoringClient()
        self.projector = make_projector(kind)
        self.store = RecordingWriter(work / "incremental")
        self.redirects = FakeRedirectStore()
        self.context = ProjectionContext(
            source=PublishedContentSource(self.client), projector=self.projector, writer=self.store, redirect_store=self.redirects
        )
        project_all(self.context)
        self.drafts: dict[str, Draft] = {}
        self.published: set[str] = set()
        self.generation = 0
        self.touched: set[str] = set()
        self.reports: list = []

    def full(self) -> tuple[dict[str, str], dict[str, str]]:
        self.generation += 1
        store = RecordingWriter(self.work / f"full-{self.generation}")
        redirects = FakeRedirectStore()
        context = ProjectionContext(
            source=PublishedContentSource(self.client), projector=self.projector, writer=store, redirect_store=redirects
        )
        project_all(context)
        return tree_digests(self.work / f"full-{self.generation}"), redirects.mapping

    def full_with_remembered_moves(self) -> dict[str, str]:
        """What a full projection writes when it reads the item states the incremental runs left."""
        self.generation += 1
        copied = RecordingWriter(self.work / f"full-{self.generation}")
        for entry in self.store.list(ITEM_STATE_PREFIX):
            copied.put(entry.key, self.store.get(entry.key))
        redirects = FakeRedirectStore()
        context = ProjectionContext(
            source=PublishedContentSource(self.client), projector=self.projector, writer=copied, redirect_store=redirects
        )
        project_all(context)
        return redirects.mapping

    def incremental(self) -> tuple[dict[str, str], dict[str, str]]:
        return tree_digests(self.work / "incremental"), dict(self.redirects.mapping)

    def save(self, item_id: str) -> None:
        save_item(self.client, self.drafts[item_id].fields(item_id), actor=ACTOR, now=NOW)

    def publish(self, item_id: str) -> None:
        self.save(item_id)
        publish_item(self.client, item_id, actor=ACTOR, now=NOW)
        self.published.add(item_id)

    def project_item(self, item_id: str):
        report = project(self.context, item_id)
        self.touched |= set(report.written) | set(report.deleted)
        self.reports.append(report)
        return report


def new_draft(rng: random.Random, taken: set[tuple[str, str]], item_number: int) -> tuple[str, Draft] | None:
    candidates = [(section, slug) for section in SECTIONS for slug in SLUGS if (section, slug) not in taken]
    if not candidates:
        return None
    section, slug = rng.choice(candidates)
    day = rng.randint(1, 28)
    draft = Draft(
        slug=slug,
        section=section,
        title=f"Title {slug} {rng.randint(0, 99)}",
        date=f"2026-{rng.randint(1, 12):02d}-{day:02d}",
        description=f"About {slug} {rng.randint(0, 99)}",
        body=f"Body of {slug} {rng.randint(0, 99)}.\n",
    )
    return f"item-{item_number}", draft


def apply_operation(site: Site, rng: random.Random) -> tuple[str, str]:
    taken = {(draft.section, draft.slug) for draft in site.drafts.values()}
    published = sorted(site.published)
    unpublished = sorted(set(site.drafts) - site.published)
    choices = ["publish"] if not published else list(OPERATION_NAMES)
    name = rng.choice(choices)
    if name == "publish":
        if unpublished and rng.random() < 0.5:
            item_id = rng.choice(unpublished)
        else:
            created = new_draft(rng, taken, len(site.drafts) + 1)
            if created is None:
                item_id = rng.choice(unpublished or published)
            else:
                item_id, draft = created
                site.drafts[item_id] = draft
        site.publish(item_id)
        return "publish", item_id
    item_id = rng.choice(published)
    draft = site.drafts[item_id]
    if name == "retitle":
        draft.title = f"Retitled {rng.randint(100, 999)}"
        site.publish(item_id)
    elif name == "retag-date":
        draft.date = f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        draft.description = f"Changed {rng.randint(100, 999)}"
        site.publish(item_id)
    elif name == "edit-body":
        draft.body = f"Edited body {rng.randint(100, 999)}.\n"
        site.publish(item_id)
    elif name == "hide":
        draft.hidden = not draft.hidden
        site.publish(item_id)
    elif name == "alias":
        draft.aliases = [f"old/{item_id}-{rng.randint(0, 9)}"]
        site.publish(item_id)
    elif name == "unpublish":
        unpublish_item(site.client, item_id, actor=ACTOR, now=NOW)
        site.published.discard(item_id)
    elif name == "rename":
        unpublish_item(site.client, item_id, actor=ACTOR, now=NOW)
        site.published.discard(item_id)
        site.project_item(item_id)
        free = [slug for slug in SLUGS if (draft.section, slug) not in taken]
        if not free:
            return "unpublish", item_id
        draft.slug = rng.choice(free)
        site.publish(item_id)
    return name, item_id




def add_item(site: Site, item_id: str, slug: str, *, section: str = "articles", date: str = "2026-03-01") -> None:
    site.drafts[item_id] = Draft(
        slug=slug, section=section, title=f"Title of {slug}", date=date, description=f"About {slug}", body=f"Body of {slug}.\n"
    )
    site.publish(item_id)


def seeded_site(kind: str, work: Path, count: int = 3) -> Site:
    site = Site(kind, work)
    for number in range(count):
        add_item(site, f"item-{number}", f"seed-{number}", date=f"2026-01-{number + 1:02d}")
        site.project_item(f"item-{number}")
    return site


class HookedSource(PublishedContentSource):
    """Runs a callback right after one of the reads, as another publish committing in the middle of a projection."""

    def __init__(self, client, hooks: dict[int, object]) -> None:
        super().__init__(client)
        self.reads = 0
        self.hooks = hooks

    def site_index(self):
        site = super().site_index()
        self.reads += 1
        hook = self.hooks.get(self.reads)
        if hook is not None:
            hook()
        return site


class FailingWriter:
    """Delegates to a writer and raises on the Nth write or delete."""

    def __init__(self, inner, fail_at: int) -> None:
        self._inner = inner
        self._fail_at = fail_at
        self.count = 0

    def _tick(self) -> None:
        self.count += 1
        if self.count == self._fail_at:
            raise RuntimeError("injected write failure")

    def put(self, key, body, **kwargs):
        if not key.startswith("_papyrus/"):
            self._tick()
        return self._inner.put(key, body, **kwargs)

    def delete(self, key):
        if not key.startswith("_papyrus/"):
            self._tick()
        return self._inner.delete(key)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class SlowWriter:
    def __init__(self, inner, seed: int) -> None:
        self._inner = inner
        self._random = random.Random(seed)
        self._lock = threading.Lock()

    def _pause(self) -> None:
        with self._lock:
            delay = self._random.random() * 0.004
        time.sleep(delay)

    def put(self, key, body, **kwargs):
        self._pause()
        return self._inner.put(key, body, **kwargs)

    def delete(self, key):
        self._pause()
        return self._inner.delete(key)

    def __getattr__(self, name):
        return getattr(self._inner, name)
