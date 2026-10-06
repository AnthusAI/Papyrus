from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contextlib
import io
import json
import unittest
from unittest import mock

from papyrus_content.markus_renderer.derive import derive_body
from papyrus_content.publishing import (
    ItemFields,
    PublishError,
    columns_from_front_matter,
    item_id_for,
    publish_item,
    save_item,
    unpublish_item,
)
from papyrus_content.publish_commands import content_publish, content_unpublish
from fake_client import FakeAuthoringClient  # noqa: E402

FRONT_MATTER = (
    "title: Forty Billion Dollars Stopped Existing in Four Days\n"
    "standfirst: TerraUSD promised stability.\n"
    "authors:\n  - various bots\n  - Ryan Porter\n"
    'date: "Sunday, September 6, 2026"\n'
)
BODY = "There is an old story.\n"
NOW = "2026-10-05T12:00:00Z"
LATER = "2026-10-06T12:00:00Z"
ITEM_ID = item_id_for("articles", "believe-the-rainbow")


def fields(**changes) -> ItemFields:
    values = dict(
        type="article",
        slug="believe-the-rainbow",
        section="articles",
        front_matter_yaml=FRONT_MATTER,
        body_markus=BODY,
        aliases=[],
        id=ITEM_ID,
        source_path="articles/believe-the-rainbow.md",
    )
    values.update(changes)
    return ItemFields(**values)


def image_body(name: str) -> str:
    return f'{BODY}\n::image{{src="images/{name}" alt="A"}}\n'


def media_row(item_id: str, name: str) -> dict:
    return {
        "id": f"media-{name}",
        "itemId": item_id,
        "type": "image",
        "sortKey": f"001#{name}",
        "storagePath": f"public/{name}",
        "metadata": json.dumps({"srcPath": f"images/{name}"}),
    }


class SaveItemTests(unittest.TestCase):
    def test_item_id_for_section_and_slug(self) -> None:
        self.assertEqual(item_id_for("Articles", "foo"), "item-articles-foo")
        self.assertEqual(item_id_for(None, "foo"), "item-foo")

    def test_columns_from_front_matter(self) -> None:
        columns = columns_from_front_matter(
            {"title": "T", "description": "D", "author": "A", "date": "2026-09-06"}
        )
        self.assertEqual(columns["deck"], "D")
        self.assertEqual(columns["byline"], "A")
        self.assertEqual(columns["publishedAt"], "2026-09-06T00:00:00Z")
        self.assertEqual(columns["sortTitle"], "T")

    def test_save_new_item_is_a_draft_with_derived_columns(self) -> None:
        client = FakeAuthoringClient()
        record = save_item(client, fields(), actor="tester", now=NOW)
        stored = client.tables["Item"][ITEM_ID]
        self.assertEqual(stored["status"], "draft")
        self.assertEqual(stored["typeStatus"], "article#draft")
        self.assertEqual(stored["sectionStatus"], "articles#draft")
        self.assertEqual(stored["lineageId"], ITEM_ID)
        self.assertEqual(stored["versionNumber"], 1)
        self.assertEqual(stored["title"], "Forty Billion Dollars Stopped Existing in Four Days")
        self.assertEqual(stored["deck"], "TerraUSD promised stability.")
        self.assertEqual(stored["byline"], "various bots, Ryan Porter")
        self.assertEqual(stored["publishedAt"], "2026-09-06T00:00:00Z")
        self.assertEqual(json.loads(stored["metadata"])["source"]["path"], "articles/believe-the-rainbow.md")
        self.assertEqual(record["contentHash"], stored["contentHash"])

    def test_stale_expected_hash_conflicts(self) -> None:
        client = FakeAuthoringClient()
        save_item(client, fields(), actor="tester", now=NOW)
        with self.assertRaises(PublishError) as raised:
            save_item(client, fields(body_markus="Changed.\n"), actor="tester", now=NOW, expected_content_hash="sha256:stale")
        self.assertEqual(raised.exception.code, "conflict")
        self.assertEqual(client.tables["Item"][ITEM_ID]["bodyMarkus"], BODY)

    def test_matching_expected_hash_updates_in_place(self) -> None:
        client = FakeAuthoringClient()
        first = save_item(client, fields(), actor="tester", now=NOW)
        second = save_item(
            client, fields(body_markus="Changed.\n"), actor="tester", now=LATER, expected_content_hash=first["contentHash"]
        )
        self.assertNotEqual(first["contentHash"], second["contentHash"])
        self.assertEqual(client.tables["Item"][ITEM_ID]["versionNumber"], 1)
        self.assertEqual(client.tables["Item"][ITEM_ID]["status"], "draft")

    def test_invalid_body_raises_without_writing(self) -> None:
        client = FakeAuthoringClient()
        with self.assertRaises(PublishError) as raised:
            save_item(client, fields(body_markus=":::nope\nText.\n:::\n"), actor="tester", now=NOW)
        self.assertEqual(raised.exception.code, "markus-validation")
        self.assertTrue(raised.exception.errors)
        self.assertEqual(client.write_calls(), [])

    def test_slug_is_locked_after_publish(self) -> None:
        client = FakeAuthoringClient()
        save_item(client, fields(), actor="tester", now=NOW)
        publish_item(client, ITEM_ID, actor="tester", now=NOW)
        with self.assertRaises(PublishError) as raised:
            save_item(client, fields(slug="renamed"), actor="tester", now=LATER)
        self.assertEqual(raised.exception.code, "slug-locked")

    def test_slug_can_change_while_draft(self) -> None:
        client = FakeAuthoringClient()
        save_item(client, fields(), actor="tester", now=NOW)
        save_item(client, fields(slug="renamed"), actor="tester", now=LATER)
        self.assertEqual(client.tables["Item"][ITEM_ID]["slug"], "renamed")


