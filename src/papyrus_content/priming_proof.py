"""The priming proof: does the relevance classifier agree with editors more after N labels?

A proof has two fixed parts and one variable:

- The held-out set is a frozen, fingerprinted sample of References that editors
  already reviewed, labeled by the existing scope-training rule. It is balanced
  across the two labels, so a classifier that always answers one label scores
  50% agreement. It is frozen once per proof id and never regenerated.
- The conditions are fixed: the configured decision model, the publication
  doctrine as the only rubric, no optimizer and no review program.
- The variable is N, the number of accepted priming examples (pasted URLs an
  editor labeled publish or reject) the classifier sees as training context, in
  acceptance order.

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
                             "positiveLabel", "items")}
    return hashlib.sha256(canonical_json(fingerprinted_fields).encode()).hexdigest()


def verify_held_out_set(held_out_set: Mapping[str, Any]) -> None:
    if held_out_set.get("version") != HELD_OUT_SET_VERSION:
        raise ValueError(f"The held-out set must be {HELD_OUT_SET_VERSION}.")
    if held_out_set_fingerprint(held_out_set) != held_out_set.get("fingerprint"):
        raise ValueError("The held-out set changed after it was frozen; freeze a new set under a new proof id.")


def freeze_held_out_set(reviewed_references_with_labels: Sequence[tuple[Mapping[str, Any], str]], *, plan,
                        proof_id: str, size: int = DEFAULT_HELD_OUT_SIZE,
                        frozen_at: str | None = None) -> dict[str, Any]:
    """A balanced, deterministic held-out set from (reference, editor label) pairs."""
    from .relevance_sweep import reference_item

    classifier = plan.definition.classifiers[0]
    if size < 2 * MINIMUM_HELD_OUT_ITEMS_PER_LABEL or size % 2:
        raise ValueError(f"The held-out size must be an even number of at least {2 * MINIMUM_HELD_OUT_ITEMS_PER_LABEL}.")
    items_per_label = size // 2
    candidates_by_label: dict[str, list[tuple[str, dict[str, Any]]]] = {label: [] for label in classifier.labels}
    for reference, label in reviewed_references_with_labels:
        if label not in candidates_by_label:
            continue
        item = reference_item(reference)
        candidates_by_label[label].append((held_out_selection_rank(proof_id, item.id),
                                           {"id": item.id, "label": label, "values": dict(item.values)}))
    shortfalls = {label: len(candidates) for label, candidates in candidates_by_label.items()
                  if len(candidates) < items_per_label}
    if shortfalls:
        counts = ", ".join(f"{label}: {count}" for label, count in shortfalls.items())
        raise ValueError(f"A held-out set of {size} needs {items_per_label} reviewed references per label; "
                         f"only {counts} are available. Review more references or choose a smaller --size.")
    selected_items = [item for label in classifier.labels
                      for _, item in sorted(candidates_by_label[label], key=lambda pair: pair[0])[:items_per_label]]
    selected_items.sort(key=lambda item: held_out_selection_rank(proof_id, item["id"]))
    held_out_set = {
        "version": HELD_OUT_SET_VERSION,
        "proofId": proof_id,
        "cyclotronId": plan.definition.id,
        "classifierId": classifier.id,
        "question": classifier.question,
        "labels": list(classifier.labels),
        "positiveLabel": classifier.positive_label,
        "frozenAt": frozen_at or _now(),
        "selection": "balanced; editor-reviewed References ranked by sha256(proofId, lineageId)",
        "items": selected_items,
    }
    held_out_set["fingerprint"] = held_out_set_fingerprint(held_out_set)
    return held_out_set


def reviewed_references_with_editor_labels(client, steering_config: Mapping[str, Any], plan) -> list[tuple[dict, str]]:
    """Every current reviewed Reference of the canonical corpus that the scope-training rule labels."""
    from .ids import knowledge_corpus_id
    from .relevance_decisions import relevance_label_for_review
    from .relevance_sweep import REVIEWED_STATUSES, _curation_messages, _current
    from .steering import require_corpus_config

    corpus = require_corpus_config(dict(steering_config), steering_config["canonicalTopicSet"]["corpusKey"],
                                   "canonicalTopicSet.corpusKey")
    corpus_id = knowledge_corpus_id(corpus)
    labels = plan.definition.classifiers[0].labels
    labeled_references = []
    for status in REVIEWED_STATUSES:
        for reference in _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}")):
            label = relevance_label_for_review(reference, _curation_messages(client, reference["lineageId"]),
                                               labels=labels)
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
                      ran_at: str | None = None,
                      on_point: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Decide the held-out set once per scheduled N in a fresh store primed with the first N examples."""
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
            "order": "acceptance order",
        },
        "conditions": {
            "freshStorePerPoint": True,
            "rubric": "publication doctrine seed",
            "optimizer": False,
            "reviewProgram": False,
        },
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


def references_prove_priming(flags: list[str]) -> None:
    """papyrus references prove-priming --held-out <held-out.json> --catalog <examples.sqlite3>
    --list-id <id> --classifiers '<json>' --output <report.json> [--schedule 0,5,10,20,40]
    [--config <steering.yml>] [--doctrine <doctrine.yml>]

    Calls the configured decision model once per held-out item per scheduled N
    (the key comes from the environment). Writes the aggregate report only.
    """
    from decision_flywheel.priming import PrimingService
    from decision_flywheel.web_store import WebStore

    from .newsroom_doctrine import load_publication_doctrine_seed
    from .options import parse_options
    from .priming_bootstrap import AcceptedPrimingSnapshot
    from .relevance_cyclotron import build_relevance_cyclotron, decision_model_from_environment, decision_model_identity
    from .steering import require_steering_config

    options = parse_options(flags)
    required_options = ("held-out", "catalog", "list-id", "classifiers", "output")
    missing_options = [name for name in required_options if not isinstance(options.get(name), str)]
    if missing_options:
        raise ValueError("references prove-priming requires " + ", ".join(f"--{name}" for name in missing_options) + ".")
    steering_config = require_steering_config(options.get("config"))
    plan = build_relevance_cyclotron(steering_config, load_publication_doctrine_seed(options.get("doctrine"))["doctrine"])
    held_out_set = json.loads(Path(options["held-out"]).read_text(encoding="utf-8"))
    label_schedule = ([int(part) for part in options["schedule"].split(",")] if isinstance(options.get("schedule"), str)
                      else list(DEFAULT_LABEL_SCHEDULE))
    priming_service = PrimingService(WebStore(options["catalog"]))
    try:
        snapshot = AcceptedPrimingSnapshot.capture(priming_service, list_id=options["list-id"],
                                                   classifiers=json.loads(options["classifiers"]),
                                                   definition=plan.definition)
    finally:
        priming_service.close()
    priming_examples = snapshot.for_definition(plan.definition)[plan.definition.classifiers[0].id]

    def print_point(point: dict[str, Any]) -> None:
        print(f"references\tprove-priming\tlabels\t{point['labels']}\tagreement\t{point['agreement']}\t"
              f"precision\t{point['precision']}\trecall\t{point['recall']}")

    report = run_priming_proof(held_out_set, plan=plan, priming_examples=priming_examples,
                               model=decision_model_from_environment(plan), label_schedule=label_schedule,
                               publication=steering_config["publication"]["name"],
                               priming_fingerprint=snapshot.fingerprint,
                               model_identity=decision_model_identity(plan), on_point=print_point)
    Path(options["output"]).parent.mkdir(parents=True, exist_ok=True)
    Path(options["output"]).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"references\tprove-priming\t{options['output']}")
