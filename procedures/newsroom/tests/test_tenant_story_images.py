"""Pictures on a tenant site: one key rule, the repair of the old tenant keys, and the signed-in request for renditions (PPY-a96347)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from papyrus_content.media_store import S3MediaStore
from papyrus_content.renditions import MEDIA_KEY_PREFIX, media_key_for_source, source_from_media_key
from papyrus_content.renditions_commands import request_renditions_signed_in
from papyrus_content.story_image_repair import apply_image_path_repair, plan_image_path_repair, plan_lines
from papyrus_content.tenancy import tenant_media_path

TENANT = "machines-on-machines"
SOURCE = "assets/draft-security-1/cant-opt-out.png"
OLD_KEY = f"media/{TENANT}/{SOURCE}"
NEW_KEY = f"media/{SOURCE}"


class Bucket:
    def __init__(self, keys=()):
        self.objects = {key: {"ContentType": "image/png", "Metadata": {"sha256": "ab"}} for key in keys}
        self.copies = []
        self.touched = []

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return self.objects[Key]

    def copy_object(self, Bucket, Key, CopySource, MetadataDirective, **fields):
        if MetadataDirective == "REPLACE":
            assert CopySource["Key"] == Key and fields["ContentType"] == "image/png" and fields["Metadata"] == {"sha256": "ab"}
            self.touched.append(Key)
        else:
            self.copies.append((CopySource["Key"], Key))
            self.objects[Key] = dict(self.objects[CopySource["Key"]])

    def get_paginator(self, name):
        objects = self.objects

        class Pages:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": key} for key in sorted(objects) if key.startswith(Prefix)]}

        return Pages()


class Rows:
    def __init__(self):
        self.updates = []

    def update_record(self, model, payload):
        self.updates.append((model, payload))


def row(row_id, storage, src=SOURCE):
    return {"id": row_id, "type": "image", "storagePath": storage, "metadata": json.dumps({"srcPath": src})}


def test_the_key_is_media_plus_source_and_round_trips():
    assert media_key_for_source(SOURCE) == NEW_KEY
    assert source_from_media_key(media_key_for_source(SOURCE)) == SOURCE
    assert MEDIA_KEY_PREFIX == "media/"


def test_the_key_refuses_an_unsafe_source():
    with pytest.raises(Exception):
        media_key_for_source("../outside.png")


def test_the_old_tenant_key_is_the_one_the_tenant_helper_makes():
    assert tenant_media_path(TENANT, NEW_KEY) == OLD_KEY   # what older save-versions stored, and what the repair moves


def test_plan_copies_each_object_once_and_updates_every_version_row():
    plan = plan_image_path_repair([row("v2", OLD_KEY), row("v3", OLD_KEY), row("v3b", "media/assets/x/other.png", "assets/x/other.png"), {"id": "n", "type": "image"}])
    assert plan.copies == {OLD_KEY: NEW_KEY}
    assert [(i, o, n) for i, o, n in plan.row_updates] == [("v2", OLD_KEY, NEW_KEY), ("v3", OLD_KEY, NEW_KEY)]
    assert plan.already_canonical == 1 and plan.unrepairable and plan.needed
    assert any("v2" in line and NEW_KEY in line for line in plan_lines("lineage", plan))


def test_a_story_at_the_one_key_needs_nothing():
    plan = plan_image_path_repair([row("v2", NEW_KEY)])
    assert not plan.needed and plan.already_canonical == 1


def test_apply_copies_then_points_the_rows_and_keeps_the_old_object():
    bucket, client = Bucket([OLD_KEY]), Rows()
    plan = plan_image_path_repair([row("v2", OLD_KEY), row("v3", OLD_KEY)])
    results = apply_image_path_repair(client, S3MediaStore("b", client=bucket), plan)
    assert bucket.copies == [(OLD_KEY, NEW_KEY)] and OLD_KEY in bucket.objects
    assert [r for r in results if r[0] == "row"] == [("row", "v2", "updated"), ("row", "v3", "updated")]
    assert client.updates == [("MediaAsset", {"id": "v2", "storagePath": NEW_KEY}), ("MediaAsset", {"id": "v3", "storagePath": NEW_KEY})]


def test_apply_with_a_missing_source_leaves_the_rows_alone():
    bucket, client = Bucket(), Rows()
    results = apply_image_path_repair(client, S3MediaStore("b", client=bucket), plan_image_path_repair([row("v2", OLD_KEY)]))
    assert ("object", OLD_KEY, "source-missing") in results and ("row", "v2", "left-alone") in results
    assert client.updates == [] and bucket.copies == []


def test_apply_when_the_new_key_already_holds_the_object_only_points_the_rows():
    bucket, client = Bucket([OLD_KEY, NEW_KEY]), Rows()
    results = apply_image_path_repair(client, S3MediaStore("b", client=bucket), plan_image_path_repair([row("v2", OLD_KEY)]))
    assert bucket.copies == [] and ("object", NEW_KEY, "already-there") in results and client.updates


def test_signed_in_request_touches_the_object_and_a_dry_run_does_not():
    bucket = Bucket([NEW_KEY])
    store = S3MediaStore("b", client=bucket)
    dry = request_renditions_signed_in(store, source=SOURCE, dry_run=True, tenant_id=TENANT)
    assert dry["ok"] and dry["counts"] == {"would-request": 1} and bucket.touched == []
    done = request_renditions_signed_in(store, source=SOURCE, dry_run=False, tenant_id=TENANT)
    assert done["ok"] and done["counts"] == {"requested": 1} and bucket.touched == [NEW_KEY]


def test_signed_in_request_for_a_missing_object_says_where_it_is_and_what_moves_it():
    report = request_renditions_signed_in(S3MediaStore("b", client=Bucket([OLD_KEY])), source=SOURCE, dry_run=False, tenant_id=TENANT)
    assert not report["ok"]
    error = report["results"][0]["error"]
    assert NEW_KEY in error and OLD_KEY in error and "papyrus stories repair-image-paths" in error


def test_signed_in_backfill_requests_every_image_under_media_and_skips_other_files():
    bucket = Bucket([NEW_KEY, "media/notes/readme.txt", "media/payloads/x.json"])
    report = request_renditions_signed_in(S3MediaStore("b", client=bucket), source=None, dry_run=False, tenant_id=None)
    assert report["images"] == 1 and bucket.touched == [NEW_KEY]


def test_tenant_stamp_leaves_media_storage_paths_alone():
    from papyrus_content.tenancy import tenant_stamped_payload

    for model in ("MediaAsset", "PublishedMediaAsset"):
        assert tenant_stamped_payload(model, TENANT, {"id": "m", "storagePath": NEW_KEY})["storagePath"] == NEW_KEY


def test_plan_repoints_media_and_published_rows_whose_object_is_at_the_one_key():
    plan = plan_image_path_repair([row("m1", OLD_KEY)], [row("p1", OLD_KEY)], exists=lambda key: key == NEW_KEY)
    assert plan.repoint_only == {OLD_KEY} and plan.row_updates == [("m1", OLD_KEY, NEW_KEY)]
    assert plan.published_row_updates == [("p1", OLD_KEY, NEW_KEY)]
    lines = plan_lines("lineage", plan)
    assert any("object-already-there" in line for line in lines) and any("published-row\tp1" in line for line in lines)
    bucket, client = Bucket([NEW_KEY]), Rows()
    apply_image_path_repair(client, S3MediaStore("b", client=bucket), plan)
    assert client.updates == [("MediaAsset", {"id": "m1", "storagePath": NEW_KEY}), ("PublishedMediaAsset", {"id": "p1", "storagePath": NEW_KEY})]
    assert bucket.copies == []
