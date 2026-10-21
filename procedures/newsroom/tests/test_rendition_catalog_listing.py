"""``RenditionCatalog.all_records``: the images a site store has renditions for, read from the store itself."""

from __future__ import annotations

import io
import json

from papyrus_content.markus_renderer.images import ImagePipeline
from papyrus_content.renditions import DirectoryRenditionStore, RenditionCatalog, S3RenditionStore, meta_key

PIPELINE = ImagePipeline()
RECORDS = {
    "images/b.png": {"kind": "gatsby", "source": "images/b.png", "size": [800, 400]},
    "diagrams/a.svg": {"kind": "passthrough", "source": "diagrams/a.svg", "size": [10, 20]},
}


def seed(store) -> None:
    for source, record in RECORDS.items():
        store.put(meta_key(PIPELINE, source), json.dumps(record).encode("utf-8"), cache_control="x")
    store.put("assets/responsive/images/b-400.webp", b"not a record", cache_control="x")
    store.put("elsewhere/c.meta.json", b"{}", cache_control="x")


def test_a_directory_store_lists_every_record_ordered_by_source(tmp_path):
    store = DirectoryRenditionStore(tmp_path)
    seed(store)
    catalog = RenditionCatalog(store, PIPELINE)
    assert [record["source"] for record in catalog.all_records()] == ["diagrams/a.svg", "images/b.png"]
    assert catalog.record("images/b.png")["size"] == [800, 400]   # primed: no second read


def test_an_empty_store_has_no_records(tmp_path):
    assert RenditionCatalog(DirectoryRenditionStore(tmp_path), PIPELINE).all_records() == []


class FakeS3:
    class exceptions:  # noqa: N801 - mirrors boto3
        NoSuchKey = KeyError

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, **_):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(key for key in self.objects if key.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start : start + 2]   # two per page: the store must follow the continuation token
        more = start + 2 < len(keys)
        return {"Contents": [{"Key": key} for key in page], "IsTruncated": more, "NextContinuationToken": str(start + 2)}


def test_an_s3_store_follows_the_listing_pages():
    client = FakeS3()
    store = S3RenditionStore("bucket", client)
    seed(store)
    assert [record["source"] for record in RenditionCatalog(store, PIPELINE).all_records()] == ["diagrams/a.svg", "images/b.png"]
