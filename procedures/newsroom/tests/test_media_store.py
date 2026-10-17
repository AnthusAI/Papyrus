from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from botocore.exceptions import ClientError

from papyrus_content.media_store import S3MediaStore, configured_media_bucket
from papyrus_content.videoml.commands import create_default_media_store


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.put_calls = 0

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {"Metadata": self.objects[Key]["Metadata"]}

    def put_object(self, Bucket, Key, Body, ContentType, Metadata):
        self.put_calls += 1
        self.objects[Key] = {"Body": Body.read(), "ContentType": ContentType, "Metadata": Metadata}

    def download_file(self, Bucket, Key, Filename):
        Path(Filename).write_bytes(self.objects[Key]["Body"])


class S3MediaStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeS3Client()
        self.store = S3MediaStore("test-bucket", client=self.client)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.local = Path(self.directory.name) / "figure.png"
        self.local.write_bytes(b"png-bytes")
        self.sha = hashlib.sha256(b"png-bytes").hexdigest()

    def test_put_uploads_then_is_idempotent(self) -> None:
        path = "media/articles/a/figure.png"
        self.assertEqual(self.store.put(path, self.local, content_type="image/png", sha256=self.sha), "uploaded")
        self.assertEqual(self.store.put(path, self.local, content_type="image/png", sha256=self.sha), "unchanged")
        self.assertEqual(self.client.put_calls, 1)
        self.assertEqual(self.client.objects[path]["Metadata"], {"sha256": self.sha})
        self.assertEqual(self.client.objects[path]["ContentType"], "image/png")

    def test_changed_content_reuploads(self) -> None:
        path = "media/articles/a/figure.png"
        self.store.put(path, self.local, content_type="image/png", sha256=self.sha)
        self.local.write_bytes(b"new")
        new_sha = hashlib.sha256(b"new").hexdigest()
        self.assertEqual(self.store.put(path, self.local, content_type="image/png", sha256=new_sha), "uploaded")
        self.assertEqual(self.client.put_calls, 2)

    def test_has_false_when_missing(self) -> None:
        self.assertFalse(self.store.has("media/x.png", self.sha))

    def test_other_client_errors_propagate(self) -> None:
        def denied(Bucket, Key):
            raise ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject")

        self.client.head_object = denied
        with self.assertRaises(ClientError):
            self.store.has("media/x.png", self.sha)

    def test_refuses_keys_outside_media_prefix(self) -> None:
        for bad in ("newsroom/x.png", "media/../newsroom/x.png"):
            with self.assertRaises(ValueError):
                self.store.put(bad, self.local, content_type="image/png", sha256=self.sha)
        self.assertEqual(self.client.put_calls, 0)

    def test_get_downloads(self) -> None:
        path = "media/a.png"
        self.store.put(path, self.local, content_type="image/png", sha256=self.sha)
        dest = Path(self.directory.name) / "out" / "a.png"
        self.store.get(path, dest)
        self.assertEqual(dest.read_bytes(), b"png-bytes")


class BucketResolutionTestCase(unittest.TestCase):
    def test_explicit_wins_then_env_then_outputs(self) -> None:
        with mock.patch.dict(os.environ, {"PAPYRUS_MEDIA_BUCKET": "env-bucket"}):
            self.assertEqual(configured_media_bucket("flag-bucket"), "flag-bucket")
            self.assertEqual(configured_media_bucket(None), "env-bucket")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "papyrus_content.media_store.storage_bucket_from_amplify_outputs", return_value="outputs-bucket"
        ):
            self.assertEqual(configured_media_bucket(None), "outputs-bucket")

    def test_missing_bucket_is_an_error(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "papyrus_content.media_store.storage_bucket_from_amplify_outputs", return_value=None
        ):
            with self.assertRaises(ValueError):
                S3MediaStore(client=FakeS3Client())

    def test_videos_default_store_is_the_s3_store(self) -> None:
        with mock.patch.dict(os.environ, {"PAPYRUS_MEDIA_BUCKET": "b"}), mock.patch("boto3.client"):
            self.assertIsInstance(create_default_media_store(), S3MediaStore)


if __name__ == "__main__":
    unittest.main()
