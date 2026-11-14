"""``publication.cache.invalidation: "targeted"`` (PPY-2745c1): a publish purges exactly the pages it wrote, never a wildcard, capped, and a deploy never purges."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from papyrus_content.edge_invalidation import InvalidationCapped
from papyrus_content.projection.engine import project_all
from papyrus_content.projection.runtime import context_from_environment, targeted_invalidation
from papyrus_content.projection.writers import CloudFrontInvalidator, TargetedCloudFrontInvalidator, invalidation_paths_for
from procedures.newsroom.tests.incremental_site import Site, add_item


HANDLER_PATH = Path(__file__).resolve().parents[3] / "amplify/functions/content-actions/handler.py"
_specification = importlib.util.spec_from_file_location("content_actions_handler_targeted", HANDLER_PATH)
handler = importlib.util.module_from_spec(_specification)
_specification.loader.exec_module(handler)


class RecordingCloudFront:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def create_invalidation(self, **arguments):
        self.calls.append(arguments["InvalidationBatch"]["Paths"]["Items"])
        return {"Invalidation": {"Id": f"I{len(self.calls)}", "Status": "InProgress"}}

    @property
    def paths(self) -> list[str]:
        return [path for call in self.calls for path in call]


def quiet(function, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return function(*args, **kwargs)


class TargetedInvalidatorTests(unittest.TestCase):
    def test_a_page_is_purged_in_both_url_forms_with_its_twin(self) -> None:
        client = RecordingCloudFront()
        purged = quiet(TargetedCloudFrontInvalidator("E", 25, client).invalidate, ["articles/a/index.html", "articles/a/index.md", "index.html"])
        self.assertEqual(
            set(purged),
            {"/articles/a/index.html", "/articles/a/", "/articles/a/index.md", "/index.html", "/"},
        )
        self.assertEqual(client.paths, purged)

    def test_it_uses_the_same_path_code_as_the_default_invalidator(self) -> None:
        keys = ["articles/a/index.html", "articles/a/index.md", "articles/page/2/index.html"]
        client = RecordingCloudFront()
        quiet(TargetedCloudFrontInvalidator("E", 25, client).invalidate, keys)
        self.assertEqual(client.paths, invalidation_paths_for(keys))

    def test_it_never_collapses_to_a_wildcard(self) -> None:
        client = RecordingCloudFront()
        keys = [f"articles/{number}.html" for number in range(400)]
        with self.assertRaises(InvalidationCapped) as raised:
            quiet(TargetedCloudFrontInvalidator("E", 25, client).invalidate, keys)
        self.assertNotIn("/*", client.paths)
        self.assertEqual(len(client.paths), 25)
        self.assertEqual(len(raised.exception.invalidated), 25)
        self.assertEqual(len(raised.exception.skipped), 400 - 25)

    def test_the_default_invalidator_still_collapses(self) -> None:
        client = RecordingCloudFront()
        quiet(CloudFrontInvalidator("E", client).invalidate, [f"articles/{number}.html" for number in range(400)])
        self.assertEqual(client.paths, ["/*"])

    def test_the_cap_follows_the_site_setting(self) -> None:
        client = RecordingCloudFront()
        environment = {"PAPYRUS_SITE_BUCKET": "b", "PAPYRUS_EDGE_DISTRIBUTION_ID": "E", "PAPYRUS_EDGE_INVALIDATION": "targeted", "PAPYRUS_INVALIDATION_MAX_PATHS": "3"}
        self.assertTrue(targeted_invalidation(environment))
        with mock.patch("papyrus_content.projection.runtime.load_projector"), mock.patch("papyrus_content.projection.runtime.S3PageWriter"), mock.patch(
            "papyrus_content.projection.runtime.star_store_from_environment"
        ), mock.patch("papyrus_content.projection.runtime.lease_from_environment"):  # no AWS client is built
            context = context_from_environment(None, environment, s3_client=object(), cloudfront_client=client)
        with self.assertRaises(InvalidationCapped):
            quiet(context.invalidate, ["a/index.html", "b/index.html"])
        self.assertEqual(len(client.paths), 3)

    def test_targeted_is_the_default_and_off_and_all_stay_selectable(self) -> None:
        self.assertTrue(targeted_invalidation({}))
        self.assertTrue(targeted_invalidation({"PAPYRUS_EDGE_INVALIDATION": "targeted"}))
        self.assertFalse(targeted_invalidation({"PAPYRUS_EDGE_INVALIDATION": "off"}))
        self.assertFalse(targeted_invalidation({"PAPYRUS_EDGE_INVALIDATION": "all"}))

    def test_an_unset_site_gets_the_targeted_invalidator_and_all_gets_the_collapsing_one(self) -> None:
        base = {"PAPYRUS_SITE_BUCKET": "b", "PAPYRUS_EDGE_DISTRIBUTION_ID": "E"}
        made = {}
        for name, extra in (("default", {}), ("all", {"PAPYRUS_EDGE_INVALIDATION": "all"}), ("off", {"PAPYRUS_EDGE_INVALIDATION": "off"})):
            client = RecordingCloudFront()
            with mock.patch("papyrus_content.projection.runtime.load_projector"), mock.patch("papyrus_content.projection.runtime.S3PageWriter"), mock.patch(
                "papyrus_content.projection.runtime.star_store_from_environment"
            ), mock.patch("papyrus_content.projection.runtime.lease_from_environment"):
                context = context_from_environment(None, {**base, **extra}, s3_client=object(), cloudfront_client=client)
            made[name] = (context.invalidate, client)
        self.assertIsNone(made["off"][0])
        keys = [f"articles/{number}.html" for number in range(400)]
        with self.assertRaises(InvalidationCapped):
            quiet(made["default"][0], keys)
        self.assertEqual(len(made["default"][1].paths), 25)
        quiet(made["all"][0], keys)
        self.assertEqual(made["all"][1].paths, ["/*"])


class HandlerTests(unittest.TestCase):
    def run_deploy_render(self, environment: dict[str, str]) -> mock.Mock:
        context = mock.Mock()
        context.invalidate = lambda keys: keys
        report = mock.Mock(ok=True)
        report.render.unpurged = []
        report.to_dict.return_value = {}
        with mock.patch.dict(handler.os.environ, environment, clear=False), mock.patch.object(handler, "ensure_publication_from_environment"), mock.patch.object(
            handler, "ensure_default_editorial_policies"
        ), mock.patch.object(handler, "projection_context", return_value=context), mock.patch.object(handler, "deploy_render", return_value=report) as render, mock.patch.object(
            handler, "drift_metric_line", return_value=""
        ):
            handler.run_deploy_render_task(object())
        return render.call_args.args[0]

    def test_a_deploy_never_invalidates_in_targeted_mode(self) -> None:
        self.assertIsNone(self.run_deploy_render({"PAPYRUS_EDGE_INVALIDATION": "targeted"}).invalidate)

    def test_a_deploy_never_invalidates_by_default_either(self) -> None:
        with mock.patch.dict(handler.os.environ, {}, clear=False):
            handler.os.environ.pop("PAPYRUS_EDGE_INVALIDATION", None)
            self.assertIsNone(self.run_deploy_render({}).invalidate)

    def test_a_site_set_to_all_keeps_the_legacy_deploy_purge(self) -> None:
        self.assertIsNotNone(self.run_deploy_render({"PAPYRUS_EDGE_INVALIDATION": "all"}).invalidate)

    def test_the_all_and_item_pages_tasks_never_purge_in_targeted_mode(self) -> None:
        for task, engine_function in (({"task": "all"}, "project_all"), ({"task": "item-pages", "exceptItemId": "x"}, "project_item_pages")):
            context = mock.Mock()
            context.invalidate = lambda keys: keys
            report = mock.Mock(ok=True, unpurged=[], written=[], deleted=[], follow_up_item_pages=False)
            with mock.patch.dict(handler.os.environ, {}, clear=False), mock.patch.object(handler, "create_authoring_client", return_value=(object(), {})), mock.patch.object(
                handler, "projection_context", return_value=context
            ), mock.patch.object(handler, engine_function, return_value=report) as run:
                handler.os.environ.pop("PAPYRUS_EDGE_INVALIDATION", None)
                handler._run_projection_task(task)
            self.assertIsNone(run.call_args.args[0].invalidate, task)

    def test_a_capped_publish_response_names_the_skipped_paths(self) -> None:
        from papyrus_content.projection.model import ProjectionReport

        report = ProjectionReport(written=["a/index.html"], item_paths=["a/index.html"], invalidated=["/a/"], invalidation_capped=["/index.html"])
        with mock.patch.object(handler, "projection_configured", return_value=True), mock.patch.object(handler, "project", return_value=report), mock.patch.object(
            handler, "projection_context"
        ), mock.patch.object(handler, "schedule_projection_task") as scheduled:
            response = handler.project_item_action(object(), "item", unpublished=False)
        self.assertTrue(response["projected"])
        self.assertIs(response["edgePurged"], False)
        self.assertEqual(response["invalidationCapped"], ["/index.html"])
        scheduled.assert_not_called()
        self.assertEqual(response["invalidation"]["status"], "capped")
        self.assertEqual(response["invalidation"]["skippedPaths"], ["/index.html"])
        self.assertEqual(response["itemPaths"], ["a/index.html"])

    def test_a_site_without_an_invalidator_reports_the_purge_as_skipped(self) -> None:
        from papyrus_content.projection.model import ProjectionReport

        report = ProjectionReport(written=["a/index.html"], item_paths=["a/index.html"])
        context = mock.Mock()
        context.invalidate = None
        with mock.patch.object(handler, "projection_configured", return_value=True), mock.patch.object(handler, "project", return_value=report), mock.patch.object(
            handler, "projection_context", return_value=context
        ):
            response = handler.project_item_action(object(), "item", unpublished=False)
        self.assertEqual(response["invalidation"]["status"], "skipped")


class PrioritisationTests(unittest.TestCase):
    def test_a_capped_purge_takes_the_story_pages_before_the_listings(self) -> None:
        from papyrus_content.projection.engine import _finish
        from papyrus_content.projection.model import ProjectionReport

        client = RecordingCloudFront()
        listings = [f"articles/page/{number}/index.html" for number in range(10)]
        report = ProjectionReport(written=[*listings, "index.html", "articles/hello/index.html", "articles/hello/index.md"], item_paths=["articles/hello/index.html", "articles/hello/index.md"])
        quiet(_finish, mock.Mock(invalidate=TargetedCloudFrontInvalidator("E", 6, client).invalidate), report)
        self.assertEqual(client.paths[:3], ["/articles/hello/index.html", "/articles/hello/", "/articles/hello/index.md"])
        self.assertEqual(len(client.paths), 6)
        self.assertTrue(report.invalidation_capped)
        self.assertTrue(set(report.invalidation_capped).isdisjoint(client.paths))


class SinglePublishTests(unittest.TestCase):
    def make_site(self, count: int) -> Site:
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        site = Site("feed", Path(work.name))
        for number in range(count):
            add_item(site, f"item-{number}", f"seed-{number}", date=f"2026-01-{number + 1:02d}")
        quiet(project_all, site.context)
        return site

    def test_a_single_story_publish_purges_only_what_it_wrote_and_stays_under_ten_paths(self) -> None:
        site = self.make_site(30)
        client = RecordingCloudFront()
        site.context.invalidate = TargetedCloudFrontInvalidator("E", 25, client).invalidate
        site.drafts["item-0"].body = "Only this changed.\n"
        site.publish("item-0")
        report = quiet(site.project_item, "item-0")
        self.assertEqual(sorted(client.paths), sorted(invalidation_paths_for([key for key in [*report.written, *report.deleted] if not key.startswith("_papyrus/")])))
        self.assertNotIn("/*", client.paths)
        self.assertTrue(client.paths)
        self.assertFalse(report.invalidation_capped)

    def test_an_over_cap_publish_reports_the_skipped_paths_and_is_not_a_failed_write(self) -> None:
        site = self.make_site(12)

        def capped(keys: list[str]) -> list[str]:
            paths = invalidation_paths_for(keys)
            raise InvalidationCapped(paths[:1], paths[1:] or ["/skipped"], 1)

        site.context.invalidate = capped
        site.drafts["item-0"].body = "Changed.\n"
        site.publish("item-0")
        report = quiet(site.project_item, "item-0")
        self.assertTrue(report.ok)
        self.assertEqual(len(report.invalidated), 1)
        self.assertTrue(report.invalidation_capped)
        self.assertEqual(report.unpurged, [])


if __name__ == "__main__":
    unittest.main()
