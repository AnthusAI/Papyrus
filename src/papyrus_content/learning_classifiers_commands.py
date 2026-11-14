"""``papyrus cyclotron export-examples`` and ``papyrus cyclotron evaluate-promotion`` for the learning classifiers.

The central retraining path of PPY-c6aced has no periodic export for these classifiers yet, so the export is a command a retraining round
calls. ``export-examples`` writes the training split by default, so the held-out decisions are never trained on; ``evaluate-promotion`` takes
the trained version's probabilities for the held-out examples and records the promotion flag in the site Cyclotron's store directory.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

from .graphql_authoring import create_authoring_client
from .learning_classifiers import (DEFAULT_HELD_OUT_SHARE, LEARNING_CLASSIFIER_IDS, LINK_CLASSIFIER_ID, PACK_CLASSIFIER_ID, evaluate_link_fit,
                                   evaluate_pack_fit, example_rows, load_link_examples, load_pack_examples, record_evaluation,
                                   split_chronologically)
from .options import normalize_string, parse_options
from .priming_export import encode_lines

SPLITS = ("train", "held-out", "all")


def examples_of(client: Any, classifier_id: str, corpus_id: str) -> list:
    if classifier_id == LINK_CLASSIFIER_ID:
        return load_link_examples(client, corpus_id)
    return load_pack_examples(client, corpus_id)


def split_options(options: dict[str, Any]) -> float:
    share = options.get("held-out-share")
    return float(share) if isinstance(share, str) else DEFAULT_HELD_OUT_SHARE


def classifier_option(options: dict[str, Any], usage: str) -> str:
    classifier_id = normalize_string(options.get("classifier"))
    if classifier_id not in LEARNING_CLASSIFIER_IDS or not normalize_string(options.get("corpus-id")):
        raise ValueError(usage)
    return classifier_id


def cyclotron_export_examples(flags: list[str]) -> None:
    """papyrus cyclotron export-examples --classifier reference-link-fit|idea-pack-fit --corpus-id ID [--split train|held-out|all] [--held-out-share 0.3] [--out FILE]"""
    options = parse_options(flags)
    classifier_id = classifier_option(options, cyclotron_export_examples.__doc__ or "")
    split = normalize_string(options.get("split")) or "train"
    if split not in SPLITS:
        raise ValueError(f"--split is one of {', '.join(SPLITS)}.")
    client, _ = create_authoring_client()
    examples = examples_of(client, classifier_id, normalize_string(options.get("corpus-id")))
    train, held_out = split_chronologically(examples, split_options(options))
    chosen = {"train": train, "held-out": held_out, "all": examples}[split]
    text = encode_lines(example_rows(classifier_id, chosen))
    out = normalize_string(options.get("out"))
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    print(f"cyclotron\texport-examples\t{classifier_id}\t{split}\t{len(chosen)}\t{out or 'stdout'}", file=sys.stderr)


def read_probabilities(path: str) -> dict[str, float]:
    with open(path, encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    return {str(item["id"]): float(item["probability"]) for item in rows}


def cyclotron_evaluate_promotion(flags: list[str]) -> None:
    """papyrus cyclotron evaluate-promotion --classifier reference-link-fit|idea-pack-fit --corpus-id ID --predictions FILE --store DIR [--held-out-share 0.3]"""
    options = parse_options(flags)
    classifier_id = classifier_option(options, cyclotron_evaluate_promotion.__doc__ or "")
    predictions, store = normalize_string(options.get("predictions")), normalize_string(options.get("store"))
    if not predictions or not store:
        raise ValueError(cyclotron_evaluate_promotion.__doc__ or "")
    client, _ = create_authoring_client()
    examples = examples_of(client, classifier_id, normalize_string(options.get("corpus-id")))
    train, held_out = split_chronologically(examples, split_options(options))
    probabilities = read_probabilities(predictions)
    evaluation = (evaluate_link_fit(train, held_out, probabilities) if classifier_id == LINK_CLASSIFIER_ID
                  else evaluate_pack_fit(held_out, probabilities))
    record_evaluation(store, evaluation, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    print(json.dumps(evaluation.record(), sort_keys=True))
