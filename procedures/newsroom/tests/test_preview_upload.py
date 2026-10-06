import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.preview_upload import PreviewUploadError, upload_preview  # noqa: E402
from procedures.newsroom.tests.fake_s3 import FakeS3Client  # noqa: E402

BUCKET = "media-bucket"


class PreviewUploadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = Path(self.temp.name)
        (self.site / "articles").mkdir()
        (self.site / "index.html").write_text("<h1>Home</h1>", encoding="utf-8")
        (self.site / "articles" / "foo.html").write_text("<p>Foo</p>", encoding="utf-8")
        (self.site / "style.css").write_text("body{}", encoding="utf-8")
        self.client = FakeS3Client()

    def test_first_upload_writes_every_file_with_type_and_cache_headers(self) -> None:
        report = upload_preview(self.client, BUCKET, self.site)
        self.assertEqual(
            sorted(self.client.objects),
            ["preview/articles/foo.html", "preview/index.html", "preview/style.css"],
        )
        self.assertEqual(len(report.uploaded), 3)
        self.assertEqual(self.client.objects["preview/index.html"]["ContentType"], "text/html")
        self.assertEqual(self.client.objects["preview/style.css"]["ContentType"], "text/css")
        self.assertEqual(self.client.objects["preview/index.html"]["CacheControl"], "no-store")
        self.assertEqual(len(self.client.objects["preview/index.html"]["Metadata"]["sha256"]), 64)

    def test_second_upload_sends_only_changed_files(self) -> None:
        upload_preview(self.client, BUCKET, self.site)
        self.client.put_keys.clear()
        (self.site / "index.html").write_text("<h1>Home 2</h1>", encoding="utf-8")
        report = upload_preview(self.client, BUCKET, self.site)
        self.assertEqual(self.client.put_keys, ["preview/index.html"])
        self.assertEqual(sorted(report.unchanged), ["preview/articles/foo.html", "preview/style.css"])

    def test_stale_keys_under_the_prefix_are_deleted_and_others_kept(self) -> None:
        upload_preview(self.client, BUCKET, self.site)
        self.client.objects["preview/old.html"] = {"Body": b"x", "Metadata": {}}
        self.client.objects["media/keep.png"] = {"Body": b"x", "Metadata": {}}
        report = upload_preview(self.client, BUCKET, self.site)
        self.assertEqual(report.deleted, ["preview/old.html"])
        self.assertNotIn("preview/old.html", self.client.objects)
        self.assertIn("media/keep.png", self.client.objects)

    def test_pagination_covers_all_stale_keys(self) -> None:
        self.client.page_size = 2
        for number in range(5):
            self.client.objects[f"preview/stale-{number}.html"] = {"Body": b"x", "Metadata": {}}
        report = upload_preview(self.client, BUCKET, self.site)
        self.assertEqual(len(report.deleted), 5)

    def test_other_prefix_is_refused(self) -> None:
        with self.assertRaisesRegex(PreviewUploadError, "only"):
            upload_preview(self.client, BUCKET, self.site, "media/")
        self.assertEqual(self.client.objects, {})

    def test_empty_directory_is_refused_and_nothing_is_deleted(self) -> None:
        self.client.objects["preview/index.html"] = {"Body": b"x", "Metadata": {}}
        empty = Path(self.temp.name) / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(PreviewUploadError, "empty"):
            upload_preview(self.client, BUCKET, empty)
        self.assertIn("preview/index.html", self.client.objects)


if __name__ == "__main__":
    unittest.main()
