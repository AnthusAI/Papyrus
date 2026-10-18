"""The Section proof: how often do the site cyclotron's classifiers agree with held-out human Section choices?

The labels are only the explicit Section choices people made when accepting
References, the same labels the site sweep teaches from. A Reference placed in
Section S is a positive for the fit classifier of S, a negative for the fit
classifier of every other Section, and the selector's answer is S. The negatives
are inferred from the assumption that a Reference belongs to a single Section.

Each classifier is proven on its own with cross-validation: every placed
Reference is held out exactly once, taught only by the placements outside its
own fold, and decided by the configured model with and without those placements
as training context. The folds are pooled. A classifier with too few labels gets
a "not yet provable" entry carrying the reason and no numbers, because a number
from two or three examples would look like evidence and be noise. The report
holds aggregate numbers only: no item text, no explanations and no reviewer names.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .priming_proof import (CROSS_VALIDATION_SET_VERSION, DEFAULT_FOLD_COUNT, _assembled_held_out_set,
                            _ranked_candidates_by_label, agreement_metrics, cross_validation_fingerprint,
                            run_priming_proof, teaching_examples_from_reviews, verify_cross_validation_set)
from .site_classifier_set import definition_with_classifiers
from .site_cyclotron import (SECTION_FIT_POSITIVE_LABEL, build_site_cyclotron, enabled_sections_in_order,
                             is_section_selector_classifier_id, section_fit_classifier_id)
from .site_sweep import SECTION_DOES_NOT_FIT_LABEL, _human_section_references, human_labels_for_section

SECTION_PROOF_SCHEMA = "cyclotron-section-proof/v1"
MINIMUM_POSITIVE_EXAMPLES_FOR_FIT_PROOF = 2
MINIMUM_NEGATIVE_EXAMPLES_FOR_FIT_PROOF = 2
MINIMUM_PLACED_REFERENCES_FOR_SELECTOR_PROOF = 10
MINIMUM_EXAMPLES_FOR_SECTION_RECALL = 2
SMALL_SAMPLE_POSITIVE_COUNT = 10
SMALL_SAMPLE_REFERENCE_COUNT = 30


def collect_human_placed_references(client, steering_config: Mapping[str, Any],
                                    enabled_section_ids: Sequence[str]) -> list[tuple[dict[str, Any], str]]:
    """Every current accepted Reference a person explicitly placed in an enabled Section, with that Section's id."""
    from .ids import knowledge_corpus_id
    from .steering import require_corpus_config

    corpus = require_corpus_config(dict(steering_config), steering_config["canonicalTopicSet"]["corpusKey"],
                                   "canonicalTopicSet.corpusKey")
    return [(reference, section_id) for reference, _messages, section_id
            in _human_section_references(client, knowledge_corpus_id(corpus), enabled_section_ids)]


def labeled_references_for_classifier(placed_references: Sequence[tuple[Mapping[str, Any], str]],
                                      classifier_id: str,
                                      enabled_section_ids: Sequence[str]) -> list[tuple[Mapping[str, Any], str]]:
    return [(reference, human_labels_for_section(section_id, enabled_section_ids)[classifier_id])
            for reference, section_id in placed_references]


def label_counts(labeled_references: Sequence[tuple[Any, str]], labels: Sequence[str]) -> dict[str, int]:
    return {label: sum(1 for _reference, candidate in labeled_references if candidate == label) for label in labels}


def why_the_selector_is_not_yet_provable(placed_reference_count: int, section_count: int) -> str | None:
    if section_count < 2:
        return "The site cyclotron has a Section selector only when at least two Sections are enabled."
    if placed_reference_count < MINIMUM_PLACED_REFERENCES_FOR_SELECTOR_PROOF:
        return (f"Only {placed_reference_count} References have been placed in a Section by a person; the selector "
                f"needs at least {MINIMUM_PLACED_REFERENCES_FOR_SELECTOR_PROOF}.")
    return None


