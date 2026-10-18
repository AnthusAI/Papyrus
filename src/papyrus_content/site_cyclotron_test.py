import pytest

from papyrus_content.relevance_cyclotron import normalize_relevance_cyclotron_config
from papyrus_content.site_cyclotron import (build_site_cyclotron, section_selector_classifier_id, normalize_site_cyclotron_config,
                                            section_fit_classifier_id)

RELEVANCE_BLOCK = normalize_relevance_cyclotron_config({
    "cyclotronId": "ti-relevance", "decisionModel": {"provider": "jev", "model": "jev-1.13.0"}})


def section(section_id, *, order, enabled=True):
    return {"id": section_id, "title": section_id.title(), "shortTitle": "short", "type": "canonical",
            "editorialMission": f"Mission of {section_id}", "editorialPolicy": f"Policy of {section_id}",
            "assignmentGuidance": None, "killCriteria": f"Reject filler for {section_id}", "enabled": enabled,
            "sortOrder": order}


def steering(site_overrides=None):
    return {"relevanceCyclotron": RELEVANCE_BLOCK,
            "siteCyclotron": normalize_site_cyclotron_config(site_overrides or {}, RELEVANCE_BLOCK)}


def test_the_site_cyclotron_has_a_fit_classifier_per_enabled_section_and_one_selector():
    sections = [section("cloud", order=2), section("mission", order=1), section("retired", order=3, enabled=False)]
    plan = build_site_cyclotron(steering(), sections)
    ids = [spec.id for spec in plan.definition.classifiers]
    assert ids == [section_fit_classifier_id("mission"), section_fit_classifier_id("cloud"), section_selector_classifier_id(["mission", "cloud"])]
    selector = plan.definition.classifiers[-1]
    assert selector.labels == ("cloud", "mission")
    assert selector.positive_label is None
    assert plan.definition.classifiers[0].positive_label == "fits"


def test_each_classifier_is_seeded_from_the_section_curation_text():
    plan = build_site_cyclotron(steering(), [section("cloud", order=1), section("mission", order=2)])
    assert "Mission of cloud" in plan.seed_rubrics[section_fit_classifier_id("cloud")]
    assert "Reject when: Reject filler for cloud" in plan.seed_rubrics[section_fit_classifier_id("cloud")]
    assert "- mission: Mission. Mission of mission" in plan.seed_rubrics[section_selector_classifier_id(["mission", "cloud"])]


def test_a_single_enabled_section_has_a_fit_classifier_and_no_selector():
    plan = build_site_cyclotron(steering(), [section("mission", order=1)])
    assert [spec.id for spec in plan.definition.classifiers] == [section_fit_classifier_id("mission")]
    assert section_selector_classifier_id(["mission", "cloud"]) not in plan.seed_rubrics


def test_adding_or_disabling_a_section_changes_the_definition_fingerprint():
    before = build_site_cyclotron(steering(), [section("a", order=1), section("b", order=2)])
    added = build_site_cyclotron(steering(), [section("a", order=1), section("b", order=2), section("c", order=3)])
    disabled = build_site_cyclotron(steering(), [section("a", order=1), section("b", order=2, enabled=False)])
    assert len({before.definition.fingerprint, added.definition.fingerprint, disabled.definition.fingerprint}) == 3


def test_no_enabled_section_is_refused():
    with pytest.raises(ValueError, match="at least one enabled Section"):
        build_site_cyclotron(steering(), [section("a", order=1, enabled=False)])


def test_the_site_block_reuses_the_relevance_model_and_review_program_and_its_own_controls():
    plan = build_site_cyclotron(steering({"enabled": False, "maxDecisionsPerDay": 40}), [section("a", order=1)])
    assert plan.decision_model == RELEVANCE_BLOCK["decisionModel"]
    assert plan.definition.id == "ti-relevance-sections"
    assert (plan.enabled, plan.max_decisions_per_day) == (False, 40)


def test_the_site_block_needs_the_relevance_block_and_a_distinct_id_and_no_secrets():
    with pytest.raises(ValueError, match="needs a relevanceCyclotron block"):
        normalize_site_cyclotron_config({}, None)
    with pytest.raises(ValueError, match="must differ"):
        normalize_site_cyclotron_config({"cyclotronId": "ti-relevance"}, RELEVANCE_BLOCK)
    with pytest.raises(ValueError, match="credential"):
        normalize_site_cyclotron_config({"store": {"apiKey": "x"}}, RELEVANCE_BLOCK)
    assert normalize_site_cyclotron_config(None, RELEVANCE_BLOCK) is None
