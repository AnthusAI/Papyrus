import json
from pathlib import Path

from .reference_feed_keys import accept_probability, feed_keys, original_prediction_fields, stale_star_feed_key, star_feed_key

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "fixtures" / "reference-feed-key-vectors.json").read_text())


def test_the_keys_match_the_vectors_the_typescript_twin_is_tested_against():
    for vector in VECTORS:
        assert feed_keys(vector["reference"]) == vector["keys"], vector["name"]   # never carries the star key: callers spread it on partial patches
        if "starFeedKey" in vector:
            reference = vector["reference"]
            assert star_feed_key(reference.get("corpusId"), reference.get("starRating")) == vector["starFeedKey"], vector["name"]


def test_star_keys_ignore_what_is_not_a_rating_and_the_stale_check_names_only_the_key():
    assert star_feed_key("c", None) is None and star_feed_key("c", 0) is None and star_feed_key("c", 6) is None and star_feed_key("c", True) is None
    assert star_feed_key("c", float("nan")) is None and star_feed_key("c", float("inf")) is None
    assert star_feed_key("", 3) is None and star_feed_key("c", "4") is None
    assert star_feed_key("c", 4.0) == "c#stars#4"
    assert stale_star_feed_key({"corpusId": "c", "starRating": 4, "starFeedKey": "c#stars#4"}) == {}
    assert stale_star_feed_key({"corpusId": "c", "starRating": 4}) == {"starFeedKey": "c#stars#4"}
    assert stale_star_feed_key({"corpusId": "c", "starFeedKey": "c#stars#2"}) == {"starFeedKey": None}
    assert stale_star_feed_key({"corpusId": "c"}) == {}


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


def test_the_backfill_covers_the_site_corpus_named_corpora_or_every_corpus():
    import pytest
    from .reference_feed_backfill import corpus_ids_for

    class Client:
        def list_records(self, model):
            assert model == "KnowledgeCorpus"
            return [{"id": "knowledge-corpus-b"}, {"id": "knowledge-corpus-a"}, {"id": "knowledge-corpus-a"}, {}]

    assert corpus_ids_for(Client(), site="site", corpus_keys=None, all_corpora=False) == ["knowledge-corpus-site"]
    assert corpus_ids_for(Client(), site="site", corpus_keys="a, b,a", all_corpora=False) == ["knowledge-corpus-a", "knowledge-corpus-b"]
    assert corpus_ids_for(Client(), site="site", corpus_keys="a", all_corpora=True) == ["knowledge-corpus-a", "knowledge-corpus-b"]
    with pytest.raises(ValueError, match="needs"):
        corpus_ids_for(Client(), site=None, corpus_keys=None, all_corpora=False)
