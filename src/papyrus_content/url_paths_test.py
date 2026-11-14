"""One encoding for every address (url_paths.py, docs/multilingual-serving.md "Unicode addresses"): what each writer is handed. Stub AWS clients; no network."""
from __future__ import annotations

import unicodedata

from papyrus_content.markus_renderer.build import page_slug
from papyrus_content.projection.writers import KeyValueStoreRedirects, S3PageWriter, TargetedCloudFrontInvalidator, request_paths_for_key
from papyrus_content.url_paths import decoded_path, encoded_path

SLUG = "能泄露你住在哪里的声音"
KEY = f"zh/articles/{SLUG}/index.html"
ENCODED_DIRECTORY = "/zh/articles/%E8%83%BD%E6%B3%84%E9%9C%B2%E4%BD%A0%E4%BD%8F%E5%9C%A8%E5%93%AA%E9%87%8C%E7%9A%84%E5%A3%B0%E9%9F%B3/"


def test_an_ascii_key_is_unchanged_and_a_chinese_one_is_percent_encoded_in_upper_case():
    assert encoded_path("/articles/the-sound/") == "/articles/the-sound/"
    assert encoded_path(f"/zh/articles/{SLUG}/") == ENCODED_DIRECTORY
    assert request_paths_for_key(KEY) == (ENCODED_DIRECTORY, ENCODED_DIRECTORY.rstrip("/"))


def test_decoding_returns_the_composed_key_whatever_form_was_encoded():
    decomposed = unicodedata.normalize("NFD", "가")
    assert encoded_path(decomposed) == encoded_path("가")
    assert decoded_path(encoded_path(f"/zh/articles/{SLUG}/")) == f"/zh/articles/{SLUG}/"
    assert decoded_path("/zh/articles/%ea%b0%80/") == "/zh/articles/가/"   # lower-case hex decodes to the same key


def test_a_slug_in_a_script_without_ascii_is_kept_and_one_that_folds_is_folded_as_before():
    assert page_slug(SLUG) == SLUG
    assert page_slug(unicodedata.normalize("NFD", "가")) == "가"
    assert page_slug("Café") == "cafe" and page_slug("café") == "cafe"
    assert page_slug("Hello World") == "hello-world"


class RecordingS3:
    def __init__(self):
        self.keys = []

    def put_object(self, **arguments):
        self.keys.append(arguments["Key"])


def test_the_page_writer_stores_the_composed_text_key_never_the_encoded_one():
    s3 = RecordingS3()
    S3PageWriter("bucket", s3).put(KEY, b"<html></html>")
    assert s3.keys == [KEY] and unicodedata.is_normalized("NFC", s3.keys[0])


class RecordingKeyValueStore:
    def __init__(self):
        self.puts = []

    def describe_key_value_store(self, **_arguments):
        return {"ETag": "e"}

    def update_keys(self, **arguments):
        self.puts.extend(arguments.get("Puts", []))


def test_the_redirect_store_is_handed_the_encoded_paths_the_edge_function_compares():
    kvs = RecordingKeyValueStore()
    old, new = request_paths_for_key(KEY)[0], encoded_path("/zh/articles/你住在哪里/")
    KeyValueStoreRedirects("arn:aws:cloudfront::0:key-value-store/x", kvs).put_all({old: new})
    assert kvs.puts == [{"Key": ENCODED_DIRECTORY, "Value": new}]
    assert all(entry["Key"].isascii() and entry["Value"].isascii() for entry in kvs.puts)
    assert len(ENCODED_DIRECTORY.encode()) <= 512   # a KeyValueStore key is at most 512 bytes


class RecordingCloudFront:
    def __init__(self):
        self.batches = []

    def create_invalidation(self, **arguments):
        self.batches.append(arguments["InvalidationBatch"]["Paths"])
        return {"Invalidation": {"Id": "I1", "Status": "InProgress"}}


def test_exact_invalidation_purges_the_encoded_forms_and_counts_each_against_the_cap():
    cloudfront = RecordingCloudFront()
    listed = TargetedCloudFrontInvalidator("D1", 25, cloudfront).invalidate([KEY])
    assert listed == [ENCODED_DIRECTORY + "index.html", ENCODED_DIRECTORY]
    assert cloudfront.batches == [{"Quantity": 2, "Items": listed}]
