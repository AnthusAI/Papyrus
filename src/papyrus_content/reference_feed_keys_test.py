import json
from pathlib import Path

from .reference_feed_keys import (accept_probability, content_needed_key, feed_keys, medium_feed_key, medium_key_patch, moved_content_key,
                                  original_prediction_fields, stale_feed_keys, stale_star_feed_key, star_feed_key)

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "fixtures" / "reference-feed-key-vectors.json").read_text())


def test_the_keys_match_the_vectors_the_typescript_twin_is_tested_against():
    for vector in VECTORS:
        # never carries the star key: callers spread it on partial patches; the medium key is checked on its own below
        assert {key: value for key, value in feed_keys(vector["reference"]).items() if key not in ("mediumFeedKey", "contentNeededKey")} == vector["keys"], vector["name"]
        if "contentNeededKey" in vector:
            assert content_needed_key(vector["reference"]) == vector["contentNeededKey"], vector["name"]
        if "mediumFeedKey" in vector:
            assert medium_feed_key(vector["reference"]) == vector["mediumFeedKey"], vector["name"]
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


VIDEO = "https://youtu.be/dQw4w9WgXcQ"


def test_the_medium_key_follows_the_vote_and_lists_each_status_apart():
    base = {"id": "r", "corpusId": "c", "sourceUri": VIDEO, "versionState": "current"}
    assert medium_feed_key({**base, "curationStatus": "accepted"}) == "c#video#accepted"
    assert medium_feed_key({**base, "curationStatus": "pending"}) == "c#video#pending"
    assert medium_feed_key({**base, "curationStatus": "rejected"}) == "c#video#rejected"
    assert medium_feed_key({**base, "curationStatus": "archived"}) is None
    assert medium_feed_key({**base, "curationStatus": "accepted", "versionState": "superseded"}) is None
    assert medium_feed_key({**base, "curationStatus": "accepted", "sourceUri": "https://example.org/a"}) is None
    assert medium_feed_key({**base, "curationStatus": "accepted", "corpusId": None}) is None
    assert medium_feed_key({**base, "curationStatus": "accepted", "sourceUri": None, "medium": "video"}) == "c#video#accepted"


def test_feed_keys_carry_the_medium_key_only_when_there_is_one_to_set_or_clear():
    ordinary = feed_keys({"id": "r", "corpusId": "c", "curationStatus": "pending", "sourceUri": "https://example.org/a"})
    assert "mediumFeedKey" not in ordinary   # an explicit null on a new row's index key is not a missing attribute
    assert feed_keys({"id": "r", "corpusId": "c", "curationStatus": "pending", "sourceUri": VIDEO})["mediumFeedKey"] == "c#video#pending"
    assert feed_keys({"id": "r", "corpusId": "c", "curationStatus": "archived", "sourceUri": VIDEO, "mediumFeedKey": "c#video#pending"})["mediumFeedKey"] is None


def test_the_feed_key_backfill_leaves_the_medium_key_to_the_medium_backfill():
    assert "mediumFeedKey" not in stale_feed_keys({"id": "r", "corpusId": "c", "curationStatus": "pending", "sourceUri": VIDEO, "versionState": "current"})


def test_a_vote_patch_names_the_medium_key_only_for_a_reference_with_a_medium():
    video = {"id": "r", "corpusId": "c", "sourceUri": VIDEO, "curationStatus": "pending", "versionState": "current"}
    assert medium_key_patch(video, curationStatus="accepted") == {"mediumFeedKey": "c#video#accepted"}
    assert medium_key_patch(video, curationStatus="archived") == {"mediumFeedKey": None}
    assert medium_key_patch({**video, "sourceUri": "https://example.org/a"}, curationStatus="accepted") == {}
    assert medium_key_patch({**video, "sourceUri": "https://example.org/a", "mediumFeedKey": "c#video#pending"}, curationStatus="accepted") == {"mediumFeedKey": None}


def test_a_held_content_key_moves_with_a_vote_and_leaves_on_archive_without_reading_the_capture_state():
    held = {"corpusId": "c", "curationStatus": "pending", "medium": "video", "mediumFeedKey": "c#video#pending", "contentNeededKey": "c#video#needs_content#pending"}
    assert medium_key_patch(held, curationStatus="accepted") == {"mediumFeedKey": "c#video#accepted", "contentNeededKey": "c#video#needs_content#accepted"}
    assert medium_key_patch(held, curationStatus="archived") == {"mediumFeedKey": None, "contentNeededKey": None}
    assert medium_key_patch(held, versionState="superseded") == {"mediumFeedKey": None, "contentNeededKey": None}
    assert moved_content_key("c#video#needs_content#pending", {**held, "curationStatus": "rejected"}) == "c#video#needs_content#rejected"


def test_a_vote_on_a_video_that_holds_no_content_key_names_no_content_field():
    captured = {"corpusId": "c", "curationStatus": "pending", "medium": "video", "mediumFeedKey": "c#video#pending", "captureState": "full"}
    assert medium_key_patch(captured, curationStatus="accepted") == {"mediumFeedKey": "c#video#accepted"}


def test_the_stale_feed_key_check_leaves_the_content_key_to_the_backfill_and_the_capture_sync():
    video = {"id": "r", "corpusId": "c", "curationStatus": "accepted", "medium": "video", "versionState": "current", "createdAt": "2026-11-01T00:00:00Z"}
    assert "contentNeededKey" not in stale_feed_keys(video)
    assert feed_keys(video)["contentNeededKey"] == "c#video#needs_content#accepted"
    assert "contentNeededKey" not in feed_keys({**video, "medium": None, "sourceUri": "https://example.org/a"})