class PublishItemTests(unittest.TestCase):
    def saved(self, **changes) -> FakeAuthoringClient:
        client = FakeAuthoringClient()
        save_item(client, fields(**changes), actor="tester", now=NOW)
        return client

    def test_publish_projects_the_item(self) -> None:
        client = self.saved()
        result = publish_item(client, ITEM_ID, actor="tester", now=NOW)
        self.assertTrue(result.changed)
        published = client.tables["PublishedItem"]["published-" + ITEM_ID]
        expected = derive_body(FRONT_MATTER, BODY).body_ir
        self.assertEqual(json.loads(published["bodyIr"]), expected)
        self.assertEqual(published["versionNumber"], 1)
        self.assertEqual(published["typeStatus"], "article#published")
        self.assertEqual(published["sectionStatus"], "articles#published")
        self.assertEqual(published["sourceItemId"], ITEM_ID)
        self.assertEqual(published["bodyMarkus"], BODY)
        self.assertNotIn("body", published)
        self.assertEqual(
            json.loads(published["metadata"])["sourceContentHash"], client.tables["Item"][ITEM_ID]["contentHash"]
        )
        item = client.tables["Item"][ITEM_ID]
        self.assertEqual(item["status"], "published")
        self.assertEqual(item["typeStatus"], "article#published")

    def test_republish_without_change_writes_nothing(self) -> None:
        client = self.saved()
        publish_item(client, ITEM_ID, actor="tester", now=NOW)
        client.calls.clear()
        result = publish_item(client, ITEM_ID, actor="tester", now=LATER)
        self.assertFalse(result.changed)
        self.assertEqual(client.write_calls(), [])

    def test_edit_and_republish_increments_version(self) -> None:
        client = self.saved()
        publish_item(client, ITEM_ID, actor="tester", now=NOW)
        save_item(client, fields(body_markus="Edited.\n"), actor="tester", now=LATER)
        result = publish_item(client, ITEM_ID, actor="tester", now=LATER)
        self.assertTrue(result.changed)
        self.assertEqual(client.tables["PublishedItem"]["published-" + ITEM_ID]["versionNumber"], 2)
        self.assertEqual(client.tables["Item"][ITEM_ID]["versionNumber"], 2)

    def test_missing_image_blocks_publish(self) -> None:
        client = self.saved(body_markus=image_body("a.png"))
        with self.assertRaises(PublishError) as raised:
            publish_item(client, ITEM_ID, actor="tester", now=NOW)
        self.assertEqual(raised.exception.code, "image-missing")
        self.assertEqual(raised.exception.message, "images/a.png")
        self.assertNotIn("PublishedItem", client.tables)

    def test_media_sync_leaves_exactly_the_current_set(self) -> None:
        client = FakeAuthoringClient({"MediaAsset": [media_row(ITEM_ID, "a.png")]})
        save_item(client, fields(body_markus=image_body("a.png")), actor="tester", now=NOW)
        publish_item(client, ITEM_ID, actor="tester", now=NOW)
        self.assertEqual(set(client.tables["PublishedMediaAsset"]), {"published-media-a.png"})
        row = client.tables["PublishedMediaAsset"]["published-media-a.png"]
        self.assertEqual(row["publishedItemId"], "published-" + ITEM_ID)
        self.assertEqual(row["sourceMediaAssetId"], "media-a.png")

        client.tables["MediaAsset"]["media-b.png"] = media_row(ITEM_ID, "b.png")
        del client.tables["MediaAsset"]["media-a.png"]
        save_item(client, fields(body_markus=image_body("b.png")), actor="tester", now=LATER)
        result = publish_item(client, ITEM_ID, actor="tester", now=LATER)
        self.assertEqual(set(client.tables["PublishedMediaAsset"]), {"published-media-b.png"})
        self.assertEqual(result.deleted_media_ids, ["published-media-a.png"])

    def test_unpublish_removes_published_rows(self) -> None:
        client = FakeAuthoringClient({"MediaAsset": [media_row(ITEM_ID, "a.png")]})
        save_item(client, fields(body_markus=image_body("a.png")), actor="tester", now=NOW)
        publish_item(client, ITEM_ID, actor="tester", now=NOW)
        result = unpublish_item(client, ITEM_ID, actor="tester", now=LATER)
        self.assertTrue(result.changed)
        self.assertEqual(client.tables["PublishedItem"], {})
        self.assertEqual(client.tables["PublishedMediaAsset"], {})
        item = client.tables["Item"][ITEM_ID]
        self.assertEqual(item["status"], "draft")
        self.assertEqual(item["typeStatus"], "article#draft")
        self.assertEqual(item["sectionStatus"], "articles#draft")

    def test_unpublish_twice_is_idempotent(self) -> None:
        client = self.saved()
        publish_item(client, ITEM_ID, actor="tester", now=NOW)
        unpublish_item(client, ITEM_ID, actor="tester", now=LATER)
        client.calls.clear()
        result = unpublish_item(client, ITEM_ID, actor="tester", now=LATER)
        self.assertFalse(result.changed)
        self.assertEqual(client.write_calls(), [])

    def test_unknown_item_is_not_found(self) -> None:
        with self.assertRaises(PublishError) as raised:
            publish_item(FakeAuthoringClient(), "item-missing", actor="tester", now=NOW)
        self.assertEqual(raised.exception.code, "not-found")

    def test_interrupted_publish_converges_on_rerun(self) -> None:
        interrupted = self.saved()
        interrupted.fail_after = ("upsert", "PublishedItem")
        with self.assertRaises(RuntimeError):
            publish_item(interrupted, ITEM_ID, actor="tester", now=NOW)
        self.assertEqual(interrupted.tables["Item"][ITEM_ID]["status"], "draft")
        publish_item(interrupted, ITEM_ID, actor="tester", now=NOW)

        clean = self.saved()
        publish_item(clean, ITEM_ID, actor="tester", now=NOW)
        self.assertEqual(interrupted.tables["PublishedItem"], clean.tables["PublishedItem"])
        self.assertEqual(interrupted.tables["Item"], clean.tables["Item"])


