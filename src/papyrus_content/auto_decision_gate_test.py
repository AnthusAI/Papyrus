import json

from papyrus_content.auto_decision_gate import auto_decision_gate, load_approved_proof, proof_is_due

NOW = "2026-10-18T12:00:00Z"


def approved_proof(*, labels=23, agreement=0.96, ran_at="2026-10-10T00:00:00Z"):
    return {"proofId": "ti-cv-1", "ranAt": ran_at, "heldOut": {"size": labels},
            "points": [{"labels": 0, "agreement": 0.78}, {"labels": 18, "agreement": agreement}]}


def test_without_an_approved_proof_nothing_may_be_decided_automatically():
    gate = auto_decision_gate(None, human_label_count=23, now=NOW)
    assert gate["allowed"] is False
    assert gate["reason"] == "no approved proof"
    assert gate["scope"] is None


def test_a_fresh_approved_proof_allows_only_rejecting_clear_misses():
    gate = auto_decision_gate(approved_proof(), human_label_count=27, now=NOW)
    assert gate == {"allowed": True, "scope": "reject-clear-misses", "reason": None,
                    "proofId": "ti-cv-1", "humanLabelCount": 27}


def test_ten_new_labels_make_the_proof_stale_and_a_new_draft_proof_due():
    assert auto_decision_gate(approved_proof(), human_label_count=33, now=NOW)["allowed"] is False
    assert proof_is_due(approved_proof(), human_label_count=33, now=NOW) == "10 new human labels since the approved proof"
    assert proof_is_due(approved_proof(), human_label_count=32, now=NOW) is None


def test_an_old_proof_is_stale():
    gate = auto_decision_gate(approved_proof(ran_at="2026-08-01T00:00:00Z"), human_label_count=23, now=NOW)
    assert gate["allowed"] is False
    assert "days old" in gate["reason"]


def test_a_proof_with_low_agreement_never_allows_automatic_decisions():
    gate = auto_decision_gate(approved_proof(agreement=0.8), human_label_count=23, now=NOW)
    assert gate["allowed"] is False
    assert "below" in gate["reason"]


def test_a_missing_proof_file_is_no_proof(tmp_path):
    assert load_approved_proof(None) is None
    assert load_approved_proof(str(tmp_path / "missing.json")) is None
    proof_file = tmp_path / "proof.json"
    proof_file.write_text(json.dumps(approved_proof()))
    assert load_approved_proof(str(proof_file))["proofId"] == "ti-cv-1"
