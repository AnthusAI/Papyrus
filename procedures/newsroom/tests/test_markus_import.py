from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from unittest import mock

from papyrus_content.markus_import import DirMediaStore, ImportOptions, plan_import, run_import
from papyrus_content.markus_import_commands import content_import_markus, parse_draft_dirs
from papyrus_content.publishing import ItemFields, save_item
from fake_client import FakeAuthoringClient  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "markus-content"


class ImportTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.content = self.temp / "content"
        shutil.copytree(FIXTURE, self.content)
        self.store = DirMediaStore(self.temp / "bucket")
        self.client = FakeAuthoringClient()

    def options(self, **changes) -> ImportOptions:
        values = dict(content_dir=self.content, draft_dirs={"drafts": "articles"})
        values.update(changes)
        return ImportOptions(**values)

    def run_import(self, **changes):
        options = self.options(**changes.pop("options", {}))
        plan = plan_import(options, self.client, self.store)
        return run_import(plan, self.client, self.store, apply=changes.pop("apply", True))


class ImportTests(ImportTestCase):
    def test_fixture_imports_expected_counts(self) -> None:
        report = self.run_import()
        self.assertTrue(report.ok, report.errors)
        self.assertEqual((report.created, report.updated, report.unchanged), (5, 0, 0))
        self.assertEqual(report.published, 4)
        self.assertEqual((report.media_uploaded, report.reader_owned_assets), (1, 1))
        item = self.client.get_record("Item", "item-articles-hello")
        self.assertEqual(item["status"], "published")
        self.assertEqual(item["aliases"], ["/blog/hello-old"])
        metadata = json.loads(item["metadata"])
        self.assertEqual(metadata["source"]["path"], "articles/hello.md")
        self.assertEqual(metadata["source"]["importedContentHash"], item["contentHash"])
        self.assertTrue(metadata["frontMatterYaml"].startswith("title: Hello Fixture"))
        self.assertIn("::citations", item["bodyMarkus"])
        media = self.client.list_by_index("mediaAssetsByItemAndSortKey", "item-articles-hello")
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]["role"], "cover")
        self.assertEqual(media[0]["storagePath"], "media/assets/hello/a.png")
        self.assertEqual((media[0]["width"], media[0]["height"]), (40, 30))
        self.assertTrue((self.temp / "bucket" / "media" / "assets" / "hello" / "a.png").is_file())
        self.assertEqual(
            len(self.client.list_by_index("publishedMediaAssetsByItemAndSortKey", "published-item-articles-hello")), 1
        )

    def test_call_criteria_slug_and_types(self) -> None:
        self.run_import()
        self.assertEqual(self.client.get_record("Item", "item-articles-call-criteria")["slug"], "call-criteria")
        self.assertEqual(self.client.get_record("Item", "item-index")["type"], "page")
        self.assertEqual(self.client.get_record("Item", "item-articles-index")["type"], "article")

    def test_draft_dir_item_is_draft_without_published_item(self) -> None:
        self.run_import()
        draft = self.client.get_record("Item", "item-articles-wip")
        self.assertEqual(draft["status"], "draft")
        self.assertEqual(json.loads(draft["metadata"])["source"]["path"], "drafts/wip.md")
        self.assertIsNone(self.client.get_record("PublishedItem", "published-item-articles-wip"))

    def test_no_publish_leaves_everything_draft(self) -> None:
        report = self.run_import(options={"publish": False})
        self.assertEqual(report.published, 0)
        self.assertEqual(self.client.list_records("PublishedItem"), [])
        self.assertTrue(all(row["status"] == "draft" for row in self.client.list_records("Item")))

    def test_dry_run_writes_nothing(self) -> None:
        report = self.run_import(apply=False)
        self.assertEqual(report.created, 5)
        self.assertEqual(self.client.write_calls(), [])
        self.assertFalse((self.temp / "bucket").exists())

    def test_rerun_is_idempotent(self) -> None:
        self.run_import()
        self.client.calls.clear()
        report = self.run_import()
        self.assertEqual((report.created, report.updated, report.unchanged), (0, 0, 5))
        self.assertEqual(report.media_uploaded, 0)
        self.assertEqual(report.media_unchanged, 1)
        self.assertEqual(self.client.write_calls(), [])

    def test_changed_source_updates_and_republishes(self) -> None:
        self.run_import()
        path = self.content / "articles" / "hello.md"
        path.write_text(path.read_text().replace("A first paragraph", "An edited paragraph"))
        report = self.run_import()
        self.assertEqual((report.created, report.updated, report.unchanged), (0, 1, 4))
        self.assertEqual(self.client.get_record("PublishedItem", "published-item-articles-hello")["versionNumber"], 2)
        item = self.client.get_record("Item", "item-articles-hello")
        self.assertEqual(json.loads(item["metadata"])["source"]["importedContentHash"], item["contentHash"])

    def edit_in_cms(self) -> None:
        item = self.client.get_record("Item", "item-articles-hello")
        metadata = json.loads(item["metadata"])
        save_item(
            self.client,
            ItemFields(
                type="article",
                slug="hello",
                section="articles",
                front_matter_yaml=metadata["frontMatterYaml"],
                body_markus="Edited in the CMS.\n",
                aliases=["/blog/hello-old"],
                id="item-articles-hello",
            ),
            actor="editor",
        )

    def test_cms_edit_is_not_overwritten_unless_forced(self) -> None:
        self.run_import()
        self.edit_in_cms()
        path = self.content / "articles" / "hello.md"
        path.write_text(path.read_text().replace("A first paragraph", "A source change"))
        report = self.run_import()
        self.assertEqual(report.skipped_edited_in_cms, ["item-articles-hello"])
        self.assertEqual(self.client.get_record("Item", "item-articles-hello")["bodyMarkus"], "Edited in the CMS.\n")
        forced = self.run_import(options={"force": True})
        self.assertEqual(forced.updated, 1)
        self.assertIn("A source change", self.client.get_record("Item", "item-articles-hello")["bodyMarkus"])


