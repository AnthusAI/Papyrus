"""The image guidelines on the guideline store: where the text lives and how few reads a resolve makes."""
from __future__ import annotations

import json

from papyrus_content.images.handlers import Caller, execute
from papyrus_content.images.profile_fakes import FakeBackend, profile_copy
from papyrus_content.images.profile_handlers import with_client
from papyrus_content.images.profile_store import read_current_profile

EDITOR = Caller(kind="person", subject="Edie Editor")
COVER = {"target": {"kind": "story", "lineageId": "story-1"}, "use": "cover", "imageType": "cover-illustration"}


def resolve(backend, **extra):
    return execute("image_profile_resolve", {**COVER, **extra}, EDITOR, with_client(backend))


def test_the_profile_row_holds_only_catalog_fields_and_the_text_is_in_s3():
    backend = FakeBackend("ours", profile=profile_copy())
    row = backend.items[0]
    assert row["bodyMarkus"] == "" and "visualStyle" not in json.loads(row["metadata"])
    assert json.loads(backend.document_bodies[backend.document_attachments[0]["storagePath"]])["identity"]["summary"].startswith("Flat")


def test_an_old_inline_row_is_read_without_any_download():
    backend = FakeBackend("ours")
    backend.save_inline_profile_version(profile_copy(), by="admin-account", reason="Old")
    document, ref, _ = read_current_profile(backend)
    assert document["identity"]["summary"].startswith("Flat") and ref["versionNumber"] == 1 and backend.document_files.downloads == []


def test_the_section_layer_costs_one_slug_query_one_attachment_query_and_one_download_and_nothing_per_story():
    backend = FakeBackend("ours", profile=profile_copy())
    backend.add_section("security")
    backend.add_story("story-1", section="security")
    backend.save_profile_version({"schemaVersion": 2, "palette": ["Ink blue"]}, by="Ada Admin", reason="Narrow", section="security")
    backend.reads.clear()
    backend.document_files.downloads.clear()
    answer = resolve(backend)
    assert answer["ok"], answer
    section_reads = [read for read in backend.reads if read[1] == "desk-doctrine-security-visual-style" or read[1].startswith("item-desk-doctrine-security")]
    assert len(section_reads) == 2
    assert backend.document_files.downloads.count("item-desk-doctrine-security-visual-style-v1") == 1
    assert [name for name, _ in backend.reads].count("itemsByLineageAndVersion") == 1


def test_a_section_without_an_image_document_costs_one_slug_query_and_no_download():
    backend = FakeBackend("ours", profile=profile_copy())
    backend.add_section("news", visualGuidance="Calm.")
    backend.add_story("story-1", section="news")
    backend.reads.clear()
    backend.document_files.downloads.clear()
    assert resolve(backend)["ok"]
    assert [read for read in backend.reads if read[1] == "desk-doctrine-news-visual-style"] == [("itemBySlug", "desk-doctrine-news-visual-style")]
    assert all(owner.startswith("item-editorial-doctrine-visual-style") for owner in backend.document_files.downloads)
