"""The site sweep on a scripted model: a suggestion per classifier, human-only Section teaching, agreement, cap, off switch."""
import json
from unittest import mock

import pytest
import yaml

from features_backend.steps.cyclotron_relevance_sweep_steps import CORPUS_ID, LocalBucket, Model, SweepClient, reference
from papyrus_content.relevance_sweep import CyclotronClaimed
from papyrus_content.site_cyclotron import section_fit_classifier_id, section_selector_classifier_id
from papyrus_content.site_sweep import (current_site_decisions, run_decide_site_sections,
                                        site_sweep_assignment_id)
from papyrus_content.steering import load_steering_config

CYCLOTRON_ID = "papyrus-relevance-sections"
FIT_SECURITY = section_fit_classifier_id("security")
FIT_CLOUD = section_fit_classifier_id("cloud")
FIT_POLICY = section_fit_classifier_id("policy")
SELECTOR = section_selector_classifier_id(["security", "cloud"])
DOCTRINE = [{"kind": "mission", "body": ["Publish practical analysis."]}]


def section(section_id, order, enabled=True):
    return {"id": section_id, "title": section_id.title(), "shortTitle": section_id, "type": "canonical",
            "editorialMission": f"Mission of {section_id}", "editorialPolicy": f"Policy of {section_id}",
            "assignmentGuidance": None, "killCriteria": None, "enabled": enabled, "sortOrder": order}


SECTIONS = [section("security", 1), section("cloud", 2)]


class SectionModel(Model):
    """Answers each classifier from the words in the item: a Section's name fits that Section."""

    model_identity = "scripted-sections"

    async def classify_many(self, configs, target, training, **kwargs):
        from decision_flywheel.batched_classification import BatchedAnswers
        from decision_flywheel.models import DecisionResult

        self.calls += 1
        text = target.values["text"].lower()
        answers = {}
        for classifier, config in configs.items():
            labels = list(config.task.labels)
            if "fits" in labels:
                fits = classifier.removeprefix("section-fit-") in text
                label, weights = ("fits" if fits else "does-not-fit"), {"fits": 0.9 if fits else 0.2}
                weights["does-not-fit"] = 1 - weights["fits"]
            else:
                label = next((candidate for candidate in labels if candidate in text), labels[0])
                weights = {candidate: (0.8 if candidate == label else 0.2 / (len(labels) - 1)) for candidate in labels}
            answers[classifier] = {"decision": DecisionResult(label, weights)}
        return BatchedAnswers(answers, "scripted", {"input_tokens": 1000, "output_tokens": 0}, 1)


def prepared(tmp_path, site_overrides=None):
    raw = {
        "schemaVersion": 1, "publication": {"name": "Example"},
        "canonicalTopicSet": {"corpusKey": "example", "classifierId": "example"},
        "corpora": [{"key": "example", "name": "example", "path": "corpora/example", "role": "canonical"}],
        "relevanceCyclotron": {"optimizer": None},
        "siteCyclotron": {"store": {"localPath": str(tmp_path / "site-cyclotron"),
                                    "s3Prefix": "s3://example-private-media/cyclotrons/papyrus-sections/"},
                          **(site_overrides or {})},
    }
    path = tmp_path / "steering.yml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_steering_config(str(path))


def references():
    return [reference("reference-a", "A security advisory for model servers", "pending"),
            reference("reference-bb", "A cloud migration notice", "pending")]


def sweep(steering, client, tmp_path, *, model=None, sections=SECTIONS, apply=True, now="2026-10-18T10:00:00Z", **options):
    client._table('NewsroomSection').update({row['id']: dict(row) for row in sections})
    bodies = client.bodies

    def store_body(recording_client, attachment, body):
        recording_client.upsert("ModelAttachment", attachment)
        bodies[attachment["id"]] = body

    with mock.patch("papyrus_content.site_sweep.knowledge_corpus_id", return_value=CORPUS_ID), \
            mock.patch("papyrus_content.records.upload_attachment_body", side_effect=store_body), \
            mock.patch("papyrus_content.assignments.upload_attachment_body", side_effect=store_body), \
            mock.patch("papyrus_content.relevance_sweep.download_attachment_buffer",
                       side_effect=lambda recording_client, attachment: bodies.get(attachment["id"])):
        return run_decide_site_sections(client, steering, DOCTRINE, sections, apply=apply, worker="worker-a",
                                        model=model or SectionModel(), snapshots=LocalBucket(tmp_path / "bucket"),
                                        now=lambda: now, **options)


