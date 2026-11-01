import json
from pathlib import Path

from .keys import concept_hashtag, concept_hashtag_label, concept_keys_for_hashtag, entity_key

VECTORS = json.loads((Path(__file__).resolve().parents[3] / "features_backend" / "fixtures" / "concept-hashtags.json").read_text())
NODE_KEYS = VECTORS["nodeKeys"]


def test_hashtag_is_the_name_part_of_the_node_key():
    for vector in VECTORS["hashtags"]:
        assert concept_hashtag(vector["nodeKey"]) == vector["hashtag"]


def test_round_trip_from_entity_key_through_hashtag_back_to_the_key():
    key = entity_key("concept", "Voice Cloning")
    assert concept_keys_for_hashtag(concept_hashtag(key), [key, "task--other"]) == [key]


def test_collision_display_names_the_kind():
    for vector in VECTORS["labels"]:
        assert concept_hashtag_label(vector["nodeKey"], NODE_KEYS) == vector["label"]


def test_parse_returns_candidates_with_exact_key_first():
    for vector in VECTORS["parse"]:
        assert concept_keys_for_hashtag(vector["text"], NODE_KEYS) == vector["candidates"]