def why_a_fit_classifier_is_not_yet_provable(counts: Mapping[str, int]) -> str | None:
    positives = counts[SECTION_FIT_POSITIVE_LABEL]
    negatives = counts[SECTION_DOES_NOT_FIT_LABEL]
    if positives < MINIMUM_POSITIVE_EXAMPLES_FOR_FIT_PROOF:
        return (f"Only {positives} References have been placed in this Section by a person; the fit classifier "
                f"needs at least {MINIMUM_POSITIVE_EXAMPLES_FOR_FIT_PROOF}.")
    if negatives < MINIMUM_NEGATIVE_EXAMPLES_FOR_FIT_PROOF:
        return (f"Only {negatives} References placed in other Sections are available as negatives; the fit "
                f"classifier needs at least {MINIMUM_NEGATIVE_EXAMPLES_FOR_FIT_PROOF}.")
    return None


def freeze_section_folds(labeled_references: Sequence[tuple[Mapping[str, Any], str]], *, plan, proof_id: str,
                         fold_count: int, frozen_at: str) -> dict[str, Any]:
    """Every labeled Reference held out exactly once; consecutive ranked References of a label go to different folds."""
    classifier = plan.definition.classifiers[0]
    candidates_by_label = _ranked_candidates_by_label(labeled_references, classifier, proof_id)
    fold_items: list[list[dict[str, Any]]] = [[] for _ in range(fold_count)]
    position = 0
    for label in classifier.labels:
        for item in candidates_by_label[label]:
            fold_items[position % fold_count].append(item)
            position += 1
    folds = [_assembled_held_out_set(plan=plan, proof_id=f"{proof_id}/fold-{fold_number}", held_out_items=held_items,
                                     teaching_items=[item for other_number, other_items in enumerate(fold_items)
                                                     if other_number != fold_number for item in other_items],
                                     frozen_at=frozen_at,
                                     selection=f"fold {fold_number + 1} of {fold_count}; sha256(proofId, lineageId) "
                                               "rank, dealt round-robin across labels")
             for fold_number, held_items in enumerate(fold_items) if held_items]
    cross_validation_set = {"version": CROSS_VALIDATION_SET_VERSION, "proofId": proof_id, "frozenAt": frozen_at,
                            "folds": folds}
    cross_validation_set["fingerprint"] = cross_validation_fingerprint(cross_validation_set)
    verify_cross_validation_set(cross_validation_set)
    return cross_validation_set


def plan_for_one_classifier(plan, classifier_id: str):
    specification = next(spec for spec in plan.definition.classifiers if spec.id == classifier_id)
    return replace(plan, definition=definition_with_classifiers(plan.definition, [specification]),
                   seed_rubrics={key: value for key, value in plan.seed_rubrics.items() if key == classifier_id})


def pooled_outcomes_without_and_with_teaching(cross_validation_set: Mapping[str, Any], *, classifier_plan, model,
                                              publication: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]] | None]:
    """The (human label, classifier label) pairs of every fold, decided with no teaching and with the other folds' labels."""
    without_teaching: list[tuple[str, str]] = []
    with_teaching: list[tuple[str, str]] = []
    every_fold_was_taught = True
    for fold in cross_validation_set["folds"]:
        teaching_examples = teaching_examples_from_reviews(fold)
        outcome_sink: list[tuple[int, list[tuple[str, str]]]] = []
        run_priming_proof(fold, plan=classifier_plan, priming_examples=teaching_examples, model=model,
                          label_schedule=[len(teaching_examples)], publication=publication, outcome_sink=outcome_sink)
        without_teaching.extend(outcome_sink[0][1])
        if len(outcome_sink) > 1:
            with_teaching.extend(outcome_sink[-1][1])
        else:
            every_fold_was_taught = False
    return without_teaching, (with_teaching if every_fold_was_taught else None)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def fit_classifier_metrics(outcomes: Sequence[tuple[str, str]]) -> dict[str, Any]:
    metrics = agreement_metrics(outcomes, positive_label=SECTION_FIT_POSITIVE_LABEL)
    precision, recall = metrics["precision"], metrics["recall"]
    metrics["f1"] = (round(2 * precision * recall / (precision + recall), 4)
                     if precision is not None and recall is not None and precision + recall else None)
    return metrics