def curate_into_section(client, item, *, section_id, actor_kind, status="accepted", at="2999-01-01T00:00:00Z"):
    client.tables["Reference"][item["id"]].update({
        "curationStatus": status, "curationStatusKey": f"{CORPUS_ID}#{status}", "curationStatusReason": "Fits well."})
    message_id = f"message-reference-curation-{item['lineageId']}-{status}"
    metadata = {"action": "accept", "actorKind": actor_kind, **({"sectionId": section_id} if section_id else {})}
    client.upsert("Message", {"id": message_id, "messageKind": "reference_curation", "authorLabel": "someone",
                              "createdAt": at, "metadata": json.dumps(metadata)})
    client.upsert("SemanticRelation", {
        "id": f"relation-{message_id}", "relationState": "current", "predicate": "comment", "subjectKind": "message",
        "subjectId": message_id, "objectKind": "reference", "objectLineageId": item["lineageId"],
        "objectStateKey": f"reference#{item['lineageId']}#current", "subjectStateKey": f"message#{message_id}#current"})


def site_relations(client, lineage_id):
    return [relation for relation in client.list_records("SemanticRelation")
            if relation.get("predicate") == "site_decision_is" and relation.get("subjectLineageId") == lineage_id]


def taught(steering):
    from decision_flywheel import Cyclotron
    from papyrus_content.site_cyclotron import build_site_cyclotron

    plan = build_site_cyclotron(steering, SECTIONS)
    with Cyclotron.open(plan.local_path, plan.definition, SectionModel(), review_program=plan.review_program) as cyclotron:
        return {(row["item"].id, row["classifier"]): row["label"] for row in cyclotron.labels()}, \
            [addition["examples"] for addition in cyclotron.priming_additions()]


def test_one_decision_yields_a_current_suggestion_for_every_classifier_and_the_selector(tmp_path):
    steering = prepared(tmp_path)
    first, second = references()
    client = SweepClient({"Reference": [first, second]})
    model = SectionModel()
    result = sweep(steering, client, tmp_path, model=model)
    assert result.decided == 2 and model.calls == 2
    decisions = current_site_decisions(site_relations(client, "reference-a"), "reference-a")
    assert set(decisions) == {FIT_SECURITY, FIT_CLOUD, SELECTOR}
    labels = {classifier: json.loads(relation["metadata"])["label"] for classifier, relation in decisions.items()}
    assert labels == {FIT_SECURITY: "fits", FIT_CLOUD: "does-not-fit", SELECTOR: "security"}
    selector = decisions[SELECTOR]
    assert selector["classifierId"] == f"{CYCLOTRON_ID}/{SELECTOR}" and selector["predicate"] == "site_decision_is"
    metadata = json.loads(selector["metadata"])
    assert metadata["decisionId"] and metadata["probabilities"]["security"] == 0.8 and metadata["version"] is not None
    assert metadata["provenance"]["doctrineFingerprint"]
    assert len({json.loads(relation["metadata"])["decisionId"] for relation in decisions.values()}) == 1


def test_suggestions_never_change_curation_status(tmp_path):
    steering = prepared(tmp_path)
    items = references()
    client = SweepClient({"Reference": items})
    sweep(steering, client, tmp_path)
    for item in items:
        assert client.get_record("Reference", item["id"])["curationStatus"] == "pending"


