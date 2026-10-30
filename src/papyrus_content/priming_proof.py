"""The priming proof: does the relevance classifier agree with editors more after N labels?

A proof has two fixed parts and one variable:

- The held-out set is a frozen, fingerprinted sample of References that editors
  already reviewed, labeled by the existing scope-training rule. It is balanced
  across the two labels, so a classifier that always answers one label scores
  50% agreement. It is frozen once per proof id and never regenerated.
- The conditions are fixed: the configured decision model, the publication
  doctrine as the only rubric, no optimizer and no review program.
- The variable is N, the number of editor labels the classifier sees as
  training context. Labels come from the teaching pool (the reviewed References
  not in the held-out set, in review order), from accepted priming examples
  (pasted URLs an editor labeled, in acceptance order), or from both, reviews
  first.

Each point of the curve opens a fresh store with only the first N examples and
decides every held-out item once. The report holds aggregate numbers only: no
item text, no explanations and no reviewer names, so an approved report can be
shown to visitors.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

HELD_OUT_SET_VERSION = "papyrus-priming-held-out/v1"
CROSS_VALIDATION_SET_VERSION = "papyrus-priming-cross-validation/v1"
DEFAULT_FOLD_COUNT = 5
DEFAULT_CROSS_VALIDATION_SCHEDULE = (0, 5, 10)
PROOF_REPORT_VERSION = "cyclotron-priming-proof/v1"
DEFAULT_HELD_OUT_SIZE = 40
MINIMUM_HELD_OUT_ITEMS_PER_LABEL = 5
DEFAULT_LABEL_SCHEDULE = (0, 5, 10, 20, 40)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def held_out_selection_rank(proof_id: str, lineage_id: str) -> str:
    return hashlib.sha256(f"{proof_id}\n{lineage_id}".encode()).hexdigest()


def held_out_set_fingerprint(held_out_set: Mapping[str, Any]) -> str:
    fingerprinted_fields = {key: held_out_set[key] for key in
                            ("version", "proofId", "cyclotronId", "classifierId", "question", "labels",
                             "positiveLabel", "items", "teachingPool")}
    return hashlib.sha256(canonical_json(fingerprinted_fields).encode()).hexdigest()


def verify_held_out_set(held_out_set: Mapping[str, Any]) -> None:
    if held_out_set.get("version") != HELD_OUT_SET_VERSION:
        raise ValueError(f"The held-out set must be {HELD_OUT_SET_VERSION}.")
    if held_out_set_fingerprint(held_out_set) != held_out_set.get("fingerprint"):
        raise ValueError("The held-out set changed after it was frozen; freeze a new set under a new proof id.")


def freeze_held_out_set(reviewed_references_with_labels: Sequence[tuple[Mapping[str, Any], str]], *, plan,
                        proof_id: str, size: int = DEFAULT_HELD_OUT_SIZE,
                        frozen_at: str | None = None) -> dict[str, Any]:
    """A balanced, deterministic held-out set and the teaching pool of every other labeled review."""
    classifier = plan.definition.classifiers[0]
    if size < 2 * MINIMUM_HELD_OUT_ITEMS_PER_LABEL or size % 2:
        raise ValueError(f"The held-out size must be an even number of at least {2 * MINIMUM_HELD_OUT_ITEMS_PER_LABEL}.")
    items_per_label = size // 2
    candidates_by_label = _ranked_candidates_by_label(reviewed_references_with_labels, classifier, proof_id)
    shortfalls = {label: len(candidates) for label, candidates in candidates_by_label.items()
                  if len(candidates) < items_per_label}
    if shortfalls:
        counts = ", ".join(f"{label}: {count}" for label, count in shortfalls.items())
        raise ValueError(f"A held-out set of {size} needs {items_per_label} reviewed references per label; "
                         f"only {counts} are available. Review more references or choose a smaller --size.")
    selected_items = [item for label in classifier.labels for item in candidates_by_label[label][:items_per_label]]
    teaching_pool = [item for label in classifier.labels for item in candidates_by_label[label][items_per_label:]]
    return _assembled_held_out_set(plan=plan, proof_id=proof_id, held_out_items=selected_items,
                                   teaching_items=teaching_pool, frozen_at=frozen_at,
                                   selection="balanced; editor-reviewed References ranked by sha256(proofId, lineageId)")


def _ranked_candidates_by_label(reviewed_references_with_labels, classifier, proof_id: str) -> dict[str, list[dict[str, Any]]]:
    candidates_by_label: dict[str, list[tuple[str, dict[str, Any]]]] = {label: [] for label in classifier.labels}
    for reference, label in reviewed_references_with_labels:
        if label not in candidates_by_label:
            continue
        item = reviewed_reference_item_without_the_editor_note(reference)
        candidates_by_label[label].append((held_out_selection_rank(proof_id, item.id),
                                           {"id": item.id, "label": label, "values": dict(item.values),
                                            "reviewedAt": str(reference.get("curationStatusUpdatedAt") or ""),
                                            "explanation": str(reference.get("curationStatusReason") or "").strip()}))
    return {label: [item for _, item in sorted(candidates, key=lambda pair: pair[0])]
            for label, candidates in candidates_by_label.items()}


def _assembled_held_out_set(*, plan, proof_id: str, held_out_items: Sequence[Mapping[str, Any]],
                            teaching_items: Sequence[Mapping[str, Any]], frozen_at: str | None,
                            selection: str) -> dict[str, Any]:
    classifier = plan.definition.classifiers[0]
    held_out_items = sorted(held_out_items, key=lambda item: held_out_selection_rank(proof_id, item["id"]))
    teaching_pool = sorted(teaching_items, key=lambda item: (item["reviewedAt"], held_out_selection_rank(proof_id, item["id"])))
    held_out_set = {
        "version": HELD_OUT_SET_VERSION,
        "proofId": proof_id,
        "cyclotronId": plan.definition.id,
        "classifierId": classifier.id,
        "question": classifier.question,
        "labels": list(classifier.labels),
        "positiveLabel": classifier.positive_label,
        "frozenAt": frozen_at or _now(),
        "selection": selection,
        "items": [{key: item[key] for key in ("id", "label", "values")} for item in held_out_items],
        "teachingPool": list(teaching_pool),
    }
    held_out_set["fingerprint"] = held_out_set_fingerprint(held_out_set)
    return held_out_set


def freeze_cross_validation_set(reviewed_references_with_labels: Sequence[tuple[Mapping[str, Any], str]], *, plan,
                                proof_id: str, fold_count: int = DEFAULT_FOLD_COUNT,
                                frozen_at: str | None = None) -> dict[str, Any]:
    """Every labeled review held out exactly once, in stratified folds, each with the other folds as its teaching pool."""
    classifier = plan.definition.classifiers[0]
    if fold_count < 2:
        raise ValueError("Cross-validation needs at least two folds.")
    candidates_by_label = _ranked_candidates_by_label(reviewed_references_with_labels, classifier, proof_id)
    shortfalls = {label: len(candidates) for label, candidates in candidates_by_label.items()
                  if len(candidates) < fold_count}
    if shortfalls:
        counts = ", ".join(f"{label}: {count}" for label, count in shortfalls.items())
        raise ValueError(f"{fold_count}-fold cross-validation needs at least {fold_count} reviewed references per "
                         f"label; only {counts} are available.")
    frozen_at = frozen_at or _now()
    fold_items: list[list[dict[str, Any]]] = [[] for _ in range(fold_count)]
    for label in classifier.labels:
        for position, item in enumerate(candidates_by_label[label]):
            fold_items[position % fold_count].append(item)
    folds = [_assembled_held_out_set(plan=plan, proof_id=f"{proof_id}/fold-{fold_number}",
                                     held_out_items=held_items,
                                     teaching_items=[item for other_number, other_items in enumerate(fold_items)
                                                     if other_number != fold_number for item in other_items],
                                     frozen_at=frozen_at,
                                     selection=f"stratified fold {fold_number + 1} of {fold_count}; position in "
                                               "sha256(proofId, lineageId) rank within each label, modulo the fold count")
             for fold_number, held_items in enumerate(fold_items)]
    cross_validation_set = {"version": CROSS_VALIDATION_SET_VERSION, "proofId": proof_id, "frozenAt": frozen_at,
                            "folds": folds}
    cross_validation_set["fingerprint"] = cross_validation_fingerprint(cross_validation_set)
    return cross_validation_set


def cross_validation_fingerprint(cross_validation_set: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json({"version": cross_validation_set["version"],
                                          "proofId": cross_validation_set["proofId"],
                                          "folds": [fold["fingerprint"] for fold in cross_validation_set["folds"]]}
                                         ).encode()).hexdigest()


def verify_cross_validation_set(cross_validation_set: Mapping[str, Any]) -> None:
    if cross_validation_set.get("version") != CROSS_VALIDATION_SET_VERSION:
        raise ValueError(f"The cross-validation set must be {CROSS_VALIDATION_SET_VERSION}.")
    for fold in cross_validation_set["folds"]:
        verify_held_out_set(fold)
    if cross_validation_fingerprint(cross_validation_set) != cross_validation_set.get("fingerprint"):
        raise ValueError("The cross-validation set changed after it was frozen; freeze a new set under a new proof id.")


def reviewed_reference_item_without_the_editor_note(reference: Mapping[str, Any]):
    """The operational projection of a reviewed Reference, without the review note that would leak its label."""
    from .relevance_sweep import reference_item

    return reference_item({**reference, "curationStatusReason": None})


def teaching_examples_from_reviews(held_out_set: Mapping[str, Any]) -> list[Any]:
    """The teaching pool as priming examples, in review order, each with the editor's note when there is one."""
    from decision_flywheel import Item, LabeledItem

    return [LabeledItem(Item(item["id"], item["values"]), item["label"],
                        context={"human_feedback": item["explanation"]} if item["explanation"] else {})
            for item in held_out_set["teachingPool"]]


