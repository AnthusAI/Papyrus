"""Opt-in auto-reject of clear misses: off by default, gated, capped, audited, never a human label."""
import pytest

from features_backend.steps.cyclotron_relevance_sweep_steps import CORPUS_ID, SweepClient
from papyrus_content.relevance_auto_reject_support import (VENDOR_TITLE, SECURITY_TITLE, BORDERLINE_TITLE, ConfidentModel,
                                                             auto_reject_context, votes_of, labels_of_store,
                                                             make_reference, reopen_as_a_person, sweep_with)
from papyrus_content.relevance_cyclotron import normalize_relevance_cyclotron_config
from papyrus_content.relevance_decisions import human_label_for_review
from papyrus_content.relevance_sweep import _human_label_count

ENABLED = {"enabled": True, "minimumRejectProbability": 0.95, "maxRejectsPerSweep": 10}


def statuses(client):
    return {row["lineageId"]: row["curationStatus"] for row in client.tables["Reference"].values()}


def test_auto_reject_is_off_by_default_even_with_an_open_gate(tmp_path):
    context = auto_reject_context(tmp_path, auto_reject=None, proof=True)
    vendor = make_reference("reference-vendor", VENDOR_TITLE)
    client = SweepClient({"Reference": [vendor]})
    result = sweep_with(context, ConfidentModel(), client, tmp_path)
    assert result.auto_rejected == []
    assert result.to_json()["autoRejected"] == []
    assert statuses(client) == {"reference-vendor": "pending"}


def test_a_closed_gate_blocks_auto_reject(tmp_path):
    context = auto_reject_context(tmp_path, auto_reject=ENABLED, proof=False)
    vendor = make_reference("reference-vendor", VENDOR_TITLE)
    client = SweepClient({"Reference": [vendor]})
    result = sweep_with(context, ConfidentModel(), client, tmp_path)
    assert result.live_agreement["autoDecision"]["allowed"] is False
    assert result.auto_rejected == []
    assert statuses(client) == {"reference-vendor": "pending"}


def test_a_miss_below_the_probability_threshold_is_left_pending(tmp_path):
    context = auto_reject_context(tmp_path, auto_reject=ENABLED, proof=True)
    borderline = make_reference("reference-borderline", BORDERLINE_TITLE)
    client = SweepClient({"Reference": [borderline]})
    result = sweep_with(context, ConfidentModel(), client, tmp_path)
    assert result.decided == 1 and result.auto_rejected == []
    assert statuses(client) == {"reference-borderline": "pending"}


def test_a_reference_a_person_already_reviewed_is_never_touched(tmp_path):
    context = auto_reject_context(tmp_path, auto_reject=ENABLED, proof=True)
    reopened = make_reference("reference-vendor", VENDOR_TITLE)
    client = SweepClient({"Reference": [reopened]})
    reopen_as_a_person(client, reopened)
    result = sweep_with(context, ConfidentModel(), client, tmp_path)
    assert result.decided == 1 and result.auto_rejected == []
    assert statuses(client) == {"reference-vendor": "pending"}
    assert len(votes_of(client, "reference-vendor")) == 1


def test_a_reference_moved_out_of_pending_is_not_rejected_again(tmp_path):
    context = auto_reject_context(tmp_path, auto_reject=ENABLED, proof=True)
    vendor = make_reference("reference-vendor", VENDOR_TITLE)
    client = SweepClient({"Reference": [vendor]})
    sweep_with(context, ConfidentModel(), client, tmp_path)
    reopen_as_a_person(client, vendor, at="2999-01-01T00:00:00Z")
    again = sweep_with(context, ConfidentModel(), client, tmp_path)
    assert again.auto_rejected == []
    assert statuses(client) == {"reference-vendor": "pending"}


def test_no_more_than_the_per_sweep_cap_is_rejected(tmp_path):
    context = auto_reject_context(tmp_path, auto_reject={**ENABLED, "maxRejectsPerSweep": 2}, proof=True)
    references = [make_reference(f"reference-vendor-{index}", VENDOR_TITLE) for index in range(3)]
    client = SweepClient({"Reference": references})
    result = sweep_with(context, ConfidentModel(), client, tmp_path)
    assert result.decided == 3
    assert len(result.auto_rejected) == 2
    assert sorted(statuses(client).values()) == ["pending", "rejected", "rejected"]


def test_the_daily_decision_cap_also_bounds_auto_rejection(tmp_path):
    context = auto_reject_context(tmp_path, auto_reject=ENABLED, proof=True, extra={"maxDecisionsPerDay": 1})
    references = [make_reference(f"reference-vendor-{index}", VENDOR_TITLE) for index in range(3)]
    client = SweepClient({"Reference": references})
    result = sweep_with(context, ConfidentModel(), client, tmp_path)
    assert result.stopped_because == "daily decision cap"
    assert len(result.auto_rejected) == 1