class ValidationTests(ImportTestCase):
    def assert_aborts(self, expected: str, **changes) -> list[str]:
        report = self.run_import(**changes)
        self.assertFalse(report.ok)
        self.assertTrue(any(expected in message for message in report.errors), report.errors)
        self.assertEqual(self.client.write_calls(), [])
        self.assertFalse((self.temp / "bucket").exists())
        return report.errors

    def test_slug_collision_names_both_files(self) -> None:
        (self.content / "articles" / "A b.md").write_text("---\ntitle: One\n---\nOne.\n")
        (self.content / "articles" / "a-b.md").write_text("---\ntitle: Two\n---\nTwo.\n")
        errors = self.assert_aborts("slug collision")
        collision = next(message for message in errors if "slug collision" in message)
        self.assertIn("A b.md", collision)
        self.assertIn("a-b.md", collision)

    def test_alias_equal_to_canonical_path_aborts(self) -> None:
        path = self.content / "articles" / "hello.md"
        path.write_text(path.read_text().replace("/blog/hello-old", "/articles/call-criteria.html"))
        self.assert_aborts("shadows")

    def test_alias_must_start_with_slash(self) -> None:
        aliases = self.temp / "aliases.json"
        aliases.write_text(json.dumps({"articles/hello": ["no-slash"]}))
        self.assert_aborts("must start with /", options={"aliases_file": aliases})

    def test_aliases_file_adds_aliases(self) -> None:
        aliases = self.temp / "aliases.json"
        aliases.write_text(json.dumps({"articles/call-criteria": ["/old/criteria"], "index": ["/home"]}))
        self.run_import(options={"aliases_file": aliases})
        self.assertEqual(self.client.get_record("Item", "item-articles-call-criteria")["aliases"], ["/old/criteria"])
        self.assertEqual(self.client.get_record("Item", "item-index")["aliases"], ["/home"])

    def test_missing_image_aborts(self) -> None:
        (self.content / "assets" / "hello" / "a.png").unlink()
        self.assert_aborts("image-missing")

    def test_unknown_directive_aborts_with_file_and_code(self) -> None:
        (self.content / "articles" / "bad.md").write_text("---\ntitle: Bad\n---\n::nope{x=1}\n")
        errors = self.assert_aborts("articles/bad.md")
        self.assertTrue(any("markus-validation" in message for message in errors), errors)

    def test_not_in_source_is_counted_not_deleted(self) -> None:
        self.run_import()
        (self.content / "articles" / "Call Criteria.md").unlink()
        report = self.run_import()
        self.assertEqual(report.not_in_source, 1)
        self.assertIsNotNone(self.client.get_record("Item", "item-articles-call-criteria"))


class CommandTests(unittest.TestCase):
    def test_parse_draft_dirs(self) -> None:
        self.assertEqual(parse_draft_dirs("drafts=articles,x=y"), {"drafts": "articles", "x": "y"})
        with self.assertRaises(ValueError):
            parse_draft_dirs("drafts")

    def test_command_dry_run_json_with_fake_client(self) -> None:
        client = FakeAuthoringClient()
        buffer = io.StringIO()
        with mock.patch("papyrus_content.markus_import_commands.create_authoring_client", return_value=(client, {})), \
                mock.patch("papyrus_content.markus_import_commands.configured_media_bucket", return_value=None), \
                contextlib.redirect_stdout(buffer):
            content_import_markus(
                ["--content-dir", str(FIXTURE), "--draft-dirs", "drafts=articles", "--dry-run", "--json"]
            )
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual((payload["created"], payload["mediaUploaded"], payload["readerOwnedAssets"]), (5, 1, 1))
        self.assertEqual(client.write_calls(), [])

    def test_command_exits_one_on_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "bad.md").write_text("---\ntitle: Bad\n---\n::nope{}\n")
            with mock.patch(
                "papyrus_content.markus_import_commands.create_authoring_client",
                return_value=(FakeAuthoringClient(), {}),
            ), mock.patch(
                "papyrus_content.markus_import_commands.configured_media_bucket", return_value=None
            ), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    content_import_markus(["--content-dir", directory, "--dry-run", "--json"])
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
