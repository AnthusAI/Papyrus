"""The automatic Section's rules on synthetic References, a scripted model and a fake site function (docs/reference-auto-section.md)."""
import json

import pytest

from features_backend.steps.reference_auto_section_steps import (ART, CONFIDENT_PROOF, MUSIC, PROOF_MODEL, SECURITY, AutoSectionClient, SlugModel,
                                                               accepted, person_sets_section, proof_report, row, run, steering_for)
from papyrus_content.relevance_decisions import human_section_for_review
from papyrus_content.site_auto_section import calibration_from_proof, person_owns_section, proposal_for, why_not_eligible
from papyrus_content.site_cyclotron import normalize_auto_section_policy


def test_only_a_section_nobody_touched_or_the_machine_set_is_the_machines_to_change():
    assert not person_owns_section({})
    assert not person_owns_section({"curationSectionId": SECURITY, "curationSectionActorKind": "cyclotron"})
    assert person_owns_section({"curationSectionId": SECURITY, "curationSectionActorKind": "human"})
    assert person_owns_section({"curationSectionId": SECURITY}), "a section recorded with an accept before the actor kind existed is a person's"
    assert person_owns_section({"curationSectionUpdatedBy": "editor@example.org"}), "a person's clear"
    assert person_owns_section({"curationSectionActorKind": "agent"}), "an operator's clear"
    assert why_not_eligible({"curationStatus": "pending"}) == "not accepted"
    assert why_not_eligible({"curationStatus": "accepted", "versionState": "superseded"}) == "not the current version"


def test_the_threshold_comes_from_the_held_out_evidence_and_the_target_precision():
    learned = calibration_from_proof(proof_report(CONFIDENT_PROOF), model_identity=PROOF_MODEL, precision=0.9)
    assert learned["threshold"] == 0.95 and learned["heldOut"] == 60 and learned["votes"] == 40 and learned["lowerBound"] >= 0.9
    stricter = calibration_from_proof(proof_report(CONFIDENT_PROOF), model_identity=PROOF_MODEL, precision=0.95)
    assert stricter["threshold"] is None and "held-out editor Section choices" in stricter["reason"], "40 of 40 cannot prove 95% at 95% confidence"
    few = calibration_from_proof(proof_report([[0.99, True]] * 5), model_identity=PROOF_MODEL, precision=0.9)
    assert few["threshold"] is None, "five agreeing examples are not evidence of 90%"


def test_a_proof_of_another_model_a_dry_run_proof_or_no_calibration_gives_no_threshold():
    assert "run the proof again" in calibration_from_proof(proof_report(CONFIDENT_PROOF, model="other"), model_identity=PROOF_MODEL, precision=0.9)["reason"]
    assert calibration_from_proof({**proof_report(CONFIDENT_PROOF), "dryRun": True}, model_identity=PROOF_MODEL, precision=0.9)["threshold"] is None
    no_pairs = {**proof_report([]), "selector": {"status": "not-yet-provable", "reason": "needs 10 placed References"}}
    assert "needs 10 placed References" in calibration_from_proof(no_pairs, model_identity=PROOF_MODEL, precision=0.9)["reason"]


def _relation(label, confidence, relation_id="relation-1"):
    return {"id": relation_id, "confidence": confidence, "modelVersion": "3",
            "metadata": json.dumps({"label": label, "classifier": "section-selector-x", "cyclotronId": "c", "probabilities": {label: confidence}})}


def test_the_machine_clears_its_own_tag_when_its_newest_decision_no_longer_supports_it():
    learned = {"threshold": 0.9, "votes": 40, "heldOut": 60, "rate": 1.0, "lowerBound": 0.91, "targetPrecision": 0.9, "proofId": "p"}
    sections = {SECURITY: {"id": SECURITY, "title": "Security"}}
    tagged = {"id": "r-v2", "lineageId": "r", "curationSectionId": SECURITY, "curationSectionActorKind": "cyclotron",
              "curationSectionDecisionRelationId": "relation-old"}
    assert proposal_for(tagged, _relation(SECURITY, 0.5, "relation-new"), learned, sections)["action"] == "clear"
    assert proposal_for(tagged, _relation(SECURITY, 0.95, "relation-new"), learned, sections)["action"] == "set"
    assert proposal_for({**tagged, "curationSectionDecisionRelationId": "relation-new"}, _relation(SECURITY, 0.95, "relation-new"), learned,
                        sections)["action"] == "unchanged"
    untagged = {"id": "s-v1", "lineageId": "s"}
    assert proposal_for(untagged, _relation(SECURITY, 0.5), learned, sections)["action"] == "leave"
    assert proposal_for(untagged, _relation("retired#section", 0.99), learned, sections)["action"] == "leave", "only an enabled Section is set"