def reviewed_references_with_editor_labels(client, steering_config: Mapping[str, Any], plan) -> list[tuple[dict, str]]:
    """Every current reviewed Reference of the canonical corpus that the scope-training rule labels."""
    from .ids import knowledge_corpus_id
    from .relevance_decisions import relevance_label_for_review
    from .relevance_sweep import REVIEWED_STATUSES, _current
    from .steering import require_corpus_config

    corpus = require_corpus_config(dict(steering_config), steering_config["canonicalTopicSet"]["corpusKey"],
                                   "canonicalTopicSet.corpusKey")
    corpus_id = knowledge_corpus_id(corpus)
    labels = plan.definition.classifiers[0].labels
    labeled_references = []
    for status in REVIEWED_STATUSES:
        for reference in _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}")):
            label = relevance_label_for_review(reference, labels=labels)
            if label is not None:
                labeled_references.append((reference, label))
    return labeled_references


def agreement_metrics(outcomes: Sequence[tuple[str, str]], *, positive_label: str) -> dict[str, Any]:
    """Agreement, precision and recall of (editor label, classifier label) pairs."""
    true_positives = sum(1 for editor, classifier in outcomes if editor == positive_label and classifier == positive_label)
    false_positives = sum(1 for editor, classifier in outcomes if editor != positive_label and classifier == positive_label)
    false_negatives = sum(1 for editor, classifier in outcomes if editor == positive_label and classifier != positive_label)
    true_negatives = len(outcomes) - true_positives - false_positives - false_negatives
    return {
        "decided": len(outcomes),
        "agreement": _ratio(true_positives + true_negatives, len(outcomes)),
        "precision": _ratio(true_positives, true_positives + false_positives),
        "recall": _ratio(true_positives, true_positives + false_negatives),
        "confusion": {"truePositives": true_positives, "falsePositives": false_positives,
                      "trueNegatives": true_negatives, "falseNegatives": false_negatives},
    }


