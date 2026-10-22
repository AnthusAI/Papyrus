"""A bulk projection refuses deletions that look like a wrong site configuration and writes nothing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from papyrus_content.projection.engine import (
    DeletionGuard,
    DeletionRefused,
    ProjectionContext,
    project_all,
    reconcile,
)
from papyrus_content.projection.item_state import ItemState, read_item_state, write_item_state
from papyrus_content.projection.source import PublishedContentSource
from papyrus_content.publishing import unpublish_item
from procedures.newsroom.tests.incremental_site import ACTOR, NOW, Site, seeded_site
from procedures.newsroom.tests.projection_fixtures import tree_digests


class DroppingProjector:
    """Delegates to a projector, except that it places nothing for the named items, as a site configuration without their section does."""

    def __init__(self, inner, dropped: set[str]) -> None:
        self._inner = inner
        self._dropped = dropped

    def item_page_paths(self, summary):
        return () if summary.item_id in self._dropped else self._inner.item_page_paths(summary)

    def item_pages(self, item, site):
        return {} if item.summary.item_id in self._dropped else self._inner.item_pages(item, site)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def context_for(site: Site, *, projector=None, guard: DeletionGuard | None = DeletionGuard()) -> ProjectionContext:
    return ProjectionContext(
        source=PublishedContentSource(site.client),
        projector=projector or site.projector,
        writer=site.store,
        redirect_store=site.redirects,
        deletion_guard=guard,
    )


class ProjectAllGuardTests(unittest.TestCase):
    def test_a_published_item_the_projector_stops_placing_refuses_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("generic", Path(temporary))
            before = tree_digests(Path(temporary) / "incremental")
            operations = len(site.store.operations)
            context = context_for(site, projector=DroppingProjector(site.projector, {"item-1"}))
            with self.assertRaises(DeletionRefused) as raised:
                project_all(context)
            message = str(raised.exception)
            self.assertIn("articles/seed-1.html", message)
            self.assertIn("item-1", message)
            self.assertIn("articles/ 1", message)
            self.assertIn("--allow-deletions", message)
            self.assertIn("current checkout", message)
            self.assertEqual(raised.exception.dropped_items, ("item-1",))
            self.assertEqual(tree_digests(Path(temporary) / "incremental"), before)
            self.assertEqual(len(site.store.operations), operations)

    def test_the_same_projection_without_a_guard_deletes_the_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("generic", Path(temporary))
            context = context_for(site, projector=DroppingProjector(site.projector, {"item-1"}), guard=None)
            report = project_all(context)
            self.assertIn("articles/seed-1.html", report.deleted)

    def test_a_large_share_of_the_pages_refuses_even_when_every_item_keeps_a_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("generic", Path(temporary))
            state = read_item_state(site.store, "item-0")
            stray = tuple(f"articles/stray-{number}.html" for number in range(30))
            for key in stray:
                site.store.put(key, b"<html></html>")
            write_item_state(site.store, ItemState(summary=state.summary, page_keys=(*state.page_keys, *stray)))
            before = tree_digests(Path(temporary) / "incremental")
            with self.assertRaises(DeletionRefused) as raised:
                project_all(context_for(site))
            self.assertEqual(raised.exception.dropped_items, ())
            self.assertEqual(len(raised.exception.keys), 30)
            self.assertEqual(tree_digests(Path(temporary) / "incremental"), before)

    def test_a_small_deletion_for_an_item_that_keeps_its_pages_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("generic", Path(temporary))
            unpublish_item(site.client, "item-1", actor=ACTOR, now=NOW)
            site.drafts["item-1"].slug = "renamed-one"
            site.publish("item-1")
            report = project_all(context_for(site))
            self.assertIn("articles/seed-1.html", report.deleted)
            self.assertIn("articles/renamed-one.html", report.written)

    def test_the_message_lists_at_most_twenty_items_and_fifty_keys(self) -> None:
        refusal = DeletionRefused(
            [f"wiki/page-{number:03d}.html" for number in range(564)], [f"item-{number:03d}" for number in range(282)], 600
        )
        message = str(refusal)
        self.assertIn("Refusing to delete 564 of 600", message)
        self.assertIn("wiki/ 564", message)
        self.assertIn("and 262 more", message)
        self.assertIn("and 514 more", message)
        self.assertIn("item-019", message)
        self.assertNotIn("item-020", message)
        self.assertIn("wiki/page-049.html", message)
        self.assertNotIn("wiki/page-050.html", message)


class ReconcileGuardTests(unittest.TestCase):
    def test_a_reconcile_that_would_delete_a_dropped_items_pages_refuses_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("generic", Path(temporary))
            before = tree_digests(Path(temporary) / "incremental")
            operations = len(site.store.operations)
            context = context_for(site, projector=DroppingProjector(site.projector, {"item-1"}))
            with self.assertRaises(DeletionRefused) as raised:
                reconcile(context)
            self.assertEqual(raised.exception.dropped_items, ("item-1",))
            self.assertIn("articles/seed-1.html", raised.exception.keys)
            self.assertEqual(tree_digests(Path(temporary) / "incremental"), before)
            self.assertEqual(len(site.store.operations), operations)

    def test_a_dry_run_reports_without_refusing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("generic", Path(temporary))
            context = context_for(site, projector=DroppingProjector(site.projector, {"item-1"}))
            report = reconcile(context, dry_run=True)
            self.assertIn("articles/seed-1.html", report.orphan_pages)

    def test_without_a_guard_the_reconcile_deletes_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("generic", Path(temporary))
            context = context_for(site, projector=DroppingProjector(site.projector, {"item-1"}), guard=None)
            report = reconcile(context)
            self.assertIn("articles/seed-1.html", report.orphan_pages)
            self.assertNotIn("articles/seed-1.html", tree_digests(Path(temporary) / "incremental"))

    def test_unpublishing_one_item_still_reconciles_on_a_small_site(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("generic", Path(temporary))
            unpublish_item(site.client, "item-2", actor=ACTOR, now=NOW)
            report = reconcile(context_for(site))
            self.assertEqual(report.removed_items, ["item-2"])
            self.assertNotIn("articles/seed-2.html", tree_digests(Path(temporary) / "incremental"))
            self.assertIn("articles/seed-1.html", tree_digests(Path(temporary) / "incremental"))


if __name__ == "__main__":
    unittest.main()