def selector_metrics(outcomes: Sequence[tuple[str, str]], section_ids: Sequence[str]) -> dict[str, Any]:
    correct = sum(1 for human, suggested in outcomes if human == suggested)
    per_section = {}
    for section_id in section_ids:
        placed = [(human, suggested) for human, suggested in outcomes if human == section_id]
        found = sum(1 for human, suggested in placed if suggested == human)
        provable = len(placed) >= MINIMUM_EXAMPLES_FOR_SECTION_RECALL
        per_section[section_id] = {
            "humanPlaced": len(placed),
            "found": found if provable else None,
            "recall": _ratio(found, len(placed)) if provable else None,
            "status": "measured" if provable else "not-yet-provable",
        }
    return {"decided": len(outcomes), "correct": correct, "accuracy": _ratio(correct, len(outcomes)),
            "perSectionRecall": per_section}


def majority_answer_rate(labels: Sequence[str]) -> float | None:
    return _ratio(max((labels.count(label) for label in set(labels)), default=0), len(labels))


def sample_size_caveats_for_fit(counts: Mapping[str, int]) -> list[str]:
    positives = counts[SECTION_FIT_POSITIVE_LABEL]
    caveats = [f"Precision, recall and F1 rest on {positives} human-placed positive examples and "
               f"{counts[SECTION_DOES_NOT_FIT_LABEL]} inferred negatives; one more correct positive answer moves "
               f"recall by about {round(100 / positives, 1)} percentage points."]
    if positives < SMALL_SAMPLE_POSITIVE_COUNT:
        caveats.append(f"With fewer than {SMALL_SAMPLE_POSITIVE_COUNT} positives, treat these numbers as a rough "
                       "indication, not a measured accuracy.")
    return caveats


def sample_size_caveats_for_selector(placed_reference_count: int) -> list[str]:
    caveats = [f"Accuracy rests on {placed_reference_count} human-placed References; one more correct answer moves "
               f"it by about {round(100 / placed_reference_count, 1)} percentage points."]
    if placed_reference_count < SMALL_SAMPLE_REFERENCE_COUNT:
        caveats.append(f"With fewer than {SMALL_SAMPLE_REFERENCE_COUNT} placed References, treat accuracy as a rough "
                       "indication, not a measured accuracy.")
    return caveats


def classifier_report_skeleton(classifier_id: str, kind: str, section_id: str | None, counts: Mapping[str, int],
                               placed_reference_count: int) -> dict[str, Any]:
    return {"classifierId": classifier_id, "kind": kind, "sectionId": section_id,
            "labelCounts": dict(counts), "humanPlacedReferences": placed_reference_count}


def not_yet_provable_report(skeleton: dict[str, Any], reason: str) -> dict[str, Any]:
    return {**skeleton, "status": "not-yet-provable", "reason": reason}


