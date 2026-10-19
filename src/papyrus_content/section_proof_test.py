"""The Section proof on synthetic References and the scripted Section model: method, not editorial quality."""
import json
from unittest import mock

import pytest

from features_backend.steps.cyclotron_relevance_sweep_steps import CORPUS_ID, SweepClient, reference
from papyrus_content.section_proof import (SECTION_PROOF_SCHEMA, collect_human_placed_references, run_section_proof)
from papyrus_content.site_cyclotron import section_fit_classifier_id
from papyrus_content.site_sweep_test import SectionModel, curate_into_section, prepared, section

SECTIONS = [section("security", 1), section("cloud", 2), section("policy", 3)]
SECTION_IDS = ["security", "cloud", "policy"]


def build_client(security_titles, cloud_titles, *, agent_placed=0, unplaced=0):
    rows = []
    placements = []
    for index, title in enumerate(security_titles):
        rows.append(reference(f"sec-{index}", title, "pending"))
        placements.append((f"sec-{index}", "security", "human"))
    for index, title in enumerate(cloud_titles):
        rows.append(reference(f"clo-{index}", title, "pending"))
        placements.append((f"clo-{index}", "cloud", "human"))
    for index in range(agent_placed):
        rows.append(reference(f"bot-{index}", f"cloud agent pick {index}", "pending"))
        placements.append((f"bot-{index}", "cloud", "agent"))
    for index in range(unplaced):
        rows.append(reference(f"nop-{index}", f"security without a section {index}", "pending"))
        placements.append((f"nop-{index}", None, "human"))
    client = SweepClient({"Reference": rows})
    for lineage, section_id, actor_kind in placements:
        curate_into_section(client, {"id": f"{lineage}-v1", "lineageId": lineage}, section_id=section_id,
                            actor_kind=actor_kind)
    return client


def eleven_placements_client():
    security_titles = [f"security advisory {index}" for index in range(5)] + ["cloud and security hybrid advisory"]
    cloud_titles = [f"cloud notice {index}" for index in range(5)]
    return build_client(security_titles, cloud_titles, agent_placed=2, unplaced=2)


def placed(client, steering):
    with mock.patch("papyrus_content.ids.knowledge_corpus_id", return_value=CORPUS_ID):
        return collect_human_placed_references(client, steering, SECTION_IDS)


def prove(client, steering, model=None, **options):
    model = model or SectionModel()
    report = run_section_proof(placed(client, steering), SECTIONS, steering, model=model, proof_id="proof-a",
                               publication="Example", ran_at="2026-10-18T10:00:00Z", **options)
    return report, model


def test_only_explicit_human_section_choices_are_collected(tmp_path):
    steering = prepared(tmp_path)
    collected = placed(eleven_placements_client(), steering)
    assert len(collected) == 11
    assert sorted(section_id for _reference, section_id in collected) == ["cloud"] * 5 + ["security"] * 6


def test_the_selector_reports_accuracy_and_per_section_recall(tmp_path):
    report, _model = prove(eleven_placements_client(), prepared(tmp_path))
    assert report["schema"] == SECTION_PROOF_SCHEMA == "cyclotron-section-proof/v1"
    selector = report["selector"]
    assert selector["status"] == "proven" and selector["humanPlacedReferences"] == 11
    taught = selector["withTeaching"]
    assert taught["decided"] == 11 and taught["correct"] == 10 and taught["accuracy"] == 0.9091
    assert taught["perSectionRecall"]["security"] == {"humanPlaced": 6, "found": 5, "recall": 0.8333, "status": "measured"}
    assert taught["perSectionRecall"]["cloud"]["recall"] == 1.0
    assert taught["perSectionRecall"]["policy"] == {"humanPlaced": 0, "found": None, "recall": None,
                                                    "status": "not-yet-provable"}
    assert selector["withoutTeaching"]["decided"] == 11
    assert selector["majorityAnswerRate"] == 0.5455


def test_each_fit_classifier_reports_precision_recall_and_f1(tmp_path):
    report, _model = prove(eleven_placements_client(), prepared(tmp_path))
    by_section = {entry["sectionId"]: entry for entry in report["fitClassifiers"]}
    security = by_section["security"]["withTeaching"]
    assert (security["precision"], security["recall"], security["f1"]) == (1.0, 1.0, 1.0)
    cloud = by_section["cloud"]["withTeaching"]
    assert (cloud["precision"], cloud["recall"], cloud["f1"]) == (0.8333, 1.0, 0.9091)
    assert by_section["cloud"]["labelCounts"] == {"fits": 5, "does-not-fit": 6}
    assert by_section["cloud"]["classifierId"] == section_fit_classifier_id("cloud")


def test_a_section_with_too_few_labels_is_not_yet_provable_and_has_no_numbers(tmp_path):
    report, _model = prove(eleven_placements_client(), prepared(tmp_path))
    policy = next(entry for entry in report["fitClassifiers"] if entry["sectionId"] == "policy")
    assert policy["status"] == "not-yet-provable" and "needs at least 2" in policy["reason"]
    assert "withTeaching" not in policy and "withoutTeaching" not in policy
    assert report["notYetProvable"] == [section_fit_classifier_id("policy")]


def test_one_positive_example_is_not_enough_for_a_fit_classifier(tmp_path):
    client = build_client([f"security advisory {index}" for index in range(6)], ["cloud notice 0"] + [])
    report, _model = prove(client, prepared(tmp_path))
    cloud = next(entry for entry in report["fitClassifiers"] if entry["sectionId"] == "cloud")
    assert cloud["status"] == "not-yet-provable" and cloud["labelCounts"]["fits"] == 1


def test_the_selector_needs_ten_human_placed_references(tmp_path):
    client = build_client([f"security advisory {index}" for index in range(5)], [f"cloud notice {index}" for index in range(4)])
    report, model = prove(client, prepared(tmp_path))
    assert report["selector"]["status"] == "not-yet-provable"
    assert "at least 10" in report["selector"]["reason"] and "accuracy" not in json.dumps(report["selector"])
    assert report["labels"]["humanPlacedReferences"] == 9


def test_a_dry_run_lists_what_is_provable_without_calling_the_model(tmp_path):
    report, model = prove(eleven_placements_client(), prepared(tmp_path), dry_run=True)
    assert model.calls == 0 and report["dryRun"] is True
    assert report["selector"]["status"] == "provable" and "withTeaching" not in report["selector"]
    assert [entry["status"] for entry in report["fitClassifiers"]] == ["provable", "provable", "not-yet-provable"]


def test_the_report_states_sample_size_caveats_and_holds_no_reference_text(tmp_path):
    report, model = prove(eleven_placements_client(), prepared(tmp_path))
    assert model.calls > 0
    assert any("rough indication" in caveat for caveat in report["selector"]["sampleSizeCaveats"])
    assert any("5 human-placed positive examples" in caveat for caveat in report["fitClassifiers"][1]["sampleSizeCaveats"])
    assert "single Section" in report["labels"]["assumption"]
    serialized = json.dumps(report)
    assert "advisory" not in serialized and "notice" not in serialized and "example.org" not in serialized


def test_every_placed_reference_is_held_out_exactly_once_per_classifier(tmp_path):
    report, _model = prove(eleven_placements_client(), prepared(tmp_path))
    assert report["selector"]["folds"] == 5
    for entry in [report["selector"], *[item for item in report["fitClassifiers"] if item["status"] == "proven"]]:
        assert entry["withoutTeaching"]["decided"] == 11