def priming_examples_outside_held_out_set(priming_examples: Sequence[Any],
                                          held_out_set: Mapping[str, Any]) -> tuple[list[Any], int]:
    """The priming examples in acceptance order, minus any that match a held-out item by id or source URL."""
    held_out_ids = {item["id"] for item in held_out_set["items"]}
    held_out_sources = {item["values"].get("source_uri") for item in held_out_set["items"]} - {None}
    kept_examples = [example for example in priming_examples
                     if example.item.id not in held_out_ids
                     and example.item.values.get("source_uri") not in held_out_sources]
    return kept_examples, len(priming_examples) - len(kept_examples)


def run_priming_proof(held_out_set: Mapping[str, Any], *, plan, priming_examples: Sequence[Any], model,
                      label_schedule: Sequence[int] = DEFAULT_LABEL_SCHEDULE, publication: str,
                      priming_fingerprint: str | None = None, model_identity: str | None = None,
                      teaching_source: str = "accepted priming examples",
                      ran_at: str | None = None,
                      on_point: Callable[[dict[str, Any]], None] | None = None,
                      outcome_sink: list[tuple[int, list[tuple[str, str]]]] | None = None) -> dict[str, Any]:
    """Decide the held-out set once per scheduled N in a fresh store primed with the first N examples.

    When an outcome sink is given, each point also appends its label count and
    its (editor label, classifier label) pairs, for callers that need more than
    the binary agreement metrics.
    """
    from decision_flywheel import Cyclotron, Item

    from .relevance_sweep import _HeldLease

    verify_held_out_set(held_out_set)
    classifier = plan.definition.classifiers[0]
    if (held_out_set["cyclotronId"], held_out_set["classifierId"], held_out_set["question"],
            list(held_out_set["labels"])) != (plan.definition.id, classifier.id, classifier.question,
                                              list(classifier.labels)):
        raise ValueError("The held-out set was frozen for a different relevance cyclotron definition.")
    usable_examples, examples_overlapping_held_out = priming_examples_outside_held_out_set(priming_examples,
                                                                                           held_out_set)
    scheduled_label_counts = sorted({count for count in label_schedule if 0 <= count <= len(usable_examples)})
    if 0 not in scheduled_label_counts:
        scheduled_label_counts.insert(0, 0)
    held_out_items = [(Item(item["id"], item["values"]), item["label"]) for item in held_out_set["items"]]
    points = []
    for label_count in scheduled_label_counts:
        examples_in_context = list(usable_examples[:label_count])
        priming_options = {"priming_examples": {classifier.id: examples_in_context}} if examples_in_context else {}
        with tempfile.TemporaryDirectory() as scratch_store:
            with Cyclotron.open(Path(scratch_store) / "proof-store", plan.definition, model, None,
                                lease=_HeldLease(), max_requests=len(held_out_items) + 1, review_program=None,
                                seed_rubrics=plan.seed_rubrics, **priming_options) as cyclotron:
                outcomes = [(editor_label, asyncio.run(cyclotron.decide(item)).label)
                            for item, editor_label in held_out_items]
        point = {"labels": label_count,
                 "labelsByClass": {label: sum(1 for example in examples_in_context if example.label == label)
                                   for label in classifier.labels},
                 **agreement_metrics(outcomes, positive_label=classifier.positive_label)}
        points.append(point)
        if outcome_sink is not None:
            outcome_sink.append((label_count, list(outcomes)))
        if on_point:
            on_point(point)
    return {
        "version": PROOF_REPORT_VERSION,
        "proofId": held_out_set["proofId"],
        "publication": publication,
        "cyclotronId": plan.definition.id,
        "question": classifier.question,
        "labels": list(classifier.labels),
        "positiveLabel": classifier.positive_label,
        "decisionModel": model_identity or getattr(model, "model_identity", None),
        "ranAt": ran_at or _now(),
        "heldOut": {
            "size": len(held_out_items),
            "byLabel": {label: sum(1 for _, editor_label in held_out_items if editor_label == label)
                        for label in classifier.labels},
            "fingerprint": held_out_set["fingerprint"],
            "frozenAt": held_out_set["frozenAt"],
            "source": "References editors reviewed in the Newsroom, labeled by the scope-training rule",
        },
        "priming": {
            "acceptedExamples": len(priming_examples),
            "excludedBecauseInHeldOut": examples_overlapping_held_out,
            "fingerprint": priming_fingerprint,
            "source": teaching_source,
            "order": "reviews in review order, then priming examples in acceptance order",
        },
        "conditions": {
            "freshStorePerPoint": True,
            "rubric": "publication doctrine seed",
            "optimizer": False,
            "reviewProgram": False,
        },
        "points": points,
    }


