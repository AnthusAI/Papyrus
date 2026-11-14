"""What one publish costs does not grow with the site (PPY-3acc8d): a fixed number of record reads, two passes over the published summaries,
no whole-table read and no read per Story, at 150 and at 300 Stories; and pages whose bytes did not change are neither written nor purged."""

from __future__ import annotations

import unittest

from papyrus_content.projection.body_cache import BODY_CACHE_KEY
from procedures.newsroom.tests.publish_cost_support import CostSite, point_reads, settings_reads, summary_passes, whole_table_reads

# The projection of one publish: the story's Item and PublishedItem, and its Item again for its lineage (sibling versions).
MAX_POINT_READS = 3
# The listing data, read once to plan the pages and once more to notice a concurrent publish.
SUMMARY_PASSES = 2


class OnePublishCostsTheSameAtAnySizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.small, cls.large = CostSite(150), CostSite(300)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.small.cleanup()
        cls.large.cleanup()

    def test_a_publish_reads_a_fixed_number_of_records_whatever_the_number_of_stories(self) -> None:
        small_report, small, _ = self.small.publish_one()
        large_report, large, _ = self.large.publish_one()
        self.assertTrue(small_report.ok and large_report.ok)
        self.assertIn("llms-full.txt", large_report.written)   # the page that needs every Story's text was rebuilt, from the kept bodies
        for counted in (small, large):
            self.assertLessEqual(point_reads(counted), MAX_POINT_READS, counted)
            self.assertEqual(summary_passes(counted), SUMMARY_PASSES, counted)
            self.assertEqual(whole_table_reads(counted), 0, counted)
            self.assertLessEqual(settings_reads(counted), 1, counted)   # the site's languages, once per projection
        self.assertEqual(point_reads(small), point_reads(large))
        self.assertEqual(summary_passes(small), summary_passes(large))

    def test_the_item_pages_follow_up_reads_no_story_one_by_one_and_no_whole_table(self) -> None:
        report, counted = self.large.follow_up()
        self.assertTrue(report.ok)
        self.assertEqual(point_reads(counted), 0, counted)
        self.assertLessEqual(settings_reads(counted), 1, counted)
        self.assertEqual(whole_table_reads(counted), 0, counted)
        self.assertEqual(summary_passes(counted), 1, counted)

    def test_the_kept_bodies_live_beside_the_item_states(self) -> None:
        self.assertIsNotNone(self.large.writer.get(BODY_CACHE_KEY))


class WithoutKeptBodiesTest(unittest.TestCase):
    """The first projection after the cache is lost reads each body once, keeps them, and the next publish is cheap again."""

    def test_a_lost_cache_is_rebuilt_by_the_next_publish(self) -> None:
        site = CostSite(40)
        try:
            site.writer.delete(BODY_CACHE_KEY)
            _report, first, _ = site.publish_one()
            self.assertGreater(point_reads(first), 40)   # every Story's body, once
            _report, second, _ = site.publish_one()
            self.assertLessEqual(point_reads(second), MAX_POINT_READS)
        finally:
            site.cleanup()

    def test_an_edited_story_is_never_shown_from_a_stale_body(self) -> None:
        from procedures.newsroom.tests.publish_cost_support import publish, story_fields

        site = CostSite(10)
        try:
            fields = story_fields(3)
            fields.body_markus = "An edited body that must reach llms-full.txt.\n"
            publish(site.client, fields, "2026-11-09T00:00:00Z")
            report = __import__("papyrus_content.projection.engine", fromlist=["project"]).project(site.context(), fields.id)
            self.assertTrue(report.ok)
            self.assertIn("An edited body that must reach llms-full.txt.", site.writer.get("llms-full.txt").decode("utf-8"))
            _report, _counted, _ = site.publish_one()   # another Story's publish rebuilds llms-full.txt from the cache
            self.assertIn("An edited body that must reach llms-full.txt.", site.writer.get("llms-full.txt").decode("utf-8"))
        finally:
            site.cleanup()


if __name__ == "__main__":
    unittest.main()


class CountingBucket:
    """The in-memory S3 bucket of the resilience tests, counting the writes."""

    def __init__(self) -> None:
        from procedures.newsroom.tests.test_projection_resilience import FakeBucket

        self.inner = FakeBucket()
        self.puts: list[str] = []

    def put_object(self, **arguments) -> None:
        self.puts.append(arguments["Key"])
        self.inner.put_object(**arguments)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class UnchangedPagesAreNotWrittenTest(unittest.TestCase):
    """On S3, a page rendered again with the bytes the store already holds is neither written nor purged; the rest is written as before."""

    @classmethod
    def setUpClass(cls) -> None:
        from papyrus_content.projection.writers import S3PageWriter

        cls.bucket = CountingBucket()
        cls.site = CostSite(120, writer_factory=lambda _root: S3PageWriter("site", cls.bucket), every_page_reads_every_story=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.site.cleanup()

    def test_only_pages_whose_bytes_changed_are_written_and_named_for_the_purge(self) -> None:
        before = {key: dict(stored) for key, stored in self.bucket.inner.objects.items()}
        self.bucket.puts.clear()
        report, _counted, _calls = self.site.publish_one()
        self.assertTrue(report.ok)
        changed = {key for key in report.written}
        for key in changed:   # every page named for the purge really changed
            self.assertNotEqual(before.get(key, {}).get("Body"), self.bucket.inner.objects[key]["Body"], key)
        for key in report.unchanged:   # and every page left out has the bytes it had
            self.assertEqual(before[key]["Body"], self.bucket.inner.objects[key]["Body"], key)
        page_puts = [key for key in self.bucket.puts if not key.startswith("_papyrus/")]
        self.assertGreater(len(report.unchanged), 0)   # pages rendered again only because every page reads every Story came out the same
        self.assertEqual(set(page_puts) - changed, set(page_puts) & set(report.unchanged))   # those were written only to record a new digest
        self.assertTrue(all(before[key].get("Metadata", {}).get("papyrus-inputs") != self.bucket.inner.objects[key].get("Metadata", {}).get("papyrus-inputs") for key in set(page_puts) & set(report.unchanged)))
        self.assertTrue(any(key.endswith("story-120/index.html") for key in changed))

    def test_a_page_with_the_same_bytes_but_a_new_digest_gets_its_digest_without_a_purge(self) -> None:
        from papyrus_content.projection.engine import ProjectionContext, _put_pages
        from papyrus_content.projection.model import ProjectionReport

        writer = self.site.writer
        writer.put("probe.html", b"<p>same</p>", inputs="old")
        context = ProjectionContext(source=self.site.context().source, projector=self.site.projector, writer=writer)
        report = ProjectionReport()
        _put_pages(context, report, [("probe.html", b"<p>same</p>", None, "new")])
        self.assertEqual(report.written, [])
        self.assertEqual(report.unchanged, ["probe.html"])
        self.assertEqual(writer.head("probe.html").inputs, "new")
