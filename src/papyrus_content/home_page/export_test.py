import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from features_backend.steps.home_page_snapshot_steps import FixtureClient
from papyrus_content.graphql_authoring import REFERENCE_FIELDS
from papyrus_content.home_page import export
from papyrus_content.home_page.export import (
    EXCLUDED_REFERENCE_FIELDS,
    PUBLIC_REFERENCE_FIELDS,
    PUBLIC_SOURCE_FIELDS,
    WithheldReference,
    accept_probability,
    clip_summary,
    collect_references,
    public_key,
    public_reference,
    public_url,
    scrub,
)
from papyrus_content.home_page.settings import HomePageSettings, home_page_settings_from_mapping
from procedures.newsroom.tests.reader_privacy import identity_leaks

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def test_every_reference_field_is_published_or_excluded_exactly_once():
    model_fields = set(REFERENCE_FIELDS.split())
    published, excluded = set(PUBLIC_SOURCE_FIELDS), set(EXCLUDED_REFERENCE_FIELDS)
    assert not published & excluded
    assert published | excluded == model_fields
    assert all(reason for reason in EXCLUDED_REFERENCE_FIELDS.values())


def test_the_allowlist_has_no_duplicates_and_no_excluded_name():
    assert len(set(PUBLIC_REFERENCE_FIELDS)) == len(PUBLIC_REFERENCE_FIELDS)
    assert not set(PUBLIC_REFERENCE_FIELDS) & set(EXCLUDED_REFERENCE_FIELDS)


def test_public_key_is_twelve_hex_characters_of_the_lineage_hash():
    key = public_key("lineage-1")
    assert len(key) == 12 and int(key, 16) >= 0
    import hashlib

    assert key == hashlib.sha256(b"lineage-1").hexdigest()[:12]
    assert public_key("lineage-1") != public_key("lineage-2")


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (None, 0.5),
        ({"label": "include", "confidence": 0.93, "positiveLabel": None}, 0.93),
        ({"label": "exclude", "confidence": 0.9, "positiveLabel": None}, pytest.approx(0.1)),
        ({"label": "keep", "confidence": 0.8, "positiveLabel": "keep"}, 0.8),
        ({"label": "include", "confidence": 0.8, "positiveLabel": "keep"}, pytest.approx(0.2)),
        ({"label": "include", "confidence": None, "positiveLabel": None}, 0.6),
        ({"label": "exclude", "confidence": None, "positiveLabel": None}, pytest.approx(0.4)),
    ],
)
def test_accept_probability_follows_the_newsroom_console(decision, expected):
    assert accept_probability(decision) == expected


def test_clip_summary_ends_on_a_sentence_boundary_within_the_limit():
    text = "One short sentence. A second sentence that is a little longer than the first. A third that will not fit at all."
    assert clip_summary(text, 60) == "One short sentence."
    assert clip_summary(text, 1000) == text


def test_clip_summary_without_a_sentence_boundary_cuts_at_a_word():
    clipped = clip_summary("word " * 40, 22)
    assert clipped.endswith("…") and len(clipped) <= 23


def test_scrub_removes_emails_uuids_and_site_subjects():
    dirty = f"Write to a.b@example.test about {"-".join(["123e4567", "e89b", "12d3", "a456", "426614174000"])} and ss1_abcdefghijkl now"
    assert scrub(dirty) == "Write to about and now"
    assert identity_leaks(scrub(dirty)) == []


def test_public_url_drops_an_identifying_query_and_withholds_an_identifying_path():
    assert public_url("https://example.org/read?email=a@example.test&id=1") == "https://example.org/read"
    assert public_url("https://example.org/a?page=2") == "https://example.org/a?page=2"
    with pytest.raises(WithheldReference):
        public_url("https://example.org/u/a@example.test/profile")


def settings_with_fields(fields):
    return home_page_settings_from_mapping({"references": {"fields": fields}})


def test_a_record_holds_only_the_chosen_fields_in_allowlist_order():
    row = FixtureClient().rows()[0]
    record = public_reference(row, None, None, {}, settings_with_fields(["status", "key", "title"]))
    assert list(record) == ["key", "status", "title"]


def test_an_excluded_name_in_the_allowlist_is_refused_when_a_record_is_built(monkeypatch):
    monkeypatch.setattr(export, "PUBLIC_REFERENCE_FIELDS", (*PUBLIC_REFERENCE_FIELDS, "curationStatusUpdatedBy"))
    monkeypatch.setitem(export.EXCLUDED_REFERENCE_FIELDS, "key", "test")
    row = FixtureClient().rows()[0]
    with pytest.raises(AssertionError, match="excluded fields"):
        public_reference(row, None, None, {}, HomePageSettings())


def test_an_export_of_the_fixture_has_no_excluded_name_value_or_identity():
    client = FixtureClient()
    records = collect_references(client, client.corpus_id, HomePageSettings())
    assert len(records) == 12
    text = json.dumps(records)
    for record in records:
        assert not set(record) & set(EXCLUDED_REFERENCE_FIELDS)
    for row in client.rows():
        for field in EXCLUDED_REFERENCE_FIELDS:
            value = row.get(field)
            if isinstance(value, str) and len(value) > 3 and not field.endswith("At"):
                assert value not in text, field
    assert identity_leaks(text) == []


def test_collect_references_returns_accepted_then_recommended_and_nothing_else():
    client = FixtureClient()
    records = collect_references(client, client.corpus_id, HomePageSettings())
    assert [record["status"] for record in records] == ["accepted"] * 8 + ["recommended"] * 4
    titles = [record["title"] for record in records]
    for absent in ("Rejected", "Archived", "Pending low", "Pending predicted reject", "Superseded old version"):
        assert absent not in titles


def test_the_recommended_threshold_is_the_setting():
    client = FixtureClient()
    strict = home_page_settings_from_mapping({"references": {"recommendedThreshold": 0.9}})
    records = collect_references(client, client.corpus_id, strict)
    assert [record["title"] for record in records if record["status"] == "recommended"] == ["Pending high"]


def test_parallel_collection_gives_the_same_records():
    client = FixtureClient()
    sequential = collect_references(client, client.corpus_id, HomePageSettings())
    parallel = collect_references(client, client.corpus_id, HomePageSettings(), client_factory=FixtureClient, workers=4)
    assert parallel == sequential


def test_the_snapshot_modules_never_import_the_login_library():
    code = (
        "import sys; sys.modules['cli_login'] = None; "
        "import papyrus_content.home_page.task, papyrus_content.home_page.snapshot, papyrus_content.projection.plugins; "
        "assert 'cli_login' not in [name for name, module in sys.modules.items() if module is not None]"
    )
    environment = {**os.environ, "PYTHONPATH": str(SOURCE_ROOT)}
    result = subprocess.run([sys.executable, "-c", code], env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