class PublishCommandTests(unittest.TestCase):
    def run_command(self, command, client, flags):
        output = io.StringIO()
        with mock.patch("papyrus_content.publish_commands.create_authoring_client", return_value=(client, {})):
            with contextlib.redirect_stdout(output):
                command(flags)
        return json.loads(output.getvalue())

    def test_dry_run_prints_planned_ids_and_writes_nothing(self) -> None:
        client = FakeAuthoringClient()
        save_item(client, fields(), actor="tester", now=NOW)
        client.calls.clear()
        payload = self.run_command(content_publish, client, ["--id", ITEM_ID, "--dry-run", "--json"])
        self.assertTrue(payload["dryRun"])
        self.assertEqual(
            [(entry["model"], entry["id"]) for entry in payload["planned"]],
            [("PublishedItem", "published-" + ITEM_ID), ("Item", ITEM_ID)],
        )
        self.assertEqual(client.write_calls(), [])
        self.assertEqual(client.tables.get("PublishedItem"), {})

    def test_publish_by_slug_then_unpublish(self) -> None:
        client = FakeAuthoringClient()
        save_item(client, fields(), actor="tester", now=NOW)
        payload = self.run_command(content_publish, client, ["--slug", "believe-the-rainbow", "--json"])
        self.assertTrue(payload["changed"])
        self.assertIn("published-" + ITEM_ID, client.tables["PublishedItem"])
        payload = self.run_command(content_unpublish, client, ["--slug", "believe-the-rainbow", "--section", "articles", "--json"])
        self.assertTrue(payload["changed"])
        self.assertEqual(client.tables["PublishedItem"], {})

    def test_ambiguous_slug_asks_for_id(self) -> None:
        client = FakeAuthoringClient()
        save_item(client, fields(), actor="tester", now=NOW)
        save_item(client, fields(id="item-other", section="notes"), actor="tester", now=NOW)
        with self.assertRaises(ValueError) as raised:
            self.run_command(content_publish, client, ["--slug", "believe-the-rainbow", "--json"])
        self.assertIn("--id", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
