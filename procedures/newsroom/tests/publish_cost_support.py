"""A standard-front-end site with N published stories, for the tests of what one publish costs (PPY-3acc8d).

The client is the in-memory fake, which records every call: a ``get`` is one AppSync request, a ``list`` of the published summaries is one
pass over them (one request per 1,000 rows against AppSync). The site writes ``llms-full.txt``, the page that needs every Story's text.
"""

from __future__ import annotations

import collections
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from papyrus_content.projection.engine import ProjectionContext, project, project_all
from papyrus_content.projection.source import PublishedContentSource
from papyrus_content.projection.standard.projector import StandardMarkusProjector
from papyrus_content.publishing import ItemFields, publish_item, save_item
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from procedures.newsroom.tests.projection_fixtures import RecordingWriter
from procedures.newsroom.tests.standard_frontend_support import FakeRedirects, static_directory

ORIGIN = "https://cost.example.org"
SECTIONS = ("notes", "essays", "reviews")
SETTINGS = {
    "site": {"name": "Cost", "description": "A site for counting requests.", "productionUrl": ORIGIN},
    "urls": {"style": "directory", "sections": {name: {"label": name.title()} for name in SECTIONS}},
    "listings": {"pageSize": 20},
    "agents": {"llmsFullMaxItems": 5000, "llmsFullMaxBytes": 50_000_000},
}
ENVIRON = {"PAPYRUS_SITE_PUBLIC_URL": ORIGIN}
BODY = "\n\n".join(f"Paragraph {number} about the subject of this story." for number in range(4))


def story_fields(number: int) -> ItemFields:
    section = SECTIONS[number % len(SECTIONS)]
    front_matter = f"title: Story {number}\ndate: 2026-10-{1 + number % 28:02d}\nsummary: The summary of story {number}.\n"
    return ItemFields(type="article", slug=f"story-{number}", section=section, front_matter_yaml=front_matter, body_markus=f"{BODY}\n", aliases=[], id=f"story-{number}")


def publish(client, fields: ItemFields, now: str) -> None:
    with mock.patch("papyrus_content.story_checklist.require_checklist_closed"), mock.patch("papyrus_content.story_checklist.mark_published"):
        save_item(client, fields, actor="cost-tests", now=now)
        publish_item(client, fields.id, actor="cost-tests", now=now)


class CostSite:
    """``stories`` published and projected once, as the deploy render leaves a site; then each :meth:`publish_one` is a fresh invocation."""

    def __init__(self, stories: int, *, writer_factory=None, every_page_reads_every_story: bool = False) -> None:
        """``every_page_reads_every_story``: a hooks module declaring ``DEPENDS_ON = ["*"]``, as a site whose hooks read the whole site does
        (Machines on Machines): every listing page is rendered again on every publish, and most of them come out byte for byte the same."""
        self.work = Path(tempfile.mkdtemp(prefix="publish-cost-"))
        self.client = FakeAuthoringClient()
        for number in range(stories):
            publish(self.client, story_fields(number), "2026-11-01T00:00:00Z")
        settings = {**SETTINGS, "hooks": "hooks.py"} if every_page_reads_every_story else SETTINGS
        extra = {"hooks.py": 'DEPENDS_ON = ["*"]\n'} if every_page_reads_every_story else None
        self.static = static_directory(self.work, settings, extra)
        self.projector = StandardMarkusProjector.from_static_directory(self.static, environ=ENVIRON)
        self.writer = writer_factory(self.work / "out") if writer_factory else RecordingWriter(self.work / "out")
        self.redirects = FakeRedirects()
        self.next_number = stories
        report = project_all(self.context())
        assert report.ok, report.errors

    def context(self) -> ProjectionContext:
        """A new source each time, as each Lambda invocation has: nothing read by an earlier projection is remembered in memory."""
        context = ProjectionContext(source=PublishedContentSource(self.client), projector=self.projector, writer=self.writer, redirect_store=self.redirects)
        context.defer_follow_up = True   # as in the function: the item-pages follow-up is its own task
        return context

    def follow_up(self, except_item_id: str | None = None):
        """The item-pages follow-up as its own invocation. Returns (report, calls by kind)."""
        from papyrus_content.projection.engine import project_item_pages

        self.client.calls.clear()
        report = project_item_pages(self.context(), except_item_id=except_item_id)
        return report, collections.Counter(f"{operation}:{model}" for operation, model, _ in self.client.calls)

    def publish_one(self):
        """Publish one more story, then project it as the function does. Returns (report, calls by kind, the projection's own calls)."""
        fields = story_fields(self.next_number)
        self.next_number += 1
        publish(self.client, fields, "2026-11-08T00:00:00Z")
        self.client.calls.clear()
        report = project(self.context(), fields.id)
        calls = list(self.client.calls)
        return report, collections.Counter(f"{operation}:{model}" for operation, model, _ in calls), calls

    def cleanup(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)


#: The one read of the site's settings a projection makes: its languages (docs/multilingual-serving.md). Counted on its own, never per Story.
SETTINGS_READ = "get:EditorialCheckSettings"


def point_reads(counted: collections.Counter) -> int:
    """Records read one by one, the site's settings aside (:func:`settings_reads`)."""
    return sum(count for key, count in counted.items() if key.startswith("get:") and key != SETTINGS_READ)


def settings_reads(counted: collections.Counter) -> int:
    return counted.get(SETTINGS_READ, 0)


def summary_passes(counted: collections.Counter) -> int:
    return counted.get("list:PublishedItemSummary", 0)


def whole_table_reads(counted: collections.Counter) -> int:
    return sum(count for key, count in counted.items() if key.startswith("list:") and key != "list:PublishedItemSummary")