def run_cross_validated_priming_proof(cross_validation_set: Mapping[str, Any], *, plan, model,
                                      label_schedule: Sequence[int] = DEFAULT_CROSS_VALIDATION_SCHEDULE,
                                      publication: str, model_identity: str | None = None,
                                      ran_at: str | None = None,
                                      on_point: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Run the proof once per fold on a schedule every fold can honor, then pool the folds' decisions per N."""
    verify_cross_validation_set(cross_validation_set)
    folds = cross_validation_set["folds"]
    smallest_teaching_pool = min(len(fold["teachingPool"]) for fold in folds)
    common_schedule = sorted({count for count in label_schedule if 0 <= count <= smallest_teaching_pool}
                             | {0, smallest_teaching_pool})
    fold_reports = [run_priming_proof(fold, plan=plan, priming_examples=teaching_examples_from_reviews(fold),
                                      model=model, label_schedule=common_schedule, publication=publication,
                                      model_identity=model_identity, ran_at=ran_at,
                                      teaching_source=TEACHING_SOURCES["reviews"])
                    for fold in folds]
    classifier = plan.definition.classifiers[0]
    points = []
    for point_number, label_count in enumerate(common_schedule):
        fold_points = [report["points"][point_number] for report in fold_reports]
        pooled_confusion = {key: sum(point["confusion"][key] for point in fold_points)
                            for key in fold_points[0]["confusion"]}
        pooled_outcomes = ([("positive", "positive")] * pooled_confusion["truePositives"]
                           + [("other", "positive")] * pooled_confusion["falsePositives"]
                           + [("other", "other")] * pooled_confusion["trueNegatives"]
                           + [("positive", "other")] * pooled_confusion["falseNegatives"])
        point = {"labels": label_count,
                 "labelsByClass": {label: round(sum(point["labelsByClass"][label] for point in fold_points)
                                                / len(fold_points)) for label in classifier.labels},
                 **agreement_metrics(pooled_outcomes, positive_label="positive")}
        points.append(point)
        if on_point:
            on_point(point)
    held_out_by_label = {label: sum(report["heldOut"]["byLabel"][label] for report in fold_reports)
                         for label in classifier.labels}
    return {
        **{key: fold_reports[0][key] for key in ("version", "publication", "cyclotronId", "question", "labels",
                                                  "positiveLabel", "decisionModel", "ranAt", "conditions")},
        "proofId": cross_validation_set["proofId"],
        "heldOut": {
            "size": sum(held_out_by_label.values()),
            "byLabel": held_out_by_label,
            "fingerprint": cross_validation_set["fingerprint"],
            "frozenAt": cross_validation_set["frozenAt"],
            "source": fold_reports[0]["heldOut"]["source"],
            "design": f"{len(folds)}-fold cross-validation: every reviewed Reference is held out exactly once, "
                      "taught only by reviews outside its own fold; folds are pooled at each N",
        },
        "priming": {**fold_reports[0]["priming"], "acceptedExamples": smallest_teaching_pool,
                    "order": "reviews in review order within each fold's teaching pool"},
        "points": points,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def references_freeze_priming_held_out(flags: list[str]) -> None:
    """papyrus references freeze-priming-held-out --proof-id <id> --output <held-out.json>
    [--size 40] [--config <steering.yml>] [--doctrine <doctrine.yml>]

    Reads reviewed References and writes a balanced held-out set. Makes no model
    call and writes nothing to Papyrus. Keep the file private: it holds source
    titles and URLs. Refuses to overwrite an existing file.
    """
    from .graphql_authoring import create_authoring_client
    from .newsroom_doctrine import load_publication_doctrine_seed
    from .options import parse_options
    from .relevance_cyclotron import build_relevance_cyclotron
    from .steering import require_steering_config

    options = parse_options(flags)
    if not isinstance(options.get("proof-id"), str) or not isinstance(options.get("output"), str):
        raise ValueError("references freeze-priming-held-out requires --proof-id <id> and --output <held-out.json>.")
    output_path = Path(options["output"])
    if output_path.exists():
        raise ValueError(f"{output_path} exists; a frozen held-out set is never regenerated. Use a new --proof-id.")
    steering_config = require_steering_config(options.get("config"))
    plan = build_relevance_cyclotron(steering_config, load_publication_doctrine_seed(options.get("doctrine"))["doctrine"])
    size = int(options["size"]) if isinstance(options.get("size"), str) else DEFAULT_HELD_OUT_SIZE
    client, _ = create_authoring_client()
    held_out_set = freeze_held_out_set(reviewed_references_with_editor_labels(client, steering_config, plan),
                                       plan=plan, proof_id=options["proof-id"], size=size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(held_out_set, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"references\tfreeze-priming-held-out\t{output_path}\t{len(held_out_set['items'])} items\t"
          f"{held_out_set['fingerprint']}")


TEACHING_SOURCES = {"reviews": "editor reviews of References", "catalog": "accepted priming examples",
                    "both": "editor reviews of References, then accepted priming examples"}


def references_prove_priming(flags: list[str]) -> None:
    """papyrus references prove-priming --held-out <held-out.json> --teach-from reviews|catalog|both
    --output <report.json> [--catalog <examples.sqlite3> --list-id <id> --classifiers '<json>']
    [--schedule 0,5,10,20,40] [--config <steering.yml>] [--doctrine <doctrine.yml>]

    ``reviews`` teaches from the frozen teaching pool; ``catalog`` from the
    accepted priming examples; ``both`` from reviews first. Calls the configured
    decision model once per held-out item per scheduled N (the key comes from
    the environment). Writes the aggregate report only.
    """
    from .newsroom_doctrine import load_publication_doctrine_seed
    from .options import parse_options
    from .relevance_cyclotron import build_relevance_cyclotron, decision_model_from_environment, decision_model_identity
    from .steering import require_steering_config

    options = parse_options(flags)
    teaching_source = options.get("teach-from")
    if teaching_source not in TEACHING_SOURCES:
        raise ValueError("references prove-priming requires --teach-from reviews, catalog or both.")
    required_options = ["held-out", "output"] + (["catalog", "list-id", "classifiers"] if teaching_source != "reviews" else [])
    missing_options = [name for name in required_options if not isinstance(options.get(name), str)]
    if missing_options:
        raise ValueError("references prove-priming requires " + ", ".join(f"--{name}" for name in missing_options) + ".")
    steering_config = require_steering_config(options.get("config"))
    plan = build_relevance_cyclotron(steering_config, load_publication_doctrine_seed(options.get("doctrine"))["doctrine"])
    held_out_set = json.loads(Path(options["held-out"]).read_text(encoding="utf-8"))
    verify_held_out_set(held_out_set)
    label_schedule = ([int(part) for part in options["schedule"].split(",")] if isinstance(options.get("schedule"), str)
                      else list(DEFAULT_LABEL_SCHEDULE))
    teaching_examples = teaching_examples_from_reviews(held_out_set) if teaching_source != "catalog" else []
    catalog_fingerprint = None
    if teaching_source != "reviews":
        catalog_examples, catalog_fingerprint = accepted_catalog_examples(options, plan)
        teaching_examples += catalog_examples

    def print_point(point: dict[str, Any]) -> None:
        print(f"references\tprove-priming\tlabels\t{point['labels']}\tagreement\t{point['agreement']}\t"
              f"precision\t{point['precision']}\trecall\t{point['recall']}")

    report = run_priming_proof(held_out_set, plan=plan, priming_examples=teaching_examples,
                               model=decision_model_from_environment(plan), label_schedule=label_schedule,
                               publication=steering_config["publication"]["name"],
                               priming_fingerprint=catalog_fingerprint, teaching_source=TEACHING_SOURCES[teaching_source],
                               model_identity=decision_model_identity(plan), on_point=print_point)
    Path(options["output"]).parent.mkdir(parents=True, exist_ok=True)
    Path(options["output"]).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"references\tprove-priming\t{options['output']}")


def references_freeze_priming_cross_validation(flags: list[str]) -> None:
    """papyrus references freeze-priming-cross-validation --proof-id <id> --output <folds.json>
    [--folds 5] [--config <steering.yml>] [--doctrine <doctrine.yml>]

    Reads reviewed References and writes stratified folds that hold every labeled
    review out exactly once. Makes no model call and writes nothing to Papyrus.
    Keep the file private. Refuses to overwrite an existing file.
    """
    from .graphql_authoring import create_authoring_client
    from .newsroom_doctrine import load_publication_doctrine_seed
    from .options import parse_options
    from .relevance_cyclotron import build_relevance_cyclotron
    from .steering import require_steering_config

    options = parse_options(flags)
    if not isinstance(options.get("proof-id"), str) or not isinstance(options.get("output"), str):
        raise ValueError("references freeze-priming-cross-validation requires --proof-id <id> and --output <folds.json>.")
    output_path = Path(options["output"])
    if output_path.exists():
        raise ValueError(f"{output_path} exists; a frozen set is never regenerated. Use a new --proof-id.")
    steering_config = require_steering_config(options.get("config"))
    plan = build_relevance_cyclotron(steering_config, load_publication_doctrine_seed(options.get("doctrine"))["doctrine"])
    fold_count = int(options["folds"]) if isinstance(options.get("folds"), str) else DEFAULT_FOLD_COUNT
    client, _ = create_authoring_client()
    cross_validation_set = freeze_cross_validation_set(reviewed_references_with_editor_labels(client, steering_config, plan),
                                                       plan=plan, proof_id=options["proof-id"], fold_count=fold_count)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(cross_validation_set, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"references\tfreeze-priming-cross-validation\t{output_path}\t"
          f"{sum(len(fold['items']) for fold in cross_validation_set['folds'])} items\t{cross_validation_set['fingerprint']}")


def references_prove_priming_cross_validated(flags: list[str]) -> None:
    """papyrus references prove-priming-cross-validated --folds-file <folds.json> --output <report.json>
    [--schedule 0,5,10] [--config <steering.yml>] [--doctrine <doctrine.yml>]

    Calls the configured decision model once per labeled review per scheduled N
    (the key comes from the environment). Writes the aggregate report only.
    """
    from .newsroom_doctrine import load_publication_doctrine_seed
    from .options import parse_options
    from .relevance_cyclotron import build_relevance_cyclotron, decision_model_from_environment, decision_model_identity
    from .steering import require_steering_config

    options = parse_options(flags)
    if not isinstance(options.get("folds-file"), str) or not isinstance(options.get("output"), str):
        raise ValueError("references prove-priming-cross-validated requires --folds-file <folds.json> and --output <report.json>.")
    steering_config = require_steering_config(options.get("config"))
    plan = build_relevance_cyclotron(steering_config, load_publication_doctrine_seed(options.get("doctrine"))["doctrine"])
    cross_validation_set = json.loads(Path(options["folds-file"]).read_text(encoding="utf-8"))
    label_schedule = ([int(part) for part in options["schedule"].split(",")] if isinstance(options.get("schedule"), str)
                      else list(DEFAULT_CROSS_VALIDATION_SCHEDULE))

    def print_point(point: dict[str, Any]) -> None:
        print(f"references\tprove-priming-cross-validated\tlabels\t{point['labels']}\tagreement\t{point['agreement']}\t"
              f"precision\t{point['precision']}\trecall\t{point['recall']}")

    report = run_cross_validated_priming_proof(cross_validation_set, plan=plan, model=decision_model_from_environment(plan),
                                               label_schedule=label_schedule,
                                               publication=steering_config["publication"]["name"],
                                               model_identity=decision_model_identity(plan), on_point=print_point)
    Path(options["output"]).parent.mkdir(parents=True, exist_ok=True)
    Path(options["output"]).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"references\tprove-priming-cross-validated\t{options['output']}")


def accepted_catalog_examples(options: Mapping[str, Any], plan) -> tuple[list[Any], str]:
    from decision_flywheel.priming import PrimingService
    from decision_flywheel.web_store import WebStore

    from .priming_bootstrap import AcceptedPrimingSnapshot

    priming_service = PrimingService(WebStore(options["catalog"]))
    try:
        snapshot = AcceptedPrimingSnapshot.capture(priming_service, list_id=options["list-id"],
                                                   classifiers=json.loads(options["classifiers"]),
                                                   definition=plan.definition)
    finally:
        priming_service.close()
    return list(snapshot.for_definition(plan.definition)[plan.definition.classifiers[0].id]), snapshot.fingerprint
