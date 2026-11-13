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
    entry_of,
    has_prediction,
    is_chosen,
    stored_prediction,
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
        (None, None),
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
    assert len(records) == 11
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
    assert [record["status"] for record in records] == ["accepted"] * 8 + ["recommended"] * 3
    titles = [record["title"] for record in records]
    for absent in ("Rejected", "Archived", "Pending low", "Pending predicted reject", "Superseded old version", "Pending undecided"):
        assert absent not in titles


def rate(client, title, stars):
    row = next(row for row in client.rows() if row["title"].startswith(title))
    row.update({"starRating": stars, "starRatedAt": "2026-10-31T09:00:00.000Z", "starRatedBy": "editor-who-rated@example.test"})


def test_every_record_carries_a_rank_and_only_an_accepted_one_carries_its_stars():
    client = FixtureClient()
    for title, stars in (("Accepted one", 5), ("Accepted eight", 2), ("Pending mid", 4)):
        rate(client, title, stars)
    records = collect_references(client, client.corpus_id, HomePageSettings())
    assert sorted(record["rank"] for record in records) == list(range(1, len(records) + 1))
    by_title = {record["title"]: record["rank"] for record in records}
    assert by_title["Accepted one"] < by_title["Pending mid"] < by_title["Accepted two"] < by_title["Accepted eight"], "5 stars, 4 stars, unrated and a 2 star Reference the Cyclotron is sure of"
    stars_of = {record["title"]: record["stars"] for record in records}
    assert stars_of["Accepted one"] == 5 and stars_of["Accepted eight"] == 2, "an accepted Reference shows the count an editor gave it"
    assert stars_of["Pending mid"] is None, "a pending Reference is rated too, but a list of recommended ones shows its confidence instead"
    assert stars_of["Accepted two"] is None, "nobody rated it, so there is nothing to show"
    text = json.dumps(records)
    for private in ("starRating", "starRatedAt", "starRatedBy", "editor-who-rated@example.test"):
        assert private not in text, "the count is published as stars; who rated it and when are not published"
    assert sorted({name for record in records for name in record if "star" in name.lower()}) == ["stars"]


def test_unrated_records_are_ranked_by_confidence_then_newest_arrival_then_key():
    client = FixtureClient()
    records = collect_references(client, client.corpus_id, HomePageSettings())
    ordered = [record["title"] for record in sorted(records, key=lambda record: record["rank"])]
    assert ordered[:3] == ["Accepted eight", "Accepted two", "Pending high"]


def test_a_fields_list_that_leaves_out_what_the_order_reads_does_not_change_the_order():
    client = FixtureClient()
    rate(client, "Accepted one", 5)
    everything = {record["key"]: record["rank"] for record in collect_references(client, client.corpus_id, HomePageSettings())}
    narrow = collect_references(client, client.corpus_id, settings_with_fields(["key", "status", "title"]))
    assert {record["key"]: record["rank"] for record in narrow} == everything
    assert list(narrow[0]) == ["key", "status", "title", "rank"], "rank is in every record whatever the list says"


def test_a_rating_that_moves_nothing_changes_only_the_stars_of_its_own_record():
    client = FixtureClient()
    before = collect_references(client, client.corpus_id, HomePageSettings())
    rate(client, "Accepted eight", 4)   # already first
    after = collect_references(client, client.corpus_id, HomePageSettings())
    assert [{**record, "stars": None} for record in after] == [{**record, "stars": None} for record in before]
    assert {record["title"]: record["stars"] for record in after if record["stars"]} == {"Accepted eight": 4}


def test_a_pending_reference_never_publishes_its_stars_even_when_it_is_rated():
    client = FixtureClient()
    rate(client, "Pending high", 5)
    records = {record["title"]: record for record in collect_references(client, client.corpus_id, HomePageSettings())}
    assert records["Pending high"]["stars"] is None and records["Pending high"]["confidence"] is not None


def test_stars_are_a_count_from_one_to_five_and_anything_else_is_nothing():
    client = FixtureClient()
    for bad in (0, 6, 2.5, "4", True):
        rate(client, "Accepted one", bad)
        records = {record["title"]: record for record in collect_references(client, client.corpus_id, HomePageSettings())}
        assert records["Accepted one"]["stars"] is None, bad


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


def test_the_confidence_of_a_reference_an_editor_accepted_is_not_published_but_any_other_keeps_it():
    row = {"lineageId": "l", "title": "T", "sourceUri": "https://example.org/a", "curationStatus": "accepted", "curationActorKind": "human"}
    settings = home_page_settings_from_mapping({"references": {"corpus": "c"}})
    decision = {"label": "include", "confidence": 0.9, "positiveLabel": None}

    def made(**changes):
        return public_reference({**row, **changes}, decision, None, {}, settings)

    assert made()["confidence"] is None and made()["actor"] == "human"
    assert made(curationActorKind="cyclotron")["confidence"] == 0.9
    assert made(curationActorKind="rule")["confidence"] == 0.9
    assert made(curationActorKind=None)["confidence"] == 0.9
    assert made(curationStatus="pending")["confidence"] == 0.9


def pending_row(**changes):
    return {"id": "l-v1", "lineageId": "l", "title": "T", "sourceUri": "https://example.org/a", "curationStatus": "pending", **changes}


