"""Guideline documents: validation, the store (catalog row in the database, document in S3), and the writing resolver. A fake backend; no network."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from papyrus_content.guidelines import (Field, GuidelineError, GuidelineStore, KindSpec, kind_names, register_kind, resolve_guidelines, resolve_writing, slug_for,
                                        unregister_kind, validate_document)
from papyrus_content.guidelines.document import PROSE, digest, texts
from papyrus_content.guidelines.fakes import FakeBackend, FakeFiles

ROOT = Path(__file__).resolve().parents[3]
SITE = {"schemaVersion": 1, "voice": {"name": "House"}, "audience": "General readers", "tone": ["Warm."], "voicePatterns": ["Opens plainly."],
        "lexicon": {"prefer": ["inspect"], "avoid": ["synergy"]}, "bodyMarkus": "Write plainly.",
        "constraints": [{"id": "no-hype", "text": "No hype."}], "locked": ["headline"], "headline": {"order": ["title"]}}


def make():
    backend = FakeBackend()
    return backend, GuidelineStore(backend, FakeFiles(backend))


def save(store, document, section=None, *, kind="writing", expected="none", reason="First"):
    return store.save(kind, document, section=section, expected_current_version_id=expected, actor="Ada", reason=reason, now="2026-11-10T10:00:00Z")


def with_site(section_document=None, section="news"):
    backend, store = make()
    save(store, SITE)
    if section_document is not None:
        save(store, section_document, section)
    return backend, store


def problems(kind, document, scope="publication"):
    return [(p.path, p.code) for p in validate_document(kind, document, scope)]


# --- validation ---------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["anthus", "pilobolus"])
def test_the_repository_style_profiles_validate_unchanged(name):
    document = yaml.safe_load((ROOT / "publications" / name / "style-profile.yml").read_text())
    assert problems("writing", document) == []


def test_problems_are_reported_by_field():
    bad = {"schemaVersion": 1, "tone": ["ok", ""], "lexicon": {"avoid": "x", "ban": []}, "glossary": [{"use": "a"}], "mystery": 1,
           "locked": ["tone"], "constraints": [{"id": "a"}]}
    paths = {path for path, _ in problems("writing", bad)}
    assert paths == {"tone", "lexicon", "glossary", "mystery", "locked", "constraints"}
    assert ("mystery", "unknown_field") in problems("writing", bad)


def test_schema_version_is_required():
    assert problems("writing", {"tone": ["x"]}) == [("schemaVersion", "invalid_input")]


def test_a_section_document_cannot_hold_publication_only_fields():
    assert problems("writing", {"schemaVersion": 1, "density": {"minWords": 1}}, "section") == [("density", "publication_only")]


# --- the store ----------------------------------------------------------------------------------------------------------------------------------

def test_a_save_writes_a_catalog_row_and_one_s3_document():
    backend, store = make()
    result = save(store, SITE)
    assert result["changed"] and result["reference"]["versionNumber"] == 1
    (row,) = backend.items
    assert row["slug"] == "editorial-doctrine-writing" and row["type"] == "doctrine" and row["status"] == "private"
    assert row["bodyMarkus"] == "" and json.loads(row["metadata"]) == {} and row["body"] == []
    assert row["contentHash"] == digest(SITE) and row["changeReason"] == "First" and row["versionCreatedBy"] == "Ada"
    (attachment,) = backend.attachments
    assert attachment["role"] == "doctrine_document" and attachment["ownerKind"] == "item" and attachment["ownerId"] == row["id"]
    assert attachment["storagePath"] == f"newsroom/payloads/item/{row['id']}/doctrine-document/guidelines.json"
    assert json.loads(backend.bodies[attachment["storagePath"]]) == SITE
    read = store.read("writing")
    assert read["document"] == SITE and read["reference"]["contentHash"] == digest(SITE)


def test_every_read_is_an_index_query():
    backend, store = with_site(None)
    backend.reads.clear()
    store.read("writing")
    store.history("writing")
    resolve_writing(store, "news")
    assert {index for index, _ in backend.reads} <= {"itemBySlug", "modelAttachmentsByOwnerRoleAndSortKey"}   # the fake raises on any scan


def test_an_unchanged_document_makes_no_version():
    backend, store = with_site()
    current = store.read("writing")["reference"]["itemId"]
    result = save(store, copy.deepcopy(SITE), expected=current)
    assert result["changed"] is False and len(backend.items) == 1 and len(backend.attachments) == 1


def test_a_second_save_supersedes_the_first_and_history_lists_both():
    backend, store = with_site()
    first = store.read("writing")["reference"]["itemId"]
    save(store, {**SITE, "audience": "Engineers"}, expected=first, reason="Narrowed")
    assert store.read("writing")["document"]["audience"] == "Engineers"
    assert store.read("writing", version=1)["document"]["audience"] == "General readers"
    assert [(h["versionNumber"], h["versionState"], h["reason"]) for h in store.history("writing")] == [(2, "current", "Narrowed"), (1, "superseded", "First")]


def test_a_stale_save_is_refused_and_stores_nothing():
    backend, store = with_site()
    with pytest.raises(GuidelineError) as caught:
        save(store, {**SITE, "audience": "X"}, expected="item-editorial-doctrine-writing-v0")
    assert caught.value.code == "stale_version" and len(backend.items) == 1
    with pytest.raises(GuidelineError):
        save(store, SITE, expected="none")   # a lineage that exists is not "none"


def test_an_invalid_document_or_missing_reason_is_refused():
    backend, store = make()
    with pytest.raises(GuidelineError) as caught:
        save(store, {"schemaVersion": 1, "tone": [""]})
    assert caught.value.code == "invalid_input" and caught.value.details["problems"][0]["path"] == "tone"
    with pytest.raises(GuidelineError):
        save(store, SITE, reason=" ")
    assert backend.items == [] and backend.attachments == []


def test_a_tampered_document_is_detected():
    backend, store = with_site()
    path = backend.attachments[0]["storagePath"]
    backend.bodies[path] = json.dumps({**SITE, "audience": "Changed"}).encode()
    with pytest.raises(GuidelineError) as caught:
        store.read("writing")
    assert caught.value.code == "document_hash_mismatch"


def test_another_accounts_row_is_refused():
    backend, store = with_site()
    backend.tenant_id = "other"
    backend.items[0]["tenantId"] = None
    with pytest.raises(ValueError):
        store.read("writing")


def test_slugs_mirror_the_doctrine_lineages():
    assert slug_for("writing") == "editorial-doctrine-writing"
    assert slug_for("writing", "Deep Dives") == "desk-doctrine-deep-dives-writing"
    assert slug_for("image", "news") == "desk-doctrine-news-visual-style"
    assert slug_for("video") == "editorial-doctrine-video"


# --- the writing resolver ----------------------------------------------------------------------------------------------------------------------

def test_a_section_adds_tone_and_voice_patterns_after_the_sites():
    _, store = with_site({"schemaVersion": 1, "tone": ["Brisk."], "voicePatterns": ["Short leads."], "bodyMarkus": "Be quick."})
    document = resolve_writing(store, "news")["document"]
    assert document["tone"] == ["Warm.", "Brisk."] and document["voicePatterns"] == ["Opens plainly.", "Short leads."]
    assert document["bodyMarkus"] == "Write plainly.\n\nBe quick."


def test_a_section_cannot_remove_a_word_the_site_avoids():
    _, store = with_site({"schemaVersion": 1, "lexicon": {"avoid": ["leverage"], "prefer": []}})
    assert resolve_writing(store, "news")["document"]["lexicon"] == {"prefer": ["inspect"], "avoid": ["synergy", "leverage"]}


def test_a_section_replaces_the_audience_when_the_site_leaves_it_open():
    _, store = with_site({"schemaVersion": 1, "audience": "Engineers", "voice": {"name": "Desk"}})
    answer = resolve_writing(store, "news")
    assert answer["document"]["audience"] == "Engineers" and answer["document"]["voice"] == {"name": "Desk"} and answer["warnings"] == []


def test_a_section_cannot_replace_a_field_the_site_locks():
    _, store = with_site({"schemaVersion": 1, "headline": {"order": ["subtitle"]}})
    answer = resolve_writing(store, "news")
    assert answer["document"]["headline"] == {"order": ["title"]}
    assert [(w["code"], w["field"]) for w in answer["warnings"]] == [("locked_field_ignored", "headline")]


def test_a_sections_binding_constraint_is_ignored_with_a_warning():
    _, store = with_site({"schemaVersion": 1, "constraints": [{"id": "x", "text": "Anything."}]})
    answer = resolve_writing(store, "news")
    assert answer["document"]["constraints"] == SITE["constraints"]
    assert [w["code"] for w in answer["warnings"]] == ["section_constraint_ignored"]


def test_a_site_with_no_writing_guidelines_resolves_with_a_warning():
    _, store = make()
    answer = resolve_writing(store, "news")
    assert answer["found"] is False and answer["document"] == {} and [w["code"] for w in answer["warnings"]] == ["writing_guidelines_missing"]


def test_a_section_without_a_document_resolves_to_the_sites_alone():
    _, store = with_site()
    answer = resolve_writing(store, "news")
    assert answer["document"]["tone"] == ["Warm."] and len(answer["layers"]) == 1 and answer["warnings"] == []


def test_every_resolved_field_names_its_layer_and_version():
    backend, store = with_site({"schemaVersion": 1, "tone": ["Brisk."], "audience": "Engineers"})
    answer = resolve_writing(store, "news")
    assert answer["fieldSources"]["tone"] == [{"layer": "publication", "version": 1}, {"layer": "section", "version": 1}]
    assert answer["fieldSources"]["audience"] == [{"layer": "section", "version": 1}]
    assert answer["fieldSources"]["voice"] == [{"layer": "publication", "version": 1}]
    assert set(answer["fieldSources"]) == set(answer["document"])
    assert [(l["scope"], l["slug"], l["versionNumber"]) for l in answer["layers"]] == [
        ("publication", "editorial-doctrine-writing", 1), ("section", "desk-doctrine-news-writing", 1)]
    assert all(l["contentHash"].startswith("sha256:") for l in answer["layers"])


def test_a_glossary_entry_replaces_the_sites_unless_locked_and_keeps_its_avoids():
    site = {**SITE, "glossary": [{"term": "Papyrus", "use": "Papyrus", "avoid": ["Papirus"]}]}
    backend, store = make()
    save(store, site)
    save(store, {"schemaVersion": 1, "glossary": [{"term": "Papyrus", "use": "the newsroom", "avoid": ["PPY"]}, {"term": "Cyclotron", "use": "Cyclotron"}]}, "news")
    glossary = resolve_writing(store, "news")["document"]["glossary"]
    assert glossary[0] == {"term": "Papyrus", "use": "the newsroom", "avoid": ["Papirus", "PPY"]} and glossary[1]["term"] == "Cyclotron"
    first = store.read("writing")["reference"]["itemId"]
    save(store, {**site, "locked": ["glossary"]}, expected=first, reason="Lock")
    assert resolve_writing(store, "news")["document"]["glossary"][0]["use"] == "Papyrus"


def test_the_real_style_profiles_resolve():
    backend, store = make()
    save(store, yaml.safe_load((ROOT / "publications" / "pilobolus" / "style-profile.yml").read_text()))
    assert resolve_writing(store)["document"]["voice"] == {"name": "Pilobolus impersonal weird"}


# --- kinds are data ----------------------------------------------------------------------------------------------------------------------------

def test_the_built_in_kinds():
    assert {"writing", "image", "video"} <= set(kind_names())


def test_video_is_registered_and_minimal():
    _, store = make()
    save(store, {"schemaVersion": 1, "bodyMarkus": "Cut on motion."}, kind="video")
    save(store, {"schemaVersion": 1, "bodyMarkus": "Shorts."}, "shorts", kind="video")
    assert resolve_guidelines(store, "video", "shorts")["document"]["bodyMarkus"] == "Cut on motion.\n\nShorts."
    assert resolve_guidelines(store, "video", "x")["warnings"] == []
    assert resolve_guidelines(make()[1], "video")["warnings"][0]["code"] == "video_guidelines_missing"


def test_a_new_kind_needs_no_store_change():
    register_kind(KindSpec("podcast", "podcast", 1, {"hosts": Field(texts, PROSE), "bodyMarkus": Field(lambda v: None, PROSE)}))
    try:
        backend, store = make()
        save(store, {"schemaVersion": 1, "hosts": ["Ada"]}, kind="podcast")
        save(store, {"schemaVersion": 1, "hosts": ["Bo"]}, "weekly", kind="podcast")
        assert backend.items[0]["slug"] == "editorial-doctrine-podcast" and backend.items[1]["slug"] == "desk-doctrine-weekly-podcast"
        assert backend.attachments[0]["storagePath"].endswith("doctrine-document/guidelines.json")
        assert resolve_guidelines(store, "podcast", "weekly")["document"]["hosts"] == ["Ada", "Bo"]
        assert validate_document("podcast", {"schemaVersion": 1, "guests": []})[0].code == "unknown_field"
    finally:
        unregister_kind("podcast")
    with pytest.raises(GuidelineError) as caught:
        slug_for("podcast")
    assert caught.value.code == "unknown_kind"


def test_an_unknown_kind_is_refused():
    _, store = make()
    with pytest.raises(GuidelineError) as caught:
        save(store, SITE, kind="audio")
    assert caught.value.code == "unknown_kind"


def test_image_documents_store_like_any_kind_but_resolve_elsewhere():
    from papyrus_content.images.profile_fakes import profile_copy

    _, store = make()
    save(store, profile_copy(), kind="image")
    assert store.read("image")["row"]["slug"] == "editorial-doctrine-visual-style"
    with pytest.raises(GuidelineError) as caught:
        resolve_guidelines(store, "image")
    assert caught.value.code == "resolver_not_available"
