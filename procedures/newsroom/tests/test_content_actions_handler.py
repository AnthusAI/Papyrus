from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_client import FakeAuthoringClient  # noqa: E402
from tenant_support import dedicated_call  # noqa: E402

HANDLER_PATH = Path(__file__).resolve().parents[3] / "amplify/functions/content-actions/handler.py"
specification = importlib.util.spec_from_file_location("content_actions_handler", HANDLER_PATH)
content_actions_handler = importlib.util.module_from_spec(specification)
specification.loader.exec_module(content_actions_handler)

FRONT_MATTER = "title: Hello\n"


def event(field: str, payload, *, as_string: bool = True) -> dict:
    import json

    return {
        "fieldName": field,
        "arguments": {"input": json.dumps(payload) if as_string else payload},
        "identity": {"username": "editor-one", "sub": "sub-1", "claims": {"sub": "sub-1"}},
    }


def save_payload(**changes) -> dict:
    values = {
        "id": None,
        "type": "article",
        "slug": "my-post",
        "section": "articles",
        "frontMatterYaml": FRONT_MATTER,
        "bodyMarkus": "Hello **x**\n",
        "aliases": [],
        "expectedContentHash": None,
    }
    values.update(changes)
    return values


class HomePageSnapshotTaskTest(unittest.TestCase):
    """The task the stream trigger schedules reads the list of changed rows, runs, and takes out exactly what it read once it succeeded."""

    def run_task(self, report: dict, task: dict | None = None):
        from papyrus_content.home_page.state_store import DirtyBatch

        batch, dirty, state = DirtyBatch(ids=frozenset({"reference-1-v1"})), mock.Mock(), mock.Mock()
        self.dirty = dirty
        with mock.patch.object(content_actions_handler, "projection_context", return_value=mock.Mock()), \
                mock.patch.object(content_actions_handler, "home_page_settings_of", return_value=object()), \
                mock.patch.object(content_actions_handler, "home_page_stores_for", return_value=(state, dirty, batch)), \
                mock.patch.object(content_actions_handler, "run_home_page_snapshot", return_value=report) as run:
            result = content_actions_handler.run_home_page_snapshot_task(FakeAuthoringClient(), task or {"task": "home-page-snapshot", "incremental": True, "scope": "abc"})
        return result, run, dirty, batch, state

    def test_a_successful_run_gets_the_state_and_the_batch_and_acknowledges_what_it_read(self) -> None:
        result, run, dirty, batch, state = self.run_task({"mode": "incremental", "written": []})
        self.assertTrue(result["ok"])
        self.assertIs(run.call_args.kwargs["dirty"], batch)
        self.assertIs(run.call_args.kwargs["state_store"], state)
        dirty.acknowledge.assert_called_once_with(batch)

    def test_a_run_that_reports_errors_keeps_the_list_for_the_retry(self) -> None:
        with self.assertRaises(content_actions_handler.ProjectionTaskFailed):
            self.run_task({"errors": ["a page failed"]})
        self.dirty.acknowledge.assert_not_called()  # the list is only taken out after success, so the retry reads the same rows


class ContentActionsHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeAuthoringClient()
        patcher = mock.patch.object(
            content_actions_handler, "create_authoring_client", return_value=(self.client, {})
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, field: str, payload, **kwargs) -> dict:
        return content_actions_handler.handler(event(field, payload, **kwargs), None)

    def test_derive_ok_reports_size_and_optional_ir(self) -> None:
        result = self.call("deriveMarkus", {"frontMatterYaml": FRONT_MATTER, "bodyMarkus": "Hello **x**\n"})
        self.assertTrue(result["ok"])
        self.assertGreater(result["bodyIrBytes"], 0)
        self.assertNotIn("bodyIr", result)
        with_ir = self.call(
            "deriveMarkus", {"frontMatterYaml": FRONT_MATTER, "bodyMarkus": "Hello\n", "includeIr": True}
        )
        self.assertIn("bodyIr", with_ir)

    def test_derive_accepts_dict_input(self) -> None:
        result = self.call(
            "deriveMarkus", {"frontMatterYaml": FRONT_MATTER, "bodyMarkus": "Hi\n"}, as_string=False
        )
        self.assertTrue(result["ok"])

    def test_derive_bad_body_returns_errors_without_raising(self) -> None:
        result = self.call("deriveMarkus", {"frontMatterYaml": FRONT_MATTER, "bodyMarkus": "::nope\n::\n"})
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"][0]["code"])

    def test_save_then_stale_hash_conflicts(self) -> None:
        first = self.call("saveItemDraft", save_payload())
        self.assertTrue(first["ok"])
        item = first["item"]
        self.assertEqual(item["status"], "draft")
        self.assertEqual(item["slug"], "my-post")
        self.assertEqual(item["versionNumber"], 1)

        second = self.call(
            "saveItemDraft",
            save_payload(id=item["id"], bodyMarkus="Changed\n", expectedContentHash=item["contentHash"]),
        )
        self.assertTrue(second["ok"])

        stale = self.call(
            "saveItemDraft",
            save_payload(id=item["id"], bodyMarkus="Again\n", expectedContentHash=item["contentHash"]),
        )
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["errors"][0]["code"], "conflict")

    def test_publish_then_unpublish(self) -> None:
        item = self.call("saveItemDraft", save_payload())["item"]
        published = self.call("publishItem", {"id": item["id"]})
        self.assertTrue(published["ok"])
        self.assertTrue(published["changed"])
        self.assertEqual(published["versionNumber"], 1)
        self.assertIn(published["publishedId"], self.client.tables["PublishedItem"])

        unpublished = self.call("unpublishItem", {"id": item["id"]})
        self.assertEqual(unpublished, {"ok": True, "changed": True})
        self.assertNotIn(published["publishedId"], self.client.tables.get("PublishedItem", {}))

    def test_a_live_story_cannot_change_type_by_saving_in_place(self) -> None:
        item = self.call("saveItemDraft", save_payload())["item"]
        self.call("publishItem", {"id": item["id"]})
        refused = self.call("saveItemDraft", save_payload(id=item["id"], type="post", expectedContentHash=item["contentHash"]))
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["errors"][0]["code"], "type-locked")
        self.assertIn("new version", refused["errors"][0]["message"])
        self.assertEqual(self.client.tables["Item"][item["id"]]["type"], "article", "the live row was not touched")

    def test_a_new_version_can_change_the_type_and_the_live_page_waits_for_publish(self) -> None:
        item = self.call("saveItemDraft", save_payload())["item"]
        self.call("publishItem", {"id": item["id"]})
        saved = self.call("saveItemDraft", save_payload(id=item["id"], type="post", newVersion=True, expectedContentHash=item["contentHash"], bodyMarkus="Changed\n"))
        self.assertTrue(saved["ok"])
        self.assertEqual(self.client.tables["Item"][saved["item"]["id"]]["type"], "post")
        self.assertEqual(self.client.tables["Item"][saved["item"]["id"]]["typeStatus"], "post#draft")
        live = self.client.tables["PublishedItem"]["published-" + item["id"]]
        self.assertEqual(live["type"], "article", "the live row keeps its type until the new version is published")
        moved = self.call("publishItem", {"id": saved["item"]["id"]})
        self.assertEqual(moved["typeChangedFrom"], "article")
        self.assertEqual(self.client.tables["PublishedItem"]["published-" + item["id"]]["type"], "post")

    def test_a_new_version_refuses_a_system_type(self) -> None:
        item = self.call("saveItemDraft", save_payload())["item"]
        refused = self.call("saveItemDraft", save_payload(id=item["id"], type="wiki_page", newVersion=True, expectedContentHash=item["contentHash"]))
        self.assertFalse(refused["ok"])
        self.assertIn("not a Story", refused["errors"][0]["message"])

    def test_publishing_the_same_type_reports_no_type_change(self) -> None:
        item = self.call("saveItemDraft", save_payload())["item"]
        self.call("publishItem", {"id": item["id"]})
        saved = self.call("saveItemDraft", save_payload(id=item["id"], newVersion=True, expectedContentHash=item["contentHash"], bodyMarkus="Changed\n"))
        self.assertNotIn("typeChangedFrom", self.call("publishItem", {"id": saved["item"]["id"]}))

    def test_publish_missing_item_is_not_found(self) -> None:
        result = self.call("publishItem", {"id": "item-missing"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["code"], "not-found")

    def test_unexpected_exception_propagates(self) -> None:
        item = self.call("saveItemDraft", save_payload())["item"]
        self.client.fail_after = ("upsert", "PublishedItem")
        with self.assertRaises(RuntimeError):
            self.call("publishItem", {"id": item["id"]})

    def test_unknown_field_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.call("somethingElse", {})

    def test_actor_falls_back_to_unknown(self) -> None:
        self.assertEqual(content_actions_handler.actor_from_event({}), "unknown")
        self.assertEqual(content_actions_handler.actor_from_event({"identity": {"sub": "s"}}), "s")


class ContentActionsSiteTriggerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(dedicated_call())   # the tests call the handler's own functions, which act for one call's tenant
        self.client = FakeAuthoringClient()
        patcher = mock.patch.object(
            content_actions_handler, "create_authoring_client", return_value=(self.client, {})
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        environment = mock.patch.dict(
            "os.environ",
            {"PAPYRUS_READER_AMPLIFY_APP_ID": "reader1", "PAPYRUS_READER_BRANCH": "live"},
            clear=False,
        )
        environment.start()
        self.addCleanup(environment.stop)

    def call(self, field: str, payload, **kwargs) -> dict:
        return content_actions_handler.handler(event(field, payload, **kwargs), None)

    def saved_item_id(self) -> str:
        return self.call("saveItemDraft", save_payload())["item"]["id"]

    def test_changed_publish_starts_a_rebuild(self) -> None:
        item_id = self.saved_item_id()
        with mock.patch.object(
            content_actions_handler, "trigger_rebuild", return_value={"started": True, "jobId": "42"}
        ) as trigger:
            result = self.call("publishItem", {"id": item_id})
        trigger.assert_called_once_with(reader_app_id="reader1", reader_branch="live")
        self.assertTrue(result["ok"])
        self.assertEqual(result["rebuild"], {"started": True, "jobId": "42"})

    def test_unchanged_publish_triggers_nothing(self) -> None:
        item_id = self.saved_item_id()
        self.call("publishItem", {"id": item_id})
        with mock.patch.object(content_actions_handler, "trigger_rebuild") as trigger:
            result = self.call("publishItem", {"id": item_id})
        trigger.assert_not_called()
        self.assertFalse(result["changed"])
        self.assertNotIn("rebuild", result)

    def test_unpublish_starts_a_rebuild(self) -> None:
        item_id = self.saved_item_id()
        self.call("publishItem", {"id": item_id})
        with mock.patch.object(content_actions_handler, "trigger_rebuild", return_value={"started": False, "reason": "pending-job-exists"}):
            result = self.call("unpublishItem", {"id": item_id})
        self.assertEqual(result["rebuild"], {"started": False, "reason": "pending-job-exists"})

    def test_a_failed_trigger_does_not_fail_the_publish(self) -> None:
        item_id = self.saved_item_id()
        failed = {"started": False, "error": "RuntimeError: boom"}
        with mock.patch.object(content_actions_handler, "trigger_rebuild", return_value=failed):
            result = self.call("publishItem", {"id": item_id})
        self.assertTrue(result["ok"])
        self.assertEqual(result["rebuild"], failed)
        self.assertIn(result["publishedId"], self.client.tables["PublishedItem"])

    def test_revalidation_failure_is_reported_and_publish_still_succeeds(self) -> None:
        item_id = self.saved_item_id()
        with mock.patch.dict("os.environ", {"PAPYRUS_REVALIDATE_BASE_URL": "https://reader.test"}), mock.patch.object(
            content_actions_handler, "trigger_pretext_revalidation", side_effect=RuntimeError("down")
        ), mock.patch.object(content_actions_handler, "trigger_rebuild", return_value={"started": True, "jobId": "1"}):
            result = self.call("publishItem", {"id": item_id})
        self.assertTrue(result["ok"])
        self.assertFalse(result["revalidated"]["ok"])
        self.assertTrue(result["rebuild"]["started"])

    def test_revalidation_receives_the_item_slug(self) -> None:
        item_id = self.saved_item_id()
        with mock.patch.dict("os.environ", {"PAPYRUS_REVALIDATE_BASE_URL": "https://reader.test"}), mock.patch.object(
            content_actions_handler, "trigger_pretext_revalidation", return_value={"ok": True}
        ) as revalidate, mock.patch.object(content_actions_handler, "trigger_rebuild", return_value={"started": True}):
            result = self.call("publishItem", {"id": item_id})
        revalidate.assert_called_once_with(["my-post"], None, base_url="https://reader.test")
        self.assertEqual(result["revalidated"], {"ok": True})

    def test_revalidated_paths_are_purged_from_the_configured_distributions(self) -> None:
        item_id = self.saved_item_id()
        revalidated = {"ok": True, "revalidatedPaths": ["/articles/my-post", "/archive"]}
        environment = {"PAPYRUS_REVALIDATE_BASE_URL": "https://reader.test", "PAPYRUS_REVALIDATE_DISTRIBUTION_IDS": "EONE, ETWO"}
        invalidated: list[tuple[str, list[str]]] = []

        def record(distribution_id, paths, _client=None, **_kwargs):
            invalidated.append((distribution_id, list(paths)))
            return list(paths)

        with mock.patch.dict("os.environ", environment), mock.patch.object(
            content_actions_handler, "trigger_pretext_revalidation", return_value=revalidated
        ), mock.patch("papyrus_content.edge_invalidation.invalidate_distribution", side_effect=record), mock.patch.object(
            content_actions_handler, "trigger_rebuild", return_value={"started": True}
        ):
            result = self.call("publishItem", {"id": item_id})
        self.assertEqual(invalidated, [("EONE", ["/articles/my-post", "/archive"]), ("ETWO", ["/articles/my-post", "/archive"])])
        self.assertTrue(result["edgeInvalidated"]["ok"])

    def test_no_distribution_ids_means_no_edge_invalidation(self) -> None:
        item_id = self.saved_item_id()
        with mock.patch.dict("os.environ", {"PAPYRUS_REVALIDATE_BASE_URL": "https://reader.test"}), mock.patch.object(
            content_actions_handler, "trigger_pretext_revalidation", return_value={"ok": True, "revalidatedPaths": ["/a"]}
        ), mock.patch.object(content_actions_handler, "trigger_rebuild", return_value={"started": True}):
            result = self.call("publishItem", {"id": item_id})
        self.assertNotIn("edgeInvalidated", result)

    def test_unconfigured_site_adds_no_trigger_fields(self) -> None:
        item_id = self.saved_item_id()
        with mock.patch.dict("os.environ", {"PAPYRUS_READER_AMPLIFY_APP_ID": ""}):
            result = self.call("publishItem", {"id": item_id})
        self.assertEqual(set(result), {"ok", "changed", "publishedId", "versionNumber"})

    def test_request_staging_build(self) -> None:
        with mock.patch.dict("os.environ", {"PAPYRUS_CMS_AMPLIFY_APP_ID": "cms1"}), mock.patch.object(
            content_actions_handler, "trigger_staging_build", return_value={"started": True, "jobId": "7"}
        ) as trigger:
            result = self.call("requestStagingBuild", {})
        trigger.assert_called_once_with(cms_app_id="cms1", staging_branch="staging")
        self.assertEqual(result, {"ok": True, "build": {"started": True, "jobId": "7"}})

    def test_request_staging_build_without_configuration_fails_cleanly(self) -> None:
        with mock.patch.dict("os.environ", {"PAPYRUS_CMS_AMPLIFY_APP_ID": ""}):
            result = self.call("requestStagingBuild", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["code"], "staging-build-not-configured")

    def held(self):
        from papyrus_content.projection.lease import ProjectionLeaseHeld

        return ProjectionLeaseHeld("site-bucket", "papyrus-projection-locks", {"owner": "cloud", "purpose": "cloud-run projection", "expiresAt": 1}, 120)

    def test_a_held_projection_lease_fails_an_asynchronous_task_so_lambda_retries_it(self) -> None:
        with mock.patch.object(content_actions_handler, "projection_context"), mock.patch.object(
            content_actions_handler, "project_all", side_effect=self.held()
        ):
            with self.assertRaises(content_actions_handler.ProjectionTaskFailed) as raised:
                content_actions_handler.handler({"projectionTask": {"task": "all"}}, None)
        self.assertIn("Projection lease for site-bucket is held by cloud", str(raised.exception))

    def test_a_held_projection_lease_at_publish_time_schedules_a_retry_instead_of_losing_the_projection(self) -> None:
        with mock.patch.dict("os.environ", {"PAPYRUS_PUBLICATION_KIND": "s3-projection"}), mock.patch.object(
            content_actions_handler, "projection_context"
        ), mock.patch.object(content_actions_handler, "project", side_effect=self.held()), mock.patch.object(
            content_actions_handler, "schedule_projection_task"
        ) as schedule:
            result = content_actions_handler.project_item_action(self.client, "item-1", unpublished=False)
        self.assertFalse(result["projected"])
        schedule.assert_called_once()
        self.assertEqual(schedule.call_args.args[0]["task"], "item")
        self.assertIn("ProjectionLeaseHeld", result["error"])


if __name__ == "__main__":
    unittest.main()