def test_dry_run_lists_pending_references_without_a_model_call(tmp_path):
    steering = prepared(tmp_path)
    client = SweepClient({"Reference": references()})
    model = SectionModel()
    result = sweep(steering, client, tmp_path, model=model, apply=False)
    assert sorted(result.pending) == ["reference-a", "reference-bb"] and model.calls == 0


def test_only_an_explicit_human_section_choice_teaches_every_classifier(tmp_path):
    steering = prepared(tmp_path)
    human_item, agent_item = references()
    client = SweepClient({"Reference": [human_item, agent_item]})
    sweep(steering, client, tmp_path)
    curate_into_section(client, human_item, section_id="security", actor_kind="human")
    curate_into_section(client, agent_item, section_id="cloud", actor_kind="agent")
    result = sweep(steering, client, tmp_path)
    labels, _ = taught(steering)
    assert result.reviews == 1
    assert labels == {("reference-a", FIT_SECURITY): "fits", ("reference-a", FIT_CLOUD): "does-not-fit",
                      ("reference-a", SELECTOR): "security"}


def test_a_human_accept_without_a_section_or_with_an_unknown_actor_never_teaches(tmp_path):
    steering = prepared(tmp_path)
    no_section, unknown_actor = references()
    client = SweepClient({"Reference": [no_section, unknown_actor]})
    sweep(steering, client, tmp_path)
    curate_into_section(client, no_section, section_id=None, actor_kind="human")
    curate_into_section(client, unknown_actor, section_id="cloud", actor_kind=None)
    sweep(steering, client, tmp_path)
    assert taught(steering) == ({}, [])


def test_a_reference_nobody_decided_teaches_as_priming_from_a_human_section(tmp_path):
    steering = prepared(tmp_path)
    undecided = reference("reference-old", "An older cloud article", "accepted")
    client = SweepClient({"Reference": [undecided]})
    curate_into_section(client, undecided, section_id="cloud", actor_kind="human")
    result = sweep(steering, client, tmp_path)
    _, additions = taught(steering)
    assert result.primed_from_human_reviews == 1
    assert additions and set(additions[0]) == {FIT_SECURITY, FIT_CLOUD, SELECTOR}
    assert sweep(steering, client, tmp_path).primed_from_human_reviews == 0
    assert len(taught(steering)[1]) == 1


def test_shadow_agreement_is_counted_per_classifier_for_honest_human_comparisons_only(tmp_path):
    steering = prepared(tmp_path)
    right, wrong = references()
    early = reference("reference-early", "A security note reviewed before any suggestion", "pending")
    client = SweepClient({"Reference": [right, wrong, early]})
    sweep(steering, client, tmp_path)
    curate_into_section(client, right, section_id="security", actor_kind="human")
    curate_into_section(client, wrong, section_id="security", actor_kind="human")
    curate_into_section(client, early, section_id="security", actor_kind="human", at="2000-01-01T00:00:00Z")
    agreement = sweep(steering, client, tmp_path).live_agreement
    assert agreement["schema"] == "cyclotron-shadow-agreement/v1"
    selector = agreement["classifiers"][SELECTOR]
    assert (selector["comparisons"], selector["correct"], selector["agreement"]) == (2, 1, 0.5)
    assert agreement["selectorAccuracy"] == 0.5
    security = agreement["classifiers"][FIT_SECURITY]
    assert security["comparisons"] == 2 and security["confusion"]["truePositives"] == 1
    assert security["confusion"]["falseNegatives"] == 1
    cloud = agreement["classifiers"][FIT_CLOUD]
    assert cloud["comparisons"] == 2 and cloud["confusion"]["trueNegatives"] == 1 and cloud["confusion"]["falsePositives"] == 1
    payload = client.get_record("KnowledgeRawPayload", f"knowledge-raw-payload-cyclotron-shadow-agreement-{CYCLOTRON_ID}")
    assert payload is not None


