"""CLI publish, unpublish, import-markus and set-slug project s3-projection sites like the newsroom does."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contextlib
import io
import json
import unittest
from unittest import mock

from papyrus_content.publish_commands import content_publish, content_unpublish
from papyrus_content.publishing import ItemFields, publish_item, save_item
from papyrus_content.story_commands import stories_set_slug
from fake_client import FakeAuthoringClient  # noqa: E402

NOW = "2026-10-05T12:00:00Z"
PROJECTING = {"PAPYRUS_PUBLICATION_KIND": "s3-projection", "PAPYRUS_CONTENT_ACTIONS_FUNCTION": "content-actions-fn"}


def item_fields(slug: str = "hello", item_id: str = "item-articles-hello", section: str = "articles") -> ItemFields:
    return ItemFields(
        type="article", slug=slug, section=section, front_matter_yaml="title: Hello\n",
        body_markus="Hello.\n", aliases=[], id=item_id,
    )


def run(command, client, flags, environment):
    output = io.StringIO()
    with mock.patch.dict("os.environ", environment, clear=False), \
            mock.patch("papyrus_content.publish_commands.create_authoring_client", return_value=(client, {})), \
            mock.patch("papyrus_content.story_commands.create_authoring_client", return_value=(client, {})), \
            mock.patch("papyrus_content.projection_trigger._invoke_lambda") as invoke, \
            contextlib.redirect_stdout(output):
        command(flags)
    return output.getvalue(), invoke


class PublishProjectionTests(unittest.TestCase):
    def saved(self) -> FakeAuthoringClient:
        client = FakeAuthoringClient()
        save_item(client, item_fields(), actor="t", now=NOW)
        return client

    def test_publish_schedules_one_item_projection(self) -> None:
        client = self.saved()
        _out, invoke = run(content_publish, client, ["--id", "item-articles-hello", "--json"], PROJECTING)
        invoke.assert_called_once_with(
            "content-actions-fn",
            {"projectionTask": {"task": "item", "itemId": "item-articles-hello", "unpublished": False}},
        )

    def test_unpublish_schedules_unpublished_projection(self) -> None:
        client = self.saved()
        publish_item(client, "item-articles-hello", actor="t", now=NOW)
        _out, invoke = run(content_unpublish, client, ["--id", "item-articles-hello", "--json"], PROJECTING)
        invoke.assert_called_once_with(
            "content-actions-fn",
            {"projectionTask": {"task": "item", "itemId": "item-articles-hello", "unpublished": True}},
        )

    def test_no_trigger_prints_one_skip_line_naming_the_command(self) -> None:
        client = self.saved()
        out, invoke = run(content_publish, client, ["--id", "item-articles-hello", "--no-trigger"], PROJECTING)
        invoke.assert_not_called()
        skip_lines = [line for line in out.splitlines() if "projection skipped" in line]
        self.assertEqual(len(skip_lines), 1)
        self.assertIn("papyrus ops content project --all", skip_lines[0])

    def test_dry_run_projects_nothing(self) -> None:
        client = self.saved()
        _out, invoke = run(content_publish, client, ["--id", "item-articles-hello", "--dry-run", "--json"], PROJECTING)
        invoke.assert_not_called()

    def test_other_publication_kinds_keep_revalidation(self) -> None:
        client = self.saved()
        with mock.patch("papyrus_content.publish_commands.trigger_pretext_revalidation", return_value={"ok": True}) as revalidate:
            _out, invoke = run(content_publish, client, ["--id", "item-articles-hello", "--json"], {"PAPYRUS_PUBLICATION_KIND": ""})
        revalidate.assert_called_once()
        invoke.assert_not_called()

    def test_projection_failure_does_not_fail_the_publish(self) -> None:
        client = self.saved()
        output = io.StringIO()
        with mock.patch.dict("os.environ", PROJECTING), \
                mock.patch("papyrus_content.publish_commands.create_authoring_client", return_value=(client, {})), \
                mock.patch("papyrus_content.projection_trigger._invoke_lambda", side_effect=RuntimeError("denied")), \
                contextlib.redirect_stdout(output):
            content_publish(["--id", "item-articles-hello", "--json"])
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["projection"]["ok"])


class SetSlugTests(unittest.TestCase):
    def client(self) -> FakeAuthoringClient:
        client = FakeAuthoringClient()
        save_item(client, item_fields(), actor="t", now=NOW)
        save_item(client, item_fields("taken", "item-articles-taken"), actor="t", now=NOW)
        return client

    def test_rename_updates_the_draft(self) -> None:
        client = self.client()
        out, invoke = run(stories_set_slug, client, ["--story", "item-articles-hello", "--slug", "better-name"], PROJECTING)
        self.assertEqual(client.tables["Item"]["item-articles-hello"]["slug"], "better-name")
        invoke.assert_not_called()
        self.assertIn("better-name", out)

    def test_dry_run_changes_nothing(self) -> None:
        client = self.client()
        run(stories_set_slug, client, ["--story", "item-articles-hello", "--slug", "better-name", "--dry-run"], PROJECTING)
        self.assertEqual(client.tables["Item"]["item-articles-hello"]["slug"], "hello")

    def test_rejects_duplicate_in_the_publication(self) -> None:
        client = self.client()
        with self.assertRaises(ValueError) as raised:
            run(stories_set_slug, client, ["--story", "item-articles-hello", "--slug", "taken"], PROJECTING)
        self.assertIn("already used", str(raised.exception))

    def test_rejects_bad_format(self) -> None:
        client = self.client()
        with self.assertRaises(ValueError):
            run(stories_set_slug, client, ["--story", "item-articles-hello", "--slug", "Bad Slug!"], PROJECTING)

    def test_refuses_published_without_force(self) -> None:
        client = self.client()
        publish_item(client, "item-articles-hello", actor="t", now=NOW)
        with self.assertRaises(ValueError) as raised:
            run(stories_set_slug, client, ["--story", "item-articles-hello", "--slug", "better-name"], PROJECTING)
        self.assertIn("--force", str(raised.exception))
        self.assertEqual(client.tables["Item"]["item-articles-hello"]["slug"], "hello")

    def test_force_renames_published_keeps_old_address_as_alias_and_projects(self) -> None:
        client = self.client()
        publish_item(client, "item-articles-hello", actor="t", now=NOW)
        _out, invoke = run(
            stories_set_slug, client, ["--story", "item-articles-hello", "--slug", "better-name", "--force"], PROJECTING
        )
        item = client.tables["Item"]["item-articles-hello"]
        self.assertEqual(item["slug"], "better-name")
        self.assertIn("hello", item["aliases"])
        self.assertEqual(client.tables["PublishedItem"]["published-item-articles-hello"]["slug"], "better-name")
        invoke.assert_called_once()


class ImportProjectionTests(unittest.TestCase):
    def test_batch_publish_schedules_one_projection_run(self) -> None:
        from papyrus_content import markus_import_commands as commands

        report = mock.Mock(ok=True)
        report.to_dict.return_value = {
            "ok": True, "published": 3, "created": 3, "updated": 0, "unchanged": 0, "skippedEditedInCms": 0,
            "mediaUploaded": 0, "mediaUnchanged": 0, "readerOwnedAssets": 0, "notInSource": 0, "errors": [],
        }
        for flags, expected_calls in ((["--content-dir", "x", "--json"], 1), (["--content-dir", "x", "--json", "--no-trigger"], 0)):
            output = io.StringIO()
            with mock.patch.dict("os.environ", PROJECTING), \
                    mock.patch.object(commands, "create_authoring_client", return_value=(FakeAuthoringClient(), {})), \
                    mock.patch.object(commands, "configured_media_bucket", return_value="b"), \
                    mock.patch.object(commands, "S3MediaStore"), mock.patch.object(commands, "plan_import"), \
                    mock.patch.object(commands, "run_import", return_value=report), \
                    mock.patch("papyrus_content.projection_trigger._invoke_lambda") as invoke, \
                    contextlib.redirect_stdout(output):
                commands.content_import_markus(flags)
            self.assertEqual(invoke.call_count, expected_calls)
            if expected_calls:
                invoke.assert_called_once_with("content-actions-fn", {"projectionTask": {"task": "all"}})


if __name__ == "__main__":
    unittest.main()
