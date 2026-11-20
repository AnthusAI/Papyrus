from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from papyrus_content.projection.runtime import OUTPUT_PREFIX_ENV, SITE_BUCKET_ENV, store_name
from papyrus_content.projection.writers import (
    LocalDirectoryWriter,
    OutputPrefixError,
    S3PageWriter,
    normalize_output_prefix,
    prefixed_key,
)

BUCKET = "shared-site-bucket"


@pytest.mark.parametrize("given,expected", [(None, ""), ("", ""), ("  ", ""), ("sites/alpha", "sites/alpha/"), ("sites/alpha/", "sites/alpha/"), ("a", "a/")])
def test_prefix_is_normalised(given, expected):
    assert normalize_output_prefix(given) == expected


@pytest.mark.parametrize("bad", ["/sites", "sites//alpha", "sites/../x", "./x", ".."])
def test_prefix_that_is_not_a_plain_relative_folder_is_refused(bad):
    with pytest.raises(OutputPrefixError):
        normalize_output_prefix(bad)


def test_no_prefix_leaves_every_key_untouched():
    assert prefixed_key("", "index.html") == "index.html"
    assert prefixed_key("", "_papyrus/state") == "_papyrus/state"


@pytest.mark.parametrize("key", ["../beta/index.html", "/index.html", "a/../../b", ".."])
def test_prefixed_writer_refuses_a_key_outside_its_prefix(key):
    with pytest.raises(OutputPrefixError):
        prefixed_key("sites/alpha/", key)


def test_local_writer_without_prefix_writes_at_the_root(tmp_path):
    writer = LocalDirectoryWriter(tmp_path)
    writer.put("posts/a/index.html", b"a")
    assert (tmp_path / "posts/a/index.html").read_bytes() == b"a"
    assert [entry.key for entry in writer.list()] == ["posts/a/index.html"]


def test_local_writer_with_prefix_stores_under_it_and_lists_only_its_own(tmp_path):
    (tmp_path / "sites/beta").mkdir(parents=True)
    (tmp_path / "sites/beta/index.html").write_bytes(b"beta")
    writer = LocalDirectoryWriter(tmp_path, "sites/alpha/")
    writer.put("index.html", b"alpha")
    assert (tmp_path / "sites/alpha/index.html").read_bytes() == b"alpha"
    assert [entry.key for entry in writer.list()] == ["index.html"]
    assert writer.get("index.html") == b"alpha"
    writer.delete("index.html")
    assert writer.get("index.html") is None
    assert (tmp_path / "sites/beta/index.html").read_bytes() == b"beta"


@mock_aws
def test_s3_writer_without_prefix_uses_the_key_as_given():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    writer = S3PageWriter(BUCKET, s3)
    writer.put("index.html", b"x", version=2)
    writer.put_many([("a/index.html", b"a", None, None), ("sitemap.xml", b"s", None, None)])
    assert sorted(entry["Key"] for entry in s3.list_objects_v2(Bucket=BUCKET)["Contents"]) == ["a/index.html", "index.html", "sitemap.xml"]
    assert writer.head("index.html").version == 2


@mock_aws
def test_s3_writer_with_prefix_writes_reads_lists_and_deletes_only_under_it():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(Bucket=BUCKET, Key="sites/beta/index.html", Body=b"beta")
    writer = S3PageWriter(BUCKET, s3, output_prefix="sites/alpha/")
    writer.put("index.html", b"alpha", version=3, inputs="abc")
    writer.put_many([("404.html", b"nf", None, None), ("sitemap.xml", b"sm", None, None), ("_papyrus/item/x", b"{}", None, None)])
    keys = sorted(entry["Key"] for entry in s3.list_objects_v2(Bucket=BUCKET)["Contents"])
    assert keys == ["sites/alpha/404.html", "sites/alpha/_papyrus/item/x", "sites/alpha/index.html", "sites/alpha/sitemap.xml", "sites/beta/index.html"]
    assert [entry.key for entry in writer.list()] == ["404.html", "_papyrus/item/x", "index.html", "sitemap.xml"]
    assert writer.get("index.html") == b"alpha"
    stored = writer.head("index.html")
    assert (stored.key, stored.version, stored.inputs) == ("index.html", 3, "abc")
    assert writer.head_many(["index.html", "missing.html"])["missing.html"] is None
    # the 404 page keeps its special headers at its prefixed key
    assert s3.head_object(Bucket=BUCKET, Key="sites/alpha/404.html")["ContentType"] == "text/html"
    writer.delete("index.html")
    assert writer.get("index.html") is None
    assert s3.get_object(Bucket=BUCKET, Key="sites/beta/index.html")["Body"].read() == b"beta"


@mock_aws
def test_s3_writer_with_prefix_refuses_to_leave_it():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    writer = S3PageWriter(BUCKET, s3, output_prefix="sites/alpha/")
    for call in (lambda: writer.put("../beta/x.html", b"x"), lambda: writer.get("/x"), lambda: writer.delete("a/../../b"), lambda: writer.head("../x")):
        with pytest.raises(OutputPrefixError):
            call()
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET)


def test_the_lock_table_name_of_a_site_is_its_bucket_unless_the_bucket_is_shared():
    assert store_name({SITE_BUCKET_ENV: BUCKET}) == BUCKET
    assert store_name({SITE_BUCKET_ENV: BUCKET, OUTPUT_PREFIX_ENV: ""}) == BUCKET
    assert store_name({SITE_BUCKET_ENV: BUCKET, OUTPUT_PREFIX_ENV: "sites/alpha"}) == f"{BUCKET}/sites/alpha"