def run_section_proof(placed_references: Sequence[tuple[Mapping[str, Any], str]], sections: Sequence[Mapping[str, Any]],
                      steering_config: Mapping[str, Any], *, model, proof_id: str, publication: str,
                      model_identity: str | None = None, fold_count: int = DEFAULT_FOLD_COUNT,
                      dry_run: bool = False, ran_at: str | None = None,
                      on_classifier: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Prove the selector and every fit classifier by cross-validation, or only report which are provable when dry_run."""
    ran_at = ran_at or _now()
    ordered_sections = enabled_sections_in_order(sections)
    enabled_section_ids = [str(section["id"]) for section in ordered_sections]
    plan = build_site_cyclotron(steering_config, sections)
    placed_by_section = {section_id: sum(1 for _reference, placed in placed_references if placed == section_id)
                         for section_id in enabled_section_ids}
    section_id_by_fit_classifier = {section_fit_classifier_id(identifier): identifier for identifier in enabled_section_ids}
    classifier_reports = []
    for specification in plan.definition.classifiers:
        is_selector = is_section_selector_classifier_id(specification.id)
        labeled = labeled_references_for_classifier(placed_references, specification.id, enabled_section_ids)
        counts = label_counts(labeled, specification.labels)
        section_id = None if is_selector else section_id_by_fit_classifier[specification.id]
        skeleton = classifier_report_skeleton(specification.id, "selector" if is_selector else "fit", section_id,
                                              counts, len(placed_references))
        reason = (why_the_selector_is_not_yet_provable(len(placed_references), len(enabled_section_ids))
                  if is_selector else why_a_fit_classifier_is_not_yet_provable(counts))
        if reason:
            classifier_report = not_yet_provable_report(skeleton, reason)
        elif dry_run:
            classifier_report = {**skeleton, "status": "provable", "reason": None}
        else:
            classifier_report = _proven_report(skeleton, is_selector, labeled, plan, specification, model, proof_id,
                                               publication, enabled_section_ids, fold_count, ran_at)
        classifier_reports.append(classifier_report)
        if on_classifier:
            on_classifier(classifier_report)
    selector_report = next((report for report in classifier_reports if report["kind"] == "selector"), None)
    return {
        "schema": SECTION_PROOF_SCHEMA,
        "proofId": proof_id,
        "publication": publication,
        "cyclotronId": plan.definition.id,
        "decisionModel": model_identity or getattr(model, "model_identity", None),
        "ranAt": ran_at,
        "dryRun": dry_run,
        "labels": {
            "source": "References a person explicitly accepted into a Section; agents, rejections and accepts "
                      "without a Section are never used",
            "humanPlacedReferences": len(placed_references),
            "bySection": placed_by_section,
            "assumption": "A Reference belongs to a single Section: placed in S, it fits S and does not fit any other "
                          "Section, so the fit classifiers' negatives are inferred rather than chosen by a person.",
        },
        "design": {
            "method": f"Up to {fold_count}-fold cross-validation per classifier: every human-placed Reference is held "
                      "out exactly once and taught only by placements outside its own fold; folds are pooled.",
            "conditions": {"freshStorePerFold": True, "rubric": "Section seed rubric", "optimizer": False,
                           "reviewProgram": False},
            "minimums": {"selectorPlacedReferences": MINIMUM_PLACED_REFERENCES_FOR_SELECTOR_PROOF,
                         "fitPositiveExamples": MINIMUM_POSITIVE_EXAMPLES_FOR_FIT_PROOF,
                         "fitNegativeExamples": MINIMUM_NEGATIVE_EXAMPLES_FOR_FIT_PROOF,
                         "sectionRecallExamples": MINIMUM_EXAMPLES_FOR_SECTION_RECALL},
        },
        "selector": selector_report,
        "fitClassifiers": [report for report in classifier_reports if report["kind"] == "fit"],
        "notYetProvable": [report["classifierId"] for report in classifier_reports
                           if report["status"] == "not-yet-provable"],
        "caveats": [
            "Every number is measured against what editors chose, not against an independent truth.",
            "Sections with few human placements are reported as not yet provable instead of as a number.",
            "Small samples give wide uncertainty; each classifier lists its own sample-size caveat.",
            "The report holds aggregate numbers only: no Reference text, notes or reviewer names.",
        ],
    }


def _proven_report(skeleton: dict[str, Any], is_selector: bool, labeled, plan, specification, model, proof_id: str,
                   publication: str, enabled_section_ids: Sequence[str], fold_count: int, ran_at: str) -> dict[str, Any]:
    classifier_plan = plan_for_one_classifier(plan, specification.id)
    effective_fold_count = max(2, min(fold_count, len(labeled) // 2))
    cross_validation_set = freeze_section_folds(labeled, plan=classifier_plan, proof_id=f"{proof_id}/{specification.id}",
                                                fold_count=effective_fold_count, frozen_at=ran_at)
    without_teaching, with_teaching = pooled_outcomes_without_and_with_teaching(
        cross_validation_set, classifier_plan=classifier_plan, model=model, publication=publication)
    human_labels = [human for human, _suggested in without_teaching]
    summarize = ((lambda outcomes: selector_metrics(outcomes, enabled_section_ids)) if is_selector
                 else fit_classifier_metrics)
    return {
        **skeleton,
        "status": "proven",
        "reason": None,
        "folds": len(cross_validation_set["folds"]),
        "heldOutFingerprint": cross_validation_set["fingerprint"],
        "majorityAnswerRate": majority_answer_rate(human_labels),
        "withoutTeaching": summarize(without_teaching),
        "withTeaching": summarize(with_teaching) if with_teaching is not None else None,
        "sampleSizeCaveats": (sample_size_caveats_for_selector(skeleton["humanPlacedReferences"]) if is_selector
                              else sample_size_caveats_for_fit(skeleton["labelCounts"])),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def references_prove_site_sections(flags: list[str]) -> None:
    """papyrus references prove-site-sections --proof-id <id> [--output <report.json>] [--folds 5] [--apply]
    [--config <steering.yml>] [--sections-file <newsroom-sections.yml>]

    Dry run by default: reads the human-placed References, prints the label
    counts and which classifiers are provable, and makes no model call.
    ``--apply`` calls the configured decision model (the key comes from the
    environment) and writes the aggregate report to ``--output``.
    """
    from .graphql_authoring import create_authoring_client
    from .newsroom_sections import load_newsroom_section_seeds
    from .options import parse_options
    from .relevance_cyclotron import decision_model_from_environment, decision_model_identity
    from .site_sweep import default_sections_path
    from .steering import require_steering_config

    options = parse_options(flags)
    apply = bool(options.get("apply"))
    if not isinstance(options.get("proof-id"), str) or (apply and not isinstance(options.get("output"), str)):
        raise ValueError("references prove-site-sections requires --proof-id <id>, and --output <report.json> with --apply.")
    config_path = options.get("config") if isinstance(options.get("config"), str) else None
    steering_config = require_steering_config(config_path)
    if not steering_config.get("siteCyclotron"):
        raise ValueError("This publication's steering config has no siteCyclotron block; see docs/cyclotron-priming.md.")
    sections_file = options.get("sections-file") if isinstance(options.get("sections-file"), str) \
        else default_sections_path(config_path)
    sections = load_newsroom_section_seeds(sections_file)
    fold_count = int(options["folds"]) if isinstance(options.get("folds"), str) else DEFAULT_FOLD_COUNT
    plan = build_site_cyclotron(steering_config, sections)
    client, _ = create_authoring_client()
    placed_references = collect_human_placed_references(
        client, steering_config, [str(section["id"]) for section in enabled_sections_in_order(sections)])

    def print_classifier(classifier_report: Mapping[str, Any]) -> None:
        print(f"references\tprove-site-sections\t{classifier_report['classifierId']}\t{classifier_report['status']}\t"
              f"labels\t{json.dumps(classifier_report['labelCounts'], sort_keys=True)}\t{classifier_report['reason'] or ''}")

    report = run_section_proof(placed_references, sections, steering_config,
                               model=decision_model_from_environment(plan) if apply else None,
                               proof_id=options["proof-id"], publication=steering_config["publication"]["name"],
                               model_identity=decision_model_identity(plan) if apply else None,
                               fold_count=fold_count, dry_run=not apply, on_classifier=print_classifier)
    if not apply:
        print(f"references\tprove-site-sections\tdry-run\tplaced\t{report['labels']['humanPlacedReferences']}")
        return
    Path(options["output"]).parent.mkdir(parents=True, exist_ok=True)
    Path(options["output"]).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"references\tprove-site-sections\t{options['output']}")