def test_what_counts_as_a_real_prediction_is_the_stored_probability_alone():
    """Ryan, 2026-11-05: an unpredicted Reference is not 50%. Only a finite ``predictedAcceptProbability`` on the row is a prediction."""
    assert stored_prediction(pending_row()) is None
    assert stored_prediction(pending_row(predictedAcceptProbability=None)) is None
    assert stored_prediction(pending_row(predictedAcceptProbability=True)) is None
    assert stored_prediction(pending_row(predictedAcceptProbability="0.9")) is None
    assert stored_prediction(pending_row(predictedAcceptProbability=float("nan"))) is None
    assert stored_prediction(pending_row(predictionDecidedAt="2026-11-04T10:00:00.000Z")) is None, "a decision time without the number is not a prediction"
    assert stored_prediction(pending_row(predictionSortKey="0.500000#2026-11-04T18:49:50.761Z#reference-a-v1")) is None, "every row has a sort key from creation"
    assert stored_prediction(pending_row(predictedAcceptProbability=0.5)) == 0.5, "a prediction that really is 0.5 is a prediction"
    assert stored_prediction(pending_row(predictedAcceptProbability=0)) == 0.0


def test_a_pending_reference_with_no_prediction_is_not_chosen_whatever_its_decision_or_the_threshold():
    settings = HomePageSettings()
    decision = {"label": "include", "confidence": 0.99, "positiveLabel": None}
    assert not is_chosen(pending_row(), None, settings)
    assert not is_chosen(pending_row(), decision, settings), "a decision relation without the prediction written onto the row is not public yet"
    low = home_page_settings_from_mapping({"references": {"recommendedThreshold": 0}})
    assert not is_chosen(pending_row(), None, low), "not even a threshold of zero lets a missing prediction through"


def test_a_prediction_of_exactly_the_threshold_still_passes_and_the_threshold_still_decides():
    settings = HomePageSettings()
    assert is_chosen(pending_row(predictedAcceptProbability=0.5), None, settings)
    assert not is_chosen(pending_row(predictedAcceptProbability=0.49), None, settings)
    assert is_chosen(pending_row(predictedAcceptProbability=0.2), {"label": "include", "confidence": 0.9, "positiveLabel": None}, settings), "the live decision is the number compared"


def test_an_accepted_reference_with_no_prediction_stays_public_and_shows_no_confidence():
    row = {**pending_row(curationStatus="accepted", curationActorKind="rule")}
    settings = home_page_settings_from_mapping({"references": {"corpus": "c"}})
    assert is_chosen(row, None, settings)
    record = public_reference(row, None, None, {}, settings)
    assert record["confidence"] is None and record["predictedAcceptProbability"] is None
    entry = entry_of(row, None, None, {}, settings)
    assert entry.standing.confidence is None, "the order is told there is none, not 0.5"


def test_the_stored_prediction_stands_in_for_a_decision_relation_that_is_missing_but_a_decision_wins():
    settings = home_page_settings_from_mapping({"references": {"corpus": "c"}})
    row = pending_row(predictedAcceptProbability=0.8)
    assert public_reference(row, None, None, {}, settings)["confidence"] == 0.8
    assert public_reference(row, {"label": "include", "confidence": 0.7, "positiveLabel": None}, None, {}, settings)["confidence"] == 0.7


def test_the_home_page_trigger_and_the_snapshot_agree_on_which_pending_rows_have_a_prediction():
    """The trigger cannot import this package, so its ``can_show`` mirrors ``stored_prediction``; both are run over the same rows."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("home_page_trigger", SOURCE_ROOT.parent / "amplify" / "plugins" / "home-page" / "function" / "handler.py")
    trigger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trigger)

    def image_of(row):
        return {name: ({"N": str(value)} if isinstance(value, (int, float)) and not isinstance(value, bool) else {"NULL": True} if value is None else {"S": str(value)}) for name, value in row.items()}

    rows = [
        pending_row(), pending_row(predictedAcceptProbability=None), pending_row(predictedAcceptProbability=0.9), pending_row(predictedAcceptProbability=0.5),
        pending_row(predictedAcceptProbability=0), pending_row(predictedAcceptProbability="0.9"),
        pending_row(predictionDecidedAt="2026-11-04T10:00:00.000Z"), pending_row(predictionSortKey="0.500000#a#b"),
        pending_row(predictionDecidedAt="2026-11-04T10:00:00.000Z", predictionSortKey="0.500000#a#b"),
    ]
    for row in rows:
        row = {**row, "predictedAcceptProbability": row.get("predictedAcceptProbability")} if "predictedAcceptProbability" in row else row
        assert trigger.can_show(image_of(row)) == has_prediction(row), row
    accepted = pending_row(curationStatus="accepted")
    assert trigger.can_show(image_of(accepted)) and is_chosen(accepted, None, HomePageSettings())
    for status in ("rejected", "archived"):
        assert not trigger.can_show(image_of(pending_row(curationStatus=status, predictedAcceptProbability=0.9)))


def test_section_titles_are_keyed_by_the_id_a_reference_stores():
    from papyrus_content.tenancy import tenant_row_with_bare_record_id

    stored = [{"id": "machines-on-machines#security", "title": "Security"}, {"id": "machines-on-machines#music", "title": "Music"}]

    class TenantClient:
        def list_records(self, model_name):
            return [tenant_row_with_bare_record_id(model_name, "machines-on-machines", row) for row in stored]   # what the real client returns

    labels = export.section_labels_of(TenantClient())
    assert labels == {"machines-on-machines#security": "Security", "machines-on-machines#music": "Music"}
    assert labels.get("machines-on-machines#nothing") is None and labels.get("security") is None

    class UntenantedClient:
        def list_records(self, model_name):
            return [{"id": "security", "title": "Security"}]

    assert export.section_labels_of(UntenantedClient()) == {"security": "Security"}, "a backend with no tenant stores the id as it is"
