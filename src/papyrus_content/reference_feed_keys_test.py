import json
from pathlib import Path

from .reference_feed_keys import accept_probability, feed_keys, original_prediction_fields

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "fixtures" / "reference-feed-key-vectors.json").read_text())


def test_the_keys_match_the_vectors_the_typescript_twin_is_tested_against():
    for vector in VECTORS:
        assert feed_keys(vector["reference"]) == vector["keys"], vector["name"]


def test_accept_probability_is_the_include_confidence_or_one_minus_the_exclude_confidence():
    assert accept_probability("include", "include", 0.8) == 0.8
    assert abs(accept_probability("exclude", "include", 0.8) - 0.2) < 1e-12
    assert accept_probability("include", None, 0.7) == 0.7
    assert accept_probability("include", "include", None) == 0.6   # a label with no recorded confidence is a mild lean
    assert abs(accept_probability("exclude", "include", None) - 0.4) < 1e-12


def test_the_original_prediction_is_written_once():
    reference = {"id": "r-v1", "corpusId": "c", "curationStatus": "pending", "createdAt": "2026-10-28T12:00:00Z"}
    first = original_prediction_fields(reference, label="include", positive_label="include", confidence=0.9, decided_at="2026-10-28T12:01:00Z")
    assert first["predictedAcceptProbability"] == 0.9 and first["predictionSortKey"].startswith("0.900000#")
    assert original_prediction_fields({**reference, **first}, label="exclude", positive_label="include", confidence=0.99,
                                      decided_at="2026-10-29T00:00:00Z") == {}