def test_a_machine_section_never_teaches_the_cyclotron():
    reference = {"curationStatus": "accepted", "curationActorKind": "human", "curationStatusUpdatedAt": "2026-11-01T00:00:00Z",
                 "curationSectionId": SECURITY, "lineageId": "r", "id": "r-v1"}
    assert human_section_for_review(reference, [SECURITY]) == SECURITY
    assert human_section_for_review({**reference, "curationSectionActorKind": "cyclotron"}, [SECURITY]) is None


def test_a_new_version_is_decided_again_and_the_machine_re_tags_it(tmp_path):
    client = AutoSectionClient({"Reference": [accepted("video-a", "Clearly a security exploit walkthrough", medium="video")]})
    steering = steering_for(tmp_path, proof=proof_report(CONFIDENT_PROOF))
    model = SlugModel()
    run(client, steering, tmp_path, model=model)
    assert row(client, "video-a")["curationSectionId"] == SECURITY
    # The Reference changes meaning in a new version (the same row id here, a higher version number): the old decision was about version 1.
    row(client, "video-a").update(versionNumber=2, title="Clearly a music video now", updatedAt="2026-11-14T00:00:00Z")
    calls = model.calls
    result = run(client, steering, tmp_path, model=model, scope="all")
    assert model.calls == calls + 1 and result.decided == 1
    assert row(client, "video-a")["curationSectionId"] == MUSIC and row(client, "video-a")["curationSectionActorKind"] == "cyclotron"


def test_a_person_who_acts_between_the_decision_and_the_write_wins(tmp_path):
    client = AutoSectionClient({"Reference": [accepted("video-a", "Clearly a security exploit walkthrough")]})
    original = client.graphql

    def a_person_first(query, variables=None):
        if "SetReferenceSectionAutomatically" in query:
            person_sets_section(client, "video-a", ART)
        return original(query, variables)

    client.graphql = a_person_first
    result = run(client, steering_for(tmp_path, proof=proof_report(CONFIDENT_PROOF)), tmp_path)
    assert row(client, "video-a")["curationSectionId"] == ART and result.counts == {"skipped": 1}


def test_the_watermark_limits_the_next_pass_to_what_changed(tmp_path):
    client = AutoSectionClient({"Reference": [accepted("video-a", "Clearly a security exploit walkthrough")]})
    steering = steering_for(tmp_path, proof=proof_report(CONFIDENT_PROOF))
    first = run(client, steering, tmp_path)
    assert first.watermark == "2026-11-13T10:00:00Z" and first.read == 1
    client.upsert("Reference", accepted("video-b", "Clearly an art piece", updated_at="2026-11-13T11:00:00Z"))
    second = run(client, steering, tmp_path)
    assert second.read == 1 and [proposal["lineageId"] for proposal in second.proposals] == ["video-b"]
    assert row(client, "video-b")["curationSectionId"] == ART


def test_switched_off_decides_nothing(tmp_path):
    client = AutoSectionClient({"Reference": [accepted("video-a", "Clearly a security exploit walkthrough")]})
    model = SlugModel()
    result = run(client, steering_for(tmp_path, proof=proof_report(CONFIDENT_PROOF), auto_section={"enabled": False}), tmp_path, model=model)
    assert result.stopped_because == "disabled" and model.calls == 0 and not row(client, "video-a").get("curationSectionId")


def test_the_policy_is_validated():
    assert normalize_auto_section_policy(None) == {"enabled": True, "precision": 0.9, "proofPath": None}
    with pytest.raises(ValueError, match="precision"):
        normalize_auto_section_policy({"precision": 1.5})
    with pytest.raises(ValueError, match="unknown fields"):
        normalize_auto_section_policy({"threshold": 0.8})


def test_a_proof_of_another_section_list_gives_no_threshold():
    report = proof_report(CONFIDENT_PROOF)
    report["selector"]["classifierId"] = "section-selector-00000000"
    learned = calibration_from_proof(report, model_identity=PROOF_MODEL, precision=0.9, selector_id="section-selector-11111111")
    assert learned["threshold"] is None and "another Section list" in learned["reason"]