def test_the_daily_cap_counts_a_reference_once_and_the_off_switch_decides_nothing(tmp_path):
    (tmp_path / "capped").mkdir()
    capped = prepared(tmp_path / "capped", {"maxDecisionsPerDay": 1})
    client = SweepClient({"Reference": references()})
    first = sweep(capped, client, tmp_path / "capped")
    assert first.decided == 1 and first.stopped_because == "daily decision cap"
    assert sweep(capped, client, tmp_path / "capped").decided == 0
    (tmp_path / "off").mkdir()
    switched_off = prepared(tmp_path / "off", {"enabled": False})
    model = SectionModel()
    result = sweep(switched_off, SweepClient({"Reference": references()}), tmp_path / "off", model=model)
    assert result.decided == 0 and result.stopped_because == "disabled" and model.calls == 0


def test_a_second_sweep_changes_nothing(tmp_path):
    steering = prepared(tmp_path)
    client = SweepClient({"Reference": references()})
    model = SectionModel()
    sweep(steering, client, tmp_path, model=model)
    before = [dict(row) for row in client.list_records("SemanticRelation")]
    second = sweep(steering, client, tmp_path, model=model)
    assert second.decided == 0 and model.calls == 2
    assert [dict(row) for row in client.list_records("SemanticRelation")] == before
    assert client.get_record("Assignment", site_sweep_assignment_id(CYCLOTRON_ID))["status"] == "open"


def human_placed_security_reference(client, tmp_path, steering):
    item = reference("reference-human", "A security review by an editor", "pending")
    client.upsert("Reference", item)
    curate_into_section(client, item, section_id="security", actor_kind="human")


def retired_and_labels(steering, active_sections):
    from decision_flywheel import Cyclotron
    from papyrus_content.site_classifier_set import definition_with_classifiers, stored_active_specs
    from papyrus_content.site_cyclotron import build_site_cyclotron

    plan = build_site_cyclotron(steering, active_sections)
    definition = definition_with_classifiers(plan.definition, stored_active_specs(plan.local_path))
    with Cyclotron.open(plan.local_path, definition, SectionModel(), review_program=plan.review_program) as cyclotron:
        return cyclotron.retired_classifiers(), {(row["item"].id, row["classifier"]) for row in cyclotron.labels(include_retired=True)}


def test_a_new_section_gets_a_classifier_and_a_new_selector_and_learns_from_earlier_human_choices(tmp_path):
    steering = prepared(tmp_path)
    client = SweepClient({"Reference": references()})
    sweep(steering, client, tmp_path)
    human_placed_security_reference(client, tmp_path, steering)
    with_policy = [*SECTIONS, section("policy", 3)]
    result = sweep(steering, client, tmp_path, sections=with_policy, now="2026-10-18T11:00:00Z")
    new_selector = section_selector_classifier_id(["security", "cloud", "policy"])
    assert result.classifier_set["added"] == [FIT_POLICY, new_selector]
    assert result.classifier_set["retired"] == [SELECTOR]
    assert active_classifiers_of(steering, with_policy) == {FIT_SECURITY, FIT_CLOUD, FIT_POLICY, new_selector}
    retired, labels = retired_and_labels(steering, with_policy)
    assert retired == [SELECTOR]
    assert result.primed_from_human_reviews >= 1
    assert primed_classifiers(steering, with_policy) >= {FIT_POLICY, new_selector}


def primed_classifiers(steering, sections):
    from decision_flywheel import Cyclotron
    from papyrus_content.site_classifier_set import definition_with_classifiers, stored_active_specs
    from papyrus_content.site_cyclotron import build_site_cyclotron

    plan = build_site_cyclotron(steering, sections)
    definition = definition_with_classifiers(plan.definition, stored_active_specs(plan.local_path))
    with Cyclotron.open(plan.local_path, definition, SectionModel(), review_program=plan.review_program) as cyclotron:
        return {classifier for addition in cyclotron.priming_additions() for classifier in addition["examples"]}


def active_classifiers_of(steering, sections):
    from papyrus_content.site_classifier_set import stored_active_specs
    from papyrus_content.site_cyclotron import build_site_cyclotron

    return {spec.id for spec in stored_active_specs(build_site_cyclotron(steering, sections).local_path)}


