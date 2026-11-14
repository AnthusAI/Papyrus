from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures/newsroom/tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.engine import project  # noqa: E402
from papyrus_content.projection.writers import S3PageWriter  # noqa: E402
from procedures.newsroom.tests.publish_cost_support import CostSite, point_reads, publish, story_fields, summary_passes, whole_table_reads  # noqa: E402
from procedures.newsroom.tests.test_publish_cost import CountingBucket  # noqa: E402


def _sites(context) -> dict[int, CostSite]:
    if not hasattr(context, "cost_sites"):
        context.cost_sites = {}
        context.add_cleanup(lambda: [site.cleanup() for site in context.cost_sites.values()])
    return context.cost_sites


@given("a site with {count:d} published stories whose pages were built")
def step_site(context, count: int) -> None:
    _sites(context)[count] = CostSite(count)
    context.cost_site = _sites(context)[count]


@given("a site on S3 whose every page reads every story, with {count:d} published stories whose pages were built")
def step_s3_site(context, count: int) -> None:
    context.bucket = CountingBucket()
    context.cost_site = CostSite(count, writer_factory=lambda _root: S3PageWriter("site", context.bucket), every_page_reads_every_story=True)
    context.add_cleanup(context.cost_site.cleanup)


@when("an editor publishes one more story on each site")
def step_publish_each(context) -> None:
    context.builds = {count: site.publish_one() for count, site in sorted(_sites(context).items())}


@then("each build reads at most {limit:d} records one by one and the listing data twice")
def step_each_reads(context, limit: int) -> None:
    for count, (report, counted, _calls) in context.builds.items():
        assert report.ok, report.errors
        assert point_reads(counted) <= limit, (count, counted)
        assert summary_passes(counted) == 2, (count, counted)


@then("the build on the larger site reads no more than the build on the smaller one")
def step_no_growth(context) -> None:
    (_small_report, small, _), (_large_report, large, _) = (context.builds[count] for count in sorted(context.builds))
    assert point_reads(large) <= point_reads(small), (small, large)
    assert summary_passes(large) == summary_passes(small), (small, large)


@then("neither build reads a whole table of stories")
def step_no_whole_table(context) -> None:
    for count, (_report, counted, _calls) in context.builds.items():
        assert whole_table_reads(counted) == 0, (count, counted)


@then("llms-full.txt is rebuilt on both sites")
def step_llms_full(context) -> None:
    for count, (report, _counted, _calls) in context.builds.items():
        assert "llms-full.txt" in report.written, (count, report.written)


@when("every story page is built again after a change they all read")
def step_follow_up(context) -> None:
    context.follow_up = context.cost_site.follow_up()


@then("the rebuild reads the listing data once and no record one by one")
def step_follow_up_reads(context) -> None:
    report, counted = context.follow_up
    assert report.ok, report.errors
    assert summary_passes(counted) == 1 and point_reads(counted) == 0 and whole_table_reads(counted) == 0, counted


@when("an editor publishes a new version of one story")
def step_new_version(context) -> None:
    fields = story_fields(3)
    fields.body_markus = "The text of the new version, which llms-full.txt must show.\n"
    publish(context.cost_site.client, fields, "2026-11-09T00:00:00Z")
    report = project(context.cost_site.context(), fields.id)
    assert report.ok, report.errors


@when("then publishes another story")
def step_another(context) -> None:
    report, _counted, _calls = context.cost_site.publish_one()
    assert report.ok, report.errors


@then("llms-full.txt shows the new version's text")
def step_new_text(context) -> None:
    text = context.cost_site.writer.get("llms-full.txt").decode("utf-8")
    assert "The text of the new version, which llms-full.txt must show." in text


@when("an editor publishes one more story on that site")
def step_publish_s3(context) -> None:
    context.before = {key: dict(stored) for key, stored in context.bucket.inner.objects.items()}
    context.bucket.puts.clear()
    context.report, _counted, _calls = context.cost_site.publish_one()
    assert context.report.ok, context.report.errors


@then("only the pages whose bytes changed are named for the edge purge")
def step_purged_changed(context) -> None:
    objects = context.bucket.inner.objects
    for key in context.report.written:
        assert context.before.get(key, {}).get("Body") != objects[key]["Body"], key
    assert any(re.search(r"story-\d+/index\.html$", key) for key in context.report.written)


@then("the pages that came out the same keep the bytes they had")
def step_same_bytes(context) -> None:
    assert context.report.unchanged, "every page re-rendered on this site should include some that came out the same"
    for key in context.report.unchanged:
        assert context.before[key]["Body"] == context.bucket.inner.objects[key]["Body"], key


@then("a page that came out the same is written again only to record its new inputs digest")
def step_digest_only(context) -> None:
    rewritten = [key for key in context.bucket.puts if key in set(context.report.unchanged)]
    for key in rewritten:
        before = context.before[key].get("Metadata", {}).get("papyrus-inputs")
        after = context.bucket.inner.objects[key].get("Metadata", {}).get("papyrus-inputs")
        assert before != after, key