def test_a_clear_miss_is_rejected_with_an_audited_cyclotron_message_and_nothing_is_accepted(tmp_path):
    context = auto_reject_context(tmp_path, auto_reject=ENABLED, proof=True)
    vendor = make_reference("reference-vendor", VENDOR_TITLE)
    security = make_reference("reference-security", SECURITY_TITLE)
    client = SweepClient({"Reference": [vendor, security]})
    result = sweep_with(context, ConfidentModel(), client, tmp_path)
    assert statuses(client) == {"reference-vendor": "rejected", "reference-security": "pending"}
    assert "accepted" not in statuses(client).values()
    (rejection,) = result.auto_rejected
    assert rejection == {"lineageId": "reference-vendor", "probability": 0.99, "proofId": "ti-cv-1"}
    assert result.to_json()["autoRejected"] == [rejection]
    row = client.tables["Reference"][vendor["id"]]
    assert row["curationStatusKey"] == f"{CORPUS_ID}#rejected"
    assert "papyrus-relevance" in row["curationStatusUpdatedBy"]
    # The vote is on the Reference itself; no Message is written.
    (vote,) = votes_of(client, "reference-vendor")
    assert vote["actorKind"] == "cyclotron" and vote["action"] == "reject" and vote["reasonCode"] == "out_of_scope"
    assert "Message" not in client.tables or not client.tables["Message"]
    for fact in ("papyrus-relevance", "99.0%", "ti-cv-1"):
        assert fact in row["curationStatusReason"]


def test_an_auto_rejection_is_not_a_human_label_and_never_teaches(tmp_path):
    context = auto_reject_context(tmp_path, auto_reject=ENABLED, proof=True)
    vendor = make_reference("reference-vendor", VENDOR_TITLE)
    client = SweepClient({"Reference": [vendor]})
    sweep_with(context, ConfidentModel(), client, tmp_path)
    rejected = client.tables["Reference"][vendor["id"]]
    assert human_label_for_review(rejected, labels=["include", "exclude"]) is None
    assert _human_label_count_of(client) == 0
    sweep_with(context, ConfidentModel(), client, tmp_path)
    assert labels_of_store(context) == {}


def _human_label_count_of(client):
    from unittest import mock

    with mock.patch("papyrus_content.relevance_sweep.download_attachment_buffer", return_value=None):
        return _human_label_count(client, ["include", "exclude"], CORPUS_ID)


def test_a_dry_run_lists_what_would_be_rejected_and_writes_nothing(tmp_path):
    context = auto_reject_context(tmp_path, auto_reject=ENABLED, proof=True)
    vendor = make_reference("reference-vendor", VENDOR_TITLE)
    borderline = make_reference("reference-borderline", BORDERLINE_TITLE)
    client = SweepClient({"Reference": [vendor, borderline]})
    context.steering["relevanceCyclotron"]["autoReject"] = {**ENABLED, "enabled": False}
    sweep_with(context, ConfidentModel(), client, tmp_path)
    context.steering["relevanceCyclotron"]["autoReject"] = ENABLED
    writes_before = len(client.calls)
    result = sweep_with(context, ConfidentModel(), client, tmp_path, apply=False)
    assert result.applied is False
    assert result.auto_rejected == [{"lineageId": "reference-vendor", "probability": 0.99, "proofId": "ti-cv-1"}]
    assert statuses(client) == {"reference-vendor": "pending", "reference-borderline": "pending"}
    assert [call for call in client.calls[writes_before:] if call[0] != "get"] == []
    assert votes_of(client, "reference-vendor") == []


def test_the_configuration_defaults_to_off_and_refuses_unknown_or_invalid_fields():
    defaults = normalize_relevance_cyclotron_config({})["autoReject"]
    assert defaults == {"enabled": False, "minimumRejectProbability": 0.95, "maxRejectsPerSweep": 10}
    chosen = normalize_relevance_cyclotron_config({"autoReject": {"enabled": True, "maxRejectsPerSweep": 3}})
    assert chosen["autoReject"] == {"enabled": True, "minimumRejectProbability": 0.95, "maxRejectsPerSweep": 3}
    for bad, fragment in (({"surprise": 1}, "unknown fields: surprise"), ({"enabled": "yes"}, "enabled"),
                          ({"minimumRejectProbability": 0.3}, "minimumRejectProbability"),
                          ({"minimumRejectProbability": 1.5}, "minimumRejectProbability"),
                          ({"maxRejectsPerSweep": 0}, "maxRejectsPerSweep"), ("on", "must be an object")):
        with pytest.raises(ValueError, match=fragment):
            normalize_relevance_cyclotron_config({"autoReject": bad})
