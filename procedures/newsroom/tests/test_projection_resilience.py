"""Concurrent publishes converge; failed projections are retried; reconcile repairs drift."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from papyrus_content import cli
from papyrus_content.projection.writers import S3PageWriter, body_etag

from papyrus_content.projection.engine import ProjectionContext, project, reconcile
from papyrus_content.projection.source import PublishedContentSource
from papyrus_content.publishing import unpublish_item
from procedures.newsroom.tests.incremental_site import (
    ACTOR,
    NOW,
    FailingWriter,
    HookedSource,
    SlowWriter,
    Site,
    add_item,
    seeded_site,
)


def assert_equals_full(test: unittest.TestCase, site: Site, label: str = "") -> None:
    incremental_pages, incremental_redirects = site.incremental()
    full_pages, _full_redirects = site.full()
    test.assertEqual(incremental_pages, full_pages, label)
    test.assertEqual(incremental_redirects, site.full_with_remembered_moves(), label)


class ConcurrentPublishTests(unittest.TestCase):
    def test_a_publish_that_read_a_stale_listing_set_is_corrected_by_its_own_reread(self) -> None:
        for kind in ("generic", "feed"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                site = seeded_site(kind, Path(temporary))
                add_item(site, "item-a", "alpha-new", date="2026-02-01")

                def second_publish_runs_to_completion() -> None:
                    add_item(site, "item-b", "bravo-new", date="2026-02-02")
                    project(
                        ProjectionContext(
                            source=PublishedContentSource(site.client),
                            projector=site.projector,
                            writer=site.store,
                            redirect_store=site.redirects,
                        ),
                        "item-b",
                    )

                source = HookedSource(site.client, {1: second_publish_runs_to_completion})
                context = ProjectionContext(
                    source=source, projector=site.projector, writer=site.store, redirect_store=site.redirects
                )
                report = project(context, "item-a")
                self.assertTrue(report.ok, report.errors)
                self.assertGreaterEqual(report.rounds, 2)
                assert_equals_full(self, site, kind)
                pages, _ = site.incremental()
                self.assertIn("articles/alpha-new.html", pages)
                self.assertIn("articles/bravo-new.html", pages)

    def test_two_publishes_racing_on_the_same_store_converge_on_both_listings(self) -> None:
        for kind in ("generic", "feed"):
            for seed in range(12):
                with self.subTest(kind=kind, seed=seed), tempfile.TemporaryDirectory() as temporary:
                    site = seeded_site(kind, Path(temporary))
                    add_item(site, "item-a", "alpha-new", date="2026-02-01")
                    add_item(site, "item-b", "bravo-new", date="2026-02-02")
                    slow = SlowWriter(site.store, seed)
                    contexts = [
                        ProjectionContext(
                            source=PublishedContentSource(site.client),
                            projector=site.projector,
                            writer=slow,
                            redirect_store=site.redirects,
                        )
                        for _ in range(2)
                    ]
                    reports = []
                    threads = [
                        threading.Thread(target=lambda c=context, i=item_id: reports.append(project(c, i)))
                        for context, item_id in zip(contexts, ("item-a", "item-b"))
                    ]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()
                    self.assertTrue(all(report.ok for report in reports), [report.errors for report in reports])
                    assert_equals_full(self, site, f"{kind} {seed}")

    def test_a_publish_racing_an_edit_of_the_same_item_ends_on_the_latest_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("generic", Path(temporary))
            add_item(site, "item-a", "alpha-new")

            def edit_and_project_again() -> None:
                site.drafts["item-a"].title = "Edited while projecting"
                site.publish("item-a")

            context = ProjectionContext(
                source=HookedSource(site.client, {1: edit_and_project_again}),
                projector=site.projector,
                writer=site.store,
                redirect_store=site.redirects,
            )
            report = project(context, "item-a")
            self.assertTrue(report.ok, report.errors)
            assert_equals_full(self, site)
            page = (Path(temporary) / "incremental" / "articles" / "alpha-new.html").read_text(encoding="utf-8")
            self.assertIn("Edited while projecting", page)


class FailureAndRetryTests(unittest.TestCase):
    def test_a_failure_at_any_write_is_repaired_by_running_the_projection_again(self) -> None:
        for kind in ("generic", "feed"):
            with tempfile.TemporaryDirectory() as probe_directory:
                probe = seeded_site(kind, Path(probe_directory))
                probe.drafts["item-1"].title = "Retitled"
                probe.drafts["item-1"].date = "2026-05-05"
                probe.publish("item-1")
                writes = len(project(probe.context, "item-1").written)
            for fail_at in range(1, writes + 1):
                with self.subTest(kind=kind, fail_at=fail_at), tempfile.TemporaryDirectory() as temporary:
                    site = seeded_site(kind, Path(temporary))
                    site.drafts["item-1"].title = "Retitled"
                    site.drafts["item-1"].date = "2026-05-05"
                    site.publish("item-1")
                    failing = ProjectionContext(
                        source=PublishedContentSource(site.client),
                        projector=site.projector,
                        writer=FailingWriter(site.store, fail_at),
                        redirect_store=site.redirects,
                    )
                    with self.assertRaises(RuntimeError):
                        project(failing, "item-1")
                    retry = project(site.context, "item-1")
                    self.assertTrue(retry.ok, retry.errors)
                    assert_equals_full(self, site, f"{kind} fail_at={fail_at}")

    def test_a_unpublish_that_failed_midway_is_repaired_by_running_it_again(self) -> None:
        with tempfile.TemporaryDirectory() as probe_directory:
            probe = seeded_site("feed", Path(probe_directory))
            unpublish_item(probe.client, "item-1", actor=ACTOR, now=NOW)
            probe.published.discard("item-1")
            writes = len(project(probe.context, "item-1").written) + len(project(probe.context, "item-1").deleted) + 1
        for fail_at in range(1, writes + 1):
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as temporary:
                site = seeded_site("feed", Path(temporary))
                unpublish_item(site.client, "item-1", actor=ACTOR, now=NOW)
                site.published.discard("item-1")
                failing = ProjectionContext(
                    source=PublishedContentSource(site.client),
                    projector=site.projector,
                    writer=FailingWriter(site.store, fail_at),
                    redirect_store=site.redirects,
                )
                try:
                    project(failing, "item-1")
                except RuntimeError:
                    pass
                project(site.context, "item-1")
                assert_equals_full(self, site, f"fail_at={fail_at}")


class ReconcileTests(unittest.TestCase):
    def test_a_publish_whose_projection_never_ran_is_found_and_repaired(self) -> None:
        for kind in ("generic", "feed"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                site = seeded_site(kind, Path(temporary))
                add_item(site, "item-lost", "never-rendered", date="2026-04-04")
                site.drafts["item-1"].title = "Saved but not rendered"
                site.publish("item-1")
                preview = reconcile(site.context, dry_run=True)
                self.assertEqual(sorted(preview.stale_items), ["item-1", "item-lost"])
                self.assertTrue(preview.drift)
                before, _ = site.incremental()
                self.assertNotIn("articles/never-rendered.html", before)
                outcome = reconcile(site.context)
                self.assertTrue(outcome.ok, outcome.errors)
                assert_equals_full(self, site, kind)
                self.assertFalse(reconcile(site.context, dry_run=True).drift)

    def test_an_unpublish_whose_projection_never_ran_is_found_and_repaired(self) -> None:
        for kind in ("generic", "feed"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                site = seeded_site(kind, Path(temporary))
                unpublish_item(site.client, "item-2", actor=ACTOR, now=NOW)
                site.published.discard("item-2")
                preview = reconcile(site.context, dry_run=True)
                self.assertEqual(preview.removed_items, ["item-2"])
                reconcile(site.context)
                assert_equals_full(self, site, kind)
                pages, _ = site.incremental()
                self.assertNotIn("articles/seed-2.html", pages)

    def test_orphan_pages_stale_listings_and_lost_state_are_repaired(self) -> None:
        for kind in ("generic", "feed"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                site = seeded_site(kind, Path(temporary))
                site.store.put("articles/ghost.html", b"<p>a deleted article</p>", version=3)
                site.store.put("index.html", b"<p>stale home</p>", inputs="0000000000000000")
                for entry in site.store.list("_papyrus/items/"):
                    site.store.delete(entry.key)
                preview = reconcile(site.context, dry_run=True)
                self.assertIn("articles/ghost.html", preview.orphan_pages)
                self.assertIn("index.html", preview.stale_listings)
                self.assertEqual(sorted(preview.stale_items), ["item-0", "item-1", "item-2"])
                reconcile(site.context)
                assert_equals_full(self, site, kind)
                self.assertFalse(reconcile(site.context, dry_run=True).drift)
                self.assertEqual(len(site.store.list("_papyrus/items/")), 3)

    def test_lost_redirects_are_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("generic", Path(temporary))
            site.drafts["item-0"].aliases = ["old/zero"]
            site.publish("item-0")
            site.project_item("item-0")
            self.assertEqual(site.redirects.mapping, {"/old/zero": "/articles/seed-0.html"})
            site.redirects.mapping.clear()
            outcome = reconcile(site.context)
            self.assertEqual(outcome.redirects_repaired, 1)
            self.assertEqual(site.redirects.mapping, {"/old/zero": "/articles/seed-0.html"})

    def test_a_large_drift_is_repaired_by_projecting_everything(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = Site("generic", Path(temporary))
            for number in range(25):
                add_item(site, f"item-{number}", f"bulk-{number}", date=f"2026-01-{number + 1:02d}")
            outcome = reconcile(site.context)
            self.assertTrue(outcome.projected_everything)
            assert_equals_full(self, site)


class FakeBucket:
    """The calls S3PageWriter makes, against a dict."""

    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    @staticmethod
    def _missing(code: str) -> Exception:
        error = Exception(code)
        error.response = {"Error": {"Code": code}}
        return error

    def put_object(self, **arguments) -> None:
        self.objects[arguments["Key"]] = arguments

    def delete_object(self, **arguments) -> None:
        self.objects.pop(arguments["Key"], None)

    def get_object(self, **arguments) -> dict:
        if arguments["Key"] not in self.objects:
            raise self._missing("NoSuchKey")
        body = self.objects[arguments["Key"]]["Body"]
        return {"Body": type("Body", (), {"read": lambda _self: body})()}

    def head_object(self, **arguments) -> dict:
        stored = self.objects.get(arguments["Key"])
        if stored is None:
            raise self._missing("404")
        return {"ETag": f'"{body_etag(stored["Body"])}"', "Metadata": stored.get("Metadata", {})}

    def list_objects_v2(self, **arguments) -> dict:
        prefix = arguments.get("Prefix", "")
        return {
            "Contents": [
                {"Key": key, "ETag": f'"{body_etag(stored["Body"])}"'}
                for key, stored in sorted(self.objects.items())
                if key.startswith(prefix)
            ],
            "IsTruncated": False,
        }


class S3SiteStoreTests(unittest.TestCase):
    def test_pages_carry_their_version_and_inputs_and_can_be_read_back_listed_and_deleted(self) -> None:
        store = S3PageWriter("site", FakeBucket())
        store.put("articles/a.html", b"<p>a</p>", version=3)
        store.put("index.html", b"<p>home</p>", inputs="abc123")
        self.assertEqual(store.head("articles/a.html").version, 3)
        self.assertEqual(store.head("index.html").inputs, "abc123")
        self.assertIsNone(store.head("missing.html"))
        self.assertIsNone(store.get("missing.html"))
        self.assertEqual(store.get("index.html"), b"<p>home</p>")
        listed = {entry.key: entry.etag for entry in store.list()}
        self.assertEqual(sorted(listed), ["articles/a.html", "index.html"])
        self.assertEqual(listed["index.html"], body_etag(b"<p>home</p>"))
        self.assertEqual(sorted(store.head_many(["articles/a.html", "nope.html"])), ["articles/a.html", "nope.html"])
        self.assertIsNone(store.head_many(["nope.html"])["nope.html"])
        store.delete("articles/a.html")
        self.assertIsNone(store.head("articles/a.html"))

    def test_the_redirect_store_retries_a_conflicting_update_and_reads_back(self) -> None:
        from papyrus_content.projection.writers import KeyValueStoreRedirects

        class Conflict(Exception):
            response = {"Error": {"Code": "ConflictException"}}

        class MovedEtag(Exception):
            response = {"Error": {"Code": "ValidationException", "Message": "Pre-Condition failed during update of Key-Value-Store"}}

        class NotFound(Exception):
            response = {"Error": {"Code": "ResourceNotFoundException"}}

        class FakeKeyValueStore:
            def __init__(self) -> None:
                self.data: dict[str, str] = {}
                self.calls = 0

            def describe_key_value_store(self, **_arguments) -> dict:
                return {"ETag": f"etag-{self.calls}"}

            def update_keys(self, **arguments) -> None:
                self.calls += 1
                if self.calls == 1:
                    raise Conflict()
                if self.calls == 2:
                    raise MovedEtag()
                for entry in arguments.get("Puts", []):
                    self.data[entry["Key"]] = entry["Value"]
                for entry in arguments.get("Deletes", []):
                    self.data.pop(entry["Key"], None)

            def get_key(self, **arguments) -> dict:
                if arguments["Key"] not in self.data:
                    raise NotFound()
                return {"Value": self.data[arguments["Key"]]}

            def list_keys(self, **_arguments) -> dict:
                return {"Items": [{"Key": key, "Value": value} for key, value in self.data.items()]}

        fake = FakeKeyValueStore()
        store = KeyValueStoreRedirects("arn:aws:cloudfront::1:key-value-store/x", fake)
        store.put_all({"/old": "/new"})
        self.assertEqual(fake.calls, 3)
        self.assertEqual(store.get("/old"), "/new")
        self.assertIsNone(store.get("/other"))
        self.assertEqual(store.list_all(), {"/old": "/new"})


class ReconcileCommandTests(unittest.TestCase):
    def run_command(self, site: Site, flags: list[str]) -> tuple[int, dict]:
        output = io.StringIO()
        status = 0
        with mock.patch("papyrus_content.project_commands.create_authoring_client", return_value=(site.client, {})), mock.patch(
            "papyrus_content.project_commands._context_for", return_value=site.context
        ), contextlib.redirect_stdout(output):
            try:
                cli.dispatch("content", "project", [*flags, "--json"])
            except SystemExit as error:
                status = int(error.code or 0)
        return status, json.loads(output.getvalue())

    def test_the_command_reports_drift_in_a_dry_run_and_repairs_it_otherwise(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("feed", Path(temporary))
            site.drafts["item-1"].title = "Saved but not rendered"
            site.publish("item-1")
            status, payload = self.run_command(site, ["--reconcile", "--dry-run"])
            self.assertEqual(status, 1)
            self.assertEqual(payload["staleItems"], ["item-1"])
            status, payload = self.run_command(site, ["--reconcile"])
            self.assertEqual(status, 0)
            assert_equals_full(self, site)
            status, payload = self.run_command(site, ["--reconcile", "--dry-run"])
            self.assertEqual((status, payload["drift"]), (0, False))

    def test_the_modes_exclude_each_other(self) -> None:
        with self.assertRaises(ValueError):
            cli.dispatch("content", "project", ["--reconcile", "--all"])


class RenamedSlugTests(unittest.TestCase):
    def test_a_renamed_item_leaves_a_redirect_from_its_old_address_and_nothing_stale(self) -> None:
        for kind in ("generic", "feed"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                site = seeded_site(kind, Path(temporary))
                unpublish_item(site.client, "item-1", actor=ACTOR, now=NOW)
                site.published.discard("item-1")
                site.project_item("item-1")
                pages, redirects = site.incremental()
                self.assertNotIn("articles/seed-1.html", pages)
                self.assertEqual(redirects, {})
                site.drafts["item-1"].slug = "renamed-one"
                site.publish("item-1")
                site.project_item("item-1")
                pages, redirects = site.incremental()
                self.assertIn("articles/renamed-one.html", pages)
                self.assertNotIn("articles/seed-1.html", pages)
                self.assertEqual(redirects, {"/articles/seed-1.html": "/articles/renamed-one.html"})
                assert_equals_full(self, site, kind)

    def test_a_page_that_takes_over_a_redirected_address_is_not_shadowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("generic", Path(temporary))
            unpublish_item(site.client, "item-1", actor=ACTOR, now=NOW)
            site.project_item("item-1")
            site.drafts["item-1"].slug = "renamed-one"
            site.publish("item-1")
            site.project_item("item-1")
            add_item(site, "item-new", "seed-1")
            site.project_item("item-new")
            _pages, redirects = site.incremental()
            self.assertNotIn("/articles/seed-1.html", redirects)


if __name__ == "__main__":
    unittest.main()
