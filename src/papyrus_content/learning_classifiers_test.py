import sys
import types
from dataclasses import dataclass

import pytest

from papyrus_content.learning_classifiers import (LINK_CLASSIFIER_ID, PACK_CLASSIFIER_ID, LearningExample, PromotedLinkCalibration, example_rows,
                                                  is_promoted, order_packs, record_evaluation, sign_test_p_value, split_chronologically,
                                                  evaluate_pack_fit, link_features)
from papyrus_content.reference_suggestions import _kept


@pytest.fixture
def fake_decision_flywheel(monkeypatch):
    @dataclass(frozen=True)
    class ClassifierSpec:
        id: str
        labels: tuple
        question: str
        positive_label: str | None = None

    module = types.ModuleType("decision_flywheel")
    module.ClassifierSpec = ClassifierSpec
    monkeypatch.setitem(sys.modules, "decision_flywheel", module)


def test_the_learning_classifiers_are_derived_beside_the_section_classifiers(fake_decision_flywheel):
    from papyrus_content.site_cyclotron import site_classifier_specs

    sections = [{"id": "a", "enabled": True, "sortOrder": 1}, {"id": "b", "enabled": True, "sortOrder": 2}]
    plain = [spec.id for spec in site_classifier_specs(sections)]
    with_learning = site_classifier_specs(sections, include_learning=True)
    assert [spec.id for spec in with_learning][: len(plain)] == plain
    assert [spec.id for spec in with_learning][len(plain):] == [LINK_CLASSIFIER_ID, PACK_CLASSIFIER_ID]
    assert with_learning[-2].positive_label == "fits" and with_learning[-1].positive_label == "worth-an-idea"


def test_chronological_split_holds_out_the_latest_decisions():
    examples = [LearningExample(f"e{i}", f"2026-10-{i + 1:02d}", True, "", {}, "t", "", "") for i in range(10)]
    train, held = split_chronologically(examples, 0.3)
    assert [e.example_id for e in held] == ["e7", "e8", "e9"] and len(train) == 7
    assert split_chronologically(examples[:1])[1] == []
    with pytest.raises(ValueError):
        split_chronologically(examples, 1.0)


def test_sign_test_needs_clear_wins():
    assert sign_test_p_value(0, 0) == 1.0
    assert sign_test_p_value(8, 0) == pytest.approx(1 / 256)
    assert sign_test_p_value(3, 2) > 0.05


def test_a_missing_prediction_blocks_promotion():
    held = [LearningExample("a", "x", True, "", {"surprise": 1.0}, "t", "", ""), LearningExample("b", "x", False, "", {"surprise": 2.0}, "t", "", "")]
    assert not evaluate_pack_fit(held, {"a": 0.9}).promoted


def test_the_promotion_flag_defaults_off_and_follows_the_latest_evaluation(tmp_path):
    held = [LearningExample(f"g{i}", "x", True, "", {"surprise": 1.0}, "t", "", "") for i in range(8)] + \
           [LearningExample(f"b{i}", "x", False, "", {"surprise": 2.0}, "t", "", "") for i in range(8)]
    assert not is_promoted(tmp_path, PACK_CLASSIFIER_ID)
    record_evaluation(tmp_path, evaluate_pack_fit(held, {e.example_id: 0.9 if e.positive else 0.1 for e in held}), "now")
    assert is_promoted(tmp_path, PACK_CLASSIFIER_ID)
    record_evaluation(tmp_path, evaluate_pack_fit(held, {e.example_id: 0.1 if e.positive else 0.9 for e in held}), "later")
    assert not is_promoted(tmp_path, PACK_CLASSIFIER_ID)


def test_rows_use_the_priming_shape_with_the_explanation():
    example = LearningExample("link-1", "2026-11-01T00:00:00Z", False, "off-topic: no", {"similarity": 0.5}, "A <-> B", "https://x.example", "s")
    row = example_rows(LINK_CLASSIFIER_ID, [example])[0]
    assert row["labels"] == {LINK_CLASSIFIER_ID: {"label": "does-not-fit", "explanation": "off-topic: no"}}
    assert "similarity" in row["values"]["text"] and row["provenance"]["modelMade"] is False


def test_link_features():
    first = {"sourceUri": "https://www.x.example/a", "sourcePublishedAt": "2026-10-01", "curationStatus": "accepted", "curationStatusUpdatedBy": "user:s"}
    second = {**first, "sourceUri": "https://x.example/b", "sourcePublishedAt": "2026-10-11"}
    features = link_features(0.7, first, second, {"c1", "c2"}, {"c2"})
    assert features == {"similarity": 0.7, "sharedConcepts": 1, "sharedHost": True, "publicationGapDays": 10, "bothHumanAccepted": True}


class Rule:
    def label(self, kind, similarity):
        return "likely" if similarity >= 0.8 else "possible"


def test_suggestions_switch_to_the_trained_version_only_when_promoted():
    candidate = {"lineageId": "x", "similarity": 0.4}
    off = PromotedLinkCalibration(Rule(), False, lambda c: 0.9)
    on = PromotedLinkCalibration(Rule(), True, lambda c: 0.9)
    assert _kept(candidate, "created", off, "reference")["label"] == "possible"
    assert _kept(candidate, "created", on, "reference")["label"] == "likely"


def test_packs_are_reordered_only_when_promoted():
    packs = ["p1", "p2", "p3"]
    scores = {"p1": 0.1, "p2": 0.9, "p3": 0.5}
    assert order_packs(packs, False, scores.get) == packs
    assert order_packs(packs, True, scores.get) == ["p2", "p3", "p1"]
