"""Invalidation and KeyValueStore cost: one wildcard per large run, small runs stay exact, redirect writes are diffed and batched."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from papyrus_content.edge_invalidation import (
    WILDCARD_INVALIDATION_PATH,
    WILDCARD_THRESHOLD,
    WholeSiteInvalidationRefused,
    invalidate_distribution,
    invalidate_revalidated_paths,
)
from papyrus_content.projection.engine import ProjectionContext, project_all, project_item_pages
from papyrus_content.projection.writers import KEY_VALUE_STORE_BATCH_SIZE, CloudFrontInvalidator, KeyValueStoreRedirects
from procedures.newsroom.tests.incremental_site import FakeRedirectStore, Site, add_item


class RecordingCloudFront:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def create_invalidation(self, **arguments) -> None:
        self.calls.append(arguments["InvalidationBatch"]["Paths"]["Items"])


def quiet(function, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return function(*args, **kwargs)


class WildcardCollapseTests(unittest.TestCase):
    def test_small_runs_keep_exact_paths(self) -> None:
        client = RecordingCloudFront()
        paths = [f"/p/{number}.html" for number in range(WILDCARD_THRESHOLD)]
        result = quiet(invalidate_distribution, "E", paths, client)
        self.assertEqual(client.calls, [paths])
        self.assertEqual(result, paths)

    def test_a_run_over_the_threshold_is_one_wildcard(self) -> None:
        client = RecordingCloudFront()
        paths = [f"/p/{number}.html" for number in range(WILDCARD_THRESHOLD + 1)]
        result = quiet(invalidate_distribution, "E", paths, client)
        self.assertEqual(client.calls, [[WILDCARD_INVALIDATION_PATH]])
        self.assertEqual(result, [WILDCARD_INVALIDATION_PATH])

    def test_a_caller_cannot_pass_a_wildcard(self) -> None:
        with self.assertRaises(WholeSiteInvalidationRefused):
            quiet(invalidate_distribution, "E", ["/*"], RecordingCloudFront())

    def test_reader_revalidated_paths_collapse_per_distribution(self) -> None:
        client = RecordingCloudFront()
        revalidated = {"revalidatedPaths": [f"/a/{number}" for number in range(300)]}
        outcome = quiet(invalidate_revalidated_paths, ["E1", "E2"], revalidated, client)
        self.assertTrue(outcome["ok"])
        self.assertEqual(client.calls, [["/*"], ["/*"]])

    def test_invalidator_over_keys_issues_one_call(self) -> None:
        client = RecordingCloudFront()
        keys = [f"articles/{number}.html" for number in range(400)]
        quiet(CloudFrontInvalidator("E", client).invalidate, keys)
        self.assertEqual(client.calls, [["/*"]])


class RunTests(unittest.TestCase):
    def make_site(self, count: int) -> Site:
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        site = Site("feed", Path(work.name))
        for number in range(count):
            add_item(site, f"item-{number}", f"seed-{number}", date=f"2026-01-{number + 1:02d}")
        return site

    def test_a_full_render_issues_one_wildcard(self) -> None:
        site = self.make_site(8)
        client = RecordingCloudFront()
        site.context.invalidate = CloudFrontInvalidator("E", client).invalidate
        quiet(project_all, site.context)
        self.assertEqual(client.calls, [["/*"]])

    def test_an_item_pages_follow_up_batches_into_one_invalidation(self) -> None:
        site = self.make_site(12)
        quiet(project_all, site.context)
        for item_id in list(site.drafts):
            site.drafts[item_id].body = "Changed.\n"
            site.publish(item_id)
        client = RecordingCloudFront()
        site.context.invalidate = CloudFrontInvalidator("E", client).invalidate
        quiet(project_item_pages, site.context)
        self.assertEqual(client.calls, [["/*"]])

    def test_a_single_page_change_stays_exact(self) -> None:
        site = self.make_site(3)
        quiet(project_all, site.context)
        client = RecordingCloudFront()
        site.context.invalidate = CloudFrontInvalidator("E", client).invalidate
        site.drafts["item-0"].body = "Only this changed.\n"
        site.publish("item-0")
        quiet(site.project_item, "item-0")
        self.assertEqual(len(client.calls), 1)
        self.assertLessEqual(len(client.calls[0]), WILDCARD_THRESHOLD)
        self.assertNotIn("/*", client.calls[0])


class CountingStore(FakeRedirectStore):
    def __init__(self) -> None:
        super().__init__()
        self.puts: list[dict[str, str]] = []

    def put_all(self, redirects: dict[str, str]) -> None:
        self.puts.append(dict(redirects))
        super().put_all(redirects)


class RedirectWriteTests(unittest.TestCase):
    def test_a_full_render_skips_unchanged_redirects(self) -> None:
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        site = Site("feed", Path(work.name))
        add_item(site, "item-0", "seed-0")
        site.drafts["item-0"].aliases = ["/old/one", "/old/two"]
        site.publish("item-0")
        store = CountingStore()
        context = ProjectionContext(
            source=site.context.source, projector=site.projector, writer=site.store, redirect_store=store
        )
        project_all(context)
        self.assertTrue(store.mapping)
        self.assertEqual(len(store.puts), 1)
        project_all(context)
        self.assertEqual(len(store.puts), 1)
        store.mapping["/old/one"] = "/stale"
        project_all(context)
        self.assertEqual(store.puts[-1], {"/old/one": site.projector.redirects(context.source.site_index())["/old/one"]})


class FakeKvsClient:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    def describe_key_value_store(self, **_arguments) -> dict:
        return {"ETag": "tag"}

    def update_keys(self, **arguments) -> None:
        self.updates.append(arguments)


class KeyValueStoreBatchTests(unittest.TestCase):
    def test_puts_are_sent_fifty_per_call(self) -> None:
        client = FakeKvsClient()
        store = KeyValueStoreRedirects("arn", client)
        store.put_all({f"/s/{number}": f"/t/{number}" for number in range(120)})
        self.assertEqual([len(call["Puts"]) for call in client.updates], [KEY_VALUE_STORE_BATCH_SIZE, 50, 20])


if __name__ == "__main__":
    unittest.main()
