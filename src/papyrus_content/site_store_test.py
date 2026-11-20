import io
import json

import pytest

from papyrus_content import site_store as store
from papyrus_content.site_store import SiteSaveConflict, SiteStore, SiteStoreError
from papyrus_content.tenancy import TenantError


class FakeS3:
    def __init__(self, fail_put=False):
        self.objects = {}
        self.fail_put = fail_put

    def put_object(self, Bucket, Key, Body, ContentType):
        if self.fail_put:
            raise OSError("S3 unavailable")
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


class FakeTable:
    def __init__(self, fail_create=None):
        self.rows = {}
        self.writes = []
        self.fail_create = fail_create

    def get(self, model, row_id):
        return self.rows.get((model, row_id))

    def create(self, model, row):
        if model == self.fail_create:
            raise OSError("table unavailable")
        if (model, row["id"]) in self.rows:
            raise KeyError(row["id"])
        self.rows[(model, row["id"])] = dict(row)
        self.writes.append(model)

    def update_if(self, model, row_id, changes, expected):
        row = self.rows[(model, row_id)]
        if any(row[k] != v for k, v in expected.items()):
            return False
        row.update(changes)
        self.writes.append(model)
        return True

    def latest_version(self, document_id):
        versions = [r for (m, _), r in self.rows.items() if m == "SiteDocumentVersion" and r["documentId"] == document_id]
        return max(versions, key=lambda r: r["version"], default=None)


def make(s3=None, table=None):
    s3, table = s3 or FakeS3(), table or FakeTable()
    return SiteStore(s3, "bucket", table, now=lambda: "2026-11-13T00:00:00Z"), s3, table


def test_key_shapes():
    assert store.document_id("alpha", "brand") == "alpha#brand"
    assert store.version_id("alpha", "brand", 4) == "alpha#brand#4"
    assert store.version_key("alpha", "nav", 2) == "tenants/alpha/site/nav/2.json"
    with pytest.raises(SiteStoreError):
        store.document_id("alpha", "pages")
    with pytest.raises(TenantError):
        store.document_id("Alpha", "site")
    with pytest.raises(SiteStoreError):
        store.version_key("alpha", "site", 0)


def test_a_save_writes_the_object_then_the_row_then_the_pointer():
    s3, table = FakeS3(), FakeTable()
    s, _, _ = make(s3, table)
    assert s.save("alpha", "brand", {"colour": "red"}, "ada") == 1
    assert table.writes == ["SiteDocumentVersion", "SiteDocument"]
    assert ("bucket", "tenants/alpha/site/brand/1.json") in s3.objects
    document = table.rows[("SiteDocument", "alpha#brand")]
    assert document["currentVersion"] == 1 and document["s3Key"] == "tenants/alpha/site/brand/1.json"
    assert s.read_current("alpha", "brand") == {"colour": "red"}
    assert s.save("alpha", "brand", {"colour": "blue"}, "ada", note="new colours") == 2
    assert s.read_current("alpha", "brand") == {"colour": "blue"}
    assert s.read_version("alpha", "brand", 1) == {"colour": "red"}
    assert table.rows[("SiteDocumentVersion", "alpha#brand#2")]["note"] == "new colours"


def test_restore_writes_a_new_version_with_the_old_content():
    s, _, table = make()
    for colour in ("red", "green", "blue", "pink"):
        s.save("alpha", "brand", {"colour": colour}, "ada")
    assert s.restore("alpha", "brand", 2, "ada") == 5
    assert s.read_current("alpha", "brand") == {"colour": "green"}
    assert s.read_version("alpha", "brand", 4) == {"colour": "pink"}
    assert table.rows[("SiteDocumentVersion", "alpha#brand#5")]["sha256"] == table.rows[("SiteDocumentVersion", "alpha#brand#2")]["sha256"]
    with pytest.raises(SiteStoreError):
        s.restore("alpha", "brand", 9, "ada")


def test_a_failed_object_write_changes_nothing():
    s, _, table = make()
    s.save("alpha", "site", {"a": 1}, "ada")
    failing = SiteStore(FakeS3(fail_put=True), "bucket", table)
    with pytest.raises(OSError):
        failing.save("alpha", "site", {"a": 2}, "ada")
    assert table.rows[("SiteDocument", "alpha#site")]["currentVersion"] == 1
    assert s.current_version("alpha", "site") == 1


def test_a_failed_version_row_leaves_the_old_version_live_and_the_orphan_is_skipped():
    s3, table = FakeS3(), FakeTable()
    s, _, _ = make(s3, table)
    s.save("alpha", "nav", {"v": 1}, "ada")
    table.fail_create = "SiteDocumentVersion"
    with pytest.raises(OSError):
        s.save("alpha", "nav", {"v": 2}, "ada")
    assert s.read_current("alpha", "nav") == {"v": 1}
    table.fail_create = None
    assert s.save("alpha", "nav", {"v": 3}, "ada") == 2
    assert s.read_current("alpha", "nav") == {"v": 3}


def test_an_orphan_version_row_is_never_reused():
    s, _, table = make()
    s.save("alpha", "nav", {"v": 1}, "ada")
    table.rows[("SiteDocumentVersion", "alpha#nav#2")] = {"id": "alpha#nav#2", "documentId": "alpha#nav", "version": 2}
    assert s.save("alpha", "nav", {"v": 3}, "ada") == 3


def test_a_save_that_loses_the_pointer_race_is_not_live():
    s, _, table = make()
    s.save("alpha", "site", {"a": 1}, "ada")
    original = table.update_if

    def racing(model, row_id, changes, expected):
        table.rows[(model, row_id)]["currentVersion"] = 7
        return original(model, row_id, changes, expected)

    table.update_if = racing
    with pytest.raises(SiteSaveConflict):
        s.save("alpha", "site", {"a": 2}, "ada")
    assert table.rows[("SiteDocument", "alpha#site")]["currentVersion"] == 7


def test_a_body_that_does_not_match_its_hash_is_refused():
    s, s3, _ = make()
    s.save("alpha", "site", {"a": 1}, "ada")
    s3.objects[("bucket", "tenants/alpha/site/site/1.json")] = json.dumps({"a": 2}).encode()
    with pytest.raises(SiteStoreError):
        s.read_current("alpha", "site")


def test_a_never_saved_document_reads_as_none():
    s, _, _ = make()
    assert s.read_current("alpha", "brand") is None and s.current_version("alpha", "brand") == 0