def test_a_disabled_section_has_its_classifier_retired_and_keeps_its_labels(tmp_path):
    steering = prepared(tmp_path)
    client = SweepClient({"Reference": references()})
    human_placed_security_reference(client, tmp_path, steering)
    sweep(steering, client, tmp_path)
    only_security = [section("security", 1), section("cloud", 2, enabled=False)]
    result = sweep(steering, client, tmp_path, sections=only_security, now="2026-10-18T11:00:00Z")
    assert sorted(result.classifier_set["retired"]) == sorted([FIT_CLOUD, SELECTOR])
    assert active_classifiers_of(steering, only_security) == {FIT_SECURITY}
    retired, _ = retired_and_labels(steering, only_security)
    assert set(retired) == {FIT_CLOUD, SELECTOR}


def test_enabling_a_section_again_brings_back_its_classifier_with_its_history(tmp_path):
    steering = prepared(tmp_path)
    client = SweepClient({"Reference": references()})
    human_placed_security_reference(client, tmp_path, steering)
    sweep(steering, client, tmp_path)
    sweep(steering, client, tmp_path, sections=[section("security", 1), section("cloud", 2, enabled=False)])
    result = sweep(steering, client, tmp_path, now="2026-10-18T12:00:00Z")
    assert set(result.classifier_set["added"]) == {FIT_CLOUD, SELECTOR}
    assert active_classifiers_of(steering, SECTIONS) == {FIT_SECURITY, FIT_CLOUD, SELECTOR}
    retired, _ = retired_and_labels(steering, SECTIONS)
    assert retired == []


def test_a_dry_run_reports_what_a_section_change_would_do_and_changes_nothing(tmp_path):
    steering = prepared(tmp_path)
    client = SweepClient({"Reference": references()})
    sweep(steering, client, tmp_path)
    result = sweep(steering, client, tmp_path, sections=[*SECTIONS, section("policy", 3)], apply=False)
    assert result.classifier_set["added"] and any("Section policy" in warning for warning in result.warnings)
    assert active_classifiers_of(steering, SECTIONS) == {FIT_SECURITY, FIT_CLOUD, SELECTOR}


def test_an_unchanged_section_list_changes_no_classifiers(tmp_path):
    steering = prepared(tmp_path)
    client = SweepClient({"Reference": references()})
    sweep(steering, client, tmp_path)
    result = sweep(steering, client, tmp_path, now="2026-10-18T11:00:00Z")
    assert result.classifier_set == {"added": [], "retired": [], "kept": [FIT_SECURITY, FIT_CLOUD, SELECTOR]}


def test_a_claimed_site_cyclotron_refuses_a_second_worker(tmp_path):
    steering = prepared(tmp_path)
    client = SweepClient({"Reference": references()})
    sweep(steering, client, tmp_path)
    client.tables["Assignment"][site_sweep_assignment_id(CYCLOTRON_ID)].update(
        {"status": "claimed", "assigneeKey": "worker-b", "claimExpiresAt": "2999-01-01T00:00:00Z"})
    with pytest.raises(CyclotronClaimed):
        sweep(steering, client, tmp_path)


def test_a_retired_classifiers_suggestion_stops_being_current_when_the_reference_is_decided_again(tmp_path):
    steering = prepared(tmp_path)
    client = SweepClient({"Reference": references()})
    sweep(steering, client, tmp_path)
    sweep(steering, client, tmp_path, sections=[*SECTIONS, section("policy", 3)], now="2026-10-18T11:00:00Z")
    new_selector = section_selector_classifier_id(["security", "cloud", "policy"])
    current = [relation for relation in site_relations(client, "reference-a") if relation["relationState"] == "current"]
    assert {json.loads(relation["metadata"])["classifier"] for relation in current} == {
        FIT_SECURITY, FIT_CLOUD, FIT_POLICY, new_selector}
