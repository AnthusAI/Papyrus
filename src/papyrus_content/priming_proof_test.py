"""The priming proof on synthetic references and a scripted model: method, not editorial quality."""
import json
from types import SimpleNamespace

import pytest
from decision_flywheel import Item, LabeledItem
from decision_flywheel.batched_classification import BatchedAnswers
from decision_flywheel.models import DecisionResult

from features_backend.steps.cyclotron_relevance_sweep_steps import DOCTRINE, configure, reference
from papyrus_content.priming_proof import (PROOF_REPORT_VERSION, agreement_metrics, freeze_held_out_set,
                                           held_out_set_fingerprint, run_priming_proof, verify_held_out_set)
from papyrus_content.relevance_cyclotron import build_relevance_cyclotron

INCLUDED_TOPICS = ("prompt-injection", "model-theft", "jailbreak", "data-poisoning", "agent-hijack")
EXCLUDED_TOPICS = ("celebrity-gossip", "sports-score", "recipe", "travel-deal", "stock-tip")


class NearestTrainingExampleModel:
    """Answers with the label of a training example on the same topic, or include when none matches."""
    model_identity = "scripted-nearest-example"

    def __init__(self):
        self.training_sizes = []

    async def classify_many(self, configs, target, training, **kwargs):
        answers = {}
        for classifier_id in configs:
            examples = training.get(classifier_id, ())
            self.training_sizes.append(len(examples))
            topic = target.values["text"].split()[0]
            matching = [example.label for example in examples if example.item.values["text"].split()[0] == topic]
            label = matching[0] if matching else "include"
            answers[classifier_id] = {"decision": DecisionResult(label, {label: 0.9, ("exclude" if label == "include" else "include"): 0.1})}
        return BatchedAnswers(answers, "scripted", {"input_tokens": 1, "output_tokens": 0}, 1)


@pytest.fixture
def relevance_plan(tmp_path):
    context = SimpleNamespace(tmp=str(tmp_path))
    configure(context, tmp_path / "worker")
    return build_relevance_cyclotron(context.steering, DOCTRINE)


def reviewed_reference(topic, index, status):
    row = reference(f"{topic}-{index}", f"{topic} study {index}", status)
    return {**row, "title": f"{topic} study {index}"}


def reviewed_pairs(per_topic=2):
    pairs = []
    for index in range(per_topic):
        pairs += [(reviewed_reference(topic, index, "accepted"), "include") for topic in INCLUDED_TOPICS]
        pairs += [(reviewed_reference(topic, index, "rejected"), "exclude") for topic in EXCLUDED_TOPICS]
    return pairs


def priming_example(topic, label, identifier):
    return LabeledItem(Item(identifier, {"text": f"{topic} pasted source", "source_uri": f"https://example.org/pasted/{identifier}"}),
                       label)


def test_held_out_set_is_balanced_deterministic_and_tamper_evident(relevance_plan):
    first = freeze_held_out_set(reviewed_pairs(), plan=relevance_plan, proof_id="proof-a", size=10, frozen_at="2026-10-17T00:00:00Z")
    again = freeze_held_out_set(list(reversed(reviewed_pairs())), plan=relevance_plan, proof_id="proof-a", size=10, frozen_at="2026-10-17T00:00:00Z")
    other = freeze_held_out_set(reviewed_pairs(), plan=relevance_plan, proof_id="proof-b", size=10, frozen_at="2026-10-17T00:00:00Z")
    assert first == again
    assert [item["id"] for item in first["items"]] != [item["id"] for item in other["items"]]
    assert sorted(item["label"] for item in first["items"]) == ["exclude"] * 5 + ["include"] * 5
    verify_held_out_set(first)
    tampered = json.loads(json.dumps(first))
    tampered["items"][0]["label"] = "exclude" if tampered["items"][0]["label"] == "include" else "include"
    with pytest.raises(ValueError, match="changed after it was frozen"):
        verify_held_out_set(tampered)


def test_held_out_set_refuses_too_few_reviews_per_label(relevance_plan):
    only_includes = [pair for pair in reviewed_pairs() if pair[1] == "include"]
    with pytest.raises(ValueError, match="exclude: 0"):
        freeze_held_out_set(only_includes, plan=relevance_plan, proof_id="proof-a", size=10)


def test_agreement_metrics_count_the_positive_label():
    metrics = agreement_metrics([("include", "include"), ("include", "exclude"), ("exclude", "include"), ("exclude", "exclude")],
                                positive_label="include")
    assert metrics["agreement"] == 0.5 and metrics["precision"] == 0.5 and metrics["recall"] == 0.5
    assert agreement_metrics([("exclude", "exclude")], positive_label="include")["precision"] is None


def test_agreement_rises_with_labels_and_the_report_holds_no_item_text(relevance_plan):
    held_out_set = freeze_held_out_set(reviewed_pairs(), plan=relevance_plan, proof_id="proof-a", size=20)
    examples = [priming_example(topic, "exclude", f"pasted-{topic}") for topic in EXCLUDED_TOPICS]
    examples.insert(0, priming_example(INCLUDED_TOPICS[0], "include", "pasted-first-include"))
    model = NearestTrainingExampleModel()
    report = run_priming_proof(held_out_set, plan=relevance_plan, priming_examples=examples, model=model,
                               label_schedule=[0, 3, 6, 50], publication="Example")
    assert report["version"] == PROOF_REPORT_VERSION
    assert [point["labels"] for point in report["points"]] == [0, 3, 6]
    agreements = [point["agreement"] for point in report["points"]]
    assert agreements == [0.5, 0.7, 1.0]
    assert report["points"][2]["labelsByClass"] == {"include": 1, "exclude": 5}
    assert report["heldOut"] == {**report["heldOut"], "size": 20, "byLabel": {"include": 10, "exclude": 10}}
    assert set(model.training_sizes) == {0, 3, 6}
    serialized = json.dumps(report)
    assert "study" not in serialized and "example.org" not in serialized


def test_priming_examples_matching_the_held_out_set_are_excluded(relevance_plan):
    held_out_set = freeze_held_out_set(reviewed_pairs(), plan=relevance_plan, proof_id="proof-a", size=10)
    held_out_item = held_out_set["items"][0]
    same_identity = LabeledItem(Item(held_out_item["id"], {"text": "pasted again"}), held_out_item["label"])
    same_source = LabeledItem(Item("pasted-elsewhere", {"text": "pasted again", "source_uri": held_out_item["values"]["source_uri"]}),
                              held_out_item["label"])
    report = run_priming_proof(held_out_set, plan=relevance_plan, priming_examples=[same_identity, same_source],
                               model=NearestTrainingExampleModel(), label_schedule=[0, 1, 2], publication="Example")
    assert report["priming"]["excludedBecauseInHeldOut"] == 2
    assert [point["labels"] for point in report["points"]] == [0]


def test_a_held_out_set_for_another_definition_is_refused(relevance_plan):
    held_out_set = freeze_held_out_set(reviewed_pairs(), plan=relevance_plan, proof_id="proof-a", size=10)
    held_out_set["question"] = "Another question?"
    held_out_set["fingerprint"] = held_out_set_fingerprint(held_out_set)
    with pytest.raises(ValueError, match="different relevance cyclotron definition"):
        run_priming_proof(held_out_set, plan=relevance_plan, priming_examples=[], model=NearestTrainingExampleModel(),
                          publication="Example")
