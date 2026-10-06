import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.markus_export import (  # noqa: E402
    EmptyExportError,
    ExportError,
    export_content,
    item_output_path,
)
from papyrus_content.markus_import import DirMediaStore  # noqa: E402
from papyrus_content.publishing import ItemFields, publish_item, save_item  # noqa: E402
from papyrus_content.record_helpers import to_aws_json  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

NOW = "2026-10-05T12:00:00Z"
IMAGE_BYTES = b"\x89PNG-fake-bytes"


def add_item(client, slug, *, section="articles", item_type="article", publish=True, aliases=None, source_path=None, body="Body text.\n"):
    fields = ItemFields(
        type=item_type,
        slug=slug,
        section=section,
        front_matter_yaml=f"title: {slug.title()}\n",
        body_markus=body,
        aliases=aliases or [],
        id=f"item-{section or 'root'}-{slug}",
        source_path=source_path,
    )
    save_item(client, fields, actor="test", now=NOW)
    if publish:
        publish_item(client, fields.id, actor="test", now=NOW)
    return fields.id


def add_media(client, item_id, src_path, *, published):
    sha = hashlib.sha256(IMAGE_BYTES).hexdigest()
    metadata = to_aws_json({"srcPath": src_path, "sha256": sha})
    client.upsert(
        "MediaAsset",
        {"id": f"media-{item_id}", "itemId": item_id, "type": "image", "sortKey": "000", "storagePath": f"media/{src_path}", "metadata": metadata},
    )
    if published:
        lineage = client.get_record("Item", item_id)["lineageId"]
        client.upsert(
            "PublishedMediaAsset",
            {"id": f"published-media-{item_id}", "publishedItemId": f"published-{lineage}", "type": "image", "sortKey": "000", "storagePath": f"media/{src_path}", "metadata": metadata},
        )


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "out"
        self.store = DirMediaStore(self.root / "bucket")
        (self.root / "bucket" / "media" / "assets").mkdir(parents=True)
        (self.root / "bucket" / "media" / "assets" / "a.png").write_bytes(IMAGE_BYTES)
        self.client = FakeAuthoringClient()

    def export(self, **kwargs):
        kwargs.setdefault("drafts", False)
        return export_content(self.client, self.store, self.out, now=NOW, **kwargs)

    def test_published_mode_excludes_drafts_and_unpublished(self):
        add_item(self.client, "live")
        add_item(self.client, "draft-only", publish=False)
        self.export()
        self.assertTrue((self.out / "articles" / "live.md").exists())
        self.assertFalse((self.out / "articles" / "draft-only.md").exists())

    def test_drafts_mode_includes_unpublished(self):
        add_item(self.client, "live")
        add_item(self.client, "draft-only", publish=False)
        report = self.export(drafts=True)
        self.assertEqual(report.mode, "drafts")
        self.assertTrue((self.out / "articles" / "draft-only.md").exists())
        manifest = json.loads((self.out / "_papyrus" / "manifest.json").read_text())
        self.assertEqual(manifest["mode"], "drafts")

    def test_other_item_types_are_not_exported(self):
        add_item(self.client, "live")
        add_item(self.client, "doc", item_type="doctrine", section="doctrine")
        self.export(drafts=True)
        self.assertFalse((self.out / "doctrine").exists())

    def test_source_path_is_kept_when_section_matches(self):
        item = {"section": "articles", "slug": "x", "metadata": json.dumps({"source": {"path": "articles/Call Criteria.md"}})}
        self.assertEqual(item_output_path(item), "articles/Call Criteria.md")

    def test_draft_directory_item_exports_under_its_section(self):
        add_item(self.client, "wip", source_path="drafts/wip.md")
        self.export()
        self.assertTrue((self.out / "articles" / "wip.md").exists())
        self.assertFalse((self.out / "drafts").exists())

    def test_root_page_exports_to_root(self):
        add_item(self.client, "index", section=None, item_type="page", source_path="index.md")
        self.export()
        self.assertTrue((self.out / "index.md").exists())

    def test_file_text_is_front_matter_plus_verbatim_body(self):
        add_item(self.client, "live", body="Line one.\n\n\nLine two.\n")
        self.export()
        self.assertEqual((self.out / "articles" / "live.md").read_text(), "---\ntitle: Live\n---\nLine one.\n\n\nLine two.\n")

    def test_duplicate_path_error_lists_both(self):
        add_item(self.client, "one", source_path="articles/same.md")
        add_item(self.client, "two", source_path="articles/same.md")
        with self.assertRaises(ExportError) as caught:
            self.export()
        self.assertIn("item-articles-one", str(caught.exception))
        self.assertIn("item-articles-two", str(caught.exception))

    def test_path_traversal_is_rejected(self):
        for bad in ("../evil.md", "/abs.md", "articles/x.txt"):
            with self.subTest(bad=bad):
                client = FakeAuthoringClient()
                add_item(client, "x", source_path=bad)
                with self.assertRaises(ExportError):
                    export_content(client, self.store, self.out, drafts=False)

    def test_empty_export_fails_unless_allowed(self):
        with self.assertRaises(EmptyExportError):
            self.export()
        self.assertFalse(self.out.exists())
        report = self.export(allow_empty=True)
        self.assertEqual(report.items, [])

    def test_media_is_downloaded_and_unchanged_files_are_skipped(self):
        item_id = add_item(self.client, "live")
        add_media(self.client, item_id, "assets/a.png", published=True)
        first = self.export()
        self.assertEqual((first.mediaDownloaded, first.mediaSkipped), (1, 0))
        self.assertEqual((self.out / "assets" / "a.png").read_bytes(), IMAGE_BYTES)
        second = self.export()
        self.assertEqual((second.mediaDownloaded, second.mediaSkipped), (0, 1))

    def test_drafts_mode_reads_draft_media(self):
        item_id = add_item(self.client, "wip", publish=False)
        add_media(self.client, item_id, "assets/a.png", published=False)
        self.export(drafts=True)
        self.assertTrue((self.out / "assets" / "a.png").exists())

    def test_manifest_and_redirects(self):
        item_id = add_item(self.client, "hello", aliases=["/blog/hello-old"])
        add_media(self.client, item_id, "assets/a.png", published=True)
        add_item(self.client, "index", section=None, item_type="page", aliases=["/old-home"])
        self.export(site="pilobol-us")
        manifest = json.loads((self.out / "_papyrus" / "manifest.json").read_text())
        self.assertEqual(manifest["contract"], "papyrus-export/v1")
        self.assertEqual(manifest["site"], "pilobol-us")
        entry = next(row for row in manifest["items"] if row["slug"] == "hello")
        self.assertEqual(entry["path"], "articles/hello.md")
        self.assertEqual(entry["versionNumber"], 1)
        self.assertTrue(entry["contentHash"].startswith("sha256:"))
        self.assertEqual(manifest["media"][0]["storagePath"], "media/assets/a.png")
        redirects = json.loads((self.out / "_papyrus" / "redirects.json").read_text())
        self.assertIn({"from": "/blog/hello-old", "to": "/articles/hello.html", "status": 301}, redirects)
        self.assertIn({"from": "/old-home", "to": "/index.html", "status": 301}, redirects)

    def test_graphql_error_propagates(self):
        add_item(self.client, "live")

        def boom(_model):
            raise RuntimeError("GraphQL outage")

        self.client.list_records = boom
        with self.assertRaises(RuntimeError):
            self.export()

    def test_clean_removes_stale_files_and_refuses_unsafe_targets(self):
        add_item(self.client, "live")
        self.out.mkdir()
        (self.out / "stale.txt").write_text("x")
        self.export(clean=True)
        self.assertFalse((self.out / "stale.txt").exists())
        (self.out / ".git").mkdir()
        with self.assertRaises(ExportError):
            self.export(clean=True)
        with self.assertRaises(ExportError):
            export_content(self.client, self.store, Path("/"), drafts=False, clean=True)
        with self.assertRaises(ExportError):
            export_content(self.client, self.store, Path.home(), drafts=False, clean=True)


class CommandTests(unittest.TestCase):
    def run_command(self, client, flags):
        from unittest import mock

        from papyrus_content import markus_export_commands

        with mock.patch.object(markus_export_commands, "create_authoring_client", return_value=(client, {})):
            markus_export_commands.content_export_published(flags)

    def test_empty_backend_exits_one_with_no_items(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit) as caught:
                self.run_command(FakeAuthoringClient(), ["--out", str(Path(tmp) / "x"), "--json"])
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("no items", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
